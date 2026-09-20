"""Freeze the review-correction baseline of the mixer-sensitivity report tree.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 1 rules that the
current evidence is frozen *before* any correction lands, so the review can be
re-read as a diff rather than as an opinion. This tool is that freeze and the
gate over it; ``reports/mixer-sensitivity-analysis/review-correction-baseline.json``
is the record it reads.

What the record is. Twenty-four report items:

- the 22 generated artefacts — the WP0 manifest and QC summary, the WP1
  reference-repeat table/provenance/figure, and the resolution, burst, PRF and
  gain/power axis tables, provenance documents and figures — each carrying the
  module that writes it, the CLI command that regenerates it, the revision its own
  provenance document records, and the SHA-256 of the committed bytes;
- the two hand-written documents, ``decision-table.md`` and ``README.md``, which
  nothing regenerates and which are therefore recorded by hash alone;

plus the correction register (R1-R9 of §8.2, each with its status and the
baseline items it maps once it lands) and the focused/full gate commands with the
raw results of the runs that were actually made.

Step 8's rebinding is checked here too. ``--check-final`` requires the two
hand-written documents to carry a *binding list* — a markdown table whose rows are
``| `path` | `sha256` |`` — that names every generated item at the bytes now on
disk, so a rebinding that updates the record but not the documents it describes,
or the documents but not the record, is a failure rather than a half-done pass.

Two modes, both read-only — nothing here writes to the report tree:

``--check-current``
    Verify the baseline against the tree as it stands: every item present with its
    recorded hash, every generated item's generator present and its recorded
    revision still the one its provenance document cites, and every required gate
    command recorded green. Exit 0 when the tree still *is* the frozen baseline,
    and non-zero the moment anything has moved. **This is the mode §8.3 item 1
    requires to exit zero against the committed record.**

``--check-final``
    The rebinding mode step 8 uses. It is ``--check-current`` plus the correction
    bookkeeping: every *changed* item must name a correction id from R1-R9 and a
    replacement hash that equals the bytes now on disk, every recorded correction
    must map at least one changed item, and every correction still pending is
    reported as missing. It returns non-zero while any correction is unlanded —
    which is the honest answer at freeze time, because the mappings for R1-R9 do
    not exist yet. This tool never invents one: a pending correction is reported,
    never assumed, and a changed item with no mapping is a failure, never a pass.
    It also re-checks the two binding lists, so the hand-written documents and the
    record cannot disagree about the tree.

Why hashes and not just presence: six modules write the twenty-two artefacts, the
decision table is bound to the manifest's own hash, and the plan's whole
correction record is read from these bytes. A baseline that only listed names
would let every one of them move silently. Hashes are taken over the worktree
bytes, which ``.gitattributes`` pins to LF for this directory's ``*.csv`` and
``*.json`` — the same pin the axis modules rely on for the manifest hash.

Usage::

    .venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-current
    .venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-final
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Repository root, from this file's own location (``tools/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: This file's repository-relative path — the focused gate's own subject.
TOOL_RELATIVE_PATH = "tools/validate_analysis_review_baseline.py"

#: The report tree the baseline describes, repository-relative POSIX.
REPORT_DIR = "reports/mixer-sensitivity-analysis"

#: The record's own name, and its repository-relative path.
RECORD_NAME = "review-correction-baseline.json"
RECORD_RELATIVE_PATH = f"{REPORT_DIR}/{RECORD_NAME}"

#: Record kind marker, so a wrong JSON cannot be checked by accident.
BASELINE_KIND = "review-correction-baseline"

#: The frozen item set: 22 generated artefacts plus two hand-written documents.
REQUIRED_ITEM_COUNT = 24
GENERATED_ITEM_COUNT = 22
GENERATED_ROLE = "generated-artifact"
HAND_WRITTEN_ROLE = "hand-written"
ROLES = (GENERATED_ROLE, HAND_WRITTEN_ROLE)
HAND_WRITTEN_PATHS = ("decision-table.md", "README.md")

#: The correction ids of plan §8.2. A mapping may only name one of these.
CORRECTION_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9")

#: The hand-written documents that carry a binding list of the generated artifacts.
BINDING_LIST_PATHS = ("decision-table.md", "README.md")

#: Correction statuses: ``recorded`` means every mapped item is rebound.
CORRECTION_STATUSES = ("pending", "recorded")

#: The gate commands the record must carry, spelled exactly as plan §6/§8.6 does.
GATE_COMMANDS = {
    "focused-tests": (
        ".venv/Scripts/python.exe -m pytest -q tests/test_validate_analysis_review_baseline.py"
    ),
    "full-tests": ".venv/Scripts/python.exe -m pytest -q",
    "lint": ".venv/Scripts/ruff.exe check src tests tools",
}

#: Every one of these must be recorded, with its raw result, before this gate passes.
REQUIRED_GATES = ("focused-tests", "full-tests", "lint")

#: ``sha256:`` plus 64 lower-case hex characters — the repository's id form.
SHA256_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: One markdown binding row: ``| `path` | `sha256` | ... |``, hash bare or prefixed.
BINDING_ROW_RE = re.compile(
    r"^\|\s*`(?P<path>[^`]+)`\s*\|\s*`?(?:sha256:)?(?P<hash>[0-9a-f]{64})`?\s*\|"
)

#: A short git revision, as the provenance documents record it.
GENERATOR_REVISION_RE = re.compile(r"^[0-9a-f]{7,40}$")


class BaselineError(Exception):
    """The record does not describe a baseline this gate can check."""


@dataclass(frozen=True)
class BaselineItem:
    """One frozen report artefact or hand-written document."""

    path: str
    role: str
    sha256: str
    generator: str | None
    generator_revision: str | None
    generator_command: str | None
    revision_source: str | None
    correction: str | None
    replacement_sha256: str | None


@dataclass(frozen=True)
class GateRecord:
    """One gate command and the raw result of the run that made it."""

    name: str
    command: str
    exit_code: int
    raw_result: str


@dataclass(frozen=True)
class CorrectionRecord:
    """One §8.2 ruling and the baseline items it maps once it has landed."""

    id: str
    title: str
    status: str
    mapped_items: tuple[str, ...]


@dataclass(frozen=True)
class Baseline:
    """The frozen 24-item report baseline."""

    report_dir: str
    items: tuple[BaselineItem, ...]
    gates: tuple[GateRecord, ...]
    corrections: tuple[CorrectionRecord, ...]
    captured_head: str
    captured_branch: str
    captured_utc: str

    def item(self, path: str) -> BaselineItem:
        for item in self.items:
            if item.path == path:
                return item
        raise BaselineError(f"no baseline item named {path!r}")


def sha256_id(path: Path) -> str:
    """Return the ``sha256:<64 hex>`` id of a file's bytes, in 64 KiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _text(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineError(f"{where} must be a non-empty string")
    return value


