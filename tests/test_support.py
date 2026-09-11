"""Phase 2 sample-support and quality tests (plan §6.3, §11, §13).

Locks in the three-axis support contract: ``SupportKind`` (uint8) records
whether/where acquisition support exists, ``valid`` (bool) records whether the
current numeric value is usable, and ``QualityFlag`` (uint32) explains why a
value is invalid or what a transform did to it. The axes are never collapsed.
Unknown kinds or undeclared quality bits fail at construction with the
offending integer and its first index.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import QualityFlag, SampleSupport, SupportKind

#: reasons that make an invalid OBSERVED cell explainable (plan §6.3)
_ACQ_REASONS = [
    QualityFlag.DEVICE_INVALID,
    QualityFlag.LOW_SIGNAL,
    QualityFlag.SATURATED,
    QualityFlag.OUT_OF_RANGE,
    QualityFlag.ALIASED,
    QualityFlag.OUTLIER,
]

#: OR of every declared bit (they are distinct single bits, so sum == OR)
_DECLARED_MASK = sum(int(v) for v in QualityFlag.__members__.values())

_QUALITY_BITS = {
    "NONE": 0,
    "DEVICE_INVALID": 1 << 0,
    "LOW_SIGNAL": 1 << 1,
    "SATURATED": 1 << 2,
    "OUT_OF_RANGE": 1 << 3,
    "TIMESTAMP_ANOMALY": 1 << 4,
    "ALIASED": 1 << 5,
    "OUTLIER": 1 << 6,
    "GAP_TOO_LONG": 1 << 7,
    "FILTERED": 1 << 8,
    "EDGE_AFFECTED": 1 << 9,
    "EXTRAPOLATED": 1 << 10,
    "REINTERPOLATED": 1 << 11,
    "TIME_ALIGNED": 1 << 12,
    "ALIGNMENT_UNCERTAIN": 1 << 13,
}


def _mk(kind, valid, quality):
    """Build a ``SampleSupport`` from array-likes at the field dtypes."""
    return SampleSupport(
        kind=np.asarray(kind, dtype=np.uint8),
        valid=np.asarray(valid, dtype=bool),
        quality=np.asarray(quality, dtype=np.uint32),
    )


def _observed(shape):
    """All-OBSERVED, all-valid, all-NONE support of ``shape``."""
    return _mk(
        np.full(shape, int(SupportKind.OBSERVED), np.uint8),
        np.ones(shape, bool),
        np.zeros(shape, np.uint32),
    )


# ── enums ──────────────────────────────────────────────────────────────


def test_support_kind_is_intenum_with_expected_values():
    assert issubclass(SupportKind, IntEnum)
    assert int(SupportKind.MISSING) == 0
    assert int(SupportKind.OBSERVED) == 1
    assert int(SupportKind.INTERPOLATED) == 2
    assert int(SupportKind.EXTRAPOLATED) == 3


def test_quality_flag_is_intflag_with_14_declared_bits():
    assert issubclass(QualityFlag, IntFlag)
    members = {name: int(value) for name, value in QualityFlag.__members__.items()}
    assert members == _QUALITY_BITS
    assert len(_QUALITY_BITS) == 15  # NONE + 14 declared bits
    assert _DECLARED_MASK == (1 << 14) - 1


# ── dtype budget (plan §13) ────────────────────────────────────────────


def test_support_dtype_budget_is_uint8_bool_uint32():
    s = _observed((2, 3))
    assert s.kind.dtype == np.uint8
    assert s.kind.itemsize == 1
    assert s.valid.dtype == np.bool_
    assert s.valid.itemsize == 1
    assert s.quality.dtype == np.uint32
    assert s.quality.itemsize == 4
    assert s.kind.nbytes + s.valid.nbytes + s.quality.nbytes == 6 * 6


# ── shape agreement ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "arr"),
    [
        ("valid", np.ones((2, 3), bool)),
        ("quality", np.zeros((3, 2), np.uint32)),
    ],
)
def test_same_shape_required(field, arr):
    box = {
        "kind": np.ones((2, 2), np.uint8),
        "valid": np.ones((2, 2), bool),
        "quality": np.zeros((2, 2), np.uint32),
    }
    box[field] = arr
    with pytest.raises(ValidationError) as ei:
        SampleSupport(**box)
    msg = str(ei.value)
    assert "shapes must be identical" in msg
    assert "kind" in msg and "valid" in msg and "quality" in msg
    assert str(tuple(arr.shape)) in msg


@pytest.mark.parametrize("field", ["kind", "valid", "quality"])
def test_components_must_be_two_dimensional(field):
    box = {
        "kind": np.zeros((2, 2), np.uint8),
        "valid": np.zeros((2, 2), bool),
        "quality": np.zeros((2, 2), np.uint32),
    }
    box[field] = np.zeros(2, box[field].dtype)
    with pytest.raises(ValidationError) as ei:
        SampleSupport(**box)
    assert "rank 2" in str(ei.value)


# ── unknown support values ─────────────────────────────────────────────


def test_unknown_support_value_reports_integer_and_first_index():
    kind = np.zeros((2, 3), np.uint8)  # all MISSING
    valid = np.zeros((2, 3), bool)
    quality = np.zeros((2, 3), np.uint32)
    kind[0, 2] = 4
    kind[1, 0] = 9  # a later unknown must not be reported first
    with pytest.raises(ValidationError) as ei:
        _mk(kind, valid, quality)
    msg = str(ei.value)
    assert "unknown support value 4" in msg
    assert "index 2" in msg
    assert "time=0" in msg and "gate=2" in msg


def test_unknown_support_value_255_rejected():
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((1, 1), 255, np.uint8),
            np.zeros((1, 1), bool),
            np.zeros((1, 1), np.uint32),
        )
    assert "unknown support value 255" in str(ei.value)


# ── unknown quality bits ───────────────────────────────────────────────


def test_undeclared_quality_bit_reports_integer_and_first_index():
    quality = np.zeros((2, 2), np.uint32)
    quality[1, 1] = (1 << 14) | int(QualityFlag.SATURATED)
    with pytest.raises(ValidationError) as ei:
        _mk(np.ones((2, 2), np.uint8), np.ones((2, 2), bool), quality)
    msg = str(ei.value)
    assert "undeclared quality bits" in msg
    assert str((1 << 14) | int(QualityFlag.SATURATED)) in msg
    assert "index 3" in msg
    assert "time=1" in msg and "gate=1" in msg


def test_all_declared_quality_bits_accepted():
    s = _mk(
        np.ones((1, 2), np.uint8),
        np.ones((1, 2), bool),
        np.full((1, 2), _DECLARED_MASK, np.uint32),
    )
    assert int(s.quality[0, 0]) == _DECLARED_MASK


# ── relation invariants ────────────────────────────────────────────────


def test_missing_must_be_invalid():
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((2, 2), int(SupportKind.MISSING), np.uint8),
            np.ones((2, 2), bool),
            np.zeros((2, 2), np.uint32),
        )
    msg = str(ei.value)
    assert "MISSING support must have valid=False" in msg
    assert "4 cells" in msg
    assert "first at (time=0, gate=0)" in msg


def test_missing_invalid_accepted():
    s = _mk(
        np.zeros((1, 1), np.uint8),
        np.zeros((1, 1), bool),
        np.zeros((1, 1), np.uint32),
    )
    assert int(s.kind[0, 0]) == int(SupportKind.MISSING)


@pytest.mark.parametrize(
    "kind_value",
    [SupportKind.INTERPOLATED, SupportKind.EXTRAPOLATED],
)
def test_estimated_support_must_be_valid(kind_value):
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((2, 2), int(kind_value), np.uint8),
            np.zeros((2, 2), bool),
            np.full((2, 2), int(QualityFlag.EXTRAPOLATED), np.uint32),
        )
    msg = str(ei.value)
    assert "must have valid=True" in msg
    assert "4 cells" in msg and "(time=0, gate=0)" in msg


@pytest.mark.parametrize(
    "kind_value", [SupportKind.INTERPOLATED, SupportKind.EXTRAPOLATED]
)
def test_estimated_support_valid_accepted(kind_value):
    s = _mk(
        np.full((1, 1), int(kind_value), np.uint8),
        np.ones((1, 1), bool),
        np.full((1, 1), int(QualityFlag.EXTRAPOLATED), np.uint32),
    )
    assert int(s.kind[0, 0]) == int(kind_value)


def test_invalid_observed_requires_acquisition_reason():
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((2, 2), int(SupportKind.OBSERVED), np.uint8),
            np.zeros((2, 2), bool),
            np.zeros((2, 2), np.uint32),
        )
    msg = str(ei.value)
    assert "acquisition-quality reason" in msg
    assert "4 cells" in msg and "first at (time=0, gate=0)" in msg


def test_invalid_observed_with_non_acquisition_flag_rejected():
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((1, 1), int(SupportKind.OBSERVED), np.uint8),
            np.zeros((1, 1), bool),
            np.full((1, 1), int(QualityFlag.FILTERED), np.uint32),
        )
    assert "acquisition-quality reason" in str(ei.value)


@pytest.mark.parametrize("reason", _ACQ_REASONS, ids=lambda r: r.name)
def test_invalid_observed_accepts_each_acquisition_reason(reason):
    s = _mk(
        np.full((1, 1), int(SupportKind.OBSERVED), np.uint8),
        np.zeros((1, 1), bool),
        np.full((1, 1), int(reason), np.uint32),
    )
    assert int(s.quality[0, 0]) == int(reason)


def test_extrapolated_support_requires_flag():
    with pytest.raises(ValidationError) as ei:
        _mk(
            np.full((1, 2), int(SupportKind.EXTRAPOLATED), np.uint8),
            np.ones((1, 2), bool),
            np.zeros((1, 2), np.uint32),
        )
    msg = str(ei.value)
    assert "EXTRAPOLATED support must include" in msg
    assert "2 cells" in msg


def test_extrapolated_support_with_flag_accepted():
    s = _mk(
        np.full((1, 2), int(SupportKind.EXTRAPOLATED), np.uint8),
        np.ones((1, 2), bool),
        np.full((1, 2), int(QualityFlag.EXTRAPOLATED), np.uint32),
    )
    assert int(s.quality[0, 0]) & int(QualityFlag.EXTRAPOLATED)


def test_clean_observation_none_quality_accepted():
    s = _observed((1, 2))
    assert int(s.quality[0, 0]) == int(QualityFlag.NONE)


# ── ownership across every nested array ────────────────────────────────


@pytest.mark.parametrize("field", ["kind", "valid", "quality"])
def test_support_owns_each_array(field):
    sources = {
        "kind": np.array([[1, 0], [2, 3]], np.uint8),
        "valid": np.array([[True, False], [True, True]], bool),
        "quality": np.array([[0, 0], [0, int(QualityFlag.EXTRAPOLATED)]], np.uint32),
    }
    src = sources[field]
    s = SampleSupport(**sources)
    out = getattr(s, field)
    assert np.shares_memory(src, out) is False
    assert out.flags["OWNDATA"] is True
    assert out.flags["C_CONTIGUOUS"] is True
    assert out.flags["WRITEABLE"] is False
    with pytest.raises(ValueError):
        out[...] = out
    snapshot = out.copy()
    src[...] = 0
    assert np.array_equal(out, snapshot)


def test_support_owns_copy_from_list_like():
    s = SampleSupport(kind=[[1, 0]], valid=[[True, False]], quality=[[0, 0]])
    assert s.kind.flags["OWNDATA"] is True
    assert s.kind.flags["WRITEABLE"] is False
    assert np.shares_memory(s.kind, s.valid) is False
