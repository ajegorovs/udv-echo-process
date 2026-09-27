"""SA5's canonical NPZ effect container — the deterministic numeric codec of §3–§4.

``docs/dop3000/sa5-effect-artifact-schema-proposal.md`` (accepted v1) fixes the committed
``sa5-live-N-effects.npz`` at two layers, and this module is both of them and nothing else:

* **the schema** (§3) — for every effect, exactly ten members named
  ``<effect_id>__<suffix>.npy`` with a fixed little-endian dtype and a ``K``/``P`` shape,
  where ``K = knot_count`` and ``P = participant_count`` are published (mirrored in the JSON
  of §5); and
* **the byte rule** (§4) — a ``ZIP_STORED`` archive whose members are raw NPY v1.0 payloads,
  written in ascending lexicographic member-name order with the ZIP epoch as their timestamp
  and fixed attributes, so two runs over one dataset at one analysis revision produce
  byte-identical files.

The codec is a **container**: it moves arrays between typed records and canonical bytes. It
computes no reduction, reads no recording, knows no ``PassRef``, no contrast and no metric,
and performs no arithmetic of any kind — least of all across sittings. It also does not
import the engine: the closed state vocabularies are stated here as integers exactly as
§8 states them (with the backend enum each maps to named in the comment), so a writer, a
reader and a verifier can share the container without sharing the generator.

What is refused, and by which layer
-----------------------------------
A **writer** refuses a record that cannot be a §3 artifact: a wrong dtype, a shape that
disagrees with the record's own ``knot_count``/``participant_count``, a duplicate
``effect_id``, a non-finite number anywhere, knot depths that are not strictly increasing, a
mask or state code outside the closed table, or a placeholder/mask/sentinel combination that
would let a reader mistake "no measurement" for a measured ``0.0``. A **reader** refuses all
of that *and* the container-level drift a byte-reproduction test exists to catch: a member
that is compressed rather than stored, a timestamp or attribute that is not the fixed one, a
duplicate or out-of-order member, a member outside the closed ten suffixes, a payload whose
declared NPY version/dtype/shape/order is not the §3 one, an archive comment, a directory
entry, trailing bytes in a payload — and, as the last net under all of them, a container
whose bytes are not exactly what this module would have written for the arrays it read.

The invariants of §3.2 are checked per position, not per file:

* ``defined[i] == 1`` exactly where the effect ``state[i] == 0``, and every other position
  carries the finite placeholder ``0.0``;
* an **unaligned** read is exactly ``gate_index == -1``, ``depth == 0.0``, ``offset == 0.0``,
  ``value == 0.0``, mask ``0`` and state code ``6``, and the ``-1`` gate sentinel appears
  **only** there;
* an **aligned** read whose metric is undefined (codes ``1``–``5``) **retains** its actual
  nonnegative native gate index, depth and offset — only its value is the ``0.0`` placeholder
  — so "no measurement" never collapses into the unaligned case;
* every placeholder is finite, so ``allow_pickle=False`` reading is exact and no ``NaN`` or
  ``Inf`` is ever a stand-in for a missing number.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Mapping
from typing import NamedTuple

import numpy as np
from pydantic import model_validator

from udv_echo_process.models.base import ArrayModel, array_field

__all__ = [
    "EFFECT_STATE_CODES",
    "MEMBER_DTYPES",
    "MEMBER_SUFFIXES",
    "PARTICIPANT_STATE_CODES",
    "UNALIGNED_READ_CODE",
    "EffectArrays",
    "EffectShape",
    "NpzContainerError",
    "NpzSchemaError",
    "SparseSa5NpzError",
    "decode_effect_npz",
    "effect_member_names",
    "encode_effect_npz",
    "member_name",
]

#: The ten closed per-effect suffixes of §3, in ascending order (so the ten member names of
#: one effect are already in the order the container sorts them in).
MEMBER_SUFFIXES: tuple[str, ...] = (
    "defined",
    "effect",
    "knots_mm",
    "participant_defined",
    "participant_depth_mm",
    "participant_gate_index",
    "participant_offset_mm",
    "participant_state",
    "participant_value",
    "state",
)

#: The fixed little-endian dtype of each member — the byte order is part of the dtype, so a
#: big-endian host still produces the same bytes (§4 point 4).
MEMBER_DTYPES: Mapping[str, np.dtype] = {
    "knots_mm": np.dtype("<f8"),
    "effect": np.dtype("<f8"),
    "defined": np.dtype("<u1"),
    "state": np.dtype("<u1"),
    "participant_gate_index": np.dtype("<i4"),
    "participant_depth_mm": np.dtype("<f8"),
    "participant_offset_mm": np.dtype("<f8"),
    "participant_value": np.dtype("<f8"),
    "participant_defined": np.dtype("<u1"),
    "participant_state": np.dtype("<u1"),
}

#: Table A (§8): the effect state codes, matching ``sparse_sa5_effects.EffectState``.
EFFECT_STATE_CODES: Mapping[int, str] = {
    0: "defined",
    1: "undefined-operand",
    2: "undefined-alignment",
}

#: The read-level unaligned sentinel (§8 table B, code 6).
UNALIGNED_READ_CODE = 6

#: Table B (§8): the participant read state codes, matching
#: ``sparse_sa5_metrics.MetricState`` (0–5) plus the read-level sentinel (6).
PARTICIPANT_STATE_CODES: Mapping[int, str] = {
    0: "defined",
    1: "defined-zero-power",
    2: "refused-axis",
    3: "undefined-constant-trace",
    4: "undefined-not-supported",
    5: "undefined-no-estimate",
    6: "undefined-alignment",
}

#: The ZIP epoch every member timestamp is pinned to (§4 point 2).
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: ``0o600 << 16`` — specified explicitly so ``ZipFile``'s implicit default is not relied on.
EXTERNAL_ATTR = 0o600 << 16

#: The NPY format version every payload is written with (§4 point 4).
NPY_FORMAT_VERSION = (1, 0)

#: The member-name extension; a member is ``<effect_id>__<suffix>.npy``.
_MEMBER_EXTENSION = ".npy"

#: The join between the effect id and the suffix — the *last* one in a member name, because
#: an ``effect_id`` itself is ``<view>__<metric>__<contrast>`` and therefore already contains
#: double underscores.
_MEMBER_JOIN = "__"

#: The suffixes whose shape is ``(K,)``; every other member is ``(P, K)``.
_PER_KNOT_SUFFIXES: frozenset[str] = frozenset(
    {"knots_mm", "effect", "defined", "state"}
)

#: The rank §3 fixes for each member: the four per-knot members are 1-D, the six
#: per-participant members are 2-D.
_MEMBER_NDIM: Mapping[str, int] = {
    suffix: (1 if suffix in _PER_KNOT_SUFFIXES else 2) for suffix in MEMBER_SUFFIXES
}

#: The suffixes that carry a floating-point number and must therefore be finite.
_FLOAT_SUFFIXES: tuple[str, ...] = (
    "knots_mm",
    "effect",
    "participant_depth_mm",
    "participant_offset_mm",
    "participant_value",
)

#: The two declared metadata counts the JSON mirrors — real positive integers, never a
#: booleans or a float that could be coerced into a plausible ``K`` or ``P``.
_COUNT_FIELDS: tuple[str, str] = ("knot_count", "participant_count")


class SparseSa5NpzError(ValueError):
    """An effect container that cannot be written or read under the accepted v1 schema."""


class NpzSchemaError(SparseSa5NpzError):
    """The records (or the arrays a container carries) are not a §3 effect artifact."""


class NpzContainerError(SparseSa5NpzError):
    """The container bytes are not the canonical §4 ZIP of NPY members."""


class EffectShape(NamedTuple):
    """The two shape counts an effect publishes and the NPZ arrays are checked against."""

    knot_count: int
    participant_count: int


class EffectArrays(ArrayModel):
    """One effect's ten §3 arrays, with the ``K``/``P`` counts the JSON mirrors (§5.3).

    The record is an :class:`~udv_echo_process.models.base.ArrayModel`: frozen, so it cannot
    be re-bound after construction, and every array field is declared with
    :func:`~udv_echo_process.models.base.array_field`, so each is stored as an **owned**
    C-contiguous read-only copy that never shares memory with the caller's input — mutating
    the array a caller passed in cannot alter the record.

    ``knot_count`` and ``participant_count`` are *declared* metadata, not derived ones: the
    record is refused unless every array has exactly the shape the declaration implies, so a
    caller cannot publish one shape in the JSON and another in the NPZ. The array fields are
    named exactly as their member suffixes, so ``getattr(record, suffix)`` is the whole
    mapping, and there is no room for an eleventh member to creep in.

    The field dtype is the schema's fixed little-endian one, and the **byte order is part of
    it**: an array whose own dtype is not exactly ``MEMBER_DTYPES[suffix]`` — a big-endian or
    narrower array, say — is refused before ``array_field``'s helper could silently convert
    it, so a record can never hide a byte-order change the container would then re-emit.
    """

    effect_id: str
    knot_count: int
    participant_count: int
    knots_mm: array_field(MEMBER_DTYPES["knots_mm"], rank=_MEMBER_NDIM["knots_mm"])
    effect: array_field(MEMBER_DTYPES["effect"], rank=_MEMBER_NDIM["effect"])
    defined: array_field(MEMBER_DTYPES["defined"], rank=_MEMBER_NDIM["defined"])
    state: array_field(MEMBER_DTYPES["state"], rank=_MEMBER_NDIM["state"])
    participant_gate_index: array_field(
        MEMBER_DTYPES["participant_gate_index"],
        rank=_MEMBER_NDIM["participant_gate_index"],
    )
    participant_depth_mm: array_field(
        MEMBER_DTYPES["participant_depth_mm"],
        rank=_MEMBER_NDIM["participant_depth_mm"],
    )
    participant_offset_mm: array_field(
        MEMBER_DTYPES["participant_offset_mm"],
        rank=_MEMBER_NDIM["participant_offset_mm"],
    )
    participant_value: array_field(
        MEMBER_DTYPES["participant_value"],
        rank=_MEMBER_NDIM["participant_value"],
    )
    participant_defined: array_field(
        MEMBER_DTYPES["participant_defined"],
        rank=_MEMBER_NDIM["participant_defined"],
    )
    participant_state: array_field(
        MEMBER_DTYPES["participant_state"],
        rank=_MEMBER_NDIM["participant_state"],
    )

    @model_validator(mode="before")
    @classmethod
    def _enforce_exact_schema_types(cls, data: object) -> object:
        """Refuse a wrong input dtype or count before ``owned_array`` could convert it.

        ``array_field``'s shared helper converts with the field's declared dtype, which
        would *silently* re-order a big-endian array instead of rejecting it — the one way a
        record could carry a dtype the schema does not name and still round-trip. Running
        before the field validators, this checks the byte order a caller supplies rather
        than repairing it, and checks the two declared counts are genuine positive integers
        so a ``bool`` or a ``2.0`` is not coerced into a plausible ``K`` or ``P``.
        """
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        for name in _COUNT_FIELDS:
            if name not in payload:
                continue
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} is a positive integer, got {value!r}")
        for suffix in MEMBER_SUFFIXES:
            value = payload.get(suffix)
            if not isinstance(value, np.ndarray):
                continue
            dtype = MEMBER_DTYPES[suffix]
            if value.dtype != dtype:
                raise ValueError(
                    f"{suffix} must be {dtype.str} (the schema's fixed little-endian "
                    f"dtype), got {value.dtype.str}"
                )
        return payload

    @property
    def shape(self) -> EffectShape:
        """The declared counts, as the pair a JSON effect record publishes."""
        return EffectShape(self.knot_count, self.participant_count)

    def __eq__(self, other: object) -> bool:
        """Field-wise equality: the arrays by value and dtype, not by identity."""
        if not isinstance(other, EffectArrays):
            return NotImplemented
        if self.shape != other.shape or self.effect_id != other.effect_id:
            return False
        for suffix in MEMBER_SUFFIXES:
            mine = getattr(self, suffix)
            theirs = getattr(other, suffix)
            if mine.dtype != theirs.dtype or not np.array_equal(mine, theirs):
                return False
        return True


# ── names ───────────────────────────────────────────────────────────────


def member_name(effect_id: str, suffix: str) -> str:
    """Return the member name of one suffix of one effect: ``<effect_id>__<suffix>.npy``."""
    if suffix not in MEMBER_DTYPES:
        raise NpzSchemaError(
            f"{suffix!r} is not one of the ten closed member suffixes of the schema: "
            f"{list(MEMBER_SUFFIXES)}"
        )
    return f"{effect_id}{_MEMBER_JOIN}{suffix}{_MEMBER_EXTENSION}"


def effect_member_names(effect_id: str) -> tuple[str, ...]:
    """Return all ten member names of one effect, in ascending name order."""
    return tuple(sorted(member_name(effect_id, suffix) for suffix in MEMBER_SUFFIXES))


def _split_member_name(name: str) -> tuple[str, str]:
    """Split ``<effect_id>__<suffix>.npy`` into its effect id and closed suffix."""
    if not name.endswith(_MEMBER_EXTENSION):
        raise NpzContainerError(f"member {name!r} is not a .npy member")
    stem = name[: -len(_MEMBER_EXTENSION)]
    effect_id, separator, suffix = stem.rpartition(_MEMBER_JOIN)
    if not separator:
        raise NpzContainerError(f"member {name!r} is not '<effect_id>__<suffix>.npy'")
    if not effect_id:
        raise NpzContainerError(f"member {name!r} carries an empty effect id")
    if any(char in effect_id for char in ("/", "\\", "\x00")):
        raise NpzContainerError(
            f"member {name!r} is not a flat '<effect_id>__<suffix>.npy' name: its effect id "
            "carries a path separator or a NUL"
        )
    if suffix not in MEMBER_DTYPES:
        raise NpzContainerError(
            f"member {name!r} carries the suffix {suffix!r}, which is not one of the ten "
            f"closed suffixes of the schema: {list(MEMBER_SUFFIXES)}"
        )
    return effect_id, suffix


# ── validation (§3) ─────────────────────────────────────────────────────


def _check_effect(record: EffectArrays) -> None:
    """Refuse a record that is not a §3 effect: dtype, shape, counts, values and masks."""
    if not isinstance(record, EffectArrays):
        raise NpzSchemaError(
            f"an effect record is an EffectArrays, got {type(record).__name__}"
        )
    effect_id = record.effect_id
    if not isinstance(effect_id, str) or not effect_id:
        raise NpzSchemaError("every effect states its non-empty effect_id")
    if any(char in effect_id for char in ("/", "\\", "\x00")):
        raise NpzSchemaError(
            f"the effect id {effect_id!r} cannot name a ZIP member: it carries a path "
            "separator or a NUL"
        )

    counts = tuple((name, getattr(record, name)) for name in _COUNT_FIELDS)
    for name, value in counts:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise NpzSchemaError(
                f"effect {effect_id!r}: {name} is a positive integer, got {value!r}"
            )
    knot_count = record.knot_count
    participant_count = record.participant_count

    for suffix in MEMBER_SUFFIXES:
        array = getattr(record, suffix)
        dtype = MEMBER_DTYPES[suffix]
        if not isinstance(array, np.ndarray):
            raise NpzSchemaError(
                f"effect {effect_id!r}: {suffix} must be an ndarray, got "
                f"{type(array).__name__}"
            )
        if array.dtype != dtype:
            raise NpzSchemaError(
                f"effect {effect_id!r}: {suffix} must be {dtype.str} (the schema's fixed "
                f"little-endian dtype), got {array.dtype.str}"
            )
        expected = (
            (knot_count,)
            if suffix in _PER_KNOT_SUFFIXES
            else (participant_count, knot_count)
        )
        if array.shape != expected:
            raise NpzSchemaError(
                f"effect {effect_id!r}: {suffix} must have shape {expected} for "
                f"K={knot_count} and P={participant_count}, got {array.shape}"
            )

    for suffix in _FLOAT_SUFFIXES:
        if not bool(np.isfinite(getattr(record, suffix)).all()):
            raise NpzSchemaError(
                f"effect {effect_id!r}: {suffix} carries a non-finite number; every value "
                "and every placeholder is finite, never NaN or Inf"
            )
    if knot_count > 1 and not bool((np.diff(record.knots_mm) > 0.0).all()):
        raise NpzSchemaError(
            f"effect {effect_id!r}: knots_mm must be strictly increasing"
        )
    _check_effect_state(record)
    _check_participant_reads(record)


def _check_effect_state(record: EffectArrays) -> None:
    """Table A: one closed code per knot, the mask it implies, and the placeholder."""
    effect_id = record.effect_id
    codes = record.state
    out_of_table = sorted(
        {int(code) for code in codes.ravel()} - set(EFFECT_STATE_CODES)
    )
    if out_of_table:
        raise NpzSchemaError(
            f"effect {effect_id!r}: effect state code(s) {out_of_table} are outside table A "
            f"({sorted(EFFECT_STATE_CODES)}); a code the backend never produced is refused"
        )
    _check_binary_mask(effect_id, "defined", record.defined)
    if not bool(np.array_equal(record.defined == 1, codes == 0)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: the defined mask is 1 exactly where the effect state "
            "code is 0 (defined), and 0 at every other code"
        )
    undefined = codes != 0
    if bool(np.any(record.effect[undefined] != 0.0)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: an undefined effect knot carries the finite placeholder "
            "0.0; a number there would read as a measurement never taken"
        )


def _check_participant_reads(record: EffectArrays) -> None:
    """Table B: the closed codes, the masks, and the aligned/unaligned sentinel rule."""
    effect_id = record.effect_id
    codes = record.participant_state
    out_of_table = sorted(
        {int(code) for code in codes.ravel()} - set(PARTICIPANT_STATE_CODES)
    )
    if out_of_table:
        raise NpzSchemaError(
            f"effect {effect_id!r}: participant state code(s) {out_of_table} are outside "
            f"table B ({sorted(PARTICIPANT_STATE_CODES)}); a code the backend never "
            "produced is refused"
        )
    _check_binary_mask(effect_id, "participant_defined", record.participant_defined)
    if not bool(np.array_equal(record.participant_defined == 1, codes == 0)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: the participant defined mask is 1 exactly where the "
            "read state code is 0 (defined), and 0 at every other code"
        )

    unaligned = codes == UNALIGNED_READ_CODE
    aligned = ~unaligned
    gate_index = record.participant_gate_index
    if bool(np.any(gate_index[unaligned] != -1)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: an unaligned read carries the -1 gate sentinel"
        )
    if bool(np.any(gate_index[aligned] < 0)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: the -1 gate sentinel appears only at an unaligned read; "
            "an aligned read retains its actual nonnegative native gate index"
        )
    if bool(
        np.any(record.participant_depth_mm[unaligned] != 0.0)
        or np.any(record.participant_offset_mm[unaligned] != 0.0)
        or np.any(record.participant_value[unaligned] != 0.0)
    ):
        raise NpzSchemaError(
            f"effect {effect_id!r}: an unaligned read carries the 0.0 depth, offset and "
            "value placeholders"
        )
    undefined = codes != 0
    if bool(np.any(record.participant_value[undefined] != 0.0)):
        raise NpzSchemaError(
            f"effect {effect_id!r}: an aligned read whose metric is undefined carries the "
            "0.0 value placeholder and retains its gate index, depth and offset"
        )


def _check_binary_mask(effect_id: str, suffix: str, mask: np.ndarray) -> None:
    """Refuse a mask that is not exactly zero or one."""
    unusual = sorted({int(value) for value in mask.ravel()} - {0, 1})
    if unusual:
        raise NpzSchemaError(
            f"effect {effect_id!r}: {suffix} is a 0/1 mask, got {unusual}"
        )


# ── writing (§4) ────────────────────────────────────────────────────────


def encode_effect_npz(effects: Iterable[EffectArrays]) -> bytes:
    """Return the canonical §4 bytes of one sitting's effects container.

    Args:
        effects: one :class:`EffectArrays` per effect; the order is irrelevant, because the
            members are written in ascending lexicographic member-name order.

    Returns:
        The ``ZIP_STORED`` archive bytes: one stored NPY v1.0 member per suffix per effect,
        every member stamped with the ZIP epoch and the fixed attributes.

    Raises:
        NpzSchemaError: the sequence is empty, two effects share an ``effect_id``, or any
            record is not a §3 effect (dtype, shape, counts, finiteness, masks, states).
    """
    records = tuple(effects)
    if not records:
        raise NpzSchemaError("an effects container holds at least one effect")
    ordered: dict[str, EffectArrays] = {}
    for record in records:
        _check_effect(record)
        if record.effect_id in ordered:
            raise NpzSchemaError(
                f"the effect id {record.effect_id!r} appears twice; member names would "
                "duplicate"
            )
        ordered[record.effect_id] = record

    members: dict[str, bytes] = {}
    for effect_id, record in ordered.items():
        for suffix in MEMBER_SUFFIXES:
            members[member_name(effect_id, suffix)] = _npy_bytes(
                getattr(record, suffix)
            )

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as archive:
        for name in sorted(members):
            archive.writestr(_zip_info(name), members[name])
    return buffer.getvalue()


def _zip_info(name: str) -> zipfile.ZipInfo:
    """Return the one fixed member header every canonical member is written under (§4.2)."""
    info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = EXTERNAL_ATTR
    info.internal_attr = 0
    info.create_system = 0
    info.extra = b""
    info.comment = b""
    return info


def _npy_bytes(array: np.ndarray) -> bytes:
    """Serialize one owned array as NPY v1.0, C-order, never pickled (§4.4)."""
    buffer = io.BytesIO()
    np.lib.format.write_array(
        buffer,
        np.ascontiguousarray(array),
        version=NPY_FORMAT_VERSION,
        allow_pickle=False,
    )
    return buffer.getvalue()


# ── reading (§4) ────────────────────────────────────────────────────────


def decode_effect_npz(
    data: bytes,
    *,
    expected: Mapping[str, EffectShape | tuple[int, int]] | None = None,
) -> tuple[EffectArrays, ...]:
    """Read a canonical §4 container, refusing anything a writer could drift into.

    Args:
        data: the container's exact file bytes.
        expected: optionally, the effect id → ``(knot_count, participant_count)`` mapping
            the sibling JSON publishes (§5.3). When given, the container's effect set must
            equal it exactly and every array shape must agree with the declared counts, so
            the mirror between the JSON and the NPZ is checked rather than assumed.

    Returns:
        One :class:`EffectArrays` per effect, in ascending ``effect_id`` order, with
        read-only arrays.

    Raises:
        NpzContainerError: the bytes are not a ZIP, the archive carries a comment or a
            directory entry, a member is compressed, duplicated, out of order, outside the
            closed ten suffixes or stamped with anything but the fixed timestamp and
            attributes, a payload is not a stored NPY v1.0 array of the member's exact dtype
            and shape, or the container is not byte-for-byte what this module would write.
        NpzSchemaError: the arrays break a §3 invariant — an unusable state code, a mask
            that disagrees with its state, a non-finite number, a ``-1`` sentinel on an
            aligned read, or an unaligned read that is not the full sentinel tuple.
    """
    raw = _as_bytes(data)
    per_effect = _read_members(raw)
    records = tuple(
        _record(effect_id, members) for effect_id, members in sorted(per_effect.items())
    )
    for record in records:
        _check_effect(record)
    _check_expected(records, expected)
    if encode_effect_npz(records) != raw:
        raise NpzContainerError(
            "the container bytes are not the canonical §4 encoding of the effects they "
            "carry: a timestamp, attribute, member order, NPY header or container field has "
            "drifted from the fixed byte rule"
        )
    return records


def _as_bytes(data: object) -> bytes:
    """Return the container's exact bytes, or refuse a non-bytes input."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    raise NpzContainerError(
        f"a container is read from its bytes, got {type(data).__name__}"
    )


