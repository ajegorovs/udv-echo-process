"""Mutation-proof this package's verifier on scratch copies.

A verifier that cannot fail proves nothing. This applies each perturbation to a copy of
the package in a temporary directory and requires ``verify.py`` to fail on it, then
requires the untouched package to pass. Nothing here writes to the committed package.

The perturbations are the ways the evidence would be wrong if the run's own records were
not what they claim: the emitted event order disturbed (re-ordered, dropped, duplicated,
fabricated), the plan's fingerprint moved, a recording's bytes changed, and the derived
summary contradicting the records or the files.

Run from anywhere with the project interpreter:

    uv run --no-sync python data/emissions-control-live-1/mutation_proof.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
WRITING_JOB = "e64-a"  # the first job that really wrote
NO_WRITE_JOB = "e20-a"  # a job that must carry no event at all


def copy_package(workdir: Path) -> Path:
    target = workdir / PACKAGE.name
    shutil.copytree(PACKAGE, target)
    return target


def records(target: Path, job: str) -> Path:
    return target / "records" / f"{job}.jsonl"


def rewrite_records(target: Path, job: str, lines: list[str]) -> None:
    records(target, job).write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )


def read_records(target: Path, job: str) -> list[str]:
    return [
        line
        for line in records(target, job).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def mutate_summary(target: Path, mutate) -> None:
    path = target / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --- the emitted event order, disturbed ------------------------------------------------


def reordered_event(target: Path) -> None:
    """The point record is placed before the mutation that caused it."""
    lines = read_records(target, WRITING_JOB)
    assert len(lines) == 2
    rewrite_records(target, WRITING_JOB, [lines[1], lines[0]])


def dropped_event(target: Path) -> None:
    """The verified transition is deleted; the point record is left behind."""
    lines = read_records(target, WRITING_JOB)
    assert len(lines) == 2
    rewrite_records(target, WRITING_JOB, lines[1:])


def duplicated_event(target: Path) -> None:
    """One real transition is doubled, which would read as two occurrences."""
    lines = read_records(target, WRITING_JOB)
    assert len(lines) == 2
    rewrite_records(target, WRITING_JOB, [lines[0], lines[0], lines[1]])


def fabricated_event(target: Path) -> None:
    """A boundary that spent no write is given a transition it never made."""
    fabricated = read_records(target, WRITING_JOB)[0]
    lines = read_records(target, NO_WRITE_JOB)
    rewrite_records(target, NO_WRITE_JOB, [fabricated, *lines])


def relabelled_event(target: Path) -> None:
    """The transition's own job is edited, so it no longer matches where it sits."""
    lines = read_records(target, WRITING_JOB)
    record = json.loads(lines[0])
    record["job"] = NO_WRITE_JOB
    rewrite_records(target, WRITING_JOB, [json.dumps(record), lines[1]])


# --- the plan, the recordings and the derived summary ----------------------------------


def moved_definition_fingerprint(target: Path) -> None:
    path = target / "plan" / "jobs" / f"{WRITING_JOB}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["fingerprint"] = "0" * 64
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def flipped_recording_byte(target: Path) -> None:
    stored = next(target.glob("*.BDD"))
    data = bytearray(stored.read_bytes())
    data[0x40] ^= 0xFF
    stored.write_bytes(bytes(data))


def summary_word14_disagrees(target: Path) -> None:
    def mutate(doc):
        for job in doc["jobs"]:
            if job["job"] == WRITING_JOB:
                job["points"][0]["word14_emissions_per_profile"] = 20

    mutate_summary(target, mutate)


def summary_order_reversed(target: Path) -> None:
    mutate_summary(target, lambda doc: doc["mutations"].reverse())


def summary_claims_a_write(target: Path) -> None:
    def mutate(doc):
        for job in doc["jobs"]:
            if job["job"] == NO_WRITE_JOB:
                job["write_spent"] = True

    mutate_summary(target, mutate)


def leaked_local_path(target: Path) -> None:
    """A record's path is made machine-local again, with the summary's recorded hash
    kept in step, so only the path detector can be what fails on it."""
    lines = read_records(target, WRITING_JOB)
    record = json.loads(lines[1])
    record["file_path"] = "\\\\fileserver\\share\\" + Path(record["file_path"]).name
    lines[1] = json.dumps(record)
    rewrite_records(target, WRITING_JOB, lines)
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()

    def mutate(doc):
        for job in doc["jobs"]:
            if job["job"] == WRITING_JOB:
                job["records_sha256"] = digest

    mutate_summary(target, mutate)


CASES = [
    ("record path made machine-local again", leaked_local_path),
    ("event order reversed in the records", reordered_event),
    ("verified transition dropped from the records", dropped_event),
    ("transition duplicated in the records", duplicated_event),
    ("transition fabricated for a no-write job", fabricated_event),
    ("transition relabelled to another job", relabelled_event),
    ("plan definition fingerprint moved", moved_definition_fingerprint),
    ("stored recording byte flipped", flipped_recording_byte),
    ("summary word 14 disagrees with the file", summary_word14_disagrees),
    ("summary mutation order reversed", summary_order_reversed),
    ("no-write boundary claimed as a write", summary_claims_a_write),
]


def verify(target: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(target / "verify.py")],
        capture_output=True,
        text=True,
        check=False,
        cwd=PACKAGE.parent,
    )
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return proc.returncode, tail[-1] if tail else ""


def main() -> int:
    caught = 0
    with tempfile.TemporaryDirectory(prefix="emctl-mutation-") as tmp:
        workdir = Path(tmp)
        for index, (label, mutate) in enumerate(CASES):
            target = copy_package(workdir / str(index))
            mutate(target)
            code, last = verify(target)
            verdict = "failed as required" if code != 0 else "STILL PASSED — NOT PROVEN"
            caught += code != 0
            print(f"{verdict:22} | {label}\n{'':22} | {last[:104]}")
        code, last = verify(copy_package(workdir / "pristine"))
    print(f"\npristine package: exit={code} | {last[:104]}")
    if code != 0 or caught != len(CASES):
        print(f"mutation proof FAILED: {caught}/{len(CASES)} perturbations caught")
        return 1
    print(
        f"mutation proof: all {caught}/{len(CASES)} perturbations are caught and the "
        "pristine package still passes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
