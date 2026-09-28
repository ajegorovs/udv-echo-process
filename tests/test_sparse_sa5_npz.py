"""Adversarial, writer-independent tests for SA5's canonical NPZ effect codec.

The contract under test is `docs/dop3000/sa5-effect-artifact-schema-proposal.md` §3 (the
closed ten per-effect members, their dtypes, shapes, masks, state codes and the finite
placeholder) and §4 (the canonical byte rule: ``ZIP_STORED``, ascending member-name order,
the ZIP epoch, ``0o600 << 16``, fixed little-endian NPY v1.0 payloads, no extras, no
comments). What the tests pin:

- the *writer* is byte-deterministic and order-independent, and its bytes are reproduced by
  an **independent** writer built here from ``zipfile`` and ``numpy.lib.format`` alone — so
  §4 is checked against a second implementation, not against itself;
- the *reader* round-trips every member exactly, returns readonly finite arrays in ascending
  ``effect_id`` order, and refuses every container drift a byte-reproduction test exists to
  catch: compression, timestamp, attributes, extra fields, member comments, an archive
  comment, a directory entry, duplicate/out-of-order/extra/missing members, a payload whose
  NPY version, dtype, order, shape or length is not the §3 one, and any residual difference
  from the canonical bytes;
- the *schema* invariants of §3.2 are enforced per position on both sides: the mask is 1
  exactly at the ``defined`` code, a placeholder is never a measured number, an unaligned
  read is the full ``-1``/``0.0``/``0``/``6`` sentinel tuple **only** there, and an aligned
  read whose metric is undefined **retains** its gate index, depth and offset;
- the closed state vocabularies of §8 agree with the backend enums they name, so a code the
  estimator never produced cannot be published and a code that moves in the backend is
  caught here;
- the codec performs no arithmetic, publishes nothing, and is independent of the writer: its
  only inputs are arrays plus the ``knot_count``/``participant_count`` metadata the JSON
  mirrors, and its only outputs are bytes and decoded arrays.

Every fixture and every tampered container is built in this file; the module under test is
only ever called through ``encode_effect_npz``/``decode_effect_npz``. No container is written
to disk and no committed artifact is touched.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_sa5_effects import EffectState
from udv_echo_process.analysis.sparse_sa5_metrics import MetricState
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    MEMBER_DTYPES,
    MEMBER_SUFFIXES,
    PARTICIPANT_STATE_CODES,
    UNALIGNED_READ_CODE,
    EffectArrays,
    EffectShape,
    NpzContainerError,
    NpzSchemaError,
    SparseSa5NpzError,
    decode_effect_npz,
    effect_member_names,
    encode_effect_npz,
    member_name,
)

#: Two ids whose *effect-id* order and *member-name* order disagree: the container sorts by
#: member name, so ``burst_4``'s members precede ``burst_18``'s even though the id
#: ``...burst_18`` sorts first. Sorting members by id would produce a different archive.
EFFECT_ID_BURST_18 = "primary-comparison__mean__pitch_at_burst_18"
EFFECT_ID_BURST_4 = "primary-comparison__mean__pitch_at_burst_4"

#: A second id, used where more than one effect has to be in one container.
EFFECT_ID_INTERACTION = "full-record__band_fraction__pitch_x_burst_interaction"


# ── the canonical records (built here, never by the module under test) ──


def _arrays(knot_count: int = 4, participant_count: int = 2) -> dict[str, np.ndarray]:
    """Return a §3-legal ten-member array set: defined, undefined and unaligned reads.

    The set deliberately carries every case the schema distinguishes, so a round-trip has to
    preserve all of them: a measured value, a **defined measured zero** (mask 1, value 0.0 —
    a value, never a placeholder), an aligned-but-undefined read that must keep its real gate
    index/depth/offset, and an unaligned read that must be exactly the ``-1`` sentinel tuple.
    """
    knots = np.array([10.0, 20.0, 30.0, 40.0], dtype="<f8")[:knot_count]
    effect = np.array([0.5, 0.0, -1.5, 0.0], dtype="<f8")[:knot_count]
    defined = np.array([1, 0, 1, 0], dtype="<u1")[:knot_count]
    state = np.array([0, 1, 0, 2], dtype="<u1")[:knot_count]

    gate = np.array([[3, 7, 11, -1], [2, -1, 9, 13]], dtype="<i4")[
        :participant_count, :knot_count
    ]
    depth = np.array([[3.1, 7.2, 11.3, 0.0], [2.4, 0.0, 9.6, 13.7]], dtype="<f8")[
        :participant_count, :knot_count
    ]
    offset = np.where(gate < 0, 0.0, depth - knots[None, :])
    value = np.array([[1.5, 0.0, 2.5, 0.0], [0.4, 0.0, 0.0, 1.2]], dtype="<f8")[
        :participant_count, :knot_count
    ]
    p_defined = np.array([[1, 0, 1, 0], [1, 0, 1, 1]], dtype="<u1")[
        :participant_count, :knot_count
    ]
    p_state = np.array([[0, 3, 0, 6], [0, 6, 0, 0]], dtype="<u1")[
        :participant_count, :knot_count
    ]
    return {
        "knots_mm": knots,
        "effect": effect,
        "defined": defined,
        "state": state,
        "participant_gate_index": gate,
        "participant_depth_mm": np.ascontiguousarray(depth, dtype="<f8"),
        "participant_offset_mm": np.ascontiguousarray(offset, dtype="<f8"),
        "participant_value": value,
        "participant_defined": p_defined,
        "participant_state": p_state,
    }


def _record(
    effect_id: str = EFFECT_ID_BURST_4,
    arrays: Mapping[str, np.ndarray] | None = None,
    *,
    knot_count: int | None = None,
    participant_count: int | None = None,
) -> EffectArrays:
    """Build one record, with the declared counts defaulting to the arrays' own shapes."""
    members = dict(_arrays() if arrays is None else arrays)
    if knot_count is None:
        knot_count = int(members["knots_mm"].shape[0])
    if participant_count is None:
        participant_count = int(members["participant_gate_index"].shape[0])
    return EffectArrays(
        effect_id=effect_id,
        knot_count=knot_count,
        participant_count=participant_count,
        **members,
    )


