"""Focused tests for the WP2 resolution ladder (plan ``WP2``, resolution axis).

Written RED first: ``analysis.resolution_ladder``, its CLI verb and the four
reviewer-visible artefacts (``resolution-levels.csv``, ``resolution-pairs.csv``,
``resolution-ladder.provenance.json``, ``figures/resolution-ladder.png``) did not
exist, so this module failed at import.

The tests pin the *definitions* the resolution axis must not drift on:

- the ladder is selected from ``manifest.csv`` (the WP0 artefact) by its ``res``
  rows, never from a hand-written filename list, and every re-checked cell must
  agree with the decoded recording;
- every distributional metric uses one common-duration view: the largest integer
  number of nominal 500-RPM revolutions fitting *every* resolution recording;
- cross-level summaries use only the common physical support (the intersection
  of the decoded depth ranges, ~10.163–96.743 mm);
- between-level comparisons use common knots no finer than the coarsest
  participating pitch, and the finer grid is *sampled* at those knots (nearest
  native gate) — never interpolated, never upsampled;
- gradients and the spatial correlation length are computed on each native grid
  before any alignment;
- every effect is stated against the committed WP1 repeatability screening_threshold read
  from ``reference-repeat.provenance.json``, and the focus pair is the plan's own
  0.247 mm vs 0.617 mm question, selected by pitch from the manifest.
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

from udv_echo_process.analysis.resolution_ladder import (
    AXIS,
    CORRELATION_FLOOR,
    DATASET_ROOT,
    ELIGIBILITY,
    FOCUS_PITCHES_MM,
    LEVEL_COLUMNS,
    NOMINAL_REVOLUTION_S,
    PAIR_COLUMNS,
    LevelInput,
    ResolutionLadderError,
    build_resolution_ladder,
    common_support,
    correlation_length,
    levels_csv_text,
    nearest_gate_indices,
    pair_row,
    select_level_rows,
    spatial_gradient,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
DATA_ROOT = ROOT / DATASET_ROOT
#: The paths the CLI defaults to, relative to the repository root: the committed
#: artefacts are generated with exactly these, so that is what a regeneration has
#: to pass to be byte-identical.
RELATIVE_MANIFEST = Path("reports/mixer-sensitivity-analysis/manifest.csv")
RELATIVE_ENVELOPE = Path("reports/mixer-sensitivity-analysis/reference-repeat.provenance.json")
MANIFEST = ROOT / RELATIVE_MANIFEST
ENVELOPE = ROOT / RELATIVE_ENVELOPE
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

#: The resolution ladder in decoded-pitch order, as ``manifest.csv`` records it.
LABELS = (
    "0-2",
    "0-4",
    "0-6",
    "0-8",
    "1-0",
    "1-2",
    "1-4",
    "1-6",
    "1-8",
    "2-0",
    "2-2",
    "2-5",
    "3-0",
)
FOCUS_FINE = "res/0-2.BDD"
FOCUS_COARSE = "res/0-6.BDD"
#: The two recordings that carry one decoded fingerprint whatever folder they sit in (plan §8.2
#: R1): the dataset's one repeated setting, both recorded at the 1.850 mm pitch. The ``res``
#: folder's own recording is the level's primary; the ``prf`` folder's is its second realization.
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")
#: Every realization of every eligible resolution level, in ladder order: one recording per decoded
#: pitch, with the 1.850 mm level carrying both of the reference recordings.
REALIZATION_PATHS = (
    "res/0-2.BDD",
    "res/0-4.BDD",
    "res/0-6.BDD",
    "res/0-8.BDD",
    "res/1-0.BDD",
    "res/1-2.BDD",
    "res/1-4.BDD",
    "res/1-6.BDD",
    ANCHOR_PATHS[0],
    ANCHOR_PATHS[1],
    "res/2-0.BDD",
    "res/2-2.BDD",
    "res/2-5.BDD",
    "res/3-0.BDD",
)

#: 93 nominal revolutions at 500 RPM fit every resolution recording (the
#: shortest is res/1-0.BDD at 11.2316 s).
COMMON_REVOLUTIONS = 93
COMMON_WINDOW_S = 11.16
#: The intersection of the 13 decoded depth ranges, the plan's "common physical
#: support (~10.163–96.743 mm)".
SUPPORT_MIN_MM = 10.1626666667
SUPPORT_MAX_MM = 96.7426666667
#: The committed WP1 screening_threshold: the largest absolute per-gate mean difference.
ENVELOPE_MM_S = 19.37008103465545


@pytest.fixture(scope="module", autouse=True)
def _repository_root():
    """Run with the repository root as cwd, so relative artefact paths resolve."""
    previous = Path.cwd()
    os.chdir(ROOT)
    yield
    os.chdir(previous)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _manifest(tmp_path: Path, mutator=None) -> Path:
    """Copy the committed manifest, optionally mutating rows, into ``tmp_path``."""
    rows = _rows(MANIFEST)
    if mutator is not None:
        rows = mutator(rows)
    path = tmp_path / "manifest.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rebound_screening_threshold(tmp_path: Path, manifest: Path) -> Path:
    """The committed WP1 screening_threshold re-bound to a copied manifest's own hash.

    A manifest copied into ``tmp_path`` has different bytes, so the screening_threshold's
    recorded ``manifest.sha256`` no longer matches it. Tests that mutate a manifest
    and expect a *decoding* refusal rebind the screening_threshold first, so the refusal they
    assert is the one they provoke.
    """
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    document["manifest"]["sha256"] = (
        f"sha256:{hashlib.sha256(manifest.read_bytes()).hexdigest()}"
    )
    path = tmp_path / "reference-repeat.provenance.json"
    path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline=""
    )
    return path


@pytest.fixture(scope="module")
def ladder():
    """The built ladder: 13 levels, the common views, 78 unordered pairs."""
    return build_resolution_ladder(
        DATASET_ROOT,
        RELATIVE_MANIFEST,
        RELATIVE_ENVELOPE,
        analysis_commit=COMMIT,
    )


@pytest.fixture(scope="module")
def realization_numbers() -> dict[str, dict[str, object]]:
    """Every recording of every eligible level, measured independently.

    One entry per realization path of every eligible level: the recording's own window mean
    profile and every per-recording number the level mean has to be aggregated from. Decoded here
    straight from the reader, so a level mean is checked against an independent derivation rather
    than against the module's own intermediate (plan §8.3 step 5).
    """
    from udv_echo_process.analysis.resolution_ladder import selected_levels

    measured: dict[str, dict[str, object]] = {}
    for _group, rows in selected_levels(MANIFEST):
        for row in rows:
            measured[row["relative_path"]] = _realization_numbers(row["relative_path"])
    return measured


def _realization_numbers(relative_path: str) -> dict[str, object]:
    from udv_echo_process.io import load

    stream = load(DATA_ROOT / relative_path).recording.streams[0]
    values = np.asarray(stream.data.values, dtype=float)
    time_s = np.asarray(stream.data.time_s, dtype=float)
    depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
    mask = _in_support(depths)
    window = values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9]
    supported = window[:, mask]
    means = supported.mean(axis=0)
    gradient = spatial_gradient(depths[mask], means)
    correlation = correlation_length(depths[mask], means)
    time_iqr = np.percentile(supported, 75, axis=0) - np.percentile(supported, 25, axis=0)
    pitch = float(np.diff(depths).mean())
    return {
        "depths": depths,
        "means": means,
        # The recording's window mean over its *whole* gate grid: what a pair samples at the
        # coarser participant's knots (the tables restrict it to the common support there).
        "window_mean": window.mean(axis=0),
        "profiles_window": int(window.shape[0]),
        "gates_in_support": int(np.count_nonzero(mask)),
        "mean_mm_s": float(means.mean()),
        "robust_spread_mm_s": float(np.percentile(means, 75.0) - np.percentile(means, 25.0)),
        "rms_mm_s": float(np.sqrt(np.mean(supported**2))),
        "zero_fraction": float(np.count_nonzero(supported == 0.0) / supported.size),
        "time_iqr_median_mm_s": float(np.median(time_iqr)),
        "gradient_median_abs_mm_s_per_mm": gradient.median_abs_mm_s_per_mm,
        "gradient_max_abs_mm_s_per_mm": gradient.max_abs_mm_s_per_mm,
        "gradient_max_depth_mm": gradient.max_depth_mm,
        "correlation_length_mm": correlation.length_mm,
        "correlation_lag_max_mm": correlation.lag_max_mm,
        "correlation_reaches_floor": correlation.reaches_floor,
        "correlation_length_over_pitch": correlation.length_mm / pitch,
    }


@pytest.fixture(scope="module")
def native(realization_numbers, ladder) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Each level's native gate depths and its **aggregated** common-window mean profile.

    The level's profile is the unweighted mean of its realizations' window mean profiles, on the one
    grid the level's shared settings give it - the aggregation rule the tables use (plan §8.3
    step 5).
    """
    decoded: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for row in ladder.levels:
        parts = [
            realization_numbers[path]["window_mean"]
            for path in row.realization_paths.split(";")
        ]
        depths = realization_numbers[row.relative_path]["depths"]
        decoded[row.relative_path] = (depths, np.mean(np.stack(parts), axis=0))
    return decoded