def _optional_text(value: object, *, where: str) -> str | None:
    if value is None:
        return None
    return _text(value, where=where)


def _hash_id(value: object, *, where: str) -> str:
    text = _text(value, where=where)
    if not SHA256_ID_RE.fullmatch(text):
        raise BaselineError(f"{where} must be a lower-case 'sha256:<64 hex>' id, got {text!r}")
    return text


def _relative_path(value: object, *, where: str) -> str:
    text = _text(value, where=where)
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or "\\" in text:
        raise BaselineError(f"{where} must be a repository-relative POSIX path, got {text!r}")
    if ".." in Path(text).parts:
        raise BaselineError(f"{where} must not escape the report directory, got {text!r}")
    return text


def _item(raw: object, *, index: int) -> BaselineItem:
    if not isinstance(raw, dict):
        raise BaselineError(f"items[{index}] must be an object")
    where = f"items[{index}]"
    path = _relative_path(raw.get("path"), where=f"{where}.path")
    role = _text(raw.get("role"), where=f"{where}.role")
    if role not in ROLES:
        raise BaselineError(f"{where}.role must be one of {ROLES}, got {role!r}")
    sha256 = _hash_id(raw.get("sha256"), where=f"{where}.sha256")

    correction = _optional_text(raw.get("correction"), where=f"{where}.correction")
    if correction is not None and correction not in CORRECTION_IDS:
        raise BaselineError(
            f"{where}.correction must be one of {CORRECTION_IDS}, got {correction!r}"
        )
    replacement = raw.get("replacement_sha256")
    replacement_sha256 = (
        None if replacement is None else _hash_id(replacement, where=f"{where}.replacement_sha256")
    )

    if role == GENERATED_ROLE:
        generator = _relative_path(raw.get("generator"), where=f"{where}.generator")
        generator_command = _text(raw.get("generator_command"), where=f"{where}.generator_command")
        revision = _text(raw.get("generator_revision"), where=f"{where}.generator_revision")
        if not GENERATOR_REVISION_RE.fullmatch(revision):
            raise BaselineError(f"{where}.generator_revision must be a short git SHA, got {revision!r}")
        revision_source = _relative_path(raw.get("revision_source"), where=f"{where}.revision_source")
        if revision not in generator_command:
            raise BaselineError(
                f"{where}.generator_command must name the recorded revision {revision!r}"
            )
    else:
        for field in (
            "generator",
            "generator_revision",
            "generator_command",
            "revision_source",
        ):
            if raw.get(field) is not None:
                raise BaselineError(f"{where}.{field} must be null for a hand-written document")
        generator = generator_command = revision = revision_source = None

    return BaselineItem(
        path=path,
        role=role,
        sha256=sha256,
        generator=generator,
        generator_revision=revision,
        generator_command=generator_command,
        revision_source=revision_source,
        correction=correction,
        replacement_sha256=replacement_sha256,
    )


