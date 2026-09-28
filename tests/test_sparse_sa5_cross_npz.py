"""Adversarial, writer-independent tests for SA5's canonical cross-sitting NPZ codec.

The contract under test is `docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md` §3 (the
closed five per-comparison members, their dtypes, shapes, masks, state codes and the
``+0.0`` placeholder) and §4 (the canonical byte rule: ``ZIP_STORED``, ascending member-name
order, the ZIP epoch, ``0o600 << 16``, fixed little-endian NPY v1.0 payloads, no extras, no
comments). What the tests pin:

- the *writer* is byte-deterministic and order-independent, and its bytes are reproduced by an
  **independent** writer built here from ``zipfile`` and ``numpy.lib.format`` alone — so §4 is
  checked against a second implementation, not against itself;
- the *reader* round-trips every member exactly, returns readonly finite arrays in ascending
  ``effect_id`` order, and refuses every container drift a byte-reproduction test exists to
  catch: compression, timestamp, attributes, extra fields, member comments, an archive comment,
  a directory entry, duplicate/out-of-order/extra/missing members, a payload whose NPY version,
  dtype, order, shape or length is not the §3 one, and any residual difference from the
  canonical bytes;
- the *schema* invariants of §3.3 are enforced per position on both sides: the mask is 1 exactly
  where **both** sides are ``defined``, a placeholder is never a measured number, a ``−0.0``
  may occupy only a **defined** position and is preserved rather than normalized, and a
  non-comparable comparison contributes no member;
- the closed state table A agrees with the v1 codec and the backend enum it names, so a code the
  estimator never produced cannot be published and a code that moves in the backend is caught
  here;
- the codec performs no arithmetic (``difference`` is never recomputed as ``E2 − E1``), publishes
  nothing, and is independent of the writer: its only inputs are arrays plus the
  ``comparison_knot_count`` metadata the JSON mirrors, and its only outputs are bytes and
  decoded arrays.

Every fixture and every tampered container is built in this file; the module under test is only
ever called through ``encode_cross_npz``/``decode_cross_npz``. No container is written to disk
and no committed artifact is touched.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_sa5_cross_npz import (
    CROSS_MEMBER_DTYPES,
    CROSS_MEMBER_SUFFIXES,
    EFFECT_STATE_CODES,
    CrossArrays,
    CrossComparisonShape,
    CrossNpzContainerError,
    CrossNpzError,
    CrossNpzSchemaError,
    cross_member_name,
    cross_member_names,
    decode_cross_npz,
    encode_cross_npz,
)
from udv_echo_process.analysis.sparse_sa5_effects import EffectState

#: Three frozen effect ids. ``burst_18``'s members precede ``burst_4``'s in both id and member
#: name order, so the multi-effect fixtures never rely on sorting by id coincidentally.
EFFECT_ID_BURST_4 = "primary-comparison__mean__pitch_at_burst_4"
EFFECT_ID_BURST_18 = "primary-comparison__mean__pitch_at_burst_18"
EFFECT_ID_INTERACTION = "full-record__band_fraction__pitch_x_burst_interaction"


# ── the canonical records (built here, never by the module under test) ──


def _arrays(knot_count: int = 3) -> dict[str, np.ndarray]:
    """Return a §3-legal five-member array set.

    The set deliberately carries every case the schema distinguishes, so a round-trip has to
    preserve all of them: a **defined measured negative zero** at knot 0 (mask 1, ``−0.0`` — a
    value whose sign is preserved, never a placeholder), a common-undefined knot 1 where one
    side is ``undefined-operand`` and the other ``undefined-alignment``, and a knot 2 undefined
    because the *first* side is undefined. Every undefined position carries the exact ``+0.0``
    placeholder.
    """
    knots = np.array([10.0, 20.0, 30.0], dtype="<f8")[:knot_count]
    state1 = np.array([0, 0, 1], dtype="<u1")[:knot_count]
    state2 = np.array([0, 2, 0], dtype="<u1")[:knot_count]
    defined = np.array([1, 0, 0], dtype="<u1")[:knot_count]
    difference = np.array([-0.0, 0.0, 0.0], dtype="<f8")[:knot_count]
    return {
        "knots_mm": knots,
        "difference": difference,
        "defined": defined,
        "state1": state1,
        "state2": state2,
    }


def _record(
    effect_id: str = EFFECT_ID_BURST_4,
    arrays: Mapping[str, np.ndarray] | None = None,
    *,
    comparison_knot_count: int | None = None,
) -> CrossArrays:
    """Build one record, with the declared count defaulting to the arrays' own shape."""
    members = dict(_arrays() if arrays is None else arrays)
    if comparison_knot_count is None:
        comparison_knot_count = int(members["knots_mm"].shape[0])
    return CrossArrays(
        effect_id=effect_id,
        comparison_knot_count=comparison_knot_count,
        **members,
    )


