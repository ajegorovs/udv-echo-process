"""The SA2 admission layer: every refusal it can issue, and the threshold's boundary.

The boundary group is the one that has to be exact. ``<=`` and ``<`` differ on an axis that
sits precisely at the calibrated tolerance, and no axis is more precisely at it than one built
by asking for it: the tolerance the test passes in *is* the axis's own measured timing error, so
the equality is exact rather than approximated by a constructed perturbation. That is also why
:func:`spectral_admission` takes the tolerance as a parameter at all - a policy threshold that
could only be tested by perturbing an axis until it happened to land on it would not be testable.

**Admission is target-independent, and that is asserted rather than assumed.** The verdict
function has no target parameter and no pass over the probe list, and the tests below pin both
the call signature and the behaviour that makes the E128 case reportable: an axis can be
admitted while a target on it is unsupported, and the two verdicts come from different
functions for that reason.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_spectral_admission import (
    ADMISSION_CONDITIONS,
    DECLARED_DISTORTION_BOUNDS,
    MIN_SPECTRAL_SAMPLES,
    SPECTRAL_UNIFORMITY_TOL,
    SPECTRAL_UNIFORMITY_TOL_DERIVATION,
    AdmissionCondition,
    spectral_admission,
)
from udv_echo_process.analysis.sparse_spectral_support import (
    characterize_stamps,
)


def uniform(count: int, span_s: float) -> np.ndarray:
    """An exact uniform axis of ``count`` samples spanning ``span_s``."""
    return np.linspace(0.0, span_s, count)


def jogged(count: int, span_s: float, amount: float) -> np.ndarray:
    """A uniform axis whose stamps alternate either side of the grid by ``amount`` intervals.

    The realised timing error is up to *twice* ``amount``: the sign change at the ends leaves the
    span short by ``2 * amount`` intervals, so the adopted rate is a hair slow and a linear ramp
    adds to the jog in the middle of the record. The tests below read the measured value rather
    than predicting it, and the boundary test passes the axis's own measurement back in as the
    tolerance so that its equality is exact whatever the factor is.
    """
    interval = span_s / (count - 1)
    signs = np.where(np.arange(count) % 2 == 0, 1.0, -1.0)
    return interval * np.arange(count) + signs * amount * interval


def test_an_exact_uniform_axis_is_admitted_and_says_why() -> None:
    verdict = spectral_admission(characterize_stamps(uniform(536, 11.98)))
    assert verdict.admitted is True
    assert verdict.failed_conditions == ()
    assert all(item.satisfied for item in verdict.conditions)
    assert verdict.reason.startswith("admitted for ")
    assert verdict.estimator in verdict.reason
    assert len(verdict.conditions) == len(ADMISSION_CONDITIONS)
    assert verdict.observed_samples == 536
    assert verdict.spectral_uniformity_tol == SPECTRAL_UNIFORMITY_TOL
    assert verdict.min_samples == MIN_SPECTRAL_SAMPLES


def test_the_verdict_exposes_the_design_s_operands_through_one_characterization() -> None:
    """The verdict carries no second copy of the numbers it rules on."""
    characterization = characterize_stamps(jogged(826, 12.5345, 0.1))
    verdict = spectral_admission(characterization)
    assert verdict.characterization is characterization
    assert verdict.observed_samples == characterization.profiles
    assert verdict.strictly_increasing == characterization.strictly_increasing
    assert verdict.duplicate_intervals == characterization.duplicate_intervals
    assert verdict.negative_intervals == characterization.negative_intervals
    assert verdict.max_relative_timing_error == characterization.max_relative_timing_error
    assert (
        verdict.max_relative_interval_deviation
        == characterization.max_relative_interval_deviation
    )
    assert verdict.largest_gap_ratio == characterization.largest_gap_ratio
    assert verdict.interval_deviation_role and verdict.gap_dominance_rule
    assert verdict.timing_error_admission


def test_the_verdict_carries_every_condition_with_its_observed_value_and_threshold() -> None:
    verdict = spectral_admission(characterize_stamps(uniform(64, 3.0)))
    seen = {item.condition: item for item in verdict.conditions}
    assert set(seen) == set(ADMISSION_CONDITIONS)
    assert seen[AdmissionCondition.SAMPLE_COUNT].observed == 64.0
    assert seen[AdmissionCondition.SAMPLE_COUNT].threshold == float(MIN_SPECTRAL_SAMPLES)
    assert seen[AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE].threshold == (
        SPECTRAL_UNIFORMITY_TOL
    )
    assert seen[AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE].observed == pytest.approx(0.0)


def test_too_few_samples_is_its_own_refusal() -> None:
    verdict = spectral_admission(characterize_stamps(uniform(MIN_SPECTRAL_SAMPLES - 1, 1.0)))
    assert verdict.admitted is False
    assert verdict.failed_conditions == (AdmissionCondition.SAMPLE_COUNT,)
    assert "too few samples" in verdict.reason
    assert f"{MIN_SPECTRAL_SAMPLES - 1}" in verdict.reason


def test_the_sample_floor_itself_is_admitted() -> None:
    """``>=`` on the floor, inclusive, and stated rather than implied."""
    verdict = spectral_admission(characterize_stamps(uniform(MIN_SPECTRAL_SAMPLES, 1.0)))
    assert verdict.admitted is True
    assert verdict.failed_conditions == ()


def test_a_duplicate_stamp_is_refused_and_names_the_pathology() -> None:
    stamps = uniform(64, 3.0)
    stamps[10] = stamps[9]
    verdict = spectral_admission(characterize_stamps(stamps))
    assert verdict.admitted is False
    assert AdmissionCondition.NO_DUPLICATE_STAMPS in verdict.failed_conditions
    assert AdmissionCondition.STRICTLY_INCREASING in verdict.failed_conditions
    assert "duplicate timestamps" in verdict.reason
    assert verdict.duplicate_intervals == 1


def test_a_decreasing_axis_is_refused_as_an_axis_and_is_not_sorted() -> None:
    verdict = spectral_admission(characterize_stamps(np.array([3.0, 2.0, 1.0, 0.0])))
    assert verdict.admitted is False
    assert AdmissionCondition.STRICTLY_INCREASING in verdict.failed_conditions
    assert verdict.negative_intervals == 3
    assert verdict.strictly_increasing is False
    assert "do not increase strictly" in verdict.reason


def test_an_axis_with_one_profile_is_refused_for_having_no_interval() -> None:
    verdict = spectral_admission(characterize_stamps(np.array([1.5])))
    assert verdict.admitted is False
    assert set(verdict.failed_conditions) == {
        AdmissionCondition.SAMPLE_COUNT,
        AdmissionCondition.STRICTLY_INCREASING,
        AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE,
    }
    assert verdict.strictly_increasing is None
    assert "no timing error is defined" in verdict.reason
    assert "too few samples" in verdict.reason, "every failed condition is named"
    assert "do not increase strictly" in verdict.reason


def test_low_irregularity_well_below_the_tolerance_is_admitted() -> None:
    verdict = spectral_admission(characterize_stamps(jogged(826, 12.5345, 0.01)))
    assert verdict.admitted is True
    assert verdict.max_relative_timing_error is not None
    assert 0.0 < verdict.max_relative_timing_error < 0.3 * SPECTRAL_UNIFORMITY_TOL


def test_the_tolerance_itself_is_admitted_and_a_hair_more_is_not() -> None:
    """The inclusive boundary, tested exactly and with no hidden epsilon."""
    characterization = characterize_stamps(jogged(826, 12.5345, 0.1))
    observed = characterization.max_relative_timing_error
    assert observed is not None and observed > 0.0
    at = spectral_admission(characterization, tolerance=observed)
    assert at.admitted is True, "<= tolerance: the equality is admitted"
    above = spectral_admission(characterization, tolerance=np.nextafter(observed, 0.0))
    assert above.admitted is False, "one float step below the observed value refuses it"
    assert "irregularity past the calibrated tolerance" in above.reason


def test_a_grossly_irregular_axis_is_refused_on_the_calibrated_rule() -> None:
    interval = 12.5345 / 825
    ramping = np.concatenate((np.full(412, 0.1), np.full(413, -0.1)))
    stamps = np.concatenate(([0.0], np.cumsum(interval * (1.0 + ramping))))
    verdict = spectral_admission(characterize_stamps(stamps))
    assert verdict.admitted is False
    assert verdict.failed_conditions == (AdmissionCondition.TIMING_ERROR_WITHIN_TOLERANCE,)
    assert verdict.max_relative_timing_error is not None
    assert verdict.max_relative_timing_error > 40.0
    assert "against the calibrated" in verdict.reason


def test_several_simultaneous_failures_are_all_named_in_one_reason() -> None:
    stamps = np.array([0.0, 0.0, 0.2, 0.0, 0.31])
    verdict = spectral_admission(characterize_stamps(stamps))
    assert verdict.admitted is False
    assert len(verdict.failed_conditions) >= 3
    assert "too few samples" in verdict.reason
    assert "duplicate timestamps" in verdict.reason


def test_the_gap_diagnostic_is_dominated_by_the_rule_that_does_the_refusing() -> None:
    """An isolated gap is refused by the timing rule, and the bound is a stated inequality.

    The claim in ``GAP_DOMINANCE_RULE`` is that one interval of ratio ``g`` *forces* a timing
    error: a gap cannot hide below a timing-error threshold that this bound exceeds. The test
    sweeps the gap's ratio and its position, because the position decides how much of the
    accumulation the axis reaches and the minimum over positions is the interesting one.
    """
    count, span = 257, 12.5345
    interval = span / (count - 1)
    for ratio in (1.001, 1.01, 1.1, 2.0, 5.0):
        for position in (1, (count - 1) // 2, count - 3):
            intervals = np.full(count - 1, interval)
            intervals[position] = interval * ratio
            intervals *= span / float(np.sum(intervals))
            stamps = np.concatenate(([0.0], np.cumsum(intervals)))
            verdict = spectral_admission(characterize_stamps(stamps))
            observed = verdict.max_relative_timing_error
            assert observed is not None
            lower_bound = (ratio - 1.0) * (count - 1) / (count - 2 + ratio + 1.0)
            assert observed > 0.4 * lower_bound, (
                f"a gap of ratio {ratio} at position {position} reported a timing error of "
                f"{observed}, far below the {lower_bound} a gap forces"
            )
            assert verdict.largest_gap_ratio == pytest.approx(ratio, rel=0.01)


def test_admission_is_target_independent_by_signature_and_by_behaviour() -> None:
    """No target can reach the admission rule: the parameter is not there to pass."""
    parameters = set(inspect.signature(spectral_admission).parameters)
    assert "target_hz" not in parameters
    assert not {name for name in parameters if "target" in name}
    assert "frequency" not in " ".join(parameters)
    characterization = characterize_stamps(uniform(144, 12.5345))
    assert spectral_admission(characterization) == spectral_admission(characterization)
    assert spectral_admission(characterization).admitted is True
    assert characterization.nyquist_hz is not None
    assert characterization.nyquist_hz < 25.0 / 3.0, (
        "the E128 geometry is admitted for the estimator while its band cannot carry 8.333 Hz"
    )


def test_the_declared_bounds_are_positive_and_the_tolerance_is_inside_them() -> None:
    assert DECLARED_DISTORTION_BOUNDS.peak_frequency_error_bins > 0.0
    assert DECLARED_DISTORTION_BOUNDS.band_power_error_percent > 0.0
    assert DECLARED_DISTORTION_BOUNDS.windowed_power_error_percent > 0.0
    assert DECLARED_DISTORTION_BOUNDS.target_response_error_percent > 0.0
    assert 0.0 < SPECTRAL_UNIFORMITY_TOL < 0.2
    assert SPECTRAL_UNIFORMITY_TOL in (0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09), (
        "the operational tolerance is a whole UNIFORMITY_TOL_QUANTUM of an interval, quantized "
        "downward from a measurement rather than chosen"
    )


def test_the_tolerance_is_selected_from_the_declared_bounds_and_never_from_a_recording() -> None:
    """The policy numbers are module constants: no committed quantity can have chosen them.

    The derivation must carry all three distinct numbers and the rule between them, because the
    failure mode this guards is exactly the conflation of the measured boundary with the shipped
    operational tolerance.
    """
    assert "0.09918" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "measured clean boundary" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "0.09923" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "first measured violation" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "quantized downward" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "UNIFORMITY_TOL_QUANTUM" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
    assert "strictly inside" in SPECTRAL_UNIFORMITY_TOL_DERIVATION, (
        "the derivation must say the tolerance sits inside the clean region, not at its edge"
    )
    assert "no committed recording" in SPECTRAL_UNIFORMITY_TOL_DERIVATION
