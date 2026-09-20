"""Focused tests for the WP2 burst-length ladder (plan ``WP2``, burst axis).

Written RED first: ``analysis.burst_ladder``, its CLI verb and its four reviewer-visible
artefacts (``burst-levels.csv``, ``burst-pairs.csv``, ``burst-ladder.provenance.json``,
``figures/burst-ladder.png``) did not exist, so this module failed at import.

The tests pin the definitions the burst axis must not drift on: the ladder is the
``burst_len`` rows of ``manifest.csv`` (never a filename list); one common-duration view and
one common physical support serve every cross-level summary; native-grid gradient and
correlation length are computed before any alignment and pairs sample the shorter pulse's
grid at the longer pulse's own knots; every mean-profile effect is stated against the
committed WP1 screening_threshold; the full-record temporal view is matched across all 12 files and
compared to the temporal repeat floor the committed WP1 curves imply; and the
18-versus-20-cycle question is answered from the numbers rather than asserted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis.burst_ladder import (
    AXIS,
    DATASET_ROOT,
    FOCUS_PAIR_CYCLES,
    FOCUS_WINDOW_CYCLES,
    LEVEL_COLUMNS,
    NOMINAL_REVOLUTION_S,
    PAIR_COLUMNS,
    BurstLadderError,
    build_burst_ladder,
    largest_step,
    level_groups,
    select_level_rows,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
DATA_ROOT = ROOT / DATASET_ROOT
RELATIVE_MANIFEST = Path("reports/mixer-sensitivity-analysis/manifest.csv")
RELATIVE_ENVELOPE = Path(
    "reports/mixer-sensitivity-analysis/reference-repeat.provenance.json"
)
MANIFEST = ROOT / RELATIVE_MANIFEST
ENVELOPE = ROOT / RELATIVE_ENVELOPE
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

CYCLES = (2, 4, 6, 8, 12, 14, 16, 18, 20, 24, 28, 32)  # decoded order, as manifest.csv
#: 92 nominal revolutions at 500 RPM fit every recording (the shortest is burst_len/16.BDD at
#: 11.1051 s); every file carries the same 50-gate 1.85 mm grid, so the support is that grid.
COMMON_REVOLUTIONS, COMMON_WINDOW_S, WINDOW_PROFILES = 92, 11.04, 494
SUPPORT_MIN_MM, SUPPORT_MAX_MM, GATES_IN_SUPPORT = 10.1626666667, 100.8126666667, 50
ENVELOPE_MM_S = 19.37008103465545
PITCH_MM = 1.85
WORST_PAIR_ABS_MM_S = 44.03130014799165  # burst_len/4.BDD minus burst_len/28.BDD
FOCUS_ABS_MM_S = 11.751918176021  # burst_len/18.BDD minus burst_len/20.BDD
FLOOR_HF_SHARE_DIFFERENCE = 0.027913255720827812


@pytest.fixture(scope="module", autouse=True)
def _repository_root():
    """Run with the repository root as cwd, so relative artefact paths resolve."""
    previous = Path.cwd()
    os.chdir(ROOT)
    yield
    os.chdir(previous)


def _manifest(tmp_path: Path, mutator=None) -> Path:
    """Copy the committed manifest, optionally mutating rows, into ``tmp_path``."""
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if mutator is not None:
        rows = mutator(rows)
    path = tmp_path / "manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rebound_screening_threshold(tmp_path: Path, manifest: Path) -> Path:
    """The committed WP1 screening_threshold re-bound to a copied manifest's own hash."""
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    document["manifest"]["sha256"] = (
        f"sha256:{hashlib.sha256(manifest.read_bytes()).hexdigest()}"
    )
    path = tmp_path / "reference-repeat.provenance.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _replace(rows, relative, **cells):
    """The manifest rows with one relative path's cells replaced."""
    return [{**row, **cells} if row["relative_path"] == relative else row for row in rows]


def _decoded(relative: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A file's ``(values, time_s, gate_depths_mm)`` straight from the reader."""
    from udv_echo_process.io import load

    stream = load(DATA_ROOT / relative).recording.streams[0]
    return (
        np.asarray(stream.data.values, dtype=float),
        np.asarray(stream.data.time_s, dtype=float),
        np.asarray(stream.data.gate_depths_mm, dtype=float),
    )


def _window(relative: str) -> np.ndarray:
    """A file's common-duration window, derived here rather than by the module."""
    values, time_s, _depths = _decoded(relative)
    return values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9]


def _write(tmp_path: Path, name: str = "a"):
    from udv_echo_process.analysis.burst_ladder import write_burst_ladder

    return write_burst_ladder(
        DATASET_ROOT, tmp_path / name, manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE, analysis_commit=COMMIT,
    )


@pytest.fixture(scope="module")
def ladder():
    """The built ladder: 12 levels, the two matched views and 66 unordered pairs."""
    return build_burst_ladder(
        DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT
    )