def _read_members(raw: bytes) -> dict[str, dict[str, np.ndarray]]:
    """Verify the container envelope and return every effect's suffix → array mapping."""
    if not raw:
        raise NpzContainerError("the container is empty")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise NpzContainerError(f"the bytes are not a ZIP archive: {exc}") from exc
    with archive:
        if archive.comment:
            raise NpzContainerError(
                "the archive carries a comment; the schema's container has none"
            )
        infos = archive.infolist()
        if not infos:
            raise NpzContainerError("the container carries no member")
        names = [info.filename for info in infos]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise NpzContainerError(
                f"member {duplicates[0]!r} appears more than once; the member set is closed "
                "and exact"
            )
        if names != sorted(names):
            raise NpzContainerError(
                "the members are not in ascending lexicographic name order; the central "
                "directory order is fixed by the schema"
            )
        per_effect: dict[str, dict[str, np.ndarray]] = {}
        for info in infos:
            _check_member_header(info)
            effect_id, suffix = _split_member_name(info.filename)
            try:
                payload = archive.read(info)
            except (
                zipfile.BadZipFile,
                RuntimeError,
                NotImplementedError,
                OSError,
            ) as exc:
                raise NpzContainerError(
                    f"member {info.filename!r} cannot be read: {exc}"
                ) from exc
            slots = per_effect.setdefault(effect_id, {})
            slots[suffix] = _load_member(info.filename, suffix, payload)
    for effect_id, slots in per_effect.items():
        missing = sorted(set(MEMBER_SUFFIXES) - set(slots))
        if missing:
            raise NpzContainerError(
                f"effect {effect_id!r} is missing member(s) {missing}; the ten suffixes are "
                "closed and exact"
            )
    return per_effect


