"""Focused tests for the SA1 temporal-recurrence backend (plan ``SA1``).

Written RED first: ``analysis.sparse_recurrence`` did not exist when this module
was written, so every test below failed at collection with an import error. The
run before implementation is the RED evidence in the report.

The plan's temporal-recurrence paragraph is the specification, and each test
pins one of its sentences:

- "subtract the trace mean by default before normalized ACF; name any
  additional detrending method and show raw traces alongside it" —
  ``test_mean_subtraction_is_the_default_and_is_named``,
  ``test_linear_detrending_is_optional_named_and_the_raw_trace_stays``;
- "A constant or effectively zero-variance trace has undefined normalized ACF,
  not an all-zero correlation curve" —
  ``test_a_constant_trace_is_undefined_not_an_all_zero_curve``,
  ``test_a_constant_trace_is_undefined_at_every_constant_value``,
  ``test_an_effectively_zero_variance_trace_is_undefined``;
- "Report first zero crossing, 1/e decay, integral time and descriptive
  recurrence peaks only when supported by the window" — the
  ``SupportedQuantity`` assertions in the correlated, the monotone-decaying,
  the white-noise and the periodic tests;
- "seek but do not assume an approximately 1 s feature" and "Twelve seconds
  contains only about twelve candidate cycles, so report frequency/lag
  resolution and avoid a precise period claim from a weak peak" —
  ``test_a_known_period_is_recovered_within_the_stated_resolution`` (three
  different periods, none privileged),
  ``test_a_window_too_short_for_a_period_refuses_the_claim`` and
  ``test_a_weak_peak_cannot_support_a_period_claim``;
- "Test on constant, intermittent, correlated and known-period synthetic traces
  and on the committed reader path" — the four synthetic families plus
  ``test_the_committed_reader_path_feeds_the_estimator``;
- "No pseudoreplicate confidence intervals" —
  ``test_the_result_carries_no_pseudoreplicate_uncertainty``.

The view tests pin the plan's shared views: the primary comparison window is
the recording's own designed 0-12 s, "Refuse insufficient coverage; never widen
it", and the full record and exploration views carry their own labels.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_inventory import DESIGNED_WINDOW_S
from udv_echo_process.analysis.sparse_recurrence import (
    ACF_ESTIMATOR,
    MIN_CANDIDATE_CYCLES,
    MIN_SAMPLES_FOR_ACF,
    WEAK_PEAK_CORRELATION,
    Detrending,
    RecurrenceError,
    RecurrenceVerdict,
    RecurrenceView,
    TraceRecurrence,
    gate_recurrence,
    trace_recurrence,
)
from udv_echo_process.io import load

ROOT = Path(__file__).resolve().parent.parent
LIVE_2 = ROOT / "data" / "sparse-mixer-live-2"

#: The synthetic cadence the per-sample arithmetic below is checked against.
DT_S = 0.02


def _recurrence(
    trace: np.ndarray, time_s: np.ndarray, **settings: object
) -> TraceRecurrence:
    """One synthetic trace through the estimator, with the required provenance."""
    defaults: dict[str, object] = {"view": RecurrenceView.PRIMARY, "label": "synthetic"}
    defaults.update(settings)
    return trace_recurrence(trace, time_s=time_s, **defaults)


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


def _view(
    values: np.ndarray,
    time_s: np.ndarray,
    depths: np.ndarray,
    *,
    label: str = "sa1-view",
    relative_path: str = "sa1-view.BDD",
) -> SimpleNamespace:
    """A stand-in decoded view carrying the attributes ``gate_recurrence`` reads."""
    return SimpleNamespace(
        values=values,
        time_s=time_s,
        depths=depths,
        relative_path=relative_path,
        binding=SimpleNamespace(point=SimpleNamespace(label=label)),
    )


def _synthetic_view(
    *, profiles: int = 800, dt_s: float = 0.025, gates: int = 4
) -> SimpleNamespace:
    """A 20 s, four-gate view, so the 12 s primary cut is a strict subset."""
    time_s = np.arange(profiles) * dt_s
    values = np.empty((profiles, gates))
    for gate in range(gates):
        scale = 1.0 + gate
        values[:, gate] = scale * np.sin(2.0 * np.pi * time_s / 1.0) + 0.2 * scale
    depths = np.array([5.0, 10.0, 15.0, 20.0])
    return _view(values, time_s, depths)


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


def test_a_trace_with_no_samples_returns_the_no_samples_verdict() -> None:
    result = _recurrence(np.empty(0), np.empty(0))

    assert result.verdict is RecurrenceVerdict.UNDEFINED_NO_SAMPLES
    assert result.profile_count == 0
    assert result.raw_trace.size == 0
    assert result.lag_s.size == 0 and result.acf.size == 0
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


# ── the detrending discipline ─────────────────────────────────────────


def test_mean_subtraction_is_the_default_and_is_named() -> None:
    count = 300
    time_s = np.arange(count) * DT_S
    trace = 8.0 + np.sin(2.0 * np.pi * time_s / 1.0)
    result = _recurrence(trace, time_s)

    assert result.detrending is Detrending.MEAN
    assert result.trace_mean_mm_s == pytest.approx(8.0, abs=0.05)
    assert float(np.mean(result.detrended_trace)) == pytest.approx(0.0, abs=1e-12)
    assert np.allclose(result.raw_trace, trace)
    assert result.acf[0] == pytest.approx(1.0)

    raw_only = _recurrence(trace, time_s, detrending=Detrending.NONE)
    assert raw_only.detrending is Detrending.NONE
    assert np.allclose(raw_only.raw_trace, trace)
    # the offset is what the mean removal takes out: without it the curve is the
    # offset's, with it the recurrence is visible
    assert raw_only.acf[12] > 0.95
    assert result.acf[12] < 0.2


def test_linear_detrending_is_optional_named_and_the_raw_trace_stays() -> None:
    count = 400
    time_s = np.arange(count) * DT_S
    trace = 0.5 * time_s + 0.2 * np.sin(2.0 * np.pi * time_s / 0.5)
    result = _recurrence(trace, time_s, detrending=Detrending.MEAN_AND_LINEAR)

    assert result.detrending is Detrending.MEAN_AND_LINEAR
    assert result.linear_trend_mm_s_per_s == pytest.approx(0.5, rel=0.05)
    assert np.allclose(result.raw_trace, trace)
    slope = float(np.polyfit(time_s, result.detrended_trace, 1)[0])
    assert abs(slope) < 1e-8

    mean_only = _recurrence(trace, time_s)
    assert mean_only.linear_trend_mm_s_per_s is None
    kept = float(np.polyfit(time_s, mean_only.detrended_trace, 1)[0])
    assert kept == pytest.approx(0.5, rel=0.01)


# ── provenance ────────────────────────────────────────────────────────


def test_the_view_labels_are_the_plans_own_words() -> None:
    assert RecurrenceView.PRIMARY.value == "primary comparison"
    assert RecurrenceView.FULL_RECORD.value == "full record"
    assert RecurrenceView.EXPLORATION.value == "exploration"


@pytest.mark.parametrize("view", list(RecurrenceView))
def test_every_result_carries_its_view_its_window_and_its_settings(
    view: RecurrenceView,
) -> None:
    trace, time_s = _periodic(1.0, duration_s=6.0)
    result = _recurrence(trace, time_s, view=view, label="gate-3", gate_index=3)

    assert result.view is view
    assert result.label == "gate-3"
    assert result.gate_index == 3
    assert result.unit == "mm/s"
    assert result.window_start_s == pytest.approx(float(time_s[0]))
    assert result.window_end_s == pytest.approx(float(time_s[-1]))
    assert result.window_duration_s == pytest.approx(time_s[-1] - time_s[0])
    assert result.profile_count == trace.size
    assert result.detrending is Detrending.MEAN
    assert result.acf_estimator == ACF_ESTIMATOR
    assert result.weak_peak_correlation == WEAK_PEAK_CORRELATION
    assert result.min_candidate_cycles == MIN_CANDIDATE_CYCLES
    assert math.isfinite(result.max_relative_interval_deviation)


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


def test_a_trace_and_a_time_axis_that_do_not_share_one_length_are_refused() -> None:
    with pytest.raises(RecurrenceError, match="length"):
        _recurrence(np.ones(10), np.arange(9) * DT_S)


def test_a_time_axis_that_is_not_a_time_axis_is_refused() -> None:
    time_s = np.arange(64) * DT_S
    time_s[10] = time_s[20]
    time_s[30] = time_s[5]
    with pytest.raises(RecurrenceError, match="non-decreasing"):
        _recurrence(np.sin(np.arange(64) * 0.3), time_s)


def test_an_unknown_view_or_detrending_is_refused() -> None:
    time_s = np.arange(64) * DT_S
    trace = np.sin(np.arange(64) * 0.3)
    with pytest.raises(RecurrenceError, match="view"):
        _recurrence(trace, time_s, view="vibes")
    with pytest.raises(RecurrenceError, match="detrending"):
        _recurrence(trace, time_s, detrending="spline")


# ── the gate view and the shared windows ──────────────────────────────


def test_the_primary_view_cuts_the_designed_window_and_never_widens_it() -> None:
    point = _synthetic_view()
    time_s = np.asarray(point.time_s, dtype=float)
    result = gate_recurrence(
        point, gate_index=1, view=RecurrenceView.PRIMARY, window_s=DESIGNED_WINDOW_S
    )

    assert result.view is RecurrenceView.PRIMARY
    assert result.label == "sa1-view"
    assert result.gate_index == 1
    assert result.depth_mm == pytest.approx(10.0)
    assert result.profile_count == int(np.count_nonzero(time_s <= DESIGNED_WINDOW_S))
    assert result.profile_count < time_s.size
    assert result.window_end_s <= time_s[0] + DESIGNED_WINDOW_S + 1e-9
    assert result.window_duration_s < time_s[-1] - time_s[0]


def test_the_full_record_view_is_labelled_and_is_not_a_window() -> None:
    point = _synthetic_view()
    result = gate_recurrence(point, gate_index=0, view=RecurrenceView.FULL_RECORD)

    assert result.view is RecurrenceView.FULL_RECORD
    assert result.profile_count == np.asarray(point.time_s).size
    with pytest.raises(RecurrenceError, match="window_s"):
        gate_recurrence(
            point,
            gate_index=0,
            view=RecurrenceView.FULL_RECORD,
            window_s=DESIGNED_WINDOW_S,
        )


def test_an_exploration_window_is_labelled_separately() -> None:
    point = _synthetic_view()
    result = gate_recurrence(
        point, gate_index=0, view=RecurrenceView.EXPLORATION, window_s=4.0
    )
    assert result.view is RecurrenceView.EXPLORATION
    assert result.window_duration_s <= 4.0 + 1e-9
    assert result.window_duration_s < 12.0


def test_a_primary_window_without_its_window_is_refused() -> None:
    point = _synthetic_view()
    with pytest.raises(RecurrenceError, match="window_s"):
        gate_recurrence(point, gate_index=0, view=RecurrenceView.PRIMARY)


def test_a_recording_too_short_for_the_primary_window_is_refused_not_narrowed() -> None:
    point = _synthetic_view(profiles=200)
    with pytest.raises(RecurrenceError, match="never widened"):
        gate_recurrence(
            point,
            gate_index=0,
            view=RecurrenceView.PRIMARY,
            window_s=DESIGNED_WINDOW_S,
        )


def test_a_gate_outside_the_native_grid_or_the_support_is_refused() -> None:
    point = _synthetic_view()
    with pytest.raises(RecurrenceError, match="native gates"):
        gate_recurrence(
            point,
            gate_index=4,
            view=RecurrenceView.PRIMARY,
            window_s=DESIGNED_WINDOW_S,
        )
    with pytest.raises(RecurrenceError, match="common physical support"):
        gate_recurrence(
            point,
            gate_index=1,
            view=RecurrenceView.PRIMARY,
            window_s=DESIGNED_WINDOW_S,
            support_mm=(12.0, 18.0),
        )
    inside = gate_recurrence(
        point,
        gate_index=2,
        view=RecurrenceView.PRIMARY,
        window_s=DESIGNED_WINDOW_S,
        support_mm=(12.0, 18.0),
    )
    assert inside.depth_mm == pytest.approx(15.0)


# ── the committed reader path ─────────────────────────────────────────


def test_the_committed_reader_path_feeds_the_estimator() -> None:
    """One committed live-2 recording, through ``io.load`` and the 12 s window."""
    paths = sorted(LIVE_2.glob("*.BDD"))
    assert len(paths) == 26
    data = load(paths[0]).recording.streams[0].data
    values = np.asarray(data.values, dtype=float)
    time_s = np.asarray(data.time_s, dtype=float)
    depths = np.asarray(data.gate_depths_mm, dtype=float)
    point = _view(
        values, time_s, depths, label=paths[0].stem, relative_path=paths[0].name
    )

    result = gate_recurrence(
        point,
        gate_index=depths.size // 2,
        view=RecurrenceView.PRIMARY,
        window_s=DESIGNED_WINDOW_S,
    )

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
    assert result.view is RecurrenceView.PRIMARY
    assert result.label == paths[0].stem
