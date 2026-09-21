"""Focused tests for WP1 — the sparse pass's per-job anchor floors.

The tests pin the three things the review round asked WP1 to keep apart or to state:
the anchors are *block-local* (their job's condition, at the reference window) and not
reference realizations; **drift** (signed, ordered: ``M - B``, ``E - M``, ``E - B``) and
**spread** (``max - min`` over the three) are distinct quantities and the table carries
both; and a scientific row is placed only by its bracket in acquisition order, because
the pass carries no per-recording clock — the file name's stamp is the job's
``sweep_id``, so the residuals are taken against each bracketing anchor rather than
against an invented interpolated instant.

Everything is recomputed here from the committed recordings through the shared loader,
so a change in the artefacts that does not survive the recordings fails.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_anchor_floor as saf
from udv_echo_process.analysis._sparse_pass import (
    SCIENTIFIC_JOBS,
    decode_pass,
    gate_statistics,
    supported_gates,
    supported_mean_of,
)
from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    DESIGNED_WINDOW_S,
    PLAN_PATH,
    REPORT_DIR,
    SparseIngestError,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"


def _copy_dataset(tmp_path: Path) -> Path:
    """A private copy of the committed pass, so a test may mutate it."""
    import shutil

    target = tmp_path / "sparse-mixer-live-1"
    shutil.copytree(ROOT / DATASET_ROOT, target)
    return target


@pytest.fixture(scope="module")
def decoded():
    return decode_pass()


@pytest.fixture(scope="module")
def floor():
    return saf.build_anchor_floor(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(floor):
    return saf.def_document(floor)


# ── the shared views are the frozen table's own ───────────────────────


def test_the_loader_uses_the_wp0_window_and_support(decoded) -> None:
    assert decoded.window_s == DESIGNED_WINDOW_S == 12.0
    assert decoded.window_revolutions == 100
    assert decoded.support_mm[0] == pytest.approx(10.138, rel=1e-12)
    assert decoded.support_mm[1] == pytest.approx(98.938, rel=1e-12)
    assert len(decoded.points) == 26
    orders = [point.binding.order for point in decoded.points]
    assert orders == sorted(orders) == list(range(1, 27))


# ── the anchors are block-local, at the reference window ──────────────


def test_every_scientific_job_carries_three_anchors_at_the_reference_window(
    floor, decoded
) -> None:
    assert [job.job for job in floor.jobs] == list(SCIENTIFIC_JOBS)
    for job in floor.jobs:
        assert [anchor.label for anchor in job.anchors] == [
            label for label, _ in saf.ANCHORS
        ]
        assert [anchor.short for anchor in job.anchors] == ["B", "M", "E"]
        orders = [anchor.order for anchor in job.anchors]
        assert orders == sorted(orders)
        assert len({anchor.sweep_id for anchor in job.anchors}) == 1
        for anchor in job.anchors:
            assert anchor.gates == saf.REFERENCE_WINDOW[1] == 50
            assert anchor.resolution_mm == pytest.approx(1.85, rel=1e-9)
            assert anchor.supported_gates == 49 < anchor.gates
        # the anchors are the *reference window* at the job's own condition, which is
        # the distinction the review round asked for: not a reference realization
        assert job.structure.startswith("B") and job.structure.endswith("E")


def test_anchors_share_their_own_jobs_condition_and_not_the_reference_one(
    floor, decoded
) -> None:
    for job in floor.jobs:
        points = decoded.of_job(job.job)
        for anchor in job.anchors:
            point = next(
                item for item in points if str(item.binding.point.label) == anchor.label
            )
            assert int(point.config.burst_length) == job.burst_length
            assert int(point.config.emissions_per_profile) == job.emissions_per_profile
    # the reference condition is observed by CR1-CR4 alone, and only there
    reference = [
        (int(point.config.burst_length), int(point.config.emissions_per_profile))
        for point in decoded.of_kind("common-reference")
    ]
    assert reference == [(10, 20)] * 4
    assert reference[0] not in {
        (job.burst_length, job.emissions_per_profile) for job in floor.jobs
    }


# ── drift and spread are different evidence ───────────────────────────


def test_drift_is_signed_ordered_and_recomputable(floor, decoded) -> None:
    for job in floor.jobs:
        scalars: dict[str, dict[str, float]] = {}
        for anchor in job.anchors:
            point = next(
                item
                for item in decoded.of_job(job.job)
                if str(item.binding.point.label) == anchor.label
            )
            scalars[anchor.label] = {
                statistic: supported_mean_of(
                    point,
                    window_s=decoded.window_s,
                    support_mm=decoded.support_mm,
                    name=statistic,
                )
                for statistic in saf.STATISTICS
            }
            for statistic, value in scalars[anchor.label].items():
                assert value == pytest.approx(
                    anchor.statistics[statistic], rel=1e-12, abs=1e-15
                )
        for statistic in saf.STATISTICS:
            begin, mid, end = (
                scalars["ctrl-begin"][statistic],
                scalars["ctrl-mid"][statistic],
                scalars["ctrl-end"][statistic],
            )
            assert job.drift[statistic]["drift_mid_minus_begin"] == pytest.approx(
                mid - begin, rel=1e-12, abs=1e-12
            )
            assert job.drift[statistic]["drift_end_minus_mid"] == pytest.approx(
                end - mid, rel=1e-12, abs=1e-12
            )
            assert job.drift[statistic]["drift_end_minus_begin"] == pytest.approx(
                end - begin, rel=1e-12, abs=1e-12
            )
            assert job.spread[statistic] == pytest.approx(
                max(begin, mid, end) - min(begin, mid, end), rel=1e-12, abs=1e-12
            )


def test_spread_and_whole_job_drift_differ_where_the_job_turns(floor) -> None:
    """burst-4 falls monotonically; burst-18 rises and then falls."""
    by_job = {job.job: job for job in floor.jobs}
    four = by_job["burst-4"]
    eighteen = by_job["burst-18"]
    assert four.drift["mean"]["drift_end_minus_begin"] == pytest.approx(
        -four.spread["mean"], rel=1e-12, abs=1e-12
    )
    assert four.drift["mean"]["drift_mid_minus_begin"] < 0
    assert eighteen.drift["mean"]["drift_mid_minus_begin"] > 0
    assert eighteen.drift["mean"]["drift_end_minus_mid"] < 0
    assert (
        abs(eighteen.drift["mean"]["drift_end_minus_begin"]) < eighteen.spread["mean"]
    )


def test_the_two_job_kinds_carry_floors_of_different_size(floor) -> None:
    """The number WP3 will screen its interaction against."""
    spread = {job.job: job.spread["mean"] for job in floor.jobs}
    assert spread["burst-4"] > 9.0 and spread["burst-18"] > 9.0
    for job in ("emissions-8", "emissions-64", "emissions-128"):
        assert spread[job] < 4.0
    assert min(spread["burst-4"], spread["burst-18"]) > 2.5 * max(
        spread["emissions-8"], spread["emissions-64"], spread["emissions-128"]
    )


def test_the_level_moves_more_than_the_robust_spread(floor) -> None:
    """The rig's velocity level drifts; the within-window width barely does."""
    for job in ("burst-4", "burst-18"):
        floor_job = next(item for item in floor.jobs if item.job == job)
        assert floor_job.spread["rms"] > 2.0 * floor_job.spread["iqr"]
    for job in floor.jobs:
        assert job.spread["zero_fraction"] < 0.01