def _check_member_header(info: zipfile.ZipInfo) -> None:
    """Refuse a member whose stored/attribute envelope is not the fixed §4.2 one."""
    name = info.filename
    if info.is_dir():
        raise NpzContainerError(
            f"member {name!r} is a directory entry; a canonical container has none"
        )
    if tuple(info.date_time) != ZIP_EPOCH:
        raise NpzContainerError(
            f"member {name!r} carries the timestamp {tuple(info.date_time)} rather than "
            f"the fixed ZIP epoch {ZIP_EPOCH}"
        )
    if info.compress_type != zipfile.ZIP_STORED:
        raise NpzContainerError(
            f"member {name!r} is compressed (method {info.compress_type}); every member is "
            "stored, never deflated"
        )
    if info.external_attr != EXTERNAL_ATTR:
        raise NpzContainerError(
            f"member {name!r} carries external_attr {info.external_attr:#o} rather than the "
            f"fixed {EXTERNAL_ATTR:#o}"
        )
    if info.internal_attr != 0:
        raise NpzContainerError(
            f"member {name!r} carries internal_attr {info.internal_attr:#o} rather than 0"
        )
    if info.create_system != 0:
        raise NpzContainerError(
            f"member {name!r} carries create_system {info.create_system} rather than 0"
        )
    if info.extra:
        raise NpzContainerError(
            f"member {name!r} carries {len(info.extra)} extra field byte(s); the schema has "
            "no extras"
        )
    if info.comment:
        raise NpzContainerError(
            f"member {name!r} carries a comment; the schema has none"
        )


