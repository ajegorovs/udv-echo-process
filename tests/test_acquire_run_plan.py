"""Contract tests for the run plan — ``acquire/run_plan.py`` + its CLI verb.

``test_acquire_campaign.py`` pins the layer that runs *one* job; this module pins the layer above
it: a **pass** of nine jobs whose order, run-wide values, control placement and progress are the
things a single campaign definition cannot express. The design it encodes is
``docs/dop3000/sparse-parameter-set.md`` §3 (accepted, and bound by the WP3 decision table), and
the pass itself is the committed JSON under ``examples/sparse-mixer-first-pass/``.

Everything here is headless: :func:`plan_run` is static by construction, and the pass's record is
folded from manifests this module builds in memory. What the cases assert is the *law*:

- the committed pass plans clean, and its nine jobs, its counts and its per-job conditions are the
  ones ``decision-table.md`` carries — read through the decision-layer validator's own
  :func:`parse_rows`/:func:`compute_counts`, so the plan and the documents cannot drift apart
  silently;
- the two control kinds stay different: a block-local control is the pass's reference window at its
  own job's run-wide values and sits at the beginning / middle / end of that job's order, and a
  common-reference job is exactly one recording of the *true* reference condition;
- D1 cannot be expressed at all — the models carry no ``sensitivity`` field, so a file that names
  one is refused by name rather than compiled into a plan;
- the block cap a pass declares cannot wrap any of its points, whatever the achieved period is;
- and a pass cannot be run out of order: :func:`record_job` refuses a job whose predecessor is not
  ok, which is the one thing a per-job resume cannot check.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from udv_echo_process.acquire import campaign, run_plan
from udv_echo_process.acquire.campaign import JobManifest, ManifestPoint
from udv_echo_process.acquire.log import PointStatus
from udv_echo_process.cli import acquire_main

#: Repository root, from this file's own location (``tests/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The committed pass this module is about.
PASS_DIR = REPO / "examples" / "sparse-mixer-first-pass"
PLAN_FILE = PASS_DIR / "run-plan.json"

#: The mixer-enabled realization of the *same* design, run on 2026-09-21: its own plan name
#: and root, its own record, and nothing scientific moved. Its own test below pins that.
LIVE_PASS_DIR = REPO / "examples" / "sparse-mixer-live-1"
LIVE_PLAN_FILE = LIVE_PASS_DIR / "run-plan.json"

#: The decision-layer validator's own parser, so the cross-check reads the documents the way the
#: gate that guards them does.
TOOL_PATH = REPO / "tools" / "validate_decision_layer.py"

#: The nine jobs, in the order the design runs them (``sparse-parameter-set.md`` §3.2: one
#: common-reference job between each pair of scientific jobs).
EXPECTED_ORDER: tuple[tuple[int, str, str, int, int], ...] = (
    (1, "burst-4", "scientific", 4, 20),
    (2, "common-reference-1", "common-reference", 10, 20),
    (3, "burst-18", "scientific", 18, 20),
    (4, "common-reference-2", "common-reference", 10, 20),
    (5, "emissions-8", "scientific", 10, 8),
    (6, "common-reference-3", "common-reference", 10, 20),
    (7, "emissions-64", "scientific", 10, 64),
    (8, "common-reference-4", "common-reference", 10, 20),
    (9, "emissions-128", "scientific", 10, 128),
)

#: The window each scientific row of the pass is acquired at, by label (``§3.1``'s rows).
EXPECTED_SCIENTIFIC: dict[str, tuple[float, int]] = {
    "cc1": (0.617, 145),
    "cc3": (2.96, 31),
    "cc2": (0.617, 145),
    "cc4": (2.96, 31),
    "e8": (1.85, 50),
    "e64": (1.85, 50),
    "e128": (1.85, 50),
}

REFERENCE_WINDOW = (1.85, 50)


def _load_decision_layer():
    """Import the WP4 validator from ``tools/`` (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("validate_decision_layer_plan", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def committed_run() -> run_plan.PlannedRun:
    """The committed pass, planned — the fixture every case here starts from."""
    return run_plan.plan_run_file(PLAN_FILE)


def pass_copy(tmp_path: Path) -> Path:
    """A mutable copy of the committed pass: the ten JSON files, nothing else."""
    target = tmp_path / "pass"
    shutil.copytree(PASS_DIR, target)
    return target


def plan_payload(path: Path) -> dict:
    """The run plan's own JSON, as a dictionary to mutate."""
    return json.loads((path / "run-plan.json").read_text(encoding="utf-8"))


def job_payload(path: Path, job: str) -> dict:
    """One job definition's JSON, as a dictionary to mutate."""
    return json.loads((path / "jobs" / f"{job}.json").read_text(encoding="utf-8"))


def write_plan(path: Path, payload: dict) -> None:
    (path / "run-plan.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def write_job(path: Path, job: str, payload: dict) -> None:
    (path / "jobs" / f"{job}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def refuses(path: Path) -> str:
    """Plan the pass at ``path`` and return the refusal's message.

    A run-plan refusal is a :class:`~udv_echo_process.acquire.run_plan.RunPlanError`, which is a
    :class:`~udv_echo_process.acquire.campaign.CampaignError`; a *job file* that cannot be loaded
    is refused by the campaign loader, which raises the parent. Both are the same answer to a
    caller, so the cases below assert on the parent and on the message.
    """
    with pytest.raises(campaign.CampaignError) as error:
        run_plan.plan_run_file(path / "run-plan.json")
    return str(error.value)


def job_manifest_for(
    run: run_plan.PlannedRun,
    job: run_plan.PlannedJob,
    *,
    ok: int | None = None,
    failed: int = 0,
    aborted: bool = False,
    declared_only: bool = False,
    skipped: tuple[str, ...] = (),
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
    moment = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    return JobManifest(
        job=job.job,
        fingerprint=job.definition_fingerprint,
        channel=run.channel,
        planned=job.recordings,
        skipped=skipped,
        started_at=moment,
        finished_at=moment,
        outcomes=tuple(outcomes),
        declared_only=declared_only,
    )


# --------------------------------------------------------------------------------------------
# The committed pass
# --------------------------------------------------------------------------------------------


def test_the_committed_pass_plans_clean() -> None:
    """The acceptance criterion in one case: nine jobs compile as written, statically."""
    run = committed_run()
    assert [
        (job.step, job.job, job.kind.value, job.condition.burst_length,
         job.condition.emissions_per_profile)
        for job in run.jobs
    ] == list(EXPECTED_ORDER)
    assert len(run.scientific_jobs) == 5
    assert len(run.common_reference_jobs) == 4


def test_the_pass_counts_are_the_designs_counts() -> None:
    """Nine jobs, 26 recordings: 7 scientific + 15 block-local controls + 4 reference checks."""
    run = committed_run()
    assert run.counts == {
        "unique_new_conditions": 7,
        "blocked_conditions": 0,
        "executable_scientific_recordings": 7,
        "block_local_control_recordings": 15,
        "common_reference_recordings": 4,
        "executable_jobs": 9,
        "recordings_first_pass": 26,
    }
    assert run.recordings == 26


def test_every_job_records_at_the_passes_frame() -> None:
    """One channel, one window length, one frame, one store directory, one cap for the pass."""
    run = committed_run()
    assert run.channel == 1
    assert run.duration_s == 12.0
    # §4's assumption is a window of at least 11.52 s, so every record can be truncated to the
    # same common-duration window as its comparand.
    assert run.duration_s >= 11.52
    assert run.sound_speed_ms == 1480.0
    assert run.first_gate_mm == 10.0
    assert run.store_dir == "outputs/live/store"
    for job in run.jobs:
        assert job.condition.prf_us == 600.0


def test_the_exact_kind_sequence_is_science_reference_science(tmp_path: Path) -> None:
    """The concrete sequence, not a name or a count: S, R, S, R, S, R, S, R, S.

    ``RunPlan._check_structure`` proves each reference job is *interior* and that no two are
    adjacent; it does not require a reference job between every pair of scientific jobs (a plan may
    legitimately have two scientific jobs in a row). So the pass's own sequence is pinned here,
    where the design's order lives.
    """
    run = committed_run()
    assert [job.kind.value for job in run.jobs] == [
        "scientific",
        "common-reference",
        "scientific",
        "common-reference",
        "scientific",
        "common-reference",
        "scientific",
        "common-reference",
        "scientific",
    ]
    # And generically: two scientific jobs in a row are *allowed* by the validator, which is
    # exactly why the committed sequence needs its own case.
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["jobs"][1]["kind"] = "scientific"
    payload["jobs"][2]["kind"] = "common-reference"
    payload["jobs"][3]["kind"] = "scientific"
    write_plan(path, payload)
    kinds = [
        job.kind.value for job in run_plan.load_run_plan(path / "run-plan.json").jobs
    ]
    assert kinds[:3] == ["scientific", "scientific", "common-reference"]


def test_the_scientific_rows_are_the_designs_windows() -> None:
    run = committed_run()
    windows = {
        label: (point.parameters.resolution_mm, point.parameters.gates)
        for job in run.scientific_jobs
        for point in job.points
        for label in (point.label,)
        if not point.label.startswith("ctrl-")
    }
    assert windows == EXPECTED_SCIENTIFIC


def test_each_scientific_job_places_its_three_controls_at_begin_middle_end() -> None:
    """The within-job order the WP4 rows deliberately do not encode (plan §10.2)."""
    run = committed_run()
    expected_orders = {
        "burst-4": ("ctrl-begin", "cc1", "ctrl-mid", "cc3", "ctrl-end"),
        "burst-18": ("ctrl-begin", "cc2", "ctrl-mid", "cc4", "ctrl-end"),
        "emissions-8": ("ctrl-begin", "e8", "ctrl-mid", "ctrl-end"),
        "emissions-64": ("ctrl-begin", "e64", "ctrl-mid", "ctrl-end"),
        "emissions-128": ("ctrl-begin", "e128", "ctrl-mid", "ctrl-end"),
    }
    for job in run.jobs:
        labels = tuple(point.label for point in job.points)
        if job.kind is run_plan.JobKind.SCIENTIFIC:
            assert labels == expected_orders[job.job]
            assert job.control_labels == run_plan.CONTROL_LABELS
        else:
            assert labels == (f"cr{job.step // 2}",)


def test_every_control_is_the_passes_reference_window() -> None:
    """A control repeats the job's own anchor at that job's run-wide values (design §3.2)."""
    run = committed_run()
    for job in run.scientific_jobs:
        for point in job.points:
            if not point.label.startswith(run_plan.CONTROL_PREFIX):
                continue
            assert (
                point.parameters.resolution_mm,
                point.parameters.gates,
            ) == REFERENCE_WINDOW


def test_every_common_reference_job_is_one_recording_of_the_reference_condition() -> None:
    run = committed_run()
    for job in run.common_reference_jobs:
        assert job.recordings == 1
        assert job.condition.as_triple == run.reference_condition.as_triple
        assert (
            job.points[0].parameters.resolution_mm,
            job.points[0].parameters.gates,
        ) == REFERENCE_WINDOW


def test_the_separations_are_the_order_the_design_intends() -> None:
    """Each reference check sits between the two scientific jobs it is a check between."""
    run = committed_run()
    assert run_plan.separates(run, "common-reference-1") == ("burst-4", "burst-18")
    assert run_plan.separates(run, "common-reference-2") == ("burst-18", "emissions-8")
    assert run_plan.separates(run, "common-reference-3") == ("emissions-8", "emissions-64")
    assert run_plan.separates(run, "common-reference-4") == ("emissions-64", "emissions-128")
    assert run_plan.separates(run, "burst-4") == (None, None)


def test_identities_are_unique_across_the_whole_pass() -> None:
    """One store directory and one name-prefix root: no two jobs may name one file."""
    run = committed_run()
    identities = [point.identity for job in run.jobs for point in job.points]
    assert len(set(identities)) == len(identities) == run.recordings
    assert identities[0] == "sparse1-burst-4-ctrl-begin"
    assert run_plan.job_prefix(
        run_plan.load_run_plan(PLAN_FILE), "burst-4"
    ) == "sparse1-burst-4"


def test_the_declared_block_cap_is_the_passes_own_requirement() -> None:
    """The cap is declared, not defaulted, and it cannot wrap any point of the pass."""
    run = committed_run()
    # The floor period of one profile is emissions x PRF, so the worst case is emissions-8:
    # ceil(12 s / (8 x 600 us)) = 2500 profiles.
    assert run.required_block_cap == 2500
    assert run.max_profiles_per_block == run.required_block_cap


def test_the_log_and_record_paths_are_derived_from_the_plan() -> None:
    plan = run_plan.load_run_plan(PLAN_FILE)
    job = plan.jobs[0]
    assert run_plan.job_log_path(plan, job) == Path(
        "outputs/live/store/sparse-mixer-first-pass-burst-4.jsonl"
    )
    assert run_plan.run_manifest_path(plan) == Path(
        "outputs/live/store/sparse-mixer-first-pass.run.json"
    )
    assert run_plan.job_log_path(
        plan, job, store_dir="C:/tmp/store"
    ) == Path("C:/tmp/store/sparse-mixer-first-pass-burst-4.jsonl")


def test_the_expected_point_order_is_begin_middle_end_for_one_and_two_rows() -> None:
    assert run_plan.expected_point_order(("a",)) == (
        "ctrl-begin",
        "a",
        "ctrl-mid",
        "ctrl-end",
    )
    assert run_plan.expected_point_order(("a", "b")) == (
        "ctrl-begin",
        "a",
        "ctrl-mid",
        "b",
        "ctrl-end",
    )
    assert run_plan.expected_point_order(("a", "b", "c")) == (
        "ctrl-begin",
        "a",
        "b",
        "ctrl-mid",
        "c",
        "ctrl-end",
    )
    with pytest.raises(ValueError):
        run_plan.expected_point_order(())


def test_the_plan_hash_is_stable_and_moves_with_the_content() -> None:
    plan = run_plan.load_run_plan(PLAN_FILE)
    assert run_plan.plan_fingerprint(plan) == run_plan.plan_fingerprint(plan)
    other = plan.model_copy(update={"duration_s": 13.0})
    assert run_plan.plan_fingerprint(other) != run_plan.plan_fingerprint(plan)
    assert committed_run().plan_fingerprint == run_plan.plan_fingerprint(plan)


# --------------------------------------------------------------------------------------------
# The pass against the accepted design's own documents
# --------------------------------------------------------------------------------------------


def test_the_pass_counts_are_the_documents_counts() -> None:
    """The plan and ``decision-table.md`` derive the same numbers, or one of them is wrong."""
    tool = _load_decision_layer()
    text = (REPO / tool.DECISION_TABLE).read_text(encoding="utf-8")
    derived = tool.compute_counts(tool.parse_rows(text, tool.DECISION_TABLE))
    declared = tool.parse_counts(text, tool.DECISION_TABLE)
    assert derived == declared
    run = committed_run()
    for key in (
        "executable_scientific_recordings",
        "block_local_control_recordings",
        "common_reference_recordings",
        "executable_jobs",
        "recordings_first_pass",
    ):
        assert run.counts[key] == derived[key], key
    # The documents carry eight conditions because one of them — D1 — is blocked, and a plan
    # cannot express a condition it cannot run. The relation is asserted rather than assumed.
    assert run.counts["blocked_conditions"] == 0
    assert derived["blocked_conditions"] == 1
    assert derived["unique_new_conditions"] == (
        run.counts["unique_new_conditions"] + derived["blocked_conditions"]
    )


def test_every_job_of_the_pass_is_a_job_of_the_accepted_rows() -> None:
    """Each job's run-wide values and recordings are the rows' own, field for field."""
    tool = _load_decision_layer()
    text = (REPO / tool.DECISION_TABLE).read_text(encoding="utf-8")
    rows = [row for row in tool.parse_rows(text, tool.DECISION_TABLE) if row.job != "none"]
    run = committed_run()
    for job in run.jobs:
        job_rows = [row for row in rows if row.job == job.job]
        assert job_rows, job.job
        assert sum(int(row.recordings) for row in job_rows) == job.recordings
        for row in job_rows:
            assert int(row.burst_cycles) == job.condition.burst_length
            assert int(row.emissions_per_profile) == job.condition.emissions_per_profile
            assert row.sensitivity == "medium"
    # Every executable row belongs to exactly one job of the pass.
    assert {row.job for row in rows} == {job.job for job in run.jobs}


def test_the_scientific_labels_are_the_rows_they_encode() -> None:
    """``cc1`` is CC1: the same window, at the same job, as the decision table's own row."""
    tool = _load_decision_layer()
    text = (REPO / tool.DECISION_TABLE).read_text(encoding="utf-8")
    rows = {
        row.id: row
        for row in tool.parse_rows(text, tool.DECISION_TABLE)
        if row.kind == tool.CONDITION_KIND
    }
    run = committed_run()
    for job in run.scientific_jobs:
        for point in job.points:
            if point.label.startswith(run_plan.CONTROL_PREFIX):
                continue
            row = rows[point.label.upper()]
            assert float(row.resolution_mm) == pytest.approx(
                point.parameters.resolution_mm, abs=5e-4
            )
            assert int(row.gates) == point.parameters.gates
            assert row.job == job.job
            assert int(row.recordings) == 1


def test_the_block_local_rows_carry_three_recordings_at_the_reference_window() -> None:
    tool = _load_decision_layer()
    text = (REPO / tool.DECISION_TABLE).read_text(encoding="utf-8")
    run = committed_run()
    for job in run.scientific_jobs:
        rows = [
            row
            for row in tool.parse_rows(text, tool.DECISION_TABLE)
            if row.kind == tool.BLOCK_LOCAL_KIND and row.job == job.job
        ]
        assert len(rows) == 1
        row = rows[0]
        assert int(row.recordings) == len(job.control_labels) == 3
        assert float(row.resolution_mm) == pytest.approx(REFERENCE_WINDOW[0], abs=5e-4)
        assert int(row.gates) == REFERENCE_WINDOW[1]
        assert row.control_kind == tool.BLOCK_LOCAL_CONTROL_KIND


def test_no_file_of_the_pass_names_a_sensitivity() -> None:
    """D1's one blocked term cannot be written into this vocabulary at all."""
    for path in sorted(PASS_DIR.rglob("*.json")):
        assert "sensitivity" not in json.loads(path.read_text(encoding="utf-8")), path


# --------------------------------------------------------------------------------------------
# Refusals: one field at a time
# --------------------------------------------------------------------------------------------


def test_a_job_that_disagrees_with_the_plans_run_wide_value_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["burst_length"] = 18
    write_job(path, "burst-4", payload)
    message = refuses(path)
    assert "burst_length" in message and "18" in message and "4" in message


def test_a_job_file_that_names_another_job_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["job"] = "burst-18"
    write_job(path, "burst-4", payload)
    assert "declares job" in refuses(path)


def test_a_point_off_the_plans_window_frame_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["points"][1]["parameters"]["first_gate_mm"] = 2.0
    write_job(path, "burst-4", payload)
    message = refuses(path)
    assert "first_gate_mm" in message and "dialog-only" in message


def test_a_window_the_plan_does_not_declare_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["points"][1]["parameters"]["resolution_mm"] = 1.2333333
    payload["points"][1]["parameters"]["gates"] = 74
    write_job(path, "burst-4", payload)
    message = refuses(path)
    assert "not one of the pass's windows" in message


def test_a_declared_window_that_nothing_acquires_is_refused(tmp_path: Path) -> None:
    """A plan that declares a condition and never records it is a design the pass does not have."""
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["windows"].append({"resolution_mm": 1.2333333, "gates": 74})
    write_plan(path, payload)
    assert "windows nothing acquires" in refuses(path)


def test_a_block_local_control_off_the_reference_window_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["points"][0]["parameters"]["gates"] = 31
    payload["points"][0]["parameters"]["resolution_mm"] = 2.96
    write_job(path, "burst-4", payload)
    assert "block-local control" in refuses(path)


def test_a_scientific_job_at_the_reference_condition_is_refused(tmp_path: Path) -> None:
    """The design acquires no new condition at burst 10 / emissions 20."""
    path = pass_copy(tmp_path)
    payload = job_payload(path, "emissions-64")
    payload["emissions_per_profile"] = 20
    write_job(path, "emissions-64", payload)
    plan = plan_payload(path)
    plan["jobs"][6]["condition"]["emissions_per_profile"] = 20
    write_plan(path, plan)
    assert "no new condition" in refuses(path)


def test_a_job_that_moves_the_prf_is_refused(tmp_path: Path) -> None:
    """§1 holds the PRF period for the whole augmentation; 250 us is deferred, not acquired."""
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["prf_us"] = 400.0
    write_job(path, "burst-4", payload)
    plan = plan_payload(path)
    plan["jobs"][0]["condition"]["prf_us"] = 400.0
    write_plan(path, plan)
    message = refuses(path)
    assert "PRF 400 us" in message and "holds 600" in message


def test_a_job_whose_plan_entry_disagrees_with_its_file_is_refused(tmp_path: Path) -> None:
    """The plan states a job's run-wide values and the definition states them again."""
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["emissions_per_profile"] = 64
    write_job(path, "burst-4", payload)
    message = refuses(path)
    assert "emissions_per_profile" in message and "run-wide" in message


def test_a_common_reference_job_at_another_condition_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "common-reference-2")
    payload["burst_length"] = 4
    write_job(path, "common-reference-2", payload)
    plan = plan_payload(path)
    plan["jobs"][3]["condition"]["burst_length"] = 4
    write_plan(path, plan)
    message = refuses(path)
    assert "reference condition" in message


def test_a_common_reference_job_with_two_points_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "common-reference-1")
    payload["points"].append(json.loads(json.dumps(payload["points"][0])))
    payload["points"][1]["label"] = "cr1b"
    write_job(path, "common-reference-1", payload)
    assert "one recording" in refuses(path)


def test_a_common_reference_record_labelled_as_a_control_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "common-reference-1")
    payload["points"][0]["label"] = "ctrl-begin"
    write_job(path, "common-reference-1", payload)
    assert "not a block-local control" in refuses(path)


def test_two_jobs_sharing_a_label_are_refused(tmp_path: Path) -> None:
    """Identity is what a resume keys on, and the pass stores into one directory."""
    path = pass_copy(tmp_path)
    payload = job_payload(path, "common-reference-2")
    payload["name_prefix"] = "sparse1-burst-4"
    write_job(path, "common-reference-2", payload)
    message = refuses(path)
    assert "name_prefix" in message and "identity" not in message.split("\n")[0]


def test_a_job_whose_controls_are_not_at_begin_middle_end_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    points = payload["points"]
    payload["points"] = [points[0], points[2], points[1], points[3], points[4]]
    write_job(path, "burst-4", payload)
    assert "within-job order" in refuses(path)


def test_a_job_acquiring_one_window_twice_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["points"][3]["parameters"]["resolution_mm"] = 0.617
    payload["points"][3]["parameters"]["gates"] = 145
    write_job(path, "burst-4", payload)
    assert "twice" in refuses(path)


def test_a_block_cap_below_the_requirement_is_refused(tmp_path: Path) -> None:
    """The cap a pass declares is its own requirement, and the refusal names the number."""
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["max_profiles_per_block"] = 2400
    write_plan(path, payload)
    # Every job declares the pass's cap too, and a job that disagreed would be refused for that
    # reason instead — so the whole pass is moved together, as an author would move it.
    for job in payload["jobs"]:
        name = job["job"]
        body = job_payload(path, name)
        body["max_profiles_per_block"] = 2400
        write_job(path, name, body)
    message = refuses(path)
    assert "2400" in message and "at least 2500" in message


# ------------------------------------------------ the same design, a new run identity


def test_the_live_pass_is_the_same_design_under_a_new_identity() -> None:
    """The mixer pass is the frozen design re-run, and only its identity may differ.

    ``examples/sparse-mixer-live-1/`` is a derived copy of the frozen first pass, run on a
    mixer that measures. Everything the *experiment* is — the nine jobs in their order, their
    conditions, the points and their windows, the frame, the block cap and the raised facts —
    has to be equal, and only what names *this run* may move: the plan's name, its root, the
    directory it lives in, and the hashes that follow from those. Stating the claim in a
    README is not enough; without this, a later edit to one plan could silently turn the
    repeat into a different experiment.
    """
    first = run_plan.plan_run_file(PLAN_FILE)
    live = run_plan.plan_run_file(LIVE_PLAN_FILE)

    # Provenance, and only provenance: four fields, all of them naming this run.
    assert live.plan != first.plan
    assert live.name_prefix != first.name_prefix
    assert live.directory != first.directory
    assert live.plan_fingerprint != first.plan_fingerprint

    # The experiment itself, field for field.
    for field in (
        "channel",
        "duration_s",
        "store_dir",
        "max_profiles_per_block",
        "sound_speed_ms",
        "first_gate_mm",
        "reference_window",
        "reference_condition",
        "strict_facts",
    ):
        assert getattr(live, field) == getattr(first, field), field

    assert live.recordings == first.recordings == 26
    assert [job.job for job in live.jobs] == [job.job for job in first.jobs]
    assert [job.step for job in live.jobs] == [job.step for job in first.jobs]
    assert [job.kind for job in live.jobs] == [job.kind for job in first.jobs]
    assert [job.condition for job in live.jobs] == [job.condition for job in first.jobs]
    assert [job.definition for job in live.jobs] == [job.definition for job in first.jobs]
    # The definition hash covers the naming prefix, so it moves with the run identity — and it
    # is the only per-job field that does.
    assert [job.definition_fingerprint for job in live.jobs] != [
        job.definition_fingerprint for job in first.jobs
    ]

    for live_job, first_job in zip(live.jobs, first.jobs, strict=True):
        # The job files themselves: identical once the prefix — the one field a derived copy
        # has to change — is taken out.
        live_definition = campaign.load_campaign(LIVE_PASS_DIR / live_job.definition)
        first_definition = campaign.load_campaign(PASS_DIR / first_job.definition)
        assert live_definition.name_prefix == f"{live.name_prefix}-{live_job.job}"
        assert first_definition.name_prefix == f"{first.name_prefix}-{first_job.job}"
        assert live_definition.model_dump(
            exclude={"name_prefix"}
        ) == first_definition.model_dump(exclude={"name_prefix"})

        assert [point.label for point in live_job.points] == [
            point.label for point in first_job.points
        ]
        for live_point, first_point in zip(
            live_job.points, first_job.points, strict=True
        ):
            assert live_point.parameters == first_point.parameters
            assert live_point.duration_s == first_point.duration_s
            assert live_point.profiles == first_point.profiles
            assert live_point.expected_depth_mm == first_point.expected_depth_mm
            # A point's identity is its label under this pass's root, so it is the point-level
            # counterpart of the same normalization.
            assert live_point.identity == (
                f"{live.name_prefix}-{live_job.job}-{live_point.label}"
            )
            assert first_point.identity == (
                f"{first.name_prefix}-{first_job.job}-{first_point.label}"
            )


def test_a_point_that_overrides_its_window_length_above_the_cap_is_refused(
    tmp_path: Path,
) -> None:
    """A one-off longer window is the one way a point can wrap a cap the pass itself satisfies."""
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    # 60 s at the job's own period is 2655 profiles, well past the pass's declared 2500: the
    # requirement check is satisfied (2500 *is* the requirement) and the point's own note fires.
    payload["points"][1]["duration_s"] = 60.0
    write_job(path, "burst-4", payload)
    message = refuses(path)
    assert "wraps the pass's own declared block cap" in message
    assert "2655 profiles" in message


def test_a_file_that_names_a_sensitivity_is_refused_by_field(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = job_payload(path, "burst-4")
    payload["sensitivity"] = "high"
    write_job(path, "burst-4", payload)
    assert "sensitivity" in refuses(path)


def test_a_definition_outside_the_plans_directory_is_refused(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["jobs"][0]["definition"] = "../burst-4.json"
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    assert "climbs out" in str(error.value)


def test_the_job_sequence_must_alternate_scientific_and_reference(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["jobs"][0]["kind"] = "common-reference"
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    assert "open and close on a scientific job" in str(error.value)

    payload = plan_payload(path)
    payload["jobs"][0]["kind"] = "scientific"
    payload["jobs"][1]["kind"] = "scientific"
    payload["jobs"][2]["kind"] = "common-reference"
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    assert "two common-reference jobs are adjacent" in str(error.value)


def test_steps_must_be_one_to_n_in_order(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["jobs"][2]["step"] = 4
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    assert "step numbers" in str(error.value)


def test_the_same_definition_cannot_be_two_jobs(tmp_path: Path) -> None:
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["jobs"][1]["definition"] = payload["jobs"][0]["definition"]
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    assert "one definition file" in str(error.value)


def test_an_unknown_job_has_no_separation() -> None:
    run = committed_run()
    with pytest.raises(run_plan.RunPlanError):
        run_plan.separates(run, "burst-9")


# --------------------------------------------------------------------------------------------
# The pass's own record
# --------------------------------------------------------------------------------------------


def test_a_fresh_record_is_every_job_pending_and_the_first_one_next() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    assert [record.status.value for record in manifest.jobs] == ["pending"] * 9
    assert manifest.next_step == 1
    assert run_plan.next_job(run, manifest).job == "burst-4"
    assert not manifest.complete
    assert "0/9 job(s) ok" in manifest.summary


def test_recording_a_job_folds_its_own_manifest_into_the_pass(tmp_path: Path) -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[0]
    manifest = run_plan.record_job(
        manifest,
        run,
        job,
        job_manifest_for(run, job),
        now=datetime(2026, 9, 20, 12, 30, tzinfo=UTC),
    )
    record = manifest.jobs[0]
    assert record.status is run_plan.RunJobStatus.OK
    assert record.ok_recordings == 5
    assert record.manifest is not None and record.manifest.endswith(".manifest.json")
    assert manifest.updated_at > manifest.created_at
    assert manifest.next_step == 2
    assert run_plan.next_job(run, manifest).job == "common-reference-1"
    # A round trip through disk changes nothing: the record is what a later session reads.
    path = tmp_path / "run.json"
    run_plan.write_run_manifest(path, manifest)
    assert run_plan.read_run_manifest(path) == manifest


def test_a_job_that_is_not_next_is_refused_by_name(tmp_path: Path) -> None:
    """The cross-job order is the one thing a per-job resume cannot check."""
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.record_job(
            manifest, run, run.jobs[2], job_manifest_for(run, run.jobs[2])
        )
    message = str(error.value)
    assert "not the next job" in message
    assert "burst-4" in message and "pending" in message


def test_raising_a_fact_no_stored_file_carries_is_refused_by_the_plan(tmp_path: Path) -> None:
    """The plan's own vocabulary check: a raise has to be enforceable on both sides of a recording."""
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["strict_facts"] = ["max_profiles_per_block"]
    write_plan(path, payload)
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.load_run_plan(path / "run-plan.json")
    message = str(error.value)
    assert "max_profiles_per_block" in message
    assert "raiseable facts" in message


def test_a_raise_only_holds_for_a_fact_every_job_states(tmp_path: Path) -> None:
    """The raise relies on every job declaring the fact, and the guard says so.

    Today's vocabulary makes the guard unreachable — every strictable fact is required by
    ``CampaignDefinition`` or by its points — so this case drives the check directly, with a
    definition that states nothing for the raised fact. It exists because the vocabulary is a table
    rather than a law: an optional fixed fact added to it would otherwise let a raise compare
    nothing while the plan still read as stricter than it is.
    """
    plan = run_plan.load_run_plan(PLAN_FILE)
    entry = plan.jobs[0]
    definition = campaign.load_campaign(PASS_DIR / entry.definition)
    silent = definition.model_copy(update={"burst_length": None})
    raised = plan.model_copy(update={"strict_facts": ("burst_length",)})

    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan._check_raised_facts(raised, entry, silent)

    message = str(error.value)
    assert "burst_length" in message
    assert "declares no value for" in message
    # And with the fact stated, the same check is satisfied.
    run_plan._check_raised_facts(raised, entry, definition)


def test_a_record_that_answers_another_plan_is_refused(tmp_path: Path) -> None:
    """A pass's record and the plan it was run from are one thing — by hash, both sides named."""
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    plan = run_plan.load_run_plan(PLAN_FILE)
    edited_plan = plan.model_copy(
        update={"strict_facts": ("emissions_per_profile", "burst_length")}
    )
    edited = run_plan.plan_run(edited_plan, directory=PASS_DIR)
    assert edited.plan_fingerprint != run.plan_fingerprint

    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.next_job(edited, manifest)
    assert "plan fingerprint" in str(error.value)

    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.record_job(
            manifest, edited, edited.jobs[0], job_manifest_for(run, run.jobs[0])
        )
    assert "plan fingerprint" in str(error.value)


def test_a_job_whose_outcome_is_partial_is_recorded_as_such() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[0]
    manifest = run_plan.record_job(
        manifest, run, job, job_manifest_for(run, job, ok=4, failed=1)
    )
    record = manifest.jobs[0]
    assert record.status is run_plan.RunJobStatus.PARTIAL
    assert record.ok_recordings == 4
    assert record.note is not None and "not ok" in record.note
    # A partial job still stands in front of the pass: the next job is the same one.
    assert run_plan.next_job(run, manifest).job == "burst-4"


def test_a_job_with_no_ok_point_is_failed() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[1]
    earlier = run_plan.record_job(
        manifest, run, run.jobs[0], job_manifest_for(run, run.jobs[0])
    )
    manifest = run_plan.record_job(
        earlier, run, job, job_manifest_for(run, job, ok=0, failed=1)
    )
    assert manifest.jobs[1].status is run_plan.RunJobStatus.FAILED
    assert manifest.next_step == 2


def test_a_manifest_from_another_job_or_definition_is_refused() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[0]
    other = job_manifest_for(run, run.jobs[0]).model_copy(update={"job": "burst-18"})
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.record_job(manifest, run, job, other)
    assert "the manifest reports job" in str(error.value)

    changed = job_manifest_for(run, job).model_copy(update={"fingerprint": "0" * 64})
    with pytest.raises(run_plan.RunPlanError) as error:
        run_plan.record_job(manifest, run, job, changed)
    assert "definition fingerprint" in str(error.value)


def test_the_whole_pass_recorded_is_complete() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    for job in run.jobs:
        manifest = run_plan.record_job(manifest, run, job, job_manifest_for(run, job))
    assert manifest.complete
    assert manifest.next_record is None
    assert run_plan.next_job(run, manifest) is None
    assert "9/9 job(s) ok" in manifest.summary


def test_a_resumed_job_reports_what_it_skipped() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[0]
    manifest = run_plan.record_job(
        manifest,
        run,
        job,
        job_manifest_for(run, job, ok=3, skipped=("sparse1-burst-4-ctrl-begin", "sparse1-burst-4-cc1")),
    )
    assert manifest.jobs[0].skipped == (
        "sparse1-burst-4-ctrl-begin",
        "sparse1-burst-4-cc1",
    )
    assert "skipped" in (manifest.jobs[0].note or "") or "skipped" in manifest.summary


def test_a_declared_only_job_says_so_on_the_pass_record() -> None:
    run = committed_run()
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, tzinfo=UTC))
    job = run.jobs[0]
    manifest = run_plan.record_job(
        manifest, run, job, job_manifest_for(run, job, declared_only=True)
    )
    assert "declared only" in (manifest.jobs[0].note or "")


# --------------------------------------------------------------------------------------------
# The operator's sheet
# --------------------------------------------------------------------------------------------


def test_the_sheet_names_every_job_its_run_wide_values_and_its_points() -> None:
    sheet = run_plan.operator_setup_sheet(committed_run())
    assert "9 (5 scientific, 4 common-reference), 26 recording(s)" in sheet
    for step, job, kind, burst, emissions in EXPECTED_ORDER:
        assert f"--- step {step} of 9: {job} [{kind}] ---" in sheet
        assert (
            f"run-wide   : burst_length {burst}, emissions_per_profile {emissions}, "
            "prf_us 600" in sheet
        )
    # Every point of the pass appears, with its window and identity.
    for job in committed_run().jobs:
        for point in job.points:
            assert point.identity in sheet


def test_the_sheet_says_which_run_wide_fact_refuses_and_which_only_advises() -> None:
    """The pass raises its own axis, and the sheet has to say so in the operator's terms.

    ``emissions_per_profile`` is the one fact the verifier's table calls advisory — for a reason
    (a definition's value for it used to be derived) that does not hold for a pass that *moves* it
    between jobs on purpose. This pass therefore raises it, and both halves are named: the compile
    refuses before the first recording, and the stored file's own word has to agree too.
    """
    run = committed_run()
    assert run.strict_facts == ("emissions_per_profile",)
    sheet = run_plan.operator_setup_sheet(run)
    assert (
        "burst_length: read from the Operating parameters dialog; a disagreement refuses"
        in sheet
    )
    assert (
        "prf_us: read from the measurement screen's parameter column; a disagreement refuses"
        in sheet
    )
    assert "emissions_per_profile: read from the measurement screen's parameter column" in sheet
    assert "this pass raises it to a refusal" in sheet
    assert "the stored file's own word has to agree as well" in sheet
    assert "raised facts: ['emissions_per_profile']" in sheet
    # The default sentence is what an ordinary campaign keeps, and it is not this pass's.
    assert "is advisory to the stored-file verifier — confirm it on the screen" not in sheet


def test_the_sheet_names_the_settings_no_reader_reaches_and_the_cap() -> None:
    sheet = run_plan.operator_setup_sheet(committed_run())
    for name, value in run_plan.MANUAL_SETTINGS:
        assert f"{name}: {value}" in sheet
    assert "at least 2500 profiles" in sheet
    assert "sensitivity: medium — D1's `high` is not acquired in this pass" in sheet
    assert run_plan.REFERENCE_DOCUMENT in sheet


def test_the_sheet_places_each_reference_check_between_its_two_jobs() -> None:
    sheet = run_plan.operator_setup_sheet(committed_run())
    assert "placement  : the reference check between 'burst-4' and 'burst-18'" in sheet
    assert "placement  : the reference check between 'emissions-64' and 'emissions-128'" in sheet


# --------------------------------------------------------------------------------------------
# The CLI verb
# --------------------------------------------------------------------------------------------


def test_the_cli_check_prints_the_jobs_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--check"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "9 job(s), 26 recording(s)" in out
    assert "block cap   : declared 2500, required 2500" in out
    assert "recordings_first_pass=26" in out
    assert "sparse1-burst-4-cc1" in out


def test_the_cli_check_json_is_the_only_thing_on_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--check", "--json"])
    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["plan"] == "sparse-mixer-first-pass"
    assert payload["counts"]["recordings_first_pass"] == 26
    assert payload["required_block_cap"] == payload["max_profiles_per_block"] == 2500
    assert [job["job"] for job in payload["jobs"]] == [
        job for _, job, _, _, _ in EXPECTED_ORDER
    ]
    assert payload["jobs"][1]["separates"] == ["burst-4", "burst-18"]
    assert payload["jobs"][0]["points"][1]["label"] == "cc1"
    # The pass's policy is part of what `--check` states: the one fact it raises.
    assert payload["strict_facts"] == ["emissions_per_profile"]


def test_the_cli_sheet_prints_the_operator_sheet(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--sheet"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert out == run_plan.operator_setup_sheet(committed_run()) + "\n"


def test_the_cli_status_says_the_pass_has_not_started(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "run-plan",
                "--plan",
                str(PLAN_FILE),
                "--status",
                "--store-dir",
                str(store),
            ]
        )
    assert exit_info.value.code == 0
    assert "no run manifest" in capsys.readouterr().out


def test_the_cli_status_reports_a_record_and_the_next_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = committed_run()
    store = tmp_path / "store"
    store.mkdir()
    manifest = run_plan.new_run_manifest(run, store_dir=store)
    manifest = run_plan.record_job(manifest, run, run.jobs[0], job_manifest_for(run, run.jobs[0]))
    run_plan.write_run_manifest(run_plan.run_manifest_path(
        run_plan.load_run_plan(PLAN_FILE), store_dir=store
    ), manifest)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "run-plan",
                "--plan",
                str(PLAN_FILE),
                "--status",
                "--store-dir",
                str(store),
            ]
        )
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "burst-4" in out and "ok" in out
    assert "next        : step 2 common-reference-1" in out


def test_the_cli_next_without_a_declared_process_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--next` records, so it declares the process — the other three actions do not."""
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["run-plan", "--plan", str(PLAN_FILE), "--next"])
    assert exit_info.value.code == 2
    assert "--expect-mode" in capsys.readouterr().err


def test_the_cli_reports_a_refused_plan_in_one_line_and_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = pass_copy(tmp_path)
    payload = plan_payload(path)
    payload["max_profiles_per_block"] = 1000
    write_plan(path, payload)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["run-plan", "--plan", str(path / "run-plan.json"), "--check"])
    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "udv-acquire:" in captured.err and "2500" in captured.err


def test_the_cli_next_hands_the_next_job_to_the_campaign_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--next` runs the job through ``run_campaign`` — the same compiled path, unchanged."""
    store = tmp_path / "store"
    seen: dict[str, object] = {}

    def fake_run_campaign(definition, actuator, **kwargs):
        seen["job"] = definition.job
        seen["log"] = kwargs["log_path"]
        seen["store"] = kwargs["store_dir"]
        seen["resume"] = kwargs["resume"]
        seen["mode"] = kwargs["expected_mode"]
        seen["strict_facts"] = kwargs.get("strict_facts")
        run = committed_run()
        job = next(entry for entry in run.jobs if entry.job == definition.job)
        manifest = job_manifest_for(run, job)
        seen["manifest"] = manifest
        return manifest

    monkeypatch.setattr(campaign, "run_campaign", fake_run_campaign)
    monkeypatch.setattr(
        "udv_echo_process.acquire.live.live_actuator", lambda channel, notes: object()
    )
    monkeypatch.setattr(
        "udv_echo_process.cli.live.live_actuator", lambda channel, notes: object()
    )

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "run-plan",
                "--plan",
                str(PLAN_FILE),
                "--next",
                "--store-dir",
                str(store),
                "--expect-mode",
                "simulation",
            ]
        )
    assert exit_info.value.code == 0
    assert seen["job"] == "burst-4"
    assert str(seen["log"]).endswith("sparse-mixer-first-pass-burst-4.jsonl")
    assert seen["resume"] is True
    # The pass's own policy travels with the job: the compile refuses on it, and the stored file's
    # word is enforced against it.
    assert seen["strict_facts"] == ("emissions_per_profile",)
    # The pass's record is written and stands at step 2 afterwards.
    written = run_plan.read_run_manifest(
        run_plan.run_manifest_path(
            run_plan.load_run_plan(PLAN_FILE), store_dir=store
        )
    )
    assert written.next_step == 2
    assert written.jobs[0].status is run_plan.RunJobStatus.OK
    out = capsys.readouterr().out
    assert "step 1 of 9: burst-4" in out
