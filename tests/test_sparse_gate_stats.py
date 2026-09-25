"""Focused tests for SA1's per-gate statistics and declared depth reductions.

Written RED first: ``analysis.sparse_gate_stats`` did not exist, so this module
failed at import. What the tests pin:

- the statistic set is the frozen WP1 ``gate_metrics`` five *plus* the extended
  eleven SA1 asks for, and the extended five are computed here while the frozen
  five are called, not restated;
- each statistic's documented convention, and the degenerate cases the plan
  demands behaviour for: a constant (zero-variance) trace, a single-profile view,
  a single-gate view, an intermittent trace with zero samples, a correlated
  trace and a known-period synthetic trace;
- the constant-trace convention is *undefined shape* (NaN skewness and excess
  kurtosis), never an all-zero curve, and the spread statistics of a constant
  trace are exactly zero rather than withheld;
- MAD is stated as 1.4826-scaled and the scaling is arithmetic, not a label;
- the three labelled views (primary comparison, full record, exploration) carry
  the visible label, the time/depth support and the method settings, and the
  primary view is the designed window rather than the retained surplus;
- depth reductions declare their weights: one vote per supported gate, and the
  native-slab weighting read from the participating gates' own grid, which
  agrees with the unweighted one on a uniform grid and differs where the grid or
  the support is not uniform;
- no pseudoreplicate interval is offered, because gates and profiles are
  correlated samples rather than independent replicates;
- the committed reader path: the live-2 pass decodes (26 recordings, 0.4 s) and
  the statistics of one real recording agreeing gate by gate with the reused
  ``gate_metrics``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_gate_stats as sgs
from udv_echo_process.analysis._native_grid import in_support
from udv_echo_process.analysis._sparse_pass import decode_pass, supported_mean_of
from udv_echo_process.analysis.reference_repeat import METRICS as FROZEN_METRICS
from udv_echo_process.analysis.reference_repeat import gate_metrics

ROOT = Path(__file__).resolve().parent.parent
LIVE2_ROOT = ROOT / "data" / "sparse-mixer-live-2"
LIVE2_PLAN = ROOT / "examples" / "sparse-mixer-live-2" / "run-plan.json"

#: The designed exposure of both mixer-enabled passes: the primary comparison
#: window is this, cut by each recording's own stored stamps.
DESIGNED_WINDOW_S = 12.0

EXTENDED_EXPECTED: tuple[str, ...] = (
    "std",
    "mad_scaled",
    "min",
    "max",
    "q05",
    "q25",
    "q50",
    "q75",
    "q95",
    "skewness",
    "excess_kurtosis",
)


@pytest.fixture(scope="module")
def live2():
    """The committed live-2 pass, decoded once through the committed reader path.

    Decoding the 26 committed recordings takes about 0.4 s, so the real path is
    exercised in the unit tests rather than described.
    """
    return decode_pass(LIVE2_ROOT, plan_path=LIVE2_PLAN)


def _synthetic_view(
    values: np.ndarray,
    *,
    depths_mm: np.ndarray | None = None,
    dt_s: float = 0.02,
    view: str = sgs.VIEW_PRIMARY,
    support_mm: tuple[float, float] | None = None,
    time_bounds_s: tuple[float, float] | None = None,
    depth_bounds_mm: tuple[float, float] | None = None,
) -> sgs.WindowView:
    """One synthetic :class:`~sparse_gate_stats.WindowView`, built directly.

    The synthetic views are the degenerate and controlled cases the plan names:
    a constant trace, a single profile, a single gate, an intermittent trace and
    a known-period trace. The native grid is uniform, as every committed
    recording's is, and the support defaults to the whole grid.
    """
    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    gates = array.shape[1]
    depths = (
        np.arange(gates, dtype=float) * 1.85 + 10.0
        if depths_mm is None
        else np.asarray(depths_mm, dtype=float)
    )
    time_s = np.arange(array.shape[0], dtype=float) * dt_s
    support = (
        (float(depths[0]), float(depths[-1])) if support_mm is None else support_mm
    )
    start = float(time_s[0]) if time_s.size else 0.0
    stop = float(time_s[-1]) if time_s.size else 0.0
    return sgs.WindowView(
        view=view,
        view_rule=sgs.VIEW_RULES[view],
        relative_path="synthetic-control.BDD",
        source_sha256="0" * 64,
        job="synthetic",
        point_label="control",
        order=1,
        values=array,
        time_s=time_s,
        depths_mm=depths,
        support_mask=in_support(depths, support),
        start_index=0,
        stop_index=array.shape[0],
        window_start_s=start,
        window_end_s=stop,
        window_s=stop - start,
        support_mm=support,
        time_bounds_s=time_bounds_s,
        depth_bounds_mm=depth_bounds_mm,
    )


# ── the statistic set ─────────────────────────────────────────────────


def test_the_statistic_set_is_the_frozen_five_plus_the_extended_eleven() -> None:
    assert sgs.REUSED_STATISTICS == FROZEN_METRICS
    assert sgs.EXTENDED_STATISTICS == EXTENDED_EXPECTED
    assert sgs.GATE_STATISTICS == FROZEN_METRICS + EXTENDED_EXPECTED
    assert sgs.REUSED_STATISTICS == ("mean", "median", "iqr", "rms", "zero_fraction")


def test_every_statistic_carries_its_units() -> None:
    velocity = {"mean", "median", "iqr", "rms", "std", "mad_scaled", "min", "max"}
    quantiles = {"q05", "q25", "q50", "q75", "q95"}
    shape = {"skewness", "excess_kurtosis"}
    for name in sgs.GATE_STATISTICS:
        assert sgs.statistic_units(name) == (
            "mm/s" if name in velocity | quantiles else "dimensionless"
        )
    assert set(sgs.STATISTIC_UNITS) == set(sgs.GATE_STATISTICS)
    assert shape and velocity and quantiles
    with pytest.raises(sgs.SparseGateStatsError, match="unknown gate statistic"):
        sgs.statistic_units("kurtosis_of_nothing")


# ── the degenerate cases the plan demands behaviour for ───────────────


def test_a_constant_trace_reports_zero_spread_and_undefined_shape() -> None:
    """A constant gate has no shape: NaN skewness, not 0.0, and exact zero spread."""
    constant = np.full((40, 3), -7.25)
    metrics = sgs.extended_gate_metrics(constant)
    for name in ("std", "mad_scaled"):
        assert np.all(metrics[name] == 0.0), name
    for name in ("min", "max", "q05", "q25", "q50", "q75", "q95"):
        assert np.all(metrics[name] == -7.25), name
    for name in ("skewness", "excess_kurtosis"):
        assert np.all(np.isnan(metrics[name])), name


def test_the_constant_trace_convention_is_stated_not_implied() -> None:
    assert sgs.MAD_SCALE == 1.4826
    assert "1.4826" in sgs.MAD_SCALING
    assert "1.4826" in sgs.__doc__
    assert "NaN" in sgs.CONSTANT_TRACE_RULE
    assert "never" in sgs.CONSTANT_TRACE_RULE
    assert "excess kurtosis" in sgs.EXCESS_KURTOSIS_CONVENTION
    assert "normal" in sgs.EXCESS_KURTOSIS_CONVENTION


def test_a_single_profile_view_is_the_same_degenerate_case() -> None:
    one = np.array([[3.0, -1.5, 0.0]])
    metrics = sgs.extended_gate_metrics(one)
    assert np.all(metrics["std"] == 0.0)
    assert np.all(metrics["mad_scaled"] == 0.0)
    assert np.all(metrics["min"] == metrics["max"])
    assert np.all(metrics["q05"] == metrics["q95"])
    assert np.all(np.isnan(metrics["skewness"]))
    assert np.all(np.isnan(metrics["excess_kurtosis"]))
    result = sgs.gate_statistics(_synthetic_view(one))
    assert result.provenance.profiles == 1
    assert result.of("mean") == pytest.approx([3.0, -1.5, 0.0])
    assert set(result.unmeasured()) == {"skewness", "excess_kurtosis"}
    assert result.unmeasured()["skewness"] == (0, 1, 2)


def test_a_single_gate_view_carries_one_column_and_reduces_to_its_value() -> None:
    column = np.array([[1.0], [2.0], [4.0]])
    view = _synthetic_view(column)
    result = sgs.gate_statistics(view)
    assert result.statistics.shape == (len(sgs.GATE_STATISTICS), 1)
    assert result.depths_mm.shape == (1,)
    equal = sgs.reduce_equal_weight(
        result.of("mean"), statistic="mean", depths_mm=result.depths_mm
    )
    slab = sgs.reduce_native_slab(
        result.of("mean"),
        result.depths_mm,
        statistic="mean",
        support_mm=result.provenance.support_mm,
    )
    assert equal.value == pytest.approx(7.0 / 3.0)
    assert slab.value == pytest.approx(7.0 / 3.0)
    assert (equal.gates, slab.gates) == (1, 1)
    assert equal.weights == (1.0,)
    assert slab.weights == (1.0,)
    assert equal.units == "mm/s"


def test_an_intermittent_trace_with_zero_samples() -> None:
    """Half the samples are exactly zero; the zero fraction is measured, not assumed."""
    trace = np.zeros((20, 2))
    trace[0::2, 0] = 4.0
    trace[0::4, 1] = -2.0
    frozen = gate_metrics(trace)
    metrics = sgs.extended_gate_metrics(trace)
    assert frozen["zero_fraction"] == pytest.approx([0.5, 0.75])
    assert metrics["std"] == pytest.approx([2.0, np.sqrt(0.25 * 4.0 - 0.25**2 * 4.0)])
    assert metrics["min"] == pytest.approx([0.0, -2.0])
    assert metrics["max"] == pytest.approx([4.0, 0.0])
    assert metrics["q50"] == pytest.approx([2.0, 0.0])
    # a two-valued trace is defined, not degenerate: its shape is measurable. The
    # excess kurtosis of a two-point trace is closed-form: -2 for the 50/50 column
    # and -2/3 for the 25/75 one, so the population moment is pinned, not eyeballed.
    assert np.isfinite(metrics["skewness"]).all()
    assert np.isfinite(metrics["excess_kurtosis"]).all()
    assert metrics["excess_kurtosis"] == pytest.approx([-2.0, -2.0 / 3.0])


def test_a_correlated_trace_keeps_its_spread_and_needs_no_interval() -> None:
    """An AR(1) trace with rho=0.9: the spread is the process's, and no CI is offered."""
    rho = 0.9
    generator = np.random.default_rng(20260925)
    trace = np.empty((1200, 1))
    trace[0, 0] = 0.0
    for index in range(1, trace.shape[0]):
        trace[index, 0] = rho * trace[index - 1, 0] + generator.normal()
    metrics = sgs.extended_gate_metrics(trace)
    lag_one = float(np.corrcoef(trace[:-1, 0], trace[1:, 0])[0, 1])
    assert lag_one > 0.8
    assert metrics["std"][0] == pytest.approx(
        1.0 / np.sqrt(1.0 - rho**2), rel=0.15
    )
    assert abs(metrics["skewness"][0]) < 0.35
    assert abs(metrics["excess_kurtosis"][0]) < 0.5
    # the 1.4826 scaling is what makes MAD comparable to the standard deviation
    # of a near-Gaussian trace; on a correlated trace it still is
    assert metrics["mad_scaled"][0] == pytest.approx(metrics["std"][0], rel=0.2)