def _gate(raw: object, *, index: int) -> GateRecord:
    if not isinstance(raw, dict):
        raise BaselineError(f"gates[{index}] must be an object")
    where = f"gates[{index}]"
    name = _text(raw.get("name"), where=f"{where}.name")
    if name not in GATE_COMMANDS:
        raise BaselineError(f"{where}.name must be one of {tuple(GATE_COMMANDS)}, got {name!r}")
    command = _text(raw.get("command"), where=f"{where}.command")
    exit_code = raw.get("exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise BaselineError(f"{where}.exit_code must be an integer")
    raw_result = _text(raw.get("raw_result"), where=f"{where}.raw_result")
    return GateRecord(name=name, command=command, exit_code=exit_code, raw_result=raw_result)


def _correction(raw: object, *, index: int) -> CorrectionRecord:
    if not isinstance(raw, dict):
        raise BaselineError(f"corrections[{index}] must be an object")
    where = f"corrections[{index}]"
    correction_id = _text(raw.get("id"), where=f"{where}.id")
    if correction_id not in CORRECTION_IDS:
        raise BaselineError(f"{where}.id must be one of {CORRECTION_IDS}, got {correction_id!r}")
    title = _text(raw.get("title"), where=f"{where}.title")
    status = _text(raw.get("status"), where=f"{where}.status")
    if status not in CORRECTION_STATUSES:
        raise BaselineError(f"{where}.status must be one of {CORRECTION_STATUSES}, got {status!r}")
    mapped = raw.get("mapped_items")
    if not isinstance(mapped, list):
        raise BaselineError(f"{where}.mapped_items must be a list")
    mapped_items = tuple(
        _relative_path(entry, where=f"{where}.mapped_items[{position}]")
        for position, entry in enumerate(mapped)
    )
    return CorrectionRecord(
        id=correction_id, title=title, status=status, mapped_items=mapped_items
    )


def parse_baseline(document: object) -> Baseline:
    """Validate the record's schema and return it as a :class:`Baseline`.

    Only the schema lives here: the item count and roles, the id/hash forms, the
    correction ids and the gate names. Whether the record is *true of the tree* —
    and whether its gate results are complete — is what the two check modes
    decide, so a record can never be trusted merely because it parsed.
    """
    if not isinstance(document, dict):
        raise BaselineError("the record must be a JSON object")
    kind = document.get("baseline")
    if kind != BASELINE_KIND:
        raise BaselineError(f"baseline must be {BASELINE_KIND!r}, got {kind!r}")
    report_dir = _relative_path(document.get("report_dir"), where="report_dir")

    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise BaselineError("items must be a list")
    items = tuple(_item(entry, index=index) for index, entry in enumerate(raw_items))
    if len(items) != REQUIRED_ITEM_COUNT:
        raise BaselineError(
            f"the baseline is the {REQUIRED_ITEM_COUNT}-item report baseline, "
            f"got {len(items)} items"
        )
    paths = [item.path for item in items]
    if len(set(paths)) != len(paths):
        raise BaselineError("item paths must be unique")
    generated = [item for item in items if item.role == GENERATED_ROLE]
    if len(generated) != GENERATED_ITEM_COUNT:
        raise BaselineError(
            f"expected {GENERATED_ITEM_COUNT} generated artefacts and "
            f"{REQUIRED_ITEM_COUNT - GENERATED_ITEM_COUNT} hand-written documents, "
            f"got {len(generated)} generated"
        )
    hand_written = tuple(
        item.path for item in items if item.role == HAND_WRITTEN_ROLE
    )
    if hand_written != HAND_WRITTEN_PATHS:
        raise BaselineError(
            f"the hand-written items must be exactly {HAND_WRITTEN_PATHS}, got {hand_written}"
        )
    for item in generated:
        if item.revision_source not in paths:
            raise BaselineError(
                f"{item.path} cites an unrecorded revision source "
                f"{item.revision_source!r}"
            )

    raw_corrections = document.get("corrections")
    if not isinstance(raw_corrections, list):
        raise BaselineError("corrections must be a list")
    corrections = tuple(
        _correction(entry, index=index) for index, entry in enumerate(raw_corrections)
    )
    if tuple(correction.id for correction in corrections) != CORRECTION_IDS:
        raise BaselineError(
            f"the correction register must be exactly {CORRECTION_IDS} in order, got "
            f"{tuple(correction.id for correction in corrections)}"
        )

    raw_gates = document.get("gates")
    if not isinstance(raw_gates, list):
        raise BaselineError("gates must be a list")
    gates = tuple(_gate(entry, index=index) for index, entry in enumerate(raw_gates))
    names = [gate.name for gate in gates]
    if len(set(names)) != len(names):
        raise BaselineError("gate names must be unique")

    captured = document.get("captured")
    if not isinstance(captured, dict):
        raise BaselineError("captured must be an object")
    return Baseline(
        report_dir=report_dir,
        items=items,
        gates=gates,
        corrections=corrections,
        captured_head=_text(captured.get("head"), where="captured.head"),
        captured_branch=_text(captured.get("branch"), where="captured.branch"),
        captured_utc=_text(captured.get("utc"), where="captured.utc"),
    )


def _tree_state(baseline: Baseline, root: Path) -> dict[str, tuple[str, str | None]]:
    """Map each recorded item to ``(state, current hash)``.

    ``state`` is ``missing``, ``changed`` or ``same``; the hash is ``None`` only
    when the file is missing.
    """
    report = root / baseline.report_dir
    state: dict[str, tuple[str, str | None]] = {}
    for item in baseline.items:
        path = report / item.path
        if not path.is_file():
            state[item.path] = ("missing", None)
            continue
        current = sha256_id(path)
        state[item.path] = ("same" if current == item.sha256 else "changed", current)
    return state


def binding_table_hashes(text: str) -> dict[str, str]:
    """Map each ``| `path` | `sha256` |`` row of a markdown binding list to its hash.

    The hash is returned bare (no ``sha256:`` prefix), matching how the hand-written
    documents print it. Rows whose second cell is not a SHA-256 are ignored, so a
    document may carry other tables beside its binding list.
    """
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = BINDING_ROW_RE.match(line.strip())
        if match is not None:
            found[match.group("path")] = match.group("hash")
    return found


def binding_problems(baseline: Baseline, root: Path = REPO) -> list[str]:
    """The hand-written binding lists: complete, current, and free of phantom rows.

    Step 8 rebinds the record *and* the documents that describe the tree. A binding
    list that omits a generated item, or prints a hash the bytes no longer have, is
    the same class of error as a stale replacement hash in the record, so it is
    reported the same way.
    """
    report = root / baseline.report_dir
    generated = {item.path: item for item in baseline.items if item.role == GENERATED_ROLE}
    problems: list[str] = []
    for name in BINDING_LIST_PATHS:
        path = report / name
        if not path.is_file():
            problems.append(f"missing binding list: {name} is not in the report tree")
            continue
        listed = binding_table_hashes(path.read_text(encoding="utf-8"))
        missing = sorted(set(generated) - set(listed))
        if missing:
            problems.append(
                f"incomplete binding list: {name} does not list {', '.join(missing)}"
            )
        for artifact in sorted(set(listed) & set(generated)):
            target = report / artifact
            if not target.is_file():
                problems.append(f"missing artifact: {name} lists {artifact}, which is absent")
                continue
            current = sha256_id(target).removeprefix("sha256:")
            if listed[artifact] != current:
                problems.append(
                    f"stale binding hash: {name} lists {artifact} as {listed[artifact]}, "
                    f"tree {current}"
                )
    return problems


def _provenance_problems(baseline: Baseline, root: Path) -> list[str]:
    """Generator modules and the revisions their provenance documents record."""
    report = root / baseline.report_dir
    problems: list[str] = []
    for item in baseline.items:
        if item.role != GENERATED_ROLE:
            continue
        assert item.generator is not None  # guaranteed by the schema
        assert item.generator_revision is not None
        assert item.revision_source is not None
        if not (root / item.generator).is_file():
            problems.append(f"missing generator: {item.path} names {item.generator}")
        source = report / item.revision_source
        if not source.is_file():
            problems.append(
                f"missing revision source: {item.path} cites {item.revision_source}"
            )
            continue
        try:
            recorded = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(
                f"unreadable revision source: {item.revision_source} ({error.__class__.__name__})"
            )
            continue
        revision = recorded.get("analysis_commit") if isinstance(recorded, dict) else None
        if revision != item.generator_revision:
            problems.append(
                f"stale generator revision: {item.path} records {item.generator_revision}, "
                f"{item.revision_source} records {revision!r}"
            )
    return problems


def _gate_problems(baseline: Baseline) -> list[str]:
    """The recorded gate results: present, canonical, and green."""
    problems: list[str] = []
    recorded = {gate.name: gate for gate in baseline.gates}
    for name in REQUIRED_GATES:
        gate = recorded.get(name)
        if gate is None:
            problems.append(f"missing gate result: {name} is not recorded")
            continue
        if gate.command != GATE_COMMANDS[name]:
            problems.append(
                f"stale gate command: {name} records {gate.command!r}, "
                f"expected {GATE_COMMANDS[name]!r}"
            )
        if gate.exit_code != 0:
            problems.append(f"failed gate: {name} exited {gate.exit_code}")
        if not gate.raw_result.strip():
            problems.append(f"empty gate result: {name} records no raw output")
    return problems


def check_current(baseline: Baseline, root: Path = REPO) -> list[str]:
    """Return every way the tree fails to be the frozen baseline (empty is a pass).

    This is the freeze gate: any changed, missing or added-under-a-new-name
    artefact, any generator whose provenance revision has moved, and any missing
    or non-green gate result is a problem.
    """
    problems: list[str] = []
    state = _tree_state(baseline, root)
    for item in baseline.items:
        status, current = state[item.path]
        if status == "missing":
            problems.append(f"missing artifact: {item.path}")
        elif status == "changed":
            problems.append(
                f"changed artifact: {item.path} baseline {item.sha256} tree {current}"
            )
    problems.extend(_provenance_problems(baseline, root))
    problems.extend(_gate_problems(baseline))
    return problems


def check_final(baseline: Baseline, root: Path = REPO) -> list[str]:
    """Return every unlanded rebinding: changed items without a mapping, and the rest.

    Step 8's mode. On top of ``check_current``'s artifact and gate checks it
    requires, for every item whose bytes have moved, a correction id from
    ``CORRECTION_IDS`` and a replacement hash equal to the bytes now on disk, and
    it reports every correction still pending. Pending corrections are reported as
    missing — never assumed and never filled in here, because a mapping this tool
    invented would be indistinguishable from a measured one.

    It also checks the two hand-written binding lists, so the record and the
    documents it rebinds cannot disagree about which bytes are current.
    """
    problems: list[str] = []
    state = _tree_state(baseline, root)
    for item in baseline.items:
        status, current = state[item.path]
        if status == "missing":
            problems.append(f"missing artifact: {item.path} — no replacement can be rebound")
            continue
        if status == "same":
            if item.replacement_sha256 is not None:
                problems.append(
                    f"stale replacement: {item.path} records a replacement hash but its "
                    f"bytes are still the baseline's {item.sha256}"
                )
            elif item.correction is not None:
                problems.append(
                    f"unused correction mapping: {item.path} names {item.correction} but its "
                    f"bytes are unchanged"
                )
            continue
        if item.correction is None:
            problems.append(
                f"changed artifact without a correction mapping: {item.path} "
                f"baseline {item.sha256} tree {current}"
            )
        elif item.replacement_sha256 is None:
            problems.append(
                f"changed artifact without a replacement hash: {item.path} "
                f"names {item.correction} but records no replacement"
            )
        elif item.replacement_sha256 != current:
            problems.append(
                f"replacement hash does not match the tree: {item.path} records "
                f"{item.replacement_sha256} for {item.correction}, tree {current}"
            )

    by_path = {item.path: item for item in baseline.items}
    for correction in baseline.corrections:
        if correction.status == "pending":
            problems.append(
                f"correction {correction.id} ({correction.title}) is still pending: no "
                f"replacement hash is recorded for it"
            )
            continue
        if not correction.mapped_items:
            problems.append(
                f"correction {correction.id} ({correction.title}) is recorded as landed but "
                f"maps no baseline item"
            )
        for path in correction.mapped_items:
            item = by_path.get(path)
            if item is None:
                problems.append(
                    f"correction {correction.id} maps an unrecorded item: {path}"
                )
                continue
            if item.correction != correction.id:
                problems.append(
                    f"correction {correction.id} maps {path}, which names "
                    f"{item.correction!r} instead"
                )
            elif item.replacement_sha256 is None:
                problems.append(
                    f"correction {correction.id} maps {path}, which records no replacement hash"
                )
            elif item.replacement_sha256 != state[path][1]:
                problems.append(
                    f"correction {correction.id} maps {path}, whose replacement hash does not "
                    f"match the tree"
                )

    problems.extend(_provenance_problems(baseline, root))
    problems.extend(_gate_problems(baseline))
    problems.extend(binding_problems(baseline, root))
    return problems


def _load(path: Path = REPO / RECORD_RELATIVE_PATH) -> Baseline:
    if not path.is_file():
        raise BaselineError(f"the baseline record is missing: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineError(f"the baseline record is not readable JSON: {error}") from None
    return parse_baseline(document)


def main(argv: list[str] | None = None) -> int:
    """Run one of the two check modes; return the exit code (0 is a pass)."""
    parser = argparse.ArgumentParser(
        prog="udv-validate-analysis-review-baseline",
        description=(
            "Check the frozen 24-item mixer-sensitivity report baseline "
            "(plan docs/dop3000/existing-sweep-analysis-plan.md §8.3 item 1)"
        ),
    )
    parser.add_argument(
        "--check-current",
        action="store_true",
        help="verify the baseline against the tree as it stands (the freeze gate)",
    )
    parser.add_argument(
        "--check-final",
        action="store_true",
        help=(
            "verify the rebinding: every changed item needs a correction id and its "
            "replacement hash, and every pending correction is reported"
        ),
    )
    parser.add_argument(
        "--record",
        default=RECORD_RELATIVE_PATH,
        help="baseline record to read (default: the committed one)",
    )
    parser.add_argument(
        "--root",
        default=str(REPO),
        help="repository root the record's paths resolve against",
    )
    args = parser.parse_args(argv)

    if args.check_current == args.check_final:
        parser.error("choose exactly one of --check-current and --check-final")

    try:
        baseline = _load(Path(args.record))
    except BaselineError as error:
        print(f"udv-baseline: {error}", file=sys.stderr)
        return 1

    root = Path(args.root)
    mode = "--check-current" if args.check_current else "--check-final"
    generated = sum(1 for item in baseline.items if item.role == GENERATED_ROLE)
    hand_written = len(baseline.items) - generated
    print(f"record   : {args.record}")
    print(f"mode     : {mode}")
    print(f"captured : {baseline.captured_head} on {baseline.captured_branch} at {baseline.captured_utc}")
    print(f"items    : {len(baseline.items)} ({generated} generated, {hand_written} hand-written)")
    print(f"gates    : {len(baseline.gates)} recorded")

    problems = (
        check_current(baseline, root) if args.check_current else check_final(baseline, root)
    )
    if args.check_final:
        pending = [record.id for record in baseline.corrections if record.status == "pending"]
        landed = [record.id for record in baseline.corrections if record.status == "recorded"]
        print(
            f"corrections: {len(landed)} recorded, {len(pending)} pending"
            + (f" ({', '.join(pending)})" if pending else "")
        )
        if pending:
            print(
                "udv-baseline: a pending correction is reported as a missing mapping, never "
                "assumed; map it to the changed item and its replacement hash when it lands",
                file=sys.stderr,
            )

    for problem in problems:
        print(f"udv-baseline: {problem}", file=sys.stderr)
    if problems:
        print(f"udv-baseline: {len(problems)} problem(s); the tree is not the baseline", file=sys.stderr)
        return 1
    print("udv-baseline: the tree is the frozen baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
