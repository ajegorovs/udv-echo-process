"""The SA2 timebase layer: what an axis publishes, including what it refuses to invent.

Four groups:

- **the three definitions**, pinned arithmetically rather than by example: ``span``,
  ``dt_eff = span / (N - 1)``, ``fs_eff = 1 / dt_eff``, and ``delta_f = fs_eff / N`` as a
  quantity that is *not* ``1 / span``;
- **the degenerate axes**, where the point of the group is that every undefined field is
  ``None`` and never ``0.0``, and that a backwards axis has its rates withheld rather than
  published as negative sample rates;
- **the two timestamp statistics**, which are asserted to be different numbers measuring
  different things, on an axis built so that they cannot be confused;
- **the grid and its cells**, including the endpoint rules that have no neighbour to read.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_spectral_support import (
    SpectralSupportError,
    TimebaseCharacterization,
    characterize_stamps,
    one_sided_frequency_grid,
)


def uniform(count: int, span_s: float) -> np.ndarray:
    """An exact uniform axis of ``count`` samples spanning ``span_s``."""
    return np.linspace(0.0, span_s, count)


def test_an_exact_uniform_axis_has_no_pathology_and_the_definitions_agree() -> None:
    count, span = 145, 11.98
    result = characterize_stamps(uniform(count, span))
    interval = span / (count - 1)
    assert result.profiles == count
    assert result.start_s == 0.0
    assert result.end_s == span
    assert result.span_s == pytest.approx(span)
    assert result.full_span_interval_s == pytest.approx(interval)
    assert result.effective_sample_rate_hz == pytest.approx(1.0 / interval)
    assert result.effective_sample_rate_hz == pytest.approx((count - 1) / span)
    assert result.nyquist_hz == pytest.approx(0.5 / interval)
    assert result.median_interval_s == pytest.approx(interval)
    assert result.interval_min_s == pytest.approx(interval)
    assert result.interval_max_s == pytest.approx(interval)
    assert result.interval_iqr_s == pytest.approx(0.0)
    assert result.max_relative_timing_error == pytest.approx(0.0, abs=1e-12)
    assert result.max_relative_interval_deviation == pytest.approx(0.0, abs=1e-12)
    assert result.largest_gap_ratio == pytest.approx(1.0)
    assert result.duplicate_intervals == 0
    assert result.negative_intervals == 0
    assert result.strictly_increasing is True


def test_the_bin_spacing_is_not_the_observation_duration_scale() -> None:
    count, span = 257, 12.5345
    result = characterize_stamps(uniform(count, span))
    rate = result.effective_sample_rate_hz
    assert rate is not None
    spacing = result.frequency_resolution_hz
    scale = result.duration_resolution_scale_hz
    assert spacing is not None and scale is not None
    assert spacing == pytest.approx(rate / count)
    assert spacing == pytest.approx((count - 1) / (count * span))
    assert scale == pytest.approx(1.0 / span)
    # The two are close and are not equal: the difference is exactly the (N-1)/N factor.
    assert spacing != scale
    assert spacing == pytest.approx(scale * (count - 1) / count)
    assert 0.99 < spacing / scale < 1.0


def test_a_single_profile_has_no_interval_rate_or_nyquist() -> None:
    result = characterize_stamps(np.array([4.25]))
    assert result.profiles == 1
    assert result.start_s == pytest.approx(4.25)
    assert result.end_s == pytest.approx(4.25)
    assert result.span_s == pytest.approx(0.0)
    for undefined in (
        result.median_interval_s,
        result.median_interval_rate_hz,
        result.full_span_interval_s,
        result.effective_sample_rate_hz,
        result.nyquist_hz,
        result.frequency_resolution_hz,
        result.duration_resolution_scale_hz,
        result.interval_min_s,
        result.interval_max_s,
        result.interval_iqr_s,
        result.max_relative_interval_deviation,
        result.max_relative_timing_error,
        result.largest_gap_ratio,
    ):
        assert undefined is None
    assert result.strictly_increasing is None, "no interval exists to be increasing"
    assert result.duplicate_intervals == 0 and result.negative_intervals == 0


def test_an_empty_axis_is_characterized_as_empty_rather_than_as_zero() -> None:
    result = characterize_stamps(np.array([]))
    assert result.profiles == 0
    assert result.start_s is None and result.end_s is None and result.span_s is None
    assert result.effective_sample_rate_hz is None
    assert result.nyquist_hz is None
    assert result.frequency_resolution_hz is None
    assert result.strictly_increasing is None


def test_two_profiles_are_enough_for_an_interval_and_nothing_more() -> None:
    result = characterize_stamps(np.array([0.0, 0.5]))
    assert result.profiles == 2
    assert result.median_interval_s == pytest.approx(0.5)
    assert result.median_interval_rate_hz == pytest.approx(2.0)
    assert result.full_span_interval_s == pytest.approx(0.5)
    assert result.effective_sample_rate_hz == pytest.approx(2.0)
    assert result.nyquist_hz == pytest.approx(1.0)
    assert result.frequency_resolution_hz == pytest.approx(1.0)
    assert result.duration_resolution_scale_hz == pytest.approx(2.0)
    assert result.max_relative_timing_error == pytest.approx(0.0)
    assert result.strictly_increasing is True


def test_a_quantized_axis_differs_from_uniform_without_being_refused() -> None:
    """The committed recordings' own pathology: stamps rounded to a 1e-4 s quantum."""
    span, count, quantum = 12.5345, 560, 1e-4
    exact = uniform(count, span)
    rounded = np.round(exact / quantum) * quantum
    result = characterize_stamps(rounded)
    deviation = result.max_relative_interval_deviation
    timing = result.max_relative_timing_error
    assert deviation is not None and timing is not None
    assert deviation > 0.0 and timing > 0.0
    # The quantum is 0.1 ms and the interval 22.4 ms: the interval statistic sees one quantum,
    # and the timing error cannot exceed it however many intervals are rounded.
    interval = span / (count - 1)
    assert deviation == pytest.approx(quantum / interval, rel=0.01)
    assert timing <= quantum / interval
    assert result.strictly_increasing is True
    assert result.duplicate_intervals == 0


