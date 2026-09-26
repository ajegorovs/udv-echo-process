"""May this axis be analysed by the uniform-grid estimator at all? (``SA2``).

The second SA2 question, and a **target-independent** one: it may not consult whether 8.333 Hz
was requested. A recording can support a valid uniformly-sampled spectrum while a particular
requested target lies above Nyquist, and the two verdicts are computed by two modules
(:mod:`udv_echo_process.analysis.sparse_spectral_support` characterizes the axis,
:mod:`udv_echo_process.analysis.sparse_target_support` asks about a target) so that neither can
quietly become the other.

**What admission rests on, and why.** The design's §B uniformity rule is stated over the
*interval* deviation, and :data:`SPECTRAL_UNIFORMITY_TOL` is calibrated by the procedure in §J.
Carrying that procedure out showed that the two candidate operands answer different questions,
and the difference is not academic:

- a uniform-grid estimator assumes the samples sit on ``t_0 + n * dt_eff``, so its phase error
  at frequency ``f`` is bounded by ``2 * pi * (f / fs_eff) * max_relative_timing_error`` - the
  **timing error** is the quantity that drives the distortion, and it is the quantity
  :func:`~udv_echo_process.analysis.sparse_spectral_support.characterize_timebase` measures
  against the adopted grid;
- the **interval deviation** bounds a single interval's error and says nothing about how those
  errors accumulate. Its cost is precisely what a quantized logger produces and what a coherent
  ramp produces alike: the committed recordings' stamps are rounded to a 1e-4 s quantum, so
  their intervals deviate by up to 6.5789e-3 relative while their *positions* never leave the
  quantum - a bounded timing error of 6.58e-3 intervals - whereas an axis whose intervals ramp
  by the same relative amount accumulates a timing error of up to half its span, i.e. of order
  4.1e-2 s, and a uniform grid is simply the wrong model for it.

Admission therefore rests on the calibrated **timing error** (:data:`SPECTRAL_UNIFORMITY_TOL`,
:data:`TIMING_ERROR_ADMISSION`), and the interval deviation is carried on both the
characterization and the verdict as the design's own diagnostic
(:data:`INTERVAL_DEVIATION_ROLE`). The calibration measures both operands, and
``tests/test_sparse_spectral_admission.py`` pins the pair of cases that makes the choice
load-bearing rather than cosmetic: an axis with the committed quantum's interval deviation is
admitted, and a ramp axis with the same interval deviation is refused.

**The tolerance is evidence, not a cautious-looking decimal.** :data:`DECLARED_DISTORTION_BOUNDS`
states, before any measurement, how much distortion the axis may contribute; the jitter
calibration in ``tests/_spectral_calibration.py`` measures the four distortions against the
same signal on an exact uniform grid; and the calibration then fixes

- the **measured clean boundary** - the largest timing error at which *every* measured axis at or
  below it stays inside those bounds (``0.09918``);
- the **first measured violation**, just above it (``0.09923``);
- the **operational admission tolerance** shipped as :data:`SPECTRAL_UNIFORMITY_TOL`, which is the
  measured clean boundary **quantized downward** by :data:`UNIFORMITY_TOL_QUANTUM` (``0.09``).

The three are separate numbers and are not interchangeable: the shipped value is deliberately
*inside* the measured clean region rather than equal to its edge. Quantization is downward only -
rounding up would cross the measured break and admit axes outside the bounds. The bounds were
declared first and were not revised to change the answer, and the calibration never reads a
committed recording, so no committed-data verdict can have influenced the threshold. A test
re-derives all three from the matrix, so a threshold that drifts from the measurement fails.

**Refusal is a result.** The only alternative to admission is an *explicitly named*
irregular-sampling estimator with its own admission policy, and SA2 v1 does not implement one
(no resampling either, and no dormer framework for either): an axis that fails this policy is
reported as refused, by name, with the failed conditions and their thresholds. Admission is
never an exception.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._sparse_view import SparseViewError, WindowView
from udv_echo_process.analysis.sparse_spectral_support import (
    TimebaseCharacterization,
    characterize_timebase,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ADMISSION_CONDITIONS",
    "DECLARED_DISTORTION_BOUNDS",
    "ESTIMATOR_UNIFORM_PERIODOGRAM",
    "GAP_DOMINANCE_RULE",
    "INTERVAL_DEVIATION_ROLE",
    "MIN_SPECTRAL_SAMPLES",
    "SPECTRAL_UNIFORMITY_TOL",
    "SPECTRAL_UNIFORMITY_TOL_DERIVATION",
    "TIMING_ERROR_ADMISSION",
    "AdmissionCondition",
    "DistortionBounds",
    "SpectralAdmission",
    "spectral_admission",
]


class DistortionBounds(ValueModel):
    """How much spectral distortion a timestamp axis may contribute, declared in advance.

    These are the plan §J bounds, stated as the largest error the axis may add to four
    quantities - each measured on a perturbed axis against the **same signal on an exact
    uniform grid**, so a quantity's own finite-record bias cancels and what is left is the
    distortion the timestamps caused.

    Each bound is derived from the role of the quantity in this stage rather than tuned until
    a dataset passed:

    - ``peak_frequency_error_bins``: a peak is reported as a frequency on this grid, and the
      stage's whole target question is asked in bins. A timestamp axis that could move a peak
      by a fifth of a bin would be comparable to the resolution at which the stage distinguishes
      "on the target" from "between bins", so the bound is set twenty times finer than one bin -
      below the grid's own resolution, and therefore conservative.
    - ``band_power_error_percent``: a band power is a number this stage reports and later
      compares between conditions. A percentage-level change is the smallest difference worth
      stating, so the axis may not manufacture one.
    - ``windowed_power_error_percent``: the same bound on the quantity §I's one-sided integral
      reproduces exactly on a uniform grid (the window-normalized mean-square power), because
      that identity is the estimator's own energy statement and an axis that breaks it by a
      per-cent-level amount has stopped being a uniform grid.
    - ``target_response_error_percent``: looser than the band bound on purpose and for a stated
      reason: the target response is a *single* bin's power, and a single Hann-tapered bin is
      the most scalloping-sensitive quantity in the spectrum (a worst-case off-bin tone leaves
      the nearest bin about 28 % short of the peak). Holding the axis's contribution to 5 %
      keeps it well inside the estimator's own accepted finite-record behaviour without
      pretending a single bin carries a tolerance it cannot.
    """

    peak_frequency_error_bins: float
    band_power_error_percent: float
    windowed_power_error_percent: float
    target_response_error_percent: float

    @model_validator(mode="after")
    def _check_the_bounds_are_positive_and_finite(self) -> DistortionBounds:
        for name, value in (
            ("peak_frequency_error_bins", self.peak_frequency_error_bins),
            ("band_power_error_percent", self.band_power_error_percent),
            ("windowed_power_error_percent", self.windowed_power_error_percent),
            ("target_response_error_percent", self.target_response_error_percent),
        ):
            if not (np.isfinite(value) and value > 0.0):
                raise ValueError(
                    f"a declared distortion bound must be positive and finite, got "
                    f"{name}={value!r}: a bound of zero would admit no axis at all"
                )
        return self


#: The distortion bounds :data:`SPECTRAL_UNIFORMITY_TOL` was selected at, declared before the
#: calibration was run and never revised to accommodate its output.
DECLARED_DISTORTION_BOUNDS = DistortionBounds(
    peak_frequency_error_bins=0.05,
    band_power_error_percent=1.0,
    windowed_power_error_percent=1.0,
    target_response_error_percent=5.0,
)

#: The estimator this admission is *for*. Admission is not a property of an axis in the
#: abstract: it is the answer to "may the uniform-grid periodogram be applied here", and an
#: irregular-sampling estimator would carry its own policy rather than silently inheriting
#: this one.
ESTIMATOR_UNIFORM_PERIODOGRAM = (
    "the single-view periodogram on the adopted uniform grid (fs_eff = (N - 1) / span, bin "
    "spacing fs_eff / N, Hann taper, one-sided density normalized by fs_eff * sum(w^2)) - the "
    "SA2.2 estimator, whose grid is fixed by "
    "sparse_spectral_support.one_sided_frequency_grid"
)

#: The smallest sample count the uniform-grid estimator is admitted on at all, independent of
#: any rate or target. At 16 samples a one-sided spectrum carries nine bins, so the grid holds
#: an interior bin beside its DC-adjacent and top cells - which is what makes the endpoint cell
#: rules of plan §F testable rather than degenerate. It is a floor on a *spectrum existing*,
#: not a cycle count, and it is not the binding constraint on any committed view: the fewest
#: samples any of them holds is 138.
MIN_SPECTRAL_SAMPLES = 16

#: The operational admission tolerance, on the **timing error** operand: how far, in effective
#: intervals, any stored profile stamp may sit from the uniform grid the estimator assumes. The
#: comparison is inclusive (:data:`TIMING_ERROR_ADMISSION`): an axis at exactly the tolerance is
#: admitted. This is *not* the measured clean boundary (0.09918) and not the first measured
#: violation (0.09923): it is that boundary quantized **downward** by
#: :data:`UNIFORMITY_TOL_QUANTUM`, so it sits nine hundredths of an interval below the break with a
#: 9.3% margin. Never rounded up - rounding up would cross the break.
SPECTRAL_UNIFORMITY_TOL = 0.09

#: The quantization the operational tolerance is derived by, named so the rule is executable rather
#: than described: ``SPECTRAL_UNIFORMITY_TOL == floor(measured clean boundary / this) * this``. A
#: whole hundredth of an interval is a reporting granularity, not a measurement one.
UNIFORMITY_TOL_QUANTUM = 0.01

#: How the tolerance above was obtained, in the form a reader can reproduce.
SPECTRAL_UNIFORMITY_TOL_DERIVATION = (
    "the jitter calibration (tests/_spectral_calibration.py) perturbs exact uniform grids of the "
    "four committed rate regimes - E8 826 samples / 12.5345 s, E20 560 / 12.5345 s, E64 257 / "
    "12.5345 s, E128 144 / 12.5345 s - across five perturbation families (a rounded clock quantum, "
    "independent jitter, a coherent ramp, an alternating reversal, and one isolated gap), on the "
    "on-bin and off-bin tone nearest each of the 1 Hz and 8.333 Hz probes, and measures four "
    "distortions against the same tone on the exact uniform grid: peak-frequency error in bins, "
    "band-power error over the tone's cell +/-4 bins, windowed power error over the whole one-sided "
    "grid, and the target-bin response error. 770 axes are constructed; 742 of them reach the "
    "uniformity condition (the rest are refused by the duplicate or monotonicity condition first, "
    "and their spectra are degenerate quadratic forms rather than distortions of an irregular "
    "axis). The measured clean boundary is the largest measured max_relative_timing_error at which "
    "*every* axis at or below it stays inside DECLARED_DISTORTION_BOUNDS - 0.09918 - with the first "
    "measured violation at 0.09923 and zero violations in the end. The operational tolerance 0.09 is "
    "that boundary quantized downward by UNIFORMITY_TOL_QUANTUM (a whole hundredth of an interval), "
    "so it is strictly inside the measured clean region rather than equal to its edge; it is never "
    "rounded up, because rounding up would cross the measured break. The matrix contains no "
    "committed recording, and no committed quantity appears anywhere in it: the threshold cannot "
    "have been selected from the data it will be applied to."
)

#: The uniformity comparison, stated as the arithmetic it is, with its boundary semantics.
TIMING_ERROR_ADMISSION = (
    "max_relative_timing_error <= SPECTRAL_UNIFORMITY_TOL, inclusive: an axis at exactly the "
    "tolerance is admitted (the equality is the calibrated value's own meaning, and there is "
    "no hidden epsilon on this comparison)."
)

#: Why the design's interval statistic is carried on the verdict but is not its operand.
INTERVAL_DEVIATION_ROLE = (
    "max_relative_interval_deviation is reported on the characterization and on the admission as "
    "the design's own diagnostic of the timestamp quantum, and it is *not* the admission "
    "threshold. The reason is arithmetic rather than stylistic, and the calibration measures it: "
    "the deviation bounds one interval's error and says nothing about the accumulation of those "
    "errors, which is what a uniform-grid transform is actually exposed to. Two constructed axes "
    "with nearly the same deviation therefore differ by orders of magnitude in the timing error, "
    "and the ordering by deviation is the *wrong* one - at the E8 geometry a coherent ramp reads "
    "0.2222 while a reversal every sample reads 0.1818, yet the ramp's measured worst distortion "
    "is 0.964% of full scale against the reversal's 2.46%. The deviation also moves by 22% with no "
    "change in the axis at all, because an axis with two interval levels and an odd interval count "
    "puts the median reference on whichever level the middle sample happens to be. The timing error "
    "carries the bound the deviation lacks: every sample within T effective intervals of the grid "
    "the estimator assumes puts the phase error at any frequency below Nyquist within pi*T radians, "
    "whatever the interval pattern."
)

#: The domination argument that lets the gap statistic be a diagnostic rather than a second guard.
GAP_DOMINANCE_RULE = (
    "largest_gap_ratio is a diagnostic, and the admission logic is not silent about it: one "
    "isolated interval of ratio g = dt_gap / median(dt) forces "
    "max_relative_timing_error >= (g - 1) * (N - 1) / (N - 2 + g), because every interval's "
    "error enters the accumulated position error and the others are depressed to compensate. A "
    "timing-error tolerance therefore refuses every gap ratio above 1 + tol * (1 + O(1 / N)) "
    "automatically, and a gap can never slip under the threshold unnoticed - which is why it "
    "carries no threshold of its own. That inequality is proved by a test over constructed gap "
    "axes, and the converse is false by construction: an axis can violate the tolerance with "
    "no gap at all (the coherent ramp), so the gap statistic is not a substitute for the "
    "timing-error rule either."
)


class AdmissionCondition(str, Enum):
    """The named conditions a verdict reports, one per refusal the policy can name.
    """

    #: ``observed_samples >= MIN_SPECTRAL_SAMPLES``.
    SAMPLE_COUNT = "sample-count"
    #: The stamps increase strictly.
    STRICTLY_INCREASING = "strictly-increasing"
    #: No two consecutive stamps coincide.
    NO_DUPLICATE_STAMPS = "no-duplicate-stamps"
    #: ``max_relative_timing_error <= SPECTRAL_UNIFORMITY_TOL``.
    TIMING_ERROR_WITHIN_TOLERANCE = "timing-error-within-tolerance"


#: The conditions in report order. Membership is the policy's own validity rule, so a verdict
#: cannot carry a condition this module does not define.
ADMISSION_CONDITIONS: tuple[AdmissionCondition, ...] = (
    AdmissionCondition.SAMPLE_COUNT,
    AdmissionCondition.STRICTLY_INCREASING,
    AdmissionCondition.NO_DUPLICATE_STAMPS,
    AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE,
)


class ConditionVerdict(ValueModel):
    """One named condition's outcome, with the number it was compared and the threshold.

    ``observed`` and ``threshold`` are the operands the rule used, so a reader can recompute
    the comparison rather than trust it, and ``rule`` is the arithmetic in words.
    """

    condition: AdmissionCondition
    satisfied: bool
    observed: float | None
    threshold: float | None
    rule: str


class SpectralAdmission(ValueModel):
    """Whether the uniform-grid estimator is admitted on one axis, and why not.

    Target-independent by construction: no field of this model can be a target frequency. The
    axis's own numbers travel on ``characterization`` rather than being copied here, so the
    verdict and the axis cannot drift apart, and the operands the plan §B rows are stated over
    are exposed as properties of this model for a reader who wants them without reaching
    through.

    ``admitted`` is the conjunction of every condition's verdict, and ``reason`` states each
    failed condition with its threshold - so a refusal names the pathology and the number.
    """

    characterization: TimebaseCharacterization
    estimator: str
    admitted: bool
    reason: str
    conditions: tuple[ConditionVerdict, ...]
    min_samples: int
    spectral_uniformity_tol: float
    interval_deviation_role: str
    gap_dominance_rule: str
    timing_error_admission: str

    @model_validator(mode="after")
    def _check_the_verdict_is_its_conditions_and_names_every_one(self) -> SpectralAdmission:
        present = tuple(item.condition for item in self.conditions)
        if present != ADMISSION_CONDITIONS:
            raise ValueError(
                f"a verdict reports every admission condition once, in policy order "
                f"{[str(member.value) for member in ADMISSION_CONDITIONS]}, got "
                f"{[str(member.value) for member in present]}"
            )
        if self.admitted != all(item.satisfied for item in self.conditions):
            raise ValueError(
                "a verdict is admitted exactly when every condition is satisfied: a verdict "
                "that disagreed with its own conditions would be a second, unstated policy"
            )
        if self.min_samples < 1:
            raise ValueError(f"a sample floor below one sample is no floor, got {self.min_samples}")
        if not (np.isfinite(self.spectral_uniformity_tol) and self.spectral_uniformity_tol > 0.0):
            raise ValueError(
                f"the uniformity tolerance must be positive and finite, got "
                f"{self.spectral_uniformity_tol!r}"
            )
        return self

    @property
    def failed_conditions(self) -> tuple[AdmissionCondition, ...]:
        """Every condition this axis failed, in policy order.
        """
        return tuple(item.condition for item in self.conditions if not item.satisfied)

    @property
    def observed_samples(self) -> int:
        """The axis's own profile count, which the sample-count condition was decided on.
        """
        return self.characterization.profiles

    @property
    def strictly_increasing(self) -> bool | None:
        """Whether the axis's stamps increase strictly, or ``None`` where that is vacuous.
        """
        return self.characterization.strictly_increasing

    @property
    def duplicate_intervals(self) -> int:
        """How many consecutive stamp pairs coincide. A repeated stamp is not a sample.
        """
        return self.characterization.duplicate_intervals

    @property
    def negative_intervals(self) -> int:
        """How many consecutive stamp pairs run backwards, which no sorted rewrite may hide.
        """
        return self.characterization.negative_intervals

    @property
    def max_relative_timing_error(self) -> float | None:
        """The calibrated uniformity operand: the largest position error, in effective intervals.
        """
        return self.characterization.max_relative_timing_error

    @property
    def max_timing_error_s(self) -> float | None:
        """The same operand in seconds, the unit the logger's clock quantum is measured in.
        """
        return self.characterization.max_timing_error_s

    @property
    def max_relative_interval_deviation(self) -> float | None:
        """The design's interval diagnostic, carried for the reader and not the threshold.
        """
        return self.characterization.max_relative_interval_deviation

    @property
    def largest_gap_ratio(self) -> float | None:
        """The longest interval over the median one, dominated by the timing-error rule.
        """
        return self.characterization.largest_gap_ratio


def _condition_verdicts(
    characterization: TimebaseCharacterization, *, tolerance: float, min_samples: int
) -> tuple[ConditionVerdict, ...]:
    """The four condition verdicts of one axis, in policy order.
    """
    observed = float(characterization.profiles)
    increasing = characterization.strictly_increasing
    duplicates = float(characterization.duplicate_intervals)
    timing_error = characterization.max_relative_timing_error
    return (
        ConditionVerdict(
            condition=AdmissionCondition.SAMPLE_COUNT,
            satisfied=characterization.profiles >= min_samples,
            observed=observed,
            threshold=float(min_samples),
            rule=(
                f"observed_samples >= MIN_SPECTRAL_SAMPLES ({min_samples}), inclusive: an axis "
                "at exactly the floor is admitted, because the floor states a spectrum's "
                "existence rather than a rate or a target."
            ),
        ),
        ConditionVerdict(
            condition=AdmissionCondition.STRICTLY_INCREASING,
            satisfied=increasing is True,
            observed=None,
            threshold=None,
            rule=(
                "the stored stamps increase strictly. Undefined (fewer than two stamps) fails "
                "this condition rather than passing it vacuously - an axis with no interval is "
                "not an axis whose intervals increase - and a decreasing axis is characterized "
                "as it is and refused here, never silently sorted."
            ),
        ),
        ConditionVerdict(
            condition=AdmissionCondition.NO_DUPLICATE_STAMPS,
            satisfied=characterization.duplicate_intervals == 0,
            observed=duplicates,
            threshold=0.0,
            rule=(
                "no two consecutive stamps coincide: two profiles sharing one stamp have no "
                "elapsed time between them, so they are not two samples of a uniform grid. "
                "This condition can only fail on an axis that a strictly increasing axis cannot "
                "be, and it is reported separately so the refusal names the pathology."
            ),
        ),
        ConditionVerdict(
            condition=AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE,
            satisfied=timing_error is not None and timing_error <= tolerance,
            observed=timing_error,
            threshold=tolerance,
            rule=TIMING_ERROR_ADMISSION,
        ),
    )


def spectral_admission(
    characterization: TimebaseCharacterization,
    *,
    tolerance: float = SPECTRAL_UNIFORMITY_TOL,
    min_samples: int = MIN_SPECTRAL_SAMPLES,
    estimator: str = ESTIMATOR_UNIFORM_PERIODOGRAM,
) -> SpectralAdmission:
    """Whether the uniform-grid estimator is admitted on one characterized axis.

    Args:
        characterization: the axis, from
            :func:`~udv_echo_process.analysis.sparse_spectral_support.characterize_timebase`.
        tolerance: the calibrated timing-error tolerance. Defaulted, and injectable so that a
            test can pin the boundary semantics of the comparison itself rather than of the
            shipped value.
        min_samples: the sample floor, injectable for the same reason.
        estimator: the estimator the verdict is for, recorded on the result.

    Returns:
        :class:`SpectralAdmission` for this axis: admitted, or refused with every failed
        condition named and its operands stated. No target frequency enters this call.

    Raises:
        SpectralSupportError: for a tolerance or a sample floor that is not positive and
            finite, a policy asked for with numbers the policy cannot mean.
    """
    if not (np.isfinite(tolerance) and tolerance > 0.0):
        raise SparseViewError(
            f"a uniformity tolerance must be positive and finite, got {tolerance!r}"
        )
    if not isinstance(min_samples, int) or min_samples < 1:
        raise SparseViewError(
            f"a sample floor must be a positive whole number of samples, got {min_samples!r}"
        )
    conditions = _condition_verdicts(
        characterization, tolerance=float(tolerance), min_samples=int(min_samples)
    )
    admitted = all(item.satisfied for item in conditions)
    failed = [item for item in conditions if not item.satisfied]
    reason = (
        f"admitted for {ESTIMATOR_UNIFORM_PERIODOGRAM}"
        if admitted
        else "; ".join(_refusal(item) for item in failed)
    )
    return SpectralAdmission(
        characterization=characterization,
        estimator=str(estimator),
        admitted=admitted,
        reason=reason,
        conditions=conditions,
        min_samples=int(min_samples),
        spectral_uniformity_tol=float(tolerance),
        interval_deviation_role=INTERVAL_DEVIATION_ROLE,
        gap_dominance_rule=GAP_DOMINANCE_RULE,
        timing_error_admission=TIMING_ERROR_ADMISSION,
    )


def _refusal(item: ConditionVerdict) -> str:
    """One failed condition as a reader-facing sentence naming the numbers.

    Branched rather than looked up in a dict of pre-built strings: a dict literal evaluates every
    entry, so a refusal about an axis with no interval would format the *sample count* entry's
    numbers on its way past and raise on an undefined value - a refusal that cannot be printed is
    worse than no refusal.
    """
    if item.condition is AdmissionCondition.SAMPLE_COUNT:
        return (
            f"too few samples: {item.observed:.0f} stored profile(s) against the floor of "
            f"{item.threshold:.0f}"
        )
    if item.condition is AdmissionCondition.STRICTLY_INCREASING:
        return (
            "the stored timestamps do not increase strictly, so no uniform grid is defined on "
            "this axis"
        )
    if item.condition is AdmissionCondition.NO_DUPLICATE_STAMPS:
        return (
            f"duplicate timestamps: {item.observed:.0f} consecutive pair(s) share one stamp, "
            "and two profiles at one time are not two samples"
        )
    if item.observed is None:
        return (
            "timestamp irregularity past the calibrated tolerance: no timing error is defined "
            "on this axis"
        )
    return (
        f"timestamp irregularity past the calibrated tolerance: max relative timing error "
        f"{item.observed:.6g} effective interval(s) against the calibrated {item.threshold:.6g}"
    )


def admission_of_view(
    view: WindowView,
    *,
    tolerance: float = SPECTRAL_UNIFORMITY_TOL,
    min_samples: int = MIN_SPECTRAL_SAMPLES,
) -> SpectralAdmission:
    """One view's admission verdict: characterize it and classify it, in one call.

    The convenience a caller that holds a view wants, and the only path that guarantees the
    verdict's characterization is the view's own.
    """
    return spectral_admission(
        characterize_timebase(view), tolerance=tolerance, min_samples=min_samples
    )
