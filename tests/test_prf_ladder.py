"""Focused tests for the WP2 PRF ladder (plan ``WP2``, PRF axis).

Written RED first: ``analysis.prf_ladder``, its CLI verb and its four reviewer-visible artefacts
did not exist, so this module failed at import. The tests pin what the PRF axis must not drift on: the ladder is the ``prf`` rows of
``manifest.csv``, never a filename list; one common-duration view and one common support serve
every summary; the velocity scale is the key's own consequence and is audited while every other
decoded setting is refused when it moves; the load fractions and wrap-like counts are the committed
definitions recomputed here; the temporal view is matched on *physical* segment duration because
these files share no profile rate, and spectra are compared only where every recording has support;
and the 400-us versus 250-us decision is answered from the numbers, not asserted.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import re
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis.prf_ladder import (
    AXIS,
    DATASET_ROOT,
    FOCUS_SETTING_US,
    LEVEL_COLUMNS,
    PAIR_COLUMNS,
    PrfLadderError,
    build_prf_ladder,
    levels_csv_text,
    select_level_rows,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
DATA_ROOT = ROOT / DATASET_ROOT
MANIFEST = REPORT_DIR / "manifest.csv"
ENVELOPE = REPORT_DIR / "reference-repeat.provenance.json"
RELATIVE_MANIFEST = Path("reports/mixer-sensitivity-analysis/manifest.csv")
RELATIVE_ENVELOPE = Path("reports/mixer-sensitivity-analysis/reference-repeat.provenance.json")
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout
MARKER_HZ = 500.0 / 60.0

PERIODS = (400.0, 500.0, 600.0, 700.0, 800.0)  # decoded order, as manifest.csv
PATHS = tuple(f"prf/{label}.BDD" for label in ("400", "500", "600", "700", "800"))
#: The two recordings that carry one decoded fingerprint whatever folder they sit in (plan §8.2 R1):
#: the dataset's one repeated setting, both at the 600 us level.
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")
#: Every realization of every eligible PRF level, in level order: the five ``prf`` recordings plus
#: the ``res`` folder's recording of the same 600 us setting.
REALIZATION_PATHS = (PATHS[0], PATHS[1], PATHS[2], ANCHOR_PATHS[1], PATHS[3], PATHS[4])
#: 67 revolutions at 500 RPM fit every recording (the shortest is prf/400.BDD at 8.1535 s).
COMMON_REVOLUTIONS, COMMON_WINDOW_S = 67, 8.04
WINDOW_PROFILES = {PATHS[0]: 537, PATHS[1]: 431, PATHS[2]: 360, PATHS[3]: 309, PATHS[4]: 270}
SUPPORT_MIN_MM, SUPPORT_MAX_MM, GATES_IN_SUPPORT = 10.1626666667, 100.812666667, 50
ENVELOPE_MM_S = 19.37008103465545
PITCH_MM = 1.85
#: The matched temporal view: the largest 0.1 s multiple fitting five whole segments in the
#: shortest record, and the profile count it gives each file (their rates differ by two).
SEGMENT_TARGET_S = 1.6
SEGMENT_PROFILES = {PATHS[0]: 106, PATHS[1]: 85, PATHS[2]: 71, PATHS[3]: 61, PATHS[4]: 53}
SEGMENTS = {PATHS[0]: 5, PATHS[1]: 6, PATHS[2]: 9, PATHS[3]: 9, PATHS[4]: 10}
VELO_MAX_MM_S = {
    PATHS[0]: 231.20637526638495, PATHS[1]: 184.965100213108, PATHS[2]: 154.13758351092335,
    PATHS[3]: 132.11792872364862, PATHS[4]: 115.60318763319248,
}
PROFILE_RATE_HZ = {
    PATHS[0]: 66.71981357699147, PATHS[1]: 53.50708327163236, PATHS[2]: 44.66434875635196,
    PATHS[3]: 38.32976002536934, PATHS[4]: 33.56898176168519,
}
WARNING_FRACTIONS = (0.5, 0.75, 0.9, 1.0)
WRAP_STEP_FRACTION = 1.0
FOCUS_LOAD_MAX = 0.7265625000000001  # prf/400.BDD: |v| / 231.206... mm/s
LARGEST_LOAD = 1.2109375  # prf/800.BDD
WORST_PAIR_ABS_MM_S = 38.13996622718802  # prf/400.BDD minus the 600 us level at 13.8627 mm
COUPLED_SETTINGS = (
    "resolution_mm", "burst_length", "emissions_per_profile", "emit_power", "sensitivity",
    "tgc_mode", "sound_speed_ms", "gates",
)


@pytest.fixture(scope="module", autouse=True)
def _repository_root():
    """Run with the repository root as cwd, so relative artefact paths resolve."""
    previous = Path.cwd()
    os.chdir(ROOT)
    yield
    os.chdir(previous)


_DECODED: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, float]] = {}


def _decoded(relative: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """A file's ``(values, time_s, depths, velo_max_mm_s)`` straight from the reader."""
    if relative not in _DECODED:
        from udv_echo_process.io import load

        stream = load(DATA_ROOT / relative).recording.streams[0]
        _DECODED[relative] = (
            np.asarray(stream.data.values, dtype=float),
            np.asarray(stream.data.time_s, dtype=float),
            np.asarray(stream.data.gate_depths_mm, dtype=float),
            float(stream.config.velo_max_ms),
        )
    return _DECODED[relative]


def _window(relative: str) -> np.ndarray:
    """A file's common-duration window on the common support, derived here not by the module."""
    values, time_s, depths, _vmax = _decoded(relative)
    inside = (depths >= SUPPORT_MIN_MM - 1e-9) & (depths <= SUPPORT_MAX_MM + 1e-9)
    return values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9][:, inside]


def _manifest(tmp_path: Path, mutator=None, name: str = "manifest.csv") -> Path:
    """Copy the committed manifest, optionally mutating rows, into ``tmp_path``."""
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if mutator is not None:
        rows = mutator(rows)
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rebound_screening_threshold(tmp_path: Path, manifest: Path) -> Path:
    """The committed WP1 screening_threshold re-bound to a copied manifest's own hash."""
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    document["manifest"]["sha256"] = f"sha256:{hashlib.sha256(manifest.read_bytes()).hexdigest()}"
    path = tmp_path / "reference-repeat.provenance.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _replace(rows, relative, **cells):
    """The manifest rows with one relative path's cells replaced."""
    return [{**row, **cells} if row["relative_path"] == relative else row for row in rows]


def _write(tmp_path: Path, name: str = "a"):
    from udv_echo_process.analysis.prf_ladder import write_prf_ladder

    return write_prf_ladder(
        DATASET_ROOT, tmp_path / name, manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE, analysis_commit=COMMIT,
    )


