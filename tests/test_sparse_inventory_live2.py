"""Focused tests for WP0's second-pass ingest generalization (plan ``SA0``).

Written RED first, against an ingest that knew only one pass. ``build_sparse_ingest``
pinned the plan name to the module constant ``PLAN_NAME`` and read
``sparse-mixer-live-1.run.json`` by that name, so a build over the committed
``sparse-mixer-live-2`` records refused before decoding a single recording; and the
per-point provenance check ``require_retired_target`` hard-coded the live-1 transfer
term (``emissions x PRF + 1 ms``) while live-2's own logs record the manual's
sixteen-emission form (``profile_period_s``), so even a correctly-named pass would have
been refused on every point.

The tests pin the generalization and the invariance both ways:

- the ingest takes its identity from its inputs — dataset root, plan path, plan name
  and report directory — and the 26 committed live-2 recordings bind to the nine
  planned jobs (5 + 1 + 5 + 1 + 4 + 1 + 4 + 1 + 4) with the same schema;
- the second pass clears the *same* content and 12 s coverage gate the first pass's
  artifacts are frozen against, with zero decode failures and its own plan fingerprint;
- the achieved period is still measured from stored timestamps, while each pass's
  ``timing.target_s`` reproduces its own planning expectation (never the achieved
  period); a target copied from the other pass's law is refused;
- the refusals survive: a plan the dataset does not answer to, a recording no planned
  point claims, and an undecodable recording that must stay visible as a failed row
  rather than silently vanish;
- live-1's defaults are unchanged: the bare call still describes
  ``sparse-mixer-live-1`` and still emits the bare regeneration command.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis.sparse_inventory import (
    COLUMNS,
    DATASET_ROOT,
    DESIGNED_WINDOW_S,
    EXPECTED_JOB_COUNTS,
    EXPECTED_RECORDINGS,
    PLAN_NAME,
    PLAN_PATH,
    POINTS_NAME,
    QC_NAME,
    REQUESTED_DURATION_S,
    SparseIngestError,
    build_sparse_ingest,
    qc_document,
    read_run_record,
    require_retired_target,
    write_sparse_ingest,
)
from udv_echo_process.cli import sparse_inventory_main
from udv_echo_process.io import load

ROOT = Path(__file__).resolve().parent.parent
LIVE2_ROOT = ROOT / "data" / "sparse-mixer-live-2"
LIVE2_PLAN = ROOT / "examples" / "sparse-mixer-live-2" / "run-plan.json"
LIVE2_NAME = "sparse-mixer-live-2"
LIVE2_PLAN_FINGERPRINT = (
    "f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef"
)
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

#: The same nine jobs the first pass realized, in plan order, with their counts.
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


@pytest.fixture(scope="module")
def ingest():
    """The second pass, built by derivation from its own plan file."""
    return build_sparse_ingest(LIVE2_ROOT, plan_path=LIVE2_PLAN, analysis_commit=COMMIT)


# ── identity: the ingest describes the pass it is pointed at ───────────


def test_the_second_pass_is_its_own_plan_and_dataset(ingest) -> None:
    assert ingest.plan == LIVE2_NAME
    assert ingest.plan != PLAN_NAME
    assert Path(ingest.plan_path).name == "run-plan.json"
    assert "sparse-mixer-live-2" in Path(ingest.plan_path).as_posix()
    assert "sparse-mixer-live-2" in Path(ingest.dataset_root).as_posix()
    assert ingest.plan_fingerprint == LIVE2_PLAN_FINGERPRINT
    run = read_run_record(LIVE2_ROOT, plan_name=LIVE2_NAME)
    assert run["plan"] == LIVE2_NAME
    assert run["plan_fingerprint"] == LIVE2_PLAN_FINGERPRINT
    # Every row is stamped with the plan it came from, not with the default.
    assert {row["plan"] for row in ingest.rows} == {LIVE2_NAME}
    assert {row["plan_fingerprint"] for row in ingest.rows} == {LIVE2_PLAN_FINGERPRINT}


def test_the_two_passes_share_the_design_but_not_the_identity() -> None:
    live1 = json.loads((ROOT / PLAN_PATH).read_text(encoding="utf-8"))
    live2 = json.loads(LIVE2_PLAN.read_text(encoding="utf-8"))
    assert live1["plan"] == PLAN_NAME == "sparse-mixer-live-1"
    assert live2["plan"] == LIVE2_NAME
    assert live1["name_prefix"] != live2["name_prefix"]
    # The README's own claim: a derived copy with only the identity fields moved.
    for key in ("duration_s", "windows", "reference_window", "reference_condition"):
        assert live1[key] == live2[key], key
    assert [(job["step"], job["job"], job["condition"]) for job in live1["jobs"]] == [
        (job["step"], job["job"], job["condition"]) for job in live2["jobs"]
    ]


# ── binding: 26 recordings, nine jobs, the designed order ──────────────


def test_the_second_pass_binds_the_planned_twenty_six_over_nine_jobs(ingest) -> None:
    assert ingest.recordings == ingest.points_rows == EXPECTED_RECORDINGS == 26
    assert ingest.expected_recordings == 26
    assert ingest.job_counts == dict(sorted(EXPECTED_JOB_COUNTS.items()))
    counted: dict[int, int] = {}
    for row in ingest.rows:
        counted[int(row["step"])] = counted.get(int(row["step"]), 0) + 1
    assert counted == {step: count for step, _job, count in JOB_STEPS}
    assert [int(row["order"]) for row in ingest.rows] == list(range(1, 27))
    seen: list[tuple[int, str]] = []
    for row in ingest.rows:
        pair = (int(row["step"]), row["job"])
        if not seen or seen[-1] != pair:
            seen.append(pair)
    assert seen == [(step, job) for step, job, _ in JOB_STEPS]


def test_every_row_is_bound_to_the_passes_own_record_and_definition(ingest) -> None:
    run = read_run_record(LIVE2_ROOT, plan_name=LIVE2_NAME)
    recorded = {job["job"]: job for job in run["jobs"]}
    for row in ingest.rows:
        entry = recorded[row["job"]]
        assert entry["definition_fingerprint"] == row["job_definition_fingerprint"]
        definition = json.loads(
            (LIVE2_PLAN.parent / entry["definition"]).read_text(encoding="utf-8")
        )
        assert definition["job"] == row["job"]
        assert (
            row["identity"] == f"{definition['name_prefix']}-{row['requested_label']}"
        )
        assert row["relative_path"] == f"{row['identity']}-{row['recording_stamp']}.BDD"
        assert (LIVE2_ROOT / row["relative_path"]).is_file()
        assert row["job_definition"] == entry["definition"]


# ── content and coverage through the existing gate ─────────────────────


def test_the_second_pass_clears_the_wp0_gate(ingest) -> None:
    assert ingest.ok is True
    assert all(ingest.checks.values()), ingest.checks
    assert ingest.decode_failures == 0
    assert ingest.decode_failure_files == ()
    assert ingest.nan_cells == 0
    assert ingest.non_monotone_files == ()
    assert ingest.not_live_files == ()
    assert ingest.short_retention_files == ()
    assert ingest.window_s == DESIGNED_WINDOW_S == REQUESTED_DURATION_S


def test_every_second_pass_recording_is_live_and_covers_the_design(ingest) -> None:
    for row in ingest.rows:
        assert row["decode_error"] == ""
        assert row["log_status"] == "ok"
        assert row["quantity"] == "axial_velocity" and row["unit"] == "mm/s"
        assert float(row["non_zero_fraction"]) >= 0.98
        assert float(row["duration_s"]) >= DESIGNED_WINDOW_S
        assert row["retains_designed_window"] == "true"
        # The 12 s request; the store kept a little more (12.4687-12.5850 s), and the
        # surplus is the acquisition's stopping latency, not the analysed exposure.
        assert 1.0 <= float(row["retained_fraction"]) <= 1.06
        assert row["timestamps_monotone"] == "true"
        assert int(row["gates"]) == int(row["declared_gates"])
        assert float(row["prf_period_us"]) == 600.0
        assert float(row["sound_speed_ms"]) == 1480.0
    support_min, support_max = ingest.support_mm
    assert support_max > support_min


def test_the_decoded_rows_match_the_second_passes_own_published_table(ingest) -> None:
    """A handful of the committed README's own numbers, re-decoded here."""
    by_identity = {row["identity"]: row for row in ingest.rows}
    e128 = by_identity["sparse3-emissions-128-e128"]
    assert (e128["burst_length"], e128["emissions_per_profile"]) == ("10", "128")
    assert e128["profiles"] == "145"
    assert float(e128["achieved_period_s"]) == pytest.approx(0.0872, abs=5e-4)
    cc1 = by_identity["sparse3-burst-4-cc1"]
    assert (cc1["gates"], cc1["declared_resolution_mm"]) == ("145", "0.617")
    assert float(cc1["resolution_mm"]) == pytest.approx(0.6166666666666667, rel=1e-12)
    assert cc1["resolution_mm"] == cc1["declared_accepted_resolution_mm"]
    cr1 = by_identity["sparse3-common-reference-1-cr1"]
    assert (cr1["burst_length"], cr1["emissions_per_profile"]) == ("10", "20")
    assert (cr1["gates"], cr1["declared_resolution_mm"]) == ("50", "1.85")
    # The per-emissions group profile counts the README records.
    counts = {
        job: sorted(int(row["profiles"]) for row in ingest.rows if row["job"] == job)
        for job in ("emissions-8", "emissions-64", "emissions-128")
    }
    assert counts["emissions-8"] == [826, 826, 827, 827]
    assert counts["emissions-64"] == [257, 257, 258, 258]
    assert counts["emissions-128"] == [144, 144, 145, 145]


