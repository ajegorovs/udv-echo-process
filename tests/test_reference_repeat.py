"""Focused tests for the WP1 reference-repeat bound (plan ``WP1``).

Written RED first: ``analysis.reference_repeat``, its CLI verb and the three
reviewer-visible artefacts (``reference-repeat.csv``,
``reference-repeat.provenance.json``, ``figures/reference-repeat.png``) did not
exist, so this module failed at import.

The tests pin the *definitions* WP1 must not drift on:

- the pair is selected from ``manifest.csv`` (the WP0 artefact), never from a
  hand-written filename list, and both rows must agree with the bytes on disk;
- the common-duration view is the largest integer number of nominal 500-RPM
  revolutions that fits both recordings;
- per-gate mean / median / robust spread (IQR) / RMS (DC-inclusive) / zero
  fraction are computed with the declared conventions;
- the signed difference is ``prf/600.BDD - res/1-8.BDD`` at every gate;
- autocorrelation and PSD use one shared segment duration and frequency
  resolution for both recordings, on the identical 50-gate grid;
- regenerating from the recorded generator commit reproduces the committed
  artefacts byte for byte.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis.reference_repeat import (
    COLUMNS,
    DATASET_ROOT,
    NOMINAL_REVOLUTION_S,
    NOMINAL_RPM,
    REPEAT_PAIR,
    GateRow,
    ReferenceRepeatError,
    build_reference_repeat,
    common_revolution_count,
    gate_metrics,
    select_repeat_rows,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
DATA_ROOT = ROOT / DATASET_ROOT
#: The paths the CLI defaults to, relative to the repository root: the
#: committed artefacts are generated with exactly these, so that is what a
#: regeneration has to pass to be byte-identical.
RELATIVE_MANIFEST = Path("reports/mixer-sensitivity-analysis/manifest.csv")
MANIFEST = ROOT / RELATIVE_MANIFEST
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

#: The two rows of the only same-settings repeat, as ``manifest.csv`` records
#: them (WP0). Bound by relative path, not by axis or label guessing.
FILE_A = "prf/600.BDD"
FILE_B = "res/1-8.BDD"
SHA_A = "cd47a0dded66bb879acc8f177fe263ccf2fcc8b665d23468c4c185a47b59a8de"
SHA_B = "92ef87e3df57b443d37d62ed6cb84a99a5a4173c3b3c646e1a4d6c50b0fb67de"

#: 96 nominal revolutions at 500 RPM fit both 14.956 s and 11.5529 s.
COMMON_REVOLUTIONS = 96
COMMON_WINDOW_S = 11.52
COMMON_PROFILES = 515


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


# ── slice 1: selection, time view, metric definitions ──────────────────────


def test_repeat_pair_is_the_only_same_settings_repeat() -> None:
    assert REPEAT_PAIR == (FILE_A, FILE_B)
    assert NOMINAL_RPM == 500.0
    assert NOMINAL_REVOLUTION_S == pytest.approx(0.12)


def test_select_repeat_rows_binds_manifest_paths_and_source_hashes() -> None:
    row_a, row_b = select_repeat_rows(MANIFEST)
    assert (row_a["relative_path"], row_b["relative_path"]) == REPEAT_PAIR
    assert (row_a["source_sha256"], row_b["source_sha256"]) == (SHA_A, SHA_B)
    # The manifest hash is the bytes on disk, not a copy of the dataset README.
    for row in (row_a, row_b):
        digest = hashlib.sha256((DATA_ROOT / row["relative_path"]).read_bytes())
        assert row["source_sha256"] == digest.hexdigest()
    # Same operating-parameter signature: one repeat, not two settings.
    assert {field for field in row_a if row_a[field] != row_b[field]} == {
        "axis",
        "requested_label",
        "relative_path",
        "source_sha256",
        "profiles",
        "duration_s",
        "velocity_min_mm_s",
        "velocity_max_mm_s",
        "zero_fraction",
    }


def test_select_repeat_rows_rejects_a_missing_row(tmp_path) -> None:
    manifest = _manifest(
        tmp_path,
        lambda rows: [r for r in rows if r["relative_path"] != FILE_B],
    )
    with pytest.raises(ReferenceRepeatError, match=FILE_B):
        select_repeat_rows(manifest)


def test_select_repeat_rows_rejects_a_duplicated_row(tmp_path) -> None:
    def duplicate(rows):
        match = next(r for r in rows if r["relative_path"] == FILE_A)
        return [*rows, dict(match)]

    manifest = _manifest(tmp_path, duplicate)
    with pytest.raises(ReferenceRepeatError, match="exactly one"):
        select_repeat_rows(manifest)


def test_build_rejects_a_manifest_hash_that_does_not_match_the_bytes(tmp_path) -> None:
    def break_hash(rows):
        for row in rows:
            if row["relative_path"] == FILE_B:
                row["source_sha256"] = "0" * 64
        return rows

    manifest = _manifest(tmp_path, break_hash)
    with pytest.raises(ReferenceRepeatError, match="sha256"):
        build_reference_repeat(DATA_ROOT, manifest, analysis_commit=COMMIT)


def test_build_rejects_a_manifest_cell_that_no_longer_decodes(tmp_path) -> None:
    """A stale row must stop the comparison, not silently change the window."""

    def break_duration(rows):
        for row in rows:
            if row["relative_path"] == FILE_A:
                row["duration_s"] = "1.0"
                row["profiles"] = "42"
        return rows

    manifest = _manifest(tmp_path, break_duration)
    with pytest.raises(ReferenceRepeatError, match="does not match the decoded"):
        build_reference_repeat(DATA_ROOT, manifest, analysis_commit=COMMIT)


def test_build_rejects_a_selected_file_that_is_not_there(tmp_path) -> None:
    dataset = tmp_path / "dataset" / "prf"
    dataset.mkdir(parents=True)
    (dataset / "600.BDD").write_bytes((DATA_ROOT / FILE_A).read_bytes())
    with pytest.raises(ReferenceRepeatError, match="is not a file"):
        build_reference_repeat(
            tmp_path / "dataset", MANIFEST, analysis_commit=COMMIT
        )


def test_common_revolution_count_is_the_largest_integer_fit() -> None:
    assert common_revolution_count([14.956, 11.5529]) == COMMON_REVOLUTIONS
    assert COMMON_REVOLUTIONS * NOMINAL_REVOLUTION_S <= 11.5529
    assert (COMMON_REVOLUTIONS + 1) * NOMINAL_REVOLUTION_S > 11.5529
    # Degenerate inputs are refused rather than silently truncated to zero.
    with pytest.raises(ReferenceRepeatError):
        common_revolution_count([])
    with pytest.raises(ReferenceRepeatError):
        common_revolution_count([0.05])


def test_gate_metrics_use_the_declared_definitions() -> None:
    values = np.array([[0.0, 1.0], [2.0, 3.0], [4.0, 0.0]])
    metrics = gate_metrics(values)
    assert set(metrics) == {"mean", "median", "iqr", "rms", "zero_fraction"}
    assert metrics["mean"] == pytest.approx([2.0, 4.0 / 3.0])
    assert metrics["median"] == pytest.approx([2.0, 1.0])
    # Robust spread is the interquartile range, linear-interpolated percentiles.
    assert metrics["iqr"] == pytest.approx([3.0 - 1.0, 2.0 - 0.5])
    # RMS is about zero: a DC offset raises it, unlike a standard deviation.
    assert metrics["rms"] == pytest.approx(
        [np.sqrt(20.0 / 3.0), np.sqrt(10.0 / 3.0)]
    )
    assert metrics["zero_fraction"] == pytest.approx([1.0 / 3.0, 1.0 / 3.0])
    shifted = gate_metrics(values + 10.0)
    assert shifted["mean"] == pytest.approx(metrics["mean"] + 10.0)
    assert shifted["rms"][0] > metrics["rms"][0]
    assert shifted["zero_fraction"] == pytest.approx([0.0, 0.0])


def test_common_duration_view_keeps_the_same_profiles_in_both_recordings() -> None:
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    assert model.common.revolutions == COMMON_REVOLUTIONS
    assert model.common.revolution_s == pytest.approx(NOMINAL_REVOLUTION_S)
    assert model.common.window_s == pytest.approx(COMMON_WINDOW_S)
    assert model.common.profiles_a == model.common.profiles_b == COMMON_PROFILES
    assert model.common.gates == 50
    # Same window, same duration, so the distributional summaries are comparable.
    assert model.input_a.duration_s == pytest.approx(14.956)
    assert model.input_b.duration_s == pytest.approx(11.5529)
    assert model.common.window_s <= model.input_b.duration_s


def test_rows_are_depth_resolved_and_the_difference_is_signed() -> None:
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    assert len(model.rows) == 50
    assert [row.gate_index for row in model.rows] == list(range(50))
    assert model.rows[0].depth_mm == pytest.approx(10.1626666667)
    assert model.rows[-1].depth_mm == pytest.approx(100.812666667)
    # Every difference field is (prf/600) - (res/1-8), field by field.
    for row in model.rows:
        assert row.diff_mean_mm_s == pytest.approx(
            row.prf_600_mean_mm_s - row.res_1_8_mean_mm_s
        )
        assert row.diff_median_mm_s == pytest.approx(
            row.prf_600_median_mm_s - row.res_1_8_median_mm_s
        )
        assert row.diff_iqr_mm_s == pytest.approx(
            row.prf_600_iqr_mm_s - row.res_1_8_iqr_mm_s
        )
        assert row.diff_rms_mm_s == pytest.approx(
            row.prf_600_rms_mm_s - row.res_1_8_rms_mm_s
        )
        assert row.diff_zero_fraction == pytest.approx(
            row.prf_600_zero_fraction - row.res_1_8_zero_fraction
        )
    # Not a vacuous test: at least one gate moves in each direction.
    diffs = [row.diff_mean_mm_s for row in model.rows]
    assert min(diffs) < 0.0 < max(diffs)


def test_envelope_bounds_every_gate_and_names_where_it_is_worst() -> None:
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    envelope = model.envelope
    assert envelope.metric == "max_gate_abs_mean_difference_mm_s"
    assert envelope.value_mm_s > 0.0
    worst = max(model.rows, key=lambda row: abs(row.diff_mean_mm_s))
    assert envelope.value_mm_s == pytest.approx(abs(worst.diff_mean_mm_s))
    assert envelope.gate_index == worst.gate_index
    assert envelope.depth_mm == pytest.approx(worst.depth_mm)
    assert all(
        abs(row.diff_mean_mm_s) <= envelope.value_mm_s + 1e-12 for row in model.rows
    )
    assert envelope.median_abs_mean_difference_mm_s == pytest.approx(
        float(np.median([abs(row.diff_mean_mm_s) for row in model.rows]))
    )


def test_gate_row_contract_matches_the_csv_columns() -> None:
    assert tuple(GateRow.model_fields) == COLUMNS
    assert COLUMNS[0] == "gate_index"
    assert COLUMNS[1] == "depth_mm"
    assert re.fullmatch(r"[0-9a-f]{64}", SHA_A)


# ── slice 2: temporal autocorrelation and PSD on the identical gate grid ───


def test_temporal_analysis_uses_one_shared_segment_duration_and_resolution() -> (
    None
):
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    temporal = model.temporal
    series_a, series_b = temporal.series
    assert temporal.segment_profiles == 86
    assert series_a.segment_profiles == series_b.segment_profiles == 86
    # Identical segment duration and frequency resolution, exactly - not to a
    # tolerance that hides a different time base.
    assert series_a.segment_duration_s == series_b.segment_duration_s
    assert temporal.segment_duration_s == series_a.segment_duration_s
    assert temporal.frequency_resolution_hz == pytest.approx(
        temporal.profile_rate_hz / temporal.segment_profiles
    )
    assert temporal.segment_duration_s == pytest.approx(
        (temporal.segment_profiles - 1) / temporal.profile_rate_hz
    )
    assert temporal.nyquist_hz == pytest.approx(temporal.profile_rate_hz / 2.0)
    # Non-overlapping segments tile each full record from t = 0.
    assert (series_a.segments, series_b.segments) == (7, 6)
    assert series_a.profiles_analysed == 7 * 86 == 602
    assert series_b.profiles_analysed == 6 * 86 == 516
    # The temporal view is the full record, not the common-duration window.
    assert series_a.profiles_analysed > model.common.profiles_a
    assert series_a.gates == series_b.gates == model.common.gates == 50


def test_acf_is_normalized_and_shares_one_lag_grid() -> None:
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    temporal = model.temporal
    series_a, series_b = temporal.series
    assert series_a.lag_s == series_b.lag_s
    assert len(series_a.lag_s) == temporal.acf_max_lag_profiles + 1 == 44
    assert series_a.lag_s[0] == 0.0
    assert series_a.lag_s[1] == pytest.approx(1.0 / temporal.profile_rate_hz)
    for series in (series_a, series_b):
        assert series.acf_mean[0] == pytest.approx(1.0)
        assert max(series.acf_mean) <= 1.0 + 1e-9
        assert min(series.acf_mean) >= -1.0
        assert series.acf_p10[0] <= series.acf_mean[0] <= series.acf_p90[0]
        # Lag is reported in nominal revolutions beside seconds.
        assert series.lag_revolutions[1] == pytest.approx(
            series.lag_s[1] / NOMINAL_REVOLUTION_S
        )
    # Measured decorrelation is a property of these signals, not an assumption.
    assert series_a.acf_e_folding_lag_s == pytest.approx(
        series_a.lag_s[5], abs=1.0 / temporal.profile_rate_hz
    )
    assert series_b.acf_e_folding_lag_s == pytest.approx(
        series_b.lag_s[4], abs=1.0 / temporal.profile_rate_hz
    )
    assert 5.0 * series_a.lag_s[1] < NOMINAL_REVOLUTION_S


def test_psd_shares_one_frequency_grid_and_stays_non_negative() -> None:
    model = build_reference_repeat(DATA_ROOT, MANIFEST, analysis_commit=COMMIT)
    temporal = model.temporal
    series_a, series_b = temporal.series
    assert series_a.frequency_hz == series_b.frequency_hz
    assert series_a.frequency_hz[0] == 0.0
    assert len(series_a.frequency_hz) == temporal.segment_profiles // 2 + 1 == 44
    assert series_a.frequency_hz[-1] == pytest.approx(temporal.nyquist_hz)
    assert series_a.frequency_hz[1] == pytest.approx(
        temporal.frequency_resolution_hz
    )
    for series in (series_a, series_b):
        assert min(series.psd_mean_mm2_s2_per_hz) > 0.0
        assert min(series.psd_p10_mm2_s2_per_hz) > 0.0
        assert series.psd_p10_mm2_s2_per_hz[1] <= series.psd_mean_mm2_s2_per_hz[1]
        assert series.psd_mean_mm2_s2_per_hz[1] <= series.psd_p90_mm2_s2_per_hz[1]
    assert temporal.mixer_setpoint_hz == pytest.approx(NOMINAL_RPM / 60.0)
    assert temporal.band_hz == (0.5, 20.0)
    assert temporal.band_max_abs_level_difference_db > 0.0
    assert temp_difference(temporal) == pytest.approx(
        temporal.band_max_abs_level_difference_db
    )
    assert temporal.band_hz[0] <= temporal.band_max_difference_frequency_hz
    assert temporal.band_max_difference_frequency_hz <= temporal.band_hz[1]


def temp_difference(temporal) -> float:
    """Largest |10 log10(psd_a / psd_b)| inside the declared band, recomputed."""
    freq = np.asarray(temporal.series[0].frequency_hz)
    a = np.asarray(temporal.series[0].psd_mean_mm2_s2_per_hz)
    b = np.asarray(temporal.series[1].psd_mean_mm2_s2_per_hz)
    inside = (freq >= temporal.band_hz[0]) & (freq <= temporal.band_hz[1])
    return float(np.max(np.abs(10.0 * np.log10(a[inside] / b[inside]))))


def test_shared_profile_period_is_refused_when_the_rates_disagree() -> None:
    from udv_echo_process.analysis.reference_repeat import shared_profile_period_s

    assert shared_profile_period_s([0.02238922155688623, 0.02238934108527132]) == (
        pytest.approx(0.022389281321078775)
    )
    with pytest.raises(ReferenceRepeatError, match="profile rate"):
        shared_profile_period_s([0.0224, 0.015])
    with pytest.raises(ReferenceRepeatError):
        shared_profile_period_s([0.0224])


# ── slice 3: artefacts, CLI, determinism ──────────────────────────────────


def _write(tmp_path: Path, name: str = "a", **kwargs):
    from udv_echo_process.analysis.reference_repeat import write_reference_repeat

    # The repository-relative paths the CLI defaults to, not this checkout's
    # absolute ones: the artefacts must carry no machine-specific path.
    return write_reference_repeat(
        DATASET_ROOT,
        tmp_path / name,
        manifest_path=RELATIVE_MANIFEST,
        analysis_commit=COMMIT,
        **kwargs,
    )


def test_csv_reproduces_an_independent_recomputation(tmp_path, monkeypatch) -> None:
    """The table is re-derived here from the reader, not from the module."""
    from udv_echo_process.analysis.reference_repeat import (
        CSV_NAME,
        format_cell,
    )

    monkeypatch.chdir(ROOT)
    _write(tmp_path)
    rows = _rows(tmp_path / "a" / CSV_NAME)
    assert list(rows[0]) == list(COLUMNS)
    assert len(rows) == 50
    assert [int(row["gate_index"]) for row in rows] == list(range(50))
    assert rows[0]["depth_mm"] == "10.1626666667"
    assert rows[-1]["depth_mm"] == "100.812666667"

    from udv_echo_process.io import load

    windows = []
    for relative in REPEAT_PAIR:
        stream = load(DATA_ROOT / relative).recording.streams[0]
        time_s = np.asarray(stream.data.time_s, dtype=float)
        values = np.asarray(stream.data.values, dtype=float)
        windows.append(values[time_s <= time_s[0] + COMMON_WINDOW_S + 1e-9])
    first, second = windows
    assert first.shape == second.shape == (COMMON_PROFILES, 50)
    for gate in (0, 25, 49):
        column_a, column_b = first[:, gate], second[:, gate]
        expected = {
            "prf_600_mean_mm_s": column_a.mean(),
            "prf_600_median_mm_s": float(np.median(column_a)),
            "prf_600_iqr_mm_s": float(np.percentile(column_a, 75) - np.percentile(column_a, 25)),
            "prf_600_rms_mm_s": float(np.sqrt(np.mean(column_a**2))),
            "prf_600_zero_fraction": float(np.count_nonzero(column_a == 0.0) / column_a.size),
            "res_1_8_mean_mm_s": column_b.mean(),
            "res_1_8_median_mm_s": float(np.median(column_b)),
            "res_1_8_iqr_mm_s": float(np.percentile(column_b, 75) - np.percentile(column_b, 25)),
            "res_1_8_rms_mm_s": float(np.sqrt(np.mean(column_b**2))),
            "res_1_8_zero_fraction": float(np.count_nonzero(column_b == 0.0) / column_b.size),
        }
        row = rows[gate]
        for column, value in expected.items():
            # The table pins 12 significant digits; a differently ordered
            # summation can move the last one, so equality is numeric here.
            assert float(row[column]) == pytest.approx(
                value, rel=1e-10, abs=1e-12
            ), (gate, column)
        assert float(row["prf_600_mean_mm_s"]) == pytest.approx(
            float(column_a.mean()), rel=1e-10, abs=1e-12
        )
        assert float(row["diff_mean_mm_s"]) == pytest.approx(
            float(column_a.mean() - column_b.mean()), rel=1e-10, abs=1e-12
        ), gate
        assert float(row["diff_rms_mm_s"]) == pytest.approx(
            float(np.sqrt(np.mean(column_a**2)) - np.sqrt(np.mean(column_b**2))),
            rel=1e-10,
            abs=1e-12,
        ), gate
    # Every float cell is written with the shared 12-significant-digit format.
    for row in rows:
        for column, cell in row.items():
            if column not in {"gate_index"}:
                assert cell == format_cell(float(cell)), (column, cell)


def test_written_artefacts_are_byte_for_byte_reproducible(tmp_path, monkeypatch) -> None:
    from udv_echo_process.analysis.reference_repeat import (
        CSV_NAME,
        FIGURE_NAME,
        FIGURES_DIRNAME,
        PROVENANCE_NAME,
    )

    monkeypatch.chdir(ROOT)
    _write(tmp_path, "a")
    _write(tmp_path, "b")
    for name in (CSV_NAME, PROVENANCE_NAME):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    figure_a = (tmp_path / "a" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    figure_b = (tmp_path / "b" / FIGURES_DIRNAME / FIGURE_NAME).read_bytes()
    assert figure_a == figure_b
    assert figure_a.startswith(b"\x89PNG\r\n\x1a\n")
    for name in (CSV_NAME, PROVENANCE_NAME):
        blob = (tmp_path / "a" / name).read_bytes()
        assert b"\r" not in blob
        assert blob.endswith(b"\n")
        assert str(ROOT).encode() not in blob
        # No checkout-specific absolute path may reach an artefact: a clone
        # elsewhere has to regenerate the same bytes.
        assert b"C:/" not in blob
        assert b"C:\\" not in blob
        assert b"udv-echo-process" not in blob


def test_provenance_records_the_binding_definitions_and_views(tmp_path, monkeypatch) -> None:
    from udv_echo_process.analysis.reference_repeat import PROVENANCE_NAME

    monkeypatch.chdir(ROOT)
    _write(tmp_path)
    document = json.loads(
        (tmp_path / "a" / PROVENANCE_NAME).read_text(encoding="utf-8")
    )
    assert document["analysis_commit"] == COMMIT
    assert document["manifest"]["sha256"] == (
        f"sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}"
    )
    inputs = {item["relative_path"]: item for item in document["inputs"]}
    assert set(inputs) == set(REPEAT_PAIR)
    assert inputs[FILE_A]["source_sha256"] == SHA_A
    assert inputs[FILE_B]["source_sha256"] == SHA_B
    # Difference orientation, units and every metric definition are explicit.
    assert document["difference"]["definition"] == f"{FILE_A} minus {FILE_B}"
    assert document["difference"]["units"] == "mm/s"
    assert "interquartile" in document["definitions"]["iqr"]
    assert "about zero" in document["definitions"]["rms"]
    assert "exactly equal to 0.0" in document["definitions"]["zero_fraction"]
    # Time view and depth view, plus the temporal analysis parameters.
    common = document["views"]["common_duration"]
    assert common["revolutions"] == COMMON_REVOLUTIONS
    assert common["nominal_rpm"] == 500.0
    assert common["window_s"] == pytest.approx(COMMON_WINDOW_S)
    temporal = document["views"]["temporal"]
    assert temporal["segment_profiles"] == 86
    assert temporal["frequency_resolution_hz"] == pytest.approx(0.5193515061958194)
    assert temporal["nyquist_hz"] == pytest.approx(22.332114766420233)
    assert temporal["profile_rate_hz"] == pytest.approx(44.664229532840466)
    assert temporal["segments"] == {"prf/600.BDD": 7, "res/1-8.BDD": 6}
    assert temporal["mixer_setpoint_hz"] == pytest.approx(500.0 / 60.0)
    assert "marker" in temporal["mixer_setpoint_role"]
    envelope = document["envelope"]
    assert envelope["metric"] == "max_gate_abs_mean_difference_mm_s"
    assert envelope["value_mm_s"] > 0.0
    assert envelope["scope"].startswith("upper bound")
    # The caption a reviewer reads beside the figure states the caveats.
    caption = document["figure"]["caption"]
    assert COMMIT in caption
    assert "not a phase reference" in caption
    assert "not independent" in caption
    assert "prf/600.BDD minus res/1-8.BDD" in caption
    assert document["figure"]["path"] == "figures/reference-repeat.png"
    assert "reference-repeat" in document["regeneration"]["command"]
    assert "--analysis-commit" in document["regeneration"]["command"]


def test_figure_is_a_reviewer_visible_multi_panel_image(tmp_path, monkeypatch) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    from udv_echo_process.analysis.reference_repeat import (
        FIGURE_NAME,
        FIGURES_DIRNAME,
    )

    monkeypatch.chdir(ROOT)
    _write(tmp_path)
    path = tmp_path / "a" / FIGURES_DIRNAME / FIGURE_NAME
    assert path.stat().st_size > 40_000
    image = plt.imread(path)
    height, width = image.shape[:2]
    assert (height, width) == (1200, 1500)
    # Not a blank canvas: the four panels carry ink.
    assert float(image[:, :, :3].std()) > 0.05


def test_cli_writes_the_three_artefacts_and_exits_zero(tmp_path, capsys) -> None:
    from udv_echo_process.analysis.reference_repeat import (
        CSV_NAME,
        FIGURE_NAME,
        FIGURES_DIRNAME,
        PROVENANCE_NAME,
    )
    from udv_echo_process.cli import reference_repeat_main

    with pytest.raises(SystemExit) as excinfo:
        reference_repeat_main(
            [
                "--dataset-root",
                str(DATA_ROOT),
                "--report-dir",
                str(tmp_path),
                "--manifest",
                str(MANIFEST),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 0
    assert (tmp_path / CSV_NAME).is_file()
    assert (tmp_path / PROVENANCE_NAME).is_file()
    assert (tmp_path / FIGURES_DIRNAME / FIGURE_NAME).is_file()
    out = capsys.readouterr().out
    assert FILE_A in out and FILE_B in out
    assert "mm/s" in out


def test_cli_exits_one_without_a_traceback_on_a_stale_manifest(tmp_path, capsys) -> None:
    from udv_echo_process.cli import reference_repeat_main

    manifest = _manifest(
        tmp_path,
        lambda rows: [
            {**row, "source_sha256": "0" * 64}
            if row["relative_path"] == FILE_B
            else row
            for row in rows
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        reference_repeat_main(
            [
                "--dataset-root",
                str(DATA_ROOT),
                "--report-dir",
                str(tmp_path / "reports"),
                "--manifest",
                str(manifest),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "sha256" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "reports" / "reference-repeat.csv").exists()


def test_committed_artefacts_match_a_regeneration(tmp_path, monkeypatch) -> None:
    """The reviewer-visible WP1 artefacts are exactly what the command produces."""
    from udv_echo_process.analysis.reference_repeat import (
        CSV_NAME,
        FIGURE_NAME,
        FIGURES_DIRNAME,
        PROVENANCE_NAME,
        write_reference_repeat,
    )

    monkeypatch.chdir(ROOT)
    committed = {
        "csv": REPORT_DIR / CSV_NAME,
        "provenance": REPORT_DIR / PROVENANCE_NAME,
        "figure": REPORT_DIR / FIGURES_DIRNAME / FIGURE_NAME,
    }
    for name, path in committed.items():
        assert path.is_file(), f"WP1 must commit {name} ({path})"
    recorded = json.loads(
        committed["provenance"].read_text(encoding="utf-8")
    )["analysis_commit"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded
    write_reference_repeat(
        DATASET_ROOT,
        tmp_path,
        manifest_path=RELATIVE_MANIFEST,
        analysis_commit=recorded,
    )

    def normalized(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    for name in ("csv", "provenance"):
        assert normalized(tmp_path / committed[name].name) == normalized(
            committed[name]
        ), name
    assert (tmp_path / FIGURES_DIRNAME / FIGURE_NAME).read_bytes() == committed[
        "figure"
    ].read_bytes()


def test_report_readme_documents_the_wp1_regeneration() -> None:
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    assert "reference-repeat" in readme
    assert "--analysis-commit" in readme
    assert "figures/reference-repeat.png" in readme
