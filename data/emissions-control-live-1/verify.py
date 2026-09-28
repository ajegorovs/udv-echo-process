"""Recheck the portable live emissions-control evidence, without instrument access.

What this re-derives **from the committed files alone**:

- the plan's own fingerprint, and the four executed jobs' definition fingerprints,
  conditions and point lists;
- **the emitted event order**, from the committed sanitized runtime records
  (``records/<job>.jsonl``): which jobs appended a ``parameter_mutation`` and which did
  not, the order of the records inside each log, the mutation's writer-layer read-back
  and independent fresh read, and that its definition fingerprint is the committed
  plan's own fingerprint for that job;
- every recording's SHA-256, size, stored operation words (word 14 emissions/profile,
  word 8 burst, word 27 bandwidth-definition index) and decoded configuration.

What it **cannot** re-derive:

- that the committed records are byte-identical to the runtime logs — those stay local
  (they carry absolute machine paths), so only their recorded original SHA-256 values
  are available, in ``manifest.json`` as provenance;
- the compilation identities, which live in the runtime job manifests.

``manifest.json`` is a derived summary; wherever it carries a claim this file can check
against the records, the plan or the recordings, it is checked rather than trusted.

The sitting's accepted properties, each asserted below:

1. ``e20-a`` and ``e64-b`` spent **no write** and appended **no** mutation — an equal
   value is not a transition (no ``parameter_mutation`` record at all);
2. ``e64-a``'s ``20 -> 64`` and ``e20-b``'s ``64 -> 20`` are each one ``verified``
   mutation carrying the writer's own read-back *and* the independent fresh read;
3. the mutation ids are distinct and in occurrence order, and the mutations appear in
   the plan's step order;
4. every stored file's word 14 equals the emissions **its own job requested**, and the
   point record that follows a mutation carries the post-write value;
5. word 8 (burst) is unchanged at 10 in all four, and every other fixed decoded field
   is identical across the four files — only the requested axis moved;
6. word 27 is carried as raw provenance (``1``, as in every committed B4/B5 recording)
   and is never converted to a physical sampling volume.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

from udv_echo_process.acquire.run_plan import plan_run_file
from udv_echo_process.acquire.verify import read_words
from udv_echo_process.io.dop.bdd import read

root = Path(__file__).resolve().parent
report = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

#: (job, requested emissions, whether a write was spent)
expected = [
    ("e20-a", 20, False),
    ("e64-a", 64, True),
    ("e64-b", 64, False),
    ("e20-b", 20, True),
]
#: The store path the records were sanitized onto.
PORTABLE_STORE = "outputs/live/store"
#: What a machine-local path looks like — structural, not *this* machine's own directory
#: names, so the check travels with the package and the detector cannot be mistaken for
#: a path itself (the POSIX branch is deliberately lowercase).
ABSOLUTE_PATH_RE = re.compile(
    r"[A-Za-z]:[\\/]"  # a drive-absolute path: C:\…, C:/…
    r"|\\\\[^\\/\s\"]+[\\/]"  # a UNC share: \\host\share
    r"|(?<![\w.])/(?:home|users|mnt|media|root)/"  # a POSIX home-ish path
)
#: The *hold* is everything the artefact's decoded configuration carries except the
#: requested axis, so the four files must agree on all of it (word 8 burst, word 27
#: sampling_volume_index, PRF, sound speed, gates, resolution, power, sensitivity,
#: TGC, Doppler angle, gate-1 depth, module scale, trigger, wall filter …).


def normalised_sha256(text: str) -> str:
    """Hash LF-normalized content, so a checkout's line endings cannot move it."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def load_records(path: Path) -> list[dict]:
    """The records in the order the run appended them — index preserved, unread."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def stored_stamp(sweep_id: str, tzinfo) -> datetime.datetime:
    return datetime.datetime.strptime(sweep_id, "%Y%m%dT%H%M%S").replace(tzinfo=tzinfo)


assert report["channel"] == 1
assert report["strict_facts"] == ["emissions_per_profile"]
assert report["analysis_orientation"] == "E64 - E20"
assert report["initial_state"]["emissions_per_profile"] == "20"
assert len(report["jobs"]) == len(expected)
# The sanitization rule is part of the contract: the records are portable, not local.
assert "file_path" in report["records_sanitization"]
assert PORTABLE_STORE in report["records_sanitization"]

# The committed plan is the portable copy of the one that ran: re-planning it here
# ties the summary's fingerprints to a plan the reader can inspect.
plan = plan_run_file(root / "plan" / "run-plan.json")
assert plan.plan_fingerprint == report["plan_fingerprint"]
assert [job.step for job in plan.jobs] == [1, 2, 3, 4]
assert [job.job for job in plan.jobs] == [name for name, _, _ in expected]
planned = {job.job: job for job in plan.jobs}
# The committed plan carries no machine-local path either.
for committed_plan in [
    root / "plan" / "run-plan.json",
    *(root / "plan" / "jobs").glob("*.json"),
]:
    assert (
        ABSOLUTE_PATH_RE.search(committed_plan.read_text(encoding="utf-8")) is None
    ), f"{committed_plan.name}: the committed plan carries a machine-local path"

held_reference: dict | None = None
events: list[dict] = []
for step, (job, (name, requested, wrote)) in enumerate(
    zip(report["jobs"], expected, strict=True), start=1
):
    planned_job = planned[name]
    assert job["job"] == name and job["step"] == step
    assert job["status"] == "ok"
    assert job["observed_process_mode"] == "instrument"
    assert planned_job.definition_fingerprint == job["definition_fingerprint"]
    assert planned_job.condition.burst_length == 10
    assert planned_job.condition.emissions_per_profile == requested
    assert planned_job.condition.prf_us == 600.0

    # ---- the emitted event order, re-derived from the committed records ----------
    records_path = root / job["records_file"]
    assert records_path.is_file() and records_path.parent == root / "records"
    assert records_path.name == f"{name}.jsonl"
    records_text = records_path.read_text(encoding="utf-8")
    assert normalised_sha256(records_text) == job["records_sha256"]
    assert ABSOLUTE_PATH_RE.search(records_text) is None, (
        f"{name}: the committed records carry a machine-local path"
    )

    records = load_records(records_path)
    assert len(records) == job["records_lines"]
    assert [record["record_type"] for record in records] == job["records_record_types"]

    mutations_in_log = [
        (index, record)
        for index, record in enumerate(records)
        if record["record_type"] == "parameter_mutation"
    ]
    points_in_log = [
        (index, record)
        for index, record in enumerate(records)
        if record["record_type"] == "point"
    ]
    assert len(points_in_log) == 1
    point_index, point_record = points_in_log[0]

    if wrote:
        assert len(mutations_in_log) == 1
        mutation_index, mutation = mutations_in_log[0]
        # The mutation is the log's first record, appended *before* the point record.
        assert mutation_index == 0
        assert mutation_index < point_index
        evidence = mutation["evidence"]
        assert mutation["job"] == name
        assert mutation["parameter"] == "emissions_per_profile"
        assert mutation["routed_channel"] == 1
        assert evidence["role"] == "emissions_per_profile"
        assert evidence["state"] == "verified"
        assert evidence["reason"] == ""
        # the transition left the *other* level behind it, and requested it exactly
        assert evidence["before"] == str(20 if requested == 64 else 64)
        assert evidence["requested"] == str(requested)
        # the writer layer's own read-back, then the independent fresh read
        assert evidence["write_readback"] == str(requested)
        assert evidence["after"] == str(requested)
        # the mutation names the committed plan's own fingerprint for this job
        assert mutation["fingerprint"] == planned_job.definition_fingerprint
        assert mutation["fingerprint"] == job["definition_fingerprint"]
        # the point record that follows carries the post-write value
        assert point_record["decoded"]["emissions_per_profile"] == requested
        # the write is stamped before the store it precedes, and inside the job's window
        occurred = datetime.datetime.fromisoformat(mutation["occurred_at"])
        assert occurred <= stored_stamp(point_record["sweep_id"], occurred.tzinfo)
        assert (
            datetime.datetime.fromisoformat(job["started_at"])
            <= occurred
            <= datetime.datetime.fromisoformat(job["finished_at"])
        )
        events.append(
            {
                "job": name,
                "step": step,
                "mutation_id": mutation["mutation_id"],
                "occurred_at": mutation["occurred_at"],
                "before": evidence["before"],
                "requested": evidence["requested"],
                "write_readback": evidence["write_readback"],
                "fresh_read": evidence["after"],
                "definition_fingerprint": mutation["fingerprint"],
            }
        )
        # The summary's own history for this job reflects the record it came from.
        assert job["write_spent"] is True
        assert job["no_write_note"] is None
        assert [entry["mutation_id"] for entry in job["parameter_mutations"]] == [
            mutation["mutation_id"]
        ]
        assert job["parameter_mutations"][0]["before"] == evidence["before"]
        assert job["parameter_mutations"][0]["fresh_read"] == evidence["after"]
    else:
        # (1) the accepted no-write branch: no event at all, in the run's own words
        assert mutations_in_log == []
        assert job["write_spent"] is False
        assert f"already states {requested}" in job["no_write_note"]
        assert "no write was spent" in job["no_write_note"]
        assert job["parameter_mutations"] == []
        assert point_record["decoded"]["emissions_per_profile"] == requested

    assert len(job["points"]) == 1
    point = job["points"][0]
    assert point["status"] == "ok" and point["failure"] is None
    assert [p.label for p in planned_job.points] == [point["label"]]
    assert point["identity"].startswith(planned_job.points[0].identity)
    assert point["enforced_covariates"] == [
        "sound_speed_ms",
        "prf_us",
        "burst_length",
        "emissions_per_profile",
    ]
    # The point record names the committed artefact, portably.
    assert point_record["name"].startswith(point["identity"])
    assert point_record["name"] == point["file"].removesuffix(".BDD")
    assert point_record["file_path"] == f"{PORTABLE_STORE}/{point['file']}"
    assert point_record["status"] == "ok"
    assert point_record["file_size_bytes"] == point["bytes"]
    # The plan's own request for this point, re-derived from the committed plan.
    assert {
        key: str(value)
        for key, value in planned_job.points[0].parameters.model_dump().items()
    } == {key: str(value) for key, value in point_record["requested"].items()}
    assert {key: str(value) for key, value in point["requested"].items()} == {
        key: str(value) for key, value in point_record["requested"].items()
    }

    path = root / point["file"]
    assert path.is_file() and path.parent == root
    assert hashlib.sha256(path.read_bytes()).hexdigest() == point["sha256"]
    assert path.stat().st_size == point["bytes"]

    # (4) the stored word 14 is the emissions this job requested — the strict oracle.
    words = read_words(path)
    assert words.emissions_per_profile == requested
    assert words.burst_length == 10
    assert words.prf_us == 600
    assert words.sound_speed_ms == 1480
    assert words.bandwidth_definition_index == 1
    assert words.gates == 50
    assert round(words.resolution_mm, 6) == 1.85
    assert point["word14_emissions_per_profile"] == requested
    assert (
        point["word14_emissions_per_profile"]
        == point_record["decoded"]["emissions_per_profile"]
    )
    assert point["word8_burst_length"] == 10
    assert (
        point["word27_bandwidth_definition_index"]
        == words.bandwidth_definition_index
        == 1
    )

    config = read(path).recording.streams[0].config.model_dump()
    assert config == point["decoded_config"]

    # (6) word 27 is carried as raw provenance in both readings, and no physical
    # sampling volume is derived from it.
    assert point["word27_sampling_volume_index"] == config["sampling_volume_index"] == 1
    assert point["word27_sampling_volume_mm"] is None
    assert config["sampling_volume_mm"] is None

    # The log's own block and the artefact agree on the two words that decide the run.
    assert point["log_decoded"]["emissions_per_profile"] == requested
    assert point["log_decoded"]["burst_length"] == config["burst_length"] == 10

    # (5) the hold: only the requested axis moved.
    held = {
        key: value for key, value in config.items() if key != "emissions_per_profile"
    }
    assert set(held) == set(config) - {"emissions_per_profile"}
    if held_reference is None:
        held_reference = held
    assert held == held_reference, (
        f"{name}: a held field moved: {held} != {held_reference}"
    )
    print(f"{name}: word 14 = {requested}, {point['bytes']} B, wrote={wrote}")

# (3) the durable history, re-derived from the committed records and then tied to the
# summary: distinct ids, occurrence order, and the plan's step order for the jobs.
assert len(events) == 2
assert [event["job"] for event in events] == ["e64-a", "e20-b"]
assert [event["step"] for event in events] == sorted(event["step"] for event in events)
ids = [event["mutation_id"] for event in events]
assert len(set(ids)) == len(ids)  # every actual mutation id is distinct
occurred = [event["occurred_at"] for event in events]
assert occurred == sorted(occurred)  # chronological / occurrence order
assert {
    (event["before"], event["requested"], event["fresh_read"]) for event in events
} == {
    ("20", "64", "64"),
    ("64", "20", "20"),
}
assert all(
    event["write_readback"] == event["fresh_read"] == event["requested"]
    for event in events
)

summary_mutations = report["mutations"]
assert [mutation["mutation_id"] for mutation in summary_mutations] == ids
assert [mutation["occurred_at"] for mutation in summary_mutations] == occurred
assert [mutation["job"] for mutation in summary_mutations] == [
    event["job"] for event in events
]
assert [mutation["state"] for mutation in summary_mutations] == ["verified", "verified"]
assert all(mutation["routed_channel"] == 1 for mutation in summary_mutations)
assert [mutation["definition_fingerprint"] for mutation in summary_mutations] == [
    event["definition_fingerprint"] for event in events
]

print(
    f"plan {report['plan_fingerprint'][:12]}…: the four definition fingerprints, the "
    f"four BDD hashes, the committed records' hashes and the emitted event order all tie"
)
print(
    "PASS: word 14 == each job's request (20/64/64/20); word 8 held at 10 and word "
    "27 at 1; from the committed records: two verified mutations, distinct, in "
    "occurrence order, each before its point record and naming the plan's own "
    "fingerprint; e20-a and e64-b appended no event at all"
)
