"""Focused tests for the sparse pass's WP0 ingest (plan ``WP0``).

Written RED first: ``analysis.sparse_inventory``, its CLI verb and the two
reviewer-visible artefacts (``points.csv``, ``qc-summary.json``) did not exist,
so this module failed at import. The tests pin:

- the artefact contract: the row/column contract, one row per committed
  recording, and the pass's own shape (nine jobs, 26 points, the per-job counts);
- the binding discipline: every row's identity, label, order and condition come
  from the plan and the pass's own record, and the committed bytes confirm them;
- the two provenance rules the pass's README states: the achieved period is
  measured from the stored timestamps and the logs' ``timing.target_s`` still
  reproduces the *retired* planning expectation;
- the two shared views (a common window derived from the retained spans, and the
  common physical support) and the QC gate;
- byte-for-byte reproducibility, and the committed report artefacts against a
  fresh regeneration with the recorded commit;
- the refusal paths: a log rewritten to the later law, a recording the pass does
  not claim, a dataset the plan does not answer to, and a failed build leaving no
  half-artefact behind.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis.sparse_inventory import (
    COLUMNS,
    DATASET_ROOT,
    EXPECTED_JOB_COUNTS,
    EXPECTED_RECORDINGS,
    PLAN_PATH,
    PLAN_WINDOWS,
    POINTS_NAME,
    QC_NAME,
    REQUESTED_DURATION_S,
    RETIRED_PERIOD_TRANSFER_S,
    USABLE_INTERVAL_S,
    SparseIngestError,
    build_sparse_ingest,
    common_window_s,
    discover_recordings,
    read_run_record,
    write_sparse_ingest,
)
from udv_echo_process.cli import sparse_inventory_main
from udv_echo_process.io import load

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "sparse-mixer-live-1"
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

#: The pass's own job order and the number of recordings each job spends.
JOB_STEPS: tuple[tuple[int, str, int], ...] = (
    (1, "burst-4", 5),
    (2, "common-reference-1", 1),
    (3, "burst-18", 5),
    (4, "common-reference-2", 1),
    (5, "emissions-8", 4),
    (6, "common-reference-3", 1),
    (7, "emissions-64", 4),
    (8, "common-reference-4", 1),
    (9, "emissions-128", 4),
)

#: The three block-local controls every scientific job repeats, in plan order.
CONTROLS: tuple[str, ...] = ("ctrl-begin", "ctrl-mid", "ctrl-end")


def _rows(path: Path | None = None) -> list[dict[str, str]]:
    """The committed (or given) points table, as dicts."""
    text = (path or (REPORT_DIR / POINTS_NAME)).read_text(encoding="utf-8")
    return list(csv.DictReader(text.splitlines()))


@pytest.fixture(scope="module")
def ingest():
    return build_sparse_ingest(analysis_commit=COMMIT)


# ── the artefact contract ─────────────────────────────────────────────


def test_discovery_is_the_dataset_root_and_holds_twenty_six_recordings() -> None:
    files = discover_recordings(ROOT / DATASET_ROOT)
    assert len(files) == EXPECTED_RECORDINGS == 26
    assert len({path.name for path in files}) == len(files)
    assert [path.name for path in files] == sorted(path.name for path in files)


def test_points_csv_is_the_column_contract_one_row_per_recording(ingest) -> None:
    text = (REPORT_DIR / POINTS_NAME).read_text(encoding="utf-8")
    assert text.endswith("\n") and "\r\n" not in text
    reader = csv.reader(text.splitlines())
    header = next(reader)
    assert tuple(header) == COLUMNS
    rows = list(reader)
    assert len(rows) == EXPECTED_RECORDINGS == ingest.points_rows
    for row in rows:
        assert len(row) == len(COLUMNS)


def test_row_order_is_the_pass_order_and_the_jobs_are_the_plans(ingest) -> None:
    rows = ingest.rows
    assert [int(row["order"]) for row in rows] == list(range(1, len(rows) + 1))
    steps = [int(row["step"]) for row in rows]
    assert steps == sorted(steps)
    seen: list[tuple[int, str]] = []
    for row in rows:
        pair = (int(row["step"]), row["job"])
        if not seen or seen[-1] != pair:
            seen.append(pair)
    assert seen == [(step, job) for step, job, _ in JOB_STEPS]


def test_each_job_spends_the_recordings_the_designs_rows_predict(ingest) -> None:
    assert ingest.job_counts == dict(sorted(EXPECTED_JOB_COUNTS.items()))
    counted: dict[int, int] = {}
    for row in ingest.rows:
        counted[int(row["step"])] = counted.get(int(row["step"]), 0) + 1
    assert counted == {step: count for step, _job, count in JOB_STEPS}


def test_row_identity_label_and_stamp_come_from_the_pass_record(ingest) -> None:
    for row in ingest.rows:
        assert row["identity"] == f"{row['relative_path'].rsplit('-', 1)[0]}"
        assert row["relative_path"] == f"{row['identity']}-{row['recording_stamp']}.BDD"
        assert re.fullmatch(r"\d{8}T\d{6}", row["recording_stamp"])
        assert int(row["point_key"]) >= 1
        assert row["kind"] in {"scientific", "common-reference"}


def test_controls_are_the_reference_window_at_the_jobs_own_condition() -> None:
    """A control is the reference window recorded at its job's run-wide condition."""
    rows = _rows()
    conditions = {
        row["job"]: (
            row["declared_burst_length"],
            row["declared_emissions_per_profile"],
        )
        for row in rows
    }
    for row in rows:
        is_control = row["requested_label"] in CONTROLS
        assert row["is_control"] == ("true" if is_control else "false")
        if is_control:
            assert (row["gates"], row["declared_resolution_mm"]) == ("50", "1.85")
            assert (
                row["declared_burst_length"],
                row["declared_emissions_per_profile"],
            ) == conditions[row["job"]]
    in_scientific_jobs = [row for row in rows if row["kind"] == "scientific"]
    controls = [row for row in in_scientific_jobs if row["is_control"] == "true"]
    new_conditions = [row for row in in_scientific_jobs if row["is_control"] == "false"]
    reference = [row for row in rows if row["kind"] == "common-reference"]
    # The five scientific jobs spend three controls each and carry the design's seven
    # new conditions; the four reference jobs carry one recording each.
    assert len(in_scientific_jobs) == 22 and len(controls) == 15
    assert len(new_conditions) == 7 and len(reference) == 4
    assert {row["requested_label"] for row in new_conditions} == {
        "cc1",
        "cc2",
        "cc3",
        "cc4",
        "e8",
        "e64",
        "e128",
    }
    assert {row["requested_label"] for row in reference} == {
        "cr1",
        "cr2",
        "cr3",
        "cr4",
    }
    for row in reference:
        assert row["requested_label"] not in CONTROLS
        assert (row["gates"], row["declared_resolution_mm"]) == ("50", "1.85")
        assert row["declared_burst_length"] == "10"
    # Each scientific job's controls are at the beginning, the middle and the end.
    for step in {row["step"] for row in in_scientific_jobs}:
        labels = [row["requested_label"] for row in rows if row["step"] == step]
        assert labels[0] == "ctrl-begin" and labels[-1] == "ctrl-end"
        assert "ctrl-mid" in labels
        assert all(label in CONTROLS for label in (labels[0], labels[-1]))


