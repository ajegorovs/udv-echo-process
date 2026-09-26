"""The SA2 target layer: the two refusals that must never collapse into one verdict.

The load-bearing case is the E128 geometry: the estimator is **admitted** for it and 8.333 Hz is
**not supported** by it, because mathematical Nyquist is 5.73 Hz. The opposite pairing is a
ramped E20 axis: 8.333 Hz is inside its band and the estimator refused the axis. Both are
asserted here on the same target, because a single ``unsupported`` boolean would make them the
same answer, and they are different scientific statements - one about the instrument's
bandwidth, one about a defective recording.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_spectral_admission import spectral_admission
from udv_echo_process.analysis.sparse_spectral_support import (
    characterize_stamps,
    one_sided_frequency_grid,
)
from udv_echo_process.analysis.sparse_target_support import (
    BIN_EDGE_TOLERANCE_BINS,
    CELL_RULE,
    CYCLES_ROLE,
    SpectralSupportError,
    band_support,
    frequency_cell,
    target_frequency_support,
)


def uniform(count: int, span_s: float) -> np.ndarray:
    """An exact uniform axis of ``count`` samples spanning ``span_s``."""
    return np.linspace(0.0, span_s, count)


def ramped(count: int, span_s: float, amount: float) -> np.ndarray:
    """A uniform axis whose intervals run fast early and slow late: an unadmitted axis."""
    interval = span_s / (count - 1)
    half = (count - 1) // 2
    errors = np.concatenate((np.full(half, amount), np.full(count - 1 - half, -amount)))
    return np.concatenate(([0.0], np.cumsum(interval * (1.0 + errors))))


def verdict(count: int, span_s: float):
    """The admission of an exact uniform axis of the given geometry."""
    return spectral_admission(characterize_stamps(uniform(count, span_s)))


def test_a_target_inside_the_band_on_an_admitted_axis_is_supported() -> None:
    admission = verdict(536, 11.98)
    result = target_frequency_support(admission, 1.0, label="recurrence-1hz")
    assert result.band_supported is True
    assert result.analysis_supported is True
    assert result.supported is True
    assert result.target_label == "recurrence-1hz"
    assert result.band_reason in result.reason
    assert "inside bin" in result.reason
    assert "the estimator is admitted" in result.reason
    assert result.nyquist_hz is not None and result.nyquist_hz > 22.0
    assert result.frequency_resolution_hz is not None
    assert result.duration_resolution_scale_hz is not None
    assert result.frequency_resolution_hz != result.duration_resolution_scale_hz
    assert result.actual_span_s == pytest.approx(11.98)
    assert result.cycles_in_view == pytest.approx(11.98)


def test_the_rotor_reference_below_nyquist_on_a_slower_axis_is_supported() -> None:
    """The E64-like geometry: 8.333 Hz is inside a 10.2 Hz Nyquist band."""
    admission = verdict(257, 12.5345)
    result = target_frequency_support(admission, 25.0 / 3.0, label="rotor-8.333hz")
    assert result.nyquist_hz is not None and result.nyquist_hz > 10.0
    assert result.supported is True
    assert result.cycles_in_view is not None and result.cycles_in_view > 100.0
    assert result.prospective_bin == result.resolution_bins_to_target


def test_the_e128_geometry_admits_the_estimator_and_refuses_the_target() -> None:
    """The plan's own E128 x 8.333 Hz case: two verdicts, one axis, no collapse."""
    admission = verdict(144, 12.5345)
    assert admission.admitted is True, "the axis is regular enough to measure at all"
    result = target_frequency_support(admission, 25.0 / 3.0)
    assert result.nyquist_hz is not None
    assert result.nyquist_hz == pytest.approx(5.7043, abs=1e-3)
    assert result.band_supported is False
    assert result.analysis_supported is True
    assert result.supported is False
    assert result.reason == result.band_reason
    assert "at or above this axis's Nyquist frequency" in result.reason
    # Above Nyquist there is no bin to land on: the nearest *existing* bin is the top one, and
    # the offset states how far above it the target is - more than half a bin, which is the
    # evidence that the grid has no cell for this target.
    assert result.prospective_bin == 72
    assert result.bin_offset_bins is not None and result.bin_offset_bins > 30.0
    assert result.bin_offset_bins > 0.5


def test_an_unadmitted_axis_inside_its_band_refuses_for_the_other_reason() -> None:
    """The plan's second case: a real band, a defective recording."""
    characterization = characterize_stamps(ramped(560, 12.5345, 0.1))
    admission = spectral_admission(characterization)
    assert admission.admitted is False
    assert characterization.nyquist_hz is not None and characterization.nyquist_hz > 10.0
    result = target_frequency_support(admission, 25.0 / 3.0)
    assert result.band_supported is True, "the band is not the problem with this axis"
    assert result.analysis_supported is False
    assert result.supported is False
    assert result.reason == result.analysis_reason
    assert "refused the timestamp grid" in result.reason
    assert result.reason != result.band_reason


def test_a_target_exactly_at_nyquist_is_refused_and_is_not_an_error() -> None:
    admission = verdict(257, 12.5345)
    nyquist = admission.characterization.nyquist_hz
    assert nyquist is not None
    result = target_frequency_support(admission, nyquist)
    assert result.supported is False
    assert result.band_supported is False
    assert "strictly below" in result.reason
    assert result.prospective_bin is not None, "the nearest bin is still reported"