def _in_support(depths: np.ndarray) -> np.ndarray:
    return np.flatnonzero(
        (depths >= SUPPORT_MIN_MM - 1e-9) & (depths <= SUPPORT_MAX_MM + 1e-9)
    )


# ── slice 1: axis, selection and refusal of a bad manifest ──────────────────


def test_the_axis_the_pitches_and_the_artefact_names_are_the_resolution_ladder() -> None:
    from udv_echo_process.analysis import resolution_ladder as module

    assert AXIS == "res"
    assert FOCUS_PITCHES_MM[0] < FOCUS_PITCHES_MM[1]
    assert module.LEVELS_NAME == "resolution-levels.csv"
    assert module.PAIRS_NAME == "resolution-pairs.csv"
    assert module.PROVENANCE_NAME == "resolution-ladder.provenance.json"
    assert module.FIGURE_NAME == "resolution-ladder.png"
    assert module.SCREENING_THRESHOLD_NAME == "reference-repeat.provenance.json"


def test_select_level_rows_reads_every_resolution_row_from_the_manifest() -> None:
    rows = select_level_rows(MANIFEST)
    assert tuple(row["requested_label"] for row in rows) == LABELS
    assert {row["axis"] for row in rows} == {"res"}
    assert len({row["relative_path"] for row in rows}) == len(rows)
    pitches = [float(row["resolution_mm"]) for row in rows]
    assert pitches == sorted(pitches)
    # The manifest is the authority: every selected row is a decoded res file
    # whose content hash is the bytes on disk.
    for row in rows:
        digest = hashlib.sha256((DATA_ROOT / row["relative_path"]).read_bytes())
        assert row["source_sha256"] == digest.hexdigest()


def test_select_level_rows_refuses_a_missing_or_unreadable_manifest(tmp_path) -> None:
    with pytest.raises(ResolutionLadderError, match="cannot read the manifest"):
        select_level_rows(tmp_path / "absent.csv")


def test_select_level_rows_refuses_a_manifest_without_resolution_rows(tmp_path) -> None:
    manifest = _manifest(tmp_path, lambda rows: [r for r in rows if r["axis"] != "res"])
    with pytest.raises(ResolutionLadderError, match="no res rows"):
        select_level_rows(manifest)


def test_select_level_rows_refuses_a_duplicated_row(tmp_path) -> None:
    def duplicate(rows):
        return [*rows, rows[20]]

    manifest = _manifest(tmp_path, duplicate)
    with pytest.raises(ResolutionLadderError, match="exactly one row"):
        select_level_rows(manifest)


def test_select_level_rows_refuses_a_row_that_did_not_decode(tmp_path) -> None:
    manifest = _manifest(
        tmp_path,
        lambda rows: [
            {**row, "decode_error": "struct.error: boom"} if row["axis"] == "res" and row["requested_label"] == "0-6" else row
            for row in rows
        ],
    )
    with pytest.raises(ResolutionLadderError, match="0-6"):
        select_level_rows(manifest)


def test_select_level_rows_refuses_a_ladder_whose_rows_are_not_one_fingerprint_apart(
    tmp_path,
) -> None:
    """A requested row that moved a setting other than the pitch is refused by name."""
    manifest = _manifest(
        tmp_path, lambda rows: _replace(rows, "res/0-4.BDD", burst_length="12")
    )
    with pytest.raises(ResolutionLadderError, match="does not match the decoded"):
        select_level_rows(manifest)


def test_two_recordings_at_one_decoded_pitch_are_two_realizations_not_a_refusal(
    tmp_path,
) -> None:
    """R1: the old duplicate-key refusal was the defect - one decoded level, two named files."""
    from udv_echo_process.analysis.resolution_ladder import level_groups

    def collapse(rows):
        return [
            {**row, "resolution_mm": "1.85"} if row["axis"] == "res" else row for row in rows
        ]

    manifest = _manifest(tmp_path, collapse)
    collapsed = [group for group in level_groups(manifest) if group.key == ("1.85",)]
    assert len(collapsed) == 1
    level = collapsed[0]
    # Every requested row that moved to the pitch, plus the reference recording that always
    # carried 1.850 mm: one level, 14 separately named realizations, never a refusal.
    assert len(level.realizations) == len(LABELS) + 1
    assert set(level.realization_paths) == {
        *(f"res/{label}.BDD" for label in LABELS),
        ANCHOR_PATHS[0],
    }
    assert level.realization_paths[0] == ANCHOR_PATHS[0]  # manifest order, then the axis's own
    assert level.primary_path == FOCUS_FINE
    assert level.in_ladder is True
    assert level.requested_paths == tuple(f"res/{label}.BDD" for label in LABELS)
    assert [row["relative_path"] for row in select_level_rows(manifest)] == [FOCUS_FINE]


def test_a_same_settings_recording_in_another_folder_is_not_excluded(tmp_path) -> None:
    """R1: the folder a row sits in cannot decide whether it realizes a level."""
    from udv_echo_process.analysis.resolution_ladder import level_groups

    def relabel(rows):
        return [
            {**row, "axis": "burst_len"} if row["relative_path"] == ANCHOR_PATHS[0] else row
            for row in rows
        ]

    groups = level_groups(MANIFEST)
    anchor = next(group for group in groups if group.key == ("1.85",))
    assert anchor.realization_paths == ANCHOR_PATHS
    assert ANCHOR_PATHS[1] == anchor.primary_path  # the axis's own requested realization
    assert anchor.requested_paths == (ANCHOR_PATHS[1],)
    assert [group.key for group in groups if not group.in_ladder] == []
    # The same recording recorded under a third folder is still eligible, and still not the
    # ladder's own: eligibility is the decoded fingerprint, the ladder is what the axis requested.
    relabelled = next(
        group
        for group in level_groups(_manifest(tmp_path, relabel))
        if group.key == ("1.85",)
    )
    assert relabelled.realization_paths == ANCHOR_PATHS
    assert relabelled.primary_path == ANCHOR_PATHS[1]
    assert [row["relative_path"] for row in select_level_rows(MANIFEST)] == [
        f"res/{label}.BDD" for label in LABELS
    ]


def test_select_level_rows_refuses_a_row_without_a_usable_pitch(tmp_path) -> None:
    def blank(rows):
        return [
            {**row, "resolution_mm": ""}
            if row["axis"] == "res" and row["requested_label"] == "0-2"
            else row
            for row in rows
        ]

    manifest = _manifest(tmp_path, blank)
    with pytest.raises(ResolutionLadderError, match="0-2"):
        select_level_rows(manifest)


def test_build_refuses_a_stale_manifest_cell(tmp_path) -> None:
    """A manifest whose decoded cell no longer matches the bytes must not run."""
    def stale(rows):
        return [
            {**row, "gates": "999"}
            if row["axis"] == "res" and row["requested_label"] == "0-2"
            else row
            for row in rows
        ]

    manifest = _manifest(tmp_path, stale)
    screening_threshold = _rebound_screening_threshold(tmp_path, manifest)
    with pytest.raises(ResolutionLadderError, match="stale"):
        build_resolution_ladder(
            DATASET_ROOT, manifest, screening_threshold, analysis_commit=COMMIT
        )


def test_build_refuses_a_source_hash_that_is_not_the_bytes(tmp_path) -> None:
    def corrupt(rows):
        return [
            {**row, "source_sha256": "0" * 64}
            if row["axis"] == "res" and row["requested_label"] == "0-2"
            else row
            for row in rows
        ]

    manifest = _manifest(tmp_path, corrupt)
    screening_threshold = _rebound_screening_threshold(tmp_path, manifest)
    with pytest.raises(ResolutionLadderError, match="sha256"):
        build_resolution_ladder(
            DATASET_ROOT, manifest, screening_threshold, analysis_commit=COMMIT
        )