@pytest.fixture(scope="module")
def ladder():
    """The built ladder: 5 levels, the two matched views and 10 unordered pairs."""
    return build_prf_ladder(
        DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT
    )


def test_select_level_rows_refuses_a_bad_inventory(tmp_path) -> None:
    from udv_echo_process.analysis import prf_ladder as module

    assert (AXIS, FOCUS_SETTING_US) == ("prf", 400.0)
    assert (module.LEVELS_NAME, module.PAIRS_NAME) == ("prf-levels.csv", "prf-pairs.csv")
    assert (module.PROVENANCE_NAME, module.FIGURE_NAME) == (
        "prf-ladder.provenance.json", "prf-ladder.png",
    )
    rows = select_level_rows(MANIFEST)
    assert [float(row["prf_period_us"]) for row in rows] == list(PERIODS)
    # Only the PRF axis may reach the ladder, and never from a filename list.
    assert {row["axis"] for row in rows} == {AXIS}
    assert all(row["relative_path"].startswith("prf/") for row in rows)
    with pytest.raises(PrfLadderError, match="cannot read"):
        select_level_rows(tmp_path / "absent.csv")
    without = _manifest(tmp_path, lambda rows: [r for r in rows if r["axis"] != AXIS])
    with pytest.raises(PrfLadderError, match="no prf rows"):
        select_level_rows(without)
    undecoded = _manifest(tmp_path, lambda rows: _replace(rows, PATHS[0], decode_error="boom"))
    with pytest.raises(PrfLadderError, match="decode_error"):
        select_level_rows(undecoded)
    with pytest.raises(PrfLadderError, match="exactly one"):  # a repeated PRF row, not any row
        select_level_rows(_manifest(
            tmp_path,
            lambda rows: rows + [next(r for r in rows if r["relative_path"] == PATHS[0])],
        ))
    for relative, cell, pattern in (
        (PATHS[0], "", "not a pulse-repetition period"), (PATHS[1], "0", "<= 0"),
    ):
        broken = _manifest(
            tmp_path,
            lambda rows, relative=relative, cell=cell: _replace(rows, relative, prf_period_us=cell),
        )
        with pytest.raises(PrfLadderError, match=pattern):
            select_level_rows(broken)
    # A requested row that moved a setting other than the period is refused by name.
    coupled = _manifest(
        tmp_path, lambda rows: _replace(rows, PATHS[2], burst_length="12")
    )
    with pytest.raises(PrfLadderError, match="does not match the decoded"):
        select_level_rows(coupled)


def test_two_recordings_at_one_decoded_period_are_two_realizations_not_a_refusal(
    tmp_path,
) -> None:
    """R1: the old duplicate-key refusal was the defect - one decoded level, two named files."""
    from udv_echo_process.analysis.prf_ladder import level_groups

    manifest = _manifest(tmp_path, lambda rows: _replace(rows, PATHS[1], prf_period_us="600.0"))
    groups = level_groups(manifest)
    at = next(group for group in groups if group.key == ("600",))
    # Manifest order, then the axis's own requested realization: the level of the plan's 600 µs
    # setting is one level with three named recordings, never a refusal.
    assert at.realization_paths == (PATHS[1], PATHS[2], ANCHOR_PATHS[1])
    assert at.primary_path == PATHS[1]
    assert at.in_ladder is True
    assert at.requested_paths == (PATHS[1], PATHS[2])
    assert [row["relative_path"] for row in select_level_rows(manifest)] == [
        PATHS[0], PATHS[1], PATHS[3], PATHS[4]
    ]


def test_a_same_settings_recording_in_another_folder_is_not_excluded(tmp_path) -> None:
    """R1: the folder a row sits in cannot decide whether it realizes a level."""
    from udv_echo_process.analysis.prf_ladder import level_groups

    groups = level_groups(MANIFEST)
    anchor = next(group for group in groups if group.key == ("600",))
    assert anchor.realization_paths == ANCHOR_PATHS
    assert anchor.primary_path == ANCHOR_PATHS[0]  # the axis's own requested realization
    assert anchor.requested_paths == (ANCHOR_PATHS[0],)
    assert [group.key for group in groups if not group.in_ladder] == []
    assert all(
        len(group.realizations) == 1 for group in groups if group.key != ("600",)
    )
    # Relabelling the reference recording under another folder cannot exclude it either.
    def relabel(rows):
        return [
            {**row, "axis": "tgc"} if row["relative_path"] == ANCHOR_PATHS[1] else row
            for row in rows
        ]

    relabelled = next(
        group
        for group in level_groups(_manifest(tmp_path, relabel))
        if group.key == ("600",)
    )
    assert relabelled.realization_paths == ANCHOR_PATHS
    assert relabelled.primary_path == ANCHOR_PATHS[0]
    assert [float(row["prf_period_us"]) for row in select_level_rows(MANIFEST)] == list(PERIODS)


def test_build_refuses_stale_hash_derived_cells_coupling_or_unbound_screening_threshold(tmp_path) -> None:
    for cell, value in (("gates", "49"), ("velo_max_ms", "231.206375266"), ("prf_hz", "2500")):
        stale = _manifest(tmp_path, lambda rows, c=cell, v=value: _replace(rows, PATHS[4], **{c: v}))
        with pytest.raises(PrfLadderError, match="stale inventory|does not match the decoded"):
            build_prf_ladder(
                DATASET_ROOT, stale, _rebound_screening_threshold(tmp_path, stale), analysis_commit=COMMIT
            )
    wrong = _manifest(tmp_path, lambda rows: _replace(rows, PATHS[3], source_sha256="0" * 64))
    with pytest.raises(PrfLadderError, match="sha256 mismatch"):
        build_prf_ladder(
            DATASET_ROOT, wrong, _rebound_screening_threshold(tmp_path, wrong), analysis_commit=COMMIT
        )
    with pytest.raises(PrfLadderError, match="cannot read the WP1 screening_threshold"):
        build_prf_ladder(DATASET_ROOT, RELATIVE_MANIFEST, tmp_path / "absent.json",
                         analysis_commit=COMMIT)
    # The committed screening_threshold records the committed manifest's hash: another inventory must not be
    # able to borrow its threshold.
    changed = _manifest(tmp_path, lambda rows: _replace(rows, PATHS[1], gates="49"))
    with pytest.raises(PrfLadderError, match="records manifest"):
        build_prf_ladder(DATASET_ROOT, changed, ENVELOPE, analysis_commit=COMMIT)
    # The threshold and the temporal floor are the committed WP1 pair through its committed curves.
    ladder = build_prf_ladder(DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE,
                              analysis_commit=COMMIT)
    floor = ladder.temporal["floor"]
    temporal = json.loads(ENVELOPE.read_text(encoding="utf-8"))["views"]["temporal"]
    assert floor["source_sha256"] == hashlib.sha256(ENVELOPE.read_bytes()).hexdigest()
    assert floor["source_paths"] == [s["relative_path"] for s in temporal["series"]]
    assert floor["role"].startswith("sole-pair observed-discrepancy screening threshold")
    assert ladder.screening_threshold.value_mm_s == pytest.approx(ENVELOPE_MM_S)
    assert ladder.screening_threshold.metric == "max_gate_abs_mean_difference_mm_s"


