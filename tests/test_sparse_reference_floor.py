"""Focused tests for WP2 — the sparse pass's between-run reference floor.

The tests pin what the review round asked WP2 to preserve: the four reference runs stay
**four individually visible measurements** in **real campaign order** (their own jobs'
manifest windows), their six pairwise differences are published depth-resolved *and*
reduced, nothing is averaged into a synthetic reference, and the floor is stated as two
named endpoints so the depth-averaged one can be compared like for like with WP1's
anchor floors.

Every number is recomputed here from the committed recordings through the shared loader.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_reference_floor as srf
from udv_echo_process.analysis._sparse_pass import (
    REFERENCE_JOBS,
    decode_pass,
    gate_statistics,
    supported_gates,
    supported_mean_of,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"
REPORT_DIR = ROOT / "reports" / "sparse-mixer-live-1"


def _plain(text: str) -> str:
    """The document's text with markdown emphasis and wrapping removed, for prose pins."""
    for marker in ("**", "*", "`"):
        text = text.replace(marker, "")
    return " ".join(text.split())


@pytest.fixture(scope="module")
def decoded():
    return decode_pass()


@pytest.fixture(scope="module")
def floor():
    return srf.build_reference_floor(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(floor):
    return srf.def_document(floor)


# ── four runs, one condition, real campaign order ─────────────────────


def test_the_four_reference_runs_are_individually_present(floor) -> None:
    assert [run.label for run in floor.runs] == ["cr1", "cr2", "cr3", "cr4"]
    assert sorted(run.job for run in floor.runs) == sorted(REFERENCE_JOBS)
    assert [run.step for run in floor.runs] == [2, 4, 6, 8]
    assert len({run.label for run in floor.runs}) == 4
    assert all(run.supported_gates == 49 < run.gates == 50 for run in floor.runs)
    assert all(run.resolution_mm == pytest.approx(1.85, rel=1e-9) for run in floor.runs)


def test_the_runs_are_ordered_in_campaign_time(floor, decoded) -> None:
    starts = [run.job_started_at for run in floor.runs]
    assert starts == sorted(starts)
    for run in floor.runs:
        record = next(item for item in decoded.records if item.job == run.job)
        assert run.job_started_at == str(record.started_at)
        assert run.job_finished_at == str(record.finished_at)
    # the campaign is ordered by those windows, and the four are spread over it
    first = datetime.fromisoformat(starts[0])
    last = datetime.fromisoformat(starts[-1])
    assert (last - first).total_seconds() > 600.0


def test_the_four_share_one_decoded_condition(decoded) -> None:
    conditions = {
        (
            int(point.config.burst_length),
            int(point.config.emissions_per_profile),
            int(point.config.n_gates),
            round(float(point.config.resolution_mm), 6),
        )
        for point in decoded.of_kind("common-reference")
    }
    assert conditions == {(10, 20, 50, 1.85)}
    assert srf.REFERENCE_CONDITION == {
        "burst_length": 10.0,
        "emissions_per_profile": 20.0,
        "resolution_mm": 1.85,
        "n_gates": 50.0,
    }


def test_the_run_statistics_are_recomputable_from_the_recordings(
    floor, decoded
) -> None:
    for run in floor.runs:
        point = next(
            item
            for item in decoded.of_kind("common-reference")
            if str(item.binding.point.label) == run.label
        )
        for statistic in srf.STATISTICS:
            assert run.statistics[statistic] == pytest.approx(
                supported_mean_of(
                    point,
                    window_s=decoded.window_s,
                    support_mm=decoded.support_mm,
                    name=statistic,
                ),
                rel=1e-12,
                abs=1e-15,
            )


# ── the pairs, the two endpoints, and no synthetic reference ──────────


def test_the_six_pairs_are_depth_resolved_and_recomputable(floor, decoded) -> None:
    assert len(floor.pairs) == 6
    assert {(pair.left, pair.right) for pair in floor.pairs} == {
        ("cr1", "cr2"),
        ("cr1", "cr3"),
        ("cr1", "cr4"),
        ("cr2", "cr3"),
        ("cr2", "cr4"),
        ("cr3", "cr4"),
    }
    blocks = {
        run.label: gate_statistics(
            next(
                item
                for item in decoded.of_kind("common-reference")
                if str(item.binding.point.label) == run.label
            ),
            window_s=decoded.window_s,
            support_mm=decoded.support_mm,
        )[srf.FLOOR_STATISTIC]
        for run in floor.runs
    }
    depths = supported_gates(
        next(
            item
            for item in decoded.of_kind("common-reference")
            if str(item.binding.point.label) == "cr1"
        ),
        decoded.support_mm,
    )
    for pair in floor.pairs:
        difference = blocks[pair.left] - blocks[pair.right]
        worst = int(np.argmax(np.abs(difference)))
        assert pair.mean_difference_mm_s == pytest.approx(
            float(np.mean(difference)), rel=1e-12, abs=1e-15
        )
        assert pair.rms_difference_mm_s == pytest.approx(
            float(np.sqrt(np.mean(np.square(difference)))), rel=1e-12, abs=1e-15
        )
        assert pair.max_abs_difference_mm_s == pytest.approx(
            float(abs(difference[worst])), rel=1e-12, abs=1e-15
        )
        assert pair.max_abs_depth_mm == pytest.approx(float(depths[worst]), rel=1e-12)
        assert pair.job_start_separation_min > 0


def test_the_two_endpoints_are_different_numbers_from_the_same_pairs(floor) -> None:
    assert floor.floor_mm_s == pytest.approx(
        max(pair.max_abs_difference_mm_s for pair in floor.pairs), rel=1e-12
    )
    assert floor.averaged_floor_mm_s == pytest.approx(
        max(abs(pair.mean_difference_mm_s) for pair in floor.pairs), rel=1e-12
    )
    assert floor.floor_mm_s > floor.averaged_floor_mm_s
    assert floor.floor_pair == floor.averaged_floor_pair == ("cr3", "cr4")
    assert floor.floor_statistic == "mean"
    assert "per-depth" in floor.floor_endpoint
    assert "depth-averaged" in floor.averaged_endpoint


def test_the_floor_is_not_ordered_by_elapsed_time(floor) -> None:
    """The widest separation in time is not the largest difference."""
    by_pair = {(pair.left, pair.right): pair for pair in floor.pairs}
    widest = max(floor.pairs, key=lambda pair: pair.job_start_separation_min)
    assert (widest.left, widest.right) == ("cr1", "cr4")
    assert widest.max_abs_difference_mm_s < floor.floor_mm_s
    assert by_pair[floor.floor_pair].job_start_separation_min < widest.job_start_separation_min


def test_the_depth_resolved_floor_exceeds_the_averaged_one_and_lands_near_field(
    floor,
) -> None:
    assert floor.floor_depth_mm == pytest.approx(21.238, abs=5e-3)
    near = [pair for pair in floor.pairs if pair.max_abs_depth_mm < 25.0]
    assert len(near) == 5, "the near field carries most pairs' largest difference"


def test_nothing_averages_the_four_runs_into_a_reference(floor, document) -> None:
    """The average is the information WP2 exists to estimate, so it must not exist."""
    assert document["no_synthetic_reference"].startswith("the four runs are published")
    keys = set(document["depth_resolved"])
    assert {"cr1", "cr2", "cr3", "cr4"} <= keys
    assert not any("mean_of" in key or "average" in key for key in keys)
    for key in ("cr1", "cr2", "cr3", "cr4"):
        profile = np.asarray(document["depth_resolved"][key], dtype=float)
        assert profile.size == 49
    stacked = np.vstack(
        [document["depth_resolved"][key] for key in ("cr1", "cr2", "cr3", "cr4")]
    )
    averaged = stacked.mean(axis=0)
    for key in ("cr1", "cr2", "cr3", "cr4"):
        assert not np.allclose(
            np.asarray(document["depth_resolved"][key], dtype=float), averaged
        )


def test_the_document_states_both_endpoints_and_the_caveat(document, floor) -> None:
    floor_block = document["floor"]
    assert floor_block["depth_resolved"]["value_mm_s"] == pytest.approx(
        floor.floor_mm_s, rel=1e-12
    )
    assert floor_block["depth_averaged"]["value_mm_s"] == pytest.approx(
        floor.averaged_floor_mm_s, rel=1e-12
    )
    assert "like for like" in floor_block["depth_averaged"]["endpoint"]
    assert "not a confidence interval" in floor_block["note"]
    assert "not a separability criterion" in floor_block["note"]
    assert "neither proves an axis effect" in floor_block["note"]
    assert floor_block["pairs_reduced"] == 6
    assert document["reference_condition"]["declared"] == srf.REFERENCE_CONDITION
    assert "four runs" in document["reference_condition"]["note"]
    assert "block-local" in document["reference_condition"]["note"]


def test_the_document_definitions_and_gate(document, floor) -> None:
    assert set(document["definitions"]) == set(srf.STATISTICS)
    assert document["analysis_commit"] == COMMIT
    assert document["ok"] is True
    assert set(document["checks"]) == set(floor.checks)
    assert all(document["checks"].values())
    assert len(document["checks"]) == 10
    assert all(run["job_started_at"] for run in document["runs"])
    assert len(document["pairs"]) == 6


# ── the artefacts ─────────────────────────────────────────────────────


def test_the_csv_carries_the_runs_then_the_pairs(floor) -> None:
    raw = (REPORT_DIR / srf.CSV_NAME).read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    lines = raw.decode("utf-8").split("\n")
    assert lines[0].split(",") == list(srf.CSV_COLUMNS)
    blocks = [line for line in lines if line.startswith("run,")]
    assert len(blocks) == len(floor.runs) * len(srf.STATISTICS)
    assert lines[len(blocks) + 1] == ""
    assert lines[len(blocks) + 2].split(",") == list(srf.PAIR_COLUMNS)
    header = len(blocks) + 2
    # DictReader consumes its first line as the header, so the header line leads
    pairs = list(csv.DictReader(lines[header : header + 1 + len(floor.pairs)]))
    assert len(pairs) == 6
    for row in pairs:
        match = next(
            pair
            for pair in floor.pairs
            if (pair.left, pair.right) == (row["left"], row["right"])
        )
        assert float(row["mean_difference_mm_s"]) == pytest.approx(
            match.mean_difference_mm_s, rel=1e-11
        )
        assert float(row["max_abs_difference_mm_s"]) == pytest.approx(
            match.max_abs_difference_mm_s, rel=1e-11
        )
        assert float(row["job_start_separation_min"]) == pytest.approx(
            match.job_start_separation_min, rel=1e-11
        )


def test_the_command_writes_the_same_bytes_twice(tmp_path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for directory in (first, second):
        srf.write_reference_floor(
            ROOT / "data" / "sparse-mixer-live-1",
            directory,
            plan_path=ROOT / "examples" / "sparse-mixer-live-1" / "run-plan.json",
            analysis_commit=COMMIT,
        )
    assert (first / srf.CSV_NAME).read_bytes() == (second / srf.CSV_NAME).read_bytes()
    assert (first / srf.DOC_NAME).read_bytes() == (second / srf.DOC_NAME).read_bytes()
    figure_a = (first / srf.FIGURES_DIRNAME / srf.FIGURE_NAME).read_bytes()
    figure_b = (second / srf.FIGURES_DIRNAME / srf.FIGURE_NAME).read_bytes()
    assert figure_a == figure_b
    assert figure_a.startswith(b"\x89PNG\r\n\x1a\n")


def test_the_committed_floor_is_reproducible_with_the_recorded_revision(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(ROOT)
    recorded = json.loads((REPORT_DIR / srf.DOC_NAME).read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    srf.write_reference_floor(
        Path("data/sparse-mixer-live-1"),
        tmp_path,
        plan_path=Path("examples/sparse-mixer-live-1/run-plan.json"),
        analysis_commit=recorded,
    )
    for name in (srf.CSV_NAME, srf.DOC_NAME):
        committed = (REPORT_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert (tmp_path / name).read_bytes() == committed
    committed_figure = (REPORT_DIR / srf.FIGURES_DIRNAME / srf.FIGURE_NAME).read_bytes()
    assert (tmp_path / srf.FIGURES_DIRNAME / srf.FIGURE_NAME).read_bytes() == (
        committed_figure
    )


def test_the_prose_states_the_endpoints_and_the_three_consequences() -> None:
    doc = " ".join((REPORT_DIR / srf.MD_NAME).read_text(encoding="utf-8").split())
    assert "four measurements kept four" in doc.lower()
    assert "depth-resolved floor" in doc and "depth-averaged floor" in doc
    assert "not a confidence interval" in doc
    assert "no per-minute" not in doc  # the rate claim must not be made at all
    assert "The ordering by time is not the ordering by difference" in doc
    assert "WP3" in doc and "WP4" in doc


# ── the refusals ──────────────────────────────────────────────────────


def test_a_pass_with_fewer_than_four_reference_runs_is_refused(decoded) -> None:
    fewer = decoded._replace(
        points=tuple(
            point
            for point in decoded.points
            if point.binding.job.kind == "common-reference"
            and str(point.binding.point.label) != "cr4"
        )
    )
    with pytest.raises(srf.ReferenceFloorError, match="expected 4"):
        srf._reference_runs(fewer)


def test_a_malformed_manifest_window_is_refused() -> None:
    with pytest.raises(srf.ReferenceFloorError, match="ISO timestamps"):
        srf._job_start_separation_min("nonsense", "also-nonsense", "cr1/cr2")


def test_the_pair_separation_is_recomputed_from_the_jobs_manifest_windows(floor) -> None:
    """`job_start_separation_min` is the jobs' starts apart, not a recording interval."""
    windows = {run.job: run.job_started_at for run in floor.runs}
    by_job = {run.label: run.job for run in floor.runs}
    for pair in floor.pairs:
        left = datetime.fromisoformat(windows[by_job[pair.left]])
        right = datetime.fromisoformat(windows[by_job[pair.right]])
        expected = abs((right - left).total_seconds()) / 60.0
        assert pair.job_start_separation_min == pytest.approx(expected, rel=1e-12)
        # the campaign is minutes long, so none of these is a recording-to-recording gap
        assert pair.job_start_separation_min > 1.0


def test_the_document_labels_the_separation_and_defines_it(document) -> None:
    """The review's ask: the artifact must not let 5.3 min read as a recording interval."""
    assert set(document["pair_columns"]) | {"left", "right"} == set(srf.PAIR_COLUMNS)
    separation = document["pair_columns"]["job_start_separation_min"]
    assert separation.startswith("the difference between the two runs' jobs'")
    assert "NOT a recording-to-recording interval" in separation
    assert "no per-recording clock" in separation
    assert "sweep_id" in separation
    assert all(
        value for value in document["pair_columns"].values()
    ), "every pair column carries a definition"


def test_the_prose_labels_the_separation_and_narrows_the_replication_claim() -> None:
    doc = _plain((REPORT_DIR / srf.MD_NAME).read_text(encoding="utf-8"))
    assert "job-start separation" in doc.lower()
    assert "not a recording-to-recording interval" in doc
    assert "repeated observations of the common-reference condition" in doc
    assert (
        "independent replication of the pitch, burst or emissions treatment levels" in doc
    )
    assert "do not replicate anything" not in doc
    assert "| pair | apart |" not in doc


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_one(
    tmp_path, capsys
) -> None:
    from udv_echo_process.cli import _COMMANDS

    assert "sparse-reference-floor" in _COMMANDS
    with pytest.raises(SystemExit) as exit_code:
        srf.reference_floor_main(
            [
                "--dataset-root",
                (ROOT / "data" / "sparse-mixer-live-1").as_posix(),
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
        srf.reference_floor_main(
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
