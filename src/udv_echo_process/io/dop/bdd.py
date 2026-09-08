"""DOP3000/3010 `.BDD` binary reader → `models.MultiplexedMeasurement`.

Layout (hand-transcribed from the DOP3000-3010 User's Manual v6.0 rev 1 and
cross-checked against the sibling DOPpy reader on this repo's fixtures):

- **Fixed header**: `version` (16 bytes) + `comment` (512 bytes).
- **Per-channel operation-parameter blocks**: start at offset 548, 1024 bytes
  per channel (channel ``k`` at ``548 + (k-1)*1024``), a table of 256
  little-endian ``int32`` scalars; a field at op-param index ``w`` sits at
  byte offset ``4*w``. This is the *only* per-channel config source (PRF,
  gates, emit, sound speed, veloScale, module scale, Doppler angle, …).
- **Measurement blocks**: start at offset 31268. Each block is
  length-prefixed (``uint16 length``), contains nested *profile sub-blocks*
  (``uint16`` len + ``uint8`` type + packed payload), and ends with a fixed
  footer: ``timeStamp`` (ms/10, ``uint32``, overflow-corrected),
  ``triggerState``, ``block``, and ``channel`` at ``meas_end - 3``.

Data emission: one ``ChannelSeries`` per channel, with its own
overflow-corrected timestamps (seconds) and its own ``ChannelConfig``. Velocity
is decoded to **mm/s** (the ``.ADD`` ``mm/s`` convention); echo to
module-scale-reflected amplitude. Gate depths come from the per-channel
``depth`` profile when present.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from udv_echo_process.models import (
    ChannelConfig,
    ChannelSeries,
    MeasType,
    MultiplexedMeasurement,
)
from udv_echo_process.models.io import SourceFormat, SourceSpec

# ── constants ──────────────────────────────────────────────────────────

MAGIC_BINUDOPV = b"BINUDOPV"
MAGIC_BINWDOPV = b"BINWDOPV"  # DOP2000 — unsupported

_OPER_BASE_OFFSET = 548
_OPER_BLOCK_BYTES = 1024  # 256 × int32
_MEAS_BASE_OFFSET = 31268
_TIME_OVERFLOW = 2**32 - 1  # ms/10 wraps, ≈ 4.97 days
_SEC_PER_TICK = 1e-4  # stored in ms/10

# Per-channel op-param: name → (word index, struct fmt).
_OP_PARAM = {
    "emit_freq_khz": (0, "i"),
    "prf_us": (5, "i"),
    "emit_power": (7, "i"),
    "burst_length": (8, "i"),
    "gate1": (9, "i"),
    "resolution": (10, "i"),
    "gate_n": (13, "i"),
    "velo_scale": (15, "i"),
    "sensitivity": (18, "i"),
    "sound_speed_ms": (19, "i"),
    "doppler_angle_deg": (20, "i"),
    "module_scale": (21, "i"),
    "velo_offset": (22, "i"),
    "tgc_mode": (23, "i"),
    "tgc_start": (24, "i"),
    "tgc_end": (25, "i"),
    "hardware_delay_ns": (46, "i"),
    "trigger_delay_ms": (47, "i"),
}

_PROFILE_NAME = {0: "velo", 1: "echo", 2: "energy", 25: "depth"}
_PROFILE_FMT = {0: "b", 1: "B", 2: "b", 25: "h"}

_EMIT_POWER = {0: "low", 1: "medium", 2: "high"}
_SENSITIVITY = {20: "very low", 12: "low", 8: "medium", 4: "high", 2: "very high"}
_TGC_MODE = {0: "uniform", 1: "slope", 2: "auto", 3: "custom"}

_DOP_SPEC = SourceSpec(
    vendor="Signal Processing SA", device="DOP 3010", format=SourceFormat.BDD
)


def sniff_bdd(raw: bytes) -> bool:
    """Return True if bytes begin with the DOP3000/3010 magic."""
    if raw.startswith(MAGIC_BINWDOPV):
        raise ValueError("DOP2000 (.BDD) is not supported by this reader")
    return raw.startswith(MAGIC_BINUDOPV)


# public alias used by io/base dispatch
sniff = sniff_bdd


class _Buffer:
    """Thin struct reader over raw bytes."""

    __slots__ = ("raw",)

    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def at(self, offset: int, fmt: str):
        return struct.unpack(fmt, self.raw[offset : offset + struct.calcsize(fmt)])[0]

    def slice(self, offset: int, size: int) -> bytes:
        return self.raw[offset : offset + size]


def _decode_str(data: bytes) -> str:
    return (
        data.split(b"\x00", 1)[0].decode("cp1252", errors="replace").strip("\r\n\x00 ")
    )


def _read_op(buf: _Buffer, channel: int) -> dict[str, object]:
    """Read one channel's op-param block (256 words) into a dict."""
    base = _OPER_BASE_OFFSET + (channel - 1) * _OPER_BLOCK_BYTES
    return {
        name: buf.at(base + 4 * word, fmt) for name, (word, fmt) in _OP_PARAM.items()
    }


