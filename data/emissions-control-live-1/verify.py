"""Recheck the portable live emissions-control evidence, without instrument access.

What this re-derives from the committed files alone: the plan's own fingerprint,
the four executed jobs' definition fingerprints, conditions and point lists,
every recording's SHA-256 and size, and every recording's stored operation words
(word 14 emissions/profile, word 8 burst, word 27 bandwidth-definition index) and
decoded configuration.

What it cannot re-derive: the durable mutation records and the compilation
identities. Their inputs are the runtime manifests and logs, which stay local
(they carry absolute machine paths), so ``manifest.json`` is a derived summary and
is checked here against the expectations written into this file and against the
committed plan.

The sitting's accepted properties, each asserted below:

1. ``e20-a`` and ``e64-b`` spent **no write** and appended **no** mutation — an
   equal value is not a transition (``write_spent`` false, empty mutation list);
2. ``e64-a``'s ``20 -> 64`` and ``e20-b``'s ``64 -> 20`` are each one ``verified``
   mutation carrying the writer's own read-back *and* the independent fresh read;
3. the mutation ids are distinct and in occurrence order;
4. every stored file's word 14 equals the emissions **its own job requested**;
5. word 8 (burst) is unchanged at 10 in all four, and every other fixed decoded
   word is identical across the four files — only the requested axis moved;
6. word 27 is carried as raw provenance (``1``, as in every committed B4/B5
   recording) and is never converted to a physical sampling volume.
"""

from __future__ import annotations

import hashlib
import json
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
#: The *hold* is everything the artefact's decoded configuration carries except the
#: requested axis, so the four files must agree on all of it (word 8 burst, word 27
#: sampling_volume_index, PRF, sound speed, gates, resolution, power, sensitivity,
#: TGC, Doppler angle, gate-1 depth, module scale, trigger, wall filter …).

assert report["channel"] == 1
assert report["strict_facts"] == ["emissions_per_profile"]
assert report["analysis_orientation"] == "E64 - E20"
assert report["initial_state"]["emissions_per_profile"] == "20"
assert len(report["jobs"]) == len(expected)

# The committed plan is the portable copy of the one that ran: re-planning it here
# ties the summary's fingerprints to a plan the reader can inspect.
plan = plan_run_file(root / "plan" / "run-plan.json")
assert plan.plan_fingerprint == report["plan_fingerprint"]
assert [job.step for job in plan.jobs] == [1, 2, 3, 4]
assert [job.job for job in plan.jobs] == [name for name, _, _ in expected]
planned = {job.job: job for job in plan.jobs}

held_reference: dict | None = None
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

    # (1) and (2): the write bookkeeping, and the no-write boundaries.
    assert job["write_spent"] is wrote
    assert len(job["parameter_mutations"]) == (1 if wrote else 0)
    if wrote:
        assert job["no_write_note"] is None
        mutation = job["parameter_mutations"][0]
        assert mutation["state"] == "verified"
        assert mutation["requested"] == str(requested)
        assert mutation["write_readback"] == str(requested)
        assert mutation["fresh_read"] == str(requested)
        # the transition left the *other* level behind it
        assert mutation["before"] == str(20 if requested == 64 else 64)
    else:
        # (1) the accepted no-write branch, in the run's own words
        assert f"already states {requested}" in job["no_write_note"]
        assert "no write was spent" in job["no_write_note"]

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
    # The plan's own request for this point, re-derived from the committed plan.
    assert {
        key: str(value)
        for key, value in planned_job.points[0].parameters.model_dump().items()
    } == {key: str(value) for key, value in point["requested"].items()}

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

# (3) the durable history: distinct ids, occurrence order, and the order the jobs ran.
mutations = report["mutations"]
assert len(mutations) == 2
ids = [mutation["mutation_id"] for mutation in mutations]
assert len(set(ids)) == len(ids)  # every actual mutation id is distinct
occurred = [mutation["occurred_at"] for mutation in mutations]
assert occurred == sorted(occurred)  # chronological / occurrence order
assert [mutation["job"] for mutation in mutations] == ["e64-a", "e20-b"]
assert [mutation["state"] for mutation in mutations] == ["verified", "verified"]
assert {(m["before"], m["requested"], m["fresh_read"]) for m in mutations} == {
    ("20", "64", "64"),
    ("64", "20", "20"),
}
assert all(mutation["routed_channel"] == 1 for mutation in mutations)

print(
    f"plan {report['plan_fingerprint'][:12]}…: four definition fingerprints, "
    f"four BDD hashes and the mutation order tie"
)
print(
    "PASS: word 14 == each job's request (20/64/64/20); word 8 held at 10 and word "
    "27 at 1; two verified mutations, distinct and in order; e20-a and e64-b spent "
    "no write and appended no event"
)