def _tampered(record: CrossArrays, suffix: str, index: Any, value: Any) -> CrossArrays:
    """Return the record with one array element overwritten (the tampering path)."""
    array = np.array(getattr(record, suffix), dtype=getattr(record, suffix).dtype)
    array[index] = value
    members = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    members[suffix] = array
    return _record(
        record.effect_id,
        members,
        comparison_knot_count=record.comparison_knot_count,
    )


# ── the independent container writer (§4, re-implemented beside the module) ──


def _npy(
    array: np.ndarray,
    *,
    version: tuple[int, int] = (1, 0),
    trailer: bytes = b"",
) -> bytes:
    """Write one NPY payload with ``numpy.lib.format`` directly, never through the codec."""
    buffer = io.BytesIO()
    np.lib.format.write_array(
        buffer, np.asarray(array), version=version, allow_pickle=False
    )
    return buffer.getvalue() + trailer


def _fortran_payload(array: np.ndarray) -> bytes:
    """A 1-D payload with ``fortran_order`` flipped to ``True`` in its own header.

    A 1-D array is both C- and Fortran-contiguous, so ``numpy`` never writes
    ``fortran_order=True`` for one; only a hand-written header can, which is exactly the
    drift the reader must refuse.
    """
    payload = _npy(array)
    marker = b"'fortran_order': False"
    assert marker in payload
    return payload.replace(marker, b"'fortran_order': True ", 1)


def _members(
    comparisons: Mapping[str, Mapping[str, np.ndarray]],
    *,
    drop: Iterable[str] = (),
    npy_kwargs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, bytes]:
    """Build one container-wide member mapping: ``<effect_id>__<suffix>.npy`` → payload."""
    dropped = set(drop)
    payloads: dict[str, bytes] = {}
    for effect_id, arrays in comparisons.items():
        for suffix in CROSS_MEMBER_SUFFIXES:
            if suffix in dropped:
                continue
            payloads[f"{effect_id}__{suffix}.npy"] = _npy(
                arrays[suffix], **dict((npy_kwargs or {}).get(suffix, {}))
            )
    return payloads


def _zip(
    members: Mapping[str, bytes],
    *,
    order: Sequence[str] | None = None,
    date_time: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
    compress_type: int = zipfile.ZIP_STORED,
    external_attr: int = 0o600 << 16,
    internal_attr: int = 0,
    create_system: int = 0,
    create_version: int = 20,
    extract_version: int = 20,
    extra: bytes = b"",
    comment: bytes = b"",
    archive_comment: bytes = b"",
) -> bytes:
    """Write a ZIP with the fixed envelope by default; every keyword is a tampering lever."""
    names = sorted(members) if order is None else list(order)
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=False
    ) as archive:
        for name in names:
            info = zipfile.ZipInfo(name, date_time=date_time)
            info.compress_type = compress_type
            info.external_attr = external_attr
            info.internal_attr = internal_attr
            info.create_system = create_system
            info.create_version = create_version
            info.extract_version = extract_version
            info.extra = extra
            info.comment = comment
            archive.writestr(info, members[name])
        if archive_comment:
            archive.comment = archive_comment
    return buffer.getvalue()


def _raw(comparisons: Mapping[str, Mapping[str, np.ndarray]], **envelope: Any) -> bytes:
    """The independent writer's bytes for a set of comparisons, with optional tampering."""
    return _zip(_members(comparisons), **envelope)


def _valid_container(effect_id: str = EFFECT_ID_BURST_4) -> bytes:
    """The canonical bytes of one legal comparison, written by the independent writer."""
    return _raw({effect_id: _arrays()})


# ── the deterministic byte rule (§4) ────────────────────────────────────


def test_write_is_byte_deterministic_and_order_independent() -> None:
    first, second = _record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION)
    once = encode_cross_npz([first, second])
    assert once == encode_cross_npz([first, second])
    assert once == encode_cross_npz([second, first])
    assert once == encode_cross_npz(
        [_record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION)]
    )