# ── the two provenance rules, on the second pass ───────────────────────


def test_the_second_pass_period_is_measured_from_the_stored_timestamps(ingest) -> None:
    for row in ingest.rows:
        stream = load(LIVE2_ROOT / row["relative_path"]).recording.streams[0]
        time_s = stream.data.time_s
        span = float(time_s[-1] - time_s[0])
        assert float(row["duration_s"]) == pytest.approx(span, rel=1e-11, abs=0)
        assert float(row["achieved_period_s"]) == pytest.approx(
            span / (time_s.size - 1), rel=1e-11, abs=0
        )
        assert int(row["profiles"]) == time_s.size


def test_the_second_pass_logs_reproduce_the_planning_law_not_the_period(ingest) -> None:
    """``timing.target_s`` is the planner's own expectation, never the achieved period.

    This pass's logs were written by the planner's manual-consistent law (the
    sixteen-emission ``profile_period_s``), which the first pass's logs predate. Either
    way the recorded target is a *planning* number: it must equal one of those forms
    and must not be the achieved period, which differs from both.
    """
    from udv_echo_process.acquire.plan import profile_period_s

    for row in ingest.rows:
        emissions = float(row["emissions_per_profile"])
        prf_us = float(row["prf_period_us"])
        logged = float(row["log_target_s"])
        planner_law = profile_period_s(int(emissions), prf_us)
        assert logged == pytest.approx(planner_law, abs=1e-12)
        assert logged != pytest.approx(float(row["achieved_period_s"]), abs=1e-6)
        assert float(row["log_achieved_period_s"]) == pytest.approx(
            float(row["achieved_period_s"]), rel=1e-11, abs=0
        )


