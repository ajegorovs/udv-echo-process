"""SA5's canonical cross-sitting NPZ container — the deterministic numeric codec of §3–§4.

``docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`` (the cross-sitting analogue of
the accepted v1 within-sitting contract) fixes the committed ``sa5-cross-sitting.npz`` at two
layers, and this module is both of them and nothing else:

* **the schema** (§3, §3.1) — for every **comparable** comparison, exactly five members named
  ``<effect_id>__<suffix>.npy`` with a fixed little-endian dtype and a ``(Kc,)`` shape: the
  comparison knot depths (``knots_mm``), the oriented difference ``D = E2 − E1``
  (``difference``), the common-defined mask (``defined``) and the two sides' effect state codes
  (``state1``, ``state2``). ``Kc`` is *not* a stored member: it is the array shape, and the
  JSON publishes ``comparison_knot_count = Kc`` (§5.3), so the shape is stated in two places
  and must agree exactly. A **non-comparable** comparison has no common comparison domain and
  contributes **zero** members (§3.1) — it is described entirely by its JSON record and its CSV
  row, and a ``(0,)`` member is refused rather than written; and
* **the byte rule** (§4) — a ``ZIP_STORED`` archive whose members are raw NPY v1.0 payloads,
  written in ascending lexicographic member-name order with the ZIP epoch as their timestamp
  and fixed attributes, so two runs over one dataset at one analysis revision produce
  byte-identical files.

The codec is a **container**: it moves arrays between typed records and canonical bytes. It
computes no reduction, reads no recording, knows no ``PassRef``, no contrast and no metric, and
performs no arithmetic of any kind — least of all ``E2 − E1``. The stored ``difference`` is the
backend's own IEEE-754 binary64 result, and this codec **preserves** it bit-for-bit: it neither
recomputes nor normalizes a signed zero (§9). The closed effect state table is stated once, in
:mod:`udv_echo_process.analysis.sparse_sa5_npz` (``EFFECT_STATE_CODES``, table A of §5.4, the
same three codes the cross backend mirrors), and is imported here so a writer, a reader and a
verifier share one table without sharing the generator.

What is refused, and by which layer
-----------------------------------
A **writer** refuses a record that cannot be a §3 artifact: a wrong dtype, a shape that
disagrees with the record's own ``comparison_knot_count``, a duplicate ``effect_id``, a
non-finite number anywhere, knot depths that are not strictly increasing, a mask or state code
outside the closed table, or a placeholder/mask/sentinel combination that would let a reader
mistake "no measurement" for a measured ``0.0``. A **reader** refuses all of that *and* the
container-level drift a byte-reproduction test exists to catch: a member that is compressed
rather than stored, a timestamp or attribute that is not the fixed one, a duplicate or
out-of-order member, a member outside the closed five suffixes, a ``(0,)`` member, a payload
whose declared NPY version/dtype/shape/order is not the §3 one, an archive comment, a directory
entry, trailing bytes in a payload — and, as the last net under all of them, a container whose
bytes are not exactly what this module would have written for the arrays it read.

The invariants of §3.3 are checked per position, not per file:

* ``defined[i] == 1`` **exactly** where ``state1[i] == 0`` *and* ``state2[i] == 0`` — the
  prespec §4's ``D = { k : defined2[k] = 1 and defined1[k] = 1 }`` — and ``0`` at every other
  position;
* every **undefined** position of ``difference`` carries the finite placeholder exactly
  ``+0.0``. A ``−0.0`` therefore occupies a **defined** position only (§9): the signed zero is
  preserved, never silently rewritten to ``+0.0``, but it can never masquerade as the
  placeholder;
* ``knots_mm`` is strictly increasing; every float is finite; every mask value is exactly ``0``
  or ``1``; every state code is a table A code;
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

from udv_echo_process.analysis.sparse_sa5_npz import EFFECT_STATE_CODES
from udv_echo_process.models.base import ArrayModel, array_field

__all__ = [
    "CROSS_MEMBER_DTYPES",
    "CROSS_MEMBER_SUFFIXES",
    "EFFECT_STATE_CODES",
    "CrossArrays",
    "CrossComparisonShape",
    "CrossNpzContainerError",
    "CrossNpzError",
    "CrossNpzSchemaError",
    "cross_member_name",
    "cross_member_names",
    "decode_cross_npz",
    "encode_cross_npz",
]

#: The five closed per-comparison suffixes of §3, in ascending order (so the five member names
#: of one comparison are already in the order the container sorts them in). There is no sixth:
#: the two oriented effect profiles ``E1``/``E2`` are **not** re-published here (§3.2) — their
#: single home is each side's own ``sa5-live-N-effects.npz``.
CROSS_MEMBER_SUFFIXES: tuple[str, ...] = (
    "defined",
    "difference",
    "knots_mm",
    "state1",
    "state2",
)

#: The fixed little-endian dtype of each member — the byte order is part of the dtype, so a
#: big-endian host still produces the same bytes (§4 point 4). Only these two dtypes occur.
CROSS_MEMBER_DTYPES: Mapping[str, np.dtype] = {
    "knots_mm": np.dtype("<f8"),
    "difference": np.dtype("<f8"),
    "defined": np.dtype("<u1"),
    "state1": np.dtype("<u1"),
    "state2": np.dtype("<u1"),
}

#: The ZIP epoch every member timestamp is pinned to (§4 point 2).
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: ``0o600 << 16`` — specified explicitly so ``ZipFile``'s implicit default is not relied on.
EXTERNAL_ATTR = 0o600 << 16

#: The NPY format version every payload is written with (§4 point 4).
NPY_FORMAT_VERSION = (1, 0)

#: The member-name extension; a member is ``<effect_id>__<suffix>.npy``.
_MEMBER_EXTENSION = ".npy"

#: The join between the effect id and the suffix — the *last* one in a member name, because an
#: ``effect_id`` itself is ``<view>__<metric>__<contrast>`` and already contains double
#: underscores.
_MEMBER_JOIN = "__"

#: Every §3 member of a comparison is 1-D over its ``Kc`` comparison knots.
_MEMBER_RANK = 1

#: The suffixes that carry a floating-point number and must therefore be finite.
_FLOAT_SUFFIXES: tuple[str, ...] = ("knots_mm", "difference")

#: The one declared metadata count the JSON mirrors (§5.3) and the arrays are checked against —
#: a real positive integer, never a boolean or a float that could be coerced into a plausible
#: ``Kc``.
_COUNT_FIELD = "comparison_knot_count"


class CrossNpzError(ValueError):
    """A cross-sitting container that cannot be written or read under the v1 schema."""


class CrossNpzSchemaError(CrossNpzError):
    """The records (or the arrays a container carries) are not a §3 comparison artifact."""


class CrossNpzContainerError(CrossNpzError):
    """The container bytes are not the canonical §4 ZIP of NPY members."""


class CrossComparisonShape(NamedTuple):
    """The one shape count a comparison publishes and the NPZ arrays are checked against."""

    comparison_knot_count: int


class CrossArrays(ArrayModel):
    """One comparable comparison's five §3 arrays, with the ``Kc`` count the JSON mirrors (§5.3).

    The record is an :class:`~udv_echo_process.models.base.ArrayModel`: frozen, so it cannot be
    re-bound after construction, and every array field is declared with
    :func:`~udv_echo_process.models.base.array_field`, so each is stored as an **owned**
    C-contiguous read-only copy that never shares memory with the caller's input — mutating the
    array a caller passed in cannot alter the record.

    ``comparison_knot_count`` is *declared* metadata, not a derived one. The constructor itself
    checks only the two things a caller supplies directly: every array's dtype — the byte order
    is part of it — and that the count is a genuine positive integer. It does **not** re-check
    the arrays' shapes against that count: shape agreement is the §3 check
    :func:`_check_comparison` performs, at encode and again at decode, where a record is refused
    unless every array has exactly the shape the declaration implies. The effect is that a
    caller cannot publish one shape in the JSON and another in the NPZ. The array fields are
    named exactly as their member suffixes, so ``getattr(record, suffix)`` is the whole mapping,
    and there is no room for a sixth member to creep in.

    The field dtype is the schema's fixed little-endian one, and the **byte order is part of
    it**: an array whose own dtype is not exactly ``CROSS_MEMBER_DTYPES[suffix]`` — a big-endian
    or narrower array, say — is refused before ``array_field``'s helper could silently convert
    it, so a record can never hide a byte-order change the container would then re-emit.
    """

    effect_id: str
    comparison_knot_count: int
    knots_mm: array_field(CROSS_MEMBER_DTYPES["knots_mm"], rank=_MEMBER_RANK)
    difference: array_field(CROSS_MEMBER_DTYPES["difference"], rank=_MEMBER_RANK)
    defined: array_field(CROSS_MEMBER_DTYPES["defined"], rank=_MEMBER_RANK)
    state1: array_field(CROSS_MEMBER_DTYPES["state1"], rank=_MEMBER_RANK)
    state2: array_field(CROSS_MEMBER_DTYPES["state2"], rank=_MEMBER_RANK)

    @model_validator(mode="before")
    @classmethod
    def _enforce_exact_schema_types(cls, data: object) -> object:
        """Refuse a wrong input dtype or count before ``owned_array`` could convert it.

        ``array_field``'s shared helper converts with the field's declared dtype, which would
        *silently* re-order a big-endian array instead of rejecting it — the one way a record
        could carry a dtype the schema does not name and still round-trip. Running before the
        field validators, this checks the byte order a caller supplies rather than repairing it,
        and checks the declared count is a genuine positive integer so a ``bool`` or a ``2.0``
        is not coerced into a plausible ``Kc``.
        """
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        count = payload.get(_COUNT_FIELD)
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 1
        ):
            raise ValueError(f"{_COUNT_FIELD} is a positive integer, got {count!r}")
        for suffix in CROSS_MEMBER_SUFFIXES:
            value = payload.get(suffix)
            if not isinstance(value, np.ndarray):
                continue
            dtype = CROSS_MEMBER_DTYPES[suffix]
            if value.dtype != dtype:
                raise ValueError(
                    f"{suffix} must be {dtype.str} (the schema's fixed little-endian "
                    f"dtype), got {value.dtype.str}"
                )
        return payload

    @property
    def shape(self) -> CrossComparisonShape:
        """The declared count, as the pair the JSON's ``comparison_knot_count`` publishes."""
        return CrossComparisonShape(self.comparison_knot_count)

    def __eq__(self, other: object) -> bool:
        """Field-wise equality: the arrays by value and dtype, not by identity."""
        if not isinstance(other, CrossArrays):
            return NotImplemented
        if self.shape != other.shape or self.effect_id != other.effect_id:
            return False
        for suffix in CROSS_MEMBER_SUFFIXES:
            mine = getattr(self, suffix)
            theirs = getattr(other, suffix)
            if mine.dtype != theirs.dtype or not np.array_equal(mine, theirs):
                return False
        return True