def test_independent_writer_reproduces_the_codec_bytes_exactly() -> None:
    """§4 is checked against a second implementation, not against the codec itself."""
    assert _valid_container() == encode_cross_npz([_record()])


def test_member_names_are_the_closed_five_sorted_globally() -> None:
    both = {EFFECT_ID_BURST_18: _arrays(), EFFECT_ID_BURST_4: _arrays()}
    raw = encode_cross_npz([_record(EFFECT_ID_BURST_18), _record(EFFECT_ID_BURST_4)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert set(names) == set(_members(both))
    assert names == sorted(names)
    assert len(names) == 2 * len(CROSS_MEMBER_SUFFIXES)
    assert all(name.endswith(".npy") for name in names)
    assert names[0].startswith(EFFECT_ID_BURST_18 + "__")
    assert names[-1].startswith(EFFECT_ID_BURST_4 + "__")


def test_the_member_sort_is_global_and_the_suffix_is_the_last_one() -> None:
    """An effect id may itself carry ``__``, so the suffix is split from the *last* join.

    ``effect__difference``'s members all sort after ``effect``'s ``knots_mm`` member, because the
    comparison runs past the join into the suffix — which is also why ``effect__difference__state1
    .npy`` is ``effect__difference`` + ``state1`` and not ``effect`` + ``difference__state1``.
    """
    short, longer = "effect", "effect__difference"
    raw = encode_cross_npz([_record(short), _record(longer)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert names == sorted(names)
    assert set(names) == {
        f"{effect_id}__{suffix}.npy"
        for effect_id in (short, longer)
        for suffix in CROSS_MEMBER_SUFFIXES
    }
    assert raw == _zip(_members({short: _arrays(), longer: _arrays()}))
    decoded = decode_cross_npz(raw)
    assert [record.effect_id for record in decoded] == [short, longer]
    assert decoded[1].state1[2] == 1


def test_envelope_is_the_fixed_stored_epoch_container() -> None:
    with zipfile.ZipFile(io.BytesIO(_valid_container())) as archive:
        assert archive.comment == b""
        infos = archive.infolist()
    assert len(infos) == len(CROSS_MEMBER_SUFFIXES)
    for info in infos:
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.external_attr == 0o600 << 16
        assert info.internal_attr == 0
        assert info.create_system == 0
        assert info.extra == b""
        assert info.comment == b""
        assert not info.is_dir()


def test_payloads_are_bare_npy_v1_0_arrays_and_never_pickled() -> None:
    with zipfile.ZipFile(io.BytesIO(_valid_container())) as archive:
        for name in archive.namelist():
            payload = archive.read(name)
            assert payload.startswith(b"\x93NUMPY\x01\x00")
            assert np.load(io.BytesIO(payload), allow_pickle=False) is not None


def test_every_member_dtype_shape_and_count_is_the_schema_one() -> None:
    records = decode_cross_npz(_valid_container())
    assert len(records) == 1
    record = records[0]
    assert record.comparison_knot_count == 3
    assert record.shape == CrossComparisonShape(3)
    source = _arrays()
    for suffix in CROSS_MEMBER_SUFFIXES:
        array = getattr(record, suffix)
        assert array.dtype == CROSS_MEMBER_DTYPES[suffix]
        assert array.dtype.str == CROSS_MEMBER_DTYPES[suffix].str
        assert np.array_equal(array, source[suffix])
        assert not array.flags.writeable
        assert array.flags.c_contiguous
        assert array.shape == (3,)


def test_reader_round_trips_the_codec_and_orders_comparisons_by_effect_id() -> None:
    records = (_record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION))
    decoded = decode_cross_npz(encode_cross_npz(records))
    assert [record.effect_id for record in decoded] == sorted(
        [EFFECT_ID_BURST_4, EFFECT_ID_INTERACTION]
    )
    assert decoded == tuple(sorted(records, key=lambda record: record.effect_id))
    assert decode_cross_npz(encode_cross_npz(records)) == decoded


# ── signed zeros (§9) ───────────────────────────────────────────────────


def test_a_negative_zero_at_a_defined_position_is_preserved_not_normalized() -> None:
    decoded = decode_cross_npz(encode_cross_npz([_record()]))[0]
    assert decoded.defined[0] == 1
    assert decoded.difference[0] == 0.0
    assert bool(np.signbit(decoded.difference[0]))
    assert encode_cross_npz([_record()]) == _valid_container()


def test_a_negative_zero_is_refused_at_an_undefined_position() -> None:
    """ "A ``−0.0`` occupies no undefined position" (§9): undefined carries exactly ``+0.0``."""
    record = _tampered(_record(), "difference", np.s_[1], -0.0)
    with pytest.raises(CrossNpzSchemaError, match=r"exactly \+0.0"):
        encode_cross_npz([record])
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    with pytest.raises(CrossNpzSchemaError, match=r"exactly \+0.0"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_a_positive_zero_placeholder_is_accepted_at_an_undefined_position() -> None:
    arrays = _arrays()
    arrays["difference"] = np.array([-0.0, 0.0, 0.0], dtype="<f8")
    assert decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))[0].defined[1] == 0


# ── the container envelope refusals (§4) ────────────────────────────────


def test_the_control_container_is_accepted() -> None:
    assert decode_cross_npz(_valid_container())


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"compress_type": zipfile.ZIP_DEFLATED}, id="deflated"),
        pytest.param({"date_time": (1980, 1, 1, 0, 0, 2)}, id="timestamp"),
        pytest.param({"date_time": (2026, 9, 28, 12, 0, 0)}, id="real-timestamp"),
        pytest.param({"external_attr": 0o644 << 16}, id="external-attr"),
        pytest.param({"internal_attr": 1}, id="internal-attr"),
        pytest.param({"create_system": 3}, id="create-system"),
        pytest.param({"extra": b"\x00\x00\x00\x00"}, id="extra-field"),
        pytest.param({"comment": b"note"}, id="member-comment"),
        pytest.param({"archive_comment": b"note"}, id="archive-comment"),
        pytest.param({"create_version": 30}, id="create-version"),
        pytest.param({"extract_version": 45}, id="extract-version"),
    ],
)
def test_reader_refuses_a_noncanonical_envelope(tamper: dict[str, Any]) -> None:
    with pytest.raises(CrossNpzContainerError):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: _arrays()}, **tamper))


