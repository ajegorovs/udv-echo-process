"""Normalized temporal autocorrelation of one gate's trace (plan SA1).

The sparse plan's *temporal recurrence* paragraph, implemented once as plain
functions so a notebook can only select inputs and display results ("Notebooks
select inputs and display those results; they do not implement estimators").

What is measured
----------------
One gate's trace is a velocity-versus-time series (one signed line-of-sight
component at one native gate depth). :func:`trace_recurrence` subtracts the
trace mean **by default** and returns the normalized autocorrelation of the
remainder — the *biased*, divide-by-N autocovariance scaled so ``acf[0] == 1``,
the same estimator name the sibling temporal work uses. Additional detrending is
optional (:class:`Detrending`), is named in the result, and always arrives with
both the analysed and the **raw** trace, so a reader can see what was removed.

What is refused
---------------
- A constant, or effectively zero-variance, trace has an **undefined**
  normalized autocorrelation. The result says so
  (:data:`RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE`) and returns no curve at
  all: an all-zero correlation curve would be a silently substituted value, and
  the threshold that decided it is reported
  (:attr:`TraceRecurrence.constant_trace_threshold_mm_s`).
- A descriptive quantity — first zero crossing, 1/e decay lag, integral time,
  recurrence peaks — is reported as a number only where the lag range actually
  reaches it. Otherwise its :class:`SupportedQuantity` carries
  ``supported=False`` and the reason, and the value stays ``None``.
- A period is claimed only from a recurrence peak that clears named thresholds.
  The plan: "Twelve seconds contains only about twelve candidate cycles, so
  report frequency/lag resolution and avoid a precise period claim from a weak
  peak." Both resolutions (:attr:`TraceRecurrence.lag_resolution_s` — one
  profile period, the only lag step the stored timestamps define — and
  :attr:`TraceRecurrence.frequency_resolution_hz` — ``1 / window duration``) are
  reported by every result, and every threshold a claim depends on is a constant
  of this module and a field of every result.

Two explanations are not separated here
---------------------------------------
A recurrence peak is *descriptive*. A moving flow crossing a fixed beam and a
wandering central vortex are both compatible with a repeating trace, and nothing
here chooses between them or between those and acquisition-order drift. The
hypothesized ~1 s vortex timescale is **sought, never assumed**: no constant
below encodes it, the thresholds are expressed in the trace's own units and
lags, and the tests recover three different periods without privileging one.

Not here (deliberately)
-----------------------
- **No pseudoreplicate uncertainty.** Profiles and gates are correlated samples,
  not independent realizations, so no confidence interval, standard error or
  p-value is computed and none is a field of any result.
- **No sampling-support guard.** Declaring a jitter or gap threshold and
  refusing or documenting resampling before evenly sampled spectral methods is
  SA2's slice. This module *reports* the jitter it saw
  (``max_relative_interval_deviation``) and uses the full-span effective
  interval with the same reasoning the echo-RPM step documents (a quantized DOP
  timebase makes the median interval the dominant timestamp quantum rather than
  the period); it does not silently re-grid a structurally sampled axis.
- **No frequency-domain estimate.** The ACF is a time-domain curve; spectra,
  bandpower and Nyquist support are SA2.
- **No cross-gate or cross-recording reduction.** One gate, one recording, one
  window per result — collapsing gates early is what the plan forbids.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import Enum

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._native_grid import (
    TOLERANCE_S,
    in_support,
    window,
)
from udv_echo_process.analysis.sparse_inventory import DecodedPoint
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field

# ── named method settings ─────────────────────────────────────────────

#: The estimator every defined result names. The divide-by-N (biased)
#: autocovariance of the detrended trace is scaled by its own zero-lag value, so
#: ``acf[0] == 1`` exactly and no precision is claimed past the lag grid.
ACF_ESTIMATOR = "biased (divide-by-N) autocovariance of the detrended trace"

#: The normalized autocorrelation below which a recurrence peak is called *weak*.
#: Named because the plan asks for the threshold a claim rests on to be visible:
#: a peak weaker than this is reported as a descriptive maximum and supports no
#: period claim.
WEAK_PEAK_CORRELATION = 0.3

#: Whole candidate cycles of the recovered lag that must fit the window before a
#: period is claimed. The plan's own arithmetic sets the scale: 12 s holds only
#: about twelve candidate cycles of a ~1 s feature, so a lag leaving fewer than
#: three whole cycles in the window is a refusal, not a period.
MIN_CANDIDATE_CYCLES = 3.0

#: Lag steps (profile periods) a peak must sit above before its lag is a period
#: at all: one step is the lag resolution, not a measurement of recurrence.
MIN_PEAK_LAG_STEPS = 2

#: Fewest samples a normalized autocorrelation is defined on.
MIN_SAMPLES_FOR_ACF = 4

#: A trace is *effectively* constant when the standard deviation of the analysed
#: (detrended) trace is at or below
#: ``max(CONSTANT_TRACE_ABSOLUTE_TOL, CONSTANT_TRACE_RELATIVE_TOL * max|trace|)``.
CONSTANT_TRACE_RELATIVE_TOL = 1e-9
CONSTANT_TRACE_ABSOLUTE_TOL = 1e-12

#: The lag at which a normalized autocorrelation has fallen to 1/e.
INVERSE_E = 1.0 / math.e


class RecurrenceError(ValueError):
    """A recurrence input is not one trace of one view.

    Raised for a trace and a time axis that do not share one length, a time axis
    that is not non-decreasing, an unknown view or detrending, a gate outside
    the recording's native grid or its common physical support, a view asked for
    without its own window (or a window the view does not take), and a window
    the stored timestamps do not cover. Every one of those is an input the
    caller can fix; a trace that merely *cannot* support a quantity is not an
    error but a verdict (:class:`RecurrenceVerdict`).
    """


class RecurrenceView(str, Enum):
    """Which of the plan's shared views a trace came from.

    The plan requires the label to be visible in the result, so it is a required
    argument of every entry point and a field of every result. The exploration
    label can therefore never silently replace the primary comparison.
    """

    PRIMARY = "primary comparison"
    FULL_RECORD = "full record"
    EXPLORATION = "exploration"


class Detrending(str, Enum):
    """What is removed from a trace before it is correlated.

    ``MEAN`` is the default the plan asks for ("subtract the trace mean by
    default before normalized ACF"). ``MEAN_AND_LINEAR`` is the optional,
    additionally named detrending — a least-squares line over the stored
    timestamps, whose slope is reported. ``NONE`` correlates the raw trace and
    exists so the effect of the mean removal is inspectable rather than implied.
    """

    MEAN = "mean"
    MEAN_AND_LINEAR = "mean+linear"
    NONE = "none"


class RecurrenceVerdict(str, Enum):
    """Whether a normalized autocorrelation is defined, and if not, why.

    ``DEFINED`` is the only verdict that carries a curve. Every other verdict is
    an explicit typed answer — never an all-zero correlation curve and never a
    substituted value — and its message names the threshold or the shortfall.
    """

    DEFINED = "defined"
    UNDEFINED_CONSTANT_TRACE = "undefined-constant-trace"
    UNDEFINED_NO_SAMPLES = "undefined-no-samples"
    UNDEFINED_TOO_FEW_SAMPLES = "undefined-too-few-samples"
    UNDEFINED_NON_FINITE = "undefined-non-finite"


class SupportedQuantity(ValueModel):
    """One descriptive scalar with an explicit support verdict.

    ``value is not None`` exactly when ``supported`` is true, so a reader can
    never mistake an unsupported quantity for a measured zero. Every unsupported
    quantity carries the reason it was not computed.
    """

    value: float | None
    unit: str
    supported: bool
    reason: str

    @model_validator(mode="after")
    def _value_and_verdict_agree(self) -> SupportedQuantity:
        if self.supported != (self.value is not None):
            raise ValueError(
                "a supported quantity carries a value and an unsupported one "
                f"does not (supported={self.supported!r}, value={self.value!r})"
            )
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError(f"a reported quantity must be finite, got {self.value!r}")
        if not self.reason.strip():
            raise ValueError("every quantity states why it is or is not reported")
        return self


class RecurrencePeak(ValueModel):
    """One descriptive local maximum of a normalized autocorrelation.

    Reported with its lag, its correlation, whether it is below
    :data:`WEAK_PEAK_CORRELATION`, and whether the autocorrelation had fallen
    below that threshold before it — a maximum riding a still-correlated plateau
    is a *shoulder*, not a recurrence. Nothing about a peak is a period claim;
    that is :class:`PeriodClaim`.
    """

    lag_s: float
    correlation: float
    weak: bool
    preceded_by_dip_below_weak_threshold: bool
    reason: str

    @model_validator(mode="after")
    def _check(self) -> RecurrencePeak:
        if not (self.lag_s > 0.0 and math.isfinite(self.lag_s)):
            raise ValueError(
                f"a peak's lag must be finite and positive: {self.lag_s!r}"
            )
        if not (-1.0 <= self.correlation <= 1.0):
            raise ValueError(
                f"a normalized correlation must lie in [-1, 1]: {self.correlation!r}"
            )
        if not self.reason.strip():
            raise ValueError("every peak states what it is")
        return self


class PeriodClaim(ValueModel):
    """What, if anything, the window's recurrence peaks say about a period.

    A claim needs an admissible peak (not weak, preceded by the autocorrelation
    falling below the weak threshold), a lag at least
    :data:`MIN_PEAK_LAG_STEPS` lag steps above the resolution, and at least
    ``min_candidate_cycles`` whole candidate cycles of that lag inside the
    window. The reason names the first condition that failed, with its
    threshold, so a refusal is as inspectable as a claim. ``period_s`` exists
    only for a supported claim; the peak's lag, its correlation and the
    resolution are reported either way, as the evidence for the verdict.
    """

    supported: bool
    reason: str
    peak_lag_s: float | None
    peak_correlation: float | None
    period_s: float | None
    period_resolution_s: float
    candidate_cycles_in_window: float | None
    weak_peak_correlation: float
    min_candidate_cycles: float
    min_peak_lag_steps: int

    @model_validator(mode="after")
    def _check(self) -> PeriodClaim:
        if self.supported != (self.period_s is not None):
            raise ValueError(
                "a period exists exactly when the claim is supported "
                f"(supported={self.supported!r}, period_s={self.period_s!r})"
            )
        if self.period_s is not None:
            if self.peak_lag_s is None or self.peak_correlation is None:
                raise ValueError("a supported claim names the peak it rests on")
            if not math.isclose(self.period_s, self.peak_lag_s, rel_tol=1e-12):
                raise ValueError("the claimed period is the recovered lag")
        if self.peak_lag_s is None and (
            self.peak_correlation is not None
            or self.candidate_cycles_in_window is not None
        ):
            raise ValueError("a claim without a peak carries no peak evidence")
        if self.supported and not self.reason.strip():
            raise ValueError("a supported claim states the thresholds it cleared")
        if not self.reason.strip():
            raise ValueError("a refused claim names what refused it")
        return self


class TraceRecurrence(ArrayModel):
    """One gate's normalized autocorrelation, with its provenance and its refusals.

    Every field is either measured or a named method setting; nothing is a
    default that the caller did not state. The view, the window's own
    timestamps, the detrending and the thresholds travel with the curve, so a
    later reader (or reviewer) can reproduce the estimate from the result alone.
    No field is an uncertainty estimated over profiles or gates: they are
    correlated samples, so a pseudoreplicate interval does not exist here.
    """

    # who and where this trace is
    view: RecurrenceView
    label: str
    relative_path: str
    gate_index: int
    depth_mm: float
    quantity: str
    unit: str

    # the window the trace was cut to, in the recording's own stamps
    window_start_s: float
    window_end_s: float
    window_duration_s: float
    profile_count: int

    # what the stored timestamps resolve
    sample_interval_s: float
    lag_resolution_s: float
    frequency_resolution_hz: float
    max_lag_s: float
    max_relative_interval_deviation: float

    # what was done to the trace, and with which thresholds
    detrending: Detrending
    acf_estimator: str
    weak_peak_correlation: float
    min_candidate_cycles: float
    min_peak_lag_steps: int
    constant_trace_threshold_mm_s: float

    # the verdict, and the curve only when it is defined
    verdict: RecurrenceVerdict
    message: str
    lag_s: array_field(np.float64, rank=1)
    acf: array_field(np.float64, rank=1)
    raw_trace: array_field(np.float64, rank=1)
    detrended_trace: array_field(np.float64, rank=1)

    # descriptive trace statistics of the analysed series
    trace_mean_mm_s: float
    trace_std_mm_s: float
    trace_zero_fraction: float
    linear_trend_mm_s_per_s: float | None

    # the descriptive quantities, each with its own support verdict
    first_zero_crossing: SupportedQuantity
    decay_1e_lag: SupportedQuantity
    integral_time: SupportedQuantity
    recurrence_peaks: tuple[RecurrencePeak, ...]
    peaks_reason: str
    period_claim: PeriodClaim

    @model_validator(mode="after")
    def _curve_matches_the_verdict(self) -> TraceRecurrence:
        if self.verdict is RecurrenceVerdict.DEFINED:
            if self.acf.size != self.lag_s.size or self.acf.size < 2:
                raise ValueError(
                    "a defined autocorrelation carries one value per lag, "
                    f"got {self.acf.size} and {self.lag_s.size}"
                )
            if abs(float(self.acf[0]) - 1.0) > 1e-9:
                raise ValueError(
                    "a defined normalized autocorrelation starts at 1, got "
                    f"{float(self.acf[0])!r}"
                )
            if self.detrended_trace.size != self.raw_trace.size:
                raise ValueError(
                    "the analysed and the raw trace are the same series, "
                    f"got {self.detrended_trace.size} and {self.raw_trace.size}"
                )
        elif self.acf.size or self.lag_s.size or self.detrended_trace.size:
            raise ValueError(
                f"the {self.verdict.value!r} verdict carries no correlation curve"
            )
        if (self.linear_trend_mm_s_per_s is not None) != (
            self.detrending is Detrending.MEAN_AND_LINEAR
        ):
            raise ValueError(
                "a linear trend is reported exactly when linear detrending ran, "
                f"got {self.linear_trend_mm_s_per_s!r} with {self.detrending.value!r}"
            )
        if self.period_claim.peak_lag_s is not None and (
            self.period_claim.period_resolution_s != self.lag_resolution_s
        ):
            raise ValueError(
                "a claim is resolved by the lag grid it was measured on, got "
                f"{self.period_claim.period_resolution_s!r} and "
                f"{self.lag_resolution_s!r}"
            )
        return self


def _as_enum(kind: type, value: object, name: str) -> object:
    """The enum member for ``value``, or a refusal naming the allowed members."""
    if isinstance(value, kind):
        return value
    try:
        return kind(value)
    except ValueError as exc:
        allowed = ", ".join(repr(member.value) for member in kind)
        raise RecurrenceError(
            f"unknown {name} {value!r}; the accepted values are {allowed}"
        ) from exc


def _max_relative_interval_deviation(time_s: np.ndarray) -> float:
    """Largest relative deviation of a stored interval from the median interval.

    Reported, not guarded: refusing or resampling a structurally sampled axis is
    SA2's slice, and this step never re-grids the stamps.
    """
    intervals = np.diff(time_s)
    median = float(np.median(intervals))
    if median <= 0.0:
        return 0.0
    return float(np.max(np.abs(intervals - median)) / median)


def _detrended(
    trace: np.ndarray, time_s: np.ndarray, detrending: Detrending
) -> tuple[np.ndarray, float | None]:
    """The analysed series, and the fitted slope when a line was removed.

    ``MEAN_AND_LINEAR`` fits the line to the mean-removed trace, so the analysed
    series keeps a zero mean and the reported slope is the trend that was
    removed from the signal rather than an intercept artefact.
    """
    if detrending is Detrending.NONE:
        return trace.copy(), None
    centered = trace - float(np.mean(trace))
    if detrending is Detrending.MEAN:
        return centered, None
    slope = float(np.polyfit(time_s, centered, 1)[0])
    return centered - slope * (time_s - float(np.mean(time_s))), slope


def _autocorrelation(values: np.ndarray, max_lag: int) -> np.ndarray:
    """The biased divide-by-N autocorrelation of ``values``, normalized to 1 at lag 0."""
    count = int(values.size)
    denominator = float(np.dot(values, values))
    return np.array(
        [
            float(np.dot(values[: count - lag], values[lag:])) / denominator
            for lag in range(max_lag + 1)
        ]
    )


def _interpolated_lag(acf: np.ndarray, dt_s: float, index: int, target: float) -> float:
    """The lag where the curve crosses ``target``, linearly between two lags."""
    before = float(acf[index - 1])
    after = float(acf[index])
    span = before - after
    fraction = 0.0 if span <= 0.0 else (before - target) / span
    return float(index - 1 + fraction) * dt_s


def _first_crossing_index(acf: np.ndarray) -> int | None:
    """The first lag index with a non-positive correlation, or ``None``."""
    for index in range(1, int(acf.size)):
        if acf[index] <= 0.0:
            return index
    return None


def _zero_crossing_quantity(
    acf: np.ndarray, dt_s: float, index: int | None
) -> SupportedQuantity:
    """The first zero crossing, or the reason the window does not reach one."""
    last_lag = float(acf.size - 1) * dt_s
    if index is None:
        return SupportedQuantity(
            value=None,
            unit="s",
            supported=False,
            reason=(
                f"the normalized autocorrelation is still {float(acf[-1])!r} at the "
                f"last lag {last_lag!r} s: the window does not reach a zero crossing"
            ),
        )
    return SupportedQuantity(
        value=_interpolated_lag(acf, dt_s, index, 0.0),
        unit="s",
        supported=True,
        reason=(
            f"the normalized autocorrelation crosses zero between lags "
            f"{(index - 1) * dt_s!r} s and {index * dt_s!r} s on the {dt_s!r} s "
            "lag grid, interpolated between them"
        ),
    )


def _decay_quantity(acf: np.ndarray, dt_s: float) -> SupportedQuantity:
    """The lag at which the normalized autocorrelation has fallen to 1/e."""
    for index in range(1, int(acf.size)):
        if acf[index] <= INVERSE_E:
            return SupportedQuantity(
                value=_interpolated_lag(acf, dt_s, index, INVERSE_E),
                unit="s",
                supported=True,
                reason=(
                    f"the normalized autocorrelation falls to 1/e = {INVERSE_E!r} "
                    f"between lags {(index - 1) * dt_s!r} s and {index * dt_s!r} s, "
                    "interpolated between them"
                ),
            )
    last_lag = float(acf.size - 1) * dt_s
    return SupportedQuantity(
        value=None,
        unit="s",
        supported=False,
        reason=(
            f"the lag range ends at {last_lag!r} s with correlation "
            f"{float(acf[-1])!r} above 1/e = {INVERSE_E!r}: the window does not "
            "reach the decay lag"
        ),
    )


def _integral_time_quantity(
    acf: np.ndarray,
    dt_s: float,
    index: int | None,
    peaks: tuple[RecurrencePeak, ...],
    weak_peak_correlation: float,
) -> SupportedQuantity:
    """The autocorrelation integral to the first zero crossing, when it means one.

    An integral time is the sum of the normalized autocorrelation from lag 0 to
    its first zero crossing, times the lag step. It is a *decay* summary, so a
    trace that recurs above the weak-peak threshold is refused it: the sum of an
    oscillating curve's quarter cycle is a small impressive-looking number, not
    a correlation time.
    """
    recurring = [peak for peak in peaks if not peak.weak]
    if recurring:
        return SupportedQuantity(
            value=None,
            unit="s",
            supported=False,
            reason=(
                f"the trace recurs at {recurring[0].lag_s!r} s with correlation "
                f"{recurring[0].correlation!r} at or above the weak-peak threshold "
                f"{weak_peak_correlation!r}: an integral time assumes a decaying "
                "autocorrelation, so the truncated sum is not reported as one"
            ),
        )
    if index is None:
        return SupportedQuantity(
            value=None,
            unit="s",
            supported=False,
            reason=(
                "the window never reaches a zero crossing, so the integral has no "
                "upper limit to truncate it at: no integral time is reported"
            ),
        )
    total = float(np.sum(acf[: index + 1]) * dt_s)
    return SupportedQuantity(
        value=total,
        unit="s",
        supported=True,
        reason=(
            f"the sum of the normalized autocorrelation over lags 0 … "
            f"{index * dt_s!r} s (the first zero crossing) times the {dt_s!r} s "
            "lag step"
        ),
    )


def _recurrence_peaks(
    acf: np.ndarray, lags: np.ndarray, weak_peak_correlation: float
) -> tuple[tuple[RecurrencePeak, ...], str]:
    """Every descriptive local maximum of the curve, with what each one is.

    Lag 0 is excluded (``acf[0] = 1`` is not a recurrence), so are the curve's
    last lag (no right-hand neighbour) and every non-positive maximum. A peak is
    *weak* below the named threshold, and a *shoulder* when the autocorrelation
    never fell below that threshold before it — a shoulder is not a recurrence,
    however high it is.
    """
    found: list[RecurrencePeak] = []
    for index in range(1, int(acf.size) - 1):
        value = float(acf[index])
        if value <= 0.0:
            continue
        if not (value > float(acf[index - 1]) and value >= float(acf[index + 1])):
            continue
        dipped = bool(np.min(acf[1 : index + 1]) < weak_peak_correlation)
        weak = bool(value < weak_peak_correlation)
        if weak:
            reason = (
                f"descriptive only: correlation {value!r} is below the weak-peak "
                f"threshold {weak_peak_correlation!r}, so this maximum supports no "
                "period claim"
            )
        elif dipped:
            reason = (
                f"a recurrence: the autocorrelation fell below the weak-peak "
                f"threshold {weak_peak_correlation!r} and returned to {value!r}"
            )
        else:
            reason = (
                f"a shoulder of the still-correlated curve, not a recurrence: the "
                f"autocorrelation never fell below the weak-peak threshold "
                f"{weak_peak_correlation!r} before it"
            )
        found.append(
            RecurrencePeak(
                lag_s=float(lags[index]),
                correlation=value,
                weak=weak,
                preceded_by_dip_below_weak_threshold=dipped,
                reason=reason,
            )
        )
    peaks = tuple(found)
    if peaks:
        summary = (
            f"{len(peaks)} local maximum(-a) above zero in the lag range "
            f"0 … {float(lags[-1])!r} s; each one's status is stated in its reason"
        )
    else:
        summary = (
            f"the normalized autocorrelation has no local maximum above zero in the "
            f"lag range 0 … {float(lags[-1])!r} s: no recurrence peak is reported"
        )
    return peaks, summary


def _period_claim(
    peaks: tuple[RecurrencePeak, ...],
    peaks_reason: str,
    *,
    window_duration_s: float,
    dt_s: float,
    weak_peak_correlation: float,
    min_candidate_cycles: float,
) -> PeriodClaim:
    """What the peaks say about a period, or the named threshold that refuses it."""
    admissible = [
        peak
        for peak in peaks
        if not peak.weak and peak.preceded_by_dip_below_weak_threshold
    ]
    common = {
        "period_resolution_s": dt_s,
        "weak_peak_correlation": weak_peak_correlation,
        "min_candidate_cycles": min_candidate_cycles,
        "min_peak_lag_steps": MIN_PEAK_LAG_STEPS,
    }
    if not admissible:
        if not peaks:
            reason = f"no recurrence peak to claim a period from: {peaks_reason}"
        elif all(peak.weak for peak in peaks):
            strongest = max(peak.correlation for peak in peaks)
            reason = (
                f"every recurrence peak is weak: the strongest is {strongest!r}, "
                f"below the weak-peak threshold {weak_peak_correlation!r}; no "
                "precise period is claimed from it"
            )
        else:
            reason = (
                "no peak is preceded by the autocorrelation falling below the "
                f"weak-peak threshold {weak_peak_correlation!r}: they are shoulders "
                "of the still-correlated curve, not recurrences"
            )
        return PeriodClaim(
            supported=False,
            reason=reason,
            peak_lag_s=None,
            peak_correlation=None,
            period_s=None,
            candidate_cycles_in_window=None,
            **common,
        )
    peak = admissible[0]
    cycles = window_duration_s / peak.lag_s
    evidence = {
        "peak_lag_s": peak.lag_s,
        "peak_correlation": peak.correlation,
        "candidate_cycles_in_window": cycles,
    }
    if peak.lag_s < MIN_PEAK_LAG_STEPS * dt_s:
        return PeriodClaim(
            supported=False,
            reason=(
                f"the peak's lag {peak.lag_s!r} s is within "
                f"{MIN_PEAK_LAG_STEPS} lag steps of the {dt_s!r} s resolution: a "
                "period cannot be read from it"
            ),
            period_s=None,
            **evidence,
            **common,
        )
    if cycles < min_candidate_cycles:
        return PeriodClaim(
            supported=False,
            reason=(
                f"the {window_duration_s!r} s window holds only {cycles!r} candidate "
                f"cycles of the {peak.lag_s!r} s lag, fewer than the "
                f"min_candidate_cycles threshold {min_candidate_cycles!r}: no precise "
                "period is claimed"
            ),
            period_s=None,
            **evidence,
            **common,
        )
    return PeriodClaim(
        supported=True,
        reason=(
            f"the first admissible recurrence peak sits at {peak.lag_s!r} s with "
            f"correlation {peak.correlation!r}, above the weak-peak threshold "
            f"{weak_peak_correlation!r}, and the window holds {cycles!r} whole "
            f"candidate cycles of it (>= {min_candidate_cycles!r}); the period is "
            f"resolved to one lag step, {dt_s!r} s"
        ),
        period_s=peak.lag_s,
        **evidence,
        **common,
    )


def trace_recurrence(
    trace: np.ndarray | Sequence[float],
    *,
    time_s: np.ndarray | Sequence[float],
    view: RecurrenceView | str,
    label: str,
    relative_path: str = "",
    gate_index: int = 0,
    depth_mm: float = 0.0,
    quantity: str = "axial_velocity",
    unit: str = "mm/s",
    detrending: Detrending | str = Detrending.MEAN,
    max_lag_s: float | None = None,
    weak_peak_correlation: float = WEAK_PEAK_CORRELATION,
    min_candidate_cycles: float = MIN_CANDIDATE_CYCLES,
) -> TraceRecurrence:
    """The normalized autocorrelation of one gate's velocity-versus-time trace.

    The trace mean is removed by default before normalizing; ``detrending`` names
    any further method and both traces travel in the result. The lag grid is the
    full-span effective interval ``(t[-1] - t[0]) / (N - 1)`` of the *stored*
    timestamps, and the default lag range is the first half of the window: a lag
    beyond half the trace has fewer than half the products behind it.

    Args:
        trace: the ``(profiles,)`` trace of one gate, in the caller's unit.
        time_s: the same length's stored timestamps, non-decreasing.
        view: which shared view the trace was cut to (:class:`RecurrenceView`).
        label: the recording's identity, so a result is never anonymous.
        relative_path: the source file, for provenance.
        gate_index: the gate's index on the recording's native grid.
        depth_mm: the gate's native depth, preserved as the instrument reports it.
        quantity: the measured quantity, ``axial_velocity`` by default.
        unit: the velocity unit, ``mm/s`` by default.
        detrending: ``mean`` (default), ``mean+linear`` or ``none``.
        max_lag_s: the lag range to report; defaults to half the window's span.
        weak_peak_correlation: the threshold a peak must clear to support a claim.
        min_candidate_cycles: whole candidate cycles of a lag a claim needs.

    Returns:
        :class:`TraceRecurrence` — the curve and its provenance when the trace
        has variance, or an explicit :class:`RecurrenceVerdict` when it does not.

    Raises:
        RecurrenceError: for a mismatched pair, a time axis that is not
            non-decreasing, an unknown view or detrending, an unnamed source, a
            threshold outside its range, or a lag range longer than the window.
    """
    chosen_view = _as_enum(RecurrenceView, view, "view")
    chosen_detrending = _as_enum(Detrending, detrending, "detrending")
    if not label.strip():
        raise RecurrenceError(
            "every result must name its source: pass a non-empty label (the plan "
            "requires the recording and view labels to be visible)"
        )
    if not 0.0 < weak_peak_correlation < 1.0:
        raise RecurrenceError(
            "weak_peak_correlation must lie strictly inside (0, 1), got "
            f"{weak_peak_correlation!r}"
        )
    if min_candidate_cycles < 1.0:
        raise RecurrenceError(
            f"min_candidate_cycles must be at least 1, got {min_candidate_cycles!r}"
        )

    raw = np.asarray(trace, dtype=np.float64)
    times = np.asarray(time_s, dtype=np.float64)
    if raw.ndim != 1:
        raise RecurrenceError(f"trace must be a 1-D series, got shape {raw.shape}")
    if times.ndim != 1:
        raise RecurrenceError(f"time_s must be a 1-D series, got shape {times.shape}")
    if raw.shape != times.shape:
        raise RecurrenceError(
            "trace and time_s must share one length, got "
            f"{raw.shape[0]} and {times.shape[0]}"
        )
    if raw.size >= 2 and not bool(np.all(np.diff(times) >= 0.0)):
        raise RecurrenceError(
            "time_s must be non-decreasing: a trace is a time series and the lag "
            "grid is its own timestamps"
        )

    count = int(raw.size)
    start_s = float(times[0]) if count else 0.0
    end_s = float(times[-1]) if count else 0.0
    duration_s = end_s - start_s
    dt_s = duration_s / (count - 1) if count >= 2 else 0.0
    if count >= 2 and dt_s <= 0.0:
        raise RecurrenceError(
            "the stored timestamps give no positive sample interval: the lag grid "
            "is undefined for this trace"
        )
    finite_raw = raw[np.isfinite(raw)]
    scale = float(np.max(np.abs(raw))) if count else 0.0
    threshold = max(CONSTANT_TRACE_ABSOLUTE_TOL, CONSTANT_TRACE_RELATIVE_TOL * scale)

    shared: dict[str, object] = {
        "view": chosen_view,
        "label": label,
        "relative_path": relative_path,
        "gate_index": gate_index,
        "depth_mm": depth_mm,
        "quantity": quantity,
        "unit": unit,
        "window_start_s": start_s,
        "window_end_s": end_s,
        "window_duration_s": duration_s,
        "profile_count": count,
        "sample_interval_s": dt_s,
        "lag_resolution_s": dt_s,
        "max_relative_interval_deviation": (
            _max_relative_interval_deviation(times) if count >= 2 else 0.0
        ),
        "detrending": chosen_detrending,
        "acf_estimator": ACF_ESTIMATOR,
        "weak_peak_correlation": weak_peak_correlation,
        "min_candidate_cycles": min_candidate_cycles,
        "min_peak_lag_steps": MIN_PEAK_LAG_STEPS,
        "constant_trace_threshold_mm_s": threshold,
        "raw_trace": raw,
        "trace_mean_mm_s": float(np.mean(finite_raw)) if finite_raw.size else 0.0,
        "trace_zero_fraction": (
            float(np.count_nonzero(raw == 0.0)) / count if count else 0.0
        ),
    }

    verdict: RecurrenceVerdict | None = None
    message = ""
    if count == 0:
        verdict = RecurrenceVerdict.UNDEFINED_NO_SAMPLES
        message = (
            "the trace holds no samples: a normalized autocorrelation is undefined "
            "and no curve is returned"
        )
    elif finite_raw.size != count:
        verdict = RecurrenceVerdict.UNDEFINED_NON_FINITE
        message = (
            f"the trace holds {count - finite_raw.size} non-finite sample(s): a "
            "normalized autocorrelation is undefined and no curve is returned"
        )
    elif count < MIN_SAMPLES_FOR_ACF:
        verdict = RecurrenceVerdict.UNDEFINED_TOO_FEW_SAMPLES
        message = (
            f"the trace holds {count} samples, fewer than the {MIN_SAMPLES_FOR_ACF} "
            "a normalized autocorrelation needs: undefined, and no curve is returned"
        )

    analysed: np.ndarray | None = None
    trend: float | None = None
    if verdict is None:
        analysed, trend = _detrended(raw, times, chosen_detrending)
        spread = float(np.std(analysed))
        if spread <= threshold:
            verdict = RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE
            message = (
                f"the trace is constant to within its own scale: the standard "
                f"deviation of the {chosen_detrending.value!r}-detrended trace is "
                f"{spread!r}, at or below the threshold "
                f"{threshold!r} = max({CONSTANT_TRACE_ABSOLUTE_TOL!r}, "
                f"{CONSTANT_TRACE_RELATIVE_TOL!r} x max|trace| {scale!r}); a "
                "normalized autocorrelation is undefined here, and an all-zero "
                "curve would be a silently substituted value"
            )

    if verdict is not None:
        refused = SupportedQuantity(
            value=None, unit="s", supported=False, reason=message
        )
        return TraceRecurrence(
            **shared,
            verdict=verdict,
            message=message,
            frequency_resolution_hz=(1.0 / duration_s if duration_s > 0.0 else 0.0),
            trace_std_mm_s=0.0,
            linear_trend_mm_s_per_s=None,
            max_lag_s=0.0,
            lag_s=np.empty(0, dtype=np.float64),
            acf=np.empty(0, dtype=np.float64),
            detrended_trace=np.empty(0, dtype=np.float64),
            first_zero_crossing=refused,
            decay_1e_lag=refused,
            integral_time=refused,
            recurrence_peaks=(),
            peaks_reason=message,
            period_claim=PeriodClaim(
                supported=False,
                reason=message,
                peak_lag_s=None,
                peak_correlation=None,
                period_s=None,
                period_resolution_s=dt_s,
                candidate_cycles_in_window=None,
                weak_peak_correlation=weak_peak_correlation,
                min_candidate_cycles=min_candidate_cycles,
                min_peak_lag_steps=MIN_PEAK_LAG_STEPS,
            ),
        )

    assert analysed is not None  # the verdict above is the only way past this point
    lag_profiles = count // 2 if max_lag_s is None else round(max_lag_s / dt_s)
    if lag_profiles < 1:
        raise RecurrenceError(
            f"max_lag_s {max_lag_s!r} is shorter than one lag step {dt_s!r}"
        )
    if lag_profiles > count - 1:
        raise RecurrenceError(
            f"max_lag_s {max_lag_s!r} is longer than the window's own span "
            f"{duration_s!r} s: a lag beyond the trace has no products behind it"
        )
    acf = _autocorrelation(analysed, lag_profiles)
    lags = np.arange(lag_profiles + 1) * dt_s
    crossing_index = _first_crossing_index(acf)
    peaks, peaks_reason = _recurrence_peaks(acf, lags, weak_peak_correlation)
    return TraceRecurrence(
        **shared,
        verdict=RecurrenceVerdict.DEFINED,
        message=(
            f"normalized autocorrelation of {count} profiles over {duration_s!r} s, "
            f"detrending {chosen_detrending.value!r}, lag resolution {dt_s!r} s "
            f"(frequency resolution {1.0 / duration_s!r} Hz); a period is claimed "
            "only from a peak above the weak-peak threshold with enough whole "
            "candidate cycles, see period_claim"
        ),
        lag_s=lags,
        acf=acf,
        detrended_trace=analysed,
        trace_std_mm_s=float(np.std(analysed)),
        linear_trend_mm_s_per_s=trend,
        max_lag_s=float(lags[-1]),
        frequency_resolution_hz=1.0 / duration_s,
        first_zero_crossing=_zero_crossing_quantity(acf, dt_s, crossing_index),
        decay_1e_lag=_decay_quantity(acf, dt_s),
        integral_time=_integral_time_quantity(
            acf, dt_s, crossing_index, peaks, weak_peak_correlation
        ),
        recurrence_peaks=peaks,
        peaks_reason=peaks_reason,
        period_claim=_period_claim(
            peaks,
            peaks_reason,
            window_duration_s=duration_s,
            dt_s=dt_s,
            weak_peak_correlation=weak_peak_correlation,
            min_candidate_cycles=min_candidate_cycles,
        ),
    )


def gate_recurrence(
    point: DecodedPoint,
    *,
    gate_index: int,
    view: RecurrenceView | str,
    window_s: float | None = None,
    support_mm: tuple[float, float] | None = None,
    detrending: Detrending | str = Detrending.MEAN,
    max_lag_s: float | None = None,
    weak_peak_correlation: float = WEAK_PEAK_CORRELATION,
    min_candidate_cycles: float = MIN_CANDIDATE_CYCLES,
) -> TraceRecurrence:
    """One gate of a decoded recording, through the pass's own windows.

    ``point`` is a decoded view — anything carrying ``values`` ``(profiles,
    gates)``, ``time_s``, ``depths``, ``relative_path`` and
    ``binding.point.label``, as :func:`decode_pass` returns them.

    The window is the caller's, never inferred and never widened:

    - :data:`RecurrenceView.PRIMARY` requires ``window_s`` — the pass's designed
      0-12 s exposure — cut from the recording's own stored timestamps by the
      shared ``window`` helper. A recording whose stamps cover less is
      **refused**, not narrowed.
    - :data:`RecurrenceView.FULL_RECORD` takes every valid stored profile and
      refuses a ``window_s``: it is labelled separately from the primary view.
    - :data:`RecurrenceView.EXPLORATION` takes the caller's explicit leading
      window and keeps its own label, so it cannot silently replace the primary
      comparison.

    Args:
        point: the decoded view to read.
        gate_index: the gate's index on the recording's native grid.
        view: which shared view is being asked for.
        window_s: the window in seconds; required except for the full record.
        support_mm: optional ``(min_mm, max_mm)`` common physical support, which
            the gate must lie inside.
        detrending: passed through to :func:`trace_recurrence`.
        max_lag_s: passed through to :func:`trace_recurrence`.
        weak_peak_correlation: passed through to :func:`trace_recurrence`.
        min_candidate_cycles: passed through to :func:`trace_recurrence`.

    Returns:
        The gate's :class:`TraceRecurrence`, with the native depth preserved.

    Raises:
        RecurrenceError: for a gate outside the native grid or the support, a
            view asked for without its window (or with one it does not take), or
            a window the recording's stamps do not cover.
    """
    chosen_view = _as_enum(RecurrenceView, view, "view")
    values = np.asarray(point.values, dtype=np.float64)
    times = np.asarray(point.time_s, dtype=np.float64)
    depths = np.asarray(point.depths, dtype=np.float64)
    if values.ndim != 2:
        raise RecurrenceError(
            f"{point.relative_path}: expected a (profiles, gates) view, got shape "
            f"{values.shape}"
        )
    profile_count, gate_count = values.shape
    if depths.size != gate_count:
        raise RecurrenceError(
            f"{point.relative_path}: {depths.size} gate depths describe {gate_count} "
            "columns of the view; the native grid cannot be preserved"
        )
    if times.size != profile_count:
        raise RecurrenceError(
            f"{point.relative_path}: {times.size} timestamps describe {profile_count} "
            "profiles"
        )
    if not 0 <= gate_index < gate_count:
        raise RecurrenceError(
            f"{point.relative_path}: gate {gate_index} is outside the recording's "
            f"native gates 0 … {gate_count - 1}"
        )
    if support_mm is not None and not bool(in_support(depths, support_mm)[gate_index]):
        raise RecurrenceError(
            f"{point.relative_path}: gate {gate_index} at {float(depths[gate_index])!r} "
            f"mm lies outside the common physical support {support_mm!r} mm; a "
            "depth-resolved comparison may not use it"
        )

    if chosen_view is RecurrenceView.FULL_RECORD:
        if window_s is not None:
            raise RecurrenceError(
                "the full record view is not a window: pass window_s=None so the "
                "two views stay distinguishable"
            )
        cut = times
    else:
        if window_s is None:
            raise RecurrenceError(
                f"the {chosen_view.value!r} view needs its own window_s: the window "
                "is the caller's decision, never inferred"
            )
        span_s = float(times[-1] - times[0]) if times.size else 0.0
        if span_s < float(window_s) - TOLERANCE_S:
            raise RecurrenceError(
                f"{point.relative_path}: the stored timestamps span {span_s!r} s of "
                f"the {float(window_s)!r} s {chosen_view.value!r} window; "
                "insufficient coverage is refused, never widened to the retained "
                "surplus"
            )
        # The coverage test is the recording's own span, not the cut's: the shared
        # cut keeps only the stamps at or before the window's end, so its own last
        # stamp sits legitimately just short of the boundary.
        cut = window(times, times, float(window_s))
        if cut.size < 2:
            raise RecurrenceError(
                f"{point.relative_path}: only {cut.size} profile(s) fall inside the "
                f"{float(window_s)!r} s {chosen_view.value!r} window; a "
                "correlation needs at least two"
            )
    count = int(cut.size)
    return trace_recurrence(
        values[:count, gate_index],
        time_s=cut,
        view=chosen_view,
        label=str(point.binding.point.label),
        relative_path=str(point.relative_path),
        gate_index=int(gate_index),
        depth_mm=float(depths[gate_index]),
        detrending=detrending,
        max_lag_s=max_lag_s,
        weak_peak_correlation=weak_peak_correlation,
        min_candidate_cycles=min_candidate_cycles,
    )


__all__ = [
    "ACF_ESTIMATOR",
    "CONSTANT_TRACE_ABSOLUTE_TOL",
    "CONSTANT_TRACE_RELATIVE_TOL",
    "MIN_CANDIDATE_CYCLES",
    "MIN_PEAK_LAG_STEPS",
    "MIN_SAMPLES_FOR_ACF",
    "WEAK_PEAK_CORRELATION",
    "Detrending",
    "PeriodClaim",
    "RecurrenceError",
    "RecurrencePeak",
    "RecurrenceVerdict",
    "RecurrenceView",
    "SupportedQuantity",
    "TraceRecurrence",
    "gate_recurrence",
    "trace_recurrence",
]