def test_axis_artefact_names_and_manifest_selection() -> None:
    from udv_echo_process.analysis import burst_ladder as module

    assert (AXIS, FOCUS_WINDOW_CYCLES, FOCUS_PAIR_CYCLES) == ("burst_len", (16, 20), (18, 20))
    assert (module.LEVELS_NAME, module.PAIRS_NAME) == ("burst-levels.csv", "burst-pairs.csv")
    assert module.PROVENANCE_NAME == "burst-ladder.provenance.json"
    rows = select_level_rows(MANIFEST)
    assert [int(row["burst_length"]) for row in rows] == list(CYCLES)
    # Only the burst axis may reach the ladder, and never from a filename list.
    assert {row["axis"] for row in rows} == {AXIS}
    assert all(row["relative_path"].startswith("burst_len/") for row in rows)


def test_select_level_rows_refuses_a_bad_inventory(tmp_path) -> None:
    with pytest.raises(BurstLadderError, match="cannot read"):
        select_level_rows(tmp_path / "absent.csv")
    without = _manifest(tmp_path, lambda rows: [r for r in rows if r["axis"] != AXIS])
    with pytest.raises(BurstLadderError, match="no burst_len rows"):
        select_level_rows(without)
    undecoded = _manifest(
        tmp_path, lambda rows: _replace(rows, "burst_len/16.BDD", decode_error="boom")
    )
    with pytest.raises(BurstLadderError, match="decode_error"):
        select_level_rows(undecoded)
    duplicated = _manifest(tmp_path, lambda rows: rows + [rows[0]])
    with pytest.raises(BurstLadderError, match="exactly one"):
        select_level_rows(duplicated)
    for relative, cell, pattern in (
        ("burst_len/16.BDD", "", "integer cycle count"),
        ("burst_len/20.BDD", "0", "<= 0"),
    ):
        broken = _manifest(
            tmp_path,
            lambda rows, relative=relative, cell=cell: _replace(
                rows, relative, burst_length=cell
            ),
        )
        with pytest.raises(BurstLadderError, match=pattern):
            select_level_rows(broken)
    # A requested row that moved a setting other than the cycle count is refused by name.
    coupled = _manifest(tmp_path, lambda rows: _replace(rows, "burst_len/12.BDD", emit_power="high"))
    with pytest.raises(BurstLadderError, match="does not match the decoded"):
        select_level_rows(coupled)


def test_two_recordings_at_one_decoded_cycle_count_are_two_realizations_not_a_refusal(
    tmp_path,
) -> None:
    """R1: the old duplicate-key refusal was the defect - one decoded level, two named files."""
    manifest = _manifest(tmp_path, lambda rows: _replace(rows, "burst_len/14.BDD", burst_length="12"))
    groups = level_groups(manifest)
    at = next(group for group in groups if group.key == ("12",))
    assert at.realization_paths == ("burst_len/12.BDD", "burst_len/14.BDD")
    assert at.primary_path == "burst_len/12.BDD"
    assert at.in_ladder is True
    assert at.requested_paths == at.realization_paths
    assert len(select_level_rows(manifest)) == len(CYCLES) - 1


def test_the_reference_level_another_folder_realizes_is_recorded_for_the_rebuild(
    tmp_path,
) -> None:
    """R1: burst 10 is one eligible level realized by both reference recordings, never dropped."""
    groups = level_groups(MANIFEST)
    anchor = next(group for group in groups if group.key == (ANCHOR_CYCLES,))
    assert anchor.realization_paths == ANCHOR_PATHS
    assert anchor.requested_paths == ()
    assert anchor.in_ladder is False  # no burst_len row requests it: the §8.3 step 5 rebuild joins it
    assert [group.key for group in groups if not group.in_ladder] == [(ANCHOR_CYCLES,)]
    assert [int(row["burst_length"]) for row in select_level_rows(MANIFEST)] == list(CYCLES)
    # A requested row at that same decoded level joins the ladder, and the level is one level with
    # two names - the folder stopped mattering the moment the decoded cycle count was read.
    def relabel(rows):
        return [
            {**row, "axis": AXIS} if row["relative_path"] == ANCHOR_PATHS[1] else row
            for row in rows
        ]

    relabelled = level_groups(_manifest(tmp_path, relabel))
    joined = next(group for group in relabelled if group.key == (ANCHOR_CYCLES,))
    assert joined.in_ladder is True
    assert joined.primary_path == ANCHOR_PATHS[1]
    assert joined.realization_paths == ANCHOR_PATHS
    assert len(select_level_rows(_manifest(tmp_path, relabel))) == len(CYCLES) + 1


def test_the_ladder_carries_the_setting_based_selection_beside_its_levels(ladder) -> None:
    """Plan §8.3 step 2: the selection is recorded on the model; §8.3 step 5 renders it."""
    from udv_echo_process.analysis.burst_ladder import ELIGIBILITY, provenance_document

    assert ladder.eligibility == ELIGIBILITY
    assert [group.key for group in ladder.groups if group.in_ladder] == [
        (str(row["burst_length"]),) for row in select_level_rows(MANIFEST)
    ]
    assert [row["relative_path"] for row in ladder.levels] == [
        row["relative_path"] for row in select_level_rows(MANIFEST)
    ]
    # burst 10 is eligible evidence the committed ladder does not yet hold.
    assert [group.key for group in ladder.groups if not group.in_ladder] == [(ANCHOR_CYCLES,)]
    assert all(
        group.key_display == f"{group.key_fields[0]}={group.key[0]}" for group in ladder.groups
    )
    assert [group.ladder_label for group in ladder.groups] == ["burst"] * len(ladder.groups)
    assert "realizations" not in json.dumps(provenance_document(ladder))