# ── names ───────────────────────────────────────────────────────────────


def cross_member_name(effect_id: str, suffix: str) -> str:
    """Return the member name of one suffix of one comparison: ``<effect_id>__<suffix>.npy``."""
    if suffix not in CROSS_MEMBER_DTYPES:
        raise CrossNpzSchemaError(
            f"{suffix!r} is not one of the five closed member suffixes of the schema: "
            f"{list(CROSS_MEMBER_SUFFIXES)}"
        )
    return f"{effect_id}{_MEMBER_JOIN}{suffix}{_MEMBER_EXTENSION}"


def cross_member_names(effect_id: str) -> tuple[str, ...]:
    """Return all five member names of one comparable comparison, in ascending name order."""
    return tuple(
        sorted(cross_member_name(effect_id, suffix) for suffix in CROSS_MEMBER_SUFFIXES)
    )


def _split_member_name(name: str) -> tuple[str, str]:
    """Split ``<effect_id>__<suffix>.npy`` into its effect id and closed suffix."""
    if not name.endswith(_MEMBER_EXTENSION):
        raise CrossNpzContainerError(f"member {name!r} is not a .npy member")
    stem = name[: -len(_MEMBER_EXTENSION)]
    effect_id, separator, suffix = stem.rpartition(_MEMBER_JOIN)
    if not separator:
        raise CrossNpzContainerError(
            f"member {name!r} is not '<effect_id>__<suffix>.npy'"
        )
    if not effect_id:
        raise CrossNpzContainerError(f"member {name!r} carries an empty effect id")
    if any(char in effect_id for char in ("/", "\\", "\x00")):
        raise CrossNpzContainerError(
            f"member {name!r} is not a flat '<effect_id>__<suffix>.npy' name: its effect id "
            "carries a path separator or a NUL"
        )
    if suffix not in CROSS_MEMBER_DTYPES:
        raise CrossNpzContainerError(
            f"member {name!r} carries the suffix {suffix!r}, which is not one of the five "
            f"closed suffixes of the schema: {list(CROSS_MEMBER_SUFFIXES)}"
        )
    return effect_id, suffix


