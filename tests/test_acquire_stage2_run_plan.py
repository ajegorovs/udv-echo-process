"""Contract tests for the Stage-2 E20/E64 pass — the paired, run-level design.

``test_acquire_run_plan.py`` pins the *sweep* pass (nine jobs, block-local controls, common
references between scientific jobs). This module pins the other design the layer now encodes: the
``docs/dop3000/stage2-run-plan.md`` records — **eight run-level jobs in four counterbalanced
pairs, in one campaign, with emissions per profile the only varying run-wide setting**.

What the cases assert is the law of that design rather than its prose:

- the committed pass plans clean, and its eight jobs, four pairs, roles, conditions and order are
  the ones the frozen sequence names;
- the pair order is counterbalanced — the lower level leads half the pairs — because with one level
  always first, a short-timescale order effect is confounded with the emissions contrast;
- emissions per profile is the only thing that moves between the two jobs of a pair, and the plan
  raises it to a refusal, so a job recorded at the wrong level is refused before its first
  recording and its stored file's own word 14 has to agree afterwards;
- the run record carries pair, role and acquisition orientation per job, plus the fixed analysis
  orientation, so the later analysis reconstructs pair membership and orientation from the record
  rather than from file names or from the order the jobs happen to be listed in;
- and the resume is deterministic *across* pairs: a half-finished pair is finished first, and a job
  that is not next is refused by name rather than skipped, so the counterbalancing the design
  depends on is the order that actually ran.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire import run_plan
from udv_echo_process.acquire.campaign import JobManifest, ManifestPoint
from udv_echo_process.acquire.log import PointStatus
from udv_echo_process.cli import acquire_main

REPO = Path(__file__).resolve().parents[1]
STAGE2_DIR = REPO / "examples" / "stage2-e20-e64"
PLAN_FILE = STAGE2_DIR / "run-plan.json"

#: The frozen acquisition order: pair, job, emissions, role. ``B`` and ``D`` run emissions
#: 64 first, which is what makes the pairs counterbalanced.
EXPECTED_ORDER: tuple[tuple[str, str, int, str], ...] = (
    ("A", "e20-a", 20, "lead"),
    ("A", "e64-a", 64, "follow"),
    ("B", "e64-b", 64, "lead"),
    ("B", "e20-b", 20, "follow"),
    ("C", "e20-c", 20, "lead"),
    ("C", "e64-c", 64, "follow"),
    ("D", "e64-d", 64, "lead"),
    ("D", "e20-d", 20, "follow"),
)


def plan_payload() -> dict[str, object]:
    """The committed plan as a mutable dict, so a case can move exactly one thing."""
    return json.loads(PLAN_FILE.read_text(encoding="utf-8"))


def model(**moves: object) -> run_plan.RunPlan:
    """The committed plan with ``moves`` applied to the payload's top level."""
    payload = plan_payload()
    payload.update(moves)
    return run_plan.RunPlan.model_validate(payload)


@pytest.fixture(scope="module")
def run() -> run_plan.PlannedRun:
    return run_plan.plan_run_file(PLAN_FILE)


def job_manifest_for(
    run: run_plan.PlannedRun,
    job: run_plan.PlannedJob,
    *,
    ok: int | None = None,
    failed: int = 0,
    aborted: bool = False,
) -> JobManifest:
    """A job manifest for one job of the pass, as ``run_campaign`` would have written it."""
    successes = job.recordings if ok is None else ok
    outcomes = [
        ManifestPoint(
            key=point.key,
            label=point.label,
            identity=point.identity,
            status=PointStatus.OK,
            ok=True,
        )
        for point in job.points[:successes]
    ] + [
        ManifestPoint(
            key=point.key,
            label=point.label,
            identity=point.identity,
            status=PointStatus.FAILED,
            ok=False,
            reason="refused for the test's own reason",
            aborted=aborted,
        )
        for point in job.points[successes : successes + failed]
    ]
    moment = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)
    return JobManifest(
        job=job.job,
        fingerprint=job.definition_fingerprint,
        channel=run.channel,
        planned=job.recordings,
        started_at=moment,
        finished_at=moment,
        outcomes=tuple(outcomes),
    )