def test_reader_refuses_unsorted_members() -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()})
    order = sorted(members)
    with pytest.raises(CrossNpzContainerError, match="ascending"):
        decode_cross_npz(_zip(members, order=[*order[1:], order[0]]))


def test_reader_refuses_a_duplicate_member() -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()})
    order = sorted(members)
    with pytest.warns(UserWarning, match="Duplicate name"):
        raw = _zip(members, order=[*order, order[0]])
    with pytest.raises(CrossNpzContainerError, match="more than once"):
        decode_cross_npz(raw)


@pytest.mark.parametrize(
    "stray",
    [
        pytest.param("stray.npy", id="no-suffix"),
        pytest.param(f"{EFFECT_ID_BURST_4}__meta__.npy", id="unknown-suffix"),
        pytest.param(f"{EFFECT_ID_BURST_4}__knots.npy", id="near-miss-suffix"),
        pytest.param(f"{EFFECT_ID_BURST_4}__state3.npy", id="near-miss-state"),
        pytest.param("__knots_mm.npy", id="empty-effect-id"),
        pytest.param(f"sub/{EFFECT_ID_BURST_4}__knots_mm.npy", id="nested-path"),
        pytest.param(f"{EFFECT_ID_BURST_4}__knots_mm.npy.bak", id="wrong-extension"),
    ],
)
def test_reader_refuses_a_member_outside_the_closed_set(stray: str) -> None:
    members = {**_members({EFFECT_ID_BURST_4: _arrays()}), stray: b"stray"}
    with pytest.raises(CrossNpzContainerError):
        decode_cross_npz(_zip(members))


