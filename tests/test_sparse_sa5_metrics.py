"""Focused adversarial tests for SA5's per-record metric profiles (prespec §"Named observables").

What the tests pin:

- the metric set is exactly the observables the prespec names, each on the views it declares -
  SA1's ``mean``/``std``/``mad_scaled`` on the primary comparison, the supported 1/e decay lag
  and the descriptive recurrence-peak lag plus SA2.4's Φ on the two named views - and a metric
  asked for on a view it is not declared on (an exchanged view, an exploratory cut) is refused,
  not computed;
- every gate row keeps its own state and its own reason, and the states that exist in the
  backends keep the backends' own labels: a constant trace's undefined recurrence, a supported
  1/e decay against one the lag range never reaches, an admitted axis whose total power is
  exactly zero, and an axis the admission declined. None of them becomes a ``0.0``;
- units and provenance travel on the profile, so a metric row cannot be quoted without its
  recording, its view and its cut;
- no array is serialized: the profile models are not array models, a numpy value is refused in
  a scalar row, and the JSON round trip is lossless and NaN/Infinity-free.

The adversarial axes here are constructed rather than sought in the committed data - a
duplicated stamp, a constant trace, an AR(1) too persistent to decay within its own lag range.
One committed live-2 recording is read at the end through the real reader path to prove the
backends are wired, not described.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis import sparse_sa5_metrics as sa5
from udv_echo_process.analysis._native_grid import in_support
from udv_echo_process.analysis._sparse_view import (
    VIEW_RULES,
    SparseView,
    WindowView,
    exploration_view,
    full_record_view,
    primary_view,
)
from udv_echo_process.analysis.sparse_gate_stats import gate_statistics
from udv_echo_process.analysis.sparse_inventory import DESIGNED_WINDOW_S
from udv_echo_process.analysis.sparse_recurrence import (
    RecurrencePeak,
    RecurrenceVerdict,
)
from udv_echo_process.analysis.sparse_spectral_characterization import BandFractionState
from udv_echo_process.io import load
from udv_echo_process.models.base import ArrayModel

ROOT = Path(__file__).resolve().parent.parent
LIVE_2 = ROOT / "data" / "sparse-mixer-live-2"

#: The synthetic cadence and native grid every constructed view below sits on.
DT_S = 0.02
GATES = 3
DEPTHS_MM = np.arange(GATES, dtype=float) * 1.85 + 10.0
SUPPORT_MM = (float(DEPTHS_MM[0]), float(DEPTHS_MM[-1]))

#: The period, in seconds, of the sine the recurrence-peak test recovers.
PERIOD_S = 1.0

EXPECTED_UNITS = {
    "mean": "mm/s",
    "std": "mm/s",
    "mad_scaled": "mm/s",
    "recurrence-1e-lag": "s",
    "recurrence-peak-lag": "s",
    "band_fraction": "dimensionless",
}


def _stamps(count: int, *, dt_s: float = DT_S) -> np.ndarray:
    return np.arange(count, dtype=float) * dt_s


def _sine(count: int, period_s: float, *, amplitude: float = 1.0) -> np.ndarray:
    return amplitude * np.sin(2.0 * np.pi * _stamps(count) / period_s)


def _mixed(count: int = 600) -> np.ndarray:
    """Three controlled gates: a constant one, a 1 s sine and a 0.7 s sine."""
    return np.stack(
        [
            np.full(count, -3.0),
            _sine(count, 1.0, amplitude=5.0) + 0.3,
            _sine(count, 0.7),
        ],
        axis=1,
    )


def _view(
    values: np.ndarray,
    *,
    view: SparseView = SparseView.PRIMARY,
    time_s: np.ndarray | None = None,
    depths_mm: np.ndarray | None = None,
    native_depths_mm: np.ndarray | None = None,
    support_mm: tuple[float, float] | None = None,
    label: str = "sa5-synthetic",
) -> WindowView:
    """One synthetic :class:`WindowView`, built directly.

    ``native_depths_mm`` is the grid the selection was cut from, kept separately so a
    single-gate selection can still name the recording's own grid; the support defaults to
    the whole native grid, as a pass's declared common support is.
    """
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    depths = (
        DEPTHS_MM[: array.shape[1]]
        if depths_mm is None
        else np.asarray(depths_mm, float)
    )
    native = depths if native_depths_mm is None else np.asarray(native_depths_mm, float)
    stamps = (
        _stamps(array.shape[0]) if time_s is None else np.asarray(time_s, dtype=float)
    )
    support = (
        (float(native[0]), float(native[-1])) if support_mm is None else support_mm
    )
    return WindowView(
        view=view,
        view_rule=VIEW_RULES[view],
        relative_path=f"{label}.BDD",
        source_sha256="a" * 64,
        job="sa5-synthetic",
        point_label=label,
        order=3,
        values=array,
        time_s=stamps,
        depths_mm=depths,
        support_mask=in_support(depths, support),
        native_gates=int(native.size),
        native_depth_extent_mm=(float(native[0]), float(native[-1])),
        pass_support_mm=support,
        start_index=0,
        stop_index=array.shape[0],
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )


def _point(values: np.ndarray, *, label: str = "sa5-synthetic") -> SimpleNamespace:
    """A stand-in decoded recording: exactly the attributes the view constructors read."""
    return SimpleNamespace(
        values=np.asarray(values, dtype=float),
        time_s=_stamps(np.asarray(values).shape[0]),
        depths=DEPTHS_MM,
        relative_path=f"{label}.BDD",
        source_sha256="a" * 64,
        binding=SimpleNamespace(
            job=SimpleNamespace(job="sa5-synthetic"),
            point=SimpleNamespace(label=label),
            order=3,
        ),
    )


# ── the metric set and the views each metric is declared on ───────────


def test_the_metric_set_is_the_prespec_observables_on_their_declared_views() -> None:
    assert sa5.METRICS == (
        sa5.MetricName.MEAN,
        sa5.MetricName.STD,
        sa5.MetricName.MAD_SCALED,
        sa5.MetricName.RECURRENCE_1E_LAG,
        sa5.MetricName.RECURRENCE_PEAK_LAG,
        sa5.MetricName.PHI,
    )
    assert sa5.PRIMARY_METRICS == (
        sa5.MetricName.MEAN,
        sa5.MetricName.STD,
        sa5.MetricName.MAD_SCALED,
    )
    assert sa5.RECURRENCE_METRICS == (
        sa5.MetricName.RECURRENCE_1E_LAG,
        sa5.MetricName.RECURRENCE_PEAK_LAG,
    )
    assert sa5.SPECTRAL_METRICS == (sa5.MetricName.PHI,)
    # the fluctuation scale is the primary comparison's own observable; recurrence and
    # spectral allocation are the two the prespec keeps on a named view
    for metric in sa5.PRIMARY_METRICS:
        assert sa5.allowed_views(metric) == (SparseView.PRIMARY,)
    for metric in sa5.RECURRENCE_METRICS + sa5.SPECTRAL_METRICS:
        assert sa5.allowed_views(metric) == (SparseView.PRIMARY, SparseView.FULL_RECORD)
    assert set(sa5.ALLOWED_VIEWS) == set(sa5.METRICS)
    # a str label works because MetricName is a str enum, so a report can quote one
    assert sa5.allowed_views("mean") == sa5.allowed_views(sa5.MetricName.MEAN)
    with pytest.raises(sa5.SparseSa5MetricsError, match="unknown SA5 metric"):
        sa5.allowed_views("mean_and_a_promise")


def test_every_metric_carries_its_unit_and_rule_and_the_states_are_the_backends_own() -> (
    None
):
    assert {metric.value for metric in sa5.METRICS} == set(EXPECTED_UNITS)
    for metric in sa5.METRICS:
        assert sa5.metric_units(metric) == EXPECTED_UNITS[metric.value]
        assert sa5.metric_rule(metric).strip()
        assert sa5.metric_rule(metric) == sa5.METRIC_RULES[metric]
    # a Φ difference is dimensionless, never a percentage
    assert sa5.metric_units(sa5.MetricName.PHI) == "dimensionless"
    with pytest.raises(sa5.SparseSa5MetricsError, match="unknown SA5 metric"):
        sa5.metric_units("phi_in_percent")
    # the states that exist in a backend keep that backend's own label, so a row cannot
    # invent a state its estimator never produced
    assert (
        sa5.MetricState.DEFINED_ZERO_POWER.value
        == BandFractionState.DEFINED_ZERO_POWER.value
    )
    assert sa5.MetricState.REFUSED_AXIS.value == BandFractionState.REFUSED_AXIS.value
    assert (
        sa5.MetricState.UNDEFINED_CONSTANT_TRACE.value
        == RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE.value
    )
    assert "never" in sa5.STATE_MEANING
    assert "admissible" in sa5.RECURRENCE_PEAK_RULE
    assert "no period is claimed" in sa5.RECURRENCE_PEAK_RULE


# ── the primary profile ───────────────────────────────────────────────


def test_the_primary_profile_is_one_row_per_supported_gate_with_its_provenance() -> (
    None
):
    view = _view(_mixed(200))
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.MEAN)
    assert profile.metric is sa5.MetricName.MEAN
    assert profile.units == "mm/s"
    assert profile.view is SparseView.PRIMARY
    assert profile.view_rule == VIEW_RULES[SparseView.PRIMARY]
    assert profile.method == sa5.METHOD
    assert profile.defined_count == GATES
    assert profile.gates[0].value == pytest.approx(-3.0)
    assert profile.gates[1].value == pytest.approx(0.3, abs=0.02)
    assert abs(profile.gates[2].value) < 0.05
    assert [row.gate_index for row in profile.gates] == [0, 1, 2]
    assert profile.depths_mm == pytest.approx(tuple(DEPTHS_MM))
    assert profile.provenance.supported_gates == GATES
    assert profile.provenance.source_sha256 == "a" * 64
    assert profile.provenance.point_label == "sa5-synthetic"
    assert profile.provenance.participating_depth_extent_mm == pytest.approx(SUPPORT_MM)
    assert profile.undefined() == ()
    # a gate the support excludes is not a row: a profile is the view's *supported* gates
    excluded = _view(
        _mixed(200), support_mm=(float(DEPTHS_MM[1]), float(DEPTHS_MM[-1]))
    )
    narrowed = sa5.read_metric_profile(excluded, metric=sa5.MetricName.MEAN)
    assert [row.gate_index for row in narrowed.gates] == [1, 2]
    assert narrowed.provenance.supported_gates == 2


def test_the_gate_statistic_metrics_agree_gate_by_gate_with_the_frozen_backend() -> (
    None
):
    view = _view(_mixed(300))
    statistics = gate_statistics(view)
    for metric in sa5.PRIMARY_METRICS:
        profile = sa5.read_metric_profile(view, metric=metric)
        assert profile.values == pytest.approx(
            [float(value) for value in statistics.of(metric.value)]
        )
        assert profile.units == sa5.metric_units(metric)
    mad = sa5.read_metric_profile(view, metric=sa5.MetricName.MAD_SCALED)
    settings = {setting.name: setting.value for setting in mad.settings}
    assert settings["mad_scale"] == 1.4826
    assert "1.4826" in settings["mad_scaling"]
    assert settings["std_ddof"] == 0
    assert "gate-local statistics" in settings["method"]
    with pytest.raises(sa5.SparseSa5MetricsError, match="unknown detrending"):
        sa5.read_metric_profile(
            view, metric=sa5.MetricName.MEAN, detrending="quadratic"
        )


# ── the degenerate and refused cases the prespec names ────────────────


def test_a_constant_trace_gives_an_undefined_recurrence_never_a_zero() -> None:
    view = _view(_mixed(240))
    for metric in sa5.RECURRENCE_METRICS:
        profile = sa5.read_metric_profile(view, metric=metric)
        constant = profile.gates[0]
        assert constant.state is sa5.MetricState.UNDEFINED_CONSTANT_TRACE
        assert constant.value is None
        assert constant.defined is False
        # the reason is the estimator's own, not a summary written here
        assert "constant" in constant.reason
        # the two varying gates do define a lag, so the profile is not a blanket refusal
        assert [row.defined for row in profile.gates] == [False, True, True]
        assert all(row.value > 0.0 for row in profile.gates[1:])
        assert profile.undefined() == (constant,)
        assert profile.defined_count == 2


def test_a_defined_zero_power_gate_is_a_measurement_and_not_a_refusal() -> None:
    view = _view(np.full((240, GATES), 4.25))
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.PHI)
    assert profile.defined_count == 0
    for row in profile.gates:
        assert row.state is sa5.MetricState.DEFINED_ZERO_POWER
        assert row.value is None
        assert "defined zero power" in row.reason
        assert "not a refusal" in row.reason
    # the gate statistics of a constant trace are measured zeros, not refusals
    spread = sa5.read_metric_profile(view, metric=sa5.MetricName.STD)
    assert spread.values == (0.0, 0.0, 0.0)
    assert spread.defined_count == GATES


def test_a_refused_axis_is_never_a_zero_and_keeps_the_admissions_own_reason() -> None:
    duplicated = _stamps(240)
    duplicated[10] = duplicated[9]
    view = _view(_mixed(240), time_s=duplicated)
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.PHI)
    assert profile.defined_count == 0
    for row in profile.gates:
        assert row.state is sa5.MetricState.REFUSED_AXIS
        assert row.value is None
        assert "do not increase strictly" in row.reason
    settings = {setting.name: setting.value for setting in profile.settings}
    assert settings["admitted"] is False
    assert settings["low_hz"] == 1.0
    assert settings["detrending"] == "mean"
    # a zero-power row and a refused row are different states, and neither is a zero value
    assert sa5.MetricState.DEFINED_ZERO_POWER is not sa5.MetricState.REFUSED_AXIS
    assert all(row.defined is False for row in profile.gates)
    # the same profile read on the primary view keeps the primary label
    assert profile.view is SparseView.PRIMARY


def test_a_lag_range_that_never_reaches_the_decay_lag_is_unsupported() -> None:
    """An AR(1) with rho = 0.999 stays above 1/e over a declared 0.2 s lag domain."""
    generator = np.random.default_rng(20260927)
    rho = 0.999
    trace = np.empty((600, 1))
    trace[0, 0] = 0.0
    for index in range(1, trace.shape[0]):
        trace[index, 0] = rho * trace[index - 1, 0] + generator.normal()
    view = _view(
        trace,
        depths_mm=np.array([DEPTHS_MM[1]]),
        native_depths_mm=DEPTHS_MM,
        support_mm=SUPPORT_MM,
    )
    profile = sa5.read_metric_profile(
        view, metric=sa5.MetricName.RECURRENCE_1E_LAG, max_lag_s=0.2
    )
    row = profile.gates[0]
    assert row.state is sa5.MetricState.UNDEFINED_NOT_SUPPORTED
    assert row.value is None
    assert "does not reach the decay lag" in row.reason
    settings = {setting.name: setting.value for setting in profile.settings}
    assert settings["requested_max_lag_s"] == pytest.approx(0.2)
    assert settings["max_lag_s"] == pytest.approx(0.2)
    # the same trace's descriptive peak lag carries no admissible peak either
    peaks = sa5.read_metric_profile(
        view, metric=sa5.MetricName.RECURRENCE_PEAK_LAG, max_lag_s=0.2
    )
    assert peaks.gates[0].value is None
    assert peaks.gates[0].state is sa5.MetricState.UNDEFINED_NOT_SUPPORTED
    assert "no local maximum" in peaks.gates[0].reason
    # a lag domain beside a metric that has none is refused, not ignored
    with pytest.raises(sa5.SparseSa5MetricsError, match="recurrence setting"):
        sa5.read_metric_profile(view, metric=sa5.MetricName.MEAN, max_lag_s=0.2)
    with pytest.raises(sa5.SparseSa5MetricsError, match="recurrence setting"):
        sa5.read_metric_profile(view, metric=sa5.MetricName.PHI, max_lag_s=0.2)


def test_the_recurrence_peak_lag_is_recovered_and_follows_the_declared_rule() -> None:
    view = _view(_mixed(600))
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.RECURRENCE_PEAK_LAG)
    assert profile.gates[1].value == pytest.approx(PERIOD_S, abs=DT_S)
    assert profile.gates[2].value == pytest.approx(0.7, abs=DT_S)
    # the selection rule is arithmetic, checked on hand-made peaks rather than by description
    admissible = RecurrencePeak(
        lag_s=1.0,
        correlation=0.6,
        weak=False,
        preceded_by_dip_below_weak_threshold=True,
        reason="a",
    )
    stronger = RecurrencePeak(
        lag_s=2.0,
        correlation=0.9,
        weak=False,
        preceded_by_dip_below_weak_threshold=True,
        reason="b",
    )
    shoulder = RecurrencePeak(
        lag_s=3.0,
        correlation=0.99,
        weak=False,
        preceded_by_dip_below_weak_threshold=False,
        reason="c",
    )
    weak = RecurrencePeak(
        lag_s=4.0,
        correlation=0.2,
        weak=True,
        preceded_by_dip_below_weak_threshold=True,
        reason="d",
    )
    assert (
        sa5.recurrence_peak_lag(
            SimpleNamespace(recurrence_peaks=(admissible, stronger, shoulder, weak))
        )
        is stronger
    )
    tie = RecurrencePeak(
        lag_s=0.5,
        correlation=0.9,
        weak=False,
        preceded_by_dip_below_weak_threshold=True,
        reason="e",
    )
    assert (
        sa5.recurrence_peak_lag(SimpleNamespace(recurrence_peaks=(stronger, tie)))
        is tie
    )
    assert (
        sa5.recurrence_peak_lag(SimpleNamespace(recurrence_peaks=(shoulder, weak)))
        is None
    )
    assert sa5.recurrence_peak_lag(SimpleNamespace(recurrence_peaks=())) is None


# ── view separation ───────────────────────────────────────────────────


def test_the_two_named_views_are_kept_apart_and_never_exchanged() -> None:
    point = _point(_mixed(300))
    primary = primary_view(point, window_s=5.0, support_mm=SUPPORT_MM)
    full = full_record_view(point, support_mm=SUPPORT_MM)
    primary_phi = sa5.read_metric_profile(primary, metric=sa5.MetricName.PHI)
    full_phi = sa5.read_metric_profile(full, metric=sa5.MetricName.PHI)
    assert primary_phi.view is SparseView.PRIMARY
    assert full_phi.view is SparseView.FULL_RECORD
    assert primary_phi.view_rule == VIEW_RULES[SparseView.PRIMARY]
    assert full_phi.view_rule == VIEW_RULES[SparseView.FULL_RECORD]
    assert primary_phi.view_rule != full_phi.view_rule
    assert primary_phi.provenance.view is SparseView.PRIMARY
    assert full_phi.provenance.view is SparseView.FULL_RECORD
    # the two profiles are different cuts of the same recording, and they say so
    assert primary_phi.provenance.profiles < full_phi.provenance.profiles
    assert primary_phi.provenance.window_s < full_phi.provenance.window_s
    assert primary_phi.provenance.source_sha256 == full_phi.provenance.source_sha256
    # the fluctuation scale is declared on the primary comparison only
    for metric in sa5.PRIMARY_METRICS:
        with pytest.raises(sa5.SparseSa5MetricsError, match="declared on"):
            sa5.read_metric_profile(full, metric=metric)
    # an exploratory cut is not a prespecified view for any metric here
    exploration = exploration_view(
        point,
        time_bounds_s=(0.0, 2.0),
        depth_bounds_mm=SUPPORT_MM,
        support_mm=SUPPORT_MM,
    )
    for metric in sa5.METRICS:
        with pytest.raises(sa5.SparseSa5MetricsError, match="declared on"):
            sa5.read_metric_profile(exploration, metric=metric)


def test_a_profile_cannot_quote_one_views_label_beside_anothers_provenance() -> None:
    point = _point(_mixed(300))
    primary = primary_view(point, window_s=5.0, support_mm=SUPPORT_MM)
    full = full_record_view(point, support_mm=SUPPORT_MM)
    profile = sa5.read_metric_profile(full, metric=sa5.MetricName.PHI)
    payload = profile.model_dump()
    payload["view"] = SparseView.PRIMARY
    payload["view_rule"] = VIEW_RULES[SparseView.PRIMARY]
    with pytest.raises(ValidationError, match="one cut"):
        sa5.MetricProfile.model_validate(payload)
    # a rule text that is not the label's own is refused too
    payload = profile.model_dump()
    payload["view_rule"] = VIEW_RULES[SparseView.PRIMARY]
    with pytest.raises(ValidationError, match="rule text"):
        sa5.MetricProfile.model_validate(payload)
    # and the honest pairing round-trips unchanged
    assert sa5.MetricProfile.model_validate(profile.model_dump()) == profile
    assert (
        sa5.read_metric_profile(primary, metric=sa5.MetricName.PHI).view
        is SparseView.PRIMARY
    )


# ── the model's own invariants ────────────────────────────────────────


def test_the_profile_model_refuses_a_row_set_that_is_not_its_views_own() -> None:
    view = _view(_mixed(200))
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.MEAN)
    payload = profile.model_dump()
    payload["gates"] = payload["gates"][:-1]
    with pytest.raises(ValidationError, match="one row per supported gate"):
        sa5.MetricProfile.model_validate(payload)
    payload = profile.model_dump()
    payload["gates"] = list(reversed(payload["gates"]))
    with pytest.raises(ValidationError, match="increasing native depth order"):
        sa5.MetricProfile.model_validate(payload)
    payload = profile.model_dump()
    payload["units"] = "s"
    with pytest.raises(ValidationError, match="quantified in"):
        sa5.MetricProfile.model_validate(payload)
    payload = profile.model_dump()
    payload["view"] = SparseView.FULL_RECORD
    payload["view_rule"] = VIEW_RULES[SparseView.FULL_RECORD]
    with pytest.raises(ValidationError, match="declared on"):
        sa5.MetricProfile.model_validate(payload)
    # the first row must still be the profile's own leading depth
    payload = profile.model_dump()
    payload["gates"][-1]["depth_mm"] = float(DEPTHS_MM[-1]) + 1.0
    with pytest.raises(ValidationError, match="participating depth extent"):
        sa5.MetricProfile.model_validate(payload)
    # a defined row without a value, and a refusing row with one, are both refused
    with pytest.raises(ValidationError, match="carries a value"):
        sa5.GateMetric(
            gate_index=0,
            depth_mm=10.0,
            state=sa5.MetricState.DEFINED,
            value=None,
            reason="r",
        )
    with pytest.raises(ValidationError, match="carries no value"):
        sa5.GateMetric(
            gate_index=0,
            depth_mm=10.0,
            state=sa5.MetricState.REFUSED_AXIS,
            value=0.0,
            reason="r",
        )
    with pytest.raises(ValidationError, match="must be finite"):
        sa5.GateMetric(
            gate_index=0,
            depth_mm=10.0,
            state=sa5.MetricState.DEFINED,
            value=float("nan"),
            reason="r",
        )
    with pytest.raises(ValidationError, match="states why"):
        sa5.GateMetric(
            gate_index=0,
            depth_mm=10.0,
            state=sa5.MetricState.DEFINED,
            value=1.0,
            reason="  ",
        )


def test_a_profile_of_one_gate_is_one_row_on_its_own_native_grid() -> None:
    column = np.array([[1.0], [3.0], [5.0], [-2.0], [4.0], [0.0], [2.0], [6.0]])
    view = _view(
        column,
        depths_mm=np.array([11.85]),
        native_depths_mm=DEPTHS_MM,
        support_mm=SUPPORT_MM,
    )
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.MEAN)
    assert len(profile.gates) == 1
    # the row's index is the view's own column, not the recording's native gate number
    assert profile.gates[0].gate_index == 0
    assert profile.gates[0].depth_mm == pytest.approx(11.85)
    assert profile.provenance.native_gates == GATES
    assert profile.provenance.supported_gates == 1
    assert profile.depths_mm == (pytest.approx(11.85),)
    assert profile.values == (pytest.approx(float(np.mean(column)), rel=1e-12),)


# ── no array is serialized ────────────────────────────────────────────


def test_no_array_is_serialized_and_the_json_round_trips() -> None:
    view = _view(_mixed(200))
    profile = sa5.read_metric_profile(view, metric=sa5.MetricName.RECURRENCE_PEAK_LAG)
    # the profile models are value models, not array models
    assert not issubclass(sa5.MetricProfile, ArrayModel)
    assert not issubclass(sa5.GateMetric, ArrayModel)
    assert not issubclass(sa5.MetricSetting, ArrayModel)
    payload = profile.model_dump(mode="json")
    leaves = _leaves(payload)
    assert leaves, "the payload is not empty"
    for leaf in leaves:
        assert isinstance(leaf, (str, int, float, bool)) or leaf is None
    # no list holds a vector: `gates` and `settings` are rows of scalars, and the only
    # numeric pairs are the provenance's own extents and windows
    for node in _nodes(payload):
        if isinstance(node, list):
            if all(isinstance(entry, dict) for entry in node):
                continue
            assert len(node) <= 2, node
            assert all(isinstance(entry, (str, int, float, bool)) for entry in node), (
                node
            )
    text = profile.json_text()
    assert "NaN" not in text and "Infinity" not in text
    assert sa5.MetricProfile.model_validate_json(text) == profile
    # a numpy array cannot enter a scalar row
    with pytest.raises(ValidationError):
        sa5.GateMetric(
            gate_index=0,
            depth_mm=10.0,
            state=sa5.MetricState.DEFINED,
            value=np.array([1.0]),
            reason="r",
        )
    with pytest.raises(ValidationError):
        sa5.MetricSetting(name="lag", value=[1.0, 2.0])
    with pytest.raises(ValidationError, match="finite"):
        sa5.MetricSetting(name="lag", value=float("inf"))
    # an undefined setting is carried as None, never as a zero
    assert sa5.MetricSetting(name="max_lag_s", value=None).value is None


def _nodes(node: object) -> list[object]:
    found = [node]
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_nodes(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_nodes(value))
    return found


def _leaves(node: object) -> list[object]:
    return [item for item in _nodes(node) if not isinstance(item, (dict, list))]


# ── the committed reader path ─────────────────────────────────────────


def test_a_committed_recording_reads_through_the_backends() -> None:
    """One committed live-2 recording: the real reader path, both views, no new estimator."""
    paths = sorted(LIVE_2.glob("*.BDD"))
    assert len(paths) == 26
    data = load(paths[0]).recording.streams[0].data
    values = np.asarray(data.values, dtype=float)
    time_s = np.asarray(data.time_s, dtype=float)
    depths = np.asarray(data.gate_depths_mm, dtype=float)
    point = SimpleNamespace(
        values=values,
        time_s=time_s,
        depths=depths,
        relative_path=paths[0].name,
        source_sha256="c" * 64,
        binding=SimpleNamespace(
            job=SimpleNamespace(job="committed"),
            point=SimpleNamespace(label=paths[0].stem),
            order=1,
        ),
    )
    support = (float(depths.min()), float(depths.max()))
    primary = primary_view(point, window_s=DESIGNED_WINDOW_S, support_mm=support)
    full = full_record_view(point, support_mm=support)
    profile = sa5.read_metric_profile(primary, metric=sa5.MetricName.MEAN)
    assert profile.provenance.profiles < time_s.size
    assert profile.provenance.window_s <= DESIGNED_WINDOW_S + 1e-9
    assert profile.provenance.native_gates == depths.size
    statistics = gate_statistics(primary)
    assert profile.values == pytest.approx(
        [float(value) for value in statistics.of("mean")]
    )
    phi = sa5.read_metric_profile(primary, metric=sa5.MetricName.PHI)
    assert phi.view is SparseView.PRIMARY
    assert all(
        row.state
        in (
            sa5.MetricState.DEFINED,
            sa5.MetricState.DEFINED_ZERO_POWER,
            sa5.MetricState.REFUSED_AXIS,
        )
        for row in phi.gates
    )
    assert all(row.value is None for row in phi.gates if not row.defined)
    peaks = sa5.read_metric_profile(full, metric=sa5.MetricName.RECURRENCE_PEAK_LAG)
    assert peaks.provenance.profiles == time_s.size
    assert [row.gate_index for row in peaks.gates] == list(range(depths.size))
    settings = {setting.name: setting.value for setting in peaks.settings}
    assert settings["timebase"] in {
        "regular",
        "irregular",
        "duplicate-stamps",
        "undefined-timebase",
    }
    assert settings["detrending"] == "mean"
    assert isinstance(settings["lag_resolution_s"], float)
    assert sa5.MetricProfile.model_validate_json(peaks.json_text()) == peaks
