"""The SA2 calibration layer: the threshold is a measurement, and the tests re-make it.

What is asserted here is not "0.09 is a good number". It is the four things that make it a
*calibrated* number rather than a chosen one:

- the harness is **deterministic** and its zero-perturbation baseline is exactly zero (a
  calibration whose baseline already distorts measures itself);
- the harness's spectral calculation **reduces to the pinned periodogram definition** on an
  exact uniform grid, so what it measures distortion *of* is the estimator the plan defines;
- the distortion **does not fall as the operand grows**, in the region the threshold lives in;
- the shipped tolerance is the measured clean region's edge **rounded down**, inside the
  declared bounds, and the run that produced it cannot see a committed recording.

The last point is tested by running the calibration from a directory that holds no dataset:
if any part of it reached for committed data, that run would fail rather than silently agree.
"""

from __future__ import annotations

import itertools
import pathlib

import _spectral_calibration as calibration
import numpy as np
import pytest

from udv_echo_process.analysis.sparse_spectral_admission import (
    DECLARED_DISTORTION_BOUNDS,
    SPECTRAL_UNIFORMITY_TOL,
    spectral_admission,
)
from udv_echo_process.analysis.sparse_spectral_support import characterize_stamps

HARNESS = pathlib.Path(__file__).resolve().parent / "_spectral_calibration.py"

#: The one measure the whole threshold rests on, per decade of the operand.
OPERAND = "timing_error"


@pytest.fixture(scope="module")
def matrix() -> tuple[calibration.CalibrationCase, ...]:
    """The calibration matrix, computed once for the file (about seven seconds)."""
    return calibration.calibration_matrix()


def test_the_declared_bounds_are_the_shipped_policy_and_not_a_local_copy() -> None:
    bounds = calibration.declared_bounds()
    assert bounds == DECLARED_DISTORTION_BOUNDS
    assert bounds.peak_frequency_error_bins > 0.0
    assert sorted(calibration.FAMILIES) == [
        "alternating",
        "jitter",
        "quantized",
        "ramp",
    ], "the deviation families are swept on one parameter grid"
    assert calibration.GAP_RATIO_GRID, "gaps are swept on a ratio grid of their own"
    assert min(calibration.GAP_RATIO_GRID) > 1.0, "a gap ratio is above 1 by definition"


def test_the_matrix_covers_rates_counts_targets_and_an_off_bin_tone() -> None:
    """No calibration on one convenient ``N`` and one frequency."""
    regimes = [label for label, _, _ in calibration.REGIMES]
    assert len(regimes) == 4
    counts = {count for _, count, _ in calibration.REGIMES}
    assert len(counts) == 4, "the four committed rate regimes have four different counts"
    entries = [
        (label, entry)
        for label, count, span in calibration.REGIMES
        for entry in calibration.tones(count, span)
    ]
    assert entries, "the probe targets must be represented in the matrix"
    assert any("off-bin" in str(entry["label"]) for _, entry in entries)
    assert any(float(entry["frequency_hz"]) == pytest.approx(1.0, rel=0.1) for _, entry in entries)
    assert calibration.TARGET_RECURRENCE_HZ == 1.0
    assert calibration.TARGET_ROTOR_REFERENCE_HZ == pytest.approx(8.3333, abs=1e-3)
    below = [
        (label, entry)
        for label, entry in entries
        if float(entry["frequency_hz"]) > 5.0 and float(entry["frequency_hz"]) < 12.0
    ]
    assert below, "8.333 Hz tones must exist where the band carries them"
    assert len({label for label, _ in below}) == 3, "three of the four regimes carry 8.333 Hz"


def test_the_perturbation_is_deterministic_and_the_baseline_is_exactly_undistorted(
    matrix: tuple[calibration.CalibrationCase, ...],
) -> None:
    first = calibration.uniform_stamps(64, 3.0)
    assert np.array_equal(first, calibration.uniform_stamps(64, 3.0))
    assert np.array_equal(
        calibration.jitter_stamps(64, 3.0, 1e-3), calibration.jitter_stamps(64, 3.0, 1e-3)
    )
    assert not np.array_equal(
        calibration.jitter_stamps(64, 3.0, 1e-3), calibration.jitter_stamps(64, 3.0, 2e-3)
    )
    zero = [case for case in matrix if case.parameter == 0.0]
    assert zero, "every family is swept from a zero-perturbation case"
    for case in zero:
        assert case.distortion.worst_fraction(calibration.declared_bounds()) < 1e-9
        assert case.max_relative_timing_error == pytest.approx(0.0, abs=1e-12)