def test_the_ladder_audits_that_only_the_key_and_its_scale_moved() -> None:
    """A companion setting is refused; the key's own velocity scale is not."""
    from udv_echo_process.analysis.prf_ladder import (
        _require_clean_ofat,
        _require_scaled_velocity_scale,
    )

    entries = list(
        build_prf_ladder(DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT)
        .inputs
    )
    _require_clean_ofat(entries)  # the committed ladder is clean
    _require_scaled_velocity_scale(entries)  # and its scale is the key's consequence
    products = [entry.velo_max_ms * entry.prf_period_us for entry in entries]
    assert (max(products) - min(products)) / (sum(products) / len(products)) < 1e-9
    coupled = list(entries)
    coupled[-1] = coupled[-1].model_copy(update={"emit_power": "high"})
    with pytest.raises(PrfLadderError, match="OFAT ladder"):
        _require_clean_ofat(coupled)
    unscaled = [entry.model_copy(update={"velo_max_ms": VELO_MAX_MM_S[PATHS[0]]}) for entry in entries]
    with pytest.raises(PrfLadderError, match="did not follow the PRF key"):
        _require_scaled_velocity_scale(unscaled)


def test_common_duration_view_and_common_support(ladder) -> None:
    from udv_echo_process.analysis.prf_ladder import PLAN_SUPPORT_MM

    common = ladder.common
    assert (common["nominal_rpm"], common["revolution_s"]) == pytest.approx((500.0, 0.12))
    assert (common["revolutions"], common["window_s"]) == pytest.approx(
        (COMMON_REVOLUTIONS, COMMON_WINDOW_S)
    )
    assert common["revolutions"] == math.floor(
        min(entry.duration_s for entry in ladder.inputs) / 0.12
    )
    # Truncated per recording by the recorded timestamps: the duration is common, the profile counts
    # are not, because the profile rate is not. Every realization of every level is measured.
    assert common["profiles_window"] == {
        path: _window_profiles(path) for path in REALIZATION_PATHS
    }
    assert (common["support_min_mm"], common["support_max_mm"]) == pytest.approx(
        (SUPPORT_MIN_MM, SUPPORT_MAX_MM), abs=1e-9
    )
    assert set(common["gates_in_support"].values()) == {GATES_IN_SUPPORT}
    assert common["support_min_mm"] <= PLAN_SUPPORT_MM[0]
    assert common["support_max_mm"] >= PLAN_SUPPORT_MM[1]


def _window_profiles(relative: str) -> int:
    values, time_s, _depths, _vmax = _decoded(relative)
    del values
    return int(np.count_nonzero(time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9))


def _profile_rate(relative: str) -> float:
    """The recording's actual profile rate, from its own recorded timestamps."""
    _values, time_s, _depths, _vmax = _decoded(relative)
    return float((time_s.size - 1) / (time_s[-1] - time_s[0]))


def _segments(relative: str) -> tuple[int, int]:
    """A recording's matched-segment profile count and whole-segment count, derived here.

    The shared target is the largest 0.1 s multiple fitting five whole segments in the shortest
    record; this file then takes the whole number of its own profiles inside it.
    """
    values, time_s, _depths, _vmax = _decoded(relative)
    period = (time_s[-1] - time_s[0]) / (time_s.size - 1)
    duration = float(time_s[-1] - time_s[0])
    del values
    shortest = min(
        _decoded(path)[1][-1] - _decoded(path)[1][0]
        for path in (PATHS[0], PATHS[1], PATHS[2], PATHS[3], PATHS[4], ANCHOR_PATHS[1])
    )
    target = math.floor(shortest / 5 / 0.1) * 0.1
    profiles = math.floor(target / period)
    return profiles, math.floor(duration / (profiles * period))


def test_distributional_metrics_use_the_common_window_and_support(ladder) -> None:
    """Each realization is measured on its own; each level is their unweighted mean (§8.3 step 5)."""
    for row in ladder.realizations:
        window = _window(row["relative_path"])
        _values, time_s, _depths, vmax = _decoded(row["relative_path"])
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
        # The actual profile rate comes from the timestamps, not from the PRF or a setting.
        period = (time_s[-1] - time_s[0]) / (time_s.size - 1)
        assert row["profile_rate_hz"] == pytest.approx(1.0 / period)
        assert row["profile_rate_hz"] == pytest.approx(_profile_rate(row["relative_path"]))
        if row["relative_path"] in PROFILE_RATE_HZ:  # the five the sweep itself requested
            assert row["profile_rate_hz"] == pytest.approx(PROFILE_RATE_HZ[row["relative_path"]])
        assert row["nyquist_hz"] == pytest.approx(0.5 / period)
        assert row["velo_max_mm_s"] == pytest.approx(vmax)
        assert row["prf_hz"] == pytest.approx(1e6 / row["prf_period_us"])
    # A level's row is the unweighted mean of its realizations' rows.
    by_path = {row["relative_path"]: row for row in ladder.realizations}
    for row in ladder.levels:
        paths = row["realization_paths"].split(";")
        assert row["realizations"] == len(paths)
        for cell in ("mean_mm_s", "rms_mm_s", "zero_fraction", "profiles_window", "profile_rate_hz"):
            assert row[cell] == pytest.approx(
                float(np.mean([by_path[path][cell] for path in paths])), rel=1e-12
            ), cell