# ── the scientific rows, bracketed by order ───────────────────────────


def test_the_bracket_is_the_acquisition_order_and_is_not_symmetric(floor) -> None:
    for job in floor.jobs:
        labels = [row.label for row in job.bracketed]
        assert len(labels) == len(job.scientific_labels)
        for row in job.bracketed:
            assert row.grid_matches_anchors is not (
                row.residual_vs_left_mean_mm_s is None
            )
            left = next(a for a in job.anchors if a.label == row.between[0])
            right = next(a for a in job.anchors if a.label == row.between[1])
            assert left.order < row.order < right.order
            assert row.sweep_id == left.sweep_id == right.sweep_id
        if job.job.startswith("emissions"):
            # the designated measurement sits between begin and mid; end reports the
            # drift that follows it rather than bracketing it symmetrically
            assert all(
                row.between == ("ctrl-begin", "ctrl-mid") for row in job.bracketed
            )


def test_cross_pitch_rows_carry_no_residual_and_say_which_package_takes_it(
    floor,
) -> None:
    cross = [
        row
        for job in floor.jobs
        if job.job.startswith("burst")
        for row in job.bracketed
    ]
    assert len(cross) == 4
    for row in cross:
        assert not row.grid_matches_anchors
        assert row.residual_vs_left_mean_mm_s is None
        assert row.residual_vs_right_mean_mm_s is None
        assert "WP3" in row.note


