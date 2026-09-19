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
WORST_PAIR_ABS_MM_S = 37.514761734905456  # prf/400.BDD minus prf/500.BDD at 13.8627 mm
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


def _rebound_envelope(tmp_path: Path, manifest: Path) -> Path:
    """The committed WP1 envelope re-bound to a copied manifest's own hash."""
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
        envelope_path=RELATIVE_ENVELOPE, analysis_commit=COMMIT,
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
        (PATHS[1], "600.0", "one level per PRF period"),
    ):
        broken = _manifest(
            tmp_path,
            lambda rows, relative=relative, cell=cell: _replace(rows, relative, prf_period_us=cell),
        )
        with pytest.raises(PrfLadderError, match=pattern):
            select_level_rows(broken)


def test_build_refuses_stale_hash_derived_cells_coupling_or_unbound_envelope(tmp_path) -> None:
    for cell, value in (("gates", "49"), ("velo_max_ms", "231.206375266"), ("prf_hz", "2500")):
        stale = _manifest(tmp_path, lambda rows, c=cell, v=value: _replace(rows, PATHS[4], **{c: v}))
        with pytest.raises(PrfLadderError, match="stale inventory|does not match the decoded"):
            build_prf_ladder(
                DATASET_ROOT, stale, _rebound_envelope(tmp_path, stale), analysis_commit=COMMIT
            )
    wrong = _manifest(tmp_path, lambda rows: _replace(rows, PATHS[3], source_sha256="0" * 64))
    with pytest.raises(PrfLadderError, match="sha256 mismatch"):
        build_prf_ladder(
            DATASET_ROOT, wrong, _rebound_envelope(tmp_path, wrong), analysis_commit=COMMIT
        )
    with pytest.raises(PrfLadderError, match="cannot read the WP1 envelope"):
        build_prf_ladder(DATASET_ROOT, RELATIVE_MANIFEST, tmp_path / "absent.json",
                         analysis_commit=COMMIT)
    # The committed envelope records the committed manifest's hash: another inventory must not be
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
    assert floor["role"].startswith("upper bound on same-settings repeatability")
    assert ladder.envelope.value_mm_s == pytest.approx(ENVELOPE_MM_S)
    assert ladder.envelope.metric == "max_gate_abs_mean_difference_mm_s"


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
    # Truncated per file by the recorded timestamps: the duration is common, the profile counts
    # are not, because the profile rate is not.
    assert common["profiles_window"] == WINDOW_PROFILES
    assert (common["support_min_mm"], common["support_max_mm"]) == pytest.approx(
        (SUPPORT_MIN_MM, SUPPORT_MAX_MM), abs=1e-9
    )
    assert set(common["gates_in_support"].values()) == {GATES_IN_SUPPORT}
    assert common["support_min_mm"] <= PLAN_SUPPORT_MM[0]
    assert common["support_max_mm"] >= PLAN_SUPPORT_MM[1]


def test_distributional_metrics_use_the_common_window_and_support(ladder) -> None:
    for row in ladder.levels:
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
        assert row["profile_rate_hz"] == pytest.approx(PROFILE_RATE_HZ[row["relative_path"]])
        assert row["nyquist_hz"] == pytest.approx(0.5 / period)
        assert row["velo_max_mm_s"] == pytest.approx(vmax)
        assert row["prf_hz"] == pytest.approx(1e6 / row["prf_period_us"])