def record(
    run: run_plan.PlannedRun,
    manifest: run_plan.RunManifest,
    step: int,
    **kwargs: object,
) -> run_plan.RunManifest:
    """Record one job of the pass, as the runner does after ``run_campaign`` returns."""
    job = next(entry for entry in run.jobs if entry.step == step)
    return run_plan.record_job(manifest, run, job, job_manifest_for(run, job, **kwargs))


# --------------------------------------------------------------------------------------------
# The committed pass
# --------------------------------------------------------------------------------------------


def test_the_pass_is_its_own_campaign_and_compiles(run: run_plan.PlannedRun) -> None:
    """One identity, distinct from both earlier sparse passes, and it plans without an instrument."""
    assert run.plan == "stage2-e20-e64"
    assert run.name_prefix == "stage2"
    for other in ("sparse-mixer-first-pass", "sparse-mixer-live-1"):
        theirs = json.loads(
            (REPO / "examples" / other / "run-plan.json").read_text(encoding="utf-8")
        )
        assert theirs["plan"] != run.plan
        assert theirs["name_prefix"] != run.name_prefix
    assert len(run.jobs) == 8
    assert run.recordings == 8
    assert all(job.kind is run_plan.JobKind.RUN_LEVEL for job in run.jobs)
    assert run.scientific_jobs == ()
    assert run.common_reference_jobs == ()
    assert len(run.run_level_jobs) == 8


def test_the_eight_jobs_are_the_frozen_sequence(run: run_plan.PlannedRun) -> None:
    """Pair, job, level and role, in the order the frozen design fixes."""
    assert (
        tuple(
            (job.pair, job.job, job.condition.emissions_per_profile, job.role.value)
            for job in run.jobs
        )
        == EXPECTED_ORDER
    )


def test_four_pairs_with_two_partners_each_and_the_orientations_they_ran_in(
    run: run_plan.PlannedRun,
) -> None:
    pairs = run.pairs
    assert [group[0].pair for group in pairs] == ["A", "B", "C", "D"]
    assert all(len(group) == 2 for group in pairs)
    assert all(
        [member.role for member in group]
        == [run_plan.PairRole.LEAD, run_plan.PairRole.FOLLOW]
        for group in pairs
    )
    assert [run.acquisition_orientation(group[0]) for group in pairs] == [
        "20 -> 64",
        "64 -> 20",
        "20 -> 64",
        "64 -> 20",
    ]


def test_the_pair_order_is_counterbalanced(run: run_plan.PlannedRun) -> None:
    """Half the pairs lead with the lower level: an order effect cannot be read as the effect."""
    leads = [group[0].condition.emissions_per_profile for group in run.pairs]
    assert leads == [20, 64, 20, 64]
    assert leads.count(min(leads)) * 2 == len(leads)


def test_every_job_is_the_reference_window_at_the_fixed_frame(
    run: run_plan.PlannedRun,
) -> None:
    """One window, one burst, one PRF — and exactly one point, with no block-local control."""
    assert run.reference_window.as_pair == (1.85, 50)
    assert run.reference_condition.as_triple == (10, 20, 600.0)
    for job in run.jobs:
        assert job.condition.burst_length == 10
        assert job.condition.prf_us == 600.0
        assert len(job.points) == 1
        point = job.points[0]
        assert (point.parameters.resolution_mm, point.parameters.gates) == (1.85, 50)
        assert point.label == "ref"
        assert not point.label.startswith(run_plan.CONTROL_PREFIX)
        assert point.identity == f"stage2-{job.job}-ref"


def test_emissions_is_the_only_varying_setting_and_each_definition_agrees(
    run: run_plan.PlannedRun,
) -> None:
    """The plan and the eight job files say the same three values; only emissions moves."""
    assert run.strict_facts == ("emissions_per_profile",)
    levels = {
        json.loads((STAGE2_DIR / job.definition).read_text(encoding="utf-8"))[
            "emissions_per_profile"
        ]
        for job in run.jobs
    }
    assert levels == {20, 64}
    for job in run.jobs:
        definition = json.loads(
            (STAGE2_DIR / job.definition).read_text(encoding="utf-8")
        )
        assert definition["job"] == job.job
        assert definition["name_prefix"] == run_plan.job_prefix(run, job.job)
        assert definition["burst_length"] == job.condition.burst_length
        assert definition["prf_us"] == job.condition.prf_us
        assert (
            definition["emissions_per_profile"] == job.condition.emissions_per_profile
        )
        assert definition["duration_s"] == run.duration_s
        assert len(definition["points"]) == 1