def _correct_time(t_raw: np.ndarray) -> np.ndarray:
    """Overflow-correct ms/10 timestamps and convert to seconds.

    Mirrors DOPpy: after a backward step (raw timestamp wrapped past 2**32-1),
    add one overflow period to every subsequent sample.
    """
    t = t_raw.astype(np.float64)
    if t.size > 1:
        t[1:] += np.cumsum(np.ediff1d(t) < 0) * _TIME_OVERFLOW
    return t * _SEC_PER_TICK


def _decode_velocity(counts: np.ndarray, op: dict[str, object]) -> np.ndarray:
    """Velocity counts → mm/s (DOPpy `_calcVelo`)."""
    d = counts.astype(float)
    vo = op["velo_offset"]
    d[d + vo > 127] -= 256
    d[d + vo < -128] += 256

    prf = op["prf_us"]
    velo_scale = op["velo_scale"]
    emit = op["emit_freq_khz"]
    sound = op["sound_speed_ms"]
    ang = op["doppler_angle_deg"]
    if not (prf and velo_scale and emit):
        return d
    f_doppler = d * velo_scale * 1e3 / (256 * np.pi * prf)
    velo_ms = f_doppler * sound / (2e3 * np.cos(np.deg2rad(ang)) * emit)
    return velo_ms * 1000.0  # m/s → mm/s


def _decode_echo(counts: np.ndarray, op: dict[str, object]) -> np.ndarray:
    scale = op["module_scale"] or 256
    return counts * scale / 255.0


def _build_config(op: dict[str, object], depth_mm: np.ndarray | None) -> ChannelConfig:
    tgc_start = (
        (op["tgc_start"] - 127.5) / 127.5 * 40
        if op.get("tgc_start") is not None
        else None
    )
    tgc_end = (
        (op["tgc_end"] - 127.5) / 127.5 * 40 if op.get("tgc_end") is not None else None
    )
    gate1_mm = float(depth_mm[0]) if depth_mm is not None and len(depth_mm) else None
    return ChannelConfig(
        source_freq_khz=_num(op["emit_freq_khz"]),
        pulse_repetition_freq_hz=_num(op["prf_us"]),
        burst_length=_int(op["burst_length"]),
        emit_power=_EMIT_POWER.get(op["emit_power"], None),
        sensitivity=_SENSITIVITY.get(op["sensitivity"], None),
        gate1_mm=gate1_mm,
        n_gates=_int(op["gate_n"]),
        resolution_mm=_resolution_mm(op),
        sound_speed_ms=_num(op["sound_speed_ms"]),
        doppler_angle_deg=_num(op["doppler_angle_deg"]),
        velo_max_ms=_velo_max_ms(op),
        module_scale=_int(op["module_scale"]),
        tgc_mode=_TGC_MODE.get(op["tgc_mode"], None),
        tgc_start_db=tgc_start,
        tgc_end_db=tgc_end,
        trigger_delay_ms=_num(op["trigger_delay_ms"]),
    )


def _num(v: object) -> float | None:
    return float(v) if v is not None else None


def _int(v: object) -> int | None:
    return int(v) if v is not None else None


def _resolution_mm(op: dict[str, object]) -> float | None:
    """Gate pitch in mm: ``(n+1)*0.166e-6 s * sound / 2 * 1e3``."""
    if op.get("resolution") is None or not op.get("sound_speed_ms"):
        return None
    res_time = (op["resolution"] + 1) * 0.166e-6
    return res_time * op["sound_speed_ms"] / 2.0 * 1e3