def _tampered(
    record: EffectArrays, suffix: str, index: Any, value: Any
) -> EffectArrays:
    """Return the record with one array element overwritten (the tampering path)."""
    array = np.array(getattr(record, suffix), dtype=getattr(record, suffix).dtype)
    array[index] = value
    members = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    members[suffix] = array
    return _record(
        record.effect_id,
        members,
        knot_count=record.knot_count,
        participant_count=record.participant_count,
    )


# ── the independent container writer (§4, re-implemented beside the module) ──


def _npy(
    array: np.ndarray,
    *,
    version: tuple[int, int] = (1, 0),
    trailer: bytes = b"",
) -> bytes:
    """Write one NPY payload with ``numpy.lib.format`` directly, never through the codec.

    The array is passed through unchanged, so a Fortran-contiguous array here produces the
    Fortran-ordered header ``numpy`` writes for it — the way a drifted writer would.
    """
    buffer = io.BytesIO()
    np.lib.format.write_array(
        buffer, np.asarray(array), version=version, allow_pickle=False
    )
    return buffer.getvalue() + trailer


def _members(
    effects: Mapping[str, Mapping[str, np.ndarray]],
    *,
    drop: Iterable[str] = (),
    npy_kwargs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, bytes]:
    """Build one container-wide member mapping: ``<effect_id>__<suffix>.npy`` → payload."""
    dropped = set(drop)
    payloads: dict[str, bytes] = {}
    for effect_id, arrays in effects.items():
        for suffix in MEMBER_SUFFIXES:
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


def _raw(effects: Mapping[str, Mapping[str, np.ndarray]], **envelope: Any) -> bytes:
    """The independent writer's bytes for a set of effects, with optional tampering."""
    return _zip(_members(effects), **envelope)


def _valid_container(effect_id: str = EFFECT_ID_BURST_4) -> bytes:
    """The canonical bytes of one legal effect, written by the independent writer."""
    return _raw({effect_id: _arrays()})