def test_the_load_fractions_and_wrap_counts_are_the_committed_definitions(ladder) -> None:
    """``|v| / Vmax`` at the declared fractions, and the half-span wrap criterion."""
    assert WARNING_FRACTIONS == (0.5, 0.75, 0.9, 1.0) and WRAP_STEP_FRACTION == 1.0
    names = ("warning_fraction_half", "warning_fraction_three_quarter",
             "warning_fraction_nine_tenths", "warning_fraction_at_limit")
    for row in ladder.realizations:
        window = _window(row["relative_path"])
        vmax = _decoded(row["relative_path"])[3]
        if row["relative_path"] in VELO_MAX_MM_S:  # the five the sweep itself requested
            assert vmax == pytest.approx(VELO_MAX_MM_S[row["relative_path"]])
        load, steps = np.abs(window) / vmax, np.abs(np.diff(window, axis=0))
        wraps = ((window[:-1] * window[1:]) < 0.0) & (steps >= WRAP_STEP_FRACTION * vmax)
        assert row["load_max_over_velo_max"] == pytest.approx(float(load.max()))
        for name, limit in zip(names, WARNING_FRACTIONS, strict=True):
            assert row[name] == pytest.approx(float(np.count_nonzero(load >= limit) / load.size))
        assert row["samples_beyond_limit"] == int(np.count_nonzero(load > 1.0))
        assert row["wrap_like_events"] == int(np.count_nonzero(wraps))
        assert row["wrap_like_fraction"] == pytest.approx(float(wraps.mean()))
        assert row["max_abs_step_over_velo_max"] == pytest.approx(float(steps.max() / vmax))
        # The criterion is conservative: every counted step reverses sign and reaches Vmax.
        assert not np.any(wraps & ~((window[:-1] * window[1:]) < 0.0))
    # A level's load cells are the unweighted mean of its realizations' cells.
    by_path = {row["relative_path"]: row for row in ladder.realizations}
    for row in ladder.levels:
        paths = row["realization_paths"].split(";")
        for cell in (
            "load_max_over_velo_max", "warning_fraction_half", "warning_fraction_at_limit",
            "wrap_like_fraction", "max_abs_step_over_velo_max",
        ):
            assert row[cell] == pytest.approx(
                float(np.mean([by_path[path][cell] for path in paths])), rel=1e-12
            ), cell
    # The plan's own setting has the most headroom of the five and the 800 us level the least:
    # the largest load is 1.21 of a 115.6 mm/s limit, which is what a wrapped estimate looks like
    # beside the 400 us level's 0.73 of 231.2 mm/s.
    focus = next(row for row in ladder.levels if row["relative_path"] == PATHS[0])
    assert focus["load_max_over_velo_max"] == pytest.approx(FOCUS_LOAD_MAX)
    assert focus["samples_beyond_limit"] == 0 and focus["wrap_like_events"] == 0
    widest = max(ladder.levels, key=lambda row: row["load_max_over_velo_max"])
    assert widest["relative_path"] == PATHS[4]
    assert widest["load_max_over_velo_max"] == pytest.approx(LARGEST_LOAD)
    assert widest["samples_beyond_limit"] > 0 and widest["wrap_like_events"] > 0