def _load_member(name: str, suffix: str, payload: bytes) -> np.ndarray:
    """Load one payload as the member's exact NPY v1.0 array, or refuse it."""
    dtype = MEMBER_DTYPES[suffix]
    stream = io.BytesIO(payload)
    try:
        version = np.lib.format.read_magic(stream)
        if tuple(version) != NPY_FORMAT_VERSION:
            raise NpzContainerError(
                f"member {name!r} uses NPY format version {tuple(version)}; the schema "
                f"fixes {NPY_FORMAT_VERSION}"
            )
        shape, fortran_order, declared = np.lib.format.read_array_header_1_0(stream)
    except NpzContainerError:
        raise
    except (ValueError, EOFError, OSError) as exc:
        raise NpzContainerError(
            f"member {name!r} has an unreadable NPY header: {exc}"
        ) from exc
    declared = np.dtype(declared)
    if declared != dtype:
        raise NpzContainerError(
            f"member {name!r} declares dtype {declared.str} rather than the schema's "
            f"{dtype.str}"
        )
    if fortran_order:
        raise NpzContainerError(
            f"member {name!r} is Fortran-ordered; every member is C-contiguous"
        )
    offset = stream.tell()
    nbytes = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
    if len(payload) - offset != nbytes:
        raise NpzContainerError(
            f"member {name!r} carries {len(payload) - offset} array byte(s) for a declared "
            f"{nbytes}; the payload is exactly the header and its array"
        )
    array = np.frombuffer(
        payload, dtype=dtype, count=nbytes // dtype.itemsize, offset=offset
    )
    return array.reshape(shape)