# ── the decoded settings bind the row to the plan ─────────────────────


def test_declared_condition_and_window_are_the_stored_words(ingest) -> None:
    windows = {(round(resolution, 6), gates) for resolution, gates in PLAN_WINDOWS}
    for row in ingest.rows:
        assert row["burst_length"] == row["declared_burst_length"]
        assert row["emissions_per_profile"] == row["declared_emissions_per_profile"]
        assert row["op_word_14"] == row["declared_emissions_per_profile"]
        assert row["op_word_27"] == row["sampling_volume_index"]
        assert row["op_word_84"] == row["skipped_profiles"] == "0"
        assert float(row["prf_period_us"]) == 600.0
        assert float(row["sound_speed_ms"]) == 1480.0
        assert row["gates"] == row["declared_gates"]
        assert row["resolution_mm"] == row["declared_accepted_resolution_mm"]
        requested = (
            round(float(row["declared_resolution_mm"]), 6),
            int(row["declared_gates"]),
        )
        assert requested in windows, requested
        assert (row["quantity"], row["unit"]) == ("axial_velocity", "mm/s")
        assert row["log_status"] == "ok" and row["decode_error"] == ""


def test_every_recording_is_live_and_retains_the_usable_interval(ingest) -> None:
    assert ingest.decode_failures == 0
    for row in ingest.rows:
        assert int(row["profiles"]) > 100
        assert float(row["non_zero_fraction"]) > 0.5
        assert float(row["duration_s"]) >= USABLE_INTERVAL_S
        # The window is what was asked for; every recording of this pass ran a little
        # past it (12.4686-12.5888 s for a 12 s request), so the retention is >= 1 and
        # must not silently exceed the request by more than the store's own overshoot.
        assert 1.0 <= float(row["retained_fraction"]) <= 1.06
        assert row["timestamps_monotone"] == "true"