# ── the deterministic byte rule (§4) ────────────────────────────────────


def test_write_is_byte_deterministic_and_order_independent() -> None:
    first, second = _record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION)
    once = encode_effect_npz([first, second])
    assert once == encode_effect_npz([first, second])
    assert once == encode_effect_npz([second, first])
    assert once == encode_effect_npz(
        [_record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION)]
    )


def test_independent_writer_reproduces_the_codec_bytes_exactly() -> None:
    """§4 is checked against a second implementation, not against the codec itself."""
    assert _valid_container() == encode_effect_npz([_record()])


def test_member_names_are_the_closed_ten_sorted_globally() -> None:
    both = {EFFECT_ID_BURST_18: _arrays(), EFFECT_ID_BURST_4: _arrays()}
    raw = encode_effect_npz([_record(EFFECT_ID_BURST_18), _record(EFFECT_ID_BURST_4)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert set(names) == set(_members(both))
    assert names == sorted(names)
    assert len(names) == 2 * len(MEMBER_SUFFIXES)
    assert all(name.endswith(".npy") for name in names)
    assert names[0].startswith(EFFECT_ID_BURST_18 + "__")
    assert names[-1].startswith(EFFECT_ID_BURST_4 + "__")


def test_the_member_sort_is_global_and_the_suffix_is_the_last_one() -> None:
    """An effect id may itself carry ``__``, so the ten members of one effect need not group.

    ``effect__s``'s members all sort before ``effect``'s ``state`` member, because the
    comparison runs past the join into the suffix — which is also why the suffix has to be
    split off from the *last* ``__`` (``effect__s__state.npy`` is ``effect__s`` + ``state``).
    """
    short, longer = "effect", "effect__s"
    raw = encode_effect_npz([_record(short), _record(longer)])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
    assert names == sorted(names)
    assert set(names) == {
        f"{effect_id}__{suffix}.npy"
        for effect_id in (short, longer)
        for suffix in MEMBER_SUFFIXES
    }
    assert raw == _zip(_members({short: _arrays(), longer: _arrays()}))
    assert names[-1] == f"{short}__state.npy"
    assert names[-2].startswith(longer + "__")
    decoded = decode_effect_npz(raw)
    assert [record.effect_id for record in decoded] == [short, longer]


def test_envelope_is_the_fixed_stored_epoch_container() -> None:
    with zipfile.ZipFile(io.BytesIO(_valid_container())) as archive:
        assert archive.comment == b""
        infos = archive.infolist()
    assert len(infos) == len(MEMBER_SUFFIXES)
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
    records = decode_effect_npz(_valid_container())
    assert len(records) == 1
    record = records[0]
    assert record.knot_count == 4 and record.participant_count == 2
    source = _arrays()
    for suffix in MEMBER_SUFFIXES:
        array = getattr(record, suffix)
        assert array.dtype == MEMBER_DTYPES[suffix]
        assert array.dtype.str == MEMBER_DTYPES[suffix].str
        assert np.array_equal(array, source[suffix])
        assert not array.flags.writeable
        assert array.flags.c_contiguous
        expected = (
            (4,) if suffix in ("knots_mm", "effect", "defined", "state") else (2, 4)
        )
        assert array.shape == expected
    assert all(
        np.isfinite(getattr(record, suffix)).all()
        for suffix in (
            "knots_mm",
            "effect",
            "participant_depth_mm",
            "participant_offset_mm",
            "participant_value",
        )
    )


def test_reader_round_trips_the_codec_and_orders_effects_by_effect_id() -> None:
    records = (_record(EFFECT_ID_BURST_4), _record(EFFECT_ID_INTERACTION))
    decoded = decode_effect_npz(encode_effect_npz(records))
    assert [record.effect_id for record in decoded] == sorted(
        [EFFECT_ID_BURST_4, EFFECT_ID_INTERACTION]
    )
    assert decoded == tuple(sorted(records, key=lambda record: record.effect_id))
    assert decode_effect_npz(encode_effect_npz(records)) == decoded
    assert decoded[0].shape == EffectShape(4, 2)


# ── the container envelope refusals (§4) ────────────────────────────────


def test_the_control_container_is_accepted() -> None:
    assert decode_effect_npz(_valid_container())


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
    with pytest.raises(NpzContainerError):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: _arrays()}, **tamper))