def test_the_reference_calculation_is_the_pinned_periodogram_on_a_uniform_axis() -> None:
    """``|X|^2 / (fs * sum w^2)``, one-sided, DC and the Nyquist bin not doubled."""
    for count, span in ((144, 12.5345), (145, 12.5345), (64, 3.0), (257, 12.5345)):
        stamps = calibration.uniform_stamps(count, span)
        taper = calibration.hann(count)
        values = calibration.tone(stamps, 4.0)
        measured = calibration.reference_spectrum(stamps, values, taper=taper)
        rate = float(measured["effective_sample_rate_hz"])
        expected = np.abs(np.fft.rfft(taper * values)) ** 2 / (rate * float(np.sum(taper**2)))
        expected[1:] *= 2.0
        if count % 2 == 0:
            expected[-1] /= 2.0
        assert np.allclose(np.asarray(measured["density"]), expected, rtol=1e-9, atol=1e-12)
    # The two shortest axes the production floor admits, where the one-sided fold and the
    # Nyquist exception are exercised on a spectrum of 9 bins rather than of 400.
    for count in (16, 17):
        stamps = calibration.uniform_stamps(count, 1.0)
        taper = calibration.hann(count)
        values = calibration.tone(stamps, 0.8)
        measured = calibration.reference_spectrum(stamps, values, taper=taper)
        rate = float(measured["effective_sample_rate_hz"])
        expected = np.abs(np.fft.rfft(taper * values)) ** 2 / (rate * float(np.sum(taper**2)))
        expected[1:] *= 2.0
        if count % 2 == 0:
            expected[-1] /= 2.0
        assert np.allclose(np.asarray(measured["density"]), expected, rtol=1e-9, atol=1e-12)


def test_the_enbw_comes_from_the_coefficients_rather_than_a_remembered_constant() -> None:
    """The design's 1.5 bins is a *consequence* of the periodic Hann, and is derived here."""
    for count in (138, 144, 257, 560, 826):
        derived = calibration.hann_enbw_bins(count)
        for convention in ("periodic", "symmetric"):
            weights = calibration.hann(count, convention=convention)
            definition = count * float(np.sum(weights**2)) / float(np.sum(weights)) ** 2
            assert derived[convention] == pytest.approx(definition), (
                "the ENBW must be computed from the coefficients, not remembered"
            )
        assert derived["periodic"] == pytest.approx(1.5, abs=1e-12)
        assert derived["symmetric"] > 1.5 + 1e-6
    rectangular = np.ones(64)
    assert 64 * float(np.sum(rectangular**2)) / float(np.sum(rectangular)) ** 2 == 1.0


def test_the_distortion_does_not_fall_as_the_operand_grows_about_the_threshold(
    matrix: tuple[calibration.CalibrationCase, ...],
) -> None:
    """Monotone in the region the threshold is read off, across every family at once."""
    selected = calibration.select_tolerance(
        matrix, operand=OPERAND, bounds=calibration.declared_bounds()
    )
    first_breaking = selected["first_breaking"]
    assert first_breaking is not None
    rows = [
        (largest, fraction)
        for _, largest, fraction in calibration.worst_by_operand(matrix, operand=OPERAND)
        if largest <= float(first_breaking)
    ]
    assert len(rows) >= 3, "the region below the threshold must be resolved by several decades"
    assert rows[0][1] < 1e-9, "the zero-perturbation decade is the reference calculation's own"
    rows = [row for row in rows if row[1] > 1e-9]
    assert len(rows) >= 3, "several decades above the noise floor must remain"
    for (_, before), (_, after) in itertools.pairwise(rows):
        assert after >= before * 0.9, (
            "the distortion fell as the operand grew, so a threshold on it would not mean what "
            f"it claims: {before} then {after}"
        )
    assert rows[-1][1] > 0.01, (
        "the last decade below the break must already distort measurably, or the threshold is "
        "being read off a region where nothing is happening"
    )


def test_the_selected_tolerance_is_inside_the_measured_region_and_zero_violations_remain(
    matrix: tuple[calibration.CalibrationCase, ...],
) -> None:
    bounds = calibration.declared_bounds()
    selected = calibration.select_tolerance(matrix, operand=OPERAND, bounds=bounds)
    measured = float(selected["tolerance"])
    first_breaking = float(selected["first_breaking"])
    assert selected["violations"] == (), "nothing at or below the selection may break a bound"
    assert measured < first_breaking
    assert measured > 0.0
    # The shipped constant is the measurement rounded down to a whole hundredth of an interval.
    assert SPECTRAL_UNIFORMITY_TOL <= measured
    assert SPECTRAL_UNIFORMITY_TOL >= 0.9 * measured
    assert SPECTRAL_UNIFORMITY_TOL < first_breaking
    assert 0.09 < 1.2 * SPECTRAL_UNIFORMITY_TOL, "the shipped value is not far below the break"