# ── validation (§3) ─────────────────────────────────────────────────────


def _check_comparison(record: CrossArrays) -> None:
    """Refuse a record that is not a §3 comparison: dtype, shape, count, values and masks."""
    if not isinstance(record, CrossArrays):
        raise CrossNpzSchemaError(
            f"a comparison record is a CrossArrays, got {type(record).__name__}"
        )
    effect_id = record.effect_id
    if not isinstance(effect_id, str) or not effect_id:
        raise CrossNpzSchemaError("every comparison states its non-empty effect_id")
    if any(char in effect_id for char in ("/", "\\", "\x00")):
        raise CrossNpzSchemaError(
            f"the effect id {effect_id!r} cannot name a ZIP member: it carries a path "
            "separator or a NUL"
        )

    count = record.comparison_knot_count
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise CrossNpzSchemaError(
            f"comparison {effect_id!r}: {_COUNT_FIELD} is a positive integer, got {count!r}; "
            "a comparable comparison has at least one comparison knot"
        )
    knot_count = count

    for suffix in CROSS_MEMBER_SUFFIXES:
        array = getattr(record, suffix)
        dtype = CROSS_MEMBER_DTYPES[suffix]
        if not isinstance(array, np.ndarray):
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: {suffix} must be an ndarray, got "
                f"{type(array).__name__}"
            )
        if array.dtype != dtype:
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: {suffix} must be {dtype.str} (the schema's fixed "
                f"little-endian dtype), got {array.dtype.str}"
            )
        expected = (knot_count,)
        if array.shape != expected:
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: {suffix} must have shape {expected} for "
                f"Kc={knot_count}, got {array.shape}"
            )

    for suffix in _FLOAT_SUFFIXES:
        if not bool(np.isfinite(getattr(record, suffix)).all()):
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: {suffix} carries a non-finite number; every value "
                "and every placeholder is finite, never NaN or Inf"
            )
    if knot_count > 1 and not bool((np.diff(record.knots_mm) > 0.0).all()):
        raise CrossNpzSchemaError(
            f"comparison {effect_id!r}: knots_mm must be strictly increasing"
        )
    _check_states_and_mask(record)