def test_reader_refuses_unsorted_members() -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()})
    order = sorted(members)
    with pytest.raises(NpzContainerError, match="ascending"):
        decode_effect_npz(_zip(members, order=[*order[1:], order[0]]))


def test_reader_refuses_a_duplicate_member() -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()})
    order = sorted(members)
    with pytest.warns(UserWarning, match="Duplicate name"):
        raw = _zip(members, order=[*order, order[0]])
    with pytest.raises(NpzContainerError, match="more than once"):
        decode_effect_npz(raw)


@pytest.mark.parametrize(
    "stray",
    [
        pytest.param("stray.npy", id="no-suffix"),
        pytest.param(f"{EFFECT_ID_BURST_4}__meta__.npy", id="unknown-suffix"),
        pytest.param(f"{EFFECT_ID_BURST_4}__knots.npy", id="near-miss-suffix"),
        pytest.param("__knots_mm.npy", id="empty-effect-id"),
        pytest.param(f"sub/{EFFECT_ID_BURST_4}__knots_mm.npy", id="nested-path"),
        pytest.param(f"{EFFECT_ID_BURST_4}__knots_mm.npy.bak", id="wrong-extension"),
    ],
)
def test_reader_refuses_a_member_outside_the_closed_set(stray: str) -> None:
    members = {**_members({EFFECT_ID_BURST_4: _arrays()}), stray: b"stray"}
    with pytest.raises(NpzContainerError):
        decode_effect_npz(_zip(members))