def test_same_grid_rows_carry_both_interpolation_extremes(floor, decoded) -> None:
    """The two residuals are the extremes of every linear interpolation."""
    for job in floor.jobs:
        if not job.job.startswith("emissions"):
            continue
        for row in job.bracketed:
            point = next(
                item
                for item in decoded.of_job(job.job)
                if str(item.binding.point.label) == row.label
            )
            row_block = gate_statistics(
                point, window_s=decoded.window_s, support_mm=decoded.support_mm
            )[saf.RESIDUAL_STATISTIC]
            for label, mean_cell, abs_cell, depth_cell in (
                (
                    row.between[0],
                    row.residual_vs_left_mean_mm_s,
                    row.residual_vs_left_max_abs_mm_s,
                    row.residual_vs_left_max_abs_depth_mm,
                ),
                (
                    row.between[1],
                    row.residual_vs_right_mean_mm_s,
                    row.residual_vs_right_max_abs_mm_s,
                    row.residual_vs_right_max_abs_depth_mm,
                ),
            ):
                anchor = next(
                    item
                    for item in decoded.of_job(job.job)
                    if str(item.binding.point.label) == label
                )
                anchor_block = gate_statistics(
                    anchor, window_s=decoded.window_s, support_mm=decoded.support_mm
                )[saf.RESIDUAL_STATISTIC]
                residual = row_block - anchor_block
                worst = int(np.argmax(np.abs(residual)))
                assert mean_cell == pytest.approx(
                    float(np.mean(residual)), rel=1e-12, abs=1e-15
                )
                assert abs_cell == pytest.approx(
                    float(abs(residual[worst])), rel=1e-12, abs=1e-15
                )
                depths = supported_gates(anchor, decoded.support_mm)
                assert depth_cell == pytest.approx(float(depths[worst]), rel=1e-12)


def test_a_depth_averaged_residual_hides_local_structure(floor) -> None:
    """The caution the emissions slice must carry: local residuals exceed the mean."""
    for job in floor.jobs:
        for row in job.bracketed:
            if row.residual_vs_left_mean_mm_s is None:
                continue
            assert row.residual_vs_left_max_abs_mm_s > 2.0 * abs(
                row.residual_vs_left_mean_mm_s
            )


# ── the pass has no per-recording clock, and the artefacts say so ─────


def test_every_recording_of_a_job_shares_one_sweep_id(decoded) -> None:
    for job in SCIENTIFIC_JOBS:
        stamps = {str(point.binding.recording_stamp) for point in decoded.of_job(job)}
        assert len(stamps) == 1
        assert next(iter(stamps))


