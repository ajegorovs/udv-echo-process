"""Normalized temporal autocorrelation of one gate's trace (plan SA1).

The sparse plan's *temporal recurrence* paragraph, implemented once as plain
functions so a notebook can only select inputs and display results ("Notebooks
select inputs and display those results; they do not implement estimators").

What is measured
----------------
One gate's trace is a velocity-versus-time series (one signed line-of-sight
component at one native gate depth). :func:`recurrence_of_view` subtracts the
trace mean **by default** and returns the normalized autocorrelation of the
remainder — the *biased*, divide-by-N autocovariance scaled so ``acf[0] == 1``,
the same estimator name the sibling temporal work uses. Additional detrending is
optional (:class:`Detrending`), is named in the result, and always arrives with
both the analysed and the **raw** trace, so a reader can see what was removed.

The trace is not handed in beside a separately-named view: the one entry point
takes a :class:`~udv_echo_process.analysis._sparse_view.WindowView` and correlates
its own column, so the cut that selects the samples and the cut that labels them
are the same cut, and the result carries that view's own provenance rather than a
parallel description of it.

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
- **A timebase verdict, not an unqualified lag axis.** The lag grid is the
  *full-span effective* interval of the stored stamps, with the same reasoning the
  echo-RPM step documents (a quantized DOP timebase makes the median interval the
  dominant timestamp quantum rather than the period), so ``lag k`` is ``k *
  ((t[-1] - t[0]) / (N - 1))`` and is the elapsed time of lag ``k`` only when the
  stamps are themselves near-uniform. Every result therefore carries the timebase it
  saw - :class:`TimebaseVerdict`, the maximum relative deviation from the median
  interval, and :data:`LAG_GRID_RULE` - and a timebase outside the regular band makes
  every *lag-based* claim unsupported with that verdict as its reason, while the curve
  itself stays descriptive. This replaces the old diagnostic, which returned ``0.0``
  when the median interval was not positive and so scored the most degenerate axis
  possible as perfectly regular. Declaring a jitter or gap threshold for *spectral*
  methods, and documenting or refusing resampling before them, is SA2's slice: this
  module never silently re-grids a structurally sampled axis.
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

from udv_echo_process.analysis._sparse_view import (
    SparseView,
    ViewProvenance,
    WindowView,
    view_provenance,
)
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

#: The largest relative deviation of an interval from the median interval that still counts as
#: a regular axis, i.e. the widest a lag in seconds may be trusted. Measured basis: all 52
#: committed sparse recordings sit in 1.1e-3 .. 6.6e-3 (the stamps are quantized, not
#: jittered), so this is three times the worst committed recording and roughly twenty times
#: below a structurally jittered axis. The band is chosen to separate those two, not to make
#: the committed data pass.
TIMEBASE_REGULARITY_TOL = 2e-2

#: The uniform-grid assumption behind every lag this module reports, stated once so a consumer
#: - SA2 in particular - inherits it consciously rather than by default.
LAG_GRID_RULE = (
    "Integer lag indices on one effective interval: lag k is k * ((t[-1] - t[0]) / (N - 1)), "
    "the full-span effective interval of the stored stamps, as the echo-RPM step documents (a "
    "quantized DOP timebase makes the median interval the dominant timestamp quantum rather "
    "than the period). The autocorrelation is uniformly sampled by construction, so its lag "
    "axis is elapsed time only where the timebase verdict is regular; elsewhere the curve "
    "stays descriptive and no lag in seconds is claimed from it."
)

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


class TimebaseVerdict(str, Enum):
    """Whether the stored timestamps support a lag axis in seconds, and if not, why.

    The autocorrelation marches integer lag indices on one effective interval, so reading
    its lag axis in seconds is an *assumption about the stamps*. This verdict is that
    assumption's explicit answer: ``REGULAR`` when the stamps are strictly increasing and
    near-uniform within :data:`TIMEBASE_REGULARITY_TOL`, and otherwise the named way they
    are not. Every non-regular verdict makes each lag-based claim (first zero crossing,
    1/e decay lag, integral time, period) unsupported with this verdict as its reason,
    while the curve itself stays descriptive.

    The regression this vocabulary exists to prevent: the deviation diagnostic returned
    ``0.0`` when the median interval was not positive, so the most degenerate axis
    possible scored as *perfectly regular*.
    """

    #: Strictly increasing and near-uniform: a lag in seconds is claimed.
    REGULAR = "regular"
    #: Strictly increasing, but the intervals deviate past the regular band.
    IRREGULAR = "irregular"
    #: An interval is zero - two profiles share a stamp, so no elapsed time separates them.
    DUPLICATE_STAMPS = "duplicate-stamps"
    #: Not enough samples for an interval, or no positive interval at all.
    UNDEFINED_TIMEBASE = "undefined-timebase"


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

    Every field is either measured or a named method setting; nothing is a default that the
    caller did not state. The provenance is the *view's own*
    (:class:`~udv_echo_process.analysis._sparse_view.ViewProvenance`, the same one the
    per-gate statistics carry), so this result cannot describe a trace it did not take: the
    source digest, the job, the point, the order, the view, the view rule, the window and the
    three depth extents all come from the one cut, and the reading shortcuts a reader expects
    (:attr:`view`, :attr:`relative_path`, :attr:`label`, :attr:`window_duration_s`,
    :attr:`profile_count`) are properties of it rather than a second copy that can drift. The
    detrending and the thresholds travel with the curve too, so a later reader can reproduce
    the estimate from the result alone. No field is an uncertainty estimated over profiles or
    gates: they are correlated samples, so a pseudoreplicate interval does not exist here.
    """

    # where this trace is: the view it was cut from, and which gate of that view
    provenance: ViewProvenance
    gate_index: int
    depth_mm: float
    quantity: str
    unit: str

    # what the stored timestamps resolve, and what they were declared to be
    sample_interval_s: float
    lag_resolution_s: float
    frequency_resolution_hz: float
    max_lag_s: float
    requested_max_lag_s: float | None
    max_relative_interval_deviation: float | None
    timebase: TimebaseVerdict
    timebase_reason: str
    lag_grid_rule: str

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

    # Descriptive trace statistics. Two different series, deliberately: ``trace_mean_mm_s``
    # summarizes the trace *as stored*, so a reader can see the offset a mean removal took
    # out, while ``trace_std_mm_s`` summarizes the *analysed* series, which is the spread the
    # normalized autocorrelation is actually built on. Both are ``None`` when no finite
    # sample was there to summarize them - 0.0 would be read as a measured zero, and a
    # substituted value is exactly what a refusal must not publish.
    trace_mean_mm_s: float | None
    trace_std_mm_s: float | None
    trace_zero_fraction: float
    linear_trend_mm_s_per_s: float | None

    # the descriptive quantities, each with its own support verdict
    first_zero_crossing: SupportedQuantity
    decay_1e_lag: SupportedQuantity
    integral_time: SupportedQuantity
    recurrence_peaks: tuple[RecurrencePeak, ...]
    peaks_reason: str
    period_claim: PeriodClaim

    @property
    def view(self) -> SparseView:
        """The view label this trace was cut from, from its one provenance."""
        return self.provenance.view

    @property
    def relative_path(self) -> str:
        """The source recording, from its one provenance."""
        return self.provenance.relative_path

    @property
    def label(self) -> str:
        """The recording's identity string, from its one provenance."""
        return self.provenance.point_label

    @property
    def window_start_s(self) -> float:
        """The first stored stamp of the cut, from its one provenance."""
        return self.provenance.window_start_s

    @property
    def window_end_s(self) -> float:
        """The last stored stamp of the cut, from its one provenance."""
        return self.provenance.window_end_s

    @property
    def window_duration_s(self) -> float:
        """The span of the cut, from its one provenance."""
        return self.provenance.window_s

    @property
    def profile_count(self) -> int:
        """How many stored profiles the cut holds, from its one provenance."""
        return self.provenance.profiles

    @property
    def lag_claims_supported(self) -> bool:
        """Whether a lag in seconds may be claimed at all from this run's timebase."""
        return self.timebase is TimebaseVerdict.REGULAR

    @model_validator(mode="after")
    def _curve_matches_the_verdict(self) -> TraceRecurrence:
        """Hold the success invariants of a curve and the refusal invariants of a refusal.

        A refusal is a legitimate result, so an invariant that only has meaning once a curve
        exists must not be asserted of one. That was this model's defect: the equivalence "a
        linear trend is reported exactly when linear detrending ran" was checked against every
        verdict, so every refusal under :data:`Detrending.MEAN_AND_LINEAR` raised a
        ``ValidationError`` instead of returning the documented verdict - the refusal path
        unreachable for that detrending, and the error not even this module's own type.
        """
        if self.verdict is RecurrenceVerdict.DEFINED:
            if self.acf.size != self.lag_s.size or self.acf.size < 2:
                raise ValueError(
                    "a defined autocorrelation carries one value per lag, "
                    f"got {self.acf.size} and {self.lag_s.size}"
                )
            if not math.isfinite(float(self.acf[0])) or abs(float(self.acf[0]) - 1.0) > 1e-9:
                raise ValueError(
                    "a defined normalized autocorrelation starts at 1, got "
                    f"{float(self.acf[0])!r}"
                )
            if self.detrended_trace.size != self.raw_trace.size:
                raise ValueError(
                    "the analysed and the raw trace are the same series, "
                    f"got {self.detrended_trace.size} and {self.raw_trace.size}"
                )
            if (self.linear_trend_mm_s_per_s is not None) != (
                self.detrending is Detrending.MEAN_AND_LINEAR
            ):
                raise ValueError(
                    "a defined correlation under linear detrending reports the slope it "
                    f"removed, got {self.linear_trend_mm_s_per_s!r} with "
                    f"{self.detrending.value!r}"
                )
        else:
            if self.acf.size or self.lag_s.size or self.detrended_trace.size:
                raise ValueError(
                    f"the {self.verdict.value!r} verdict carries no correlation curve"
                )
            if self.linear_trend_mm_s_per_s is not None and (
                self.detrending is not Detrending.MEAN_AND_LINEAR
            ):
                raise ValueError(
                    "a slope belongs to a trace that linear detrending actually ran on, got "
                    f"{self.linear_trend_mm_s_per_s!r} with {self.detrending.value!r}"
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


def classify_timebase(time_s: np.ndarray) -> tuple[TimebaseVerdict, str, float | None]:
    """Whether a stored time axis supports a lag in seconds, why not, and how far from uniform.

    The returned deviation is the largest relative deviation of a stored interval from the
    *median* interval, or ``None`` when the axis offers no positive interval to be regular
    about. It is deliberately never ``0.0`` for a degenerate axis: a non-positive median used
    to score the worst possible timebase as perfectly regular, which is the one answer a
    regularity diagnostic must never give, and a substituted zero would read as a measurement.

    The policy, one case per :class:`TimebaseVerdict` member:

    - no positive interval at all, or fewer than two stamps: ``UNDEFINED_TIMEBASE``;
    - any *zero* interval, i.e. two profiles sharing one stamp: ``DUPLICATE_STAMPS``;
    - intervals deviating from their median by more than :data:`TIMEBASE_REGULARITY_TOL`:
      ``IRREGULAR``;
    - otherwise ``REGULAR``.

    A *negative* interval is an axis running backwards, which the view refuses before any
    estimator sees it, so it has no case of its own here: if one arrives it is reported as
    ``UNDEFINED_TIMEBASE``. There is no verdict that says "ideal" of a broken axis.
    """
    stamps = np.asarray(time_s, dtype=float).reshape(-1)
    if stamps.size < 2:
        return (
            TimebaseVerdict.UNDEFINED_TIMEBASE,
            f"{stamps.size} stored stamp(s) define no interval to be regular about",
            None,
        )
    intervals = np.diff(stamps)
    if bool(np.any(intervals < 0.0)):
        return (
            TimebaseVerdict.UNDEFINED_TIMEBASE,
            "the stored stamps decrease somewhere, so no lag axis in seconds exists",
            None,
        )
    median = float(np.median(intervals))
    if median <= 0.0:
        return (
            TimebaseVerdict.UNDEFINED_TIMEBASE,
            "no stored interval is positive, so the axis holds no elapsed time to lag on",
            None,
        )
    deviation = float(np.max(np.abs(intervals - median)) / median)
    duplicate = int(np.count_nonzero(intervals == 0.0))
    if duplicate:
        return (
            TimebaseVerdict.DUPLICATE_STAMPS,
            (
                f"{duplicate} of {intervals.size} stored interval(s) are zero: two profiles "
                "sharing one stamp have no elapsed time between them, so a lag in seconds is "
                "not defined on this axis"
            ),
            deviation,
        )
    if not deviation <= TIMEBASE_REGULARITY_TOL:
        return (
            TimebaseVerdict.IRREGULAR,
            (
                f"the stored intervals deviate from their median by up to {deviation:.3e} "
                f"relative, past the {TIMEBASE_REGULARITY_TOL:.3e} regular band, so this "
                "autocorrelation's integer lag grid is not a uniform time axis"
            ),
            deviation,
        )
    return (
        TimebaseVerdict.REGULAR,
        (
            f"the stored intervals deviate from their median by no more than {deviation:.3e} "
            f"relative, inside the {TIMEBASE_REGULARITY_TOL:.3e} regular band"
        ),
        deviation,
    )


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


def recurrence_of_view(
    view: WindowView,
    *,
    depth_mm: float,
    quantity: str = "axial_velocity",
    unit: str = "mm/s",
    detrending: Detrending | str = Detrending.MEAN,
    max_lag_s: float | None = None,
    weak_peak_correlation: float = WEAK_PEAK_CORRELATION,
    min_candidate_cycles: float = MIN_CANDIDATE_CYCLES,
) -> TraceRecurrence:
    """The normalized autocorrelation of one gate's trace, cut from one shared view.

    This is the module's single entry point, and there is deliberately no other. A trace and
    its time axis are never handed in beside a separately-named view, so the cut that selects
    the samples and the cut that labels them cannot disagree - the defect this replaced was an
    entry point that took ``(trace, time_s, view, label, ...)`` and could be called with
    arrays from one window and a label from another, or with no identity at all. The trace is
    now the view's own column at ``depth_mm``, over the view's own stored stamps, and the
    result carries the view's own provenance, so a recurrence result cannot be anonymous about
    where it came from.

    Selecting and cutting the samples is the view's job, not this function's:
    :mod:`udv_echo_process.analysis._sparse_view` owns ``primary_view``,
    ``full_record_view`` and ``exploration_view``, and each labels its own cut with its own
    rule.

    Args:
        view: the view to cut the trace out of.
        depth_mm: the native gate depth to analyse, inside the view's common support.
        quantity: the measured quantity; ``axial_velocity`` for this sparse pass.
        unit: the velocity unit; ``mm/s`` for this sparse pass.
        detrending: ``mean`` (default), ``mean+linear`` or ``none``.
        max_lag_s: the lag range to report; defaults to half the window's span.
        weak_peak_correlation: the threshold a peak must clear to support a claim.
        min_candidate_cycles: whole candidate cycles of a lag a claim needs.

    Returns:
        :class:`TraceRecurrence` - the curve and its provenance when the trace has variance,
        or an explicit :class:`RecurrenceVerdict` when it does not. Either way the timebase
        verdict says whether any lag in seconds was claimed from it.

    Raises:
        SparseViewError: for a depth that is not one of the view's native gates.
        RecurrenceError: for a depth outside the view's common support, an unknown detrending,
            a threshold outside its range, or a lag range that is not a finite positive
            duration.
    """
    column = view.column_of_depth(depth_mm)
    depths = np.asarray(view.depths_mm, dtype=float)
    if not bool(np.asarray(view.support_mask)[column]):
        raise RecurrenceError(
            f"the gate at {depths[column]!r} mm is one of this view's native gates but lies "
            "outside the pass's common physical support, so its trace is not one that a "
            "depth-resolved recurrence may be read from"
        )
    return _recurrence_of_trace(
        np.asarray(view.values, dtype=float)[:, column],
        time_s=np.asarray(view.time_s, dtype=float),
        provenance=view_provenance(view),
        gate_index=column,
        depth_mm=float(depths[column]),
        quantity=quantity,
        unit=unit,
        detrending=_as_enum(Detrending, detrending, "detrending"),
        max_lag_s=max_lag_s,
        weak_peak_correlation=weak_peak_correlation,
        min_candidate_cycles=min_candidate_cycles,
    )


def _recurrence_of_trace(
    trace: np.ndarray | Sequence[float],
    *,
    time_s: np.ndarray | Sequence[float],
    provenance: ViewProvenance,
    gate_index: int,
    depth_mm: float,
    quantity: str,
    unit: str,
    detrending: Detrending,
    max_lag_s: float | None,
    weak_peak_correlation: float,
    min_candidate_cycles: float,
) -> TraceRecurrence:
    """The estimator behind :func:`recurrence_of_view`: one trace, one named provenance.

    Private because an anonymous call is what the public entry point exists to make
    impossible: this body will build a result for any two arrays of one length, and only
    :func:`recurrence_of_view` can supply the provenance that keeps that honest.
    """
    if not provenance.point_label.strip() or not provenance.source_sha256.strip():
        raise RecurrenceError(
            "a recurrence result must name its source: the view provenance carries no point "
            "label or no source digest"
        )
    if not quantity.strip() or not unit.strip():
        raise RecurrenceError("every result must name the quantity and unit it measured")
    if not 0.0 < weak_peak_correlation < 1.0:
        raise RecurrenceError(
            "weak_peak_correlation must lie strictly inside (0, 1), got "
            f"{weak_peak_correlation!r}"
        )
    if min_candidate_cycles < 1.0:
        raise RecurrenceError(
            f"min_candidate_cycles must be at least 1, got {min_candidate_cycles!r}"
        )
    if max_lag_s is not None and not (math.isfinite(max_lag_s) and max_lag_s > 0.0):
        raise RecurrenceError(
            f"max_lag_s must be a finite positive number of seconds, got {max_lag_s!r}: a lag "
            "range is a duration on the stored stamps, and neither NaN nor an infinity is "
            "shorter or longer than the window - it is not a duration at all"
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

    timebase, timebase_reason, deviation = classify_timebase(times)

    shared: dict[str, object] = {
        "provenance": provenance,
        "gate_index": gate_index,
        "depth_mm": depth_mm,
        "quantity": quantity,
        "unit": unit,
        "sample_interval_s": dt_s,
        "lag_resolution_s": dt_s,
        "requested_max_lag_s": max_lag_s,
        "max_relative_interval_deviation": deviation,
        "timebase": timebase,
        "timebase_reason": timebase_reason,
        "lag_grid_rule": LAG_GRID_RULE,
        "detrending": detrending,
        "acf_estimator": ACF_ESTIMATOR,
        "weak_peak_correlation": weak_peak_correlation,
        "min_candidate_cycles": min_candidate_cycles,
        "min_peak_lag_steps": MIN_PEAK_LAG_STEPS,
        "constant_trace_threshold_mm_s": threshold,
        "raw_trace": raw,
        "trace_mean_mm_s": float(np.mean(finite_raw)) if finite_raw.size else None,
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
        analysed, trend = _detrended(raw, times, detrending)
        spread = float(np.std(analysed))
        if spread <= threshold:
            verdict = RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE
            message = (
                f"the trace is constant to within its own scale: the standard "
                f"deviation of the {detrending.value!r}-detrended trace is "
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
        # What a refusal can still summarize honestly for the spread. With an analysed series
        # it is that series' spread - a constant trace's zero spread *is* the reason it was
        # refused, so 0.0 there is measured rather than substituted. Otherwise it is the
        # finite samples of the raw trace - a non-finite trace's spread over the samples that
        # do exist - and ``None`` where there was nothing finite to summarize at all.
        if analysed is not None:
            summarized_std: float | None = float(np.std(analysed))
        else:
            summarized_std = float(np.std(finite_raw)) if finite_raw.size >= 2 else None
        return TraceRecurrence(
            **shared,
            verdict=verdict,
            message=message,
            frequency_resolution_hz=(1.0 / duration_s if duration_s > 0.0 else 0.0),
            trace_std_mm_s=summarized_std,
            linear_trend_mm_s_per_s=trend,
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
    # A lag range is a whole number of lag steps. The index is floored rather than rounded:
    # rounding to nearest could report a lag *beyond* the range the caller asked for, and the
    # achieved range is recorded beside the requested one so the two cannot be confused.
    lag_profiles = count // 2 if max_lag_s is None else math.floor(max_lag_s / dt_s)
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

    # Every quantity below is a lag *in seconds*, and a lag in seconds only means seconds
    # where this run's timebase verdict says the stamps support one. On any other verdict the
    # curve is still descriptive, but each of these is refused with the timebase as its
    # reason rather than being reported in seconds off an axis that does not measure them.
    if timebase is TimebaseVerdict.REGULAR:
        first_zero_crossing = _zero_crossing_quantity(acf, dt_s, crossing_index)
        decay_1e_lag = _decay_quantity(acf, dt_s)
        integral_time = _integral_time_quantity(
            acf, dt_s, crossing_index, peaks, weak_peak_correlation
        )
        period_claim = _period_claim(
            peaks,
            peaks_reason,
            window_duration_s=duration_s,
            dt_s=dt_s,
            weak_peak_correlation=weak_peak_correlation,
            min_candidate_cycles=min_candidate_cycles,
        )
    else:
        unsupported = (
            f"this run's timebase is {timebase.value!r} ({timebase_reason}), so a lag in "
            "seconds is not defined on it: the integer lag grid of this autocorrelation is "
            "not a uniform time axis"
        )
        refused_lag = SupportedQuantity(
            value=None, unit="s", supported=False, reason=unsupported
        )
        first_zero_crossing = refused_lag
        decay_1e_lag = refused_lag
        integral_time = refused_lag
        peaks = ()
        peaks_reason = unsupported
        period_claim = PeriodClaim(
            supported=False,
            reason=unsupported,
            peak_lag_s=None,
            peak_correlation=None,
            period_s=None,
            period_resolution_s=dt_s,
            candidate_cycles_in_window=None,
            weak_peak_correlation=weak_peak_correlation,
            min_candidate_cycles=min_candidate_cycles,
            min_peak_lag_steps=MIN_PEAK_LAG_STEPS,
        )

    return TraceRecurrence(
        **shared,
        verdict=RecurrenceVerdict.DEFINED,
        message=(
            f"normalized autocorrelation of {count} profiles over {duration_s!r} s, "
            f"detrending {detrending.value!r}, lag resolution {dt_s!r} s "
            f"(frequency resolution {1.0 / duration_s!r} Hz), timebase {timebase.value!r}; "
            "a period is claimed only from a peak above the weak-peak threshold with enough "
            "whole candidate cycles, see period_claim"
        ),
        lag_s=lags,
        acf=acf,
        detrended_trace=analysed,
        trace_std_mm_s=float(np.std(analysed)),
        linear_trend_mm_s_per_s=trend,
        max_lag_s=float(lags[-1]),
        frequency_resolution_hz=1.0 / duration_s,
        first_zero_crossing=first_zero_crossing,
        decay_1e_lag=decay_1e_lag,
        integral_time=integral_time,
        recurrence_peaks=peaks,
        peaks_reason=peaks_reason,
        period_claim=period_claim,
    )


__all__ = [
    "ACF_ESTIMATOR",
    "CONSTANT_TRACE_ABSOLUTE_TOL",
    "CONSTANT_TRACE_RELATIVE_TOL",
    "LAG_GRID_RULE",
    "MIN_CANDIDATE_CYCLES",
    "MIN_PEAK_LAG_STEPS",
    "MIN_SAMPLES_FOR_ACF",
    "TIMEBASE_REGULARITY_TOL",
    "WEAK_PEAK_CORRELATION",
    "Detrending",
    "PeriodClaim",
    "RecurrenceError",
    "RecurrencePeak",
    "RecurrenceVerdict",
    "SupportedQuantity",
    "TimebaseVerdict",
    "TraceRecurrence",
    "recurrence_of_view",
]