def test_build_refuses_stale_hash_wrong_grid_coupled_ladder_or_unbound_screening_threshold(
    tmp_path,
) -> None:
    stale = _manifest(
        tmp_path, lambda rows: _replace(rows, "burst_len/18.BDD", gates="49")
    )
    with pytest.raises(BurstLadderError, match="stale inventory"):
        build_burst_ladder(DATASET_ROOT, stale, _rebound_screening_threshold(tmp_path, stale), analysis_commit=COMMIT)
    wrong = _manifest(
        tmp_path, lambda rows: _replace(rows, "burst_len/20.BDD", source_sha256="0" * 64)
    )
    with pytest.raises(BurstLadderError, match="sha256 mismatch"):
        build_burst_ladder(DATASET_ROOT, wrong, _rebound_screening_threshold(tmp_path, wrong), analysis_commit=COMMIT)
    with pytest.raises(BurstLadderError, match="cannot read the WP1 screening_threshold"):
        build_burst_ladder(
            DATASET_ROOT, RELATIVE_MANIFEST, tmp_path / "absent.json",
            analysis_commit=COMMIT,
        )
    changed = _manifest(
        tmp_path, lambda rows: _replace(rows, "burst_len/18.BDD", gates="49")
    )
    # The committed screening_threshold records the committed manifest's hash: an inventory with other
    # bytes must not be able to borrow its threshold.
    with pytest.raises(BurstLadderError, match="records manifest"):
        build_burst_ladder(DATASET_ROOT, changed, ENVELOPE, analysis_commit=COMMIT)


def test_the_ladder_audits_that_only_the_burst_length_moved() -> None:
    """A ladder whose companion setting moved must be refused, not credited to the burst."""
    from udv_echo_process.analysis.burst_ladder import (
        _require_clean_ofat,
    )

    entries = list(
        build_burst_ladder(
            DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT
        ).inputs
    )
    _require_clean_ofat(entries)  # the committed ladder is clean
    entries[-1] = entries[-1].model_copy(update={"emit_power": "high"})
    with pytest.raises(BurstLadderError, match="OFAT ladder"):
        _require_clean_ofat(entries)


def test_common_duration_view_and_common_support(ladder) -> None:
    from udv_echo_process.analysis.burst_ladder import PLAN_SUPPORT_MM

    common = ladder.common
    assert (common["nominal_rpm"], common["revolution_s"]) == pytest.approx(
        (500.0, NOMINAL_REVOLUTION_S)
    )
    assert (common["revolutions"], common["window_s"]) == pytest.approx(
        (COMMON_REVOLUTIONS, COMMON_WINDOW_S)
    )
    durations = [entry.duration_s for entry in ladder.inputs]
    assert common["revolutions"] == math.floor(min(durations) / NOMINAL_REVOLUTION_S)
    # Truncated per file by the recorded timestamps: the shortest record is
    # burst_len/16.BDD, so every level keeps exactly this many profiles.
    assert set(common["profiles_window"].values()) == {WINDOW_PROFILES}
    assert set(common["profiles_window"]) == {r.relative_path for r in ladder.inputs}
    assert (common["support_min_mm"], common["support_max_mm"]) == pytest.approx(
        (SUPPORT_MIN_MM, SUPPORT_MAX_MM), abs=1e-9
    )
    assert set(common["gates_in_support"].values()) == {GATES_IN_SUPPORT}
    # The plan's declared window is 10.163-96.743 mm; this support contains it.
    assert common["support_min_mm"] <= PLAN_SUPPORT_MM[0]
    assert common["support_max_mm"] >= PLAN_SUPPORT_MM[1]


def test_distributional_metrics_use_the_common_window_not_the_full_record(ladder) -> None:
    for cycles in (2, 18, 28):
        row = next(r for r in ladder.levels if r["cycles"] == cycles)
        window = _window(row["relative_path"])
        assert row["profiles_window"] == window.shape[0]
        assert (row["mean_mm_s"], row["rms_mm_s"], row["zero_fraction"]) == pytest.approx(
            (
                float(window.mean()),
                float(np.sqrt(np.mean(np.square(window)))),
                float(np.count_nonzero(window == 0.0) / window.size),
            )
        )
        means = window.mean(axis=0)
        assert row["robust_spread_mm_s"] == pytest.approx(
            float(np.percentile(means, 75.0) - np.percentile(means, 25.0))
        )


def test_level_rows_carry_native_grid_metrics_computed_before_any_alignment(ladder) -> None:
    from udv_echo_process.analysis._native_grid import (
        correlation_length,
        spatial_gradient,
    )

    row = next(r for r in ladder.levels if r["cycles"] == 16)
    values, time_s, depths = _decoded(row["relative_path"])
    means = values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9].mean(axis=0)
    gradient = spatial_gradient(depths, means)
    correlation = correlation_length(depths, means)
    assert row["pitch_mm"] == pytest.approx(float(np.diff(depths).mean()))
    assert (row["gradient_median_abs_mm_s_per_mm"], row["gradient_max_abs_mm_s_per_mm"])         == pytest.approx((gradient.median_abs_mm_s_per_mm, gradient.max_abs_mm_s_per_mm))
    assert row["correlation_length_mm"] == pytest.approx(correlation.length_mm)
    assert row["correlation_length_over_pitch"] == pytest.approx(
        correlation.length_mm / row["pitch_mm"]
    )