def test_the_document_names_the_sweep_id_fact_rather_than_a_clock(document) -> None:
    text = document["anchors"]["sweep_id"]
    assert "not a per-recording timestamp" in text
    assert "no such clock" in text
    assert "spans every linear interpolation" in text
    scope = document["scope"]["residual"]
    assert "extremes of every linear interpolation" in scope
    assert "without assuming a time-weight" in scope


def test_job_time_is_accounted_from_the_passs_own_windows(floor, decoded) -> None:
    for job in floor.jobs:
        record = next(item for item in decoded.records if item.job == job.job)
        wall = (
            datetime.fromisoformat(record.finished_at)
            - datetime.fromisoformat(record.started_at)
        ).total_seconds()
        recorded = sum(
            float(point.time_s[-1] - point.time_s[0])
            for point in decoded.of_job(job.job)
        )
        assert job.job_wall_seconds == pytest.approx(wall, rel=1e-12)
        assert job.recorded_seconds == pytest.approx(recorded, rel=1e-12)
        assert job.unaccounted_seconds == pytest.approx(wall - recorded, rel=1e-9)
        assert job.unaccounted_seconds > 0


# ── the artefacts ─────────────────────────────────────────────────────


def test_the_csv_is_the_column_contract_and_carries_every_quantity(floor) -> None:
    text = (REPORT_DIR / saf.CSV_NAME).read_bytes()
    assert text.endswith(b"\n") and b"\r\n" not in text
    rows = list(
        csv.DictReader(
            (REPORT_DIR / saf.CSV_NAME).read_text(encoding="utf-8").splitlines()
        )
    )
    assert tuple(rows[0]) == tuple(saf.CSV_COLUMNS)
    assert len(rows) == len(SCIENTIFIC_JOBS) * len(saf.STATISTICS) * len(saf.QUANTITIES)
    assert {(row["job"], row["statistic"], row["quantity"]) for row in rows} == {
        (job.job, statistic, name)
        for job in floor.jobs
        for statistic in saf.STATISTICS
        for name, _, _ in saf.QUANTITIES
    }
    for row in rows:
        cell_row = next(
            item
            for item in floor.rows
            if (item.job, item.statistic, item.quantity)
            == (row["job"], row["statistic"], row["quantity"])
        )
        assert float(row["begin"]) == pytest.approx(cell_row.begin, rel=1e-11)
        assert float(row["mid"]) == pytest.approx(cell_row.mid, rel=1e-11)
        assert float(row["end"]) == pytest.approx(cell_row.end, rel=1e-11)
        assert float(row["value"]) == pytest.approx(cell_row.value, rel=1e-11)
        assert row["unit"] == cell_row.unit


def test_the_document_carries_the_definitions_the_scope_and_the_gate(
    document, floor
) -> None:
    assert set(document["statistics"]) == set(saf.STATISTICS)
    assert set(document["quantities"]) == {name for name, _, _ in saf.QUANTITIES}
    assert document["quantities"]["anchor_range"]["kind"] == "non-negative"
    assert all(
        document["quantities"][name]["kind"] == "signed"
        for name, _, _ in saf.QUANTITIES
        if name != "anchor_range"
    )
    assert (
        "NOT realizations of the reference condition"
        in document["anchors"]["condition"]
    )
    assert "not a confidence interval" in document["scope"]["not_a_bound"]
    assert "neither prove an axis effect" in document["scope"]["not_a_bound"]
    assert document["analysis_commit"] == COMMIT
    assert document["table_rows"] == len(floor.rows)
    assert document["ok"] is True
    assert set(document["checks"]) == set(floor.checks)
    assert all(document["checks"].values())