def _check_states_and_mask(record: CrossArrays) -> None:
    """Table A per side, the mask it implies, and the signed-zero placeholder rule (§3.3, §9)."""
    effect_id = record.effect_id
    for suffix in ("state1", "state2"):
        codes = getattr(record, suffix)
        out_of_table = sorted(
            {int(code) for code in codes.ravel()} - set(EFFECT_STATE_CODES)
        )
        if out_of_table:
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: {suffix} code(s) {out_of_table} are outside table "
                f"A ({sorted(EFFECT_STATE_CODES)}); a code the backend never produced is "
                "refused"
            )
    _check_binary_mask(effect_id, "defined", record.defined)

    common = (record.state1 == 0) & (record.state2 == 0)
    if not bool(np.array_equal(record.defined == 1, common)):
        raise CrossNpzSchemaError(
            f"comparison {effect_id!r}: the defined mask is 1 exactly where both sides' effect "
            "state code is 0 (defined), and 0 at every other position"
        )

    undefined = record.defined != 1
    if bool(undefined.any()):
        values = record.difference[undefined]
        if bool(np.any(values != 0.0)) or bool(np.any(np.signbit(values))):
            raise CrossNpzSchemaError(
                f"comparison {effect_id!r}: an undefined comparison knot carries the finite "
                "placeholder exactly +0.0; a number there would read as a measurement never "
                "taken, and a -0.0 there is a defined value misplaced onto the placeholder"
            )