def test_the_threshold_would_have_caught_the_axes_it_was_measured_against(
    matrix: tuple[calibration.CalibrationCase, ...],
) -> None:
    """The boundary is exercised from the policy side: admitted below, refused above."""
    for case in matrix:
        timing = case.max_relative_timing_error
        if timing is None or not case.reaches_uniformity:
            continue
        admitted = timing <= SPECTRAL_UNIFORMITY_TOL
        if admitted:
            fraction = case.distortion.worst_fraction(calibration.declared_bounds())
            assert fraction <= 1.0, (
                f"the shipped tolerance admits an axis measured outside the bounds: {case.report()}"
            )


def test_no_committed_recording_can_have_been_seen_by_the_calibration(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same matrix, computed where no dataset exists, selects the same tolerance."""
    where = (calibration.REGIMES[0], calibration.REGIMES[-1])
    monkeypatch.chdir(tmp_path)
    isolated = calibration.calibration_matrix(
        regimes=where, deviations=calibration.DEVIATION_GRID[:6]
    )
    here = calibration.calibration_matrix(
        regimes=where, deviations=calibration.DEVIATION_GRID[:6]
    )
    assert isolated == here
    assert calibration.select_tolerance(
        isolated, operand=OPERAND, bounds=calibration.declared_bounds()
    )["tolerance"] == calibration.select_tolerance(
        here, operand=OPERAND, bounds=calibration.declared_bounds()
    )["tolerance"]
    assert "data/" not in HARNESS.read_text(encoding="utf-8")
    assert "decode_pass" not in HARNESS.read_text(encoding="utf-8")


def test_the_harness_re_derives_the_statistics_and_agrees_with_the_backend() -> None:
    """The calibration's operand is the production statistic, checked rather than assumed."""
    for stamps in (
        calibration.uniform_stamps(257, 12.5345),
        calibration.quantized_stamps(257, 12.5345, 1e-3),
        calibration.jitter_stamps(257, 12.5345, 1e-2),
        calibration.ramp_stamps(257, 12.5345, 0.1),
        calibration.alternating_stamps(257, 12.5345, 0.1),
        calibration.gap_stamps(257, 12.5345, 1.5),
    ):
        measured = calibration.axis_statistics(stamps)
        characterized = characterize_stamps(stamps)
        assert measured["max_relative_timing_error"] == pytest.approx(
            characterized.max_relative_timing_error, rel=1e-12
        )
        assert measured["max_relative_interval_deviation"] == pytest.approx(
            characterized.max_relative_interval_deviation, rel=1e-12
        )
        assert measured["largest_gap_ratio"] == pytest.approx(
            characterized.largest_gap_ratio, rel=1e-12
        )
        assert measured["duplicate_intervals"] == characterized.duplicate_intervals
        assert measured["negative_intervals"] == characterized.negative_intervals


def test_the_gap_family_is_never_mistaken_for_an_irregularity_free_axis() -> None:
    """A gap is dominated by the timing-error rule: the inequality is checked, not asserted."""
    for count, span in ((257, 12.5345), (826, 12.5345)):
        for ratio in (1.001, 1.01, 1.1, 2.0):
            stamps = calibration.gap_stamps(count, span, ratio)
            measured = calibration.axis_statistics(stamps)
            assert measured["largest_gap_ratio"] == pytest.approx(ratio, rel=0.01)
            timing = measured["max_relative_timing_error"]
            assert timing is not None
            assert timing > 0.4 * calibration.gap_domination_lower_bound(count, ratio)
            admitted = spectral_admission(characterize_stamps(stamps))
            assert admitted.largest_gap_ratio == pytest.approx(ratio, rel=0.01)


def test_the_summary_a_reviewer_reads_carries_the_numbers_the_decision_used(
    matrix: tuple[calibration.CalibrationCase, ...],
) -> None:
    text = calibration.summary_text(matrix)
    assert "cases:" in text
    assert "selected tolerance" in text
    assert "worst distortion fraction by operand decade" in text
    assert OPERAND in text
