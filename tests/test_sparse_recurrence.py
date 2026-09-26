"""Focused tests for the SA1 temporal-recurrence backend (plan ``SA1``).

Written RED first: ``analysis.sparse_recurrence`` did not exist when this module
was written, so every test below failed at collection with an import error. The
run before implementation is the RED evidence in the report.

The plan's temporal-recurrence paragraph is the specification, and each test
pins one of its sentences:

- "subtract the trace mean by default before normalized ACF; name any
  additional detrending method and show raw traces alongside it" -
  ``test_mean_subtraction_is_the_default_and_is_named``,
  ``test_linear_detrending_is_optional_named_and_the_raw_trace_stays``;
- "A constant or effectively zero-variance trace has undefined normalized ACF,
  not an all-zero correlation curve" -
  ``test_a_constant_trace_is_undefined_not_an_all_zero_curve``,
  ``test_a_constant_trace_is_undefined_under_every_detrending``,
  ``test_an_effectively_zero_variance_trace_is_undefined``;
- "Report first zero crossing, 1/e decay, integral time and descriptive
  recurrence peaks only when supported by the window" - the
  ``SupportedQuantity`` assertions in the correlated, the monotone-decaying,
  the white-noise and the periodic tests;
- "seek but do not assume an approximately 1 s feature" and "Twelve seconds
  contains only about twelve candidate cycles, so report frequency/lag
  resolution and avoid a precise period claim from a weak peak" -
  ``test_a_known_period_is_recovered_within_the_stated_resolution`` (three
  different periods, none privileged),
  ``test_a_window_too_short_for_a_period_refuses_the_claim`` and
  ``test_a_weak_peak_cannot_support_a_period_claim``;
- "Test on constant, intermittent, correlated and known-period synthetic traces
  and on the committed reader path" - the four synthetic families plus
  ``test_the_committed_reader_path_feeds_the_estimator``;
- "No pseudoreplicate confidence intervals" -
  ``test_the_result_carries_no_pseudoreplicate_uncertainty``.

Two further families lock in the restructured entry point:

- **the refusal contract.** A refusal is a *result*, not an exception: every
  unsupported case comes back as its own typed verdict. The block
  ``the refusal contract`` drives every refusal through every detrending,
  because the defect it replaces was a success-only model invariant that turned
  every ``mean+linear`` refusal into a pydantic ``ValidationError`` - the verdict
  unreachable for that mode, and the error not even this module's own type.
- **the timebase.** The lag axis is integer indices on one effective interval, so
  reading it in seconds is an assumption about the stored stamps. The block
  ``the timebase`` pins the policy: a degenerate or jittered axis makes every
  lag-based claim unsupported while the curve stays descriptive, and a degenerate
  axis is never reported as perfectly regular.

The view tests pin the plan's shared views: the primary comparison window is
the recording's own designed 0-12 s, "Refuse insufficient coverage; never widen
it", and the full record and exploration views carry their own labels. Views are
cut by :mod:`udv_echo_process.analysis._sparse_view`, so these tests build their
synthetic recordings as stand-in decoded points and go through the same
constructors the reader path uses - there is no test-only cutting path.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis import _sparse_view as sparse_view
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    SparseViewError,
    ViewProvenance,
    WindowView,
    exploration_view,
    full_record_view,
    primary_view,
    view_provenance,
)
from udv_echo_process.analysis.sparse_inventory import DESIGNED_WINDOW_S
from udv_echo_process.analysis.sparse_recurrence import (
    ACF_ESTIMATOR,
    LAG_GRID_RULE,
    MIN_CANDIDATE_CYCLES,
    MIN_SAMPLES_FOR_ACF,
    TIMEBASE_REGULARITY_TOL,
    WEAK_PEAK_CORRELATION,
    Detrending,
    RecurrenceError,
    RecurrenceVerdict,
    TimebaseVerdict,
    TraceRecurrence,
    _recurrence_of_trace,
    classify_timebase,
    recurrence_of_view,
)
from udv_echo_process.io import load

ROOT = Path(__file__).resolve().parent.parent
LIVE_2 = ROOT / "data" / "sparse-mixer-live-2"

#: The synthetic cadence the per-sample arithmetic below is checked against.
DT_S = 0.02

#: The native grid the synthetic views below select from, one gate per entry.
SYNTHETIC_DEPTHS = np.array([10.0, 12.0, 14.0, 16.0])


def _point(
    *,
    profiles: int = 800,
    dt_s: float = 0.025,
    gates: int = 4,
    label: str = "sa1-view",
    relative_path: str = "sa1-view.BDD",
) -> SimpleNamespace:
    """A stand-in decoded recording: exactly the attributes the view constructors read.

    The estimator takes a view rather than loose arrays now, so a test that wants a labelled
    trace builds one of these and cuts a view through ``primary_view``/``full_record_view``/
    ``exploration_view`` - the same constructors the reader path uses.
    """
    time_s = np.arange(profiles) * dt_s
    values = np.empty((profiles, gates))
    for gate in range(gates):
        scale = 1.0 + gate
        values[:, gate] = scale * np.sin(2.0 * np.pi * time_s / 1.0) + 0.2 * scale
    depths = (
        SYNTHETIC_DEPTHS[:gates]
        if gates <= SYNTHETIC_DEPTHS.size
        else np.arange(gates, dtype=float) * 2.0 + 10.0
    )
    return SimpleNamespace(
        values=values,
        time_s=time_s,
        depths=depths,
        relative_path=relative_path,
        source_sha256="b" * 64,
        binding=SimpleNamespace(
            job=SimpleNamespace(job="synthetic"),
            point=SimpleNamespace(label=label),
            order=1,
        ),
    )


def _window(
    trace: np.ndarray,
    time_s: np.ndarray,
    *,
    view: SparseView | str = SparseView.PRIMARY,
    view_rule: str | None = None,
    column: int = 0,
    gates: int = 1,
    depths: np.ndarray | None = None,
    support_mask: np.ndarray | None = None,
    label: str = "synthetic",
    relative_path: str = "synthetic.BDD",
    native_gates: int | None = None,
    native_depth_extent_mm: tuple[float, float] | None = None,
    pass_support_mm: tuple[float, float] | None = None,
) -> WindowView:
    """The smallest honest labelled view around one synthetic trace.

    Built directly rather than through the three named constructors so a test can choose the
    stamps, the grid, the support and the native dimensions independently; the constructors'
    own behaviour is covered by the view tests further down. The native grid defaults to the
    four synthetic depths even when the view holds one column, because ``native`` means the
    recording's grid rather than the selection's width - the distinction SA1 got wrong.
    """
    chosen = view if isinstance(view, SparseView) else SparseView(view)
    stamps = np.asarray(time_s, dtype=float).reshape(-1)
    grid = (
        np.asarray(depths, dtype=float)
        if depths is not None
        else np.arange(gates, dtype=float) * 2.0 + 10.0
    )
    values = np.zeros((stamps.size, grid.size))
    values[:, column] = np.asarray(trace, dtype=float).reshape(-1)
    # A one-gate view still comes from a wider recording, so its native extent is a
    # two-millimetre margin around the gate it holds rather than the degenerate point the
    # validator refuses - and the support spans the same interval, since a support that is a
    # point is not a support.
    extent = (
        (float(grid[0]), float(grid[-1]))
        if grid.size > 1
        else (float(grid[0]) - 2.0, float(grid[0]) + 2.0)
    )
    return WindowView(
        view=chosen,
        view_rule=sparse_view.view_rule(chosen) if view_rule is None else view_rule,
        relative_path=relative_path,
        source_sha256="b" * 64,
        job="synthetic",
        point_label=label,
        order=1,
        values=values,
        time_s=stamps,
        depths_mm=grid,
        support_mask=(
            np.ones(grid.size, dtype=bool)
            if support_mask is None
            else np.asarray(support_mask, dtype=bool)
        ),
        native_gates=(
            max(grid.size, SYNTHETIC_DEPTHS.size)
            if native_gates is None
            else int(native_gates)
        ),
        native_depth_extent_mm=extent if native_depth_extent_mm is None else native_depth_extent_mm,
        pass_support_mm=extent if pass_support_mm is None else pass_support_mm,
        start_index=0,
        stop_index=int(stamps.size),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
        declared_window_s=None,
        time_bounds_s=None,
        depth_bounds_mm=None,
    )


def _recurrence(
    trace: np.ndarray, time_s: np.ndarray, **settings: object
) -> TraceRecurrence:
    """One synthetic trace through the estimator, cut from a labelled view.

    The estimator's single entry point takes a view, so this wraps the trace in the smallest
    one: ``gates`` columns with the trace in ``column``. It is the only place the tests build
    a view for a synthetic trace, so every test below still reads as one trace in, one
    result out.
    """
    column = int(settings.pop("column", 0))
    gates = int(settings.pop("gates", 1))
    view = settings.pop("view", SparseView.PRIMARY)
    label = str(settings.pop("label", "synthetic"))
    relative_path = str(settings.pop("relative_path", "synthetic.BDD"))
    depths = np.arange(gates, dtype=float) * 2.0 + 10.0
    return recurrence_of_view(
        _window(
            trace,
            time_s,
            view=view,
            column=column,
            depths=depths,
            label=label,
            relative_path=relative_path,
        ),
        depth_mm=float(depths[column]),
        **settings,
    )


def _periodic(
    period_s: float,
    *,
    dt_s: float = DT_S,
    duration_s: float = 12.0,
    noise: float = 0.3,
    seed: int = 20260925,
) -> tuple[np.ndarray, np.ndarray]:
    """A known-period trace with reproducible noise, and its time axis."""
    count = round(duration_s / dt_s)
    time_s = np.arange(count) * dt_s
    rng = np.random.default_rng(seed)
    trace = np.sin(2.0 * np.pi * time_s / period_s) + noise * rng.normal(size=count)
    return trace, time_s


# ── the undefined cases ───────────────────────────────────────────────


@pytest.mark.parametrize("constant", [0.0, 5.0, -12.5])
def test_a_constant_trace_is_undefined_not_an_all_zero_curve(constant: float) -> None:
    trace = np.full(200, constant)
    result = _recurrence(trace, np.arange(200) * DT_S)

    assert result.verdict is RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE
    # the refusal is a typed verdict with no curve, never a substituted one
    assert result.lag_s.size == 0
    assert result.acf.size == 0
    assert result.detrended_trace.size == 0
    # the trace itself is still shown, so a reader sees what was refused
    assert result.raw_trace.size == 200
    assert np.allclose(result.raw_trace, trace)
    assert result.profile_count == 200
    assert "undefined" in result.message
    assert result.constant_trace_threshold_mm_s > 0.0
    for quantity in (
        result.first_zero_crossing,
        result.decay_1e_lag,
        result.integral_time,
    ):
        assert quantity.supported is False
        assert quantity.value is None
        # the quantity says *why* it is unsupported, in the verdict's own words
        assert quantity.reason == result.message
    assert result.recurrence_peaks == ()
    assert result.period_claim.supported is False
    assert result.period_claim.period_s is None


def test_a_constant_trace_is_undefined_under_every_detrending() -> None:
    """The refusal path survives every detrending - which is exactly what it used not to do.

    The defect this locks out: the model's success-only invariant ("a linear trend is reported
    exactly when linear detrending ran") was asserted of every verdict, so a constant trace
    under ``mean+linear`` raised a pydantic ``ValidationError`` instead of returning the
    documented verdict. The verdict was unreachable for that mode, and the error was not even
    this module's own type, so a caller catching ``RecurrenceError`` crashed.
    """
    constant = np.full(200, 3.0)
    results = {
        mode: _recurrence(constant, np.arange(200) * DT_S, detrending=mode)
        for mode in Detrending
    }

    for mode, result in results.items():
        assert result.verdict is RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE, mode
        assert result.acf.size == 0, mode
        assert result.detrending is mode
        # a constant trace's measured spread really is zero, so zero here is a measurement
        assert result.trace_std_mm_s == pytest.approx(0.0), mode
    # the slope is reported exactly by the mode that fitted and removed a line
    assert results[Detrending.MEAN_AND_LINEAR].linear_trend_mm_s_per_s == pytest.approx(0.0)
    assert results[Detrending.MEAN].linear_trend_mm_s_per_s is None
    assert results[Detrending.NONE].linear_trend_mm_s_per_s is None


@pytest.mark.parametrize(
    ("name", "trace"),
    [
        ("constant", np.full(64, 3.0)),
        ("zero-variance", 5.0 + 1e-13 * np.arange(64) / 64.0),
        ("too-few", np.array([1.0, -1.0, 0.5])),
        ("non-finite", np.where(np.arange(64) == 7, np.nan, np.sin(np.arange(64) * 0.3))),
    ],
)
def test_every_unsupported_case_is_a_typed_verdict_under_every_detrending(
    name: str, trace: np.ndarray
) -> None:
    """The whole refusal family crossed with the whole detrending family: nine refusals, no raise.

    The cross is the point. The defect was invisible under the default detrending and fatal
    under ``mean+linear``, so a test that only exercised the default would have passed while
    the refusal path was broken for a third of the modes.
    """
    for mode in Detrending:
        result = _recurrence(trace, np.arange(trace.size) * DT_S, detrending=mode)

        assert result.verdict is not RecurrenceVerdict.DEFINED, (name, mode)
        assert result.acf.size == 0, (name, mode)
        assert result.lag_s.size == 0, (name, mode)
        assert result.message, (name, mode)
        assert result.period_claim.supported is False, (name, mode)
        assert result.first_zero_crossing.reason == result.message, (name, mode)


def test_an_effectively_zero_variance_trace_is_undefined() -> None:
    rng = np.random.default_rng(11)
    trace = 5.0 + 1e-13 * rng.normal(size=400)
    result = _recurrence(trace, np.arange(400) * DT_S)

    assert result.verdict is RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE
    assert result.acf.size == 0
    # the threshold that decided it is reported, not implied
    assert result.constant_trace_threshold_mm_s == pytest.approx(5e-9, rel=0.01)
    assert "threshold" in result.message
    assert result.period_claim.supported is False


def test_an_empty_view_cannot_be_built_so_the_no_samples_verdict_is_defensive() -> None:
    """Two halves of one guarantee, neither of which may disappear silently.

    No public call can reach ``UNDEFINED_NO_SAMPLES`` any more: a ``WindowView`` refuses to
    exist without at least one profile and one gate, so the estimator can never be handed an
    empty series. The public guarantee is tested through the view that now enforces it, and
    the verdict itself through the private estimator that still carries it - the branch is
    kept because a refusal that cannot be expressed is not the same thing as one that cannot
    happen.
    """
    trace = np.sin(np.arange(32) * 0.3)
    window = _window(trace, np.arange(32) * DT_S)
    with pytest.raises(ValidationError, match="at least one profile"):
        WindowView(
            **{
                **window.model_dump(),
                "values": np.empty((0, 1)),
                "time_s": np.empty(0),
                "stop_index": 0,
            }
        )

    result = _recurrence_of_trace(
        np.empty(0),
        time_s=np.empty(0),
        provenance=view_provenance(window),
        gate_index=0,
        depth_mm=10.0,
        quantity="axial_velocity",
        unit="mm/s",
        detrending=Detrending.MEAN,
        max_lag_s=None,
        weak_peak_correlation=WEAK_PEAK_CORRELATION,
        min_candidate_cycles=MIN_CANDIDATE_CYCLES,
    )

    assert result.verdict is RecurrenceVerdict.UNDEFINED_NO_SAMPLES
    assert result.raw_trace.size == 0
    # ``profile_count`` reads the provenance rather than the array, deliberately: the view is
    # the authority on how many profiles were cut, and this private call is the one place the
    # two can disagree - which is the point of not restating the identity beside the curve.
    assert result.profile_count == result.provenance.profiles == 32
    assert result.lag_s.size == 0 and result.acf.size == 0
    # nothing finite existed to summarize, so nothing is summarized: no substituted zero
    assert result.trace_std_mm_s is None
    assert result.trace_mean_mm_s is None
    assert result.period_claim.supported is False
    assert result.message


def test_a_trace_shorter_than_the_estimator_minimum_is_undefined() -> None:
    trace = np.array([1.0, -1.0, 0.5])
    result = _recurrence(trace, np.arange(3) * DT_S)

    assert result.verdict is RecurrenceVerdict.UNDEFINED_TOO_FEW_SAMPLES
    assert MIN_SAMPLES_FOR_ACF == 4
    assert str(MIN_SAMPLES_FOR_ACF) in result.message
    assert result.acf.size == 0


def test_a_non_finite_trace_returns_the_non_finite_verdict() -> None:
    trace = np.sin(np.arange(64) * 0.3)
    trace[7] = np.nan
    result = _recurrence(trace, np.arange(64) * DT_S)

    assert result.verdict is RecurrenceVerdict.UNDEFINED_NON_FINITE
    assert result.acf.size == 0
    assert "non-finite" in result.message
    # the descriptive trace statistics stay JSON-finite over the finite samples
    assert math.isfinite(result.trace_mean_mm_s)
    assert math.isfinite(result.trace_std_mm_s)


def test_a_refusal_reports_the_spread_it_could_measure_not_a_substituted_zero() -> None:
    """A refusal may not publish 0.0 for a spread it never measured.

    The spread used to be substituted with ``0.0`` on every refusal, so a trace with a NaN in
    it reported a standard deviation of exactly zero - a number a reader would take for a
    measurement, and the most wrong answer available for a non-finite trace. The refusal now
    summarizes the samples that do exist, and reports nothing at all when none do.
    """
    trace = np.sin(np.arange(64) * 0.3)
    trace[7] = np.nan
    result = _recurrence(trace, np.arange(64) * DT_S)
    finite = trace[np.isfinite(trace)]

    assert result.verdict is RecurrenceVerdict.UNDEFINED_NON_FINITE
    assert result.trace_std_mm_s == pytest.approx(float(np.std(finite)))
    assert result.trace_std_mm_s > 0.0
    assert result.trace_mean_mm_s == pytest.approx(float(np.mean(finite)))


def test_the_smallest_reachable_view_refuses_without_inventing_timing_metadata() -> None:
    """One stored profile is the smallest view the public surface can be handed.

    It establishes no sample interval at all, so every timing quantity the window does not
    define must be ``None``. The refusal used to substitute 0.0 for all of them, and a
    zero-valued interval or resolution is indistinguishable from a *measured* zero: a
    zero-length sample interval, a zero-Hz frequency resolution, an autocorrelation that
    reached lag zero. That is the same substitution this module already refuses for the
    spread, so the timing metadata obeys the same rule.
    """
    view = _window(np.array([3.0]), np.array([0.0]), gates=1)
    result = recurrence_of_view(view, depth_mm=float(view.depths_mm[0]))

    assert result.verdict is RecurrenceVerdict.UNDEFINED_TOO_FEW_SAMPLES
    # The invented zeros: no interval, no lag resolution, no achieved lag range, and no
    # period resolution behind the period refusal.
    assert result.sample_interval_s is None
    assert result.lag_resolution_s is None
    assert result.max_lag_s is None
    assert result.period_claim.period_resolution_s is None
    # One stamp spans no duration, so 1/T is not defined either.
    assert result.frequency_resolution_hz is None
    # It is still a typed verdict carrying its own reason and an empty curve, not an
    # exception and not a zero-valued curve.
    assert result.message
    assert result.acf.size == 0 and result.lag_s.size == 0
    assert result.period_claim.period_s is None


def test_a_two_stamp_window_carries_its_measured_interval_and_not_a_zero() -> None:
    """A positive span defines the interval even when there are too few samples for a curve.

    The boundary is two stamps: one gap is a real measurement of the spacing between them,
    so it is published rather than withheld. What the axis cannot yet support is a
    *regularity* verdict, and that is ``classify_timebase``'s own statement - a separate
    question from whether the interval exists.
    """
    result = _recurrence(np.array([3.0, 4.0]), np.array([0.0, DT_S]))

    assert result.verdict is RecurrenceVerdict.UNDEFINED_TOO_FEW_SAMPLES
    assert result.sample_interval_s == pytest.approx(DT_S)
    assert result.lag_resolution_s == pytest.approx(DT_S)
    assert result.frequency_resolution_hz == pytest.approx(1.0 / DT_S)
    # No curve was computed, so the achieved lag range is undefined, not zero.
    assert result.max_lag_s is None


# ── the synthetic families the plan names ─────────────────────────────


def test_an_intermittent_trace_with_zero_samples_is_defined() -> None:
    """Dropouts that are exactly 0.0 are not zero variance: the ACF is defined."""
    rng = np.random.default_rng(3)
    trace = rng.normal(scale=2.0, size=400)
    trace[:200] = 0.0
    result = _recurrence(trace, np.arange(400) * DT_S)

    assert result.verdict is RecurrenceVerdict.DEFINED
    assert result.trace_zero_fraction == pytest.approx(0.5)
    assert result.acf[0] == pytest.approx(1.0)
    assert np.all(np.isfinite(result.acf))
    assert result.lag_s[0] == 0.0


def test_a_correlated_trace_is_defined_and_its_decay_is_reported() -> None:
    direction = 0.9
    count = 600
    rng = np.random.default_rng(7)
    trace = np.zeros(count)
    for index in range(1, count):
        trace[index] = direction * trace[index - 1] + rng.normal()
    time_s = np.arange(count) * DT_S
    result = _recurrence(trace, time_s)

    assert result.verdict is RecurrenceVerdict.DEFINED
    assert result.acf[0] == pytest.approx(1.0)
    assert np.all(np.abs(result.acf) <= 1.0 + 1e-9)
    # the 1/e decay of an AR(1) trace is analytic: -dt / ln(phi)
    analytic = -DT_S / math.log(direction)
    assert result.decay_1e_lag.supported is True
    assert result.decay_1e_lag.value == pytest.approx(analytic, rel=0.15)
    # a correlated trace is not a recurring one, and no period is claimed
    assert result.period_claim.supported is False
    assert result.period_claim.reason


def test_a_monotone_decaying_trace_has_no_recurrence_and_refuses_a_period() -> None:
    """A decaying trace supports a decay lag and an integral time, but no period."""
    count = 200
    trace = 0.95 ** np.arange(count)
    result = _recurrence(trace, np.arange(count) * DT_S)

    assert result.verdict is RecurrenceVerdict.DEFINED
    # a monotone decay never turns back up: there is no recurrence to claim from
    assert result.recurrence_peaks == ()
    assert "no local maximum" in result.peaks_reason
    assert result.period_claim.supported is False
    assert result.period_claim.peak_lag_s is None
    # the 1/e decay lag and the integral time are the two quantities this trace
    # does support, and both sit just under the analytic geometric decay: the
    # finite-window biased estimator weights long lags down
    analytic = -DT_S / math.log(0.95)
    assert result.decay_1e_lag.supported is True
    assert result.decay_1e_lag.value == pytest.approx(analytic, rel=0.08)
    assert result.integral_time.supported is True
    assert result.integral_time.value == pytest.approx(analytic, rel=0.15)
    # the mean-removed tail does eventually cross zero, well past the decay lag
    # (measured at ~2.7x it), and the integral is truncated there
    assert result.first_zero_crossing.supported is True
    assert result.first_zero_crossing.value > 2.0 * analytic
    assert result.integral_time.value < result.first_zero_crossing.value


def test_a_white_noise_trace_reports_no_admissible_recurrence() -> None:
    rng = np.random.default_rng(4242)
    count = 800
    trace = rng.normal(size=count)
    result = _recurrence(trace, np.arange(count) * DT_S)

    assert result.verdict is RecurrenceVerdict.DEFINED
    # the crossing and the integral time are supported here: the ACF dies at the
    # first lag, which is exactly what an integral time needs
    assert result.first_zero_crossing.supported is True
    assert 0.0 < result.first_zero_crossing.value <= DT_S
    assert result.integral_time.supported is True
    assert 0.0 < result.integral_time.value <= DT_S
    # every peak a white-noise ACF can show is weak, so none supports a period
    assert all(peak.weak for peak in result.recurrence_peaks)
    assert result.period_claim.supported is False


# ── resolution honesty and the period claim ───────────────────────────


def test_the_lag_and_frequency_resolution_are_reported() -> None:
    trace, time_s = _periodic(1.0)
    result = _recurrence(trace, time_s)
    count = trace.size

    assert result.sample_interval_s == pytest.approx(
        (time_s[-1] - time_s[0]) / (count - 1)
    )
    assert result.lag_resolution_s == result.sample_interval_s
    assert result.frequency_resolution_hz == pytest.approx(
        1.0 / result.window_duration_s
    )
    assert result.max_lag_s == pytest.approx((count // 2) * DT_S)
    assert result.profile_count == count
    assert result.window_duration_s == pytest.approx(time_s[-1] - time_s[0])


@pytest.mark.parametrize("period_s", [1.0, 0.7, 0.35])
def test_a_known_period_is_recovered_within_the_stated_resolution(
    period_s: float,
) -> None:
    """Three periods, none privileged: the estimator is not tuned to ~1 s."""
    trace, time_s = _periodic(period_s)
    result = _recurrence(trace, time_s)
    claim = result.period_claim

    assert claim.supported is True, claim.reason
    assert claim.period_s == pytest.approx(period_s, abs=2 * result.lag_resolution_s)
    assert claim.period_resolution_s == result.lag_resolution_s
    assert claim.candidate_cycles_in_window == pytest.approx(
        result.window_duration_s / claim.peak_lag_s
    )
    assert claim.candidate_cycles_in_window >= MIN_CANDIDATE_CYCLES
    # the thresholds that allowed the claim are named in the reason and carried
    assert claim.weak_peak_correlation == WEAK_PEAK_CORRELATION
    assert claim.min_candidate_cycles == MIN_CANDIDATE_CYCLES
    assert "weak-peak" in claim.reason
    assert "candidate cycles" in claim.reason
    assert claim.peak_correlation is not None
    assert claim.peak_correlation >= WEAK_PEAK_CORRELATION


def test_a_window_too_short_for_a_period_refuses_the_claim() -> None:
    """2.4 s holds 2.4 candidate cycles of a 1 s lag: too few for a period."""
    trace, time_s = _periodic(1.0, dt_s=0.05, duration_s=2.45)
    result = _recurrence(trace, time_s)
    claim = result.period_claim

    # the recurrence itself is visible, so the refusal is about the window
    assert any(not peak.weak for peak in result.recurrence_peaks)
    assert claim.supported is False
    assert claim.period_s is None
    assert "candidate cycles" in claim.reason
    assert "min_candidate_cycles" in claim.reason
    assert claim.candidate_cycles_in_window is not None
    assert claim.candidate_cycles_in_window < MIN_CANDIDATE_CYCLES
    # the evidence for the refusal, and the resolution, are still reported
    assert claim.peak_lag_s is not None
    assert claim.peak_correlation is not None
    assert result.frequency_resolution_hz == pytest.approx(
        1.0 / result.window_duration_s
    )
    assert result.lag_resolution_s == result.sample_interval_s


def test_a_weak_peak_cannot_support_a_period_claim() -> None:
    trace, time_s = _periodic(1.0)
    result = _recurrence(trace, time_s, weak_peak_correlation=0.999)
    claim = result.period_claim

    assert all(peak.weak for peak in result.recurrence_peaks)
    assert claim.supported is False
    assert "weak-peak" in claim.reason
    assert claim.weak_peak_correlation == 0.999


def test_every_reported_peak_carries_its_own_status_and_the_claim_names_its_peak() -> (
    None
):
    """A peak is a recurrence, a weak peak or a shoulder, and it says which."""
    trace, time_s = _periodic(1.0)
    result = _recurrence(trace, time_s)

    assert result.recurrence_peaks
    for peak in result.recurrence_peaks:
        assert peak.reason
        assert any(
            word in peak.reason for word in ("recurrence", "weak", "shoulder")
        ), peak.reason
        assert peak.lag_s > 0.0
        assert 0.0 < peak.correlation <= 1.0
    # the claim uses the *first* admissible recurrence, and names it
    first = next(
        peak
        for peak in result.recurrence_peaks
        if not peak.weak and peak.preceded_by_dip_below_weak_threshold
    )
    assert result.period_claim.peak_lag_s == pytest.approx(first.lag_s, abs=1e-12)
    assert result.period_claim.peak_correlation == pytest.approx(
        first.correlation, abs=1e-12
    )


def test_the_period_claim_reason_names_the_threshold_it_used() -> None:
    trace, time_s = _periodic(1.0)
    supported = _recurrence(trace, time_s).period_claim
    refused = _recurrence(trace, time_s, min_candidate_cycles=100.0).period_claim

    assert str(MIN_CANDIDATE_CYCLES) in supported.reason
    assert refused.supported is False
    assert "100" in refused.reason
    assert refused.period_s is None


# ── the refusal contract ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "max_lag_s",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(-1.0, id="negative"),
        pytest.param(0.0, id="zero"),
    ],
)
def test_a_lag_range_that_is_not_a_duration_is_refused_by_name(max_lag_s: float) -> None:
    """A lag range is a duration, and this module says so in its own error type.

    ``nan`` reached the lag-index conversion and raised a bare ``ValueError``; ``inf`` reached
    it and raised ``OverflowError``. Neither is a ``RecurrenceError``, so a caller catching the
    documented refusal crashed instead - and neither error named the argument at fault. A
    refusal path that can raise a builtin is a contradiction of the whole contract.
    """
    trace, time_s = _periodic(1.0, duration_s=6.0)
    with pytest.raises(RecurrenceError, match="max_lag_s"):
        _recurrence(trace, time_s, max_lag_s=max_lag_s)


def test_a_requested_lag_range_is_recorded_beside_the_achieved_one() -> None:
    """The report has to distinguish what was asked for from what the grid delivered.

    The conversion from a duration to a whole number of lag steps used to round to nearest,
    which could report a lag *beyond* the range the caller asked for; it floors now, and both
    numbers travel in the result so a reader is never left with the achieved one alone.
    """
    trace, time_s = _periodic(1.0, duration_s=12.0)
    result = _recurrence(trace, time_s, max_lag_s=2.0)

    assert result.requested_max_lag_s == 2.0
    assert result.max_lag_s <= 2.0
    assert result.max_lag_s > 0.0
    assert result.max_lag_s == pytest.approx(math.floor(2.0 / DT_S) * DT_S)
    # the default asks for nothing, and says so
    assert _recurrence(trace, time_s).requested_max_lag_s is None


def test_an_unknown_detrending_is_refused() -> None:
    trace, time_s = _periodic(1.0, duration_s=6.0)
    with pytest.raises(RecurrenceError, match="detrending"):
        _recurrence(trace, time_s, detrending="spline")


def test_thresholds_outside_their_range_are_refused() -> None:
    trace, time_s = _periodic(1.0, duration_s=6.0)
    for bad in (0.0, 1.0, -0.5, 2.0):
        with pytest.raises(RecurrenceError, match="weak_peak_correlation"):
            _recurrence(trace, time_s, weak_peak_correlation=bad)
    with pytest.raises(RecurrenceError, match="min_candidate_cycles"):
        _recurrence(trace, time_s, min_candidate_cycles=0.5)


# ── the timebase ──────────────────────────────────────────────────────


def test_a_regular_timebase_supports_the_lag_claims_and_carries_the_grid_rule() -> None:
    trace, time_s = _periodic(1.0, duration_s=12.0)
    result = _recurrence(trace, time_s)

    assert result.timebase is TimebaseVerdict.REGULAR
    assert result.lag_claims_supported is True
    assert result.max_relative_interval_deviation == pytest.approx(0.0, abs=1e-9)
    assert result.timebase_reason
    # the uniform-grid assumption is stated in the result rather than left to a reader, so
    # the next stage inherits it consciously
    assert result.lag_grid_rule == LAG_GRID_RULE
    assert "full-span effective interval" in result.lag_grid_rule
    assert f"{TIMEBASE_REGULARITY_TOL:.3e}" in result.timebase_reason
    assert "regular band" in result.timebase_reason


@pytest.mark.parametrize(
    ("jitter_fraction", "expected"),
    [
        pytest.param(0.0, TimebaseVerdict.REGULAR, id="uniform"),
        pytest.param(0.01, TimebaseVerdict.REGULAR, id="inside-the-band"),
        pytest.param(0.2, TimebaseVerdict.IRREGULAR, id="past-the-band"),
    ],
)
def test_the_regular_band_decides_the_verdict_where_the_constant_says_it_does(
    jitter_fraction: float, expected: TimebaseVerdict
) -> None:
    """The band is a declared number with a measured justification, not a tuning knob."""
    trace, time_s = _periodic(1.0, duration_s=12.0)
    jittered = time_s + jitter_fraction * DT_S * (np.arange(time_s.size) % 2)

    verdict, reason, deviation = classify_timebase(jittered)
    assert verdict is expected
    assert reason
    assert deviation is not None
    assert _recurrence(trace, jittered).timebase is expected


def test_a_degenerate_timebase_is_never_reported_as_perfectly_regular() -> None:
    """The regression, in one assertion: a broken axis must not score like an ideal one.

    With every stamp identical there is no positive interval to be regular about, and the
    diagnostic used to answer ``0.0`` - the most degenerate axis possible scoring as the most
    regular one possible, which is the single answer a regularity diagnostic must never give.
    It now reports no deviation at all and names the case, and the estimator refuses the axis
    outright rather than reporting lags on it.
    """
    stamps = np.full(64, 4.0)
    verdict, reason, deviation = classify_timebase(stamps)

    assert verdict is TimebaseVerdict.UNDEFINED_TIMEBASE
    assert deviation is None
    assert "no stored interval is positive" in reason
    with pytest.raises(RecurrenceError, match="positive sample interval"):
        _recurrence(np.sin(np.arange(64) * 0.3), stamps)


def test_duplicate_stamps_refuse_the_lag_claims_and_leave_the_curve_descriptive() -> None:
    """Two profiles sharing a stamp have no elapsed time between them: no lag is in seconds.

    The curve itself is not withdrawn - it is still the curve of the samples as stored - but
    every quantity expressed in seconds is refused with the timebase as its reason, rather
    than being reported off an axis that does not measure them.
    """
    trace, time_s = _periodic(1.0, duration_s=12.0)
    stamps = np.sort(np.concatenate([time_s, time_s[100:110]]))
    doubled = np.concatenate([trace, trace[100:110]])
    result = _recurrence(doubled, stamps)

    assert result.timebase is TimebaseVerdict.DUPLICATE_STAMPS
    assert result.max_relative_interval_deviation is not None
    assert result.verdict is RecurrenceVerdict.DEFINED
    assert result.acf.size == result.lag_s.size > 1
    assert result.lag_claims_supported is False
    assert result.recurrence_peaks == ()
    assert result.first_zero_crossing.supported is False
    assert result.decay_1e_lag.supported is False
    assert result.integral_time.supported is False
    assert result.period_claim.supported is False
    assert result.timebase.value in result.first_zero_crossing.reason
    assert result.timebase.value in result.period_claim.reason


def test_an_irregular_timebase_refuses_the_lag_claims_without_resampling() -> None:
    """A jittered axis is not re-gridded to manufacture a lag in seconds.

    The stored full-span effective interval is still the only lag step reported, so the
    irregularity is visible in the result rather than smoothed away by an interpolation the
    caller never asked for.
    """
    trace, time_s = _periodic(1.0, duration_s=12.0)
    jittered = time_s + 0.3 * DT_S * (np.arange(time_s.size) % 3)
    result = _recurrence(trace, jittered)

    assert result.timebase is TimebaseVerdict.IRREGULAR
    assert result.max_relative_interval_deviation > TIMEBASE_REGULARITY_TOL
    assert result.verdict is RecurrenceVerdict.DEFINED
    assert result.acf.size > 1
    assert result.recurrence_peaks == ()
    assert result.period_claim.supported is False
    assert TimebaseVerdict.IRREGULAR.value in result.period_claim.reason
    assert result.integral_time.supported is False
    assert result.lag_resolution_s == pytest.approx(
        (jittered[-1] - jittered[0]) / (jittered.size - 1)
    )


# ── provenance ────────────────────────────────────────────────────────


def test_the_view_labels_are_the_plans_own_words() -> None:
    assert SparseView.PRIMARY.value == "primary-comparison"
    assert SparseView.FULL_RECORD.value == "full-record"
    assert SparseView.EXPLORATION.value == "exploration"
    # the two spellings that used to coexist for the same concept no longer both parse,
    # and neither does anything else: one vocabulary, one meaning
    for stale in ("primary comparison", "full record", "vibes"):
        with pytest.raises(ValueError, match="not a valid"):
            SparseView(stale)


def test_the_view_rule_travels_with_its_label_and_cannot_disagree_with_it() -> None:
    """A view cannot carry a rule its own label does not own."""
    window = _window(np.sin(np.arange(32) * 0.3), np.arange(32) * DT_S)

    assert window.view_rule == sparse_view.view_rule(SparseView.PRIMARY)
    with pytest.raises(ValidationError, match="fixed by the plan"):
        WindowView(**{**window.model_dump(), "view_rule": "a rule nothing else shares"})


@pytest.mark.parametrize("view", list(SparseView))
def test_every_result_carries_its_view_its_window_and_its_settings(
    view: SparseView,
) -> None:
    trace, time_s = _periodic(1.0, duration_s=6.0)
    result = _recurrence(trace, time_s, view=view, label="gate-3", column=3, gates=4)

    assert result.view is view
    assert result.label == "gate-3"
    assert result.gate_index == 3
    assert result.depth_mm == pytest.approx(16.0)
    assert result.unit == "mm/s"
    assert result.quantity == "axial_velocity"
    assert result.window_start_s == pytest.approx(float(time_s[0]))
    assert result.window_end_s == pytest.approx(float(time_s[-1]))
    assert result.window_duration_s == pytest.approx(time_s[-1] - time_s[0])
    assert result.profile_count == trace.size
    assert result.detrending is Detrending.MEAN
    assert result.acf_estimator == ACF_ESTIMATOR
    assert result.weak_peak_correlation == WEAK_PEAK_CORRELATION
    assert result.min_candidate_cycles == MIN_CANDIDATE_CYCLES
    assert result.lag_grid_rule == LAG_GRID_RULE
    assert math.isfinite(result.max_relative_interval_deviation)


def test_the_result_carries_the_views_own_provenance_rather_than_a_parallel_copy() -> None:
    """A recurrence result is never anonymous, and its identity has exactly one home.

    The identity fields used to be restated beside the curve - and could be passed in
    independently of the arrays, so a result could name a view it was not cut from. They are
    now read back off the one shared provenance object, which is why the reading shortcuts
    below are properties of it rather than a second description that can drift.
    """
    trace, time_s = _periodic(1.0, duration_s=6.0)
    window = _window(trace, time_s, label="gate-3", column=3, gates=4)
    result = recurrence_of_view(window, depth_mm=float(window.depths_mm[3]))

    assert isinstance(result.provenance, ViewProvenance)
    assert result.provenance.source_sha256 == window.source_sha256
    assert result.provenance.job == "synthetic"
    assert result.provenance.order == 1
    assert result.provenance.view is SparseView.PRIMARY
    assert result.provenance.view_rule == sparse_view.view_rule(SparseView.PRIMARY)
    assert result.provenance.native_gates == window.native_gates
    assert result.provenance.pass_support_mm == window.pass_support_mm
    assert result.provenance.profiles == trace.size

    # the shortcuts are the provenance's own values
    assert result.view is result.provenance.view
    assert result.label == result.provenance.point_label == "gate-3"
    assert result.relative_path == result.provenance.relative_path
    assert result.window_start_s == result.provenance.window_start_s
    assert result.window_end_s == result.provenance.window_end_s
    assert result.window_duration_s == result.provenance.window_s
    assert result.profile_count == result.provenance.profiles


def test_the_result_carries_no_pseudoreplicate_uncertainty() -> None:
    """Profiles and gates are correlated samples: no confidence interval exists here."""
    forbidden = (
        "confidence",
        "p_value",
        "pseudoreplicate",
        "stderr",
        "standard_error",
        "bootstrap",
    )
    names = set(TraceRecurrence.model_fields)
    assert {name for name in names if any(word in name for word in forbidden)} == set()


def test_a_mismatched_trace_and_time_axis_is_no_longer_expressed_by_the_estimator() -> None:
    """The guarantee moved from the estimator to the view, and did not disappear.

    The estimator used to take a trace and a time axis separately and refuse a pair that did
    not share one length. That pair cannot be handed in any more: the view that supplies both
    refuses to exist when its values and its stamps disagree.
    """
    window = _window(np.ones(9), np.arange(9) * DT_S)
    with pytest.raises(ValidationError, match="one sample per profile"):
        WindowView(**{**window.model_dump(), "values": np.ones((10, 1))})


def test_a_time_axis_that_is_not_a_time_axis_is_refused_by_the_view() -> None:
    """A trace is a time series: the view refuses stamps that run backwards."""
    trace = np.sin(np.arange(64) * 0.3)
    window = _window(trace, np.arange(64) * DT_S)
    stamps = np.arange(64) * DT_S
    stamps[30] = stamps[5]

    with pytest.raises(ValidationError, match="must not decrease"):
        WindowView(**{**window.model_dump(), "time_s": stamps})


# ── the gate view and the shared windows ──────────────────────────────


def test_the_primary_view_cuts_the_designed_window_and_never_widens_it() -> None:
    point = _point(profiles=800, dt_s=0.025)
    time_s = np.asarray(point.time_s, dtype=float)
    window = primary_view(point, window_s=DESIGNED_WINDOW_S, support_mm=(5.0, 20.0))
    result = recurrence_of_view(window, depth_mm=12.0)

    assert result.view is SparseView.PRIMARY
    assert result.label == "sa1-view"
    assert result.gate_index == 1
    assert result.depth_mm == pytest.approx(12.0)
    assert result.profile_count == int(np.count_nonzero(time_s <= DESIGNED_WINDOW_S))
    assert result.profile_count < time_s.size
    assert result.window_end_s <= time_s[0] + DESIGNED_WINDOW_S + 1e-9
    assert result.window_duration_s < time_s[-1] - time_s[0]
    assert window.declared_window_s == DESIGNED_WINDOW_S


def test_the_full_record_view_is_labelled_and_is_not_a_window() -> None:
    point = _point(profiles=800, dt_s=0.025)
    time_s = np.asarray(point.time_s, dtype=float)
    window = full_record_view(point, support_mm=(5.0, 20.0))
    result = recurrence_of_view(window, depth_mm=10.0)

    assert result.view is SparseView.FULL_RECORD
    assert result.profile_count == time_s.size
    assert result.window_duration_s == pytest.approx(float(time_s[-1] - time_s[0]))
    # the full record is its own label precisely because its duration is not the design's
    assert window.declared_window_s is None


def test_an_exploration_window_is_labelled_separately() -> None:
    point = _point(profiles=800, dt_s=0.025)
    window = exploration_view(
        point,
        time_bounds_s=(0.0, 4.0),
        depth_bounds_mm=(10.0, 16.0),
        support_mm=(5.0, 20.0),
    )
    result = recurrence_of_view(window, depth_mm=10.0)

    assert result.view is SparseView.EXPLORATION
    assert result.window_duration_s <= 4.0 + 1e-9
    assert result.window_duration_s < 12.0
    assert window.view_rule == sparse_view.view_rule(SparseView.EXPLORATION)


def test_a_primary_window_that_is_not_a_duration_is_refused() -> None:
    point = _point(profiles=800, dt_s=0.025)
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(SparseViewError, match="finite and positive"):
            primary_view(point, window_s=bad, support_mm=(5.0, 20.0))


def test_a_recording_too_short_for_the_primary_window_is_refused_not_narrowed() -> None:
    """Five seconds of stamps against a twelve second design: refused, not redefined."""
    point = _point(profiles=200, dt_s=0.025)
    assert np.asarray(point.time_s)[-1] < DESIGNED_WINDOW_S
    with pytest.raises(SparseViewError, match="refused rather than widened"):
        primary_view(point, window_s=DESIGNED_WINDOW_S, support_mm=(5.0, 20.0))


def test_a_gate_outside_the_native_grid_or_the_support_is_refused() -> None:
    point = _point(profiles=800, dt_s=0.025)
    window = primary_view(point, window_s=DESIGNED_WINDOW_S, support_mm=(12.0, 18.0))

    # a depth that is not one of the recording's native gates is a view-level refusal
    with pytest.raises(SparseViewError, match="not one of this view's native gate depths"):
        recurrence_of_view(window, depth_mm=22.0)
    # a native gate outside the common support is an estimator-level refusal
    with pytest.raises(RecurrenceError, match="common physical support"):
        recurrence_of_view(window, depth_mm=10.0)

    inside = recurrence_of_view(window, depth_mm=14.0)
    assert inside.depth_mm == pytest.approx(14.0)


def test_an_exploration_view_reports_the_recording_grid_not_the_width_of_its_selection() -> (
    None
):
    """``native`` means the native recording, and a selection may not be mistaken for it.

    Selecting 3 gates out of an 11-gate recording used to make the provenance report
    ``native_gates == 3``, so anything computing "the fraction of native gates supported" was
    wrong for every exploration view - and wrong in the direction that looks most reasonable.
    """
    point = _point(profiles=800, dt_s=0.025, gates=11)
    grid = np.asarray(point.depths, dtype=float)
    window = exploration_view(
        point,
        time_bounds_s=(0.0, 6.0),
        depth_bounds_mm=(float(grid[2]), float(grid[4])),
        support_mm=(float(grid[0]), float(grid[-1])),
    )
    result = recurrence_of_view(window, depth_mm=float(window.depths_mm[0]))

    assert grid.size == 11
    assert window.depths_mm.size == 3
    assert window.native_gates == 11
    assert result.provenance.native_gates == 11
    assert result.provenance.supported_gates == 3
    assert result.provenance.participating_depth_extent_mm == (
        float(window.depths_mm[0]),
        float(window.depths_mm[-1]),
    )
    assert result.provenance.native_depth_extent_mm == (
        float(grid[0]),
        float(grid[-1]),
    )
    assert window.view is SparseView.EXPLORATION
    assert window.time_bounds_s == (0.0, 6.0)


# ── the committed reader path ─────────────────────────────────────────


def test_the_committed_reader_path_feeds_the_estimator() -> None:
    """One committed live-2 recording, through ``io.load`` and the 12 s window."""
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
    window = primary_view(
        point,
        window_s=DESIGNED_WINDOW_S,
        support_mm=(float(depths.min()), float(depths.max())),
    )
    result = recurrence_of_view(window, depth_mm=float(window.depths_mm[depths.size // 2]))

    assert result.verdict is RecurrenceVerdict.DEFINED
    assert result.profile_count > 100
    assert result.window_duration_s <= DESIGNED_WINDOW_S + 1e-9
    # the recording retains more than the designed exposure, and the primary view
    # is the designed exposure, not the retained surplus
    assert time_s[-1] - time_s[0] > DESIGNED_WINDOW_S
    assert result.profile_count < time_s.size
    assert result.acf[0] == pytest.approx(1.0)
    assert np.all(np.isfinite(result.acf))
    assert len(result.lag_s) == len(result.acf)
    assert result.view is SparseView.PRIMARY
    assert result.label == paths[0].stem
    # the committed cadence is regular, so its lags in seconds are claimed - and the
    # result says which timebase it saw rather than leaving it to be assumed
    assert result.timebase is TimebaseVerdict.REGULAR
    assert result.max_relative_interval_deviation < TIMEBASE_REGULARITY_TOL
    assert result.provenance.native_gates == depths.size