def _check_binary_mask(effect_id: str, suffix: str, mask: np.ndarray) -> None:
    """Refuse a mask that is not exactly zero or one."""
    unusual = sorted({int(value) for value in mask.ravel()} - {0, 1})
    if unusual:
        raise CrossNpzSchemaError(
            f"comparison {effect_id!r}: {suffix} is a 0/1 mask, got {unusual}"
        )


# ── writing (§4) ────────────────────────────────────────────────────────


def encode_cross_npz(comparisons: Iterable[CrossArrays]) -> bytes:
    """Return the canonical §4 bytes of a cross-sitting comparisons container.

    Args:
        comparisons: one :class:`CrossArrays` per **comparable** comparison; a non-comparable
            comparison contributes no record and no member (§3.1). The order is irrelevant,
            because the members are written in ascending lexicographic member-name order.

    Returns:
        The ``ZIP_STORED`` archive bytes: one stored NPY v1.0 member per suffix per comparison,
        every member stamped with the ZIP epoch and the fixed attributes.

    Raises:
        CrossNpzSchemaError: the sequence is empty, two comparisons share an ``effect_id``, or
            any record is not a §3 comparison (dtype, shape, count, finiteness, masks, states,
            placeholder).
    """
    records = tuple(comparisons)
    if not records:
        raise CrossNpzSchemaError(
            "a comparisons container holds at least one comparable comparison"
        )
    ordered: dict[str, CrossArrays] = {}
    for record in records:
        _check_comparison(record)
        if record.effect_id in ordered:
            raise CrossNpzSchemaError(
                f"the effect id {record.effect_id!r} appears twice; member names would "
                "duplicate"
            )
        ordered[record.effect_id] = record

    members: dict[str, bytes] = {}
    for effect_id, record in ordered.items():
        for suffix in CROSS_MEMBER_SUFFIXES:
            members[cross_member_name(effect_id, suffix)] = _npy_bytes(
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


def decode_cross_npz(
    data: bytes,
    *,
    expected: Mapping[str, int | None] | None = None,
) -> tuple[CrossArrays, ...]:
    """Read a canonical §4 container, refusing anything a writer could drift into.

    Args:
        data: the container's exact file bytes.
        expected: optionally, the effect id → ``Kc`` mapping the sibling JSON publishes (§5.3,
            §5.5). A value that is an ``int`` names a **comparable** comparison and its
            ``comparison_knot_count``; a value that is ``None`` names a **not comparable**
            comparison, which must contribute no member (§3.1). When given, the container's
            comparable effect set must equal the mapping's ``int`` keys exactly and every
            member shape must agree with the declared count, so the mirror between the JSON and
            the NPZ is checked rather than assumed.

    Returns:
        One :class:`CrossArrays` per comparable comparison, in ascending ``effect_id`` order,
        with read-only arrays.

    Raises:
        CrossNpzContainerError: the bytes are not a ZIP, the archive carries a comment or a
            directory entry, a member is compressed, duplicated, out of order, outside the
            closed five suffixes or stamped with anything but the fixed timestamp and
            attributes, a payload is not a stored NPY v1.0 array of the member's exact dtype
            and shape, a per-knot member declares a ``(0,)`` comparison, a member is present
            for a comparison the published mapping types ``None``, or the container is not
            byte-for-byte what this module would write.
        CrossNpzSchemaError: the arrays break a §3.3 invariant — an unusable state code, a mask
            that disagrees with its state pair, a non-finite number, or a placeholder that is
            not exactly ``+0.0``.
    """
    raw = _as_bytes(data)
    per_effect = _read_members(raw)
    records = tuple(
        _record(effect_id, members) for effect_id, members in sorted(per_effect.items())
    )
    for record in records:
        _check_comparison(record)
    _check_expected(records, expected)
    if encode_cross_npz(records) != raw:
        raise CrossNpzContainerError(
            "the container bytes are not the canonical §4 encoding of the comparisons they "
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
    raise CrossNpzContainerError(
        f"a container is read from its bytes, got {type(data).__name__}"
    )


def _read_members(raw: bytes) -> dict[str, dict[str, np.ndarray]]:
    """Verify the container envelope and return every comparison's suffix → array mapping."""
    if not raw:
        raise CrossNpzContainerError("the container is empty")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), "r")
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise CrossNpzContainerError(f"the bytes are not a ZIP archive: {exc}") from exc
    with archive:
        if archive.comment:
            raise CrossNpzContainerError(
                "the archive carries a comment; the schema's container has none"
            )
        infos = archive.infolist()
        if not infos:
            raise CrossNpzContainerError("the container carries no member")
        names = [info.filename for info in infos]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise CrossNpzContainerError(
                f"member {duplicates[0]!r} appears more than once; the member set is closed "
                "and exact"
            )
        if names != sorted(names):
            raise CrossNpzContainerError(
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
                raise CrossNpzContainerError(
                    f"member {info.filename!r} cannot be read: {exc}"
                ) from exc
            slots = per_effect.setdefault(effect_id, {})
            slots[suffix] = _load_member(info.filename, suffix, payload)
    for effect_id, slots in per_effect.items():
        missing = sorted(set(CROSS_MEMBER_SUFFIXES) - set(slots))
        if missing:
            raise CrossNpzContainerError(
                f"comparison {effect_id!r} is missing member(s) {missing}; the five suffixes "
                "are closed and exact"
            )
    return per_effect


def _check_member_header(info: zipfile.ZipInfo) -> None:
    """Refuse a member whose stored/attribute envelope is not the fixed §4.2 one."""
    name = info.filename
    if info.is_dir():
        raise CrossNpzContainerError(
            f"member {name!r} is a directory entry; a canonical container has none"
        )
    if tuple(info.date_time) != ZIP_EPOCH:
        raise CrossNpzContainerError(
            f"member {name!r} carries the timestamp {tuple(info.date_time)} rather than "
            f"the fixed ZIP epoch {ZIP_EPOCH}"
        )
    if info.compress_type != zipfile.ZIP_STORED:
        raise CrossNpzContainerError(
            f"member {name!r} is compressed (method {info.compress_type}); every member is "
            "stored, never deflated"
        )
    if info.external_attr != EXTERNAL_ATTR:
        raise CrossNpzContainerError(
            f"member {name!r} carries external_attr {info.external_attr:#o} rather than the "
            f"fixed {EXTERNAL_ATTR:#o}"
        )
    if info.internal_attr != 0:
        raise CrossNpzContainerError(
            f"member {name!r} carries internal_attr {info.internal_attr:#o} rather than 0"
        )
    if info.create_system != 0:
        raise CrossNpzContainerError(
            f"member {name!r} carries create_system {info.create_system} rather than 0"
        )
    if info.extra:
        raise CrossNpzContainerError(
            f"member {name!r} carries {len(info.extra)} extra field byte(s); the schema has "
            "no extras"
        )
    if info.comment:
        raise CrossNpzContainerError(
            f"member {name!r} carries a comment; the schema has none"
        )


def _load_member(name: str, suffix: str, payload: bytes) -> np.ndarray:
    """Load one payload as the member's exact NPY v1.0 array, or refuse it."""
    dtype = CROSS_MEMBER_DTYPES[suffix]
    stream = io.BytesIO(payload)
    try:
        version = np.lib.format.read_magic(stream)
        if tuple(version) != NPY_FORMAT_VERSION:
            raise CrossNpzContainerError(
                f"member {name!r} uses NPY format version {tuple(version)}; the schema "
                f"fixes {NPY_FORMAT_VERSION}"
            )
        shape, fortran_order, declared = np.lib.format.read_array_header_1_0(stream)
    except CrossNpzContainerError:
        raise
    except (ValueError, EOFError, OSError) as exc:
        raise CrossNpzContainerError(
            f"member {name!r} has an unreadable NPY header: {exc}"
        ) from exc
    declared = np.dtype(declared)
    if declared != dtype:
        raise CrossNpzContainerError(
            f"member {name!r} declares dtype {declared.str} rather than the schema's "
            f"{dtype.str}"
        )
    if fortran_order:
        raise CrossNpzContainerError(
            f"member {name!r} is Fortran-ordered; every member is C-contiguous"
        )
    offset = stream.tell()
    nbytes = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
    if len(payload) - offset != nbytes:
        raise CrossNpzContainerError(
            f"member {name!r} carries {len(payload) - offset} array byte(s) for a declared "
            f"{nbytes}; the payload is exactly the header and its array"
        )
    array = np.frombuffer(
        payload, dtype=dtype, count=nbytes // dtype.itemsize, offset=offset
    )
    return array.reshape(shape)


def _record(effect_id: str, members: Mapping[str, np.ndarray]) -> CrossArrays:
    """Build one record from a decoded member mapping, reading ``Kc`` from the shapes."""
    knots = members["knots_mm"]
    if knots.ndim != _MEMBER_RANK:
        raise CrossNpzContainerError(
            f"member {cross_member_name(effect_id, 'knots_mm')!r} must be (Kc,), got shape "
            f"{knots.shape}"
        )
    if knots.shape[0] < 1:
        raise CrossNpzContainerError(
            f"member {cross_member_name(effect_id, 'knots_mm')!r} declares a zero-knot "
            "comparison: Kc = comparison_knot_count is a positive integer in the schema, so a "
            "(0,) per-knot member is refused here rather than surfacing as a raw "
            "record-validation error"
        )
    for suffix in CROSS_MEMBER_SUFFIXES:
        array = members[suffix]
        if array.ndim != _MEMBER_RANK:
            raise CrossNpzContainerError(
                f"member {cross_member_name(effect_id, suffix)!r} has shape {array.shape}; "
                f"the schema fixes a {_MEMBER_RANK}-dimensional member"
            )
    return CrossArrays(
        effect_id=effect_id,
        comparison_knot_count=int(knots.shape[0]),
        **{suffix: members[suffix] for suffix in CROSS_MEMBER_SUFFIXES},
    )


def _check_expected(
    records: tuple[CrossArrays, ...],
    expected: Mapping[str, int | None] | None,
) -> None:
    """Check the container's comparison set and shape counts against the published mirror."""
    if expected is None:
        return
    declared: dict[str, int | None] = {}
    for effect_id, count in expected.items():
        if not isinstance(effect_id, str) or not effect_id:
            raise CrossNpzSchemaError(
                "the expected mapping is effect id → comparison_knot_count (or None)"
            )
        if count is None:
            declared[effect_id] = None
            continue
        if isinstance(count, CrossComparisonShape):
            count = count.comparison_knot_count
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise CrossNpzSchemaError(
                f"the expected count of {effect_id!r} is a positive integer or None, got "
                f"{count!r}"
            )
        declared[effect_id] = count

    comparable = {key for key, count in declared.items() if count is not None}
    found = {record.effect_id for record in records}
    unexpected = sorted(found - comparable)
    if unexpected:
        raise CrossNpzContainerError(
            f"the container carries member(s) for comparison(s) {unexpected} the published "
            "mapping does not type comparable; a not comparable comparison contributes no "
            "member"
        )
    absent = sorted(comparable - found)
    if absent:
        raise CrossNpzContainerError(
            f"the container is missing the comparable comparison(s) {absent} the published "
            "mapping names"
        )
    for record in records:
        declared_count = declared[record.effect_id]
        if (
            declared_count is not None
            and record.comparison_knot_count != declared_count
        ):
            raise CrossNpzSchemaError(
                f"comparison {record.effect_id!r} is Kc={record.comparison_knot_count} in the "
                f"container but Kc={declared_count} in the published comparison_knot_count "
                "contract"
            )
