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

Data emission: one ``ChannelArtifact`` per channel **and measured quantity**, with
its own overflow-corrected timestamps (seconds) and its own ``ChannelConfig``.
Velocity is decoded to **mm/s** (the ``.ADD`` ``mm/s`` convention); echo to
module-scale-reflected amplitude. A block that stores one profile of each
quantity — the instrument's two-plot velocity+echo display does exactly that —
yields two streams on the same channel, each carrying the block's own timestamp
so the two series stay row-aligned (plan §6.7 amendment).

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
  ``200RPM.BDD`` the block word spans ``1..100`` (matching op word 53, "Nb blocks
  in multiplexer mode") with four contiguous profiles per channel per block
  (matching op word 51, "Nb profiles in block in multiplexer mode"), while on
  ``data/echo/200.BDD`` it is the constant ``1`` across 4181 blocks. **Missing
  format fact**: no field encodes round or visit identity, so those three index
  arrays stay ``None`` under the explicit-only rule.

  What the reader *does* own is the raw **profile-container account**: :func:`read_with_containers`
  returns the same bundle plus a :class:`ProfileContainerEvidence` listing every
  measurement container's 0-based source ordinal, its stored vendor
  block/sequence word (``None`` when its own footer cannot yield one) and the
  profile rows of each quantity it holds, beside the **configured** op words
  51/53. That evidence lives beside the bundle, not inside it: §6.6/§6.7 pin the
  five-field artifact/recording models, and a per-row container id on
  ``AcquisitionIndex`` would move every content-derived artifact id and
  misdescribe a block/sequence number as a row index. It supports a stored
  container partition comparison; it is not a visit law. The evidence is
  **opt-in**: :func:`read` builds no evidence model, so a caller that only wants
  the bundle pays nothing and cannot fail on evidence-model strictness.

  The vendor words are reported as stored only. Op 53 ("Nb blocks in
  multiplexer mode") and op 51 ("Nb profiles in block in multiplexer mode") are
  *configured* counts, and the footer word is a block/sequence number: none of
  them is proof that a physical acquisition, round or visit happened.

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
* Word 2 is an integer window depth, and the committed sweep says which one: the window's
  *last* gate — ``first_gate + (gates - 1) x pitch``, rounded — in 40 of 40 files of
  ``data/mixer-sensitivity-analysis/4MHz/0500RPM/001``. The session's ``Depth``
  (``first gate + gates x resolution``) is one pitch beyond it: the two coincide inside the
  rounding at the fine rungs every earlier campaign used, and do not at a 1.85 or 2.96 mm
  rung. Word 2 is deliberately not decoded or used here, and word 9 and word 46 carry an
  offset instead.
* Words 3 (velocity scale x100), 14 (emissions/profile), 27 (sampling-volume
  index), 42 (the session's *probable* ``Tgc [dB]``, which the manual's table
  calls "internal use") and 84 (skipped profiles) are verified by that session.
  Words 14, 27 and 84 are decoded into ``ChannelConfig.emissions_per_profile``,
  ``ChannelConfig.sampling_volume_index`` and ``ChannelConfig.skipped_profiles``
  as the **stored integers** — word 27 is the instrument's option-list index,
  not a length, so ``sampling_volume_mm`` stays unset (the index → mm relation
  is medium- and burst-dependent and measured at one sound speed only). Words 3
  and 42 stay undecoded: word 3 is redundant with word 15 for the Nyquist
  velocity this reader reports, and word 42's identity is not settled
  (``udop-automation.md`` §10). TGC therefore comes from the manual's rows 23–25
  (mode + start/end), not from word 42.

``tests/test_bdd_verified_map.py`` pins that map against the two committed
captures in ``data/dop3010-velocity/``.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import cast

import numpy as np
from pydantic import Field

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
from udv_echo_process.models.base import ValueModel
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
    "emissions_per_profile": (14, "i"),
    "velo_scale": (15, "i"),
    "sensitivity": (18, "i"),
    "sound_speed_ms": (19, "i"),
    "doppler_angle_deg": (20, "i"),
    "module_scale": (21, "i"),
    "velo_offset": (22, "i"),
    "tgc_mode": (23, "i"),
    "tgc_start": (24, "i"),
    "tgc_end": (25, "i"),
    # Word 27 is the stored receiver-bandwidth-definition index (the legacy
    # field name is retained for compatibility). It does not encode the
    # effective longitudinal thickness displayed in the dialog: burst can
    # increase that thickness while this bandwidth definition remains fixed.
    # Publish the stored index and leave ``sampling_volume_mm`` unset.
    "sampling_volume_index": (27, "i"),
    "hardware_delay_ns": (46, "i"),
    "trigger_delay_ms": (47, "i"),
    # Word 52, whose bit labels in the manual §10.7 parameters table are
    # **1-based**: its "bit 1: if set multiplexer enables" is bit index 0 /
    # value 1, its "bit 2: if set UDV MD mode" is index 1 / value 2, its
    # "bits 4–13" (selected channels) are indices 3–12, and its "bits 15–31"
    # (first multiplexer channel) are indices 14+.
    "mux_flags": (52, "i"),
    # Word 84 "number of skipped profiles": verified by the independent session
    # (labelled ``Number of skipped profiles 0`` next to a greyed-out
    # ``Apply skip profile``) and published as the stored integer; the manual's
    # table does not carry it.
    "skipped_profiles": (84, "i"),
    # Manual rows 51 and 53, per channel: "Nb profiles in block in multiplexer
    # mode" and "Nb blocks in multiplexer mode". These are **configured**
    # values, kept in the container evidence as configuration only: they are
    # never compared with, or substituted for, the profile containers the file
    # actually stores (see ``ProfileContainerEvidence``). They are not part of
    # ``ChannelConfig``, so they cannot move any content-derived artifact id.
    "profiles_in_block_mux": (51, "i"),
    "blocks_in_mux": (53, "i"),
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

#: The measured quantities a single measurement block can carry, in the fixed
#: order streams are emitted. Stable order matters: a two-plot capture stores
#: velocity and echo in the *same* block, so stream order must not depend on the
#: order the profiles happen to appear in.
_SIGNAL_PROFILES = ("velo", "echo")
_MEAS_TYPE_BY_PROFILE = {"velo": MeasType.VELOCITY, "echo": MeasType.ECHO}

#: Quantity key published for each signal profile in the container evidence (the
#: same string the ``MpxStreamReport`` uses, taken from the shared descriptor).
#: Derived from :data:`_MEAS_TYPE_BY_PROFILE`, so the profile → quantity relation
#: keeps a single owner instead of a second parallel table.
_QUANTITY_BY_PROFILE = {
    name: _DESCRIPTOR_BY_MEAS_TYPE[meas_type].quantity.value
    for name, meas_type in _MEAS_TYPE_BY_PROFILE.items()
}

#: Bytes of the fixed measurement-container footer this reader parses. The
#: vendor block/sequence word sits at ``meas_end - 8`` (``uint16``, manual §10.7
#: points E–K); the channel at ``meas_end - 3`` and the timestamp at
#: ``meas_end - 12``.
_FOOTER_BYTES = 12

#: One source container's facts, collected during the walk only when evidence is
#: requested: ``(channel, source_ordinal, stored_sequence, rows_by_quantity,
#: has_depth_axis, note)``. A plain tuple keeps the opt-in path allocation-light.
_ContainerFact = tuple[int, int, int | None, tuple[tuple[str, int], ...], bool, str]


class ProfileContainerCount(ValueModel):
    """How many profile rows one stored container holds **for one quantity**.

    Keyed by quantity on purpose: a container that carries two payload kinds
    keeps two separate counts, and no count is summed across kinds. ``profiles``
    is a decoded row count, never a configured value.
    """

    quantity: str
    profiles: int = Field(ge=0)


class SourceProfileContainer(ValueModel):
    """One profile container as stored: its raw identity and its profile counts.

    ``source_ordinal`` is the container's 0-based position in the file's
    container chain (the source ordinal, not a renumbering of the decoded rows).
    ``stored_sequence`` is the raw ``uint16`` vendor block/sequence word at
    ``meas_end - 8`` kept exactly as stored — the manual documents it only as a
    **block/sequence number**, not as a round or visit identity and not as proof
    that a physical acquisition happened, so no visit law is derived from it
    here.

    The word is ``None`` when the container's own footer cannot supply it (a
    container shorter than the 12-byte footer, or a stored value of ``0``), and
    ``note`` then says why. A container whose identity is unknown still keeps its
    decoded profile counts: unresolved identity is reported as unknown, never as
    absent or as a boundary. ``channel`` keeps the raw word, including the
    invalid ``0``, so a malformed file is described instead of rejected.
    """

    channel: int = Field(ge=0)
    source_ordinal: int = Field(ge=0)
    stored_sequence: int | None = None
    has_depth_axis: bool = False
    profiles: tuple[ProfileContainerCount, ...] = ()
    note: str = ""


class ConfiguredContainerSetting(ValueModel):
    """The **configured** multiplexer container settings of one channel (op 51/53).

    Configuration, not observation: ``containers_in_mode`` is op word 53 ("Nb
    blocks in multiplexer mode") and ``profiles_per_container`` is op word 51
    ("Nb profiles in block in multiplexer mode") — the vendor's own block words,
    reported as the parameters state them. Neither is ever reported as the
    number of profile containers the file stores, and neither is used as a
    divisor or a substitute for a stored count. Both are ``None`` when the word
    is absent or non-positive.
    """

    channel: int = Field(gt=0)
    profiles_per_container: int | None = None
    containers_in_mode: int | None = None


class ProfileContainerEvidence(ValueModel):
    """Decoder-owned per-container evidence for one ``.BDD`` file.

    This is the reader's own account of the profile containers it walked, kept
    **beside** the ``ArtifactBundle`` rather than inside it: the pinned five-field
    ``ChannelArtifact``/``Recording`` models (plan §6.6/§6.7) cannot carry it, and
    adding a per-row id to ``AcquisitionIndex`` would both change every
    content-derived artifact id and misdescribe a block/sequence word as a row
    index. Nothing here changes a row id, a timestamp or a decoded value.

    Built only by :func:`read_with_containers`, from the same walk that produced
    the bundle. Evidence is factual only: it records which container each profile
    row came from and how many rows of each quantity that container held; it does
    not claim that a container is a visit, a round or a repeat, and it does not
    merge containers that reuse a block/sequence word.
    """

    file_sha256: str
    byte_size: int = Field(ge=0)
    containers_consumed: int = Field(ge=0)
    trailing_bytes: int = Field(ge=0)
    containers: tuple[SourceProfileContainer, ...] = ()
    configured: tuple[ConfiguredContainerSetting, ...] = ()

    def channel_containers(self, channel: int) -> tuple[SourceProfileContainer, ...]:
        """Every stored container of ``channel``, in source order."""
        return tuple(c for c in self.containers if c.channel == channel)

    def configured_for(self, channel: int) -> ConfiguredContainerSetting | None:
        """The channel's configured container settings, or ``None`` when not read."""
        for setting in self.configured:
            if setting.channel == channel:
                return setting
        return None


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
        emissions_per_profile=_int(op["emissions_per_profile"]),
        emit_power=_EMIT_POWER.get(op["emit_power"], None),
        sensitivity=_SENSITIVITY.get(op["sensitivity"], None),
        gate1_mm=gate1_mm,
        n_gates=_int(op["gate_n"]),
        resolution_mm=_resolution_mm(op),
        # the stored index only; ``sampling_volume_mm`` stays unset because no
        # reviewed index → mm conversion exists (see ``_OP_PARAM``)
        sampling_volume_index=_int(op["sampling_volume_index"]),
        max_depth_mm=max_depth_mm,
        sound_speed_ms=_num(op["sound_speed_ms"]),
        doppler_angle_deg=_num(op["doppler_angle_deg"]),
        velo_max_ms=_velo_max_ms(op),
        module_scale=_int(op["module_scale"]),
        tgc_mode=_TGC_MODE.get(op["tgc_mode"], None),
        tgc_start_db=tgc_start,
        tgc_end_db=tgc_end,
        trigger_delay_ms=_num(op["trigger_delay_ms"]),
        skipped_profiles=_int(op["skipped_profiles"]),
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
    """Per-channel accumulation during the block walk.

    Every measured quantity keeps its **own** rows, but the channel keeps **one**
    clock: :attr:`blocks` records each block's raw timestamp once, with the set of
    quantities that block carried. Unwrapping per quantity would let two series
    disagree by a full timestamp period at the 32-bit rollover whenever a quantity
    is missing from the blocks on one side of it, so the clock is unwrapped once
    per channel and each quantity picks out its own rows (review finding F1).
    """

    __slots__ = ("blocks", "channel", "depth", "series")

    def __init__(self, channel: int) -> None:
        self.channel = channel
        self.series: dict[str, list[np.ndarray]] = {
            name: [] for name in _SIGNAL_PROFILES
        }
        #: ``(raw timestamp, quantities present)`` per signal block, in file order.
        self.blocks: list[tuple[int, tuple[str, ...]]] = []
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
    return _walk_bdd(path, collect_containers=False)[0]


def read_with_containers(path: Path) -> tuple[ArtifactBundle, ProfileContainerEvidence]:
    """Read one ``.BDD`` file and its :class:`ProfileContainerEvidence` in one walk.

    The bundle is byte-for-byte the one :func:`read` returns — same rows, same
    content-derived ids, same timestamps — because both functions share this
    walk. The evidence is decoded from the same buffer in the same pass, so a
    caller comparing a declaration with stored containers cannot see evidence
    from different bytes than the values it reports.

    Args:
        path: the ``.BDD`` file to read.

    Returns:
        ``(bundle, evidence)``: the validated artifact bundle and the reader's
        own per-container account of the same bytes.

    Raises:
        ValueError: as :func:`read`.
    """
    bundle, evidence = _walk_bdd(path, collect_containers=True)
    assert evidence is not None  # requested above
    return bundle, evidence


def _walk_bdd(
    path: Path, *, collect_containers: bool
) -> tuple[ArtifactBundle, ProfileContainerEvidence | None]:
    """Walk the file once, building the bundle and (opt-in) the container evidence."""
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

    # ── walk the measurement container chain ──────────────────────────
    acc: dict[int, _Acc] = {}
    # Evidence is collected only when requested: a plain read allocates no
    # per-container record and parses no footer word beyond the rows it needs.
    facts: list[_ContainerFact] | None = [] if collect_containers else None
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

        if facts is not None:
            # The container's own vendor word, kept only when its footer lies
            # inside this container. A short container or a stored 0 leaves the
            # number unknown; the decoded counts below are still kept, because
            # unresolved identity is not an absent container.
            notes: list[str] = []
            if meas_len >= _FOOTER_BYTES:
                stored_sequence: int | None = buf.at(meas_end - 8, "H") or None
                if stored_sequence is None:
                    notes.append(
                        "the stored block/sequence word is 0 on this container; "
                        "its block identity is unknown"
                    )
            else:
                stored_sequence = None
                notes.append(
                    f"the measurement container is {meas_len} bytes, shorter "
                    f"than its {_FOOTER_BYTES}-byte footer; its block identity "
                    "is unknown"
                )
            if channel == 0:
                notes.append(
                    "the channel word is 0, which is not a valid channel; these "
                    "rows are attributed to no declared channel"
                )
        else:
            stored_sequence = None

        # walk nested profile sub-blocks
        prof_start = meas_start + 2
        # Profiles this container carried, in the order they appeared, plus
        # whether it stored the depth pseudo-profile: the depth flag feeds the
        # container evidence, ``present`` feeds both the evidence counts and the
        # channel's single clock.
        present: list[str] = []
        saw_depth = False
        while True:
            plen = buf.at(prof_start, "H")
            if plen == 0:
                break
            ptype = buf.at(prof_start + 2, "B")
            payload = buf.slice(prof_start + 3, plen)

            name = _PROFILE_NAME.get(ptype)
            if name == "depth":
                a.depth = np.frombuffer(payload, dtype=np.int16).astype(float) / 10.0
                saw_depth = True
            elif name in _SIGNAL_PROFILES:
                dtype = np.uint8 if ptype == 1 else np.int8
                arr = np.frombuffer(payload, dtype=dtype).astype(float)
                if name == "velo":
                    decoded = _decode_velocity(arr, op[channel])
                else:
                    decoded = _decode_echo(arr, op[channel])
                a.series[name].append(decoded)
                present.append(name)
            prof_start += plen + 3

        if facts is not None:
            # The container evidence is derived from the same ``present`` list the
            # clock uses, so a container's reported profile counts and the rows
            # appended for it cannot drift apart.
            facts.append(
                (
                    int(channel),
                    len(facts),
                    stored_sequence,
                    tuple(
                        (_QUANTITY_BY_PROFILE[name], present.count(name))
                        for name in _SIGNAL_PROFILES
                        if name in present
                    ),
                    saw_depth,
                    "; ".join(notes),
                )
            )

        # A depth-only block is not a measurement timestep (matches DOPpy
        # `_scanFile`), so it contributes no clock reading. A signal block records
        # its timestamp ONCE, together with the quantities it carried.
        if present:
            a.blocks.append((ts_raw, tuple(present)))

        meas_start = meas_end

    # ── build one source artifact per (channel, measured quantity) ────
    streams: list[ChannelArtifact] = []
    used_channels: list[int] = []
    for ch in sorted(acc):
        a = acc[ch]
        present = [name for name in _SIGNAL_PROFILES if a.series[name]]
        if not present:
            continue
        depth = _canonical_depth_mm(a.depth, op[ch], path.name, ch)
        # One unwrapped clock for the channel; each quantity takes its own rows, so
        # the velocity and echo series can never disagree about a shared block
        # (review finding F1).
        clock = _correct_time(np.array([raw_ts for raw_ts, _ in a.blocks]))
        for name in present:
            # A block that stored both profile types yields two streams on one
            # channel, not one: §6.6 keeps ChannelArtifact at five fields and a
            # channel is not a stream identity on its own (plan §6.7 amendment).
            rows = np.array(
                [index for index, (_, names) in enumerate(a.blocks) if name in names],
                dtype=np.int64,
            )
            if rows.shape[0] != len(a.series[name]):
                raise ValueError(
                    f"channel {ch} ({name}) of {path.name} decoded "
                    f"{len(a.series[name])} profiles but {rows.shape[0]} block "
                    "timestamps"
                )
            values = np.vstack(a.series[name])
            time_s = clock[rows]
            meas_type = _MEAS_TYPE_BY_PROFILE[name]
            if values.shape[1] != depth.shape[0]:
                raise ValueError(
                    f"channel {ch} ({name}) of {path.name} decoded "
                    f"{values.shape[1]} gates but {depth.shape[0]} gate depths"
                )
            data = observed_signal(
                time_s,
                depth,
                values,
                acquisition=AcquisitionIndex(
                    # sample_id is the source acquisition row this series row came
                    # from (plan §6.4), not its position in this series: a quantity
                    # that skips blocks keeps the gaps, so the same block carries
                    # the same id in every quantity of the channel (review F4).
                    sample_id=rows,
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
    bundle = ArtifactBundle(recording=recording, graph=graph)
    if facts is None:
        return bundle, None
    evidence = ProfileContainerEvidence(
        file_sha256=content_sha256,
        byte_size=len(raw),
        containers_consumed=len(facts),
        trailing_bytes=eof - meas_start,
        containers=tuple(
            SourceProfileContainer(
                channel=channel,
                source_ordinal=source_ordinal,
                stored_sequence=stored_sequence,
                has_depth_axis=has_depth_axis,
                profiles=tuple(
                    ProfileContainerCount(quantity=quantity, profiles=profiles)
                    for quantity, profiles in rows
                ),
                note=note,
            )
            for (
                channel,
                source_ordinal,
                stored_sequence,
                rows,
                has_depth_axis,
                note,
            ) in facts
        ),
        configured=tuple(
            ConfiguredContainerSetting(
                channel=ch,
                profiles_per_container=(
                    int(cast(int, op[ch]["profiles_in_block_mux"])) or None
                ),
                containers_in_mode=(int(cast(int, op[ch]["blocks_in_mux"])) or None),
            )
            for ch in sorted(acc)
            # The op table holds the ten device channels; a raw 0 (or any other
            # out-of-table word) has no configured setting to report and is kept in
            # ``containers`` as an unknown-channel container instead.
            if 1 <= ch <= 10
        ),
    )
    return bundle, evidence
