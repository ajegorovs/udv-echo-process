"""The SA2 committed-data layer: 104 recording x view records, and the facts they must keep.

Two of these are hard facts no calibration may move: the E128 recordings can never carry the
8.333 Hz rotor reference (mathematical Nyquist is 5.73 Hz on them), and every committed recording
can carry 1 Hz. They are asserted over the *whole* committed set rather than on a sample of it,
because a capability claim is exactly the kind of claim that is true of the recordings someone
happened to check.

The third is the character of the committed irregularity, asserted in seconds rather than in the
design's relative statistic: the committed stamps are a logger's clock quantized to 0.1 ms, so
their timing error is *bounded by that quantum* rather than accumulating. That is why a
tolerance calibrated on accumulating perturbations admits them, and it is the reason the
calibration's families include the accumulating ones at all.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_gate_stats as sgs
from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import SparseView, view_provenance
from udv_echo_process.analysis.sparse_spectral_admission import (
    SPECTRAL_UNIFORMITY_TOL,
    spectral_admission,
)
from udv_echo_process.analysis.sparse_spectral_capability import (
    CAPABILITY_VIEWS,
    PROBE_TARGETS,
    committed_spectral_capability,
)
from udv_echo_process.analysis.sparse_spectral_support import characterize_timebase

#: One sitting's own paths, as the gate-statistics tests resolve them.
ROOT = Path(__file__).resolve().parent.parent
LIVE2_ROOT = ROOT / "data" / "sparse-mixer-live-2"
LIVE2_PLAN = ROOT / "examples" / "sparse-mixer-live-2" / "run-plan.json"

#: The logger's timestamp quantum, in seconds: every committed interval deviation is one of these.
TIMESTAMP_QUANTUM_S = 1e-4

ROTOR_REFERENCE_HZ = 25.0 / 3.0
RECURRENCE_HZ = 1.0
RECURRENCE_LABEL = "recurrence-1hz"
ROTOR_LABEL = "rotor-8.333hz"


@pytest.fixture(scope="module")
def capability():
    """Every committed live recording, on both views (about three seconds)."""
    return committed_spectral_capability()


@pytest.fixture(scope="module")
def one_sitting_views():
    """One sitting's views, built here rather than taken from the sweep's records.

    A capability record carries scalars on purpose - it is not a data container - so this fixture
    is what lets a test reach the *stamps* of the same recordings, and it is what makes the two
    paths checkable against each other.
    """
    decoding = decode_pass(LIVE2_ROOT, plan_path=LIVE2_PLAN)
    views = []
    for point in decoding.points:
        views.append(
            sgs.primary_view(point, window_s=decoding.window_s, support_mm=decoding.support_mm)
        )
        views.append(sgs.full_record_view(point, support_mm=decoding.support_mm))
    return decoding, tuple(views)


def test_the_row_set_is_every_committed_recording_on_both_views(capability) -> None:
    """104 records: 52 recordings x 2 views, not 52 generic rows."""
    assert len(capability) == 104
    assert len({(row.pass_name, row.job, row.point_label) for row in capability}) == 52
    assert len({row.pass_name for row in capability}) == 2
    counts = {}
    for row in capability:
        counts[(row.pass_name, row.view)] = counts.get((row.pass_name, row.view), 0) + 1
    assert sorted(counts.values()) == [26, 26, 26, 26]
    views = {row.view for row in capability}
    assert views == set(CAPABILITY_VIEWS)
    assert all(row.source_sha256 for row in capability)
    assert all(row.profiles > 0 for row in capability)


def test_primary_and_full_record_are_not_flattened_together(capability) -> None:
    """The two views differ in span and resolution on every recording, and are kept apart."""
    pairs = {}
    for row in capability:
        pairs.setdefault((row.pass_name, row.job, row.point_label), []).append(row)
    assert len(pairs) == 52
    for rows in pairs.values():
        assert len(rows) == 2
        primary = next(row for row in rows if row.view is SparseView.PRIMARY)
        whole = next(row for row in rows if row.view is SparseView.FULL_RECORD)
        assert whole.profiles > primary.profiles
        assert whole.span_s > primary.span_s
        assert whole.frequency_resolution_hz < primary.frequency_resolution_hz
        # The adopted rate is ``span / (N - 1)`` *of its own window*, so the same recording's two
        # views differ by the stamp quantum's effect on a shorter span - about 5e-6 relative, and
        # small enough that neither view is a different instrument, but not zero, and not asserted
        # to be zero here because that would be asserting away the definition.
        assert whole.nyquist_hz != primary.nyquist_hz
        assert whole.nyquist_hz == pytest.approx(primary.nyquist_hz, rel=1e-4)
        assert abs(whole.nyquist_hz / primary.nyquist_hz - 1.0) > 0.0
        assert primary.declared_window_s == pytest.approx(12.0)


def test_the_bin_spacing_is_the_effective_rate_over_the_count_and_not_one_over_the_span(
    capability,
) -> None:
    """The design correction, checked on all 104 committed views rather than in prose."""
    for row in capability:
        characterization = row.characterization
        rate = characterization.effective_sample_rate_hz
        count = characterization.profiles
        span = characterization.span_s
        assert rate is not None and span is not None
        assert characterization.frequency_resolution_hz == pytest.approx(rate / count)
        assert characterization.duration_resolution_scale_hz == pytest.approx(1.0 / span)
        assert rate == pytest.approx((count - 1) / span)
        assert characterization.frequency_resolution_hz != pytest.approx(
            characterization.duration_resolution_scale_hz
        )
        assert characterization.frequency_resolution_hz == pytest.approx(
            characterization.duration_resolution_scale_hz * (count - 1) / count
        )


def test_the_committed_irregularity_is_a_bounded_quantum_and_never_an_accumulating_warp(
    capability, one_sitting_views
) -> None:
    """In seconds, off the stamps themselves: a clock quantum, not an accumulating warp.

    This is the fact that makes the committed set admissible under a tolerance calibrated on
    *accumulating* perturbations, and it is measured from each view's own time axis rather than
    from either of the design's relative statistics. Two quanta is the bound, not one: rounding
    fixes the span, and the adopted interval inherits that rounding, so the distance between a
    stamp and the grid its own span implies carries both errors.
    """
    decoding, views = one_sitting_views
    worst = 0.0
    for view in views:
        stamps = np.asarray(view.time_s, dtype=float)
        assert np.allclose(stamps / TIMESTAMP_QUANTUM_S, np.round(stamps / TIMESTAMP_QUANTUM_S)), (
            "a committed stamp is not a whole number of 0.1 ms, so the quantum is not 0.1 ms"
        )
        interval = (stamps[-1] - stamps[0]) / (stamps.size - 1)
        grid = stamps[0] + interval * np.arange(stamps.size)
        worst = max(worst, float(np.max(np.abs(stamps - grid))))
    assert worst > 0.5 * TIMESTAMP_QUANTUM_S, "the quantum must actually be reached"
    assert worst <= 2.05 * TIMESTAMP_QUANTUM_S, (
        f"a committed view sits {worst} s off its own uniform grid, which two 0.1 ms quanta "
        "cannot explain"
    )
    assert decoding.window_s == pytest.approx(12.0)
    for row in capability:
        assert row.max_timing_error_s is not None
        assert row.max_timing_error_s <= 2.05 * TIMESTAMP_QUANTUM_S
        assert row.max_relative_timing_error is not None
        assert row.max_relative_timing_error < 0.2 * SPECTRAL_UNIFORMITY_TOL
        assert row.max_timing_error_s == pytest.approx(
            row.max_relative_timing_error * row.effective_interval_s
        )
    assert max(row.largest_gap_ratio for row in capability) == pytest.approx(1.0, abs=1e-9), (
        "no committed recording has an isolated gap: its irregularity is quantization"
    )


def test_every_committed_view_is_admitted_by_the_calibrated_policy(capability) -> None:
    for row in capability:
        assert row.admitted is True, f"{row.pass_name}/{row.job}/{row.view}: {row.admission_reason}"
        assert row.failed_conditions == ()


def test_all_eight_e128_recordings_stay_band_refused_for_the_rotor_reference(capability) -> None:
    """The plan's hard fact, over both views and both sittings."""
    e128 = [row for row in capability if row.job == "emissions-128"]
    assert len(e128) == 16, "eight E128 recordings on two views"
    for row in e128:
        assert row.nyquist_hz is not None and row.nyquist_hz < ROTOR_REFERENCE_HZ
        entry = row.target(ROTOR_LABEL)
        assert entry.band_supported is False
        assert entry.analysis_supported is True, "the estimator is admitted; only the band is not"
        assert entry.supported is False
        assert "Nyquist" in entry.reason