def test_a_target_between_the_top_bin_and_nyquist_on_an_odd_grid() -> None:
    """Odd length: no bin sits at Nyquist, and the top bin's cell still reaches it."""
    admission = verdict(257, 12.5345)
    characterization = admission.characterization
    top = characterization.nyquist_hz - 0.25 * characterization.frequency_resolution_hz
    result = target_frequency_support(admission, top)
    assert result.nyquist_represented is False
    assert result.band_supported is True
    assert result.prospective_bin == characterization.profiles // 2
    assert result.bin_offset_bins == pytest.approx(0.25)
    assert result.cell_high_hz == pytest.approx(characterization.nyquist_hz)


def test_an_even_grid_represents_nyquist_with_a_bin_and_an_odd_one_does_not() -> None:
    even = target_frequency_support(verdict(144, 12.5345), 5.0)
    odd = target_frequency_support(verdict(145, 12.5345), 5.0)
    assert even.nyquist_represented is True
    assert odd.nyquist_represented is False
    assert even.band_supported is True and odd.band_supported is True


def test_a_target_at_a_bin_centre_and_halfway_between_two_bins() -> None:
    admission = verdict(536, 11.98)
    spacing = admission.characterization.frequency_resolution_hz
    assert spacing is not None
    centred = target_frequency_support(admission, 12 * spacing)
    assert centred.prospective_bin == 12
    assert centred.bin_offset_bins == pytest.approx(0.0)
    assert centred.bin_offset_hz == pytest.approx(0.0)
    assert centred.supported is True
    halfway = target_frequency_support(admission, 12.5 * spacing)
    assert halfway.prospective_bin == 13, "the tie goes to the upper bin, deterministically"
    assert halfway.bin_offset_bins == pytest.approx(-0.5)
    assert halfway.supported is True, "the target sits on the cell edge and inside the cell"


def test_the_dc_adjacent_cell_and_the_last_cell_are_closed_at_the_physical_edges() -> None:
    """No cell edge reads a bin that does not exist, in either parity."""
    for count in (256, 257):
        characterization = characterize_stamps(uniform(count, 12.5345))
        grid = one_sided_frequency_grid(count, float(characterization.effective_sample_rate_hz))
        spacing = float(grid["delta_f_hz"])
        lowest = frequency_cell(0, grid=grid)
        assert lowest == (0.0, pytest.approx(0.5 * spacing))
        highest = frequency_cell(int(grid["bins"]) - 1, grid=grid)
        assert highest[1] == pytest.approx(float(grid["nyquist_hz"]))
        assert highest[0] < highest[1]
        interior = frequency_cell(5, grid=grid)
        assert interior == (
            pytest.approx(4.5 * spacing),
            pytest.approx(5.5 * spacing),
        )
    with pytest.raises(SpectralSupportError, match="outside a one-sided grid"):
        frequency_cell(999, grid=one_sided_frequency_grid(64, 12.0))


def test_the_dc_adjacent_target_is_inside_the_second_cell_not_the_dc_cell() -> None:
    admission = verdict(536, 11.98)
    spacing = admission.characterization.frequency_resolution_hz
    assert spacing is not None
    result = target_frequency_support(admission, 0.5 * spacing)
    assert result.prospective_bin == 1
    assert result.cell_low_hz == pytest.approx(0.5 * spacing)
    assert result.cell_low_hz is not None
    assert result.supported is True


def test_a_few_cycles_are_reported_and_never_refused() -> None:
    """Cycle count is an interpretation diagnostic with no threshold, on purpose."""
    admission = verdict(32, 2.0)
    result = target_frequency_support(admission, 1.0)
    assert result.cycles_in_view == pytest.approx(2.0)
    assert result.supported is True, "two cycles is a weak reading, not an unsupported axis"
    assert "never refuses" in CYCLES_ROLE
    assert "not unsupported" in CYCLES_ROLE


def test_a_target_that_is_not_a_frequency_is_an_error_not_a_verdict() -> None:
    admission = verdict(536, 11.98)
    for bad in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(SpectralSupportError, match="positive finite"):
            target_frequency_support(admission, bad)
        with pytest.raises(SpectralSupportError, match="positive finite"):
            band_support(admission.characterization, bad)


def test_the_standalone_band_question_agrees_with_the_folded_verdict() -> None:
    admission = verdict(144, 12.5345)
    characterization = admission.characterization
    for target in (1.0, 5.0, 25.0 / 3.0, 40.0):
        assert band_support(characterization, target) is target_frequency_support(
            admission, target
        ).band_supported


def test_asking_about_a_target_does_not_change_the_admission() -> None:
    """Admission is target-independent, asserted from the other side as well."""
    admission = verdict(144, 12.5345)
    before = admission.model_dump()
    target_frequency_support(admission, 25.0 / 3.0)
    target_frequency_support(admission, 1.0)
    assert admission.admitted is True
    assert admission.model_dump() == before
    assert BIN_EDGE_TOLERANCE_BINS > 0.0
    assert "fictitious" in CELL_RULE or "does not exist" in CELL_RULE