def test_build_refuses_an_screening_threshold_that_is_missing_or_bound_to_another_manifest(
    tmp_path,
) -> None:
    with pytest.raises(ResolutionLadderError, match="cannot read the WP1 screening_threshold"):
        build_resolution_ladder(
            DATASET_ROOT, RELATIVE_MANIFEST, tmp_path / "absent.json", analysis_commit=COMMIT
        )
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    document["manifest"]["sha256"] = "sha256:" + "0" * 64
    rebound = tmp_path / "reference-repeat.provenance.json"
    rebound.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="")
    with pytest.raises(ResolutionLadderError, match="manifest"):
        build_resolution_ladder(
            DATASET_ROOT, RELATIVE_MANIFEST, rebound, analysis_commit=COMMIT
        )


# ── slice 2: the two common views ────────────────────────────────────────────


def test_the_common_duration_view_is_the_largest_shared_whole_revolutions(ladder) -> None:
    common = ladder.common
    assert (common.nominal_rpm, common.revolution_s) == (500.0, NOMINAL_REVOLUTION_S)
    assert common.revolutions == COMMON_REVOLUTIONS
    assert common.window_s == pytest.approx(COMMON_WINDOW_S)
    # 94 revolutions (11.28 s) do not fit the shortest resolution recording.
    assert 94 * NOMINAL_REVOLUTION_S > min(entry.duration_s for entry in ladder.inputs)
    for entry in ladder.inputs:
        assert common.profiles_window[entry.relative_path] == pytest.approx(
            _expected_profiles(entry.relative_path)
        )


def _expected_profiles(relative_path: str) -> int:
    from udv_echo_process.io import load

    stream = load(DATA_ROOT / relative_path).recording.streams[0]
    time_s = np.asarray(stream.data.time_s, dtype=float)
    return int(np.count_nonzero(time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9))


def test_every_distributional_metric_uses_the_common_window_not_the_full_record(ladder) -> None:
    """A metric over the full record would differ from the table's value."""
    from udv_echo_process.io import load

    entry = next(e for e in ladder.inputs if e.relative_path == FOCUS_COARSE)
    row = next(r for r in ladder.levels if r.relative_path == FOCUS_COARSE)
    stream = load(DATA_ROOT / FOCUS_COARSE).recording.streams[0]
    values = np.asarray(stream.data.values, dtype=float)
    time_s = np.asarray(stream.data.time_s, dtype=float)
    depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
    mask = _in_support(depths)
    window = values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9]
    means = window[:, mask].mean(axis=0)
    assert row.mean_mm_s == pytest.approx(float(means.mean()), rel=1e-10, abs=1e-12)
    assert row.robust_spread_mm_s == pytest.approx(
        float(np.percentile(means, 75) - np.percentile(means, 25)), rel=1e-10, abs=1e-12
    )
    assert row.rms_mm_s == pytest.approx(
        float(np.sqrt(np.mean(window[:, mask] ** 2))), rel=1e-10, abs=1e-12
    )
    assert row.zero_fraction == pytest.approx(
        float(np.count_nonzero(window[:, mask] == 0.0) / window[:, mask].size),
        rel=1e-10,
        abs=1e-12,
    )
    time_iqr = np.percentile(window[:, mask], 75, axis=0) - np.percentile(
        window[:, mask], 25, axis=0
    )
    assert row.time_iqr_median_mm_s == pytest.approx(
        float(np.median(time_iqr)), rel=1e-10, abs=1e-12
    )
    full = values[:, mask]
    assert float(full.mean()) != pytest.approx(row.mean_mm_s, rel=1e-4)
    assert entry.profiles > row.profiles_window


def test_the_common_support_is_the_intersection_of_the_decoded_depth_ranges(ladder) -> None:
    ranges = [(entry.depth_min_mm, entry.depth_max_mm) for entry in ladder.inputs]
    # The decoded support carries full precision; the manifest cell is rounded to
    # 12 significant digits, so they are compared as numbers.
    low, high = common_support(ranges)
    assert low == pytest.approx(SUPPORT_MIN_MM, abs=1e-9)
    assert high == pytest.approx(SUPPORT_MAX_MM, abs=1e-9)
    assert ladder.common.support_min_mm == pytest.approx(SUPPORT_MIN_MM, abs=1e-9)
    assert ladder.common.support_max_mm == pytest.approx(SUPPORT_MAX_MM, abs=1e-9)
    # The plan's "approximately 10.163–96.743 mm".
    assert ladder.common.support_min_mm == pytest.approx(10.163, abs=5e-3)
    assert ladder.common.support_max_mm == pytest.approx(96.743, abs=5e-3)
    for entry in ladder.inputs:
        assert entry.depth_min_mm == pytest.approx(SUPPORT_MIN_MM, abs=1e-9)
        assert entry.depth_max_mm >= SUPPORT_MAX_MM - 1e-9
    for row in ladder.levels:
        assert row.gates_in_support >= 2
        assert row.gates_in_support <= row.gates


def test_common_support_refuses_disjoint_depth_ranges() -> None:
    with pytest.raises(ResolutionLadderError, match="no common physical support"):
        common_support([(0.0, 10.0), (20.0, 30.0)])


# ── slice 3: native-grid spatial metrics, before any alignment ──────────────


def test_spatial_gradient_is_the_native_gate_difference_over_the_native_pitch() -> None:
    depths = 10.0 + 1.85 * np.arange(20)
    pitch = 1.85
    profile = 3.0 * depths  # a constant slope of 3 mm/s per mm ...
    profile[8:] += 5.0  # ... with one 5 mm/s step between gates 7 and 8
    stats = spatial_gradient(depths, profile)
    assert stats.pitch_mm == pytest.approx(pitch)
    assert stats.intervals == profile.size - 1
    assert stats.median_abs_mm_s_per_mm == pytest.approx(3.0)
    assert stats.max_abs_mm_s_per_mm == pytest.approx(3.0 + 5.0 / pitch)
    # The gradient of one gate interval belongs to the midpoint of that interval.
    assert stats.max_depth_mm == pytest.approx(depths[7] + pitch / 2.0)


def test_spatial_gradient_refuses_a_profile_shorter_than_two_gates() -> None:
    with pytest.raises(ResolutionLadderError, match="at least two gates"):
        spatial_gradient(np.array([10.0]), np.array([1.0]))
    with pytest.raises(ResolutionLadderError, match="pitch"):
        spatial_gradient(np.array([10.0, 10.0]), np.array([1.0, 2.0]))