def test_the_temporal_grid_is_matched_across_every_file(ladder) -> None:
    from udv_echo_process.analysis.reference_repeat import SEGMENT_PROFILES

    temporal = ladder.temporal
    rate = 1.0 / temporal["profile_period_s"]
    assert temporal["profile_rate_hz"] == pytest.approx(rate)
    assert temporal["segment_profiles"] == SEGMENT_PROFILES == 86
    assert temporal["segment_duration_s"] == pytest.approx(
        (temporal["segment_profiles"] - 1) * temporal["profile_period_s"]
    )
    assert temporal["frequency_resolution_hz"] == pytest.approx(rate / 86)
    assert temporal["nyquist_hz"] == pytest.approx(rate / 2.0)
    assert [temporal["band_hz"], temporal["psd_scaling"]] == [[0.5, 20.0], "density"]
    # One shared period: the ladder's own mean, which every file matches inside the tolerance.
    periods = [entry.profile_period_s for entry in ladder.inputs]
    assert temporal["period_spread_relative"] < 1e-4
    assert temporal["profile_period_s"] == pytest.approx(sum(periods) / len(periods))
    assert set(temporal["profiles_analysed"]) == {r["relative_path"] for r in ladder.levels}
    assert set(temporal["segments"].values()) == {5, 6}


def test_the_psd_band_summary_integrates_over_the_actual_frequency_grid() -> None:
    """R5: the shared band summary integrates the density over the frequency grid it was given.

    A constant density on ``1-4 Hz`` has a closed-form band power, centre of mass and high-frequency
    share, so the summary is checked against the analytic values rather than against its own
    arithmetic; the same spectrum on an unequal grid must return the same numbers, because the bins'
    cells tile the band exactly. The retired rule — density values weighted by frequency, and shares
    taken over the bin count — is not grid-invariant and moves the centre of mass by over a percent.
    """
    from udv_echo_process.analysis import _native_grid as grid

    uniform = np.arange(0.0, 10.0 + 0.125, 0.25)
    unequal = np.sort(np.concatenate([uniform, [1.125, 2.125, 3.625]]))
    flat_uniform = np.ones_like(uniform)
    flat_unequal = np.ones_like(unequal)
    summary = grid.psd_band_summary(uniform, flat_uniform, (1.0, 4.0), hf_above_hz=2.0)
    same = grid.psd_band_summary(unequal, flat_unequal, (1.0, 4.0), hf_above_hz=2.0)
    # Unit density on [1, 4]: power 3, centroid (4^2 - 1^2)/2/3 = 2.5 and 2/3 of the power above 2 Hz.
    assert summary["centroid_hz"] == pytest.approx(2.5, rel=1e-12)
    assert summary["hf_share"] == pytest.approx(2.0 / 3.0, rel=1e-12)
    # The centre of mass and the share are quadrature-exact, so the unequal grid returns them too;
    # the RMS spread inherits the midpoint rule's own small term and agrees to well inside 1 %.
    assert same["centroid_hz"] == pytest.approx(2.5, rel=1e-12)
    assert same["hf_share"] == pytest.approx(2.0 / 3.0, rel=1e-12)
    assert summary["bandwidth_hz"] == pytest.approx(math.sqrt(0.75), rel=1e-2)
    assert same["bandwidth_hz"] == pytest.approx(summary["bandwidth_hz"], rel=1e-2)

    def counted(f_grid: np.ndarray) -> float:
        """The retired rule: the frequency grid weighted by bin count, band-limited."""
        inside = (f_grid >= 1.0) & (f_grid <= 4.0)
        values = np.ones_like(f_grid)
        return float((f_grid[inside] * values[inside]).sum() / values[inside].sum())

    retired_gap = abs(counted(uniform) - counted(unequal)) / counted(uniform)
    assert abs(summary["centroid_hz"] - same["centroid_hz"]) < 1e-12 < retired_gap
    assert retired_gap > 0.01


def test_the_temporal_metrics_are_the_acf_and_psd_of_the_full_record(ladder) -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.reference_repeat import temporal_series

    entry = next(e for e in ladder.inputs if e.burst_length == 16)
    values, _time_s, _depths = _decoded(entry.relative_path)
    series = temporal_series(entry, values, ladder.temporal["profile_period_s"])
    row = next(r for r in ladder.levels if r["cycles"] == 16)
    assert row["acf_e_folding_lag_s"] == series.acf_e_folding_lag_s
    assert ladder.temporal["profiles_analysed"][entry.relative_path] == series.profiles_analysed
    frequency = np.asarray(series.frequency_hz, dtype=float)
    density = np.asarray(series.psd_mean_mm2_s2_per_hz, dtype=float)
    band_hz = (0.5, 20.0)
    # Every moment is the integral over the actual grid, each bin's cell clipped to the band (R5).
    total = grid.integrate_density(frequency, density, band_hz)
    centroid = grid.integrate_density(frequency, frequency * density, band_hz) / total
    assert (row["psd_centroid_hz"], row["psd_hf_share"]) == pytest.approx(
        (
            centroid,
            1.0 - grid.integrate_density(frequency, density, (band_hz[0], 10.0)) / total,
        )
    )
    assert row["psd_bandwidth_hz"] == pytest.approx(
        math.sqrt(grid.integrate_density(frequency, (frequency - centroid) ** 2 * density, band_hz) / total)
    )
    assert row["psd_bandwidth_hz"] > 0.0 and 0.0 < row["psd_hf_share"] < 1.0