def test_the_stored_words_are_the_plan_the_pass_record_and_the_definition() -> None:
    plan = json.loads((ROOT / PLAN_PATH).read_text(encoding="utf-8"))
    run = read_run_record(ROOT / DATASET_ROOT)
    assert run["plan"] == plan["plan"] == "sparse-mixer-live-1"
    assert run["duration_s"] == plan["duration_s"] == REQUESTED_DURATION_S
    recorded = {job["job"]: job for job in run["jobs"]}
    for step, job, count in JOB_STEPS:
        entry = recorded[job]
        assert entry["step"] == step
        assert entry["expected_recordings"] == count == entry["ok_recordings"]
        assert entry["status"] == "ok"
        definition = json.loads(
            (ROOT / PLAN_PATH)
            .parent.joinpath(entry["definition"])
            .read_text(encoding="utf-8")
        )
        assert definition["job"] == job
        assert definition["burst_length"] == entry["condition"]["burst_length"]
        assert (
            definition["emissions_per_profile"]
            == entry["condition"]["emissions_per_profile"]
        )
        assert len(definition["points"]) == count


# ── the two provenance rules of this pass ─────────────────────────────


def test_achieved_period_is_measured_from_the_stored_timestamps(ingest) -> None:
    """The table's period is the file's own, recomputed here through the reader."""
    for row in ingest.rows:
        stream = load(ROOT / DATASET_ROOT / row["relative_path"]).recording.streams[0]
        time_s = np.asarray(stream.data.time_s, dtype=float)
        measured = float((time_s[-1] - time_s[0]) / (time_s.size - 1))
        assert float(row["achieved_period_s"]) == pytest.approx(
            measured, rel=1e-11, abs=0
        )
        assert float(row["duration_s"]) == pytest.approx(
            float(time_s[-1] - time_s[0]), rel=1e-11, abs=0
        )
        assert int(row["profiles"]) == time_s.size
        assert float(row["median_interval_s"]) == pytest.approx(
            float(np.median(np.diff(time_s))), rel=1e-11, abs=0
        )


def test_the_logs_still_carry_the_retired_expectation_and_not_the_period(
    ingest,
) -> None:
    """``timing.target_s`` is the retired law, unrewritten, and is never the period."""
    for row in ingest.rows:
        retired = (
            float(row["emissions_per_profile"]) * float(row["declared_prf_us"]) * 1e-6
            + RETIRED_PERIOD_TRANSFER_S
        )
        assert float(row["log_target_s"]) == pytest.approx(retired, abs=1e-12)
        assert float(row["log_achieved_period_s"]) == pytest.approx(
            float(row["achieved_period_s"]), rel=1e-11, abs=0
        )
        # The retired law and the achieved period are two different quantities at
        # every level of this pass: the intercept is 10.369 ms, not 1 ms.
        assert float(row["log_target_s"]) != pytest.approx(
            float(row["achieved_period_s"]), abs=1e-6
        )