def _record(effect_id: str, members: Mapping[str, np.ndarray]) -> EffectArrays:
    """Build one record from a decoded member mapping, reading K and P from the shapes."""
    knots = members["knots_mm"]
    if knots.ndim != _MEMBER_NDIM["knots_mm"]:
        raise NpzContainerError(
            f"member {member_name(effect_id, 'knots_mm')!r} must be (K,), got shape "
            f"{knots.shape}"
        )
    participant = members["participant_gate_index"]
    if participant.ndim != _MEMBER_NDIM["participant_gate_index"]:
        raise NpzContainerError(
            f"member {member_name(effect_id, 'participant_gate_index')!r} must be (P, K), "
            f"got shape {participant.shape}"
        )
    for suffix in MEMBER_SUFFIXES:
        array = members[suffix]
        if array.ndim != _MEMBER_NDIM[suffix]:
            raise NpzContainerError(
                f"member {member_name(effect_id, suffix)!r} has shape {array.shape}; the "
                f"schema fixes a {_MEMBER_NDIM[suffix]}-dimensional member"
            )
    return EffectArrays(
        effect_id=effect_id,
        knot_count=int(knots.shape[0]),
        participant_count=int(participant.shape[0]),
        **{suffix: members[suffix] for suffix in MEMBER_SUFFIXES},
    )