def test_the_temporal_floor_and_screening_threshold_come_from_the_committed_wp1(ladder) -> None:
    floor = ladder.temporal["floor"]
    temporal = json.loads(ENVELOPE.read_text(encoding="utf-8"))["views"]["temporal"]
    assert floor["source_path"] == RELATIVE_ENVELOPE.as_posix()
    assert floor["source_sha256"] == hashlib.sha256(ENVELOPE.read_bytes()).hexdigest()
    assert floor["source_paths"] == [
        s["relative_path"] for s in temporal["series"]
    ]
    assert floor["band_max_abs_level_difference_db"] == pytest.approx(
        temporal["band_max_abs_level_difference_db"]
    )
    assert floor["e_folding_lag_s"] == pytest.approx(
        [s["acf"]["e_folding_lag_s"] for s in temporal["series"]]
    )
    assert floor["hf_share_difference"] == pytest.approx(FLOOR_HF_SHARE_DIFFERENCE)
    assert floor["hf_share_difference"] == pytest.approx(
        abs(floor["hf_share"][0] - floor["hf_share"][1])
    )
    assert floor["role"].startswith("sole-pair observed-discrepancy screening threshold")
    # The decision threshold is the same committed artefact, and it is positive.
    assert ladder.screening_threshold.value_mm_s == pytest.approx(ENVELOPE_MM_S)
    assert ladder.screening_threshold.metric == "max_gate_abs_mean_difference_mm_s"
    assert ladder.screening_threshold.source_sha256 == floor["source_sha256"]


def test_pairs_cover_the_ladder_on_the_shared_knots_without_upsampling(ladder) -> None:
    expected = len(CYCLES) * (len(CYCLES) - 1) // 2
    assert len(ladder.pairs) == expected
    assert len({(r["short_path"], r["long_path"]) for r in ladder.pairs}) == expected
    for row in ladder.pairs:
        assert (row["knots"], row["knot_spacing_mm"]) == pytest.approx(
            (GATES_IN_SUPPORT, PITCH_MM)
        )
    means = {r["cycles"]: _window(r["relative_path"]).mean(axis=0) for r in ladder.levels}
    for row in ladder.pairs:
        difference = means[row["short_cycles"]] - means[row["long_cycles"]]
        assert (row["max_knot_offset_mm"], row["max_abs_difference_mm_s"]) == pytest.approx(
            (0.0, float(np.abs(difference).max()))
        )
        assert row["mean_abs_difference_mm_s"] == pytest.approx(
            float(np.abs(difference).mean())
        )