def test_a_known_period_synthetic_trace_recovers_its_amplitude_and_shape() -> None:
    """A 1 s sine at 50 Hz over 12 s: arcsine statistics, measured not asserted blind."""
    amplitude, period_s = 5.0, 1.0
    time_s = np.arange(601, dtype=float) * 0.02
    assert time_s[-1] == pytest.approx(12.0)
    trace = (amplitude * np.sin(2.0 * np.pi * time_s / period_s))[:, None]
    metrics = sgs.extended_gate_metrics(trace)
    frozen = gate_metrics(trace)
    assert metrics["std"][0] == pytest.approx(amplitude / np.sqrt(2.0), rel=5e-3)
    assert frozen["rms"][0] == pytest.approx(amplitude / np.sqrt(2.0), rel=5e-3)
    # 50 samples/cycle lands between crests, so the extreme sample sits within
    # 0.01 of the amplitude and the extremes are symmetric about zero
    assert metrics["max"][0] == pytest.approx(amplitude, abs=0.02)
    assert metrics["min"][0] == pytest.approx(-amplitude, abs=0.02)
    assert metrics["max"][0] == pytest.approx(-metrics["min"][0], abs=1e-9)
    assert metrics["q50"][0] == pytest.approx(0.0, abs=1e-9)
    assert metrics["q25"][0] == pytest.approx(-metrics["q75"][0], abs=1e-9)
    assert metrics["skewness"][0] == pytest.approx(0.0, abs=1e-6)
    # the arcsine distribution's excess kurtosis is -1.5
    assert metrics["excess_kurtosis"][0] == pytest.approx(-1.5, abs=0.01)
    assert metrics["q05"][0] < metrics["q25"][0] < metrics["q50"][0] < metrics["q75"][0]
    assert metrics["q75"][0] < metrics["q95"][0]