@pytest.mark.parametrize("suffix", ["knots_mm", "state", "participant_value"])
def test_reader_refuses_a_missing_member(suffix: str) -> None:
    members = _members({EFFECT_ID_BURST_4: _arrays()}, drop=[suffix])
    with pytest.raises(NpzContainerError, match="missing"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_a_directory_entry() -> None:
    members = {**_members({EFFECT_ID_BURST_4: _arrays()}), "extra/": b""}
    with pytest.raises(NpzContainerError, match="directory"):
        decode_effect_npz(_zip(members))


@pytest.mark.parametrize("dtype", ["<f4", "<i8", ">f8"])
def test_reader_refuses_a_wrong_dtype(dtype: str) -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__knots_mm.npy"] = _npy(
        np.asarray(arrays["knots_mm"], dtype=dtype)
    )
    with pytest.raises(NpzContainerError, match="dtype"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_a_shape_that_disagrees_with_the_other_members() -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__knots_mm.npy"] = _npy(
        np.array([10.0, 20.0, 30.0, 40.0, 50.0], dtype="<f8")
    )
    with pytest.raises(NpzSchemaError, match="shape"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_a_two_dimensional_per_knot_member() -> None:
    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__effect.npy"] = _npy(arrays["effect"].reshape(2, 2))
    with pytest.raises(NpzContainerError, match="dimensional"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_trailing_bytes_in_a_payload() -> None:
    members = _members(
        {EFFECT_ID_BURST_4: _arrays()},
        npy_kwargs={"effect": {"trailer": b"\x00\x00\x00\x00"}},
    )
    with pytest.raises(NpzContainerError, match="array byte"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_npy_format_2_and_fortran_order() -> None:
    members = _members(
        {EFFECT_ID_BURST_4: _arrays()}, npy_kwargs={"effect": {"version": (2, 0)}}
    )
    with pytest.raises(NpzContainerError, match="NPY format version"):
        decode_effect_npz(_zip(members))

    arrays = _arrays()
    members = _members({EFFECT_ID_BURST_4: arrays})
    members[f"{EFFECT_ID_BURST_4}__participant_value.npy"] = _npy(
        np.asfortranarray(arrays["participant_value"])
    )
    with pytest.raises(NpzContainerError, match="Fortran"):
        decode_effect_npz(_zip(members))


def test_reader_refuses_bytes_that_are_not_a_container() -> None:
    for data in (b"", b"not a zip at all", b"PK\x03\x04truncated"):
        with pytest.raises(NpzContainerError):
            decode_effect_npz(data)
    with pytest.raises(NpzContainerError, match="bytes"):
        decode_effect_npz("a string")  # type: ignore[arg-type]


def test_reader_refuses_a_corrupt_payload_crc() -> None:
    raw = bytearray(_valid_container())
    payload_start = raw.index(b"\x93NUMPY")
    raw[payload_start + 40] ^= 0xFF
    with pytest.raises(NpzContainerError):
        decode_effect_npz(bytes(raw))


def test_reader_refuses_a_noncanonical_byte_no_other_check_covers() -> None:
    """A structurally valid archive whose bytes are not the fixed rule is still refused."""
    raw = _raw({EFFECT_ID_BURST_4: _arrays()}, create_version=31)
    with pytest.raises(NpzContainerError, match="canonical"):
        decode_effect_npz(raw)


# ── the schema invariants of §3.2, on the writer and the reader ─────────


@pytest.mark.parametrize("code", [3, 7, 255])
def test_writer_and_reader_refuse_an_effect_code_outside_table_a(code: int) -> None:
    record = _record()
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    arrays["state"] = np.full(4, code, dtype="<u1")
    with pytest.raises(NpzSchemaError, match="table A"):
        encode_effect_npz([_record(arrays=arrays)])
    with pytest.raises(NpzSchemaError, match="table A"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


@pytest.mark.parametrize("code", [7, 9, 255])
def test_writer_and_reader_refuse_a_participant_code_outside_table_b(code: int) -> None:
    record = _record()
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    arrays["participant_state"] = np.full((2, 4), code, dtype="<u1")
    with pytest.raises(NpzSchemaError, match="table B"):
        encode_effect_npz([_record(arrays=arrays)])
    with pytest.raises(NpzSchemaError, match="table B"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_effect_mask_is_one_exactly_at_the_defined_code() -> None:
    # knot 1 carries state 1 (undefined), so a 1 in its mask is the mismatch.
    record = _tampered(_record(), "defined", np.s_[1], 1)
    with pytest.raises(NpzSchemaError, match="defined mask"):
        encode_effect_npz([record])
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    with pytest.raises(NpzSchemaError, match="defined mask"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_participant_mask_is_one_exactly_at_the_defined_code() -> None:
    record = _tampered(_record(), "participant_defined", np.s_[0, 1], 1)
    with pytest.raises(NpzSchemaError, match="defined mask"):
        encode_effect_npz([record])


def test_a_mask_value_outside_zero_and_one_is_refused() -> None:
    record = _tampered(_record(), "participant_defined", np.s_[1, 3], 2)
    with pytest.raises(NpzSchemaError, match="0/1 mask"):
        encode_effect_npz([record])


def test_an_undefined_position_carries_the_placeholder_and_never_a_number() -> None:
    # The effect's knot 1 is undefined (state 1); a number there is refused.
    record = _tampered(_record(), "effect", np.s_[1], 1.5)
    with pytest.raises(NpzSchemaError, match="placeholder"):
        encode_effect_npz([record])
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    with pytest.raises(NpzSchemaError, match="placeholder"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))

    # Row 0 knot 1 is aligned but undefined (state 3); only its value is the placeholder.
    record = _tampered(_record(), "participant_value", np.s_[0, 1], -0.25)
    with pytest.raises(NpzSchemaError, match="placeholder"):
        encode_effect_npz([record])


def test_a_defined_measured_zero_is_a_value_not_a_placeholder() -> None:
    decoded = decode_effect_npz(encode_effect_npz([_record()]))[0]
    # participant row 1, knot 2: mask 1 and state 0 with a measured value of exactly 0.0.
    assert decoded.participant_state[1, 2] == 0
    assert decoded.participant_defined[1, 2] == 1
    assert decoded.participant_value[1, 2] == 0.0
    assert decoded.participant_gate_index[1, 2] == 9


def test_an_unaligned_read_is_the_full_sentinel_tuple_only_there() -> None:
    row, column = 0, 3  # state 6 in the fixture: the unaligned read

    record = _tampered(_record(), "participant_gate_index", np.s_[row, column], 4)
    with pytest.raises(NpzSchemaError, match="gate sentinel"):
        encode_effect_npz([record])

    record = _tampered(_record(), "participant_depth_mm", np.s_[row, column], 12.5)
    with pytest.raises(NpzSchemaError, match="0.0 depth"):
        encode_effect_npz([record])

    record = _tampered(_record(), "participant_offset_mm", np.s_[row, column], 0.5)
    with pytest.raises(NpzSchemaError, match="0.0 depth"):
        encode_effect_npz([record])

    record = _tampered(_record(), "participant_value", np.s_[row, column], 0.1)
    with pytest.raises(NpzSchemaError, match="0.0 depth"):
        encode_effect_npz([record])

    record = _tampered(_record(), "participant_defined", np.s_[row, column], 1)
    with pytest.raises(NpzSchemaError, match="defined mask"):
        encode_effect_npz([record])

    # The reader refuses the same container the writer refused to produce.
    record = _tampered(_record(), "participant_gate_index", np.s_[row, column], 4)
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    with pytest.raises(NpzSchemaError, match="gate sentinel"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_minus_one_gate_sentinel_is_refused_on_an_aligned_read() -> None:
    # Row 0 knot 1 is aligned but undefined (state 3): -1 there is the sentinel misused.
    record = _tampered(_record(), "participant_gate_index", np.s_[0, 1], -1)
    with pytest.raises(NpzSchemaError, match="sentinel appears only"):
        encode_effect_npz([record])
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    with pytest.raises(NpzSchemaError, match="sentinel appears only"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_an_aligned_but_undefined_read_retains_its_gate_depth_and_offset() -> None:
    """The aligned-undefined case keeps the measurement's own coordinates (§3.2)."""
    decoded = decode_effect_npz(encode_effect_npz([_record()]))[0]
    assert decoded.participant_state[0, 1] == 3
    assert decoded.participant_defined[0, 1] == 0
    assert decoded.participant_value[0, 1] == 0.0
    assert decoded.participant_gate_index[0, 1] == 7
    assert decoded.participant_depth_mm[0, 1] == 7.2
    assert decoded.participant_offset_mm[0, 1] == pytest.approx(7.2 - 20.0)
    assert decoded.participant_depth_mm[0, 1] != 0.0


def test_a_sentinel_forced_onto_an_aligned_read_is_refused() -> None:
    """Zeroing an aligned read would make it read as unaligned; the code forbids that."""
    record = _record()
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    arrays["participant_gate_index"] = np.array(
        arrays["participant_gate_index"], dtype="<i4"
    )
    arrays["participant_depth_mm"] = np.array(
        arrays["participant_depth_mm"], dtype="<f8"
    )
    arrays["participant_offset_mm"] = np.array(
        arrays["participant_offset_mm"], dtype="<f8"
    )
    arrays["participant_gate_index"][0, 1] = -1
    arrays["participant_depth_mm"][0, 1] = 0.0
    arrays["participant_offset_mm"][0, 1] = 0.0
    with pytest.raises(NpzSchemaError):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


@pytest.mark.parametrize(
    "knots",
    [
        [10.0, 20.0, 20.0, 40.0],
        [40.0, 30.0, 20.0, 10.0],
        [10.0, 10.0, 30.0, 40.0],
    ],
)
def test_knots_must_be_strictly_increasing(knots: list[float]) -> None:
    record = _record()
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    arrays["knots_mm"] = np.array(knots, dtype="<f8")
    with pytest.raises(NpzSchemaError, match="strictly increasing"):
        encode_effect_npz([_record(arrays=arrays)])
    with pytest.raises(NpzSchemaError, match="strictly increasing"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


@pytest.mark.parametrize("suffix", ["knots_mm", "effect", "participant_depth_mm"])
@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_no_member_carries_a_non_finite_number(suffix: str, value: float) -> None:
    record = _tampered(
        _record(),
        suffix,
        np.s_[(0,) * (2 if suffix.startswith("participant") else 1)],
        value,
    )
    with pytest.raises(NpzSchemaError, match="non-finite"):
        encode_effect_npz([record])
    arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
    with pytest.raises(NpzSchemaError, match="non-finite"):
        decode_effect_npz(_raw({EFFECT_ID_BURST_4: arrays}))


def test_the_writer_refuses_a_wrong_input_dtype() -> None:
    record = _record()
    for suffix, dtype in (("state", "<i4"), ("knots_mm", ">f8"), ("defined", "<f8")):
        arrays = {name: getattr(record, name) for name in MEMBER_SUFFIXES}
        arrays[suffix] = np.asarray(arrays[suffix], dtype=dtype)
        with pytest.raises(ValueError, match="fixed little-endian dtype"):
            _record(arrays=arrays)


def test_the_record_is_frozen_and_refuses_a_rebind() -> None:
    record = _record()
    with pytest.raises(ValueError):
        record.effect_id = EFFECT_ID_INTERACTION  # type: ignore[misc]
    with pytest.raises(ValueError):
        record.knot_count = 8  # type: ignore[misc]


def test_the_record_owns_its_arrays_and_never_shares_the_caller_s_memory() -> None:
    """``array_field`` stores an owned, read-only C copy — not the caller's buffer."""
    source = _arrays()
    record = _record(arrays=source)
    for suffix in MEMBER_SUFFIXES:
        stored = getattr(record, suffix)
        assert stored.flags.owndata
        assert stored.flags.c_contiguous
        assert not stored.flags.writeable
        assert not np.shares_memory(stored, source[suffix])
    before = {suffix: getattr(record, suffix).copy() for suffix in MEMBER_SUFFIXES}

    source["knots_mm"][0] = 999.0
    source["participant_value"][0, 0] = 42.0

    for suffix in MEMBER_SUFFIXES:
        assert np.array_equal(getattr(record, suffix), before[suffix])
    assert record.knots_mm[0] == 10.0

    with pytest.raises(ValueError):
        record.knots_mm[0] = 1.0  # a stored field is read-only in place


def test_the_declared_counts_must_agree_with_the_arrays() -> None:
    with pytest.raises(NpzSchemaError, match="shape"):
        encode_effect_npz([_record(knot_count=5)])
    with pytest.raises(NpzSchemaError, match="shape"):
        encode_effect_npz([_record(participant_count=3)])
    for bad in (0, -1, True, 2.0):
        with pytest.raises(ValueError, match="positive integer"):
            encode_effect_npz([_record(knot_count=bad)])  # type: ignore[arg-type]


def test_the_writer_refuses_a_duplicate_effect_and_an_empty_container() -> None:
    with pytest.raises(NpzSchemaError, match="at least one effect"):
        encode_effect_npz([])
    with pytest.raises(NpzSchemaError, match="appears twice"):
        encode_effect_npz([_record(), _record()])
    with pytest.raises(NpzSchemaError, match="non-empty effect_id"):
        encode_effect_npz([_record("")])


def test_a_wrong_size_container_is_pinned_by_the_published_mirror() -> None:
    """The codec reads K and P from the shapes; the JSON mirror is what pins them."""
    small = _raw({EFFECT_ID_BURST_4: _arrays(knot_count=2, participant_count=1)})
    assert decode_effect_npz(small)[0].shape == EffectShape(2, 1)
    with pytest.raises(NpzSchemaError, match="published shape"):
        decode_effect_npz(small, expected={EFFECT_ID_BURST_4: (4, 2)})


@pytest.mark.parametrize(
    ("shapes", "message"),
    [
        pytest.param({"knot_count": 0, "participant_count": 1}, "zero-knot", id="K=0"),
        pytest.param(
            {"knot_count": 2, "participant_count": 0}, "zero-participant", id="P=0"
        ),
    ],
)
def test_reader_refuses_a_zero_knot_or_zero_participant_member(
    shapes: dict[str, int], message: str
) -> None:
    """``K`` and ``P`` are positive in the schema, so a ``(0,)`` or ``(0, K)`` member is refused.

    The refusal must be the codec's own typed :class:`NpzContainerError`, not the raw
    ``pydantic.ValidationError`` the record constructor would raise for a zero count — a reader
    that received a validation error could not tell a malformed container from a programming
    fault.
    """
    raw = _raw({EFFECT_ID_BURST_4: _arrays(**shapes)})
    with pytest.raises(NpzContainerError, match=message):
        decode_effect_npz(raw)


# ── the published mirror (§5.3/§5.4) ────────────────────────────────────


def test_expected_shape_mapping_accepts_agreement_and_refuses_drift() -> None:
    raw = encode_effect_npz([_record(), _record(EFFECT_ID_INTERACTION)])
    shapes = {
        EFFECT_ID_BURST_4: EffectShape(4, 2),
        EFFECT_ID_INTERACTION: (4, 2),
    }
    assert len(decode_effect_npz(raw, expected=shapes)) == 2

    with pytest.raises(NpzContainerError, match="does not name"):
        decode_effect_npz(raw, expected={EFFECT_ID_BURST_4: (4, 2)})
    with pytest.raises(NpzContainerError, match="missing effect"):
        decode_effect_npz(
            encode_effect_npz([_record()]),
            expected={EFFECT_ID_BURST_4: (4, 2), "absent": (1, 1)},
        )
    with pytest.raises(NpzSchemaError, match="published shape"):
        decode_effect_npz(
            encode_effect_npz([_record()]), expected={EFFECT_ID_BURST_4: (4, 3)}
        )
    with pytest.raises(NpzSchemaError, match="pair"):
        decode_effect_npz(
            encode_effect_npz([_record()]),
            expected={EFFECT_ID_BURST_4: (4,)},  # type: ignore[dict-item]
        )


def test_member_names_are_the_ten_closed_suffixes_of_one_effect() -> None:
    names = effect_member_names(EFFECT_ID_BURST_4)
    assert names == tuple(sorted(names))
    assert set(names) == {
        f"{EFFECT_ID_BURST_4}__{suffix}.npy" for suffix in MEMBER_SUFFIXES
    }
    assert len(names) == 10
    assert member_name(EFFECT_ID_BURST_4, "knots_mm") == (
        f"{EFFECT_ID_BURST_4}__knots_mm.npy"
    )
    with pytest.raises(NpzSchemaError, match="closed member suffixes"):
        member_name(EFFECT_ID_BURST_4, "knots")
    assert list(MEMBER_SUFFIXES) == sorted(MEMBER_SUFFIXES)
    assert len(MEMBER_DTYPES) == 10
    assert set(MEMBER_DTYPES) == set(MEMBER_SUFFIXES)


# ── the code vocabulary agrees with the backend (§8) ────────────────────


def test_the_state_code_tables_are_the_backend_enums_they_name() -> None:
    assert {code: EFFECT_STATE_CODES[code] for code in sorted(EFFECT_STATE_CODES)} == {
        index: state.value for index, state in enumerate(EffectState)
    }
    assert [PARTICIPANT_STATE_CODES[index] for index in range(len(MetricState))] == [
        state.value for state in MetricState
    ]
    assert UNALIGNED_READ_CODE not in {index for index in range(len(MetricState))}
    assert PARTICIPANT_STATE_CODES[UNALIGNED_READ_CODE] == "undefined-alignment"
    assert set(EFFECT_STATE_CODES) == {0, 1, 2}
    assert set(PARTICIPANT_STATE_CODES) == set(range(7))


def test_the_public_surface_is_only_the_container_codec() -> None:
    import udv_echo_process.analysis.sparse_sa5_npz as codec

    assert set(codec.__all__) == {
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
    }
    assert issubclass(NpzContainerError, SparseSa5NpzError)
    assert issubclass(NpzSchemaError, SparseSa5NpzError)
    assert issubclass(SparseSa5NpzError, ValueError)