def test_two_jobs_of_a_pair_differ_in_emissions_and_nothing_else(
    run: run_plan.PlannedRun,
) -> None:
    """The pair's own comparison: same burst, same PRF, same points, one level apart.

    A point's ``parameters`` carry the job's own run-wide values (a point is compiled at its
    job's values), so the spatial frame is what the two jobs have to share.
    """

    def frame(point: object) -> tuple[float, float, float, int]:
        parameters = point.parameters
        return (
            parameters.sound_speed_ms,
            parameters.first_gate_mm,
            parameters.resolution_mm,
            parameters.gates,
        )

    for group in run.pairs:
        first, second = group
        assert first.condition.burst_length == second.condition.burst_length
        assert first.condition.prf_us == second.condition.prf_us
        assert (
            first.condition.emissions_per_profile
            != second.condition.emissions_per_profile
        )
        assert [point.label for point in first.points] == [
            point.label for point in second.points
        ]
        assert [frame(point) for point in first.points] == [
            frame(point) for point in second.points
        ]


def test_the_pass_holds_no_pair_of_the_same_level_and_no_repeated_letter(
    run: run_plan.PlannedRun,
) -> None:
    assert len({group[0].pair for group in run.pairs}) == 4


# --------------------------------------------------------------------------------------------
# What the design refuses
# --------------------------------------------------------------------------------------------


def test_a_sweep_pass_still_plans_unchanged() -> None:
    """The extension is additive: the live pass compiles with no pairing anywhere."""
    live = run_plan.plan_run_file(
        REPO / "examples" / "sparse-mixer-live-1" / "run-plan.json"
    )
    assert len(live.jobs) == 9
    assert live.recordings == 26
    assert live.run_level_jobs == ()
    assert all(job.pair is None and job.role is None for job in live.jobs)
    manifest = run_plan.new_run_manifest(live, store_dir="outputs/live/store")
    assert manifest.analysis_orientation is None
    assert all(row.pair is None and row.orientation is None for row in manifest.jobs)


def test_a_role_that_is_not_the_job_that_runs_first_is_refused() -> None:
    """The labels have to agree with the order: the role *is* which job opens the pair."""
    payload = plan_payload()
    for entry in payload["jobs"]:
        entry["role"] = (
            "lead" if entry["condition"]["emissions_per_profile"] == 20 else "follow"
        )
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "the job that runs first is the pair's lead" in str(error.value)


def test_a_pass_that_does_not_alternate_its_lead_is_refused() -> None:
    """All the pairs leading with the lower level is the design the review rejected."""
    payload = plan_payload()
    first, second = payload["jobs"][2], payload["jobs"][3]
    payload["jobs"][2] = {
        **first,
        "job": second["job"],
        "definition": second["definition"],
        "condition": second["condition"],
        "role": "lead",
    }
    payload["jobs"][3] = {
        **second,
        "job": first["job"],
        "definition": first["definition"],
        "condition": first["condition"],
        "role": "follow",
    }
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "not counterbalanced" in str(error.value)


def test_a_pair_letter_that_does_not_sit_on_two_consecutive_jobs_is_refused() -> None:
    """A pair is two consecutive jobs, so a letter that jumps a step names no pair."""
    payload = plan_payload()
    payload["jobs"][2]["pair"] = "C"
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "consecutive" in str(error.value)


def test_a_pair_whose_two_jobs_are_at_one_level_is_refused() -> None:
    payload = plan_payload()
    payload["jobs"][1]["condition"]["emissions_per_profile"] = 20
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "two levels" in str(error.value)


def test_a_pair_that_moves_burst_is_refused() -> None:
    """Emissions only: a burst that moved would make the pair a two-factor comparison."""
    payload = plan_payload()
    payload["jobs"][1]["condition"]["burst_length"] = 18
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "emissions per profile is the only run-wide setting" in str(error.value)


def test_a_pass_that_does_not_raise_emissions_is_refused() -> None:
    """Without the raise, a job recorded at the wrong level would pass as the plan's own."""
    with pytest.raises(ValidationError) as error:
        model(strict_facts=[])
    assert "raise that fact to a refusal" in str(error.value)