def test_mad_is_scaled_by_1p4826_arithmetically() -> None:
    generator = np.random.default_rng(7)
    trace = generator.normal(size=(600, 3)) * 2.0 + 1.0
    metrics = sgs.extended_gate_metrics(trace)
    raw = np.median(np.abs(trace - np.median(trace, axis=0)), axis=0)
    assert metrics["mad_scaled"] == pytest.approx(1.4826 * raw, rel=1e-12)


def test_non_finite_and_empty_inputs_are_refused_by_name() -> None:
    with pytest.raises(sgs.SparseGateStatsError, match="at least one profile"):
        sgs.extended_gate_metrics(np.empty((0, 4)))
    with pytest.raises(sgs.SparseGateStatsError, match="2-D"):
        sgs.extended_gate_metrics(np.zeros(4))
    with pytest.raises(sgs.SparseGateStatsError, match="non-finite"):
        sgs.extended_gate_metrics(np.array([[1.0, np.nan], [2.0, 3.0]]))
    with pytest.raises(ValueError, match="at least one profile"):
        sgs.gate_statistics(_synthetic_view(np.empty((0, 4))))


def test_no_pseudoreplicate_interval_is_offered() -> None:
    """Gates and profiles are correlated samples, so no interval may treat them as replicates."""
    forbidden = (
        "interval",
        "confidence",
        "standard_error",
        "stderr",
        "p_value",
        "significance",
    )
    public = [
        name
        for name in dir(sgs)
        if not name.startswith("_") and callable(getattr(sgs, name))
    ]
    for name in public:
        assert not any(word in name.lower() for word in forbidden), name
    for model in (sgs.GateStatistics, sgs.DepthReduction, sgs.ViewProvenance, sgs.WindowView):
        for field in model.model_fields:
            assert not any(word in field.lower() for word in forbidden), (model, field)
    assert "correlated samples" in sgs.__doc__
    assert "pseudoreplicate" in sgs.__doc__