def test_duplicate_stamps_are_counted_and_still_characterized() -> None:
    stamps = np.array([0.0, 0.1, 0.1, 0.2, 0.3])
    result = characterize_stamps(stamps)
    assert result.duplicate_intervals == 1
    assert result.strictly_increasing is False
    assert result.negative_intervals == 0
    # Characterized, not repaired: the axis is described exactly as stored.
    assert result.span_s == pytest.approx(0.3)
    assert result.median_interval_s == pytest.approx(0.1)
    assert result.interval_min_s == pytest.approx(0.0)
    assert result.duplicate_intervals == 1


def test_a_decreasing_axis_is_not_sorted_and_its_rates_are_withheld() -> None:
    stamps = np.array([0.3, 0.2, 0.1, 0.0])
    result = characterize_stamps(stamps)
    assert result.negative_intervals == 3
    assert result.strictly_increasing is False
    assert result.span_s == pytest.approx(-0.3), "the span is negative and is reported as it is"
    assert result.median_interval_s == pytest.approx(-0.1)
    for withheld in (
        result.effective_sample_rate_hz,
        result.nyquist_hz,
        result.frequency_resolution_hz,
        result.max_relative_timing_error,
    ):
        assert withheld is None, "a negative sample rate is not a sample rate"


def test_an_isolated_gap_is_measured_as_a_ratio_and_moves_the_timing_error() -> None:
    """One interval longer than the others: the gap statistic and the accumulation it causes."""
    count, span, ratio = 41, 12.0, 1.5
    intervals = np.full(count - 1, (span / (count - 1)))
    intervals[3] *= ratio
    intervals[4] *= 1.0 - (ratio - 1.0) / (count - 3)
    stamps = np.concatenate(([0.0], np.cumsum(intervals)))
    result = characterize_stamps(stamps)
    assert result.largest_gap_ratio is not None
    assert result.largest_gap_ratio > 1.4
    timing = result.max_relative_timing_error
    assert timing is not None and timing > 0.1, "an isolated gap is not a bounded event"


def test_the_median_interval_and_the_adopted_interval_are_different_quantities() -> None:
    """A two-level axis: the median lands on one level and ``span / (N - 1)`` on neither.

    The axis carries an *odd* number of intervals on purpose. With an even count the median of a
    two-level axis is the average of the two levels, which is the adopted interval again, and the
    quantity the design's own definition refers to would happen to agree with the average. The
    committed geometries are the two cases: 825 intervals on E8 (odd) and 256 on E64 (even).
    """
    count, span = 256, 12.5345
    interval = span / (count - 1)
    signs = np.where(np.arange(count - 1) % 2 == 0, 1.0, -1.0)
    stamps = np.concatenate(([0.0], np.cumsum(interval * (1.0 + 0.1 * signs))))
    result = characterize_stamps(stamps)
    adopted = float(stamps[-1] - stamps[0]) / (count - 1)
    assert result.median_interval_s is not None
    assert result.full_span_interval_s == pytest.approx(adopted)
    assert result.median_interval_s != pytest.approx(adopted)
    assert abs(result.median_interval_s / adopted - 1.0) > 0.05
    assert result.median_interval_rate_hz == pytest.approx(1.0 / result.median_interval_s)
    assert result.effective_sample_rate_hz == pytest.approx(1.0 / adopted)
    assert result.median_interval_rate_hz != pytest.approx(result.effective_sample_rate_hz)