def test_correlation_length_recovers_a_known_spatial_scale() -> None:
    """A cosine of wavelength 20 mm has its 1/e crossing at ~3.80 mm."""
    pitch = 0.5
    depths = 10.0 + pitch * np.arange(80)
    profile = np.cos(2.0 * math.pi * (depths - depths[0]) / 20.0)
    stats = correlation_length(depths, profile)
    expected = 20.0 * math.acos(CORRELATION_FLOOR) / (2.0 * math.pi)
    assert stats.length_mm == pytest.approx(expected, abs=pitch)
    assert stats.lag_max_mm == pytest.approx(pitch * ((profile.size - 1) // 2))
    assert stats.reaches_floor is True
    assert stats.floor == pytest.approx(CORRELATION_FLOOR)


def test_correlation_length_refuses_a_constant_or_single_gate_profile() -> None:
    with pytest.raises(ResolutionLadderError, match="constant"):
        correlation_length(10.0 + 0.5 * np.arange(20), np.full(20, 5.0))
    with pytest.raises(ResolutionLadderError, match="at least two gates"):
        correlation_length(np.array([10.0]), np.array([5.0]))


def test_correlation_length_reports_the_cap_when_the_floor_is_unreachable() -> None:
    """Two gates leave one lag of cap: no lag can carry a 1/e crossing."""
    stats = correlation_length(np.array([10.0, 11.0]), np.array([1.0, 2.0]))
    assert stats.lag_cap_gates == 0
    assert stats.reaches_floor is False
    assert stats.length_mm == stats.lag_max_mm == 0.0


def test_level_rows_carry_the_native_grid_gradient_and_correlation_length(
    ladder, native, realization_numbers
) -> None:
    """Every level cell is its realizations' cell under the shared unweighted rule (§8.3 step 5)."""
    for row in ladder.levels:
        depths, means = native[row.relative_path]
        mask = _in_support(depths)
        native_depths, native_means = depths[mask], means[mask]
        grid = np.diff(native_depths)
        assert np.allclose(grid, row.pitch_mm, rtol=0.0, atol=1e-9)
        paths = row.realization_paths.split(";")
        # The spatial metrics of one level are the mean of its *realizations'* own native-grid
        # metrics, not the metric of the mean profile: one realization, one vote.
        for cell in (
            "gradient_median_abs_mm_s_per_mm",
            "gradient_max_abs_mm_s_per_mm",
            "gradient_max_depth_mm",
            "correlation_length_mm",
            "correlation_lag_max_mm",
            "correlation_length_over_pitch",
        ):
            assert getattr(row, cell) == pytest.approx(
                float(np.mean([realization_numbers[path][cell] for path in paths])),
                rel=1e-10,
                abs=1e-12,
            ), cell
        # The one boolean verdict aggregates by conjunction: the level's length is a measurement
        # only when every realization's own autocovariance crossed 1/e.
        assert row.correlation_reaches_floor is all(
            bool(realization_numbers[path]["correlation_reaches_floor"]) for path in paths
        )
        for cell in (
            "mean_mm_s",
            "robust_spread_mm_s",
            "rms_mm_s",
            "zero_fraction",
            "time_iqr_median_mm_s",
        ):
            assert getattr(row, cell) == pytest.approx(
                float(np.mean([realization_numbers[path][cell] for path in paths])),
                rel=1e-9,
                abs=1e-12,
            ), cell
        gradient = np.abs(np.diff(native_means)) / row.pitch_mm
        if len(paths) == 1:
            stats = spatial_gradient(native_depths, native_means)
            assert stats.max_abs_mm_s_per_mm == pytest.approx(
                row.gradient_max_abs_mm_s_per_mm
            )
            assert row.gradient_max_depth_mm == pytest.approx(
                float(native_depths[int(np.argmax(gradient))] + row.pitch_mm / 2.0)
            )
            assert stats.median_abs_mm_s_per_mm == pytest.approx(
                row.gradient_median_abs_mm_s_per_mm
            )
            assert row.correlation_length_mm == pytest.approx(
                correlation_length(native_depths, native_means).length_mm
            )
            centred = native_means - native_means.mean()
            correlation = np.correlate(centred, centred, mode="full")[centred.size - 1 :]
            correlation = correlation / correlation[0]
            cap = (centred.size - 1) // 2
            below = np.flatnonzero(correlation[: cap + 1] < CORRELATION_FLOOR)
            lag = int(below[0]) if below.size else cap
            assert row.correlation_length_mm == pytest.approx(lag * row.pitch_mm)
            assert row.correlation_lag_max_mm == pytest.approx(cap * row.pitch_mm)
            assert row.correlation_length_over_pitch == pytest.approx(
                row.correlation_length_mm / row.pitch_mm
            )
        assert row.pitch_mm == pytest.approx(
            (native_depths[-1] - native_depths[0]) / (native_depths.size - 1)
        )


def test_the_ladder_spans_the_plan_s_two_named_pitches(ladder) -> None:
    pitches = [row.pitch_mm for row in ladder.levels]
    assert pitches[0] == pytest.approx(0.246666666667, rel=1e-9)
    assert pitches[-1] == pytest.approx(2.96, rel=1e-9)
    for pitch in FOCUS_PITCHES_MM:
        assert any(row.pitch_mm == pytest.approx(pitch, rel=1e-6) for row in ladder.levels)


# ── slice 4: alignment on common knots and the screening_threshold comparison ──────────


def test_nearest_gate_indices_pick_the_closest_native_gate_of_each_knot() -> None:
    depths = np.array([10.0, 10.5, 11.0, 11.5])
    indices = nearest_gate_indices(depths, np.array([10.1, 11.2]))
    assert indices.tolist() == [0, 2]
    assert nearest_gate_indices(depths, np.array([])).tolist() == []


def test_pair_rows_cover_every_unordered_pair_of_levels(ladder) -> None:
    paths = sorted(row.relative_path for row in ladder.levels)
    expected = {
        (fine, coarse)
        for i, fine in enumerate(paths)
        for coarse in paths[i + 1 :]
    }
    assert len(ladder.pairs) == len(paths) * (len(paths) - 1) // 2 == 78
    assert {
        (row.fine_path, row.coarse_path) for row in ladder.pairs
    } == expected
    assert len({(r.fine_path, r.coarse_path) for r in ladder.pairs}) == len(ladder.pairs)
    for row in ladder.pairs:
        assert row.fine_pitch_mm < row.coarse_pitch_mm


def test_pair_rows_align_on_the_coarser_native_knots_and_never_upsample(
    ladder, native
) -> None:
    by_path = {row.relative_path: row for row in ladder.levels}
    for row in ladder.pairs:
        fine_depths, fine_means = native[row.fine_path]
        coarse_depths, coarse_means = native[row.coarse_path]
        assert row.knot_spacing_mm == pytest.approx(row.coarse_pitch_mm)
        knots = coarse_depths[_in_support(coarse_depths)]
        assert row.knots == knots.size
        assert row.support_min_mm == pytest.approx(SUPPORT_MIN_MM, abs=1e-9)
        assert row.support_max_mm == pytest.approx(SUPPORT_MAX_MM, abs=1e-9)
        indices = nearest_gate_indices(fine_depths, knots)
        offsets = np.abs(fine_depths[indices] - knots)
        # Sampling the fine grid at the coarse knots: at most half a fine pitch,
        # so a knot is never finer than either participant's own grid.
        assert row.max_knot_offset_mm == pytest.approx(float(offsets.max()))
        assert row.max_knot_offset_mm <= row.fine_pitch_mm / 2.0 + 1e-9
        assert row.max_knot_offset_mm < row.knot_spacing_mm
        difference = fine_means[indices] - coarse_means[_in_support(coarse_depths)]
        assert row.mean_abs_difference_mm_s == pytest.approx(
            float(np.mean(np.abs(difference))), rel=1e-10, abs=1e-12
        )
        assert row.median_abs_difference_mm_s == pytest.approx(
            float(np.median(np.abs(difference))), rel=1e-10, abs=1e-12
        )
        assert row.max_abs_difference_mm_s == pytest.approx(
            float(np.max(np.abs(difference))), rel=1e-10, abs=1e-12
        )
        assert row.max_abs_difference_depth_mm == pytest.approx(
            float(knots[int(np.argmax(np.abs(difference)))])
        )
        assert by_path[row.fine_path].pitch_mm == row.fine_pitch_mm


def test_pair_differences_are_compared_to_the_committed_repeatability_screening_threshold(
    ladder,
) -> None:
    screening_threshold = ladder.screening_threshold
    assert screening_threshold.metric == "max_gate_abs_mean_difference_mm_s"
    assert screening_threshold.value_mm_s == pytest.approx(ENVELOPE_MM_S)
    assert screening_threshold.path.endswith("reference-repeat.provenance.json")
    assert len(screening_threshold.source_sha256) == 64
    assert screening_threshold.scope.startswith("sole-pair observed-discrepancy screening threshold")
    for row in ladder.pairs:
        assert row.max_abs_difference_over_screening_threshold == pytest.approx(
            row.max_abs_difference_mm_s / screening_threshold.value_mm_s, rel=1e-9
        )
        assert row.fraction_above_screening_threshold == pytest.approx(
            row.knots_above_screening_threshold / row.knots, rel=1e-9, abs=1e-12
        )
        assert row.knots_above_screening_threshold <= row.knots


def test_pair_rows_flatten_the_depths_where_a_difference_clears_the_screening_threshold(
    native,
) -> None:
    """Synthetic pair: the range formatting and the screening_threshold flag are defined."""
    from udv_echo_process.analysis.resolution_ladder import ScreeningThresholdBinding

    fine_depths = 10.0 + 0.5 * np.arange(21)
    coarse_depths = 10.0 + 2.0 * np.arange(6)
    fine_means = 12.0 + 0.05 * np.arange(21)
    coarse_means = np.full(6, 12.0)
    coarse_means[3] = 40.0  # the knot at 16 mm clears the screening_threshold
    entry_fine = _entry("res/fine.BDD", "fine", 0.5, fine_depths.size)
    entry_coarse = _entry("res/coarse.BDD", "coarse", 2.0, coarse_depths.size)
    screening_threshold = ScreeningThresholdBinding(
        path="reference-repeat.provenance.json",
        source_sha256="0" * 64,
        metric="max_gate_abs_mean_difference_mm_s",
        units="mm/s",
        value_mm_s=5.0,
        gate_index=0,
        depth_mm=0.0,
        median_abs_mean_difference_mm_s=0.0,
        scope="sole-pair observed-discrepancy screening threshold: one observed realization of repeatability plus uncontrolled drift, screened and not a bound on either",
    )
    row = pair_row(
        entry_fine,
        fine_means,
        fine_depths,
        entry_coarse,
        coarse_means,
        coarse_depths,
        support=(10.0, 20.0),
        screening_threshold=screening_threshold,
    )
    assert row.knots == 6
    assert row.knots_above_screening_threshold == 1
    assert row.depth_ranges_above_screening_threshold_mm == "16..16"
    assert row.fraction_above_screening_threshold == pytest.approx(1.0 / 6.0)
    assert row.max_abs_difference_depth_mm == pytest.approx(16.0)
    assert row.max_abs_difference_mm_s == pytest.approx(40.0 - float(fine_means[12]))
    assert row.fine_detail_rms_mm_s > 0.0


def _entry(relative: str, label: str, pitch: float, gates: int) -> LevelInput:
    return LevelInput(
        relative_path=relative,
        axis="res",
        requested_label=label,
        source_sha256="1" * 64,
        pitch_mm=pitch,
        gates=gates,
        profiles=100,
        duration_s=12.0,
        depth_min_mm=10.0,
        depth_max_mm=10.0 + pitch * (gates - 1),
    )


def test_the_focus_pair_is_the_plan_s_0_247_mm_versus_0_617_mm_question(ladder) -> None:
    assert ladder.focus_pair == (FOCUS_FINE, FOCUS_COARSE)
    row = next(
        r
        for r in ladder.pairs
        if (r.fine_path, r.coarse_path) == (FOCUS_FINE, FOCUS_COARSE)
    )
    assert row.fine_pitch_mm == pytest.approx(0.246666666667, rel=1e-9)
    assert row.coarse_pitch_mm == pytest.approx(0.616666666667, rel=1e-9)
    assert row.knot_spacing_mm == pytest.approx(row.coarse_pitch_mm)
    # The extra detail below the 0.617 mm knot spacing, measured inside the finer
    # recording alone (so no repeat/drift enters this number).
    assert row.fine_detail_rms_mm_s < row.max_abs_difference_mm_s
    assert row.fine_detail_rms_mm_s < ENVELOPE_MM_S
    assert row.fine_detail_max_abs_mm_s < ENVELOPE_MM_S
    assert 0.9 < row.fine_variance_share_at_coarse_knots < 1.1
    assert row.fine_detail_variance_share < 0.01


def test_no_measured_level_pair_clears_the_screening_threshold(ladder) -> None:
    """The ladder's own verdict input: every pair's worst knot sits below the sole-pair observed-discrepancy screening threshold."""
    assert all(
        row.max_abs_difference_over_screening_threshold <= 1.0 for row in ladder.pairs
    ), max(row.max_abs_difference_over_screening_threshold for row in ladder.pairs)
    assert all(row.knots_above_screening_threshold == 0 for row in ladder.pairs)
    assert all(row.depth_ranges_above_screening_threshold_mm == "" for row in ladder.pairs)


def test_the_tables_are_written_with_the_declared_columns(ladder) -> None:
    from udv_echo_process.analysis.resolution_ladder import (
        levels_csv_text,
        pairs_csv_text,
    )

    levels = levels_csv_text(ladder).splitlines()
    pairs = pairs_csv_text(ladder).splitlines()
    assert levels[0] == ",".join(LEVEL_COLUMNS)
    assert pairs[0] == ",".join(PAIR_COLUMNS)
    assert len(levels) == len(ladder.levels) + 1
    assert len(pairs) == len(ladder.pairs) + 1
    assert [row["relative_path"] for row in _dict_rows(levels)] == [
        row.relative_path for row in ladder.levels
    ]


def _dict_rows(lines: list[str]) -> list[dict[str, str]]:
    return list(csv.DictReader(lines))


# ── slice 5: the artefacts a reviewer reads ─────────────────────────────────


def _write(tmp_path: Path, name: str = "a", **kwargs):
    from udv_echo_process.analysis.resolution_ladder import write_resolution_ladder

    return write_resolution_ladder(
        DATASET_ROOT,
        tmp_path / name,
        manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE,
        analysis_commit=COMMIT,
        **kwargs,
    )


def test_written_artefacts_are_byte_for_byte_reproducible(tmp_path) -> None:
    from udv_echo_process.analysis.resolution_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
    )

    _write(tmp_path, "a")
    _write(tmp_path, "b")
    for name in (LEVELS_NAME, PAIRS_NAME, PROVENANCE_NAME):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    figure_a = (tmp_path / "a" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    figure_b = (tmp_path / "b" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    assert figure_a == figure_b
    assert figure_a.startswith(b"\x89PNG\r\n\x1a\n")
    for name in (LEVELS_NAME, PAIRS_NAME, PROVENANCE_NAME):
        blob = (tmp_path / "a" / name).read_bytes()
        assert b"\r" not in blob
        assert blob.endswith(b"\n")
        # No checkout-specific absolute path may reach an artefact.
        assert str(ROOT).encode() not in blob
        assert b"C:/" not in blob
        assert b"C:\\" not in blob
        assert b"udv-echo-process" not in blob


def test_provenance_records_definitions_views_alignment_and_binding(tmp_path, ladder) -> None:
    from udv_echo_process.analysis.resolution_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert document["artefact"] == "resolution-ladder"
    assert document["axis"] == "res"
    assert document["analysis_commit"] == COMMIT
    assert document["manifest"]["sha256"] == (
        f"sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}"
    )
    screening_threshold = document["screening_threshold"]
    assert screening_threshold["metric"] == "max_gate_abs_mean_difference_mm_s"
    assert screening_threshold["value_mm_s"] == pytest.approx(ENVELOPE_MM_S)
    assert screening_threshold["source_sha256"] == hashlib.sha256(ENVELOPE.read_bytes()).hexdigest()
    assert screening_threshold["source_path"] == RELATIVE_ENVELOPE.as_posix()
    assert len(document["inputs"]) == len(REALIZATION_PATHS)
    assert {item["relative_path"] for item in document["inputs"]} == set(REALIZATION_PATHS)
    # Every input names the level it realizes, and every level's recordings are the inputs of that
    # level: one recording, one input, no folder consulted.
    assert {item["level_path"] for item in document["inputs"]} == {
        group.primary_path for group in ladder.groups
    }
    aggregation = document["aggregation"]
    assert aggregation["rule"] == "unweighted arithmetic mean over the level's realizations"
    assert aggregation["levels"] == len(ladder.levels) == len(LABELS)
    assert aggregation["recordings"] == len(ladder.inputs) == len(REALIZATION_PATHS)
    assert aggregation["multi_realization_levels"] == [
        {"relative_path": "res/1-8.BDD", "realization_paths": list(ANCHOR_PATHS)}
    ]
    levels = document["levels"]
    assert [entry["primary_path"] for entry in levels] == [
        row.relative_path for row in ladder.levels
    ]
    assert [entry["realizations"] for entry in levels] == [
        len(row.realization_paths.split(";")) for row in ladder.levels
    ]
    anchor = next(entry for entry in levels if entry["primary_path"] == ANCHOR_PATHS[1])
    assert anchor["realization_paths"] == list(ANCHOR_PATHS)
    assert anchor["requested_paths"] == [ANCHOR_PATHS[1]]
    assert anchor["aggregation"] == aggregation["rule"]
    assert [item["relative_path"] for item in anchor["per_realization"]] == list(ANCHOR_PATHS)
    assert [item["own_axis"] for item in anchor["per_realization"]] == [False, True]
    assert [item["requested_axis"] for item in anchor["per_realization"]] == ["prf", "res"]
    # Each realization's own numbers travel beside the mean they produced, so the mean is auditable.
    row = next(r for r in ladder.levels if r.relative_path == ANCHOR_PATHS[1])
    per_realization = anchor["per_realization"]
    for cell in ("mean_mm_s", "profiles_window", "gates_in_support", "correlation_length_mm"):
        assert getattr(row, cell) == pytest.approx(
            float(np.mean([item[cell] for item in per_realization])), rel=1e-12, abs=1e-12
        ), cell
    assert row.mean_mm_s == pytest.approx(
        float(
            np.mean(
                [
                    item["mean_mm_s"]
                    for item in per_realization
                ]
            )
        )
    )
    assert per_realization[0]["fingerprint"] == per_realization[1]["fingerprint"]
    assert per_realization[0]["extent"]["profiles"] != per_realization[1]["extent"]["profiles"]
    assert per_realization[0]["source_sha256"] == hashlib.sha256(
        (DATA_ROOT / ANCHOR_PATHS[0]).read_bytes()
    ).hexdigest()
    views = document["views"]
    assert views["time"]["common_duration"]["revolutions"] == COMMON_REVOLUTIONS
    assert views["time"]["common_duration"]["window_s"] == pytest.approx(COMMON_WINDOW_S)
    assert views["depth"]["common_support"]["min_mm"] == pytest.approx(
        SUPPORT_MIN_MM, abs=1e-9
    )
    assert views["depth"]["common_support"]["max_mm"] == pytest.approx(
        SUPPORT_MAX_MM, abs=1e-9
    )
    assert views["depth"]["common_support"]["matches_plan"] is True
    alignment = views["alignment"]
    assert "coarser" in alignment["knot_rule"]
    assert "nearest" in alignment["fine_sampling_rule"]
    assert alignment["upsampled"] is False
    assert "native" in views["gradient"]["rule"]
    assert "native" in views["correlation"]["rule"]
    for key in (
        "pitch_mm",
        "robust_spread",
        "rms",
        "zero_fraction",
        "time_iqr",
        "gradient",
        "correlation_length",
        "knots",
        "difference",
        "screening_threshold",
        "detail",
        "replicates",
        "time_view",
        "depth_view",
        "realizations",
        "aggregation",
    ):
        assert key in document["definitions"], key
    figure = document["figure"]
    assert figure["path"] == "figures/resolution-ladder.png"
    # The figure carries only the panels the resolution decision needs.
    assert len(figure["panels"]) == 2
    caption = figure["caption"]
    assert COMMIT in caption
    assert f"{ENVELOPE_MM_S:.4g}" in caption
    assert "not a phase reference" in caption
    assert "not independent" in caption
    assert "0.247" in caption or "0.2467" in caption
    assert "resolution-ladder" in document["regeneration"]["command"]
    assert "--analysis-commit" in document["regeneration"]["command"]


def test_findings_answer_the_plan_s_resolution_questions_from_the_numbers(tmp_path) -> None:
    from udv_echo_process.analysis.resolution_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    findings = document["findings"]
    gate = findings["screening_threshold_gate"]
    assert gate["pairs"] == 78
    assert gate["screening_threshold_mm_s"] == pytest.approx(ENVELOPE_MM_S)
    assert gate["pairs_above_screening_threshold"] == 0
    assert gate["max_abs_difference_mm_s"] == pytest.approx(
        max(row.max_abs_difference_mm_s for row in _model_pairs())
    )
    assert gate["max_ratio_to_screening_threshold"] <= 1.0
    information = findings["information"]
    assert information["fine_path"] == FOCUS_FINE
    assert information["coarse_path"] == FOCUS_COARSE
    assert information["knots_above_screening_threshold"] == 0
    assert information["mean_abs_difference_mm_s"] < ENVELOPE_MM_S
    assert information["max_abs_difference_mm_s"] < ENVELOPE_MM_S
    assert information["detail_max_abs_mm_s"] < ENVELOPE_MM_S
    assert "0.247" in information["statement"] or "0.2467" in information["statement"]
    assert "0.617" in information["statement"] or "0.6167" in information["statement"]
    coarsest = findings["coarsest_pitch"]
    assert coarsest["pitch_mm"] == pytest.approx(2.96)
    assert coarsest["label"] == "3-0"
    assert 1.0 < coarsest["correlation_length_over_pitch"] < 10.0
    assert len(findings["limitations"]) >= 3
    joined = " ".join(findings["limitations"])
    assert "drift" in joined
    assert "replicate" in joined


def _model_pairs():
    return build_resolution_ladder(
        DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT
    ).pairs


def test_figure_is_a_reviewer_visible_multi_panel_image(tmp_path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    from udv_echo_process.analysis.resolution_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
    )

    _write(tmp_path)
    path = tmp_path / "a" / FIGURES_DIRNAME / FIGURE_NAME
    assert path.stat().st_size > 40_000
    image = plt.imread(path)
    height, width = image.shape[:2]
    assert (height, width) == (810, 1800)
    # Not a blank canvas: the three panels carry ink.
    assert float(image[:, :, :3].std()) > 0.05


def test_cli_writes_the_four_artefacts_and_exits_zero(tmp_path, capsys) -> None:
    from udv_echo_process.analysis.resolution_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
    )
    from udv_echo_process.cli import resolution_ladder_main

    with pytest.raises(SystemExit) as excinfo:
        resolution_ladder_main(
            [
                "--dataset-root",
                str(DATA_ROOT),
                "--report-dir",
                str(tmp_path),
                "--manifest",
                str(MANIFEST),
                "--screening-threshold",
                str(ENVELOPE),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "levels" in captured.out.lower()
    for path in (
        tmp_path / LEVELS_NAME,
        tmp_path / PAIRS_NAME,
        tmp_path / PROVENANCE_NAME,
        tmp_path / FIGURES_DIRNAME / FIGURE_NAME,
    ):
        assert path.is_file(), path


def test_cli_refuses_a_stale_manifest_and_writes_nothing(tmp_path, capsys) -> None:
    from udv_echo_process.cli import resolution_ladder_main

    manifest = _manifest(
        tmp_path,
        lambda rows: [
            {**row, "gates": "999"}
            if row["axis"] == "res" and row["requested_label"] == "0-2"
            else row
            for row in rows
        ],
    )
    screening_threshold = _rebound_screening_threshold(tmp_path, manifest)
    with pytest.raises(SystemExit) as excinfo:
        resolution_ladder_main(
            [
                "--dataset-root",
                str(DATA_ROOT),
                "--report-dir",
                str(tmp_path / "reports"),
                "--manifest",
                str(manifest),
                "--screening-threshold",
                str(screening_threshold),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "stale" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "reports" / "resolution-levels.csv").exists()


def test_committed_artefacts_match_a_regeneration(tmp_path) -> None:
    """The reviewer-visible WP2 artefacts are exactly what the command produces."""
    from udv_echo_process.analysis.resolution_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
        write_resolution_ladder,
    )

    committed = {
        "levels": REPORT_DIR / LEVELS_NAME,
        "pairs": REPORT_DIR / PAIRS_NAME,
        "provenance": REPORT_DIR / PROVENANCE_NAME,
        "figure": REPORT_DIR / FIGURES_DIRNAME / FIGURE_NAME,
    }
    for name, path in committed.items():
        assert path.is_file(), f"WP2 must commit {name} ({path})"
    recorded = json.loads(committed["provenance"].read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded
    write_resolution_ladder(
        DATASET_ROOT,
        tmp_path,
        manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE,
        analysis_commit=recorded,
    )

    def normalized(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    for name in ("levels", "pairs", "provenance"):
        assert normalized(tmp_path / committed[name].name) == normalized(
            committed[name]
        ), name
    assert (tmp_path / FIGURES_DIRNAME / FIGURE_NAME).read_bytes() == committed[
        "figure"
    ].read_bytes()


def test_report_readme_documents_the_wp2_regeneration() -> None:
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    assert "resolution-ladder" in readme
    assert "resolution-levels.csv" in readme
    assert "resolution-pairs.csv" in readme
    assert "figures/resolution-ladder.png" in readme
    assert "--analysis-commit" in readme


# ── slice 6: the scientific fingerprint and the setting-based contract (R1, R4) ──────

#: The decoded configuration cells the WP0 inventory publishes that the old
#: ``DECODED_CELLS`` omitted and a complete fingerprint must carry (R4).
FINGERPRINT_OMISSIONS = (
    "emit_freq_khz",
    "doppler_angle_deg",
    "tgc_start_db",
    "tgc_end_db",
    "sampling_volume_index",
    "skipped_profiles",
)
#: The cells the two reference recordings share whatever folder they sit in. They are the
#: dataset's one repeated setting, and they must be one decoded level, not two folders.
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")


def _replace(rows, relative: str, **cells):
    """The manifest rows with one relative path's cells replaced."""
    return [{**row, **cells} if row["relative_path"] == relative else row for row in rows]


def _perturbed_cell(field: str, current: str) -> str:
    """A value of one cell that is not the committed one and is still a decoded setting."""
    if field in ("emit_power", "sensitivity", "tgc_mode"):
        return "changed"
    return f"{float(current) + 1.0:g}"


def test_the_fingerprint_covers_the_decoded_configuration_and_leaves_the_extent_out() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    for cell in FINGERPRINT_OMISSIONS:
        assert cell in grid.FINGERPRINT_FIELDS, cell
        # ... and the reader must publish it, so a fingerprint cell is re-checkable.
        assert cell in grid.DECODED_CELLS, cell
    assert grid.DERIVED_FINGERPRINT_CELLS == ("prf_hz", "velo_max_ms")
    for cell in ("profiles", "duration_s"):
        assert cell in grid.OBSERVATION_EXTENT_CELLS
        assert cell not in grid.FINGERPRINT_FIELDS
        assert cell not in grid.DERIVED_FINGERPRINT_CELLS
    assert not set(grid.OBSERVATION_EXTENT_CELLS) & set(grid.FINGERPRINT_FIELDS)


def test_the_reader_publishes_every_fingerprint_cell_the_manifest_records() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    row = next(r for r in _rows(MANIFEST) if r["relative_path"] == "res/1-8.BDD")
    decoded = grid.read_decoded_level(
        DATA_ROOT, row, cells=grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS
    )
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        assert grid.canonical_cell(row[field]) == grid.canonical_cell(
            grid.format_cell(decoded.observed[field])
        ), field


def test_the_resolution_contract_holds_every_fingerprint_field_but_the_pitch() -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.resolution_ladder import ELIGIBILITY

    assert (ELIGIBILITY.axis, ELIGIBILITY.ladder_label) == (AXIS, "resolution")
    assert ELIGIBILITY.varied == ("resolution_mm",)
    assert ELIGIBILITY.derived == ()
    every = set(grid.FINGERPRINT_FIELDS) | set(grid.DERIVED_FINGERPRINT_CELLS)
    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    assert set(ELIGIBILITY.identity_fields) == every - allowed
    assert every - set(ELIGIBILITY.identity_fields) == allowed
    assert "profiles" not in ELIGIBILITY.identity_fields


def test_the_contract_refuses_a_field_that_is_not_a_fingerprint_cell() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    with pytest.raises(ValueError, match="not a fingerprint field"):
        grid.AxisEligibility(axis="res", ladder_label="resolution", varied=("gates",))
    with pytest.raises(ValueError, match="not a derived fingerprint cell"):
        grid.AxisEligibility(
            axis="res", ladder_label="resolution", varied=("resolution_mm",), derived=("gates",)
        )
    with pytest.raises(ValueError, match="at least one varied field"):
        grid.AxisEligibility(axis="res", ladder_label="resolution", varied=())
    with pytest.raises(ValueError, match="not a fingerprint field"):
        # A derived cell is not a setting: it cannot key a ladder either.
        grid.AxisEligibility(axis="prf", ladder_label="PRF", varied=("prf_hz",))


def test_every_fingerprint_field_is_allowlisted_or_changes_the_row_s_fingerprint(
    tmp_path,
) -> None:
    """R4/R1: perturbing each field either changes identity or is allowlisted for this axis."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.resolution_ladder import ELIGIBILITY, level_groups

    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    base = next(g for g in level_groups(MANIFEST) if g.key == ("1.85",))
    assert base.realization_paths == ANCHOR_PATHS
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        row = next(r for r in _rows(MANIFEST) if r["relative_path"] == ANCHOR_PATHS[0])
        value = _perturbed_cell(field, row[field])
        manifest = _manifest(
            tmp_path,
            lambda rows, f=field, v=value: _replace(rows, ANCHOR_PATHS[0], **{f: v}),
        )
        groups = level_groups(manifest)
        at = next(g for g in groups if g.key == ("1.85",))
        if field in allowed:
            # Allowlisted: perturbing it moves the recording to the level its own key names,
            # so it is still eligible. Only the pitch may do that on this axis.
            assert field == "resolution_mm", field
            assert ANCHOR_PATHS[0] not in at.realization_paths, field
            assert ANCHOR_PATHS[0] in {
                path for group in groups for path in group.realization_paths
            }, field
        else:
            assert at.realization_paths == (ANCHOR_PATHS[1],), field


def test_the_ladder_carries_the_setting_based_selection_beside_its_levels(ladder) -> None:
    """Plan §8.3 step 2: the selection is recorded on the model; §8.3 step 5 renders it."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.resolution_ladder import provenance_document

    assert ladder.eligibility == ELIGIBILITY
    requested = select_level_rows(MANIFEST)
    assert [group.key for group in ladder.groups if group.in_ladder] == [
        (row["resolution_mm"],) for row in requested
    ]
    # Step 5: the ladder is the setting-based selection itself, so it holds every eligible level
    # (the pitch ladder's own 13) with every recording that realizes each one.
    assert len(ladder.groups) == len(LABELS)
    assert [row.relative_path for row in ladder.levels] == [
        group.primary_path for group in ladder.groups
    ]
    assert [entry.relative_path for entry in ladder.inputs] == list(REALIZATION_PATHS)
    anchor = next(group for group in ladder.groups if group.key == ("1.85",))
    assert anchor.key_display == "resolution_mm=1.85"
    assert all(
        group.key_display == f"{group.key_fields[0]}={group.key[0]}" for group in ladder.groups
    )
    # The axis's identity is the whole decoded configuration apart from the pitch: the dataset's
    # one repeated setting, held constant.
    assert anchor.identity == {
        "emit_freq_khz": "4000", "prf_period_us": "600", "prf_hz": "1666.66666667",
        "burst_length": "10", "emissions_per_profile": "20", "emit_power": "medium",
        "sensitivity": "medium", "sampling_volume_index": "4", "sound_speed_ms": "1480",
        "doppler_angle_deg": "0", "velo_max_ms": "154.137583511", "tgc_mode": "uniform",
        "tgc_start_db": "19.9215686275", "tgc_end_db": "40", "skipped_profiles": "0",
    }
    assert anchor.realizations[0].fingerprint == anchor.realizations[1].fingerprint
    assert set(anchor.realizations[0].fingerprint) == set(
        grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS
    )
    # ... and the two realizations differ only in what they observed.
    assert anchor.realizations[0].extent["profiles"] != anchor.realizations[1].extent["profiles"]
    assert anchor.realization_paths == ANCHOR_PATHS
    assert [realization.own_axis for realization in anchor.realizations] == [False, True]
    assert anchor.realizations[1].source_sha256 == hashlib.sha256(
        (DATA_ROOT / ANCHOR_PATHS[1]).read_bytes()
    ).hexdigest()
    assert anchor.realizations[0].requested_axis == "prf"
    assert anchor.realizations[1].requested_axis == AXIS
    # The ladder's own requested realization stays the level's primary, the reference recording
    # another folder requested is still named, and neither path was collapsed into the other.
    assert anchor.realizations[0].requested_axis == "prf"
    assert anchor.realizations[1].requested_axis == AXIS
    assert anchor.primary_path == ANCHOR_PATHS[1]
    assert anchor.requested_paths == (ANCHOR_PATHS[1],)
    # Step 5 renders the selection into the artefacts: every realization is named and every level
    # mean is published with the per-realization numbers it was aggregated from.
    document = provenance_document(ladder)
    assert document["aggregation"]["recordings"] == len(REALIZATION_PATHS)
    assert document["aggregation"]["multi_realization_levels"] == [
        {"relative_path": ANCHOR_PATHS[1], "realization_paths": list(ANCHOR_PATHS)}
    ]
    assert "realization_paths" in LEVEL_COLUMNS
    assert "realizations" in LEVEL_COLUMNS
    rendered = levels_csv_text(ladder)
    row = next(r for r in _dict_rows(rendered.splitlines()) if r["relative_path"] == ANCHOR_PATHS[1])
    assert row["realizations"] == "2"
    assert row["realization_paths"] == ";".join(ANCHOR_PATHS)


def test_every_eligible_level_is_measured_and_every_pair_count_comes_from_the_levels(ladder) -> None:
    """Plan §8.3 step 5: counts come from grouped settings, never from a folder's file count."""
    levels = len(ladder.groups)
    assert len(ladder.levels) == levels
    assert len(ladder.pairs) == levels * (levels - 1) // 2
    # One measurement per recording of every eligible level - the res folder's 13 and the prf
    # folder's recording of the same 1.850 mm setting.
    assert len(ladder.inputs) == len(REALIZATION_PATHS)
    assert len(ladder.realizations) == len(REALIZATION_PATHS)
    assert {row.relative_path for row in ladder.realizations} == set(REALIZATION_PATHS)
    # Both reference recordings populate the shared anchor level, and the level's own row is the
    # unweighted mean of the two realizations' rows - not either one of them.
    anchor = next(row for row in ladder.levels if row.relative_path == ANCHOR_PATHS[1])
    members = [row for row in ladder.realizations if row.relative_path in ANCHOR_PATHS]
    assert [row.relative_path for row in members] == list(ANCHOR_PATHS)
    assert anchor.mean_mm_s == pytest.approx(
        float(np.mean([row.mean_mm_s for row in members]))
    )
    assert anchor.mean_mm_s != pytest.approx(members[0].mean_mm_s)
    assert anchor.mean_mm_s != pytest.approx(members[1].mean_mm_s)
    # The shared anchor is a real level of this axis, and its pair rows are the level's, so the
    # second recording reaches every comparison the first one does.
    touching = [
        row for row in ladder.pairs
        if ANCHOR_PATHS[1] in (row.fine_path, row.coarse_path)
    ]
    assert len(touching) == levels - 1
    assert all(row.fine_path != ANCHOR_PATHS[0] for row in ladder.pairs)


def test_a_realization_that_moved_its_native_grid_is_refused_rather_than_resampled() -> None:
    """A level is measured on the one grid its shared settings give it: nothing is resampled."""
    from udv_echo_process.analysis import _native_grid as grid

    shared = (10.0, 11.85, 13.7)
    assert grid.require_one_native_grid(
        [("a", np.array(shared)), ("b", np.array(shared))], where="level"
    ).tolist() == list(shared)
    with pytest.raises(ResolutionLadderError, match="not the"):
        grid.require_one_native_grid(
            [("a", np.array(shared)), ("b", np.array([10.0, 12.0, 14.0]))], where="level"
        )
    with pytest.raises(ResolutionLadderError, match="not the"):
        grid.require_one_native_grid(
            [("a", np.array(shared)), ("b", np.array([10.0, 11.85]))], where="level"
        )
    with pytest.raises(ResolutionLadderError, match="no native gate grid"):
        grid.require_one_native_grid([], where="level")


def test_the_aggregation_cells_refuse_an_empty_or_non_finite_realization_set() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    assert grid.aggregate_cell([4.0, 6.0], cell="mean_mm_s", level="level") == pytest.approx(5.0)
    with pytest.raises(ResolutionLadderError, match="realises no recording"):
        grid.aggregate_cell([], cell="mean_mm_s", level="level")
    with pytest.raises(ResolutionLadderError, match="finite"):
        grid.aggregate_cell([float("nan")], cell="mean_mm_s", level="level")
    # The two verdict rules are not interchangeable: a measurement claim is a conjunction, an
    # adverse screening outcome a disjunction.
    assert grid.aggregate_verdict([True, False], rule="all") is False
    assert grid.aggregate_verdict([True, False], rule="any") is True
    with pytest.raises(ResolutionLadderError, match="rule 'all' or 'any'"):
        grid.aggregate_verdict([True], rule="mean")
    with pytest.raises(ResolutionLadderError, match="no verdict"):
        grid.aggregate_verdict([], rule="all")


# ── slice 7: grouped-realization prose (R1) ─────────────────────────────────


def _multi_realization_levels(ladder) -> list[str]:
    """The levels the shared validator has to be told about: one entry per level with >1 recording."""
    return [group.key_display for group in ladder.groups if len(group.realizations) > 1]


def _reviewer_visible_prose(model) -> dict[str, str]:
    """Every string the resolution artefacts put in front of a reviewer, keyed by where it sits.

    The module's own description travels too: it is source prose a reviewer reads in the repository,
    and R1 refuses singular coverage in source *and* emitted prose.
    """
    from udv_echo_process.analysis import resolution_ladder as module

    document = module.provenance_document(model)
    findings = document["findings"]
    texts: dict[str, str] = {
        "source.__doc__": module.__doc__ or "",
        "figure.caption": document["figure"]["caption"],
        "caveats.mixer_setpoint_role": module.MIXER_SETPOINT_ROLE,
        "caveats.replicate_role": module.REPLICATE_ROLE,
    }
    for key, text in document["definitions"].items():
        texts[f"definitions.{key}"] = text
    for key in ("screening_threshold_gate", "information", "coarsest_pitch", "realizations"):
        texts[f"findings.{key}.statement"] = findings[key]["statement"]
    for index, text in enumerate(findings["limitations"]):
        texts[f"findings.limitations[{index}]"] = text
    return texts


def test_the_reviewer_visible_resolution_prose_survives_the_shared_realization_validator(
    ladder,
) -> None:
    """R1: the live model's prose cannot claim singular coverage while 1.850 mm has two recordings."""
    from udv_echo_process.analysis import _native_grid as grid

    multi = _multi_realization_levels(ladder)
    assert multi == ["resolution_mm=1.85"]
    texts = _reviewer_visible_prose(ladder)
    grid.validate_realization_prose(texts, multi_realization_levels=multi)
    # The same check with a singular claim spliced in is refused, so the contract has teeth.
    for claim in (
        "one recording per setting",
        "one recording per level",
        "each level is one recording",
        "no level is replicated",
    ):
        with pytest.raises(grid.NativeGridError, match="limitations"):
            grid.validate_realization_prose(
                {**texts, "limitations": claim}, multi_realization_levels=multi
            )


def test_the_provenance_document_validates_its_own_prose_against_the_grouped_selection(
    ladder, monkeypatch
) -> None:
    """R1: emitting the document runs the shared validator over every reviewer-visible string."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.resolution_ladder import provenance_document

    expected = set(_reviewer_visible_prose(ladder))
    seen: list[tuple[dict[str, str], tuple[str, ...]]] = []
    original = grid.validate_realization_prose

    def spy(texts, *, multi_realization_levels):
        seen.append((dict(texts), tuple(multi_realization_levels)))
        return original(texts, multi_realization_levels=multi_realization_levels)

    monkeypatch.setattr(grid, "validate_realization_prose", spy)
    document = provenance_document(ladder)
    # Computed once for a caller, not once per document view.
    assert len(seen) == 1
    texts, multi = seen[0]
    assert multi == ("resolution_mm=1.85",)
    assert set(texts) == expected
    assert texts["figure.caption"] == document["figure"]["caption"]
    assert texts["findings.limitations[0]"] in document["findings"]["limitations"]


def test_emitting_the_provenance_refuses_a_definition_that_claims_singular_coverage(
    ladder, monkeypatch
) -> None:
    """R1: a singular claim spliced into live prose is refused at emit time, not merely downstream."""
    from udv_echo_process.analysis import resolution_ladder as module

    monkeypatch.setitem(module.DEFINITIONS, "replicates", "each level is one recording")
    with pytest.raises(ResolutionLadderError, match="definitions.replicates"):
        module.provenance_document(ladder)


def test_the_realization_prose_separates_the_duplicated_reference_setting_from_axis_replication(
    ladder,
) -> None:
    """R1: '14 recordings, 13 levels' is one repeated reference setting, not replicated coverage."""
    from udv_echo_process.analysis.resolution_ladder import (
        DEFINITIONS,
        provenance_document,
    )

    document = provenance_document(ladder)
    findings = document["findings"]
    statement = findings["realizations"]["statement"]
    single = [row for row in ladder.levels if row.realizations == 1]
    duplicated = [group for group in ladder.groups if len(group.realizations) > 1]
    assert [group.key_display for group in duplicated] == ["resolution_mm=1.85"]
    assert len(single) == len(LABELS) - 1 == 12
    assert findings["realizations"]["recordings"] == len(REALIZATION_PATHS) == len(single) + 2
    joined = " ".join((statement, DEFINITIONS["replicates"], *findings["limitations"]))
    # The duplicated level, both of its named recordings and the three counts are all stated ...
    assert "1.85" in joined
    for path in ANCHOR_PATHS:
        assert path in joined, path
    for count in (len(single), len(ladder.levels), len(ladder.inputs)):
        assert str(count) in joined, count
    # ... and the duplication is named as one repeated setting, explicitly not replication.
    assert re.search(r"not replicated coverage", joined, re.IGNORECASE), joined
    assert "reference setting" in joined