# ── depth reductions and their declared weighting ─────────────────────


def test_depth_reductions_declare_their_weights() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0])
    depths = np.arange(4, dtype=float) * 1.85 + 10.0
    support = (float(depths[0]), float(depths[-1]))
    equal = sgs.reduce_equal_weight(values, statistic="mean", depths_mm=depths)
    slab = sgs.reduce_native_slab(
        values, depths, statistic="mean", support_mm=support
    )
    assert equal.value == pytest.approx(values.mean())
    assert equal.weights == pytest.approx((0.25, 0.25, 0.25, 0.25))
    assert "one vote" in equal.weighting
    assert equal.weighting_rule != slab.weighting_rule
    # measured: a support landing on gate positions clips each end cell to half a
    # pitch, so the two ends carry half of an interior gate's weight (1:2:2:1)
    assert slab.weights == pytest.approx([1.0 / 6.0, 2.0 / 6.0, 2.0 / 6.0, 1.0 / 6.0])
    assert np.allclose(sgs.native_slab_weights(depths, support_mm=support), slab.weights)
    assert sum(slab.weights) == pytest.approx(1.0, rel=1e-12)
    # a profile symmetric about the support centre then reduces to the same number
    # under both weightings; a non-symmetric one does not, by the ends' share
    assert slab.value == pytest.approx(equal.value, rel=1e-12)
    ramp = sgs.reduce_native_slab(
        np.array([0.0, 0.0, 0.0, 10.0]), depths, statistic="mean", support_mm=support
    )
    flat = sgs.reduce_equal_weight(
        np.array([0.0, 0.0, 0.0, 10.0]), statistic="mean", depths_mm=depths
    )
    assert flat.value == pytest.approx(2.5)
    assert ramp.value == pytest.approx(10.0 / 6.0)
    assert (equal.gates, slab.gates) == (4, 4)
    assert equal.depth_support_mm == pytest.approx((10.0, 15.55))