def test_the_rotor_reference_is_band_supported_on_every_other_committed_view(capability) -> None:
    others = [row for row in capability if row.job != "emissions-128"]
    assert len(others) == 88
    for row in others:
        entry = row.target(ROTOR_LABEL)
        assert entry.nyquist_hz is not None and entry.nyquist_hz > ROTOR_REFERENCE_HZ
        assert entry.band_supported is True
        assert entry.supported is True
        assert "at or above this axis's Nyquist" not in entry.reason


def test_one_hertz_is_band_supported_and_supported_across_the_whole_committed_set(
    capability,
) -> None:
    """The plan's other hard fact: 1 Hz is inside every committed band, on both views."""
    assert len(capability) == 104
    for row in capability:
        entry = row.target(RECURRENCE_LABEL)
        assert entry.nyquist_hz is not None
        assert entry.nyquist_hz > 2.0 * RECURRENCE_HZ
        assert entry.band_supported is True
        assert entry.analysis_supported is True
        assert entry.supported is True
        assert entry.cycles_in_view is not None and entry.cycles_in_view > 10.0
    assert [label for label, _ in PROBE_TARGETS] == [RECURRENCE_LABEL, ROTOR_LABEL]


def test_a_characterization_from_a_committed_view_carries_that_view_s_provenance(
    capability, one_sitting_views
) -> None:
    """SA1's provenance is reused, not remade, and the direct path agrees with the sweep."""
    decoding, views = one_sitting_views
    rows = {
        (row.source_sha256, row.view): row
        for row in capability
        if row.pass_name == "sparse-mixer-live-2"
    }
    assert len(rows) == 52
    for view in views:
        characterization = characterize_timebase(view)
        assert characterization.provenance is not None
        assert characterization.provenance == view_provenance(view)
        assert characterization.provenance.declared_window_s == view.declared_window_s
        assert characterization.profiles == view.values.shape[0]
        assert characterization.profiles == view_provenance(view).profiles
        assert characterization.span_s == pytest.approx(float(view.window_s))
        row = rows[(view_provenance(view).source_sha256, view.view)]
        assert row.characterization == characterization, (
            "the sweep and the direct path must characterize one view identically"
        )
        assert spectral_admission(characterization).admitted is True
    assert decoding.window_s == pytest.approx(12.0)


def test_the_effective_rate_is_the_adopted_interval_and_not_the_median_one(capability) -> None:
    """On the committed set the two differ by the timestamp quantum, and both are reported."""
    differing = 0
    for row in capability:
        characterization = row.characterization
        median_rate = characterization.median_interval_rate_hz
        rate = characterization.effective_sample_rate_hz
        assert median_rate is not None and rate is not None
        assert rate != median_rate
        if abs(rate / median_rate - 1.0) > 1e-6:
            differing += 1
    assert differing == len(capability), (
        "every committed view's median interval differs from the adopted one, which is the "
        "reason the rate is the adopted one"
    )