def test_the_document_is_depth_resolved_and_keeps_the_four_sweeps_apart(floor) -> None:
    for job in floor.jobs:
        block = next(
            item for item in saf.def_document(floor)["jobs"] if item["job"] == job.job
        )
        depths = block["depth_resolved"]["depths_mm"]
        assert len(depths) == job.depth_resolved.depths_mm.size == 49
        for key in (
            "mean_begin",
            "mean_mid",
            "mean_end",
            "mean_drift_mid_minus_begin",
            "mean_drift_end_minus_mid",
            "iqr_drift_mid_minus_begin",
            "iqr_drift_end_minus_mid",
        ):
            assert len(block["depth_resolved"][key]) == len(depths)
        assert all(anchor["sweep_id"] for anchor in block["anchors"])


def test_the_command_writes_the_same_bytes_twice(tmp_path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for directory in (first, second):
        saf.write_anchor_floor(
            ROOT / DATASET_ROOT,
            directory,
            plan_path=ROOT / PLAN_PATH,
            analysis_commit=COMMIT,
        )
    assert (first / saf.CSV_NAME).read_bytes() == (second / saf.CSV_NAME).read_bytes()
    assert (first / saf.DOC_NAME).read_bytes() == (second / saf.DOC_NAME).read_bytes()
    for job in SCIENTIFIC_JOBS:
        a = (first / saf.FIGURES_DIRNAME / saf.figure_name(job)).read_bytes()
        b = (second / saf.FIGURES_DIRNAME / saf.figure_name(job)).read_bytes()
        assert a == b
        assert a.startswith(b"\x89PNG\r\n\x1a\n")


def test_the_committed_floor_is_reproducible_with_the_recorded_revision(
    tmp_path, monkeypatch
) -> None:
    """The committed pair regenerates byte for byte from the recorded revision."""
    monkeypatch.chdir(ROOT)
    recorded = json.loads((REPORT_DIR / saf.DOC_NAME).read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    saf.write_anchor_floor(
        DATASET_ROOT,
        tmp_path,
        plan_path=PLAN_PATH,
        analysis_commit=recorded,
    )
    for name in (saf.CSV_NAME, saf.DOC_NAME):
        committed = (REPORT_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert (tmp_path / name).read_bytes() == committed


def test_every_job_has_a_figure_and_the_prose_names_the_floors() -> None:
    doc = " ".join((REPORT_DIR / saf.MD_NAME).read_text(encoding="utf-8").split())
    for job in SCIENTIFIC_JOBS:
        assert (REPORT_DIR / saf.FIGURES_DIRNAME / saf.figure_name(job)).is_file()
    assert "block-local anchor controls" in doc
    assert "not a confidence interval" in doc
    assert "no per-recording clock" in doc
    assert "WP3" in doc and "WP4" in doc


# ── the refusals ──────────────────────────────────────────────────────


def test_a_row_without_a_bracketing_anchor_is_refused(decoded) -> None:
    job = "burst-4"
    points = decoded.of_job(job)
    only_begin = [
        point for point in points if str(point.binding.point.label) == "ctrl-begin"
    ]
    blocks = {
        "ctrl-begin": gate_statistics(
            only_begin[0], window_s=decoded.window_s, support_mm=decoded.support_mm
        )
    }
    depths = supported_gates(only_begin[0], decoded.support_mm)
    row = next(point for point in points if str(point.binding.point.label) == "cc1")
    with pytest.raises(saf.AnchorFloorError, match="not bracketed"):
        saf._bracket(decoded, job, row, only_begin, blocks, depths)


def test_a_dataset_missing_an_anchor_is_refused_by_name(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    victim = next(
        path
        for path in dataset.glob("*.BDD")
        if "burst-4-ctrl-mid" in path.name or "burst-4-ctrl-mid" in path.name
    )
    victim.unlink()
    with pytest.raises(SparseIngestError):
        saf.build_anchor_floor(
            dataset, plan_path=ROOT / PLAN_PATH, analysis_commit=COMMIT
        )


def test_a_refusal_writes_no_half_artefact(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    log = dataset / "sparse-mixer-live-1-burst-4.jsonl"
    log.write_text("", encoding="utf-8")
    report = tmp_path / "reports"
    with pytest.raises(SparseIngestError):
        saf.write_anchor_floor(
            dataset, report, plan_path=ROOT / PLAN_PATH, analysis_commit=COMMIT
        )
    assert not (report / saf.CSV_NAME).exists()
    assert not (report / saf.DOC_NAME).exists()
    assert not (report / saf.FIGURES_DIRNAME).exists()


def _plain(text: str) -> str:
    """The report's text with markdown emphasis and wrapping removed, for prose pins."""
    for marker in ("**", "*", "`"):
        text = text.replace(marker, "")
    return " ".join(text.split())


def _job_table_cells(markdown: str) -> dict[str, str]:
    """The report's job table as ``{job: condition cell}``, from the rendered markdown."""
    cells: dict[str, str] = {}
    for line in markdown.splitlines():
        row = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(row) == 8 and row[0].startswith(("burst-", "emissions-")):
            cells[row[0]] = row[1]
    return cells


def test_the_report_table_agrees_with_the_table_it_summarises(floor) -> None:
    """The review's find: the report transposed the emissions jobs' condition.

    The generator was right and only the markdown was wrong, which is exactly why this is
    checked against the published table rather than read by eye: the cells must agree with
    the CSV (and the model) for every job.
    """
    markdown = (REPORT_DIR / saf.MD_NAME).read_text(encoding="utf-8")
    cells = _job_table_cells(markdown)
    assert set(cells) == {job.job for job in floor.jobs}

    raw = (REPORT_DIR / saf.CSV_NAME).read_bytes().decode("utf-8")
    published: dict[str, str] = {}
    for row in csv.DictReader(raw.splitlines()):
        if row["quantity"] == "drift_end_minus_begin" and row["statistic"] == "mean":
            published[row["job"]] = (
                f"{row['burst_length']} / {row['emissions_per_profile']}"
            )
    assert set(published) == set(cells)
    for job in floor.jobs:
        assert cells[job.job] == published[job.job], job.job
        assert cells[job.job] == (
            f"{job.burst_length} / {job.emissions_per_profile}"
        ), job.job

    # the three emissions jobs are the ones that were transposed: burst 10, emissions ladder
    assert cells["emissions-8"] == "10 / 8"
    assert cells["emissions-64"] == "10 / 64"
    assert cells["emissions-128"] == "10 / 128"


def test_the_report_states_the_measured_ratio_not_an_order_of_magnitude(floor) -> None:
    """The floors are several-fold apart, and the report must say what was measured."""
    burst = [
        job.spread["mean"] for job in floor.jobs if job.job.startswith("burst")
    ]
    emissions = [
        job.spread["mean"] for job in floor.jobs if job.job.startswith("emissions")
    ]
    low = min(burst) / max(emissions)
    high = max(burst) / min(emissions)
    assert 2.5 < low < 3.5
    assert 7.0 < high < 8.5

    doc = _plain((REPORT_DIR / saf.MD_NAME).read_text(encoding="utf-8"))
    assert "order of magnitude" not in doc
    assert f"{low:.1f}×" in doc
    assert f"{high:.1f}×" in doc
    assert f"{min(burst):.3f}" in doc and f"{max(burst):.3f}" in doc
    assert f"{min(emissions):.3f}" in doc and f"{max(emissions):.3f}" in doc


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_one(
    tmp_path, capsys
) -> None:
    from udv_echo_process.cli import _COMMANDS

    assert "sparse-anchor-floor" in _COMMANDS
    with pytest.raises(SystemExit) as exit_code:
        saf.anchor_floor_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--report-dir",
                str(tmp_path / "reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert exit_code.value.code == 0
    assert "checks  : all pass" in capsys.readouterr().out

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as failed:
        saf.anchor_floor_main(
            [
                "--dataset-root",
                str(broken),
                "--report-dir",
                str(tmp_path / "broken-reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert failed.value.code == 1