def test_the_temporal_grid_is_matched_by_physical_duration_not_profile_count(ladder) -> None:
    temporal = ladder.temporal
    assert ladder.common["segment_target_s"] == pytest.approx(SEGMENT_TARGET_S)
    assert (temporal["segment_step_s"], temporal["min_segments"]) == (0.1, 5)
    assert temporal["nominal_resolution_hz"] == pytest.approx(1.0 / SEGMENT_TARGET_S)
    expected_rates = {path: _profile_rate(path) for path in REALIZATION_PATHS}
    assert temporal["profile_rate_hz"] == pytest.approx(expected_rates)
    assert {path: expected_rates[path] for path in PATHS} == pytest.approx(PROFILE_RATE_HZ)
    assert temporal["profile_rate_spread_relative"] > 0.5  # the rates really differ
    assert temporal["band_hz"][1] <= min(
        cell["usable_bandwidth_hz"] for cell in temporal["cell"].values()
    )
    durations, resolutions = [], []
    for row in ladder.realizations:
        cell = temporal["cell"][row["relative_path"]]
        assert (row["segment_profiles"], row["segments"]) == _segments(row["relative_path"])
        if row["relative_path"] in SEGMENT_PROFILES:  # the five the sweep itself requested
            assert (row["segment_profiles"], row["segments"]) == (
                SEGMENT_PROFILES[row["relative_path"]], SEGMENTS[row["relative_path"]],
            )
        assert cell["profile_period_s"] == pytest.approx(
            1.0 / expected_rates[row["relative_path"]]
        )
        assert {
            "profiles": cell["profiles"], "segments": cell["segments"],
            "duration_s": cell["duration_s"], "resolution_hz": cell["resolution_hz"],
            "usable_bandwidth_hz": cell["usable_bandwidth_hz"],
        } == pytest.approx({
            "profiles": row["segment_profiles"], "segments": row["segments"],
            "duration_s": row["segment_duration_s"],
            "resolution_hz": row["frequency_resolution_hz"],
            "usable_bandwidth_hz": row["usable_bandwidth_hz"],
        })
        durations.append(row["segment_duration_s"])
        resolutions.append(row["frequency_resolution_hz"])
        assert row["usable_bandwidth_hz"] == pytest.approx(
            (row["segment_profiles"] // 2) * row["frequency_resolution_hz"]
        )
        assert row["usable_bandwidth_hz"] <= row["nyquist_hz"] * (1.0 + 1e-9)
    # Every level's matched-segment cells are the unweighted mean of its realizations' cells.
    by_path = {row["relative_path"]: row for row in ladder.realizations}
    for row in ladder.levels:
        paths = row["realization_paths"].split(";")
        for cell in ("segment_profiles", "segment_duration_s", "frequency_resolution_hz",
                     "usable_bandwidth_hz", "segments"):
            assert row[cell] == pytest.approx(
                float(np.mean([by_path[path][cell] for path in paths])), rel=1e-12
            ), cell
    # Matched physical duration to within a profile period, so the resolutions agree to 2 %
    # even though the sample rates differ by two.
    assert max(durations) - min(durations) < SEGMENT_TARGET_S * 0.02
    assert max(resolutions) / min(resolutions) < 1.02


def test_band_density_is_integrated_over_the_actual_frequency_grid() -> None:
    """R5: the band density is the PSD integrated over frequency, not a sum of bins.

    Two representations of one spectral density, one on a uniform grid and one on an unequal grid
    whose in-band edge nodes agree with it, must give the same band density. The pre-correction rule
    — sum the bin values inside the band and divide by the band width — counts bins instead of
    integrating over them, so it returns a different number for a differently spaced grid.
    """
    from udv_echo_process.analysis.prf_ladder import _band_density

    slope, intercept = 0.5, 1.0
    density = lambda f: intercept + slope * np.asarray(f, dtype=float)
    uniform = np.arange(0.0, 10.0 + 0.25, 0.5)
    unequal = np.sort(np.concatenate([uniform, [1.25, 2.25, 3.25]]))
    edges = np.array([1.0, 2.0, 3.0, 4.0])
    uniform_values = _band_density(uniform, density(uniform), edges)
    unequal_values = _band_density(unequal, density(unequal), edges)
    # A linear density integrates exactly, so the two grids agree to rounding.
    assert uniform_values == pytest.approx(unequal_values, rel=1e-12)
    # The same comparison under the retired bin-sum rule does not: the unequal grid carries three
    # extra bins, whose values the old rule added to the same band widths.
    counted = np.array([
        density(unequal)[(unequal >= low) & (unequal < high)].sum() / (high - low)
        for low, high in itertools.pairwise(edges)
    ])
    assert not np.allclose(counted, unequal_values, rtol=1e-6)


def test_the_spectra_are_summarised_only_where_every_recording_has_support(ladder) -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis import reference_repeat as wp1

    bands = ladder.temporal["bands"]
    edges = np.arange(1.0, bands + 2.0) * ladder.temporal["nominal_resolution_hz"]
    assert (edges[0], edges[-1]) == pytest.approx(tuple(ladder.temporal["band_hz"]))
    assert edges[-1] <= min(row["usable_bandwidth_hz"] for row in ladder.levels)
    densities = {}
    for row in ladder.realizations:
        entry = next(e for e in ladder.inputs if e.relative_path == row["relative_path"])
        series = wp1.temporal_series(
            entry, _decoded(row["relative_path"])[0], entry.profile_period_s,
            segment_profiles=row["segment_profiles"],
        )
        assert (series.segment_duration_s, series.segments) == pytest.approx(
            (row["segment_duration_s"], row["segments"])
        )
        assert series.acf_e_folding_lag_s == row["acf_e_folding_lag_s"]
        frequency = np.asarray(series.frequency_hz, dtype=float)
        density = np.asarray(series.psd_mean_mm2_s2_per_hz, dtype=float)
        # The matched segment's top bin is its usable bandwidth, at most that file's full-record
        # Nyquist limit (the two coincide when the segment length is even).
        assert frequency[-1] == pytest.approx(row["usable_bandwidth_hz"])
        assert frequency[-1] <= row["nyquist_hz"] * (1.0 + 1e-9)
        inside = frequency <= row["usable_bandwidth_hz"] + 1e-9
        # Shares and band means are integrals over the file's own grid (R5), not counts of bins.
        band = (float(frequency[0]), min(row["usable_bandwidth_hz"], float(frequency[-1])))
        total = grid.integrate_density(frequency, density, band)
        assert row["psd_share_below_mixer_marker"] == pytest.approx(
            float(grid.integrate_density(frequency, density, (band[0], MARKER_HZ)) / total)
        )
        # Band density: the power the file supports in a band over that band's width.
        densities[row["relative_path"]] = np.array([
            grid.band_density(frequency, density, (low, high))
            for low, high in itertools.pairwise(edges)
        ])
        assert densities[row["relative_path"]].size == bands
        assert inside.any()
    # A level's band density is the unweighted mean of its realizations' densities on the shared
    # bands, and its `psd_share_below_mixer_marker` their unweighted mean.
    by_path = {row["relative_path"]: row for row in ladder.realizations}
    level_densities = {}
    for row in ladder.levels:
        paths = row["realization_paths"].split(";")
        level_densities[row["relative_path"]] = np.mean(
            np.stack([densities[path] for path in paths]), axis=0
        )
        assert row["psd_share_below_mixer_marker"] == pytest.approx(
            float(np.mean([by_path[path]["psd_share_below_mixer_marker"] for path in paths])),
            rel=1e-12,
        )
    for row in ladder.pairs:
        levels = 10.0 * np.log10(
            level_densities[row["faster_path"]] / level_densities[row["slower_path"]]
        )
        worst = int(np.argmax(np.abs(levels)))
        assert row["psd_band_max_abs_level_difference_db"] == pytest.approx(levels[worst])
        assert row["psd_band_difference_frequency_hz"] == pytest.approx(
            0.5 * (edges[worst] + edges[worst + 1])
        )
        assert row["psd_band_median_level_difference_db"] == pytest.approx(float(np.median(levels)))


def test_pair_differences_are_compared_to_the_committed_repeatability_screening_threshold(ladder) -> None:
    # Every unordered pair, on the slower level's own knots, with nothing interpolated: all five
    # files share the identical 1.85 mm grid, so the knot offset is exactly zero.
    total = len(PERIODS) * (len(PERIODS) - 1) // 2
    assert len(ladder.pairs) == total == 10
    assert len({(row["faster_path"], row["slower_path"]) for row in ladder.pairs}) == total
    assert all(
        row["knots"] == GATES_IN_SUPPORT
        and row["knot_spacing_mm"] == pytest.approx(PITCH_MM)
        and row["max_knot_offset_mm"] == 0.0
        and row["prf_gap_hz"] == pytest.approx(row["faster_prf_hz"] - row["slower_prf_hz"])
        for row in ladder.pairs
    )
    means = {
        row["relative_path"]: np.mean(
            np.stack([
                _window(path).mean(axis=0) for path in row["realization_paths"].split(";")
            ]),
            axis=0,
        )
        for row in ladder.levels
    }
    for row in ladder.pairs:
        difference = means[row["faster_path"]] - means[row["slower_path"]]
        flagged = np.abs(difference) > ENVELOPE_MM_S
        assert (row["mean_abs_difference_mm_s"], row["max_abs_difference_mm_s"]) == pytest.approx(
            (float(np.abs(difference).mean()), float(np.abs(difference).max()))
        )
        assert row["knots_above_screening_threshold"] == int(np.count_nonzero(flagged))
        assert row["max_abs_difference_over_screening_threshold"] == pytest.approx(
            row["max_abs_difference_mm_s"] / ENVELOPE_MM_S
        )
        assert bool(row["depth_ranges_above_screening_threshold_mm"]) == bool(np.count_nonzero(flagged))
        # The ranges name the runs of flagged knots on the slower level's own gate grid.
        if row["depth_ranges_above_screening_threshold_mm"]:
            assert re.fullmatch(
                r"\d+(\.\d+)?\.\.\d+(\.\d+)?(; \d+(\.\d+)?\.\.\d+(\.\d+)?)*",
                row["depth_ranges_above_screening_threshold_mm"],
            )
    worst = max(ladder.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    # The 600 us level is now the unweighted mean of prf/600.BDD and res/1-8.BDD (§8.3 step 5),
    # and the res folder's recording of that setting is the faster of the two, so the largest
    # difference in the ladder is the 400 us level against it.
    assert (worst["faster_label"], worst["slower_label"]) == ("400", "600")
    assert worst["slower_path"] == PATHS[2]
    assert worst["max_abs_difference_mm_s"] == pytest.approx(WORST_PAIR_ABS_MM_S)
    assert worst["max_abs_difference_over_screening_threshold"] == pytest.approx(
        WORST_PAIR_ABS_MM_S / ENVELOPE_MM_S
    )
    assert worst["max_abs_difference_depth_mm"] == pytest.approx(13.862666666666666)
    above = [row for row in ladder.pairs if row["knots_above_screening_threshold"]]
    # Six of ten pairs clear the threshold somewhere, always on a handful of local knots.
    assert len(above) == 6
    assert all(row["knots_above_screening_threshold"] <= 8 for row in above)
    assert all(
        len([run for run in row["depth_ranges_above_screening_threshold_mm"].split(";") if run])
        <= row["knots_above_screening_threshold"]
        for row in above
    )


def test_the_decision_answers_whether_250_us_is_justified(tmp_path) -> None:
    from udv_echo_process.analysis.prf_ladder import (
        CANDIDATE_SETTING_US,
        PROVENANCE_NAME,
    )

    _write(tmp_path)
    findings = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))[
        "findings"
    ]
    headroom, bandwidth = findings["velocity_headroom"], findings["temporal_bandwidth"]
    decision = findings["focus_decision"]
    assert headroom["focus_load_max_over_velo_max"] == pytest.approx(FOCUS_LOAD_MAX)
    assert headroom["focus_samples_beyond_limit"] == 0
    assert headroom["focus_wrap_like_events"] == 0
    assert headroom["focus_velo_max_mm_s"] == pytest.approx(VELO_MAX_MM_S[PATHS[0]])
    assert bandwidth["focus_usable_bandwidth_hz"] == pytest.approx(
        max(bandwidth["usable_bandwidth_hz"])
    )
    assert bandwidth["mixer_marker_hz"] == pytest.approx(MARKER_HZ)
    assert "harmonic" in bandwidth["statement"]
    assert (decision["focus_setting_us"], decision["candidate_setting_us"]) == (
        FOCUS_SETTING_US, CANDIDATE_SETTING_US,
    )
    assert decision["candidate_velo_max_mm_s"] == pytest.approx(
        VELO_MAX_MM_S[PATHS[0]] * FOCUS_SETTING_US / CANDIDATE_SETTING_US
    )
    assert decision["velocity_headroom_adequate"] is True
    assert decision["temporal_bandwidth_adequate"] is True
    assert "does not justify" in decision["statement"]
    assert "250" in decision["statement"] and "400" in decision["statement"]
    assert "p-value" not in decision["statement"] and "significant" not in decision["statement"]
    # The numbers the verdict rests on, so the wording cannot be re-tuned into an assertion.
    assert findings["effect_gate"]["pairs_above_screening_threshold"] == 6
    assert len(findings["limitations"]) >= 4
    joined = " ".join(findings["limitations"])
    assert "drift" in joined and "replicate" in joined and "marker" in joined