def test_pair_differences_are_compared_to_the_committed_repeatability_screening_threshold(ladder) -> None:
    means = {r["cycles"]: _window(r["relative_path"]).mean(axis=0) for r in ladder.levels}
    for row in ladder.pairs:
        above = int(
            np.count_nonzero(
                np.abs(means[row["short_cycles"]] - means[row["long_cycles"]])
                > ENVELOPE_MM_S
            )
        )
        assert row["knots_above_screening_threshold"] == above
        assert row["max_abs_difference_over_screening_threshold"] == pytest.approx(
            row["max_abs_difference_mm_s"] / ENVELOPE_MM_S
        )
        assert bool(row["depth_ranges_above_screening_threshold_mm"]) == (above > 0)
    above = [row for row in ladder.pairs if row["knots_above_screening_threshold"]]
    worst = max(ladder.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    assert (worst["short_label"], worst["long_label"]) == ("4", "28")
    assert worst["max_abs_difference_mm_s"] == pytest.approx(WORST_PAIR_ABS_MM_S)
    assert worst["max_abs_difference_over_screening_threshold"] == pytest.approx(
        WORST_PAIR_ABS_MM_S / ENVELOPE_MM_S
    )
    assert worst["max_abs_difference_over_screening_threshold"] > 2.0
    # The clearances are a handful of gates, and the longest bursts carry almost all of them.
    assert all(row["knots_above_screening_threshold"] <= 5 for row in above)
    assert sum(
        1 for row in above if {row["short_label"], row["long_label"]} & {"28", "32"}
    ) >= 16


def test_pair_rows_carry_the_smoothing_and_bandwidth_change_with_cycles(ladder) -> None:
    levels = {row["cycles"]: row for row in ladder.levels}
    focus = [r for r in ladder.pairs if (r["short_cycles"], r["long_cycles"]) in {(2, 32), (18, 20)}]
    for row in focus + [max(ladder.pairs, key=lambda r: r["cycle_gap"])]:
        short, long = levels[row["short_cycles"]], levels[row["long_cycles"]]
        assert (
            row["correlation_length_change_mm"],
            row["gradient_median_change_mm_s_per_mm"],
            row["robust_spread_change_mm_s"],
            row["zero_fraction_change"],
            row["hf_share_change"],
            row["acf_e_folding_lag_change_s"],
        ) == pytest.approx(
            (
                long["correlation_length_mm"] - short["correlation_length_mm"],
                long["gradient_median_abs_mm_s_per_mm"]
                - short["gradient_median_abs_mm_s_per_mm"],
                long["robust_spread_mm_s"] - short["robust_spread_mm_s"],
                long["zero_fraction"] - short["zero_fraction"],
                long["psd_hf_share"] - short["psd_hf_share"],
                long["acf_e_folding_lag_s"] - short["acf_e_folding_lag_s"],
            )
        )


def test_the_focus_pair_is_the_plans_18_versus_20_cycle_question(ladder) -> None:
    assert ladder.focus_pair == ("burst_len/18.BDD", "burst_len/20.BDD")
    row = next(
        r for r in ladder.pairs if (r["short_path"], r["long_path"]) == ladder.focus_pair
    )
    assert (row["short_cycles"], row["long_cycles"]) == FOCUS_PAIR_CYCLES
    assert row["knots_above_screening_threshold"] == 0
    assert row["depth_ranges_above_screening_threshold_mm"] == ""
    assert row["max_abs_difference_mm_s"] == pytest.approx(FOCUS_ABS_MM_S)
    assert row["max_abs_difference_over_screening_threshold"] == pytest.approx(
        FOCUS_ABS_MM_S / ENVELOPE_MM_S
    )
    # Nothing in the 16-20-cycle region clears the screening_threshold either.
    window = [
        r for r in ladder.pairs
        if FOCUS_WINDOW_CYCLES[0] <= r["short_cycles"] <= r["long_cycles"]
        <= FOCUS_WINDOW_CYCLES[1]
    ]
    assert len(window) == 3
    assert all(r["knots_above_screening_threshold"] == 0 for r in window)
    assert all(r["max_abs_difference_over_screening_threshold"] < 0.7 for r in window)


def test_written_artefacts_reproduce_the_declared_columns_and_bytes(tmp_path) -> None:
    from udv_echo_process.analysis.burst_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
        levels_csv_text,
        pairs_csv_text,
    )

    model = _write(tmp_path, "a")
    _write(tmp_path, "b")
    levels = levels_csv_text(model).splitlines()
    pairs = pairs_csv_text(model).splitlines()
    assert levels[0] == ",".join(LEVEL_COLUMNS)
    assert pairs[0] == ",".join(PAIR_COLUMNS)
    assert (len(levels), len(pairs)) == (len(model.levels) + 1, len(model.pairs) + 1)
    assert [int(r["cycles"]) for r in csv.DictReader(levels)] == list(CYCLES)
    for name in (LEVELS_NAME, PAIRS_NAME, PROVENANCE_NAME):
        first = (tmp_path / "a" / name).read_bytes()
        assert first == (tmp_path / "b" / name).read_bytes(), name
        assert b"\r" not in first and first.endswith(b"\n")
        assert str(ROOT).encode() not in first
        assert b"C:/" not in first and b"C:\\" not in first
    figure = (tmp_path / "a" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    assert figure == (tmp_path / "b" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    assert figure.startswith(b"\x89PNG\r\n\x1a\n") and len(figure) > 40_000


def test_provenance_records_each_level_s_timestamp_jitter_and_the_estimator_decision(
    tmp_path,
) -> None:
    """R6: every burst input carries the four interval statistics beside criterion and decision."""
    from udv_echo_process.analysis.burst_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    timestamps = document["timestamps"]
    assert timestamps["retained"] is True
    assert timestamps["tolerance_cycles"] == pytest.approx(1.0 / 16.0)
    assert "phase" in timestamps["criterion"] and timestamps["justification"].strip()
    per_input = {item["relative_path"]: item for item in timestamps["per_input"]}
    assert set(per_input) == {row["relative_path"] for row in select_level_rows(MANIFEST)}
    for item in per_input.values():
        assert item["criterion_met"] is True
        assert item["intervals"] == item["profiles"] - 1
        for key in ("median_dt_s", "rms_deviation_s", "max_abs_deviation_s"):
            assert item[key] > 0.0, key
        assert item["dt_iqr_s"] >= 0.0
        assert item["median_dt_s"] == pytest.approx(0.0224)
        assert item["max_abs_deviation_s"] == pytest.approx(1e-4, abs=1e-6)
    assert "uniform" in timestamps["estimator"] and "uniform" in timestamps["decision"]


def test_provenance_records_binding_definitions_views_and_the_caption(tmp_path) -> None:
    from udv_echo_process.analysis.burst_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert (document["artefact"], document["axis"], document["analysis_commit"]) == (
        "burst-ladder", AXIS, COMMIT,
    )
    assert document["manifest"]["sha256"] == (
        f"sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}"
    )
    assert {item["relative_path"] for item in document["inputs"]} == {
        row["relative_path"] for row in select_level_rows(MANIFEST)
    }
    views = document["views"]
    assert views["time"]["common_duration"]["revolutions"] == COMMON_REVOLUTIONS
    assert views["time"]["common_duration"]["window_s"] == pytest.approx(COMMON_WINDOW_S)
    support = views["depth"]["common_support"]
    assert (support["min_mm"], support["max_mm"]) == pytest.approx(
        (SUPPORT_MIN_MM, SUPPORT_MAX_MM), abs=1e-9
    )
    assert support["contains_plan_window"] is True
    assert views["alignment"]["upsampled"] is False
    assert "knot" in views["alignment"]["knot_rule"]
    assert views["temporal"]["grid"]["segment_profiles"] == 86
    assert views["temporal"]["floor"]["source_path"] == RELATIVE_ENVELOPE.as_posix()
    assert {
        "cycles", "robust_spread", "zero_fraction", "gradient", "correlation_length",
        "difference", "screening_threshold", "knee", "temporal_bandwidth", "temporal_floor",
        "replicates", "time_view", "depth_view",
    } <= set(document["definitions"])
    figure = document["figure"]
    assert figure["path"] == "figures/burst-ladder.png"
    assert len(figure["panels"]) == 2
    assert COMMIT in figure["caption"] and "16-20" in figure["caption"]
    assert "18" in figure["caption"] and "not a phase reference" in figure["caption"]
    assert "independent experimental replicate" in figure["caption"]
    assert "--analysis-commit" in document["regeneration"]["command"]


def test_findings_answer_the_plans_burst_questions_from_the_numbers(tmp_path) -> None:
    from udv_echo_process.analysis.burst_ladder import PROVENANCE_NAME

    model = _write(tmp_path)
    findings = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))[
        "findings"
    ]
    gate = findings["screening_threshold_gate"]
    assert (gate["pairs"], gate["pairs_above_screening_threshold"]) == (66, 21)
    assert gate["max_ratio_to_screening_threshold"] == pytest.approx(WORST_PAIR_ABS_MM_S / ENVELOPE_MM_S)
    focus = findings["focus_18_vs_20"]
    assert (focus["short_cycles"], focus["long_cycles"]) == FOCUS_PAIR_CYCLES
    assert focus["knots_above_screening_threshold"] == 0
    assert focus["ratio_to_screening_threshold"] == pytest.approx(FOCUS_ABS_MM_S / ENVELOPE_MM_S)
    assert "not" in focus["statement"]
    window = findings["focus_window_16_20"]
    assert (window["pairs"], window["pairs_above_screening_threshold"]) == (3, 0)
    assert window["max_ratio_to_screening_threshold"] < 0.7
    assert set(findings["knees"]) >= {
        "zero_fraction", "robust_spread_mm_s", "rms_mm_s", "correlation_length_mm",
        "psd_hf_share",
    }
    for knee in findings["knees"].values():
        assert knee["knee_cycles"] in CYCLES and knee["statement"]
        assert knee["knee_change"] == pytest.approx(
            largest_step(knee["metric"], knee["cycles"], [
                row[knee["metric"]] for row in model.levels
            ])["knee_change"]
        )
    temporal = findings["temporal_bandwidth"]
    assert temporal["band_hz"] == [0.5, 20.0]
    assert temporal["hf_share_min"] <= temporal["hf_share_max"]
    assert temporal["floor_hf_share_difference"] == pytest.approx(
        model.temporal["floor"]["hf_share_difference"]
    )
    assert len(findings["limitations"]) >= 3
    assert "drift" in " ".join(findings["limitations"])
    assert "replicate" in " ".join(findings["limitations"])
    assert findings["knees"]["psd_hf_share"]["monotone_decreasing"] is False


