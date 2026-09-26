"""The spectral axis of one sparse view: its timebase, its rates and its frequency grid (``SA2``).

SA2 asks three questions in a fixed order, and this module answers the first one for a
recording: **what are this axis's own numbers?** The admission verdict that follows is
:mod:`udv_echo_process.analysis.sparse_spectral_admission`, and the target question after
that is :mod:`udv_echo_process.analysis.sparse_target_support`. Nothing here estimates a
spectrum: no FFT, no periodogram, no Welch, no resampling. It reads the view's stored
timestamps and publishes what the sampling grid *is*.

**One cut, one vocabulary.** The axis is the ``time_s`` of a
:class:`~udv_echo_process.analysis._sparse_view.WindowView`, so SA2 does not slice time or
depth independently of SA1 (plan ``SA2`` §"What this slice inherits from SA1"). The result
carries the shared :class:`~udv_echo_process.analysis._sparse_view.ViewProvenance`, which is
the authority for source identity and for the windows - this module adds no second
description of a view.

**Three intervals, and they are deliberately not the same number.** SA1's ``LAG_GRID_RULE``
already puts the effective lag step at ``(t[-1] - t[0]) / (N - 1)``, and SA2 adopts that same
full-span interval as its sampling interval. The median adjacent interval is reported beside
it as a **diagnostic**, because a quantized instrument clock makes the median interval the
dominant timestamp *quantum* rather than the period; it is never the sample rate. On the
committed recordings the two agree to ~1 part in 10^4, which is reassuring and is not a
licence to conflate them.

**The frequency resolution is not ``1 / span``.** With the adopted definitions

    span   = t[-1] - t[0]
    dt_eff = span / (N - 1)
    fs_eff = (N - 1) / span

an ``N``-point DFT has bin spacing

    delta_f = fs_eff / N = (N - 1) / (N * span)

which is **not** ``1 / span``. The two differ by exactly the factor ``(N - 1) / N`` - 1.3 part
in 10^3 on the committed primary views, which is far below any physical effect and far above
the tolerance at which this stage is willing to conflate definitions. Both quantities are
therefore published, under names that say which is which:
:attr:`TimebaseCharacterization.frequency_resolution_hz` is the *actual* DFT bin spacing,
and :attr:`~TimebaseCharacterization.duration_resolution_scale_hz` is the observation-duration
scale ``1 / span``, an approximate resolution scale that is never used as bin spacing. A
result that needs bin positions asks this module for them
(:func:`one_sided_frequency_grid`), so no caller re-derives ``delta_f`` and silently gets
``1 / span``.

**Undefined is not zero.** A view with one profile has no interval, no effective sample rate
and no Nyquist frequency; those fields are ``None`` with the reason stated in the rule
strings, never ``0.0``. A backwards axis is characterized as what it is (a negative span, a
count of negative intervals) and its *rates are withheld* rather than published as negative
sample rates. Nothing here is sorted, repaired or interpolated: an axis is characterized as
stored, and refusing it is the admission policy's business.

**The timestamp pathologies are measured in two units, and they are not interchangeable.**
:attr:`TimebaseCharacterization.max_relative_interval_deviation` is the design's interval
statistic: the largest deviation of a stored interval from the axis's median interval,
relative to that median. :attr:`TimebaseCharacterization.max_relative_timing_error` is the
**timing error**: the largest distance between a stored stamp and the uniform grid the
adopted ``dt_eff`` puts it on, in units of ``dt_eff``. A uniform-grid estimator's phase error
is driven by the second, not the first, and the two answer different questions - an axis whose
intervals alternate by one clock quantum has a bounded timing error and is exactly what a
quantized logger produces, while an axis whose intervals ramp in one direction accumulates a
timing error of up to half its span at the same interval deviation. The calibration in
:data:`~udv_echo_process.analysis.sparse_spectral_admission.SPECTRAL_UNIFORMITY_TOL` is what
decides which of the two admission may rest on, and it is measured, not asserted.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._native_grid import TOLERANCE_S
from udv_echo_process.analysis._sparse_view import (
    SparseViewError,
    ViewProvenance,
    WindowView,
    view_provenance,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DURATION_RESOLUTION_SCALE_RULE",
    "FREQUENCY_RESOLUTION_RULE",
    "FULL_SPAN_INTERVAL_RULE",
    "GAP_RATIO_RULE",
    "INTERVAL_DEVIATION_RULE",
    "MEDIAN_INTERVAL_ROLE",
    "TIME_DEFINITIONS",
    "TIMING_ERROR_RULE",
    "SpectralSupportError",
    "TimebaseCharacterization",
    "characterize_stamps",
    "characterize_timebase",
    "one_sided_frequency_grid",
]


class SpectralSupportError(SparseViewError):
    """A spectral-support question cannot be answered as asked.

    Raised for stamps that are not a finite one-dimensional array of numbers, a frequency
    grid that no integer sample count and rate produce, and the boundary cases the target
    module refuses by name. A view that cannot be selected at all is refused by
    :class:`~udv_echo_process.analysis._sparse_view.SparseViewError`, of which this is a
    subclass, so a caller may catch either the spectral refusal or the whole sparse-view
    refusal - and both are a ``ValueError``.

    A *refused axis* is not this error: admission is a typed result
    (:class:`~udv_echo_process.analysis.sparse_spectral_admission.SpectralAdmission`) that
    names the failed condition, because "this axis is too irregular for a uniform-grid
    estimator" is an answer, not a failure to compute one.
    """


#: The three adopted definitions, as the arithmetic a reader can reproduce. The full-span
#: interval is the *only* sampling interval SA2 uses for a rate, a Nyquist frequency or a bin
#: width; the median interval is a timestamp diagnostic.
TIME_DEFINITIONS = (
    "span = t[-1] - t[0]; dt_eff = span / (N - 1); fs_eff = 1 / dt_eff = (N - 1) / span. "
    "dt_eff is the full-span effective interval and the adopted sampling interval - the same "
    "quantity SA1's LAG_GRID_RULE puts on the ACF lag axis."
)

#: Why the median interval is published but never called the sample rate.
MEDIAN_INTERVAL_ROLE = (
    "the median adjacent interval, and 1 / that, are diagnostics of the timestamp structure: "
    "a quantized instrument clock makes the median interval the dominant timestamp quantum "
    "rather than the period, so it is reported beside the adopted full-span interval and is "
    "never the sample rate."
)

#: The adopted interval's own statement, so a result cannot quote the diagnostic in its place.
FULL_SPAN_INTERVAL_RULE = (
    "the full-span effective interval (t[-1] - t[0]) / (N - 1) is the *adopted* sampling "
    "interval: it is the one with a stated justification, and the rate, the Nyquist frequency "
    "and the bin spacing are all derived from it and from nothing else."
)

#: The design's interval statistic, as the arithmetic it is.
INTERVAL_DEVIATION_RULE = (
    "max_relative_interval_deviation = max(|dt_i - median(dt)|) / median(dt) over the stored "
    "adjacent intervals: the largest relative deviation of a stored interval from this axis's "
    "median interval. It is reported for every axis and is consumed by the admission policy "
    "as a diagnostic (see INTERVAL_DEVIATION_ROLE there), because it bounds the *interval* "
    "error and not the accumulated timing error."
)

#: The timing error, as the arithmetic it is.
TIMING_ERROR_RULE = (
    "max_relative_timing_error = max(|t_n - (t_0 + n * dt_eff)|) / dt_eff, and "
    "max_timing_error_s is the same maximum in seconds: the largest "
    "distance between a stored stamp and the uniform grid the adopted dt_eff puts it on, in "
    "units of dt_eff. A uniform-grid estimator assumes exactly that grid, so its phase error "
    "at a frequency f is bounded by 2 * pi * (f / fs_eff) * max_relative_timing_error - which "
    "is why admission rests on this quantity rather than on the interval deviation."
)

#: The gap statistic, as the arithmetic it is and as what it does not measure.
GAP_RATIO_RULE = (
    "largest_gap_ratio = max(dt_i) / median(dt): the longest stored interval over the median "
    "one. A diagnostic of one isolated delay, deliberately not a rate, a period or a duty "
    "cycle: the axis's rates come from the full-span interval and never from this ratio."
)

#: The bin spacing, with the factor that distinguishes it from 1 / span stated explicitly.
FREQUENCY_RESOLUTION_RULE = (
    "frequency_resolution_hz = fs_eff / N = (N - 1) / (N * span): the bin spacing of an "
    "N-point one-sided DFT of samples taken at dt_eff. It is NOT 1 / span - the two differ by "
    "the factor (N - 1) / N - and a caller that needs bin positions takes them from "
    "one_sided_frequency_grid() rather than re-deriving the spacing."
)

#: The duration scale, and the reason it is not the bin spacing.
DURATION_RESOLUTION_SCALE_RULE = (
    "duration_resolution_scale_hz = 1 / span: the observation-duration scale, published "
    "because it is the resolution figure a reader expects to see quoted, and labelled "
    "approximate. It is not the DFT bin spacing under the adopted fs_eff and must not be used "
    "as one."
)


class TimebaseCharacterization(ValueModel):
    """One view's sampling axis: its counts, its intervals, its rates and its bin spacing.

    Every rate here is derived from the adopted full-span effective interval
    (:data:`TIME_DEFINITIONS`), and every interval statistic is derived from the stored stamps
    with no sorting, no repair and no interpolation. ``provenance`` is the shared SA1 record,
    absent only for an axis characterized from bare stamps
    (:func:`characterize_stamps`), where there is no recording to describe and a fabricated
    provenance would be a claim about a file that does not exist.

    The rate fields are ``None`` when the axis cannot honestly supply them: fewer than two
    stamps have no interval at all, and an axis whose span is not positive cannot yield a
    positive sampling interval. Nothing here substitutes ``0.0`` for an undefined rate.
    """

    #: The shared view record: source identity, the three extents, the time and depth windows
    #: and the view's own rule. ``None`` only on the bare-stamps path.
    provenance: ViewProvenance | None = None
    profiles: int
    start_s: float | None
    end_s: float | None
    span_s: float | None
    median_interval_s: float | None
    median_interval_rate_hz: float | None
    full_span_interval_s: float | None
    effective_sample_rate_hz: float | None
    nyquist_hz: float | None
    interval_min_s: float | None
    interval_max_s: float | None
    interval_iqr_s: float | None
    max_relative_interval_deviation: float | None
    max_relative_timing_error: float | None
    #: The same timing error in seconds, which is the unit a logger's clock quantum is in.
    max_timing_error_s: float | None
    largest_gap_ratio: float | None
    duplicate_intervals: int
    negative_intervals: int
    strictly_increasing: bool | None
    frequency_resolution_hz: float | None
    duration_resolution_scale_hz: float | None
    method: str
    median_interval_role: str
    interval_deviation_rule: str
    timing_error_rule: str
    gap_ratio_rule: str
    frequency_resolution_rule: str
    duration_resolution_scale_rule: str
    full_span_interval_rule: str
    undefined_rule: str

    @model_validator(mode="after")
    def _check_the_axis_is_the_views_own_and_its_rates_are_defined(self) -> TimebaseCharacterization:
        if self.profiles < 0:
            raise ValueError(f"a profile count cannot be negative, got {self.profiles}")
        intervals = max(self.profiles - 1, 0)
        if self.duplicate_intervals + self.negative_intervals > intervals:
            raise ValueError(
                f"{self.duplicate_intervals} duplicate(s) and {self.negative_intervals} "
                f"negative interval(s) exceed the {intervals} interval(s) {self.profiles} "
                "stored stamps define"
            )
        if self.profiles < 2:
            if self.strictly_increasing is not None:
                raise ValueError(
                    f"{self.profiles} stamp(s) define no interval, so 'strictly increasing' is "
                    "vacuous here and is reported as undefined rather than as a yes"
                )
            for name in (
                "median_interval_s",
                "median_interval_rate_hz",
                "full_span_interval_s",
                "effective_sample_rate_hz",
                "nyquist_hz",
                "interval_min_s",
                "interval_max_s",
                "interval_iqr_s",
                "max_relative_interval_deviation",
                "max_relative_timing_error",
                "largest_gap_ratio",
                "frequency_resolution_hz",
                "duration_resolution_scale_hz",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{self.profiles} stamp(s) define no interval, so {name} is undefined "
                        f"and must not be reported ({getattr(self, name)!r})"
                    )
            return self
        if self.start_s is None or self.end_s is None or self.span_s is None:
            raise ValueError("an axis with intervals records its own first and last stamp")
        if not math.isclose(
            self.span_s, self.end_s - self.start_s, abs_tol=TOLERANCE_S
        ):
            raise ValueError(
                "the span must be the distance between the axis's own first and last stamp, "
                "so a declared interval cannot be reported as achieved"
            )
        if self.strictly_increasing is None:
            raise ValueError("an axis with at least two stamps answers whether it increases")
        # A rate exists exactly when the adopted interval is positive. A backwards axis
        # (negative span) and an axis whose stamps all coincide are characterized, and their
        # rates are withheld rather than published as a negative or infinite sample rate.
        rate_defined = (
            self.full_span_interval_s is not None and self.full_span_interval_s > 0.0
        )
        for name in ("effective_sample_rate_hz", "nyquist_hz", "frequency_resolution_hz"):
            present = getattr(self, name) is not None
            if present is not rate_defined:
                raise ValueError(
                    f"{name} must be present exactly when the adopted full-span interval is "
                    "positive: a span of "
                    f"{self.span_s!r} s over {self.profiles} stamp(s) gives "
                    f"{self.full_span_interval_s!r} s, which is no sampling interval"
                )
        if (self.duration_resolution_scale_hz is not None) != (self.span_s > 0.0):
            raise ValueError(
                "the observation-duration scale 1 / span exists exactly when the stored span "
                "is positive"
            )
        if self.interval_min_s is None or self.interval_max_s is None:
            raise ValueError("an axis with intervals reports its own interval extremes")
        if self.span_s > 0.0:
            if self.interval_max_s <= 0.0:
                raise ValueError(
                    "a positive span consists of intervals whose largest is positive"
                )
            if self.interval_max_s > self.span_s + TOLERANCE_S:
                raise ValueError(
                    f"no stored interval {self.interval_max_s!r} s can exceed the span "
                    f"{self.span_s!r} s it is part of"
                )
        if self.provenance is not None:
            if self.provenance.profiles != self.profiles:
                raise ValueError(
                    f"the characterization holds {self.profiles} profile(s) and its provenance "
                    f"{self.provenance.profiles}: a rate quoted against the wrong view is a "
                    "claim about another recording"
                )
            if not math.isclose(
                self.start_s, self.provenance.window_start_s, abs_tol=TOLERANCE_S
            ) or not math.isclose(
                self.end_s, self.provenance.window_end_s, abs_tol=TOLERANCE_S
            ):
                raise ValueError(
                    "the characterization's first and last stamp must be the window the "
                    "provenance records"
                )
        return self


def _stamps(time_s: object) -> np.ndarray:
    """The axis as a finite float array, refused by name when it is not one.
    """
    if np.iscomplexobj(time_s):
        raise SpectralSupportError(
            "a time axis must be real: a complex stamp has an imaginary part that no stored "
            "profile time has, and discarding it silently would be an invisible repair"
        )
    array = np.asarray(time_s, dtype=float)
    if array.ndim != 1:
        raise SpectralSupportError(
            f"a time axis is one-dimensional, got shape {array.shape}"
        )
    if array.size and not bool(np.all(np.isfinite(array))):
        raise SpectralSupportError(
            "a time axis must be finite: a non-finite stamp is not a time at which a sample "
            "was stored"
        )
    return array


def characterize_stamps(time_s: object) -> TimebaseCharacterization:
    """One axis's sampling characterization from its stored stamps alone.

    The same arithmetic :func:`characterize_timebase` uses, on stamps that no view holds: the
    calibration harness builds synthetic axes this way, and the degenerate cases (no stamp, one
    stamp) cannot be built as a :class:`WindowView` at all - a view holds at least one profile
    by construction. The result carries no provenance, because there is no recording to
    describe; a production caller describes a recording and uses
    :func:`characterize_timebase`.

    Raises:
        SpectralSupportError: for a time axis that is not one-dimensional, or that holds a
            non-finite stamp.
    """
    return _characterize(_stamps(time_s), provenance=None)


def characterize_timebase(view: WindowView) -> TimebaseCharacterization:
    """One view's sampling characterization, with the shared view provenance attached.

    Computed from the view's own ``time_s``: no interpolation, no resampling and no
    substitution of the declared window for the span the stamps achieve. The view is the only
    cut, so this is the only place a spectral rate comes from.

    Raises:
        SpectralSupportError: for a view whose stamps are not a finite one-dimensional axis
            (the view's own validator already refuses a decreasing axis, so an axis that
            reaches here has been cut, labelled and checked by SA1).
    """
    return _characterize(_stamps(view.time_s), provenance=view_provenance(view))


def _characterize(
    stamps: np.ndarray, *, provenance: ViewProvenance | None
) -> TimebaseCharacterization:
    """The one implementation both entry points share.
    """
    count = int(stamps.size)
    shared = {
        "provenance": provenance,
        "profiles": count,
        "method": TIME_DEFINITIONS,
        "median_interval_role": MEDIAN_INTERVAL_ROLE,
        "interval_deviation_rule": INTERVAL_DEVIATION_RULE,
        "timing_error_rule": TIMING_ERROR_RULE,
        "gap_ratio_rule": GAP_RATIO_RULE,
        "frequency_resolution_rule": FREQUENCY_RESOLUTION_RULE,
        "duration_resolution_scale_rule": DURATION_RESOLUTION_SCALE_RULE,
        "full_span_interval_rule": FULL_SPAN_INTERVAL_RULE,
        "undefined_rule": (
            "an undefined quantity is reported as None with its reason, never as 0.0: fewer "
            "than two stamps have no interval and no rate, an axis whose span is not positive "
            "has no positive sampling interval to report a rate for, and an axis whose median "
            "interval is not positive has no regular band for a relative deviation to be "
            "measured against."
        ),
    }
    if count == 0:
        return TimebaseCharacterization(
            start_s=None,
            end_s=None,
            span_s=None,
            median_interval_s=None,
            median_interval_rate_hz=None,
            full_span_interval_s=None,
            effective_sample_rate_hz=None,
            nyquist_hz=None,
            interval_min_s=None,
            interval_max_s=None,
            interval_iqr_s=None,
            max_relative_interval_deviation=None,
            max_relative_timing_error=None,
            max_timing_error_s=None,
            largest_gap_ratio=None,
            duplicate_intervals=0,
            negative_intervals=0,
            strictly_increasing=None,
            frequency_resolution_hz=None,
            duration_resolution_scale_hz=None,
            **shared,
        )
    start = float(stamps[0])
    end = float(stamps[-1])
    span = float(end - start)
    if count == 1:
        return TimebaseCharacterization(
            start_s=start,
            end_s=end,
            span_s=span,
            median_interval_s=None,
            median_interval_rate_hz=None,
            full_span_interval_s=None,
            effective_sample_rate_hz=None,
            nyquist_hz=None,
            interval_min_s=None,
            interval_max_s=None,
            interval_iqr_s=None,
            max_relative_interval_deviation=None,
            max_relative_timing_error=None,
            max_timing_error_s=None,
            largest_gap_ratio=None,
            duplicate_intervals=0,
            negative_intervals=0,
            strictly_increasing=None,
            frequency_resolution_hz=None,
            duration_resolution_scale_hz=None,
            **shared,
        )

    intervals = np.diff(stamps)
    median = float(np.median(intervals))
    adopted = span / (count - 1)
    duplicates = int(np.count_nonzero(intervals == 0.0))
    negatives = int(np.count_nonzero(intervals < 0.0))
    # The deviations are relative to a median and to the adopted interval respectively, so
    # each is defined exactly when its own divisor is positive. A non-positive divisor is not
    # a small deviation: an axis that is entirely one repeated stamp scores the *worst*
    # possible axis, and a substituted zero would read as a measurement.
    deviation = (
        float(np.max(np.abs(intervals - median)) / median) if median > 0.0 else None
    )
    grid = start + np.arange(count, dtype=float) * adopted if adopted > 0.0 else None
    timing_error = (
        float(np.max(np.abs(stamps - grid)) / adopted) if grid is not None else None
    )
    timing_error_s = float(np.max(np.abs(stamps - grid))) if grid is not None else None
    gap = float(np.max(intervals) / median) if median > 0.0 else None
    positive_adopted = adopted > 0.0
    return TimebaseCharacterization(
        start_s=start,
        end_s=end,
        span_s=span,
        median_interval_s=median,
        median_interval_rate_hz=(1.0 / median) if median > 0.0 else None,
        full_span_interval_s=adopted,
        effective_sample_rate_hz=(1.0 / adopted) if positive_adopted else None,
        nyquist_hz=(0.5 / adopted) if positive_adopted else None,
        interval_min_s=float(np.min(intervals)),
        interval_max_s=float(np.max(intervals)),
        interval_iqr_s=float(
            np.percentile(intervals, 75.0) - np.percentile(intervals, 25.0)
        ),
        max_relative_interval_deviation=deviation,
        max_relative_timing_error=timing_error,
        max_timing_error_s=timing_error_s,
        largest_gap_ratio=gap,
        duplicate_intervals=duplicates,
        negative_intervals=negatives,
        strictly_increasing=bool(not duplicates and not negatives),
        frequency_resolution_hz=(1.0 / adopted / count) if positive_adopted else None,
        duration_resolution_scale_hz=(1.0 / span) if span > 0.0 else None,
        **shared,
    )


def one_sided_frequency_grid(
    profiles: int, effective_sample_rate_hz: float
) -> dict[str, object]:
    """The one-sided frequency grid an ``N``-point DFT of an adopted-rate axis produces.

    The grid is ``f_k = k * delta_f`` for ``k = 0 .. floor(N / 2)`` with
    ``delta_f = fs_eff / N`` (:data:`FREQUENCY_RESOLUTION_RULE`), and it is the *only*
    definition of the future periodogram's bin positions in this repository. It is published
    here, in SA2.1, because the target-support question is asked of the grid rather than of an
    estimator: nearest prospective bin, bin offset, resolution in bins and the frequency cells
    of §11 all come from this function, and the estimator SA2.2 implements must land on the
    same grid instead of re-deriving a spacing.

    Two facts about the one-sided grid are returned rather than left to a caller's memory,
    because they decide the endpoint cell rules:

    - for **even** ``N`` the last bin is ``k = N / 2`` and sits exactly at ``fs_eff / 2``:
      mathematical Nyquist *is* represented, and that bin is not doubled in a one-sided
      spectrum;
    - for **odd** ``N`` the last bin is ``k = (N - 1) / 2`` at ``fs_eff / 2 - delta_f / 2``,
      which is **below** mathematical Nyquist: no bin sits at Nyquist, and the highest
      represented bin's cell is closed by the physical support instead
      (:func:`~udv_echo_process.analysis.sparse_target_support.frequency_cell`).

    Returns:
        ``{"bins": int, "delta_f_hz": float, "frequencies_hz": np.ndarray,
        "nyquist_hz": float, "nyquist_is_represented": bool, "top_bin_hz": float}``.

    Raises:
        SpectralSupportError: for a sample count below one, a rate that is not positive and
            finite, or a grid whose bins are not strictly increasing (an arithmetic failure
            that must not be reported as a spectrum axis).
    """
    count = int(profiles)
    rate = float(effective_sample_rate_hz)
    if count < 1:
        raise SpectralSupportError(
            f"a one-sided DFT grid needs at least one sample, got {count}"
        )
    if not math.isfinite(rate) or rate <= 0.0:
        raise SpectralSupportError(
            f"a frequency grid needs a positive finite sample rate, got {rate!r}: an axis "
            "without a defined rate has no bins"
        )
    bins = count // 2 + 1
    delta_f = rate / count
    frequencies = np.arange(bins, dtype=float) * delta_f
    nyquist = 0.5 * rate
    if bins > 1 and not bool(np.all(np.diff(frequencies) > 0.0)):
        raise SpectralSupportError(
            f"the one-sided grid of {count} samples at {rate!r} Hz is not strictly "
            "increasing; a frequency axis with a repeated bin cannot carry a resolution"
        )
    return {
        "bins": bins,
        "delta_f_hz": float(delta_f),
        "frequencies_hz": frequencies,
        "nyquist_hz": float(nyquist),
        "nyquist_is_represented": bool(count % 2 == 0),
        "top_bin_hz": float(frequencies[-1]),
    }