def _velo_max_ms(op: dict[str, object]) -> float | None:
    """Nyquist velocity (mm/s) = velocity at count 128."""
    if not (op.get("prf_us") and op.get("velo_scale") and op.get("emit_freq_khz")):
        return None
    prf, vs = op["prf_us"], op["velo_scale"]
    emit, sound, ang = (
        op["emit_freq_khz"],
        op["sound_speed_ms"],
        op["doppler_angle_deg"],
    )
    f_dop = 128.0 * vs * 1e3 / (256 * np.pi * prf)
    return f_dop * sound / (2e3 * np.cos(np.deg2rad(ang)) * emit) * 1000.0


class _Acc:
    """Per-channel accumulation during the block walk."""

    __slots__ = ("channel", "depth", "echo", "time", "velo")

    def __init__(self, channel: int) -> None:
        self.channel = channel
        self.time: list[int] = []
        self.velo: list[np.ndarray] = []
        self.echo: list[np.ndarray] = []
        self.depth: np.ndarray | None = None


def read(path: Path) -> MultiplexedMeasurement:
    """Parse a DOP3000/3010 ``.BDD`` file into a ``MultiplexedMeasurement``."""
    raw = path.read_bytes()
    if not sniff_bdd(raw):
        raise ValueError(f"not a DOP3000 .BDD file: {path}")

    buf = _Buffer(raw)
    version = _decode_str(buf.slice(0, 16))
    comment = _decode_str(buf.slice(16, 16 + 512))

    op: dict[int, dict[str, object]] = {ch: _read_op(buf, ch) for ch in range(1, 11)}

    # ── walk the measurement block chain ──────────────────────────────
    acc: dict[int, _Acc] = {}
    meas_start = _MEAS_BASE_OFFSET
    eof = len(raw)

    while meas_start + 4 <= eof:
        meas_len = buf.at(meas_start, "H")
        meas_end = meas_start + meas_len
        if meas_len == 0 or meas_end > eof:
            break

        channel = buf.at(meas_end - 3, "B")
        ts_raw = buf.at(meas_end - 12, "I")
        a = acc.setdefault(channel, _Acc(channel))

        # walk nested profile sub-blocks
        prof_start = meas_start + 2
        saw_signal = False
        while True:
            plen = buf.at(prof_start, "H")
            if plen == 0:
                break
            ptype = buf.at(prof_start + 2, "B")
            payload = buf.slice(prof_start + 3, plen)

            name = _PROFILE_NAME.get(ptype)
            if name == "depth":
                a.depth = np.frombuffer(payload, dtype=np.int16).astype(float) / 10.0
            elif name in ("velo", "echo"):
                dtype = np.uint8 if ptype == 1 else np.int8
                arr = np.frombuffer(payload, dtype=dtype).astype(float)
                if name == "velo":
                    a.velo.append(_decode_velocity(arr, op[channel]))
                else:
                    a.echo.append(_decode_echo(arr, op[channel]))
                saw_signal = True
            prof_start += plen + 3

        # A depth-only block is not a measurement timestep (matches DOPpy
        # `_scanFile`), so only record a time when actual signal was present.
        if saw_signal:
            a.time.append(ts_raw)
        meas_start = meas_end

    # ── build ChannelSeries per used channel ──────────────────────────
    series = []
    for ch in sorted(acc):
        a = acc[ch]
        if not (a.velo or a.echo):
            continue
        t = _correct_time(np.array(a.time))
        if a.velo:
            values = np.vstack(a.velo)
            meas_type = MeasType.VELOCITY
        else:
            values = np.vstack(a.echo)
            meas_type = MeasType.ECHO
        q = a.depth if a.depth is not None else []
        series.append(
            ChannelSeries(
                channel=ch,
                meas_type=meas_type,
                gate_depths_mm=list(q),
                time_s=t,
                values=values,
                config=_build_config(op[ch], q),
            )
        )

    return MultiplexedMeasurement(
        file_path=Path(path),
        source=_DOP_SPEC,
        header=version,
        comment=comment,
        channels=series,
    )