def test_provenance_records_each_level_s_timestamp_jitter_and_the_estimator_decision(
    tmp_path,
) -> None:
    """R6: every PRF level carries the four interval statistics beside criterion and decision.

    The ladder's files do not share a profile rate, so the criterion is evaluated against each
    level's own top-of-band frequency and each level's own recorded intervals.
    """
    from udv_echo_process.analysis.prf_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    timestamps = document["timestamps"]
    assert timestamps["retained"] is True
    assert timestamps["tolerance_cycles"] == pytest.approx(1.0 / 16.0)
    assert "phase" in timestamps["criterion"] and timestamps["justification"].strip()
    per_input = {item["relative_path"]: item for item in timestamps["per_input"]}
    assert set(per_input) == set(REALIZATION_PATHS)
    for item in per_input.values():
        assert item["criterion_met"] is True
        assert item["intervals"] == item["profiles"] - 1
        assert item["median_dt_s"] > 0.0 and item["rms_deviation_s"] > 0.0
        assert item["max_abs_deviation_s"] > 0.0
        assert item["dt_iqr_s"] >= 0.0
        assert item["f_max_hz"] == pytest.approx(0.5 / item["uniform_period_s"])
        assert item["worst_case_phase_cycles"] == pytest.approx(
            item["max_grid_residual_s"] * item["f_max_hz"]
        )
        assert item["worst_case_phase_cycles"] < 1.0 / 16.0
        # These intervals are quantized to 0.1 ms, so the measured deviation is one quantum.
        assert item["max_abs_deviation_s"] == pytest.approx(1e-4, abs=1e-6)
    assert "uniform" in timestamps["estimator"] and "uniform" in timestamps["decision"]