def test_the_native_slab_weighting_differs_where_the_support_is_not_at_the_gates() -> None:
    """A support that is not a set of gates makes the covered share the weight."""
    values = np.array([0.0, 0.0, 0.0, 10.0])
    depths = np.array([10.0, 12.0, 14.0, 16.0])
    support = (10.0, 16.5)
    equal = sgs.reduce_equal_weight(values, statistic="mean", depths_mm=depths)
    slab = sgs.reduce_native_slab(
        values, depths, statistic="mean", support_mm=support
    )
    assert equal.value == pytest.approx(2.5)
    # cells 10-11, 11-13, 13-15, 15-16.5: the first and last are clipped by the
    # support, the last gate speaks for 1.5 of the 6.5 mm analysed
    assert slab.weights == pytest.approx([1.0 / 6.5, 2.0 / 6.5, 2.0 / 6.5, 1.5 / 6.5])
    assert slab.value == pytest.approx(10.0 * 1.5 / 6.5)
    assert slab.value < equal.value
    assert slab.weights[0] < 0.25
    assert slab.weights[3] < 0.25
    assert sum(slab.weights) == pytest.approx(1.0, rel=1e-12)
    assert sgs.native_slab_weights(np.array([10.0, 12.0])) == pytest.approx([0.5, 0.5])
    assert sgs.native_slab_weights(np.array([10.0])) == pytest.approx([1.0])
    with pytest.raises(sgs.SparseGateStatsError, match="increase strictly"):
        sgs.native_slab_weights(np.array([10.0, 10.0]))
    with pytest.raises(sgs.SparseGateStatsError, match="no depth inside the support"):
        sgs.native_slab_weights(np.array([10.0, 12.0]), support_mm=(20.0, 30.0))


def test_reductions_refuse_an_undefined_statistic_by_name() -> None:
    values = np.array([1.0, np.nan, 3.0])
    depths = np.array([10.0, 11.85, 13.7])
    with pytest.raises(sgs.SparseGateStatsError, match="skewness") as refusal:
        sgs.reduce_equal_weight(values, statistic="skewness", depths_mm=depths)
    assert "gate 1" in str(refusal.value)
    with pytest.raises(sgs.SparseGateStatsError, match="excess_kurtosis"):
        sgs.reduce_native_slab(values, depths, statistic="excess_kurtosis")
    with pytest.raises(sgs.SparseGateStatsError, match="not finite"):
        sgs.reduce_equal_weight(
            np.array([1.0, np.nan, np.nan, 4.0]),
            statistic="std",
            depths_mm=np.array([10.0, 11.85, 13.7, 15.55]),
        )


# ── the result models ─────────────────────────────────────────────────


def test_the_result_carries_its_names_units_and_masked_rows() -> None:
    values = np.linspace(-1.0, 1.0, 60).reshape(20, 3)
    view = _synthetic_view(values)
    result = sgs.gate_statistics(view)
    assert result.statistic_names == sgs.GATE_STATISTICS
    assert result.units == tuple(
        sgs.statistic_units(name) for name in sgs.GATE_STATISTICS
    )
    assert result.statistics.shape == (len(sgs.GATE_STATISTICS), 3)
    assert result.support_mask.dtype == np.bool_
    assert result.support_mask.shape == (3,)
    assert result.depths_mm == pytest.approx(view.depths_mm)
    assert result.provenance.profiles == 20
    assert result.provenance.view == sgs.VIEW_PRIMARY
    assert result.provenance.method == sgs.METHOD
    assert result.provenance.percentile_method == "linear"
    assert result.provenance.std_ddof == 0
    assert result.provenance.mad_scale == sgs.MAD_SCALE
    assert result.provenance.constant_trace_rule == sgs.CONSTANT_TRACE_RULE
    assert result.unmeasured() == {}
    with pytest.raises(sgs.SparseGateStatsError, match="unknown gate statistic"):
        result.of("variance_of_nothing")
    # the frozen five come from gate_metrics, not from a second definition here
    frozen = gate_metrics(values)
    for name in sgs.REUSED_STATISTICS:
        assert result.of(name) == pytest.approx(frozen[name], rel=1e-12)