def test_the_committed_logs_are_not_rewritten(ingest) -> None:
    """Every log's recorded target is the retired law *in the bytes on disk*."""
    for name in sorted({row["log_relative_path"] for row in ingest.rows}):
        text = (ROOT / DATASET_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            retired = (
                entry["decoded"]["emissions_per_profile"]
                * entry["requested"]["prf_us"]
                * 1e-6
                + RETIRED_PERIOD_TRANSFER_S
            )
            assert entry["timing"]["target_s"] == pytest.approx(retired, abs=1e-12)
            assert entry["timing"]["achieved_s"] == pytest.approx(
                entry["decoded"]["achieved_period_s"], rel=1e-12, abs=0
            )


# ── the two shared views ──────────────────────────────────────────────


def test_common_window_is_derived_from_the_retained_spans(ingest) -> None:
    spans = [float(row["duration_s"]) for row in ingest.rows]
    assert ingest.window_s == pytest.approx(common_window_s(spans), rel=1e-11)
    assert ingest.window_revolutions * 0.12 == pytest.approx(ingest.window_s, abs=1e-12)
    assert ingest.window_s >= USABLE_INTERVAL_S
    for row in ingest.rows:
        assert float(row["window_s"]) == pytest.approx(ingest.window_s, abs=1e-12)
        assert float(row["window_profiles"]) <= int(row["profiles"])


def test_common_support_is_the_intersection_of_the_decoded_depth_ranges(ingest) -> None:
    lows = [float(row["depth_min_mm"]) for row in ingest.rows]
    highs = [float(row["depth_max_mm"]) for row in ingest.rows]
    support_min, support_max = ingest.support_mm
    assert support_min == pytest.approx(max(lows), rel=1e-12)
    assert support_max == pytest.approx(min(highs), rel=1e-12)
    assert support_max > support_min
    for row in ingest.rows:
        stream = load(ROOT / DATASET_ROOT / row["relative_path"]).recording.streams[0]
        depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
        inside = int(
            np.count_nonzero(
                (depths >= support_min - 1e-9) & (depths <= support_max + 1e-9)
            )
        )
        assert int(row["supported_gates"]) == inside
        assert inside >= 2


def test_supported_metrics_land_inside_the_whole_record_range(ingest) -> None:
    for row in ingest.rows:
        lowest = float(row["velocity_min_mm_s"])
        highest = float(row["velocity_max_mm_s"])
        for column in (
            "supported_mean_mm_s",
            "supported_median_mm_s",
            "supported_iqr_mm_s",
            "supported_rms_mm_s",
        ):
            value = float(row[column])
            assert np.isfinite(value)
            assert lowest <= value <= highest
        assert 0.0 <= float(row["supported_zero_fraction"]) <= 1.0


# ── the QC gate and the committed artefacts ───────────────────────────


def test_every_wp0_check_holds_and_the_summary_binds_the_table(ingest) -> None:
    assert ingest.ok is True
    assert all(ingest.checks.values()), ingest.checks
    document = json.loads((REPORT_DIR / QC_NAME).read_text(encoding="utf-8"))
    assert document["ok"] is True
    assert document["points"] == POINTS_NAME
    assert document["points_rows"] == EXPECTED_RECORDINGS
    assert document["job_counts"] == ingest.job_counts
    assert document["expected_job_counts"] == dict(sorted(EXPECTED_JOB_COUNTS.items()))
    assert document["plan_fingerprint"] == ingest.plan_fingerprint
    assert document["views"]["common_window"]["window_s"] == ingest.window_s
    assert document["views"]["common_support"]["support_min_mm"] == ingest.support_mm[0]
    assert document["decode_failures"] == 0
    assert document["nan_cells"] == 0
    assert document["non_monotone_files"] == []
    assert document["not_live_files"] == []
    assert document["short_retention_files"] == []
    digest = hashlib.sha256((REPORT_DIR / POINTS_NAME).read_bytes()).hexdigest()
    assert document["points_sha256"] == f"sha256:{digest}"


def test_committed_artefacts_are_reproducible_with_the_recorded_commit(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(ROOT)
    committed_qc = REPORT_DIR / QC_NAME
    assert committed_qc.is_file(), "WP0 must commit qc-summary.json"
    recorded = json.loads(committed_qc.read_text(encoding="utf-8"))["analysis_commit"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded
    write_sparse_ingest(DATASET_ROOT, tmp_path, analysis_commit=recorded)

    # The writer always emits LF; a checkout can present the committed copy with the
    # platform's line endings (``core.autocrlf``), so compare normalized text — the
    # path spelling inside the documents is part of the contract and must agree.
    def normalized(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    for name in (POINTS_NAME, QC_NAME):
        assert normalized(tmp_path / name) == normalized(REPORT_DIR / name), name


def test_the_report_readme_names_the_artefacts_and_the_commit_rule() -> None:
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    assert POINTS_NAME in readme and QC_NAME in readme
    assert "--analysis-commit" in readme
    assert "current HEAD" in readme
    assert "generator" in readme


# ── the refusal paths ─────────────────────────────────────────────────


def _copy_dataset(tmp_path: Path) -> Path:
    """A working copy of the committed pass, for the tests that mutate it."""
    import shutil

    target = tmp_path / "dataset"
    shutil.copytree(ROOT / DATASET_ROOT, target)
    return target


def test_a_rewritten_log_refuses_by_name(tmp_path) -> None:
    """The retired target is provenance: a log edited to the later law is refused."""
    dataset = _copy_dataset(tmp_path)
    log = dataset / "sparse-mixer-live-1-emissions-8.jsonl"
    entries = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    for entry in entries:
        entry["timing"]["target_s"] = entry["timing"]["achieved_s"]
    log.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    with pytest.raises(SparseIngestError, match="timing.target_s"):
        build_sparse_ingest(dataset, plan_path=ROOT / PLAN_PATH)


def test_a_recording_the_pass_does_not_claim_refuses(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    extra = min(dataset.glob("*.BDD")).read_bytes()
    (dataset / "sparse2-burst-4-cc9-20260921T123240.BDD").write_bytes(extra)
    with pytest.raises(SparseIngestError, match="no planned point claims"):
        build_sparse_ingest(dataset, plan_path=ROOT / PLAN_PATH)


def test_a_plan_the_record_does_not_answer_refuses(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    record = json.loads(
        (dataset / "sparse-mixer-live-1.run.json").read_text(encoding="utf-8")
    )
    record["plan_fingerprint"] = "0" * 64
    (dataset / "sparse-mixer-live-1.run.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    with pytest.raises(SparseIngestError, match="plan fingerprint"):
        build_sparse_ingest(dataset, plan_path=ROOT / PLAN_PATH)


def test_a_failed_build_writes_no_half_artefact(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    (dataset / "sparse-mixer-live-1-burst-4.jsonl").write_text("", encoding="utf-8")
    report = tmp_path / "reports"
    with pytest.raises(SparseIngestError):
        write_sparse_ingest(dataset, report, plan_path=ROOT / PLAN_PATH)
    assert not (report / POINTS_NAME).exists()
    assert not (report / QC_NAME).exists()


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_plan(
    tmp_path, capsys
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        sparse_inventory_main(
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
    assert "26 / 26 recordings" in capsys.readouterr().out

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as failed:
        sparse_inventory_main(
            ["--dataset-root", str(broken), "--report-dir", str(tmp_path / "out")]
        )
    assert failed.value.code == 1
    assert "udv-sparse-inventory:" in capsys.readouterr().err