def test_provenance_records_binding_definitions_views_and_the_caption(tmp_path) -> None:
    from udv_echo_process.analysis.prf_ladder import PROVENANCE_NAME

    _write(tmp_path)
    document = json.loads((tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8"))
    assert (document["artefact"], document["axis"], document["analysis_commit"]) == (
        "prf-ladder", AXIS, COMMIT,
    )
    assert document["manifest"]["sha256"] == (
        f"sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}"
    )
    assert {item["relative_path"] for item in document["inputs"]} == set(REALIZATION_PATHS)
    assert {item["level_path"] for item in document["inputs"]} == set(PATHS)
    aggregation = document["aggregation"]
    assert aggregation["rule"] == "unweighted arithmetic mean over the level's realizations"
    assert (aggregation["levels"], aggregation["recordings"]) == (5, 6)
    assert aggregation["multi_realization_levels"] == [
        {"relative_path": ANCHOR_PATHS[0], "realization_paths": list(ANCHOR_PATHS)}
    ]
    levels_block = {entry["primary_path"]: entry for entry in document["levels"]}
    assert list(levels_block) == list(PATHS)
    anchor = levels_block[ANCHOR_PATHS[0]]
    assert anchor["realization_paths"] == list(ANCHOR_PATHS)
    assert anchor["requested_paths"] == [ANCHOR_PATHS[0]]
    assert anchor["aggregation"] == aggregation["rule"]
    assert [item["relative_path"] for item in anchor["per_realization"]] == list(ANCHOR_PATHS)
    assert [item["own_axis"] for item in anchor["per_realization"]] == [True, False]
    assert [item["requested_axis"] for item in anchor["per_realization"]] == ["prf", "res"]
    scale = document["derived_scale"]
    assert scale["invariant"] == "velo_max_ms x prf_period_us"
    assert max(scale["values"]) - min(scale["values"]) < 1e-4
    constants = document["audited_constants"]
    assert constants["settings"] == list(COUPLED_SETTINGS)
    assert (constants["gates"], constants["resolution_mm"]) == (50, PITCH_MM)
    views = document["views"]
    assert views["time"]["common_duration"]["revolutions"] == COMMON_REVOLUTIONS
    assert views["time"]["common_duration"]["window_s"] == pytest.approx(COMMON_WINDOW_S)
    assert views["depth"]["common_support_min_mm"] == pytest.approx(SUPPORT_MIN_MM)
    assert views["depth"]["contains_plan_window"] is True and views["depth"]["native_grid"]
    grid_view = views["temporal"]["grid"]
    assert grid_view["segment_target_s"] == pytest.approx(SEGMENT_TARGET_S)
    assert sorted(grid_view["per_level"]) == sorted(REALIZATION_PATHS)
    assert grid_view["per_level"][PATHS[0]]["profiles"] == SEGMENT_PROFILES[PATHS[0]]
    assert views["temporal"]["mixer_marker_hz"] == pytest.approx(MARKER_HZ)
    assert "not a phase reference" in views["temporal"]["mixer_setpoint_role"]
    assert views["alignment"]["upsampled"] is False
    assert views["alignment"]["max_knot_offset_over_all_pairs_mm"] == 0.0
    assert {
        "prf_period_us", "velo_max_mm_s", "velocity_scale", "profile_rate_hz",
        "load_over_velo_max", "warning_fractions", "wrap_like_discontinuity", "screening_threshold",
        "matched_segment", "comparison_bands", "mixer_marker", "replicates", "views",
        "realizations", "aggregation",
    } <= set(document["definitions"])
    figure = document["figure"]
    assert figure["path"] == "figures/prf-ladder.png" and len(figure["panels"]) == 2
    assert COMMIT in figure["caption"] and "400" in figure["caption"]
    assert "not a phase reference" in figure["caption"]
    assert "independent experimental replicate" in figure["caption"]
    assert "--analysis-commit" in document["regeneration"]["command"]
    assert (document["tables"]["levels"]["rows"], document["tables"]["pairs"]["rows"]) == (5, 10)


def test_the_wp1_temporal_estimator_default_is_unchanged(ladder) -> None:
    """The shared estimator's new ``segment_profiles`` hook defaults to the committed value."""
    from udv_echo_process.analysis import reference_repeat as wp1

    entry = next(e for e in ladder.inputs if e.relative_path == PATHS[2])
    values = _decoded(entry.relative_path)[0]
    default = wp1.temporal_series(entry, values, entry.profile_period_s)
    explicit = wp1.temporal_series(
        entry, values, entry.profile_period_s, segment_profiles=wp1.SEGMENT_PROFILES
    )
    assert default == explicit and default.segment_profiles == wp1.SEGMENT_PROFILES
    with pytest.raises(wp1.ReferenceRepeatError, match="at least two profiles"):
        wp1.temporal_series(entry, values, entry.profile_period_s, segment_profiles=1)


def test_cli_writes_the_four_artefacts_and_the_committed_ones_regenerate(tmp_path, capsys) -> None:
    """The reviewer-visible WP2 PRF artefacts are exactly what the command writes."""
    from udv_echo_process.analysis.prf_ladder import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
        LEVELS_NAME,
        PAIRS_NAME,
        PROVENANCE_NAME,
        write_prf_ladder,
    )
    from udv_echo_process.cli import _COMMANDS, prf_ladder_main

    assert _COMMANDS["prf-ladder"] is prf_ladder_main
    committed = {
        "levels": REPORT_DIR / LEVELS_NAME, "pairs": REPORT_DIR / PAIRS_NAME,
        "provenance": REPORT_DIR / PROVENANCE_NAME,
        "figure": REPORT_DIR / FIGURES_DIRNAME / FIGURE_NAME,
    }
    for name, path in committed.items():
        assert path.is_file(), f"WP2 PRF must commit {name} ({path})"
    model = build_prf_ladder(
        DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE, analysis_commit=COMMIT
    )
    with pytest.raises(SystemExit) as ok:
        prf_ladder_main([
            "--dataset-root", str(DATA_ROOT), "--report-dir", str(tmp_path),
            "--manifest", str(MANIFEST), "--screening-threshold", str(ENVELOPE),
            "--analysis-commit", COMMIT,
        ])
    assert ok.value.code == 0
    printed = capsys.readouterr().out
    assert "prf" in printed.lower() and "wrap-like" in printed and "decision" in printed
    assert (tmp_path / LEVELS_NAME).is_file() and (tmp_path / PAIRS_NAME).is_file()
    assert (tmp_path / FIGURES_DIRNAME / FIGURE_NAME).is_file()
    recorded = json.loads(committed["provenance"].read_text(encoding="utf-8"))["analysis_commit"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded
    write_prf_ladder(
        DATASET_ROOT, tmp_path / "regenerated", manifest_path=RELATIVE_MANIFEST,
        screening_threshold_path=RELATIVE_ENVELOPE, analysis_commit=recorded,
    )
    levels_text = (tmp_path / LEVELS_NAME).read_text(encoding="utf-8").splitlines()
    pairs_text = (tmp_path / PAIRS_NAME).read_text(encoding="utf-8").splitlines()
    assert levels_text[0] == ",".join(LEVEL_COLUMNS)
    assert pairs_text[0] == ",".join(PAIR_COLUMNS)
    assert (len(levels_text), len(pairs_text)) == (len(model.levels) + 1, len(model.pairs) + 1)
    for name in ("levels", "pairs", "provenance"):
        raw = committed[name].read_bytes()
        assert b"\r\n" not in raw and raw.endswith(b"\n")
        assert str(ROOT).encode() not in raw and b"C:/" not in raw and b"C:\\" not in raw
        actual = (tmp_path / "regenerated" / committed[name].name).read_bytes()
        assert actual.replace(b"\r\n", b"\n") == raw.replace(b"\r\n", b"\n"), name
    assert (
        tmp_path / "regenerated" / FIGURES_DIRNAME / FIGURE_NAME
    ).read_bytes() == committed["figure"].read_bytes()
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    for token in ("prf-ladder", "prf-levels.csv", "prf-pairs.csv"):
        assert token in readme


def test_cli_refuses_a_stale_unscaled_or_absent_inventory_with_named_reasons(tmp_path, capsys) -> None:
    from udv_echo_process.cli import prf_ladder_main

    # The clean-OFAT audit compares *decoded* settings, so a manifest tamper of an unverified
    # setting cannot reach it: the coupled refusal is exercised at unit level, above.
    cases = (
        ("stale.csv", lambda rows: _replace(rows, PATHS[1], duration_s="99"), "stale"),
        ("hash.csv", lambda rows: _replace(rows, PATHS[2], source_sha256="1" * 64), "sha256"),
    )
    for index, (name, mutate, reason) in enumerate(cases):  # each leaves no half-artefact
        broken = _manifest(tmp_path, mutate, name=name)
        target = tmp_path / f"reports{index}"
        with pytest.raises(SystemExit) as refused:
            prf_ladder_main(
                [
                    "--dataset-root", str(DATA_ROOT), "--report-dir", str(target),
                    "--manifest", str(broken), "--screening-threshold", str(_rebound_screening_threshold(tmp_path, broken)),
                    "--analysis-commit", COMMIT,
                ]
            )
        assert refused.value.code == 1
        err = capsys.readouterr().err
        assert reason in err and "Traceback" not in err
        assert not (target / "prf-levels.csv").exists()
    with pytest.raises(SystemExit) as absent:
        prf_ladder_main(  # a missing default manifest is a named refusal, not a traceback
            [
                "--dataset-root", str(DATA_ROOT), "--report-dir", str(tmp_path / "empty"),
                "--analysis-commit", COMMIT,
            ]
        )
    assert absent.value.code == 1
    assert "cannot read the manifest" in capsys.readouterr().err


# ── slice 6: the scientific fingerprint and the setting-based contract (R1, R4) ──────

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
#: The two recordings that carry one decoded fingerprint whatever folder they sit in.


def _perturbed_cell(field: str, current: str) -> str:
    """A value of one cell that is not the committed one and is still a decoded setting."""
    if field in ("emit_power", "sensitivity", "tgc_mode"):
        return "changed"
    return f"{float(current) + 1.0:g}"


def _cell_of(relative: str, field: str) -> str:
    return next(r for r in _rows() if r["relative_path"] == relative)[field]


def _rows() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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

    row = next(r for r in _rows() if r["relative_path"] == ANCHOR_PATHS[1])
    decoded = grid.read_decoded_level(
        DATA_ROOT, row, cells=grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS
    )
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        assert grid.canonical_cell(row[field]) == grid.canonical_cell(
            grid.format_cell(decoded.observed[field])
        ), field


def test_the_prf_contract_holds_every_fingerprint_field_but_the_period_and_its_scale() -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.prf_ladder import ELIGIBILITY

    assert (ELIGIBILITY.axis, ELIGIBILITY.ladder_label) == (AXIS, "PRF")
    assert ELIGIBILITY.varied == ("prf_period_us",)
    # Vmax = c / (4 f0 T) and the PRF in Hz follow the period: they are derived, not settings.
    assert ELIGIBILITY.derived == ("prf_hz", "velo_max_ms")
    every = set(grid.FINGERPRINT_FIELDS) | set(grid.DERIVED_FINGERPRINT_CELLS)
    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    assert set(ELIGIBILITY.identity_fields) == every - allowed
    assert "resolution_mm" in ELIGIBILITY.identity_fields
    assert "emit_freq_khz" in ELIGIBILITY.identity_fields


def test_every_fingerprint_field_is_allowlisted_or_changes_the_row_s_fingerprint(
    tmp_path,
) -> None:
    """R4/R1: perturbing each field either changes identity or is allowlisted for this axis."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.prf_ladder import ELIGIBILITY, level_groups

    allowed = set(ELIGIBILITY.varied) | set(ELIGIBILITY.derived)
    base = next(g for g in level_groups(MANIFEST) if g.key == ("600",))
    assert base.realization_paths == ANCHOR_PATHS
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        value = _perturbed_cell(field, _cell_of(ANCHOR_PATHS[1], field))
        manifest = _manifest(
            tmp_path,
            lambda rows, f=field, v=value: _replace(rows, ANCHOR_PATHS[1], **{f: v}),
        )
        groups = level_groups(manifest)
        at = next(g for g in groups if g.key == ("600",))
        if field in allowed:
            # Allowlisted: the recording keeps realizing 600 us (derived cells) or moves to the
            # level its own key names (the period). Either way it stays eligible.
            assert ANCHOR_PATHS[1] in {
                path for group in groups for path in group.realization_paths
            }, field
        else:
            assert at.realization_paths == (ANCHOR_PATHS[0],), field


def test_the_ladder_carries_the_setting_based_selection_beside_its_levels(ladder) -> None:
    """Plan §8.3 step 2: the selection is recorded on the model; §8.3 step 5 renders it."""
    from udv_echo_process.analysis.prf_ladder import ELIGIBILITY, provenance_document

    assert ladder.eligibility == ELIGIBILITY
    assert [
        tuple(float(value) for value in group.key) for group in ladder.groups if group.in_ladder
    ] == [(float(row["prf_period_us"]),) for row in select_level_rows(MANIFEST)]
    # Step 5: the ladder is the setting-based selection itself, so it holds every eligible level
    # with every recording that realizes each one.
    assert len(ladder.groups) == len(PERIODS)
    assert [row["relative_path"] for row in ladder.levels] == [
        group.primary_path for group in ladder.groups
    ]
    assert [entry.relative_path for entry in ladder.inputs] == list(REALIZATION_PATHS)
    assert [row["relative_path"] for row in ladder.realizations] == list(REALIZATION_PATHS)
    anchor = next(group for group in ladder.groups if group.key == ("600",))
    assert anchor.key_display == "prf_period_us=600"
    assert all(
        group.key_display == f"{group.key_fields[0]}={group.key[0]}" for group in ladder.groups
    )
    assert anchor.realization_paths == ANCHOR_PATHS
    assert anchor.primary_path == ANCHOR_PATHS[0]
    assert anchor.realizations[1].requested_axis == "res"
    assert anchor.realizations[1].fingerprint["velo_max_ms"] == (
        anchor.realizations[0].fingerprint["velo_max_ms"]
    )
    # Step 5 renders the selection into the artefacts: every realization is named and every level
    # mean is published with the per-realization numbers it was aggregated from.
    document = provenance_document(ladder)
    assert document["aggregation"]["recordings"] == len(REALIZATION_PATHS)
    assert document["aggregation"]["multi_realization_levels"] == [
        {"relative_path": ANCHOR_PATHS[0], "realization_paths": list(ANCHOR_PATHS)}
    ]
    assert "realizations" in LEVEL_COLUMNS and "realization_paths" in LEVEL_COLUMNS
    rows = list(csv.DictReader(levels_csv_text(ladder).splitlines()))
    row = next(r for r in rows if r["relative_path"] == ANCHOR_PATHS[0])
    assert row["realizations"] == "2"
    assert row["realization_paths"] == ";".join(ANCHOR_PATHS)
    # Both reference recordings populate the shared anchor level, and the level's own row is their
    # unweighted mean - not either one of them.
    level = next(r for r in ladder.levels if r["relative_path"] == ANCHOR_PATHS[0])
    members = [r for r in ladder.realizations if r["relative_path"] in ANCHOR_PATHS]
    assert [r["relative_path"] for r in members] == list(ANCHOR_PATHS)
    assert level["mean_mm_s"] == pytest.approx(
        float(np.mean([r["mean_mm_s"] for r in members]))
    )
    assert level["mean_mm_s"] != pytest.approx(members[0]["mean_mm_s"])
    assert level["mean_mm_s"] != pytest.approx(members[1]["mean_mm_s"])
    assert len(ladder.pairs) == len(ladder.groups) * (len(ladder.groups) - 1) // 2 == 10