def test_a_pass_that_states_another_analysis_orientation_is_refused() -> None:
    with pytest.raises(ValidationError) as error:
        model(analysis_orientation="E20 - E64")
    assert run_plan.ANALYSIS_ORIENTATION in str(error.value)


def test_a_pass_with_an_odd_job_count_is_refused() -> None:
    payload = plan_payload()
    payload["jobs"] = payload["jobs"][:-1]
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "even" in str(error.value)


def test_a_job_with_a_role_but_no_pair_is_refused() -> None:
    payload = plan_payload()
    payload["jobs"][0].pop("pair")
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "without a pair" in str(error.value)


def test_a_pair_letter_that_is_not_a_letter_is_refused() -> None:
    payload = plan_payload()
    payload["jobs"][0]["pair"] = "A1"
    with pytest.raises(ValidationError) as error:
        run_plan.RunPlan.model_validate(payload)
    assert "one capital letter" in str(error.value)


def test_a_run_level_job_at_another_window_is_refused(tmp_path: Path) -> None:
    """A pair is a comparison at one window, so a job at another one is a different pass."""
    shutil.copytree(STAGE2_DIR, tmp_path / "pass")
    plan_file = tmp_path / "pass" / "run-plan.json"
    payload = json.loads(plan_file.read_text(encoding="utf-8"))
    payload["windows"] = [
        {"resolution_mm": 1.85, "gates": 50},
        {"resolution_mm": 2.96, "gates": 31},
    ]
    plan_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    wide = json.loads(
        (tmp_path / "pass" / "jobs" / "e20-a.json").read_text(encoding="utf-8")
    )
    wide["points"][0]["parameters"]["resolution_mm"] = 2.96
    wide["points"][0]["parameters"]["gates"] = 31
    (tmp_path / "pass" / "jobs" / "e20-a.json").write_text(
        json.dumps(wide, indent=2), encoding="utf-8"
    )
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.plan_run(
            run_plan.load_run_plan(plan_file), directory=tmp_path / "pass"
        )
    assert "reference window" in str(error.value)