def _check_expected(
    records: tuple[EffectArrays, ...],
    expected: Mapping[str, EffectShape | tuple[int, int]] | None,
) -> None:
    """Check the container's effect set and shape counts against the published mirror."""
    if expected is None:
        return
    declared: dict[str, EffectShape] = {}
    for effect_id, shape in expected.items():
        if not isinstance(effect_id, str) or not isinstance(
            shape, (EffectShape, tuple)
        ):
            raise NpzSchemaError(
                "the expected mapping is effect id → (knot_count, participant_count)"
            )
        try:
            declared[effect_id] = EffectShape(int(shape[0]), int(shape[1]))
        except (TypeError, IndexError, ValueError) as exc:
            raise NpzSchemaError(
                f"the expected counts of {effect_id!r} are a (knot_count, "
                f"participant_count) pair, got {shape!r}"
            ) from exc
    found = {record.effect_id for record in records}
    unexpected = sorted(found - set(declared))
    if unexpected:
        raise NpzContainerError(
            f"the container carries effect(s) {unexpected} the published member list does "
            "not name"
        )
    absent = sorted(set(declared) - found)
    if absent:
        raise NpzContainerError(
            f"the container is missing effect(s) {absent} the published member list names"
        )
    for record in records:
        if record.shape != declared[record.effect_id]:
            raise NpzSchemaError(
                f"effect {record.effect_id!r} is K={record.shape.knot_count}, "
                f"P={record.shape.participant_count} in the container but "
                f"K={declared[record.effect_id].knot_count}, "
                f"P={declared[record.effect_id].participant_count} in the published shape "
                "contract"
            )