def test_the_two_timestamp_statistics_rank_two_axes_the_opposite_way_round() -> None:
    """Why the design's interval deviation is a diagnostic and the timing error is the operand.

    Two axes are built with *nearly the same* interval deviation. One stores the error as an
    alternating half-sample jog, whose accumulated position error stays bounded; the other ramps
    the error up through half the record and back, whose accumulated error does not. The interval
    deviation calls the ramping axis the worse of the two, and the timing error calls it worse by
    a factor of hundreds - and only the second statement survives being checked against a
    measurement of what a uniform-grid transform does with each axis.
    """
    count, span = 826, 12.5345
    interval = span / (count - 1)
    deviation = 0.1
    alternating = np.where(np.arange(count - 1) % 2 == 0, 1.0, -1.0) * deviation
    ramping = np.concatenate(
        (
            np.full((count - 1) // 2, deviation),
            np.full(count - 1 - (count - 1) // 2, -deviation),
        )
    )
    jog = characterize_stamps(
        np.concatenate(([0.0], np.cumsum(interval * (1.0 + alternating))))
    )
    ramp = characterize_stamps(np.concatenate(([0.0], np.cumsum(interval * (1.0 + ramping)))))
    assert jog.max_relative_interval_deviation is not None
    assert ramp.max_relative_interval_deviation is not None
    assert jog.max_relative_timing_error is not None
    assert ramp.max_relative_timing_error is not None
    # Nearly the same interval deviation, by either ordering ...
    assert 0.5 < ramp.max_relative_interval_deviation / jog.max_relative_interval_deviation < 2.0
    # ... and the interval statistic calls the *ramp* the worse axis ...
    assert ramp.max_relative_interval_deviation > jog.max_relative_interval_deviation
    # ... while the timing error is two and a half orders of magnitude larger for the ramp, and
    # the bounded jog is the one that accumulates nothing at all.
    assert ramp.max_relative_timing_error > 100.0 * jog.max_relative_timing_error
    assert ramp.max_relative_timing_error > 10.0
    assert jog.max_relative_timing_error < 0.2


def test_the_grid_of_an_even_length_transform_represents_nyquist() -> None:
    count, span = 144, 12.5345
    result = characterize_stamps(uniform(count, span))
    grid = one_sided_frequency_grid(count, float(result.effective_sample_rate_hz))
    frequencies = grid["frequencies_hz"]
    assert grid["bins"] == count // 2 + 1
    assert grid["nyquist_is_represented"] is True
    assert grid["top_bin_hz"] == pytest.approx(grid["nyquist_hz"])
    assert frequencies[0] == 0.0
    assert frequencies[-1] == pytest.approx(float(result.nyquist_hz))
    assert np.all(np.diff(frequencies) > 0.0)
    assert grid["delta_f_hz"] == pytest.approx(result.frequency_resolution_hz)


def test_the_grid_of_an_odd_length_transform_does_not() -> None:
    count, span = 145, 12.5345
    result = characterize_stamps(uniform(count, span))
    grid = one_sided_frequency_grid(count, float(result.effective_sample_rate_hz))
    assert grid["bins"] == (count - 1) // 2 + 1
    assert grid["nyquist_is_represented"] is False
    assert float(grid["top_bin_hz"]) < float(grid["nyquist_hz"])
    assert float(grid["top_bin_hz"]) == pytest.approx(
        float(grid["nyquist_hz"]) - 0.5 * float(grid["delta_f_hz"])
    )


def test_the_grid_refuses_a_count_or_a_rate_it_cannot_be_a_grid_of() -> None:
    with pytest.raises(SpectralSupportError, match="at least one sample"):
        one_sided_frequency_grid(0, 44.0)
    with pytest.raises(SpectralSupportError, match="positive finite"):
        one_sided_frequency_grid(64, 0.0)
    with pytest.raises(SpectralSupportError, match="positive finite"):
        one_sided_frequency_grid(64, math.inf)


def test_an_axis_that_is_not_a_finite_one_dimensional_series_is_refused() -> None:
    with pytest.raises(SpectralSupportError, match="finite"):
        characterize_stamps(np.array([0.0, math.nan, 0.2]))
    with pytest.raises(SpectralSupportError, match="one-dimensional"):
        characterize_stamps(np.zeros((4, 3)))
    with pytest.raises(SpectralSupportError, match="real"):
        characterize_stamps(np.array([0.0, 1.0 + 2.0j]))


def test_a_characterization_without_a_view_says_so_rather_than_inventing_provenance() -> None:
    """Off a view there is no source identity to claim, and the field is ``None``, not a guess."""
    stamps = uniform(64, 6.3)
    bare = characterize_stamps(stamps)
    assert isinstance(bare, TimebaseCharacterization)
    assert bare.provenance is None
    assert bare == characterize_stamps(stamps), "characterization is deterministic"