# ── the committed reader path and the labelled views ──────────────────


def test_the_committed_reader_path_loads_the_live2_pass(live2) -> None:
    assert len(live2.points) == 26
    assert live2.window_s == DESIGNED_WINDOW_S
    assert live2.support_mm[1] > live2.support_mm[0]
    assert all(point.unit == "mm/s" for point in live2.points)


def test_the_primary_view_is_labelled_and_never_the_retained_surplus(live2) -> None:
    point = live2.points[0]
    view = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    assert view.view == sgs.VIEW_PRIMARY
    assert sgs.VIEW_PRIMARY in view.view_rule
    assert view.declared_window_s == DESIGNED_WINDOW_S
    assert view.values.shape[0] < point.values.shape[0]
    assert view.window_end_s <= live2.window_s + 1e-9
    assert view.window_s < float(point.time_s[-1] - point.time_s[0])
    assert view.start_index == 0
    assert view.stop_index == view.values.shape[0]
    assert view.support_mm == live2.support_mm
    assert view.depths_mm.size == point.depths.size
    assert view.values.shape[1] == point.values.shape[1]


def test_the_full_record_view_is_longer_and_labelled_separately(live2) -> None:
    point = live2.points[0]
    primary = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    full = sgs.full_record_view(point, support_mm=live2.support_mm)
    assert full.view == sgs.VIEW_FULL_RECORD
    assert full.view != primary.view
    assert full.view_rule != primary.view_rule
    assert full.values.shape == point.values.shape
    assert full.window_s == pytest.approx(
        float(point.time_s[-1] - point.time_s[0]), rel=1e-12
    )
    assert full.window_s > primary.window_s


def test_the_exploration_view_records_its_bounds_and_refuses_the_unstored(live2) -> None:
    point = live2.points[0]
    view = sgs.exploration_view(
        point,
        time_bounds_s=(1.0, 3.0),
        depth_bounds_mm=(20.0, 40.0),
        support_mm=live2.support_mm,
    )
    assert view.view == sgs.VIEW_EXPLORATION
    assert sgs.VIEW_EXPLORATION in view.view_rule
    assert view.time_bounds_s == (1.0, 3.0)
    assert view.depth_bounds_mm == (20.0, 40.0)
    assert view.start_index > 0
    assert view.window_s <= 2.0 + 1e-9
    assert view.depths_mm.min() >= 20.0 and view.depths_mm.max() <= 40.0
    assert view.depths_mm.size < point.depths.size
    assert np.all(view.support_mask)
    # an exploratory selection must never widen the record it was taken from
    with pytest.raises(sgs.SparseGateStatsError, match="stored"):
        sgs.exploration_view(
            point,
            time_bounds_s=(0.0, 99.0),
            depth_bounds_mm=(20.0, 40.0),
            support_mm=live2.support_mm,
        )
    with pytest.raises(sgs.SparseGateStatsError, match="no native gate"):
        sgs.exploration_view(
            point,
            time_bounds_s=(1.0, 3.0),
            depth_bounds_mm=(99.0, 100.5),
            support_mm=live2.support_mm,
        )
    with pytest.raises(sgs.SparseGateStatsError, match="finite and increasing"):
        sgs.exploration_view(
            point,
            time_bounds_s=(3.0, 1.0),
            depth_bounds_mm=(20.0, 40.0),
            support_mm=live2.support_mm,
        )