def test_the_load_fractions_and_wrap_counts_are_the_committed_definitions(ladder) -> None:
    """``|v| / Vmax`` at the declared fractions, and the half-span wrap criterion."""
    assert WARNING_FRACTIONS == (0.5, 0.75, 0.9, 1.0) and WRAP_STEP_FRACTION == 1.0
    names = ("warning_fraction_half", "warning_fraction_three_quarter",
             "warning_fraction_nine_tenths", "warning_fraction_at_limit")
    for row in ladder.levels:
        window, vmax = _window(row["relative_path"]), VELO_MAX_MM_S[row["relative_path"]]
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
    assert temporal["profile_rate_hz"] == pytest.approx(PROFILE_RATE_HZ)
    assert temporal["profile_rate_spread_relative"] > 0.5  # the rates really differ
    assert temporal["band_hz"][1] <= min(
        cell["usable_bandwidth_hz"] for cell in temporal["cell"].values()
    )
    durations, resolutions = [], []
    for entry, row in zip(ladder.inputs, ladder.levels, strict=True):
        cell = temporal["cell"][str(entry.profile_period_s)]
        assert (row["segment_profiles"], row["segments"]) == (
            SEGMENT_PROFILES[row["relative_path"]], SEGMENTS[row["relative_path"]],
        )
        assert cell == pytest.approx({
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
    # Matched physical duration to within a profile period, so the resolutions agree to 2 %
    # even though the sample rates differ by two.
    assert max(durations) - min(durations) < SEGMENT_TARGET_S * 0.02
    assert max(resolutions) / min(resolutions) < 1.02


def test_the_spectra_are_summarised_only_where_every_recording_has_support(ladder) -> None:
    from udv_echo_process.analysis import reference_repeat as wp1

    bands = ladder.temporal["bands"]
    edges = np.arange(1.0, bands + 2.0) * ladder.temporal["nominal_resolution_hz"]
    assert (edges[0], edges[-1]) == pytest.approx(tuple(ladder.temporal["band_hz"]))
    assert edges[-1] <= min(row["usable_bandwidth_hz"] for row in ladder.levels)
    densities = {}
    for entry, row in zip(ladder.inputs, ladder.levels, strict=True):
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
        assert row["psd_share_below_mixer_marker"] == pytest.approx(
            float(density[inside & (frequency < MARKER_HZ)].sum() / density[inside].sum())
        )
        # Band density: the power the file supports in a band over that band's width.
        densities[row["relative_path"]] = np.array([
            density[inside & (frequency >= low) & (frequency < high)].sum() / (high - low)
            for low, high in itertools.pairwise(edges)
        ])
        assert densities[row["relative_path"]].size == bands
    for row in ladder.pairs:
        levels = 10.0 * np.log10(densities[row["faster_path"]] / densities[row["slower_path"]])
        worst = int(np.argmax(np.abs(levels)))
        assert row["psd_band_max_abs_level_difference_db"] == pytest.approx(levels[worst])
        assert row["psd_band_difference_frequency_hz"] == pytest.approx(
            0.5 * (edges[worst] + edges[worst + 1])
        )
        assert row["psd_band_median_level_difference_db"] == pytest.approx(float(np.median(levels)))


def test_pair_differences_are_compared_to_the_committed_repeatability_envelope(ladder) -> None:
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
    means = {row["relative_path"]: _window(row["relative_path"]).mean(axis=0) for row in ladder.levels}
    for row in ladder.pairs:
        difference = means[row["faster_path"]] - means[row["slower_path"]]
        flagged = np.abs(difference) > ENVELOPE_MM_S
        assert (row["mean_abs_difference_mm_s"], row["max_abs_difference_mm_s"]) == pytest.approx(
            (float(np.abs(difference).mean()), float(np.abs(difference).max()))
        )
        assert row["knots_above_envelope"] == int(np.count_nonzero(flagged))
        assert row["max_abs_difference_over_envelope"] == pytest.approx(
            row["max_abs_difference_mm_s"] / ENVELOPE_MM_S
        )
        assert bool(row["depth_ranges_above_envelope_mm"]) == bool(np.count_nonzero(flagged))
        # The ranges name the runs of flagged knots on the slower level's own gate grid.
        if row["depth_ranges_above_envelope_mm"]:
            assert re.fullmatch(
                r"\d+(\.\d+)?\.\.\d+(\.\d+)?(; \d+(\.\d+)?\.\.\d+(\.\d+)?)*",
                row["depth_ranges_above_envelope_mm"],
            )
    worst = max(ladder.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    assert (worst["faster_label"], worst["slower_label"]) == ("400", "500")
    assert worst["max_abs_difference_mm_s"] == pytest.approx(WORST_PAIR_ABS_MM_S)
    assert worst["max_abs_difference_over_envelope"] == pytest.approx(
        WORST_PAIR_ABS_MM_S / ENVELOPE_MM_S
    )
    assert worst["max_abs_difference_depth_mm"] == pytest.approx(13.862666666666666)
    above = [row for row in ladder.pairs if row["knots_above_envelope"]]
    # Eight of ten pairs clear the bound somewhere, always on a handful of local knots.
    assert len(above) == 8
    assert all(row["knots_above_envelope"] <= 8 for row in above)
    assert all(
        len([run for run in row["depth_ranges_above_envelope_mm"].split(";") if run])
        <= row["knots_above_envelope"]
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
    assert findings["effect_gate"]["pairs_above_envelope"] == 8
    assert len(findings["limitations"]) >= 4
    joined = " ".join(findings["limitations"])
    assert "drift" in joined and "replicate" in joined and "marker" in joined


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
    assert {item["relative_path"] for item in document["inputs"]} == set(PATHS)
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
    assert sorted(grid_view["per_level"]) == sorted(PATHS)
    assert grid_view["per_level"][PATHS[0]]["profiles"] == SEGMENT_PROFILES[PATHS[0]]
    assert views["temporal"]["mixer_marker_hz"] == pytest.approx(MARKER_HZ)
    assert "not a phase reference" in views["temporal"]["mixer_setpoint_role"]
    assert views["alignment"]["upsampled"] is False
    assert views["alignment"]["max_knot_offset_over_all_pairs_mm"] == 0.0
    assert {
        "prf_period_us", "velo_max_mm_s", "velocity_scale", "profile_rate_hz",
        "load_over_velo_max", "warning_fractions", "wrap_like_discontinuity", "envelope",
        "matched_segment", "comparison_bands", "mixer_marker", "replicates", "views",
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
            "--manifest", str(MANIFEST), "--envelope", str(ENVELOPE),
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
        envelope_path=RELATIVE_ENVELOPE, analysis_commit=recorded,
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
                    "--manifest", str(broken), "--envelope", str(_rebound_envelope(tmp_path, broken)),
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
