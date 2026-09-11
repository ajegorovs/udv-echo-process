"""Phase 2 acquisition-index and ``SignalData`` tests (plan §6.4, §6.5, §13).

Covers the row-level acquisition sentinel rules and every ``SignalData``
payload invariant: shape/rank, finite strictly increasing axes, the
value/validity relation, the observed-row acquisition rule, and owned
read-only arrays with no memory sharing. Factory tests prove the
``observed_signal`` / ``missing_signal`` helpers construct through the models
instead of bypassing them.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    AcquisitionIndex,
    QualityFlag,
    SampleSupport,
    SignalData,
    SupportKind,
    missing_signal,
    observed_signal,
)


def _support(kind, valid, quality):
    return SampleSupport(
        kind=np.asarray(kind, dtype=np.uint8),
        valid=np.asarray(valid, dtype=bool),
        quality=np.asarray(quality, dtype=np.uint32),
    )


def _observed_support(shape):
    return _support(
        np.full(shape, int(SupportKind.OBSERVED), np.uint8),
        np.ones(shape, bool),
        np.zeros(shape, np.uint32),
    )


def _acq_full():
    return AcquisitionIndex(
        sample_id=np.array([0, 1, 2], np.int64),
        acquisition_time_s=np.array([0.0, 0.5, 1.0], np.float64),
        round_id=np.array([0, 0, 1], np.int64),
        visit_id=np.array([0, 0, 1], np.int64),
        profile_in_visit=np.array([0, 0, 0], np.int64),
    )


def _make_signal(**overrides):
    base = {
        "time_s": np.array([0.0, 1.0], np.float64),
        "gate_depths_mm": np.array([5.0, 10.0], np.float64),
        "values": np.array([[1.0, 2.0], [3.0, 4.0]], np.float64),
        "support": _observed_support((2, 2)),
    }
    base.update(overrides)
    return SignalData(**base)


def _resolve(obj, path):
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


# ── AcquisitionIndex: shapes and lengths ───────────────────────────────


def test_acquisition_full_valid():
    a = _acq_full()
    assert list(a.sample_id) == [0, 1, 2]
    assert a.round_id is not None
    assert a.profile_in_visit is not None


def test_acquisition_optionals_are_independently_optional():
    base = {
        "sample_id": np.array([0, 1], np.int64),
        "acquisition_time_s": np.array([0.0, 1.0], np.float64),
    }
    only_round = AcquisitionIndex(**base, round_id=np.array([0, -1], np.int64))
    assert only_round.visit_id is None
    assert only_round.profile_in_visit is None
    only_visit = AcquisitionIndex(**base, visit_id=np.array([-1, 0], np.int64))
    assert only_visit.round_id is None
    both = AcquisitionIndex(
        **base,
        visit_id=np.array([-1, 0], np.int64),
        profile_in_visit=np.array([-1, 0], np.int64),
    )
    assert both.profile_in_visit is not None


def test_acquisition_requires_core_arrays():
    with pytest.raises(ValidationError):
        AcquisitionIndex(sample_id=np.array([0], np.int64))
    with pytest.raises(ValidationError):
        AcquisitionIndex(acquisition_time_s=np.array([0.0], np.float64))


def test_acquisition_core_length_mismatch_rejected():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, 1, 2], np.int64),
            acquisition_time_s=np.array([0.0, 1.0], np.float64),
        )
    msg = str(ei.value)
    assert "share length" in msg
    assert "sample_id=3" in msg and "acquisition_time_s=2" in msg


def test_acquisition_optional_length_mismatch_rejected():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, 1], np.int64),
            acquisition_time_s=np.array([0.0, 1.0], np.float64),
            round_id=np.array([0, 0, 0], np.int64),
        )
    assert "round_id=3" in str(ei.value)


def test_acquisition_rank_invariant():
    with pytest.raises(ValidationError):
        AcquisitionIndex(
            sample_id=np.zeros((1, 2), np.int64),
            acquisition_time_s=np.zeros(2, np.float64),
        )


# ── AcquisitionIndex: sample_id rules ──────────────────────────────────


def test_acquisition_rejects_sample_id_below_minus_one():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, -2], np.int64),
            acquisition_time_s=np.array([0.0, np.nan], np.float64),
        )
    msg = str(ei.value)
    assert "sample_id must be >= 0 or exactly -1" in msg
    assert "-2" in msg and "index 1" in msg


def test_acquisition_rejects_duplicate_sample_id():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, 1, 1], np.int64),
            acquisition_time_s=np.array([0.0, 0.5, 1.0], np.float64),
        )
    msg = str(ei.value)
    assert "duplicate sample_id 1" in msg
    assert "index 2" in msg


@pytest.mark.parametrize(
    ("sample_id", "times"),
    [
        (np.array([0, -1], np.int64), np.array([0.0, 0.5], np.float64)),
        (np.array([0, 1], np.int64), np.array([0.0, np.nan], np.float64)),
    ],
    ids=["synthetic-id-with-finite-time", "real-id-with-nan-time"],
)
def test_acquisition_sentinel_iff_nan_time(sample_id, times):
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(sample_id=sample_id, acquisition_time_s=times)
    msg = str(ei.value)
    assert "NaN acquisition time" in msg
    assert "first at index" in msg


# ── AcquisitionIndex: time ordering ────────────────────────────────────


@pytest.mark.parametrize(
    ("times", "expected_values"),
    [
        (np.array([0.0, 0.5, 0.5]), "0.5 then 0.5"),
        (np.array([0.0, 1.0, 0.5]), "1.0 then 0.5"),
    ],
    ids=["duplicate", "decreasing"],
)
def test_acquisition_times_must_be_strictly_increasing(times, expected_values):
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.arange(3, dtype=np.int64),
            acquisition_time_s=times.astype(np.float64),
        )
    msg = str(ei.value)
    assert "finite acquisition times must be strictly increasing" in msg
    assert "row 2" in msg
    assert expected_values in msg


# ── AcquisitionIndex: optional id rules ────────────────────────────────


def test_acquisition_optional_id_below_minus_one_rejected():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, 1], np.int64),
            acquisition_time_s=np.array([0.0, 1.0], np.float64),
            round_id=np.array([0, -5], np.int64),
        )
    msg = str(ei.value)
    assert "round_id must be >= 0 or exactly -1" in msg
    assert "-5" in msg and "index 1" in msg


def test_acquisition_profile_in_visit_requires_visit_id():
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0], np.int64),
            acquisition_time_s=np.array([0.0], np.float64),
            profile_in_visit=np.array([0], np.int64),
        )
    assert "profile_in_visit requires visit_id" in str(ei.value)


@pytest.mark.parametrize("bad_field", ["round_id", "visit_id", "profile_in_visit"])
def test_acquisition_synthetic_row_must_be_sentinel_in_every_optional(bad_field):
    opts = {
        "round_id": np.array([0, -1], np.int64),
        "visit_id": np.array([0, -1], np.int64),
        "profile_in_visit": np.array([0, -1], np.int64),
    }
    opts[bad_field] = np.array([0, 5], np.int64)
    with pytest.raises(ValidationError) as ei:
        AcquisitionIndex(
            sample_id=np.array([0, -1], np.int64),
            acquisition_time_s=np.array([0.0, np.nan], np.float64),
            **opts,
        )
    msg = str(ei.value)
    assert "synthetic row" in msg
    assert bad_field in msg and "5" in msg


def test_acquisition_synthetic_row_valid_with_all_sentinels():
    a = AcquisitionIndex(
        sample_id=np.array([0, -1], np.int64),
        acquisition_time_s=np.array([0.0, np.nan], np.float64),
        round_id=np.array([0, -1], np.int64),
        visit_id=np.array([0, -1], np.int64),
        profile_in_visit=np.array([0, -1], np.int64),
    )
    assert a.sample_id[1] == -1
    assert np.isnan(a.acquisition_time_s[1])


# ── AcquisitionIndex: dtype budget (plan §13) ──────────────────────────


def test_acquisition_dtype_budget():
    a = _acq_full()
    assert a.sample_id.dtype == np.int64
    assert a.acquisition_time_s.dtype == np.float64
    for name in ("round_id", "visit_id", "profile_in_visit"):
        assert getattr(a, name).dtype == np.int64
    assert a.sample_id.nbytes + a.acquisition_time_s.nbytes == 16 * 3
    optional = sum(
        getattr(a, name).nbytes for name in ("round_id", "visit_id", "profile_in_visit")
    )
    assert optional == 24 * 3


# ── AcquisitionIndex: ownership ────────────────────────────────────────


_ACQ_PATHS = [
    "sample_id",
    "acquisition_time_s",
    "round_id",
    "visit_id",
    "profile_in_visit",
]


@pytest.mark.parametrize("path", _ACQ_PATHS)
def test_acquisition_owns_every_array(path):
    raw = {
        "sample_id": np.array([0, 1], np.int64),
        "acquisition_time_s": np.array([0.0, 1.0], np.float64),
        "round_id": np.array([0, -1], np.int64),
        "visit_id": np.array([0, -1], np.int64),
        "profile_in_visit": np.array([0, -1], np.int64),
    }
    src = raw[path]
    model = AcquisitionIndex(**raw)
    out = _resolve(model, path)
    assert np.shares_memory(src, out) is False
    assert out.flags["OWNDATA"] is True
    assert out.flags["C_CONTIGUOUS"] is True
    assert out.flags["WRITEABLE"] is False
    with pytest.raises(ValueError):
        out[...] = out
    snapshot = out.copy()
    src[...] = 12345
    assert np.array_equal(out, snapshot)


# ── SignalData: shape and required fields ──────────────────────────────


def test_signal_valid_all_observed():
    s = _make_signal()
    assert s.values.shape == (2, 2)
    assert s.acquisition is None


def test_signal_requires_every_payload_field():
    with pytest.raises(ValidationError):
        SignalData()
    with pytest.raises(ValidationError):
        SignalData(time_s=[0.0], gate_depths_mm=[1.0], values=[[1.0]])


@pytest.mark.parametrize("field", ["time_s", "gate_depths_mm"])
def test_signal_axes_must_be_one_dimensional(field):
    with pytest.raises(ValidationError) as ei:
        _make_signal(**{field: np.zeros((1, 2), np.float64)})
    msg = str(ei.value)
    assert field in msg and "rank 1" in msg


def test_signal_values_must_be_two_dimensional():
    with pytest.raises(ValidationError) as ei:
        _make_signal(values=np.zeros(3, np.float64))
    assert "rank 2" in str(ei.value)


def test_signal_minimal_single_cell_accepted():
    s = _make_signal(
        time_s=np.array([0.0]),
        gate_depths_mm=np.array([5.0]),
        values=np.array([[1.0]]),
        support=_observed_support((1, 1)),
    )
    assert s.values.shape == (1, 1)


def test_signal_rejects_empty_time_axis():
    with pytest.raises(ValidationError) as ei:
        _make_signal(
            time_s=np.array([], np.float64),
            values=np.zeros((0, 2), np.float64),
            support=_observed_support((0, 2)),
        )
    assert "T >= 1" in str(ei.value)


def test_signal_rejects_empty_gate_axis():
    with pytest.raises(ValidationError) as ei:
        _make_signal(
            gate_depths_mm=np.array([], np.float64),
            values=np.zeros((2, 0), np.float64),
            support=_observed_support((2, 0)),
        )
    assert "G >= 1" in str(ei.value)


def test_signal_values_shape_mismatch_rejected():
    with pytest.raises(ValidationError) as ei:
        _make_signal(values=np.zeros((3, 2), np.float64))
    msg = str(ei.value)
    assert "values must have shape (T, G)" in msg
    assert "(2, 2)" in msg and "(3, 2)" in msg


def test_signal_support_shape_mismatch_rejected():
    with pytest.raises(ValidationError) as ei:
        _make_signal(support=_observed_support((3, 3)))
    assert "support shape must equal values shape" in str(ei.value)


# ── SignalData: axis finiteness and ordering ───────────────────────────


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_signal_time_must_be_finite(bad):
    with pytest.raises(ValidationError) as ei:
        _make_signal(time_s=np.array([0.0, bad], np.float64))
    msg = str(ei.value)
    assert "time_s must be finite" in msg
    assert "index 1" in msg


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_signal_gate_depths_must_be_finite(bad):
    with pytest.raises(ValidationError) as ei:
        _make_signal(gate_depths_mm=np.array([5.0, bad], np.float64))
    assert "gate_depths_mm must be finite" in str(ei.value)


def test_signal_time_duplicate_reports_index_and_adjacent_values():
    with pytest.raises(ValidationError) as ei:
        _make_signal(time_s=np.array([0.5, 0.5], np.float64))
    msg = str(ei.value)
    assert "time_s must be strictly increasing" in msg
    assert "index 1" in msg
    assert "0.5 then 0.5" in msg


def test_signal_gate_depths_duplicate_reports_index_and_adjacent_values():
    with pytest.raises(ValidationError) as ei:
        _make_signal(gate_depths_mm=np.array([5.0, 5.0], np.float64))
    msg = str(ei.value)
    assert "gate_depths_mm must be strictly increasing" in msg
    assert "index 1" in msg and "5.0 then 5.0" in msg


# ── SignalData: value/validity relation ────────────────────────────────


def test_signal_valid_true_requires_finite_value():
    values = np.array([[1.0, 2.0], [np.nan, 4.0]], np.float64)
    with pytest.raises(ValidationError) as ei:
        _make_signal(values=values)
    msg = str(ei.value)
    assert "valid=True needs a finite value" in msg
    assert "1 cell" in msg and "(time=1, gate=0)" in msg


def test_signal_valid_false_requires_nan():
    support = _support(
        np.array([[1, 1], [1, 1]], np.uint8),
        np.array([[True, True], [False, True]], bool),
        np.array([[0, 0], [int(QualityFlag.OUTLIER), 0]], np.uint32),
    )
    values = np.array([[1.0, 2.0], [3.0, 4.0]], np.float64)
    with pytest.raises(ValidationError) as ei:
        _make_signal(values=values, support=support)
    msg = str(ei.value)
    assert "valid=False needs NaN" in msg
    assert "1 cell" in msg and "(time=1, gate=0)" in msg


def test_signal_invalid_observation_inside_observed_accepted():
    support = _support(
        np.array([[1, 1], [1, 1]], np.uint8),
        np.array([[True, True], [False, True]], bool),
        np.array([[0, 0], [int(QualityFlag.SATURATED), 0]], np.uint32),
    )
    values = np.array([[1.0, 2.0], [np.nan, 4.0]], np.float64)
    s = _make_signal(values=values, support=support)
    assert s.support.kind[1, 0] == SupportKind.OBSERVED
    assert s.support.valid[1, 0] == np.bool_(False)
    assert np.isnan(s.values[1, 0])


@pytest.mark.parametrize("bad", [np.inf, -np.inf])
def test_signal_infinity_always_rejected(bad):
    values = np.array([[bad, 2.0], [3.0, 4.0]], np.float64)
    with pytest.raises(ValidationError):
        _make_signal(values=values)


def test_signal_infinity_rejected_even_when_support_invalid():
    support = _support(
        np.array([[1, 1], [1, 1]], np.uint8),
        np.array([[False, True], [True, True]], bool),
        np.array([[int(QualityFlag.OUTLIER), 0], [0, 0]], np.uint32),
    )
    values = np.array([[np.inf, 2.0], [3.0, 4.0]], np.float64)
    with pytest.raises(ValidationError):
        _make_signal(values=values, support=support)


# ── SignalData: acquisition cross-checks ───────────────────────────────


def test_signal_acquisition_length_must_match_t():
    acq = AcquisitionIndex(
        sample_id=np.array([0, 1, 2], np.int64),
        acquisition_time_s=np.array([0.0, 1.0, 2.0], np.float64),
    )
    with pytest.raises(ValidationError) as ei:
        _make_signal(acquisition=acq)
    assert "length T = 2" in str(ei.value)


def test_signal_observed_row_needs_real_index():
    acq = AcquisitionIndex(
        sample_id=np.array([-1, 1], np.int64),
        acquisition_time_s=np.array([np.nan, 1.0], np.float64),
    )
    with pytest.raises(ValidationError) as ei:
        _make_signal(acquisition=acq)
    msg = str(ei.value)
    assert "row 0" in msg
    assert "OBSERVED" in msg


def test_signal_row_without_observed_gate_must_be_synthetic():
    support = _support(
        np.array([[0, 0], [1, 1]], np.uint8),
        np.array([[False, False], [True, True]], bool),
        np.zeros((2, 2), np.uint32),
    )
    values = np.array([[np.nan, np.nan], [3.0, 4.0]], np.float64)
    acq = AcquisitionIndex(
        sample_id=np.array([0, 1], np.int64),
        acquisition_time_s=np.array([0.0, 1.0], np.float64),
    )
    with pytest.raises(ValidationError) as ei:
        _make_signal(support=support, values=values, acquisition=acq)
    msg = str(ei.value)
    assert "no OBSERVED gate" in msg
    assert "row 0" in msg and "sample_id=-1" in msg


def test_signal_row_with_only_invalid_observations_needs_real_index():
    support = _support(
        np.array([[1], [1]], np.uint8),
        np.array([[False], [True]], bool),
        np.array([[int(QualityFlag.LOW_SIGNAL)], [0]], np.uint32),
    )
    values = np.array([[np.nan], [4.0]], np.float64)
    acq = AcquisitionIndex(
        sample_id=np.array([-1, 1], np.int64),
        acquisition_time_s=np.array([np.nan, 1.0], np.float64),
    )
    with pytest.raises(ValidationError) as ei:
        _make_signal(
            time_s=np.array([0.0, 1.0]),
            gate_depths_mm=np.array([5.0]),
            values=values,
            support=support,
            acquisition=acq,
        )
    assert "row 0" in str(ei.value)


def test_signal_invalid_observed_row_accepts_real_index():
    support = _support(
        np.array([[1], [1]], np.uint8),
        np.array([[False], [True]], bool),
        np.array([[int(QualityFlag.LOW_SIGNAL)], [0]], np.uint32),
    )
    values = np.array([[np.nan], [4.0]], np.float64)
    acq = AcquisitionIndex(
        sample_id=np.array([0, 1], np.int64),
        acquisition_time_s=np.array([0.25, 1.0], np.float64),
    )
    s = _make_signal(
        time_s=np.array([0.0, 1.0]),
        gate_depths_mm=np.array([5.0]),
        values=values,
        support=support,
        acquisition=acq,
    )
    assert s.support.valid[0, 0] == np.bool_(False)
    assert s.acquisition.sample_id[0] == 0


def test_signal_mixed_support_row_keeps_real_index_when_any_observed():
    support = _support(
        np.array([[1, 0], [1, 1]], np.uint8),
        np.array([[True, False], [True, True]], bool),
        np.zeros((2, 2), np.uint32),
    )
    values = np.array([[1.0, np.nan], [3.0, 4.0]], np.float64)
    acq = AcquisitionIndex(
        sample_id=np.array([0, 1], np.int64),
        acquisition_time_s=np.array([0.0, 1.0], np.float64),
    )
    s = _make_signal(support=support, values=values, acquisition=acq)
    assert s.acquisition.sample_id[0] == 0


# ── SignalData: ownership across every nested array ────────────────────


def _raw_signal_arrays():
    return {
        "time_s": np.array([0.0, 1.0], np.float64),
        "gate_depths_mm": np.array([5.0, 10.0], np.float64),
        "values": np.array([[1.0, 2.0], [3.0, 4.0]], np.float64),
        "support.kind": np.full((2, 2), int(SupportKind.OBSERVED), np.uint8),
        "support.valid": np.ones((2, 2), bool),
        "support.quality": np.zeros((2, 2), np.uint32),
        "acquisition.sample_id": np.array([0, 1], np.int64),
        "acquisition.acquisition_time_s": np.array([0.0, 1.0], np.float64),
        "acquisition.round_id": np.array([0, 0], np.int64),
        "acquisition.visit_id": np.array([0, 0], np.int64),
        "acquisition.profile_in_visit": np.array([0, 1], np.int64),
    }


_SIGNAL_PATHS = list(_raw_signal_arrays())


def _signal_from_raw(raw):
    support = SampleSupport(
        kind=raw["support.kind"],
        valid=raw["support.valid"],
        quality=raw["support.quality"],
    )
    acq = AcquisitionIndex(
        sample_id=raw["acquisition.sample_id"],
        acquisition_time_s=raw["acquisition.acquisition_time_s"],
        round_id=raw["acquisition.round_id"],
        visit_id=raw["acquisition.visit_id"],
        profile_in_visit=raw["acquisition.profile_in_visit"],
    )
    return SignalData(
        time_s=raw["time_s"],
        gate_depths_mm=raw["gate_depths_mm"],
        values=raw["values"],
        support=support,
        acquisition=acq,
    )


@pytest.mark.parametrize("path", _SIGNAL_PATHS)
def test_signal_owns_every_nested_array(path):
    raw = _raw_signal_arrays()
    src = raw[path]
    model = _signal_from_raw(raw)
    out = _resolve(model, path)
    assert np.shares_memory(src, out) is False
    assert out.flags["OWNDATA"] is True
    assert out.flags["C_CONTIGUOUS"] is True
    assert out.flags["WRITEABLE"] is False
    with pytest.raises(ValueError):
        out[...] = out
    snapshot = out.copy()
    src[...] = 7
    assert np.array_equal(out, snapshot)


def test_signal_nested_arrays_do_not_share_memory():
    s = _signal_from_raw(_raw_signal_arrays())
    assert np.shares_memory(s.values, s.support.kind) is False
    assert np.shares_memory(s.time_s, s.values) is False
    assert np.shares_memory(s.values, s.acquisition.sample_id) is False


# ── factories ──────────────────────────────────────────────────────────


def test_observed_signal_all_finite_is_clean_observed():
    s = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]])
    assert (s.support.kind == int(SupportKind.OBSERVED)).all()
    assert s.support.valid.all()
    assert (s.support.quality == 0).all()
    assert s.acquisition is None


def test_observed_signal_rejects_nan_without_reason():
    with pytest.raises(ValidationError):
        observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, np.nan], [3.0, 4.0]])


def test_observed_signal_accepts_nan_with_reason():
    s = observed_signal(
        [0.0, 1.0],
        [5.0, 10.0],
        [[1.0, np.nan], [3.0, 4.0]],
        quality=[[0, int(QualityFlag.OUTLIER)], [0, 0]],
    )
    assert s.support.kind[0, 1] == SupportKind.OBSERVED
    assert s.support.valid[0, 1] == np.bool_(False)
    assert np.isnan(s.values[0, 1])


def test_observed_signal_validates_time_order():
    with pytest.raises(ValidationError) as ei:
        observed_signal([0.0, 0.0], [5.0], [[1.0], [2.0]])
    assert "strictly increasing" in str(ei.value)


def test_observed_signal_rejects_infinity():
    with pytest.raises(ValidationError):
        observed_signal([0.0, 1.0], [5.0], [[np.inf], [2.0]])


def test_observed_signal_rejects_non_2d_values():
    with pytest.raises(ValidationError):
        observed_signal([0.0, 1.0], [5.0], [1.0, 2.0])


def test_observed_signal_output_is_owned():
    t = np.array([0.0, 1.0])
    g = np.array([1.0, 2.0])
    v = np.array([[1.0, 2.0], [3.0, 4.0]])
    s = observed_signal(t, g, v)
    for src, out in ((t, s.time_s), (g, s.gate_depths_mm), (v, s.values)):
        assert np.shares_memory(src, out) is False
        assert out.flags["OWNDATA"] is True
        assert out.flags["C_CONTIGUOUS"] is True
        assert out.flags["WRITEABLE"] is False


def test_missing_signal_is_all_missing():
    s = missing_signal([0.0, 1.0], [5.0, 10.0])
    assert s.values.shape == (2, 2)
    assert np.isnan(s.values).all()
    assert (s.support.kind == int(SupportKind.MISSING)).all()
    assert not s.support.valid.any()
    assert (s.support.quality == 0).all()
    assert s.acquisition is None


def test_missing_signal_validates_axes():
    with pytest.raises(ValidationError) as ei:
        missing_signal([0.0, 0.0], [5.0])
    assert "strictly increasing" in str(ei.value)
    with pytest.raises(ValidationError):
        missing_signal([0.0, 1.0], [5.0, np.inf])


def test_missing_signal_rejects_empty_axis():
    with pytest.raises(ValidationError):
        missing_signal([], [5.0])


def test_missing_signal_output_is_owned():
    t = np.array([0.0, 1.0])
    g = np.array([5.0])
    s = missing_signal(t, g)
    assert np.shares_memory(t, s.time_s) is False
    assert np.shares_memory(g, s.gate_depths_mm) is False
    assert s.time_s.flags["WRITEABLE"] is False
    assert s.values.flags["WRITEABLE"] is False