def test_a_run_level_job_with_a_control_label_is_refused(tmp_path: Path) -> None:
    payload = plan_payload()
    plan = run_plan.RunPlan.model_validate(payload)
    definition = json.loads(
        (STAGE2_DIR / "jobs" / "e20-a.json").read_text(encoding="utf-8")
    )
    definition["points"][0]["label"] = "ctrl-begin"
    (tmp_path / "jobs").mkdir()
    for entry in plan.jobs:
        (tmp_path / "jobs" / f"{entry.job}.json").write_text(
            (STAGE2_DIR / entry.definition).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (tmp_path / "jobs" / "e20-a.json").write_text(
        json.dumps(definition, indent=2), encoding="utf-8"
    )
    (tmp_path / "run-plan.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.plan_run(
            run_plan.load_run_plan(tmp_path / "run-plan.json"), directory=tmp_path
        )
    assert "the stored file" not in str(error.value)
    assert "block-local control" in str(error.value)


def test_a_definition_whose_emissions_disagrees_with_the_plan_is_refused(
    tmp_path: Path,
) -> None:
    """The compile's own read-back of the job file: the pass's only variable is checked first."""
    payload = plan_payload()
    (tmp_path / "jobs").mkdir()
    for entry in payload["jobs"]:
        (tmp_path / "jobs" / f"{entry['job']}.json").write_text(
            (STAGE2_DIR / entry["definition"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (tmp_path / "run-plan.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    swapped = json.loads((tmp_path / "jobs" / "e64-a.json").read_text(encoding="utf-8"))
    swapped["emissions_per_profile"] = 20
    (tmp_path / "jobs" / "e64-a.json").write_text(
        json.dumps(swapped, indent=2), encoding="utf-8"
    )
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.plan_run(
            run_plan.load_run_plan(tmp_path / "run-plan.json"), directory=tmp_path
        )
    assert "emissions_per_profile" in str(error.value)


def test_the_plan_fingerprint_moves_with_a_level(run: run_plan.PlannedRun) -> None:
    """A record answers a plan: a level that moved makes the record a different pass's."""
    payload = plan_payload()
    for entry in payload["jobs"]:
        entry["condition"]["emissions_per_profile"] = (
            8 if entry["condition"]["emissions_per_profile"] == 20 else 16
        )
    moved = run_plan.RunPlan.model_validate(payload)
    assert run_plan.plan_fingerprint(moved) != run.plan_fingerprint
    assert run.plan_fingerprint == run_plan.plan_fingerprint(model())


def test_the_sheet_states_the_pairs_the_orientations_and_what_to_set(
    run: run_plan.PlannedRun,
) -> None:
    sheet = run_plan.operator_setup_sheet(run)
    assert "jobs        : 8 (8 run-level), 8 recording(s)" in sheet
    assert (
        "pairs       : 4 counterbalanced pairs — A: 20 -> 64, B: 64 -> 20, "
        "C: 20 -> 64, D: 64 -> 20" in sheet
    )
    assert (
        f"each pair is read {run_plan.ANALYSIS_ORIENTATION} whatever order it was "
        "recorded in" in sheet
    )
    for job in run.jobs:
        partner = next(
            entry
            for entry in run.jobs
            if entry.pair == job.pair and entry.step != job.step
        )
        assert (
            f"pair       : {job.pair}, {job.role.value} of 2 — set emissions_per_profile "
            f"{job.condition.emissions_per_profile} for this job; its partner is "
            f"{partner.job!r} at {partner.condition.emissions_per_profile}" in sheet
        )
    assert "the stored file's own word must agree as well" in sheet


def test_the_sheet_names_emissions_as_the_fact_this_pass_refuses_on(
    run: run_plan.PlannedRun,
) -> None:
    sheet = run_plan.operator_setup_sheet(run)
    assert "raised facts: ['emissions_per_profile']" in sheet
    assert sheet.count("this pass raises it to a refusal") == 8


def test_the_run_record_carries_the_pair_the_role_and_the_orientation(
    run: run_plan.PlannedRun,
) -> None:
    manifest = run_plan.new_run_manifest(run, store_dir="outputs/live/store")
    assert manifest.analysis_orientation == run_plan.ANALYSIS_ORIENTATION
    assert [(row.pair, row.role.value, row.orientation) for row in manifest.jobs] == [
        ("A", "lead", "20 -> 64"),
        ("A", "follow", "20 -> 64"),
        ("B", "lead", "64 -> 20"),
        ("B", "follow", "64 -> 20"),
        ("C", "lead", "20 -> 64"),
        ("C", "follow", "20 -> 64"),
        ("D", "lead", "64 -> 20"),
        ("D", "follow", "64 -> 20"),
    ]
    assert all(row.condition is not None for row in manifest.jobs)


def test_the_resume_finishes_a_half_completed_pair_before_the_next_one(
    run: run_plan.PlannedRun,
) -> None:
    """The counterbalancing only means what we intend if the order that ran is the frozen order."""
    manifest = run_plan.new_run_manifest(run, store_dir="outputs/live/store")
    assert run_plan.next_job(run, manifest).job == "e20-a"
    manifest = record(run, manifest, 1)
    assert run_plan.next_job(run, manifest).job == "e64-a"
    assert run_plan.next_job(run, manifest).pair == "A"
    manifest = record(run, manifest, 2)
    assert run_plan.next_job(run, manifest).job == "e64-b"
    assert run_plan.next_job(run, manifest).pair == "B"


def test_a_failed_lead_blocks_its_own_pair_rather_than_advancing(
    run: run_plan.PlannedRun,
) -> None:
    manifest = run_plan.new_run_manifest(run, store_dir="outputs/live/store")
    manifest = record(run, manifest, 1, ok=0, failed=1)
    assert [row.status for row in manifest.jobs][:2] == [
        run_plan.RunJobStatus.FAILED,
        run_plan.RunJobStatus.PENDING,
    ]
    assert run_plan.next_job(run, manifest).job == "e20-a"
    assert not manifest.complete


def test_a_job_that_is_not_next_is_refused_by_name(run: run_plan.PlannedRun) -> None:
    """A pair cannot be reversed by running its follow first: that is a different design."""
    manifest = run_plan.new_run_manifest(run, store_dir="outputs/live/store")
    follow = next(entry for entry in run.jobs if entry.job == "e64-a")
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.record_job(manifest, run, follow, job_manifest_for(run, follow))
    assert "is not the next job of this pass" in str(error.value)
    assert "'e20-a'" in str(error.value)


def test_the_whole_pass_recorded_is_complete_in_the_frozen_order(
    run: run_plan.PlannedRun,
) -> None:
    manifest = run_plan.new_run_manifest(run, store_dir="outputs/live/store")
    for step in range(1, 9):
        manifest = record(run, manifest, step)
        assert manifest.jobs[step - 1].status is run_plan.RunJobStatus.OK
    assert manifest.complete
    assert run_plan.next_job(run, manifest) is None
    assert [row.job for row in manifest.jobs] == [entry[1] for entry in EXPECTED_ORDER]


def test_the_manifest_round_trips_with_its_pairs(
    tmp_path: Path, run: run_plan.PlannedRun
) -> None:
    store = tmp_path / "store"
    manifest = run_plan.new_run_manifest(run, store_dir=store)
    path = run_plan.run_manifest_path(run, store_dir=store)
    run_plan.write_run_manifest(path, manifest)
    again = run_plan.read_run_manifest(path)
    assert again == manifest
    assert again.analysis_orientation == run_plan.ANALYSIS_ORIENTATION
    assert [row.orientation for row in again.jobs][:2] == ["20 -> 64", "20 -> 64"]


def test_the_cli_check_names_the_eight_jobs_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--check"])
    assert exit_code.value.code == 0
    out = capsys.readouterr().out
    for _, job, _, _ in EXPECTED_ORDER:
        assert job in out
    assert "run-level" in out
    assert "emissions_per_profile" in out


def test_the_cli_sheet_prints_the_pairs_the_operator_sets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--sheet"])
    assert exit_code.value.code == 0
    out = capsys.readouterr().out
    assert "pairs       : 4 counterbalanced pairs" in out
    assert "analysis orientation E64 - E20" in out


def test_the_cli_status_on_an_empty_store_says_nothing_has_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_code:
        acquire_main(
            [
                "run-plan",
                "--plan",
                str(PLAN_FILE),
                "--status",
                "--store-dir",
                str(tmp_path),
            ]
        )
    assert exit_code.value.code == 0
    out = capsys.readouterr().out
    assert "no run manifest" in out
    assert "no job of this pass has run" in out


def test_the_cli_refuses_a_plan_whose_pairing_is_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = plan_payload()
    payload["jobs"][1]["condition"]["emissions_per_profile"] = 20
    (tmp_path / "jobs").mkdir()
    for entry in payload["jobs"]:
        (tmp_path / "jobs" / f"{entry['job']}.json").write_text(
            (STAGE2_DIR / entry["definition"]).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (tmp_path / "run-plan.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    with pytest.raises(SystemExit) as exit_code:
        acquire_main(["run-plan", "--plan", str(tmp_path / "run-plan.json"), "--check"])
    assert exit_code.value.code == 2
    assert "udv-acquire:" in capsys.readouterr().err


def test_the_eight_job_names_are_the_designs_own() -> None:
    """The pass's identities are readable off the stored names: ``stage2-<level>-<pair>``."""
    plan = run_plan.load_run_plan(PLAN_FILE)
    assert [run_plan.job_prefix(plan, job.job) for job in plan.jobs] == [
        f"stage2-{job}" for _, job, _, _ in EXPECTED_ORDER
    ]


def test_the_committed_sheet_is_what_the_plan_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator sheet is a committed artefact, and it is the plan's own rendering.

    A sheet that drifted from the plan would be read at the machine *as* the pass, so the file the
    operator works from is generated from the plan rather than transcribed from a session. Every
    line is compared except ``directory``, which names where the plan was read from and therefore
    differs between an absolute and a repo-relative invocation (and between platforms) — the
    committed copy carries the repo-relative one, and that line is pinned separately.
    """

    committed = (STAGE2_DIR / "operator-sheet.txt").read_text(encoding="utf-8")
    monkeypatch.chdir(REPO)
    run = run_plan.plan_run_file(Path("examples/stage2-e20-e64/run-plan.json"))
    rendered = run_plan.operator_setup_sheet(run)
    if not rendered.endswith(chr(10)):
        rendered += chr(10)
    assert committed == rendered, (
        "examples/stage2-e20-e64/operator-sheet.txt is stale: re-render it from the plan "
        "(`uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --sheet`)"
    )
    assert committed.splitlines()[1] == "directory   : examples/stage2-e20-e64"
    assert committed.count("--- step ") == 8
    assert "pairs       : 4 counterbalanced pairs" in committed
    # the eight blocks are the frozen order, and no rendering can shuffle them
    for index, (_, job, _, _) in enumerate(EXPECTED_ORDER, start=1):
        assert f"--- step {index} of 8: {job} [run-level] ---" in committed


def test_the_committed_sheet_names_what_to_set_before_each_job() -> None:
    """The operator instruction is in the committed copy, not only in a live rendering."""
    committed = (STAGE2_DIR / "operator-sheet.txt").read_text(encoding="utf-8")
    for _, job, level, role in EXPECTED_ORDER:
        assert (
            f"pair       : {job[-1].upper()}, {role} of 2 — set emissions_per_profile "
            f"{level} for this job" in committed
        ), job
    assert committed.count("the stored file's own word has to agree as well") == 8
    assert "raised facts: ['emissions_per_profile']" in committed


# --------------------------------------------------------------------------------------------
# Provenance: this package cites only what the tree it runs from carries
# --------------------------------------------------------------------------------------------

#: Documents the Stage-2 package cites that belong to the frozen analysis rather than to this pass.
#: They arrive with PR #27's rebase; until then the code cites this pass's own document and this
#: pass's document names them as stack-dependent. An entry here is an allowance, not a licence: the
#: guard below still requires every other cited path to exist in the tree.
STACK_DEPENDENT_CITATIONS: tuple[str, ...] = (
    "docs/dop3000/sparse-pass-analysis-plan.md",
    "reports/sparse-mixer-live-1/decision-table.md",
)

CITED_PATTERN = re.compile(r"(?:docs|reports)/[A-Za-z0-9_./-]+\.(?:md|json)")


def _cited_paths() -> dict[str, list[str]]:
    """Every ``docs/…`` or ``reports/…`` path cited by the Stage-2 package, by where it is cited."""
    sources = {
        "docs/dop3000/stage2-run-plan.md": REPO / "docs/dop3000/stage2-run-plan.md",
        "src/udv_echo_process/acquire/run_plan.py": REPO
        / "src/udv_echo_process/acquire/run_plan.py",
        "tests/test_acquire_stage2_run_plan.py": Path(__file__).resolve(),
    }
    found: dict[str, list[str]] = {}
    for name, path in sources.items():
        text = path.read_text(encoding="utf-8")
        found[name] = sorted(set(CITED_PATTERN.findall(text)))
    return found


def test_every_document_this_package_cites_exists_in_the_tree_it_runs_from() -> None:
    """A compiled campaign may not cite a design authority its own tree does not carry.

    This is the provenance rule the review asked for, as a check rather than a promise: the design's
    authority lives on the frozen analysis branch and lands with PR #27, so until the rebase this
    package cites its own document and that document *names* the analysis as stack-dependent. Any
    other cited path has to exist — and when the rebase brings the analysis documents in, the
    allowance becomes inert rather than wrong.
    """
    for where, cited in _cited_paths().items():
        for path in cited:
            if path in STACK_DEPENDENT_CITATIONS:
                continue
            assert (REPO / path).exists(), (
                f"{where} cites {path}, which is not in this tree: cite what the campaign's own "
                "checkout carries, or name the document as stack-dependent beside the other "
                "STACK_DEPENDENT_CITATIONS"
            )


def test_the_analysis_documents_are_named_as_stack_dependent_while_they_are_absent() -> (
    None
):
    """The gap is stated where a reader meets it, not left to be discovered.

    While they are absent, the pass's own document has to say so — and once the rebase brings them
    in, this check is vacuous rather than stale, so no future session inherits a red suite for
    landing the documents the design belongs to.
    """
    doc = (REPO / "docs/dop3000/stage2-run-plan.md").read_text(encoding="utf-8")
    for path in STACK_DEPENDENT_CITATIONS:
        if (REPO / path).exists():
            continue
        assert Path(path).name in doc, (
            f"{path} is absent and unnamed in the pass's document"
        )
    assert "PR #27" in doc
    assert "depends on the stack rather than on the" in doc