def test_live_two_refuses_live_one_planning_law_in_its_log() -> None:
    """A law valid for an older sitting must not authenticate a rewritten new log."""
    point = decode_pass(LIVE2_ROOT, plan_path=LIVE2_PLAN, plan_name=LIVE2_NAME).points[
        0
    ]
    old_target = (
        point.binding.job.emissions_per_profile * point.binding.job.prf_us * 1e-6
        + 0.001
    )
    entry = {
        **point.binding.entry,
        "timing": {**point.binding.entry["timing"], "target_s": old_target},
    }
    rewritten = point._replace(binding=point.binding._replace(entry=entry))
    with pytest.raises(SparseIngestError, match="planning law"):
        require_retired_target(rewritten, plan_name=LIVE2_NAME)


# ── the second pass's artefacts, written to a temporary directory ──────


def test_write_sparse_ingest_writes_the_second_pass_artefacts(tmp_path) -> None:
    ingest = write_sparse_ingest(
        LIVE2_ROOT,
        tmp_path / "reports",
        plan_path=LIVE2_PLAN,
        analysis_commit=COMMIT,
    )
    points = tmp_path / "reports" / POINTS_NAME
    summary = tmp_path / "reports" / QC_NAME
    assert points.is_file() and summary.is_file()
    text = points.read_text(encoding="utf-8")
    assert text.endswith("\n") and "\r\n" not in text
    reader = csv.reader(text.splitlines())
    assert tuple(next(reader)) == COLUMNS
    assert len(list(reader)) == 26
    document = json.loads(summary.read_text(encoding="utf-8"))
    assert document["plan"] == LIVE2_NAME
    assert document["plan_fingerprint"] == LIVE2_PLAN_FINGERPRINT
    assert document["points_rows"] == 26
    assert document["ok"] is True
    digest = hashlib.sha256(points.read_bytes()).hexdigest()
    assert document["points_sha256"] == f"sha256:{digest}"
    assert document["points_sha256"] == ingest.points_sha256