@pytest.mark.parametrize(
    "suffix", ["knots_mm", "difference", "defined", "state1", "state2"]
)
def test_reader_refuses_a_missing_member(suffix: str) -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()}, drop=[suffix])
    with pytest.raises(CrossNpzContainerError, match="missing"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_a_directory_entry() -> None:
    members = {**_members({EFFECT_ID_BURST_4: _arrays()}), "extra/": b""}
    with pytest.raises(CrossNpzContainerError, match="directory"):
        decode_cross_npz(_zip(members))


@pytest.mark.parametrize("dtype", ["<f4", "<i8", ">f8"])
def test_reader_refuses_a_wrong_dtype(dtype: str) -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__knots_mm.npy"] = _npy(
        np.asarray(arrays["knots_mm"], dtype=dtype)
    )
    with pytest.raises(CrossNpzContainerError, match="dtype"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_a_shape_that_disagrees_with_the_other_members() -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__knots_mm.npy"] = _npy(
        np.array([10.0, 20.0, 30.0, 40.0], dtype="<f8")
    )
    with pytest.raises(CrossNpzSchemaError, match="shape"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_a_two_dimensional_member() -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__difference.npy"] = _npy(
        arrays["difference"].reshape(1, 3)
    )
    with pytest.raises(CrossNpzContainerError, match="dimensional"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_a_zero_length_member() -> None:
    """A ``(0,)`` member names a comparison domain that does not exist (§3.1)."""
    arrays = {name: value[:0] for name, value in _arrays().items()}
    with pytest.raises(CrossNpzContainerError, match="zero-knot"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_reader_refuses_trailing_bytes_in_a_payload() -> None:
    members = _members(
        {EFFECT_ID_BURST_4: _arrays()},
        npy_kwargs={"difference": {"trailer": b"\x00\x00\x00\x00"}},
    )
    with pytest.raises(CrossNpzContainerError, match="array byte"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_npy_format_2_and_fortran_order() -> None:
    members = _members(
        {EFFECT_ID_BURST_4: _arrays()}, npy_kwargs={"difference": {"version": (2, 0)}}
    )
    with pytest.raises(CrossNpzContainerError, match="NPY format version"):
        decode_cross_npz(_zip(members))

    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__difference.npy"] = _fortran_payload(
        arrays["difference"]
    )
    with pytest.raises(CrossNpzContainerError, match="Fortran"):
        decode_cross_npz(_zip(members))


def test_reader_refuses_bytes_that_are_not_a_container() -> None:
    for data in (b"", b"not a zip at all", b"PK\x03\x04truncated"):
        with pytest.raises(CrossNpzContainerError):
            decode_cross_npz(data)
    with pytest.raises(CrossNpzContainerError, match="bytes"):
        decode_cross_npz("a string")  # type: ignore[arg-type]


def test_reader_refuses_a_corrupt_payload_crc() -> None:
    raw = bytearray(_valid_container())
    payload_start = raw.index(b"\x93NUMPY")
    raw[payload_start + 40] ^= 0xFF
    with pytest.raises(CrossNpzContainerError):
        decode_cross_npz(bytes(raw))


def test_reader_refuses_a_noncanonical_byte_no_other_check_covers() -> None:
    """A structurally valid archive whose bytes are not the fixed rule is still refused."""
    raw = _raw({EFFECT_ID_BURST_4: _arrays()}, create_version=31)
    with pytest.raises(CrossNpzContainerError, match="canonical"):
        decode_cross_npz(raw)


# ── the schema invariants of §3.3, on the writer and the reader ─────────


@pytest.mark.parametrize("suffix", ["state1", "state2"])
@pytest.mark.parametrize("code", [3, 7, 255])
def test_writer_and_reader_refuse_a_state_code_outside_table_a(
    suffix: str, code: int
) -> None:
    record = _record()
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    arrays[suffix] = np.full(3, code, dtype="<u1")
    with pytest.raises(CrossNpzSchemaError, match="table A"):
        encode_cross_npz([_record(arrays=arrays)])
    with pytest.raises(CrossNpzSchemaError, match="table A"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_mask_is_one_exactly_where_both_sides_are_defined() -> None:
    # Knot 2 has state1 = 1 (undefined), so a 1 in its mask is the mismatch.
    record = _tampered(_record(), "defined", np.s_[2], 1)
    with pytest.raises(CrossNpzSchemaError, match="defined mask"):
        encode_cross_npz([record])
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    with pytest.raises(CrossNpzSchemaError, match="defined mask"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_a_mask_value_outside_zero_and_one_is_refused() -> None:
    record = _tampered(_record(), "defined", np.s_[0], 2)
    with pytest.raises(CrossNpzSchemaError, match="0/1 mask"):
        encode_cross_npz([record])


def test_an_undefined_position_carries_the_placeholder_and_never_a_number() -> None:
    # Knot 1 is common-undefined (state1 = 0, state2 = 2); a number there is refused.
    record = _tampered(_record(), "difference", np.s_[1], 1.5)
    with pytest.raises(CrossNpzSchemaError, match=r"exactly \+0.0"):
        encode_cross_npz([record])
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    with pytest.raises(CrossNpzSchemaError, match=r"exactly \+0.0"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_a_defined_measured_zero_is_a_value_not_a_placeholder() -> None:
    decoded = decode_cross_npz(encode_cross_npz([_record()]))[0]
    arrays = _arrays()
    defined_zero = np.array([0.0, 0.0, 0.0], dtype="<f8")
    record = _record(arrays={**_arrays(), "difference": defined_zero})
    round_tripped = decode_cross_npz(encode_cross_npz([record]))[0]
    assert decoded.defined[0] == 1
    assert round_tripped.difference[0] == 0.0
    assert not bool(np.signbit(round_tripped.difference[0]))
    assert np.array_equal(arrays["defined"], round_tripped.defined)


@pytest.mark.parametrize(
    "knots",
    [
        [10.0, 20.0, 20.0],
        [30.0, 20.0, 10.0],
        [10.0, 10.0, 30.0],
    ],
)
def test_knots_must_be_strictly_increasing(knots: list[float]) -> None:
    record = _record()
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    arrays["knots_mm"] = np.array(knots, dtype="<f8")
    with pytest.raises(CrossNpzSchemaError, match="strictly increasing"):
        encode_cross_npz([_record(arrays=arrays)])
    with pytest.raises(CrossNpzSchemaError, match="strictly increasing"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


@pytest.mark.parametrize("suffix", ["knots_mm", "difference"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_no_member_carries_a_non_finite_number(suffix: str, value: float) -> None:
    record = _tampered(_record(), suffix, np.s_[0], value)
    with pytest.raises(CrossNpzSchemaError, match="non-finite"):
        encode_cross_npz([record])
    arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
    with pytest.raises(CrossNpzSchemaError, match="non-finite"):
        decode_cross_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_writer_refuses_a_wrong_input_dtype() -> None:
    record = _record()
    for suffix, dtype in (("state1", "<i4"), ("knots_mm", ">f8"), ("defined", "<f8")):
        arrays = {name: getattr(record, name) for name in CROSS_MEMBER_SUFFIXES}
        arrays[suffix] = np.asarray(arrays[suffix], dtype=dtype)
        with pytest.raises(ValueError, match="fixed little-endian dtype"):
            _record(arrays=arrays)


def test_the_record_is_frozen_and_refuses_a_rebind() -> None:
    record = _record()
    with pytest.raises(ValueError):
        record.effect_id = EFFECT_ID_INTERACTION  # type: ignore[misc]
    with pytest.raises(ValueError):
        record.comparison_knot_count = 8  # type: ignore[misc]


def test_the_record_owns_its_arrays_and_never_shares_the_caller_s_memory() -> None:
    """``array_field`` stores an owned, read-only C copy — not the caller's buffer."""
    source = _arrays()
    record = _record(arrays=source)
    for suffix in CROSS_MEMBER_SUFFIXES:
        stored = getattr(record, suffix)
        assert stored.flags.owndata
        assert stored.flags.c_contiguous
        assert not stored.flags.writeable
        assert not np.shares_memory(stored, source[suffix])
    before = {
        suffix: getattr(record, suffix).copy() for suffix in CROSS_MEMBER_SUFFIXES
    }

    source["knots_mm"][0] = 999.0
    source["difference"][1] = 42.0

    for suffix in CROSS_MEMBER_SUFFIXES:
        assert np.array_equal(getattr(record, suffix), before[suffix])
    assert record.knots_mm[0] == 10.0

    with pytest.raises(ValueError):
        record.knots_mm[0] = 1.0  # a stored field is read-only in place


def test_the_declared_count_must_agree_with_the_arrays() -> None:
    with pytest.raises(CrossNpzSchemaError, match="shape"):
        encode_cross_npz([_record(comparison_knot_count=5)])
    for bad in (0, -1, True, 2.0):
        with pytest.raises(ValueError, match="positive integer"):
            encode_cross_npz([_record(comparison_knot_count=bad)])  # type: ignore[arg-type]


def test_the_writer_refuses_a_duplicate_comparison_and_an_empty_container() -> None:
    with pytest.raises(CrossNpzSchemaError, match="at least one comparable"):
        encode_cross_npz([])
    with pytest.raises(CrossNpzSchemaError, match="appears twice"):
        encode_cross_npz([_record(), _record()])
    with pytest.raises(CrossNpzSchemaError, match="non-empty effect_id"):
        encode_cross_npz([_record("")])


# ── the published mirror (§5.3/§5.5), including the no-member rule (§3.1) ──


def test_expected_mapping_accepts_agreement_and_refuses_drift() -> None:
    raw = encode_cross_npz([_record(), _record(EFFECT_ID_INTERACTION)])
    counts = {EFFECT_ID_BURST_4: 3, EFFECT_ID_INTERACTION: 3}
    assert len(decode_cross_npz(raw, expected=counts)) == 2
    assert (
        len(
            decode_cross_npz(
                raw,
                expected={
                    EFFECT_ID_BURST_4: CrossComparisonShape(3),
                    EFFECT_ID_INTERACTION: 3,
                },
            )
        )
        == 2
    )

    with pytest.raises(CrossNpzContainerError, match="does not type comparable"):
        decode_cross_npz(raw, expected={EFFECT_ID_BURST_4: 3})
    with pytest.raises(CrossNpzContainerError, match="missing the comparable"):
        decode_cross_npz(
            encode_cross_npz([_record()]),
            expected={EFFECT_ID_BURST_4: 3, "absent": 1},
        )
    with pytest.raises(CrossNpzSchemaError, match="comparison_knot_count"):
        decode_cross_npz(encode_cross_npz([_record()]), expected={EFFECT_ID_BURST_4: 4})


def test_a_not_comparable_comparison_contributes_no_member() -> None:
    """A ``None`` count names a not comparable pair; a member for it is refused (§3.1)."""
    raw = encode_cross_npz([_record()])
    full = {EFFECT_ID_BURST_4: 3, "unmatched__mean__pitch_at_burst_4": None}
    assert decode_cross_npz(raw, expected=full)[0].effect_id == EFFECT_ID_BURST_4
    with pytest.raises(CrossNpzContainerError, match="does not type comparable"):
        decode_cross_npz(
            raw,
            expected={EFFECT_ID_BURST_4: None, "other": 3},
        )


def test_expected_mapping_refuses_a_bad_count() -> None:
    raw = encode_cross_npz([_record()])
    for bad in (0, -1, True, 2.0):
        with pytest.raises(CrossNpzSchemaError, match="positive integer or None"):
            decode_cross_npz(raw, expected={EFFECT_ID_BURST_4: bad})  # type: ignore[dict-item]


def test_member_names_are_the_five_closed_suffixes_of_one_comparison() -> None:
    names = cross_member_names(EFFECT_ID_BURST_4)
    assert names == tuple(sorted(names))
    assert set(names) == {
        f"{EFFECT_ID_BURST_4}__{suffix}.npy" for suffix in CROSS_MEMBER_SUFFIXES
    }
    assert len(names) == 5
    assert cross_member_name(EFFECT_ID_BURST_4, "knots_mm") == (
        f"{EFFECT_ID_BURST_4}__knots_mm.npy"
    )
    with pytest.raises(CrossNpzSchemaError, match="closed member suffixes"):
        cross_member_name(EFFECT_ID_BURST_4, "knots")
    assert list(CROSS_MEMBER_SUFFIXES) == sorted(CROSS_MEMBER_SUFFIXES)
    assert len(CROSS_MEMBER_DTYPES) == 5
    assert set(CROSS_MEMBER_DTYPES) == set(CROSS_MEMBER_SUFFIXES)


# ── the code vocabulary agrees with the backend (§3.3) ──────────────────


def test_the_state_code_table_is_the_backend_enum_it_names() -> None:
    assert {code: EFFECT_STATE_CODES[code] for code in sorted(EFFECT_STATE_CODES)} == {
        index: state.value for index, state in enumerate(EffectState)
    }
    assert set(EFFECT_STATE_CODES) == {0, 1, 2}


def test_the_public_surface_is_only_the_container_codec() -> None:
    import udv_echo_process.analysis.sparse_sa5_cross_npz as codec

    assert set(codec.__all__) == {
        "EFFECT_STATE_CODES",
        "CROSS_MEMBER_DTYPES",
        "CROSS_MEMBER_SUFFIXES",
        "CrossArrays",
        "CrossComparisonShape",
        "CrossNpzContainerError",
        "CrossNpzError",
        "CrossNpzSchemaError",
        "cross_member_name",
        "cross_member_names",
        "decode_cross_npz",
        "encode_cross_npz",
    }
    assert issubclass(CrossNpzContainerError, CrossNpzError)
    assert issubclass(CrossNpzSchemaError, CrossNpzError)
    assert issubclass(CrossNpzError, ValueError)