def test_cli_writes_the_four_artefacts_and_the_committed_ones_regenerate(
    tmp_path, capsys
) -> None:
    """The reviewer-visible WP2 burst artefacts are exactly what the command writes."""
    from udv_echo_process.analysis.burst_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
        write_burst_ladder,
    )
    from udv_echo_process.cli import burst_ladder_main

    committed = {
        "levels": REPORT_DIR / LEVELS_NAME,
        "pairs": REPORT_DIR / PAIRS_NAME,
        "provenance": REPORT_DIR / PROVENANCE_NAME,
        "figure": REPORT_DIR / FIGURES_DIRNAME / FIGURE_NAME,
    }
    for name, path in committed.items():
        assert path.is_file(), f"WP2 burst must commit {name} ({path})"
    with pytest.raises(SystemExit) as ok:
        burst_ladder_main(
            [
                "--dataset-root", str(DATA_ROOT), "--report-dir", str(tmp_path),
                "--manifest", str(MANIFEST), "--screening-threshold", str(ENVELOPE),
                "--analysis-commit", COMMIT,
            ]
        )
    assert ok.value.code == 0
    assert "burst" in capsys.readouterr().out.lower()
    assert (tmp_path / LEVELS_NAME).is_file() and (tmp_path / PAIRS_NAME).is_file()
    assert (tmp_path / FIGURES_DIRNAME / FIGURE_NAME).is_file()
    recorded = json.loads(committed["provenance"].read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded
    write_burst_ladder(
        DATASET_ROOT, tmp_path / "regenerated", manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE, analysis_commit=recorded,
    )
    for name in ("levels", "pairs", "provenance"):
        actual = (tmp_path / "regenerated" / committed[name].name).read_bytes()
        assert actual.replace(b"\r\n", b"\n") == committed[name].read_bytes().replace(
            b"\r\n", b"\n"
        ), name
    assert (
        tmp_path / "regenerated" / FIGURES_DIRNAME / FIGURE_NAME
    ).read_bytes() == committed["figure"].read_bytes()
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    for token in ("burst-ladder", "burst-levels.csv", "burst-pairs.csv"):
        assert token in readme


    stale = _manifest(
        tmp_path, lambda rows: _replace(rows, "burst_len/32.BDD", duration_s="99")
    )
    with pytest.raises(SystemExit) as refused:
        burst_ladder_main(
            [
                "--dataset-root", str(DATA_ROOT), "--report-dir", str(tmp_path / "reports"),
                "--manifest", str(stale),
                "--screening-threshold", str(_rebound_screening_threshold(tmp_path, stale)),
                "--analysis-commit", COMMIT,
            ]
        )
    assert refused.value.code == 1
    refused_output = capsys.readouterr()
    assert "stale" in refused_output.err and "Traceback" not in refused_output.err
    assert not (tmp_path / "reports" / "burst-levels.csv").exists()
    with pytest.raises(SystemExit) as absent:
        burst_ladder_main(  # a missing default manifest is a named refusal, not a traceback
            [
                "--dataset-root", str(DATA_ROOT),
                "--report-dir", str(tmp_path / "empty"),
                "--analysis-commit", COMMIT,
            ]
        )
    assert absent.value.code == 1
    assert "cannot read the manifest" in capsys.readouterr().err


# ── slice 6: the scientific fingerprint and the setting-based contract (R1, R4) ──

#: The decoded configuration cells the WP0 inventory publishes that the old ``DECODED_CELLS``
#: omitted and a complete fingerprint must carry (R4).
FINGERPRINT_OMISSIONS = (
    "emit_freq_khz",
    "doppler_angle_deg",
    "tgc_start_db",
    "tgc_end_db",
    "sampling_volume_index",
    "skipped_profiles",
)
#: The two recordings that carry one decoded fingerprint whatever folder they sit in: the
#: dataset's one repeated setting, at burst length 10.
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")
ANCHOR_CYCLES = "10"


def _perturbed_cell(field: str, current: str) -> str:
    """A value of one cell that is not the committed one and is still a decoded setting."""
    if field in ("emit_power", "sensitivity", "tgc_mode"):
        return "changed"
    return f"{float(current) + 1.0:g}"


def _cell_of(relative: str, field: str) -> str:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return next(r for r in csv.DictReader(handle) if r["relative_path"] == relative)[field]


def test_the_fingerprint_covers_the_decoded_configuration_and_leaves_the_extent_out() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    for cell in FINGERPRINT_OMISSIONS:
        assert cell in grid.FINGERPRINT_FIELDS, cell
        assert cell in grid.DECODED_CELLS, cell
    assert grid.DERIVED_FINGERPRINT_CELLS == ("prf_hz", "velo_max_ms")
    for cell in ("profiles", "duration_s"):
        assert cell in grid.OBSERVATION_EXTENT_CELLS
        assert cell not in grid.FINGERPRINT_FIELDS
    assert not set(grid.OBSERVATION_EXTENT_CELLS) & set(grid.FINGERPRINT_FIELDS)


def test_the_reader_publishes_every_fingerprint_cell_the_manifest_records() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        row = next(r for r in csv.DictReader(handle) if r["relative_path"] == ANCHOR_PATHS[0])
    decoded = grid.read_decoded_level(
        DATA_ROOT, row, cells=grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS
    )
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        assert grid.canonical_cell(row[field]) == grid.canonical_cell(
            grid.format_cell(decoded.observed[field])
        ), field


def test_the_burst_contract_holds_every_fingerprint_field_but_the_cycle_count() -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.burst_ladder import ELIGIBILITY

    assert (ELIGIBILITY.axis, ELIGIBILITY.ladder_label) == (AXIS, "burst")
    assert ELIGIBILITY.varied == ("burst_length",)
    assert ELIGIBILITY.derived == ()
    every = set(grid.FINGERPRINT_FIELDS) | set(grid.DERIVED_FINGERPRINT_CELLS)
    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    assert set(ELIGIBILITY.identity_fields) == every - allowed
    for field in ("prf_period_us", "resolution_mm", "emit_power", "tgc_start_db"):
        assert field in ELIGIBILITY.identity_fields


def test_every_fingerprint_field_is_allowlisted_or_changes_the_row_s_fingerprint(
    tmp_path,
) -> None:
    """R4/R1: perturbing each field either changes identity or is allowlisted for this axis."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.burst_ladder import ELIGIBILITY, level_groups

    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    base = next(g for g in level_groups(MANIFEST) if g.key == (ANCHOR_CYCLES,))
    assert base.realization_paths == ANCHOR_PATHS
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        value = _perturbed_cell(field, _cell_of(ANCHOR_PATHS[1], field))
        manifest = _manifest(
            tmp_path,
            lambda rows, f=field, v=value: _replace(rows, ANCHOR_PATHS[1], **{f: v}),
        )
        groups = level_groups(manifest)
        at = next(g for g in groups if g.key == (ANCHOR_CYCLES,))
        if field in allowed:
            # Allowlisted: the cycle count moves the recording to its own level; it stays eligible.
            assert field == "burst_length", field
            assert ANCHOR_PATHS[1] in {
                path for group in groups for path in group.realization_paths
            }, field
        else:
            assert at.realization_paths == (ANCHOR_PATHS[0],), field