def test_the_second_pass_regeneration_command_names_its_own_inputs() -> None:
    ingest = build_sparse_ingest(
        Path(DATASET_ROOT.as_posix().replace("live-1", "live-2")),
        plan_path=Path(PLAN_PATH.as_posix().replace("live-1", "live-2")),
        analysis_commit=COMMIT,
    )
    command = qc_document(ingest)["regeneration"]["command"]
    assert "--dataset-root data/sparse-mixer-live-2" in command
    assert "--plan examples/sparse-mixer-live-2/run-plan.json" in command
    assert "--report-dir reports/sparse-mixer-live-2" in command
    assert "--plan-name sparse-mixer-live-2" in command
    assert f"--analysis-commit {COMMIT}" in command


def test_live_one_defaults_are_unchanged() -> None:
    """No argument still means the first pass, with its bare regeneration command."""
    ingest = build_sparse_ingest(analysis_commit=COMMIT)
    assert ingest.plan == PLAN_NAME == "sparse-mixer-live-1"
    assert ingest.dataset_root == DATASET_ROOT.as_posix()
    command = qc_document(ingest)["regeneration"]["command"]
    assert command == (
        ".venv/Scripts/python.exe -m udv_echo_process.cli sparse-inventory "
        f"--analysis-commit {COMMIT}"
    )
    assert "--dataset-root" not in command and "--report-dir" not in command


# ── the CLI, on the second pass ────────────────────────────────────────


def test_the_command_ingests_the_second_pass_and_exits_zero(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit) as exit_code:
        sparse_inventory_main(
            [
                "--dataset-root",
                LIVE2_ROOT.as_posix(),
                "--plan",
                LIVE2_PLAN.as_posix(),
                "--report-dir",
                str(tmp_path / "reports"),
                "--plan-name",
                LIVE2_NAME,
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert exit_code.value.code == 0
    out = capsys.readouterr().out
    assert "26 / 26 recordings" in out
    assert (tmp_path / "reports" / POINTS_NAME).is_file()


def test_the_command_refuses_a_pinned_name_that_is_not_the_plan(
    tmp_path, capsys
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        sparse_inventory_main(
            [
                "--dataset-root",
                LIVE2_ROOT.as_posix(),
                "--plan",
                LIVE2_PLAN.as_posix(),
                "--report-dir",
                str(tmp_path / "reports"),
                "--plan-name",
                "sparse-mixer-live-1",
            ]
        )
    assert exit_code.value.code == 1
    assert "udv-sparse-inventory:" in capsys.readouterr().err
    assert not (tmp_path / "reports" / POINTS_NAME).exists()


# ── the refusals ───────────────────────────────────────────────────────


def _copy_dataset(tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "dataset"
    shutil.copytree(LIVE2_ROOT, target)
    return target


def test_a_wrong_plan_for_the_dataset_refuses(tmp_path) -> None:
    """The first pass's plan pointed at the second pass's records answers nothing."""
    with pytest.raises(SparseIngestError, match="pass record"):
        build_sparse_ingest(
            LIVE2_ROOT, plan_path=ROOT / PLAN_PATH, analysis_commit=COMMIT
        )


def test_a_recording_the_second_pass_does_not_claim_refuses(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    extra = min(dataset.glob("*.BDD")).read_bytes()
    (dataset / "sparse3-burst-4-cc9-20260924T999999.BDD").write_bytes(extra)
    with pytest.raises(SparseIngestError, match="no planned point claims"):
        build_sparse_ingest(dataset, plan_path=LIVE2_PLAN)


def test_an_undecodable_recording_stays_a_visible_failed_row(tmp_path) -> None:
    """A claimed file that cannot be read is a row naming the failure, not a gap."""
    dataset = _copy_dataset(tmp_path)
    broken = next(dataset.glob("sparse3-emissions-8-e8-*.BDD"))
    broken.write_bytes(b"not a BDD")
    ingest = build_sparse_ingest(dataset, plan_path=LIVE2_PLAN)
    assert ingest.decode_failures == 1
    assert ingest.decode_failure_files == (broken.name,)
    assert ingest.checks["decode_failures"] is False
    assert ingest.ok is False
    assert ingest.points_rows == 26
    row = next(r for r in ingest.rows if r["relative_path"] == broken.name)
    assert "unrecognised bytes" in row["decode_error"]
    # Every measurement cell is empty, so a failed file cannot look like a reading.
    assert row["profiles"] == "" and row["velocity_min_mm_s"] == ""
    assert row["supported_mean_mm_s"] == ""
    assert row["identity"] == "sparse3-emissions-8-e8"
