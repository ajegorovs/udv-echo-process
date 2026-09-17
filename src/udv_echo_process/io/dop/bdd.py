"""DOP3000/3010 `.BDD` binary reader → `provenance.ArtifactBundle`.

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

Data emission: one ``ChannelArtifact`` per channel, with its own
overflow-corrected timestamps (seconds) and its own ``ChannelConfig``. Velocity
is decoded to **mm/s** (the ``.ADD`` ``mm/s`` convention); echo to
module-scale-reflected amplitude.

Gate depths are **calculated** from the per-channel operation parameters —
word 9 (``gate1``), word 10 (``resolution``), word 19 (``sound speed``), word 29
(``acquisition rate``, decoded from its packed 4-byte form) and word 46
(``hardware delay``) — using the reviewed DOPpy ``_calcDepth`` equation. On the
committed fixtures that vector reproduces the matching ``.ADD`` depth row to
``<= 0.005 mm`` (the ``.ADD`` row is the same vector rounded to 0.01 mm). The
file-stored ``depth`` pseudo-profile is retained **only** as a validation /
fallback input: it is quantised to 0.1 mm and differs from the calculated
vector by at most 0.05 mm on every committed fixture. The calculated vector is
canonical whenever it is decodable, the file vector is used only when the
calculation is not decodable, and a disagreement larger than
``_FILE_DEPTH_TOLERANCE_MM`` raises rather than silently choosing one.

Known, reviewed loss (Phase 9). The fixed header's ASCII version string (16
bytes) and 512-byte comment *are* decoded and then dropped: §6.6 pins
``ChannelArtifact`` at five fields and §6.7 pins ``Recording`` at five, so
neither can carry them (the legacy ``MultiplexedMeasurement`` had
``header``/``comment`` fields for exactly this). Recovering them would require a
model change that this rework deliberately did not make, so the reader drops
them **by design** rather than silently discarding an unmodelled field.

Acquisition topology (plan §6.7, §14). The reader sets ``AcquisitionMode`` from
*decoded* evidence only and never fabricates a round/visit index:

- The op-parameter multiplexer-enable bit (word 52, bit index 0 / value ``1``
  — the manual's 1-based "bit 1"; manual
  ``10-storing-and-reading-measures.md`` §"DOP3000 parameters table" row 52)
  is the decoded signal. When it is set for the used channels, multiplexed
  acquisition selected each channel's profiles one after another (manual §11
  "Using the multiplexer"), so the mode is ``SEQUENTIAL``; otherwise the
  non-multiplexed file proves no cross-channel mode, so it is ``UNKNOWN``.
  ``ROLLING`` is never emitted: roll-over is a runtime multiplexer option
  (manual §11.2), not a stored field, so the file cannot prove it.
- ``round_id`` / ``visit_id`` / ``profile_in_visit`` are **not** emitted and
  ``acquisition_order`` stays ``None``. The per-profile footer (manual §10.7
  points E–K) documents the 2-byte block number at ``meas_end - 8``, but the
  manual documents it only as a *block/sequence* number, never as a round or
  visit identity, and the plan forbids deriving round/visit from block order or
  from that word. Measured for the record: on ``data/4-sensor-velocity/
  200RPM.BDD`` the block word spans ``1..100`` (matching op word 53, "Nb blocks
  in multiplexer mode") with four contiguous profiles per channel per block
  (matching op word 51, "Nb profiles in block in multiplexer mode"), while on
  ``data/echo/200.BDD`` it is the constant ``1`` across 4181 blocks. **Missing
  format fact** (for a later phase): no field encodes round or visit identity,
  so those three index arrays stay ``None`` under the explicit-only rule.

The content SHA-256 is computed in bounded chunks and no absolute path is
stored anywhere in the returned models (``SourceAsset.file_name`` is a
basename).

Reconciliation of this map with an independent decoder (2026-09-17). A second,
independently written decoder of the same operation-parameter table — the
instrument-side session vendored into ``docs/dop3000/udop-automation.md`` §9,
pinned against a labelled UI point — was compared word by word against the
fields above. **No word decodes differently in value.** Three differences are
worth recording, because each could otherwise be mistaken for an error:

* Word 10 is the session's "0-based resolution rung index" and its law
  ``resolution_mm = (word 10 + 1) x c / 12000`` is numerically identical to this
  reader's ``c x (word 10 + 1) / (2 x rate)``, because every available file
  (committed fixtures and captures alike) packs word 29 as ``(0, 6, 12, 40)``,
  i.e. rate byte ``6`` → 6000 kHz. The rung law has no rate term at all; the two
  forms only diverge if a file ever packs a different rate byte, and such a file
  would trip the stored-depth validation below rather than decode silently.
* Word 2 (the session's "``Depth`` = first gate + gates x resolution") is the
  *UI's* integer window depth. It is not the last gate of the canonical axis —
  they differ by up to ~0.5 mm — so it is deliberately not decoded or used here;
  word 9 (first gate) and word 46 (hardware delay) carry the offset instead.
* Words 3 (velocity scale x100), 14 (emissions/profile), 27 (sampling-volume
  index), 42 (the session's *probable* ``Tgc [dB]``, which the manual's table
  calls "internal use") and 84 (skipped profiles) are verified by that session
  but stay undecoded: ``ChannelConfig`` has no field for them, or — for words 27
  and 42 — the field's identity is not settled (``udop-automation.md`` §10).
  Word 3 is redundant with word 15 for the Nyquist velocity this reader reports.
  TGC therefore comes from the manual's rows 23–25 (mode + start/end), not from
  word 42.

``tests/test_bdd_verified_map.py`` pins that map against the two committed
captures in ``data/dop3010-velocity/``.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import cast

import numpy as np

from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionMode,
    AcquisitionRef,
    ChannelArtifact,
    ChannelConfig,
    ChannelKey,
    MeasType,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.models.io import SourceFormat, SourceSpec
from udv_echo_process.models.recording import Recording
from udv_echo_process.provenance.models import (
    ArtifactBundle,
    ArtifactGraph,
    register_root_artifact,
)

# ── constants ──────────────────────────────────────────────────────────

MAGIC_BINUDOPV = b"BINUDOPV"
MAGIC_BINWDOPV = b"BINWDOPV"  # DOP2000 — unsupported

_OPER_BASE_OFFSET = 548
_OPER_BLOCK_BYTES = 1024  # 256 × int32
_MEAS_BASE_OFFSET = 31268
_TIME_OVERFLOW = 2**32 - 1  # ms/10 wraps, ≈ 4.97 days
_SEC_PER_TICK = 1e-4  # stored in ms/10

#: Maximum |calculated - file-stored| gate depth allowed before the reader
#: refuses to choose a vector. The file pseudo-profile is quantised to 0.1 mm,
#: so a correct calculation agrees to <= 0.05 mm; every committed fixture is
#: within 0.0497 mm, so 0.06 mm leaves one rounding step of head-room while
#: still catching a wrong acquisition-rate / sound-speed decode (orders of
#: magnitude larger).
_FILE_DEPTH_TOLERANCE_MM = 0.06

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
    # Word 52, whose bit labels in the manual §10.7 parameters table are
    # **1-based**: its "bit 1: if set multiplexer enables" is bit index 0 /
    # value 1, its "bit 2: if set UDV MD mode" is index 1 / value 2, its
    # "bits 4–13" (selected channels) are indices 3–12, and its "bits 15–31"
    # (first multiplexer channel) are indices 14+.
    "mux_flags": (52, "i"),
}

#: Op word 29 "acquisition rate": a packed 4-byte form, byte 0 is a byte *index*
#: and the byte at ``index + 1`` holds the rate in MHz (manual §10.7 parameters
#: table row 29: "0: acquisition rate 6 MHz, 1: 12 or 40 MHz"). Read as signed
#: bytes to mirror the source decoder; the source spelling of the name survives
#: only in decoder-internal code.
_ACQUISITION_RATE_WORD = 29

#: ``mux_flags`` bit that the manual documents as the multiplexer enable.
#: The manual numbers word 52's bits **1-based**, so its "bit 1" is the LSB —
#: bit index 0, value ``1``. Bit index 1 (value ``2``) is the manual's "bit 2:
#: if set UDV MD mode", a different flag. DOPpy agrees: its ``'4m0'`` flag is
#: the multiplexer (``multi``) while ``'4m1'`` is ``udvmd``. Reading ``1 << 1``
#: here would test the UDV MD flag instead; every committed multiplexer fixture
#: sets both bits (word 52 = ``0x261e03``), which is why the error was masked.
_MUX_ENABLE_BIT = 1 << 0

#: Bytes hashed per chunk when content-addressing a source file (plan §13).
_HASH_CHUNK_BYTES = 1 << 20

#: Descriptor (quantity + fixed unit) for each decoded measurement type.
_DESCRIPTOR_BY_MEAS_TYPE = {
    MeasType.ECHO: SignalDescriptor(
        quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module"
    ),
    MeasType.VELOCITY: SignalDescriptor(
        quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s"
    ),
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
    op: dict[str, object] = {
        name: buf.at(base + 4 * word, fmt) for name, (word, fmt) in _OP_PARAM.items()
    }
    # Word 29 is a packed 4-byte form, not a scalar, so it is read whole.
    op["aquisition_rate"] = struct.unpack(
        "<4b", buf.slice(base + 4 * _ACQUISITION_RATE_WORD, 4)
    )
    return op


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
    max_depth_mm = (
        float(np.max(depth_mm)) if depth_mm is not None and len(depth_mm) else None
    )
    return ChannelConfig(
        source_freq_khz=_num(op["emit_freq_khz"]),
        pulse_repetition_freq_hz=_prf_hz(op),
        burst_length=_int(op["burst_length"]),
        emit_power=_EMIT_POWER.get(op["emit_power"], None),
        sensitivity=_SENSITIVITY.get(op["sensitivity"], None),
        gate1_mm=gate1_mm,
        n_gates=_int(op["gate_n"]),
        resolution_mm=_resolution_mm(op),
        max_depth_mm=max_depth_mm,
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


def _acquisition_rate_khz(op: dict[str, object]) -> float | None:
    """Decode op word 29's packed acquisition rate (DOPpy's ``aquisitionRate``).

    Word 29 is four bytes: byte 0 is a byte *index* into the remaining bytes and
    the byte at ``index + 1`` holds the rate in MHz (manual §10.7 row 29). DOPpy
    then scales by ``1e3``, which is the value the depth equation is expressed
    in; we reproduce that decode exactly. ``None`` when the packed index is out
    of range or the word is absent.
    """
    raw = op.get("aquisition_rate")
    if not isinstance(raw, tuple) or len(raw) < 2:
        return None
    index = int(raw[0])
    if index < 0 or index + 1 >= len(raw):
        return None
    return float(raw[index + 1]) * 1e3


def _gate_step_mm(op: dict[str, object]) -> float | None:
    """Gate-to-gate pitch (mm): ``sound * (resolution + 1) / (2 * rate)``.

    This is the step of :func:`_calc_gate_depths_mm`; it is the quantity the
    matching ``.ADD`` depth row confirms (0.4567 mm echo / 1.095 mm velocity on
    the committed fixtures).
    """
    sound = _num(op.get("sound_speed_ms"))
    res = _int(op.get("resolution"))
    rate = _acquisition_rate_khz(op)
    if not sound or res is None or rate is None or rate <= 0:
        return None
    return sound * (res + 1) / (2.0 * rate)


def _resolution_mm(op: dict[str, object]) -> float | None:
    """Gate resolution in mm — one reviewed interpretation of word 10 + 29.

    Both this field and :func:`_calc_gate_depths_mm` now express the gate step
    through the decoded acquisition-rate word, so the config reports the same
    pitch the canonical depth axis uses. The legacy
    ``(n+1)*0.166e-6 * sound / 2 * 1e3`` form is a rounded statement of the same
    rate and is deliberately no longer used (it disagreed by ~0.4 %).
    """
    return _gate_step_mm(op)


def _prf_hz(op: dict[str, object]) -> float | None:
    """Pulse-repetition frequency in Hz.

    Op word 5 is documented as a *period* in µs ("PRF in μs", manual §10.7 row
    5) while the field is named ``pulse_repetition_freq_hz``, so it is inverted.
    """
    prf_us = _num(op.get("prf_us"))
    if not prf_us:
        return None
    return 1e6 / prf_us


def _calc_gate_depths_mm(op: dict[str, object]) -> np.ndarray | None:
    """Calculated gate depths (mm) from op words 9, 10, 19, 29 and 46.

    The reviewed DOPpy ``_calcDepth`` equation ``sound * (term1 - term2)`` with
    ``term1 = (gate1 + (resolution + 1) * (n - 1)) / (2 * rate)`` for gate
    numbers ``n = 1..gateN`` and ``term2 = hardwareDelay / 2e6``. ``None`` when
    any input is missing or degenerate so the caller can fall back to the
    file-stored pseudo-profile.
    """
    gate_n = _int(op.get("gate_n"))
    gate1 = _int(op.get("gate1"))
    res = _int(op.get("resolution"))
    hw_delay = _int(op.get("hardware_delay_ns"))
    sound = _num(op.get("sound_speed_ms"))
    rate = _acquisition_rate_khz(op)
    if not gate_n or gate_n <= 0 or not sound or rate is None or rate <= 0:
        return None
    if gate1 is None or res is None or hw_delay is None:
        return None
    gate_number = np.arange(1, gate_n + 1, dtype=np.float64)
    term1 = (gate1 + (res + 1) * (gate_number - 1)) / (2.0 * rate)
    term2 = hw_delay / 2e6
    return sound * (term1 - term2)


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


def _content_sha256(raw: bytes) -> str:
    """Return the lower-case hex SHA-256 of ``raw``, hashed in bounded chunks.

    The buffer is read through a :class:`memoryview` in ``_HASH_CHUNK_BYTES``
    slices so no extra full-size copy is made (plan §13). There is no
    incremental file-hashing helper elsewhere in the package to reuse:
    ``models._canonical.sha256_hex`` takes a whole buffer, so this wrapper
    provides the chunked variant the reader needs.
    """
    digest = hashlib.sha256()
    view = memoryview(raw)
    for start in range(0, len(view), _HASH_CHUNK_BYTES):
        digest.update(view[start : start + _HASH_CHUNK_BYTES])
    return digest.hexdigest()


def _multiplexer_enabled(mux_flags: tuple[int, ...]) -> bool:
    """Return True only when every used channel's mux-enable bit is set.

    ``mux_flags`` are the decoded op-parameter word 52 values of the channels
    that actually produced data. A mixed or absent configuration proves no
    multiplexed operation, so it is treated as disabled rather than guessed.
    The bit tested is bit index 0 (the manual's 1-based "bit 1"), not index 1,
    which is the UDV MD-mode flag.
    """
    if not mux_flags:
        return False
    return all(flag & _MUX_ENABLE_BIT for flag in mux_flags)


def _decode_acquisition_mode(multiplexed: bool) -> AcquisitionMode:
    """Map the decoded multiplexer-enable parameter to an ``AcquisitionMode``.

    Only the decoded multiplexer bit decides the mode; no channel/stream count
    participates (plan §6.7, §14). Multiplexed acquisition switches channels one
    after another (manual §11), which is ``SEQUENTIAL``. A non-multiplexed file
    and a roll-over file both stay ``UNKNOWN``: the former proves no
    cross-channel mode and the latter's roll-over is a runtime option the format
    does not store.
    """
    if multiplexed:
        return AcquisitionMode.SEQUENTIAL
    return AcquisitionMode.UNKNOWN


def _canonical_depth_mm(
    file_depth: np.ndarray | None,
    op: dict[str, object],
    file_name: str,
    channel: int,
) -> np.ndarray:
    """Choose the canonical gate-depth axis and validate it (plan Phase 1).

    Reviewed rule:

    * the **calculated** vector (words 9/10/19/29/46) is canonical whenever it
      is decodable;
    * the file-stored pseudo-profile is used **only** as a fallback when the
      calculation is not decodable, and as a validation reference otherwise;
    * when both are present with the same length and disagree by more than
      :data:`_FILE_DEPTH_TOLERANCE_MM`, that is an error — the reader raises
      rather than silently choosing one, because a large gap means the
      acquisition-rate / sound-speed decode is wrong for this file.
    """
    calc = _calc_gate_depths_mm(op)
    if calc is not None:
        if file_depth is not None and file_depth.shape == calc.shape:
            mismatch = float(np.max(np.abs(calc - file_depth)))
            if mismatch > _FILE_DEPTH_TOLERANCE_MM:
                raise ValueError(
                    f"channel {channel} of {file_name}: calculated gate depths "
                    f"differ from the stored depth pseudo-profile by "
                    f"{mismatch:.4g} mm (> {_FILE_DEPTH_TOLERANCE_MM} mm)"
                )
        return calc
    if file_depth is not None:
        return file_depth
    raise ValueError(
        f"channel {channel} of {file_name} has no decoded depth pseudo-profile "
        "and no decodable acquisition-rate parameters; the binary format "
        "guarantees one per channel"
    )


def read(path: Path) -> ArtifactBundle:
    """Parse a DOP3000/3010 ``.BDD`` file into a validated ``ArtifactBundle``.

    The graph registers every decoded channel artifact as a root artifact, so
    callers can process the bundle immediately without repairing provenance.
    Source identity is the file's content SHA-256 (no absolute path is stored);
    ``recording_id`` and every ``artifact_id`` are content-derived and
    deterministic. ``AcquisitionMode`` is decoded from the documented
    multiplexer parameter, and ``acquisition_order``/round/visit stay absent
    when the format proves no such field (see the module docstring).

    Args:
        path: the ``.BDD`` file to read.

    Returns:
        A validated :class:`~udv_echo_process.provenance.ArtifactBundle`.

    Raises:
        ValueError: the bytes are not a DOP3000 ``.BDD`` file, a used channel
            has neither a calculable nor a stored depth axis, the calculated
            and stored depth axes disagree beyond the validation tolerance, the
            gate axes disagree with the decoded values, or no channel data was
            decoded.
    """
    raw = path.read_bytes()
    if not sniff_bdd(raw):
        raise ValueError(f"not a DOP3000 .BDD file: {path.name}")

    buf = _Buffer(raw)
    # Known, reviewed loss (Phase 9, see the module docstring): the fixed header
    # (ASCII version + 512-byte comment) is decoded and then dropped because the
    # five-field §6.6/§6.7 models have no field to carry it.
    _version = _decode_str(buf.slice(0, 16))
    _comment = _decode_str(buf.slice(16, 16 + 512))

    op: dict[int, dict[str, object]] = {ch: _read_op(buf, ch) for ch in range(1, 11)}

    content_sha256 = _content_sha256(raw)
    asset_id = f"sha256:{content_sha256}"
    source_asset = SourceAsset(
        asset_id=asset_id,
        content_sha256=content_sha256,
        byte_size=len(raw),
        file_name=path.name,
        source=_DOP_SPEC,
    )
    recording_id = recording_id_for(asset_id)

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

    # ── build one source artifact per used channel ────────────────────
    streams: list[ChannelArtifact] = []
    used_channels: list[int] = []
    for ch in sorted(acc):
        a = acc[ch]
        if not (a.velo or a.echo):
            continue
        depth = _canonical_depth_mm(a.depth, op[ch], path.name, ch)
        time_s = _correct_time(np.array(a.time))
        if a.velo:
            values = np.vstack(a.velo)
            meas_type = MeasType.VELOCITY
        else:
            values = np.vstack(a.echo)
            meas_type = MeasType.ECHO
        if values.shape[1] != depth.shape[0]:
            raise ValueError(
                f"channel {ch} of {path.name} decoded {values.shape[1]} gates "
                f"but {depth.shape[0]} gate depths"
            )
        data = observed_signal(
            time_s,
            depth,
            values,
            acquisition=AcquisitionIndex(
                sample_id=np.arange(time_s.shape[0], dtype=np.int64),
                acquisition_time_s=time_s,
            ),
        )
        ref = AcquisitionRef(
            recording_id=recording_id,
            source_asset_id=asset_id,
            channel=ChannelKey(device_channel=ch),
        )
        streams.append(
            source_artifact(
                ref,
                _DESCRIPTOR_BY_MEAS_TYPE[meas_type],
                _build_config(op[ch], depth),
                data,
            )
        )
        used_channels.append(ch)

    if not streams:
        raise ValueError(f"{path.name} contains no decoded channel data")

    mux_flags = tuple(cast(int, op[ch]["mux_flags"]) for ch in used_channels)
    recording = Recording(
        recording_id=recording_id,
        source_asset=source_asset,
        acquisition_mode=_decode_acquisition_mode(_multiplexer_enabled(mux_flags)),
        streams=tuple(streams),
    )
    graph = ArtifactGraph()
    for stream in recording.streams:
        graph = register_root_artifact(graph, stream.artifact_id)
    return ArtifactBundle(recording=recording, graph=graph)