def test_committed_statistics_agree_with_the_reused_gate_metrics(live2) -> None:
    """One real recording: the frozen five are the frozen five, gate by gate."""
    point = live2.points[3]
    view = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    result = sgs.gate_statistics(view)
    mask = in_support(point.depths, live2.support_mm)
    block = np.asarray(point.values, dtype=float)[: view.values.shape[0]]
    frozen = gate_metrics(block[:, mask])
    # support_mask is a mask over the native grid; the statistics are masked by it
    assert int(result.support_mask.sum()) == int(mask.sum())
    assert result.statistics.shape[1] == int(mask.sum())
    assert result.depths_mm == pytest.approx(np.asarray(point.depths)[mask])
    for name in sgs.REUSED_STATISTICS:
        assert result.of(name) == pytest.approx(frozen[name], rel=1e-12, abs=0)
    # and the extended statistics are internally consistent with each other
    assert result.of("q50") == pytest.approx(result.of("median"), rel=1e-12, abs=0)
    assert result.of("iqr") == pytest.approx(
        result.of("q75") - result.of("q25"), rel=1e-12, abs=0
    )
    assert np.all(result.of("min") <= result.of("median"))
    assert np.all(result.of("median") <= result.of("max"))
    assert np.all(result.of("std") >= 0.0)
    assert np.all(result.of("q05") <= result.of("q25"))
    assert np.all(result.of("q75") <= result.of("q95"))
    # every defined-shape gate in this recording is a real one: no gate is constant
    assert result.unmeasured() == {}
    assert np.all(np.isfinite(result.of("skewness")))
    assert np.all(np.isfinite(result.of("excess_kurtosis")))
    assert np.all(result.of("zero_fraction") >= 0.0)
    assert np.all(result.of("zero_fraction") <= 1.0)
    # provenance: the source identity, the view, the support and the settings
    provenance = result.provenance
    assert provenance.relative_path == point.relative_path
    assert provenance.source_sha256 == point.source_sha256
    assert provenance.view == sgs.VIEW_PRIMARY
    assert provenance.profiles == view.values.shape[0]
    assert provenance.native_gates == point.depths.size
    assert provenance.supported_gates == int(mask.sum())
    supported = np.asarray(point.depths)[mask]
    assert provenance.depth_support_mm == pytest.approx(
        (float(supported.min()), float(supported.max()))
    )
    assert provenance.support_mm == live2.support_mm
    assert provenance.job == point.binding.job.job
    assert provenance.point_label == point.binding.point.label
    assert provenance.window_start_s == 0.0
    assert provenance.window_end_s <= live2.window_s + 1e-9


def test_the_two_weightings_differ_on_the_committed_support(live2) -> None:
    """Measured on the committed pass: the clipped end cells move the reduced value."""
    point = live2.points[0]
    view = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    statistics = sgs.gate_statistics(view)
    mean = statistics.of("mean")
    equal = sgs.reduce_equal_weight(
        mean, statistic="mean", depths_mm=statistics.depths_mm
    )
    slab = sgs.reduce_native_slab(
        mean,
        statistics.depths_mm,
        statistic="mean",
        support_mm=live2.support_mm,
    )
    assert statistics.provenance.supported_gates == 49
    assert equal.weights == pytest.approx([1.0 / 49.0] * 49)
    assert slab.weights[0] == pytest.approx(slab.weights[1] / 2.0, rel=1e-9)
    assert slab.weights[-1] == pytest.approx(slab.weights[-2] / 2.0, rel=1e-9)
    assert sum(slab.weights) == pytest.approx(1.0, rel=1e-12)
    assert slab.value != pytest.approx(equal.value, rel=1e-6)
    assert equal.units == slab.units == "mm/s"
    assert equal.weighting != slab.weighting


def test_the_unweighted_reduction_is_the_pass_modules_own_number(live2) -> None:
    """The equal-weight rule is restated here, never redefined: the pass helper agrees."""
    point = live2.points[2]
    view = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    statistics = sgs.gate_statistics(view)
    reduced = sgs.reduce_equal_weight(
        statistics.of("median"), statistic="median", depths_mm=statistics.depths_mm
    )
    shared = supported_mean_of(
        point,
        window_s=live2.window_s,
        support_mm=live2.support_mm,
        name="median",
    )
    assert reduced.value == pytest.approx(shared, rel=1e-12, abs=0)


def test_the_same_view_gives_the_same_numbers_twice(live2) -> None:
    point = live2.points[7]
    view = sgs.primary_view(
        point, window_s=live2.window_s, support_mm=live2.support_mm
    )
    first = sgs.gate_statistics(view)
    second = sgs.gate_statistics(view)
    assert np.array_equal(first.statistics, second.statistics)
    assert first.provenance.model_dump(mode="json") == second.provenance.model_dump(
        mode="json"
    )
