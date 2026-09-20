"""Validate the R3/R9 decision layer of the mixer-sensitivity documents.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 7 (the R3/R9
redesign) and §8.4 require that the decision layer be rebuilt *only* from the
corrected grouped artefacts, that the emissions extension be a choice between two
allowed designs, and that all condition/control/job counts be derived from the
documents' own rows rather than preserved as prose. This tool is that gate.

The two documents it checks — ``reports/mixer-sensitivity-analysis/decision-table.md``
and ``docs/dop3000/sparse-parameter-set.md`` — each carry two machine-readable
tables:

- the **condition rows**, one row per sparse condition plus the reference-control
  row, with the columns ``ID · kind · resolution_mm · gates · burst_cycles ·
  emissions_per_profile · sensitivity · conditional · recordings · job``;
- the **counts table**, ``count · value``, which must equal the counts recomputed
  from those rows.

Everything the gate refuses is a ruling this step owns:

- **R3 — E128 is an ordinary, unconditional sparse point.** No condition row may
  be ``conditional = yes``, and no live text may make E128 conditional (a trigger,
  an "only if", a "conditional eighth condition"). Because E128 is unconditional,
  there is no plateau test: the word *plateau* is refused unless the clause
  explicitly negates it, so no E20-to-E64 displacement can be called one.
- **R9 — the controls are within-run reference controls for the single reference
  condition**, whose adjacent differences are correlated. Text that calls them or
  their differences "independent" is refused unless explicitly negated, and both
  documents must carry the canonical name and a statement that the adjacent
  differences are correlated.
- **Counts.** The declared counts must equal the counts derived from the rows, and
  the two documents' rows must be identical, so neither count nor row set can
  drift while the prose stays.
- **Corrected evidence.** Both documents must name the quantity the sole-pair
  observed-discrepancy screening threshold and the one duplicated setting must be
  stated to be *not* replicated axis coverage; the decision table must cite the
  corrected grouped numbers (6 of the 10 PRF pairs, 0 of the 78 resolution pairs,
  22 of the 78 burst pairs) and the corrected residual name.

Run it directly (exit 0 is a clean tree)::

    .venv/Scripts/python.exe tools/validate_decision_layer.py
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

#: Repository root, from this file's own location (``tools/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The decision layer: the decision table and the design document it gates.
DECISION_TABLE = "reports/mixer-sensitivity-analysis/decision-table.md"
SPARSE_SET = "docs/dop3000/sparse-parameter-set.md"
DOCUMENTS: tuple[str, ...] = (DECISION_TABLE, SPARSE_SET)

#: The live name of the sole-pair quantity (§8.2 R2), spelled exactly.
CANONICAL_TERM = "sole-pair observed-discrepancy screening threshold"

#: The live name of the beginning/middle/end controls (§8.2 R9), spelled exactly.
CANONICAL_CONTROL_TERM = "within-run reference controls"

#: The R1 grouped-realization statement both documents must carry.
DUPLICATED_SETTING_STATEMENT = "one duplicated setting is not replicated axis coverage"

#: The corrected name of the resolution residual (R7).
CORRECTED_RESIDUAL_NAME = "normalized reconstruction-residual variance"

#: The machine-readable condition-row columns, in order and no other.
ROW_COLUMNS: tuple[str, ...] = (
    "ID",
    "kind",
    "resolution_mm",
    "gates",
    "burst_cycles",
    "emissions_per_profile",
    "sensitivity",
    "conditional",
    "recordings",
    "job",
)

#: The machine-readable counts-table columns, in order and no other.
COUNT_COLUMNS: tuple[str, ...] = ("count", "value")

#: The row kinds: a sparse condition, or the reference-control row.
CONDITION_KIND = "unique-condition"
CONTROL_KIND = "reference-control"
ROW_KINDS: tuple[str, ...] = (CONDITION_KIND, CONTROL_KIND)

#: The two values of the ``conditional`` column. ``yes`` is refused outright.
CONDITIONAL_VALUES: tuple[str, ...] = ("yes", "no")

#: The eight unique conditions of the unconditional-E128 design, and the control row.
REQUIRED_CONDITION_IDS: tuple[str, ...] = (
    "CC1",
    "CC2",
    "CC3",
    "CC4",
    "E8",
    "E64",
    "E128",
    "D1",
)
CONTROL_ID = "REF-CTRL"

#: The one condition whose conditionality this gate rules on by name.
UNCONDITIONAL_ID = "E128"

#: The reference condition's decoded values, which the control row must carry.
REFERENCE_PARAMETERS: dict[str, str] = {
    "resolution_mm": "1.850",
    "gates": "50",
    "burst_cycles": "10",
    "emissions_per_profile": "20",
    "sensitivity": "medium",
}

#: The counts both documents declare and this gate recomputes from the rows.
COUNT_KEYS: tuple[str, ...] = (
    "unique_new_conditions",
    "reference_controls_per_run",
    "jobs",
    "recordings_first_pass",
)

#: The corrected grouped numbers the decision table must cite (§8.3 item 7).
REQUIRED_DECISION_FACTS: tuple[tuple[str, str], ...] = (
    ("grouped PRF clearances", "6 of the 10"),
    ("grouped resolution pairs", "0 of the 78"),
    ("grouped burst clearances", "22 of the 78"),
    ("corrected resolution residual name", CORRECTED_RESIDUAL_NAME),
)

#: A negation *of the claim itself*, within the clause that carries the match.
NEGATION_RE = re.compile(
    r"\b(?:not|never|neither|nor|without|cannot|doesn't|does not|do not|isn't|"
    r"are not|no longer|no)\b",
    re.IGNORECASE,
)

#: R3: the forms that name the retired plateau test. Unconditional E128 has none,
#: so they survive only in a clause that explicitly negates them. Bare "plateau"
#: is deliberately *not* caught: "a safe plateau" is a gain/energy statement from
#: the committed provenance, not an emissions-axis inference.
PLATEAU_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bplateau(?:ed|s|ing)\b", re.IGNORECASE),
    re.compile(
        r"\bplateau\b[^.\n]{0,40}\b(?:test|axis|E64|E20|E128|emissions|level|rung)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:test|axis|E64|E20|E128|emissions|level|rung)\b[^.\n]{0,40}\bplateau\b",
        re.IGNORECASE,
    ),
)

#: R3: the forms that make E128 conditional again. ``unconditional`` does not
#: match ``\bconditional\b`` (no word boundary inside the compound).
E128_CONDITIONAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"E128[^.\n]{0,80}\bconditional\b", re.IGNORECASE),
    re.compile(r"\bconditional\b[^.\n]{0,80}E128", re.IGNORECASE),
    re.compile(r"E128[^.\n]{0,80}\b(?:only if|only on|triggered by|acquired only)\b", re.IGNORECASE),
    re.compile(r"\b(?:only if|only on|triggered by|acquired only)\b[^.\n]{0,80}E128", re.IGNORECASE),
    re.compile(r"\bconditional eighth condition\b", re.IGNORECASE),
    re.compile(r"\btrigger for E128\b", re.IGNORECASE),
    re.compile(r"\bE128 trigger\b", re.IGNORECASE),
)

#: R9: the forms that call the controls or their differences independent.
INDEPENDENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an independent reference", re.compile(r"independent references?\b", re.IGNORECASE)),
    (
        "an independent difference",
        re.compile(r"independent (?:within-run )?differences?\b", re.IGNORECASE),
    ),
    ("an independent observation", re.compile(r"independent observations?\b", re.IGNORECASE)),
    (
        "an independent recording",
        re.compile(r"independent recordings?\b", re.IGNORECASE),
    ),
    ("an independent replicate", re.compile(r"independent replicates?\b", re.IGNORECASE)),
)

#: R2: the retired floor/bound semantics around the quantity. Both documents are
#: rebuilt without them, so any live occurrence is refused.
STALE_THRESHOLD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a temporal floor", re.compile(r"\btemporal floor\b", re.IGNORECASE)),
    ("a repeat floor", re.compile(r"\brepeat floor\b", re.IGNORECASE)),
    ("a screening floor", re.compile(r"\bscreening floor\b", re.IGNORECASE)),
    ("a floor", re.compile(r"(?<![A-Za-z_])floor(?![A-Za-z_])", re.IGNORECASE)),
    ("an upper/lower bound", re.compile(r"\b(?:upper|lower) bound\b", re.IGNORECASE)),
    ("a repeatability bound", re.compile(r"\brepeatability bound\b", re.IGNORECASE)),
    ("a repeatability envelope", re.compile(r"\brepeatability envelope\b", re.IGNORECASE)),
    (
        "a bound on repeatability or drift",
        re.compile(r"\bbound(?:s|ed|ing)?\b[^.\n]{0,30}\b(?:repeatability|drift)\b", re.IGNORECASE),
    ),
)

INDISTINGUISHABILITY_RE = re.compile(
    r"\b(?:indistinguishable|unresolvable|unresolved)\b|\bnothing\s+distinguishable\b",
    re.IGNORECASE,
)

#: R9: the two words that must sit on one line to state the correlation.
ADJACENT_RE = re.compile(r"\badjacent\b", re.IGNORECASE)
CORRELATED_RE = re.compile(r"\bcorrelated\b", re.IGNORECASE)

#: The separator cells of a markdown table.
_SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")


class DecisionLayerError(Exception):
    """A document cannot be read as the decision layer this gate checks."""


@dataclass(frozen=True)
class Row:
    """One machine-readable condition row."""

    id: str
    kind: str
    resolution_mm: str
    gates: str
    burst_cycles: str
    emissions_per_profile: str
    sensitivity: str
    conditional: str
    recordings: int
    job: str


@dataclass(frozen=True)
class Violation:
    """One line (or document) that still carries a refused claim or a drift."""

    path: str
    line: int
    rule: str
    message: str
    excerpt: str


# --------------------------------------------------------------------------- #
# markdown-table parsing
# --------------------------------------------------------------------------- #


def _cells(line: str) -> list[str]:
    """The stripped cells of one markdown table line."""
    text = line.strip().removeprefix("|").removesuffix("|")
    return [cell.strip() for cell in text.split("|")]


def _clean(cell: str) -> str:
    """A cell's value without markdown emphasis or code ticks."""
    return cell.replace("**", "").replace("`", "").strip()


def _table_start(lines: list[str], columns: tuple[str, ...]) -> int | None:
    """The index of the header line whose cells are exactly ``columns``, if any."""
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        if tuple(_clean(cell) for cell in _cells(line)) == columns:
            return index
    return None


def _table_body(lines: list[str], start: int) -> list[tuple[int, list[str]]]:
    """``(line number, cells)`` for each data row after the header at ``start``."""
    body: list[tuple[int, list[str]]] = []
    for offset, line in enumerate(lines[start + 1 :], start=start + 2):
        if not line.strip().startswith("|"):
            break
        cells = [_clean(cell) for cell in _cells(line)]
        if all(_SEPARATOR_RE.match(cell) for cell in cells if cell):
            continue
        body.append((offset, cells))
    return body


def parse_rows(text: str, path: str) -> tuple[Row, ...]:
    """The condition rows of ``text``, or a :class:`DecisionLayerError`."""
    lines = text.splitlines()
    start = _table_start(lines, ROW_COLUMNS)
    if start is None:
        raise DecisionLayerError(
            f"{path}: no condition-row table with the columns {ROW_COLUMNS}"
        )
    rows: list[Row] = []
    for number, cells in _table_body(lines, start):
        if len(cells) != len(ROW_COLUMNS):
            raise DecisionLayerError(
                f"{path}:{number}: expected {len(ROW_COLUMNS)} cells, got {len(cells)}"
            )
        recordings = cells[8]
        if not recordings.isdigit():
            raise DecisionLayerError(
                f"{path}:{number}: recordings must be an integer, got {recordings!r}"
            )
        rows.append(
            Row(
                id=cells[0],
                kind=cells[1],
                resolution_mm=cells[2],
                gates=cells[3],
                burst_cycles=cells[4],
                emissions_per_profile=cells[5],
                sensitivity=cells[6],
                conditional=cells[7],
                recordings=int(recordings),
                job=cells[9],
            )
        )
    if not rows:
        raise DecisionLayerError(f"{path}: the condition-row table has no rows")
    return tuple(rows)


def parse_counts(text: str, path: str) -> dict[str, int]:
    """The declared counts of ``text``, or a :class:`DecisionLayerError`."""
    lines = text.splitlines()
    start = _table_start(lines, COUNT_COLUMNS)
    if start is None:
        raise DecisionLayerError(
            f"{path}: no counts table with the columns {COUNT_COLUMNS}"
        )
    counts: dict[str, int] = {}
    for number, cells in _table_body(lines, start):
        if len(cells) != len(COUNT_COLUMNS):
            raise DecisionLayerError(
                f"{path}:{number}: expected {len(COUNT_COLUMNS)} cells, got {len(cells)}"
            )
        key, value = cells
        if not value.lstrip("-").isdigit():
            raise DecisionLayerError(
                f"{path}:{number}: the count {key!r} must be an integer, got {value!r}"
            )
        counts[key] = int(value)
    if not counts:
        raise DecisionLayerError(f"{path}: the counts table has no rows")
    return counts


def compute_counts(rows: tuple[Row, ...]) -> dict[str, int]:
    """The condition/control/job counts derived from the rows themselves.

    ``jobs`` is the number of distinct runs the unique conditions need under
    today's writers (each run holds one run-wide field value); the controls are
    ``reference_controls_per_run`` recordings at the beginning, middle and end of
    every run, so ``recordings_first_pass`` counts every condition once plus the
    controls once per run.
    """
    conditions = [row for row in rows if row.kind == CONDITION_KIND]
    controls = [row for row in rows if row.kind == CONTROL_KIND]
    jobs = sorted({row.job for row in conditions})
    controls_per_run = sum(row.recordings for row in controls)
    return {
        "unique_new_conditions": len(conditions),
        "reference_controls_per_run": controls_per_run,
        "jobs": len(jobs),
        "recordings_first_pass": sum(row.recordings for row in conditions)
        + controls_per_run * len(jobs),
    }


# --------------------------------------------------------------------------- #
# the rule engine
# --------------------------------------------------------------------------- #


def _negated(line: str, start: int, end: int) -> bool:
    """Is the match at ``[start, end)`` inside a clause that negates *this* claim?"""
    window_start = max(
        (line.rfind(separator, 0, start) for separator in (".", ";", ",", ":")), default=-1
    )
    window_end = min(
        (index for index in (line.find(s, end) for s in (".", ";")) if index != -1),
        default=len(line),
    )
    clause = line[window_start + 1 : window_end]
    return NEGATION_RE.search(clause) is not None


def _row_rules(rows: tuple[Row, ...], path: str) -> list[Violation]:
    """R3: the rows may not make any condition, E128 above all, conditional."""
    violations: list[Violation] = []
    ids = [row.id for row in rows]
    for condition_id in REQUIRED_CONDITION_IDS:
        if condition_id not in ids:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="r3-missing-condition",
                    message=f"the unconditional-E128 design requires a condition row for {condition_id}",
                    excerpt="",
                )
            )
    if CONTROL_ID not in ids:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r3-missing-control-row",
                message=f"the design requires a {CONTROL_ID} reference-control row",
                excerpt="",
            )
        )
    for row in rows:
        if row.kind not in ROW_KINDS:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="r3-row-kind",
                    message=f"{row.id}: kind must be one of {ROW_KINDS}, got {row.kind!r}",
                    excerpt="",
                )
            )
        if row.conditional not in CONDITIONAL_VALUES:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="r3-conditional-value",
                    message=(
                        f"{row.id}: conditional must be one of {CONDITIONAL_VALUES}, "
                        f"got {row.conditional!r}"
                    ),
                    excerpt="",
                )
            )
        if row.kind == CONDITION_KIND and row.conditional != "no":
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="r3-conditional-condition",
                    message=(
                        f"{row.id} is conditional ({row.conditional!r}): the design makes "
                        "every sparse condition unconditional"
                    ),
                    excerpt="",
                )
            )
    if UNCONDITIONAL_ID in ids:
        row = next(row for row in rows if row.id == UNCONDITIONAL_ID)
        if row.kind != CONDITION_KIND:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="r3-e128-ordinary-point",
                    message=(
                        f"{UNCONDITIONAL_ID} must be an ordinary sparse point "
                        f"({CONDITION_KIND}), got {row.kind!r}"
                    ),
                    excerpt="",
                )
            )
    control = next((row for row in rows if row.id == CONTROL_ID), None)
    if control is not None:
        for field, expected in REFERENCE_PARAMETERS.items():
            if getattr(control, field) != expected:
                violations.append(
                    Violation(
                        path=path,
                        line=0,
                        rule="r9-control-is-reference",
                        message=(
                            f"{CONTROL_ID}: the controls repeat the reference condition, so "
                            f"{field} must be {expected!r}, got {getattr(control, field)!r}"
                        ),
                        excerpt="",
                    )
                )
    return violations


def _count_rules(
    rows: tuple[Row, ...], counts: dict[str, int], path: str
) -> list[Violation]:
    """The declared counts must equal the counts the rows derive."""
    violations: list[Violation] = []
    computed = compute_counts(rows)
    for key in COUNT_KEYS:
        if key not in counts:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="count-missing",
                    message=f"the counts table must declare {key!r}",
                    excerpt="",
                )
            )
            continue
        if counts[key] != computed[key]:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="count-drift",
                    message=(
                        f"{key}: the table declares {counts[key]}, the rows derive "
                        f"{computed[key]}"
                    ),
                    excerpt="",
                )
            )
    for key in counts:
        if key not in COUNT_KEYS:
            violations.append(
                Violation(
                    path=path,
                    line=0,
                    rule="count-unknown",
                    message=f"the counts table declares an unknown count {key!r}",
                    excerpt="",
                )
            )
    return violations


def _text_rules(text: str, path: str) -> list[Violation]:
    """The R1/R2/R3/R7/R9 rules that read the prose, not the tables."""
    violations: list[Violation] = []
    lowered = text.lower()

    if CANONICAL_TERM not in lowered:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r2-canonical-name",
                message=f"the quantity must be named {CANONICAL_TERM!r} in this document",
                excerpt="",
            )
        )
    if CANONICAL_CONTROL_TERM not in lowered:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r9-canonical-control-name",
                message=(
                    "the beginning/middle/end controls must be named "
                    f"{CANONICAL_CONTROL_TERM!r} in this document"
                ),
                excerpt="",
            )
        )
    if DUPLICATED_SETTING_STATEMENT not in lowered:
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r1-duplicated-setting",
                message=(
                    "the document must state that "
                    f"{DUPLICATED_SETTING_STATEMENT!r}"
                ),
                excerpt="",
            )
        )
    if not any(
        ADJACENT_RE.search(line) and CORRELATED_RE.search(line)
        for line in text.splitlines()
    ):
        violations.append(
            Violation(
                path=path,
                line=0,
                rule="r9-correlated-controls",
                message=(
                    "the document must state that the adjacent within-run reference "
                    "control differences are correlated"
                ),
                excerpt="",
            )
        )

    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in PLATEAU_PATTERNS:
            match = pattern.search(line)
            if match is None or _negated(line, match.start(), match.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r3-plateau-inference",
                    message=(
                        "E128 is unconditional, so there is no plateau test: no E20-to-E64 "
                        "displacement may be called one"
                    ),
                    excerpt=line.strip()[:200],
                )
            )
            break

        for pattern in E128_CONDITIONAL_PATTERNS:
            found = pattern.search(line)
            if found is None or _negated(line, found.start(), found.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r3-conditional-e128",
                    message=(
                        "E128 is an ordinary unconditional sparse point, not a condition "
                        "acquired on a trigger"
                    ),
                    excerpt=line.strip()[:200],
                )
            )
            break

        for name, pattern in INDEPENDENT_PATTERNS:
            found = pattern.search(line)
            if found is None or _negated(line, found.start(), found.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r9-independent-control",
                    message=(
                        f"{name}: the controls are {CANONICAL_CONTROL_TERM} and their "
                        "adjacent differences are correlated"
                    ),
                    excerpt=line.strip()[:200],
                )
            )
            break

        for name, pattern in STALE_THRESHOLD_PATTERNS:
            found = pattern.search(line)
            if found is None or _negated(line, found.start(), found.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r2-stale-threshold-semantics",
                    message=(
                        f"{name}: the quantity is a screening reference, not a floor or a "
                        "bound, and the redesign retains neither"
                    ),
                    excerpt=line.strip()[:200],
                )
            )
            break

        found = INDISTINGUISHABILITY_RE.search(line)
        if found is not None and not _negated(line, found.start(), found.end()):
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r2-indistinguishability-claim",
                    message=(
                        "one sole-pair screening observation cannot establish statistical "
                        "indistinguishability or unresolvability"
                    ),
                    excerpt=line.strip()[:200],
                )
            )

    return violations


def scan_document(text: str, path: str) -> list[Violation]:
    """Every R1/R2/R3/R7/R9 violation in one document's text."""
    violations: list[Violation] = []
    try:
        rows = parse_rows(text, path)
        counts = parse_counts(text, path)
    except DecisionLayerError as error:
        return [
            Violation(
                path=path,
                line=0,
                rule="decision-rows-schema",
                message=str(error),
                excerpt="",
            )
        ]
    violations.extend(_row_rules(rows, path))
    violations.extend(_count_rules(rows, counts, path))
    violations.extend(_text_rules(text, path))
    if path == DECISION_TABLE:
        lowered = text.lower()
        for label, fact in REQUIRED_DECISION_FACTS:
            if fact.lower() not in lowered:
                violations.append(
                    Violation(
                        path=path,
                        line=0,
                        rule="r2-grouped-evidence",
                        message=f"the decision table must cite the corrected {label} ({fact!r})",
                        excerpt="",
                    )
                )
    return violations


# --------------------------------------------------------------------------- #
# the tree
# --------------------------------------------------------------------------- #


def check_repository(root: Path = REPO) -> list[Violation]:
    """Every violation across the two documents, plus their row-set agreement."""
    violations: list[Violation] = []
    row_sets: dict[str, tuple[Row, ...]] = {}
    for relative in DOCUMENTS:
        path = root / relative
        if not path.is_file():
            violations.append(
                Violation(
                    path=".",
                    line=0,
                    rule="checker-integrity",
                    message=f"missing decision-layer document: {relative}",
                    excerpt="",
                )
            )
            continue
        text = path.read_text(encoding="utf-8")
        violations.extend(scan_document(text, relative))
        try:
            row_sets[relative] = parse_rows(text, relative)
        except DecisionLayerError:
            continue

    if len(row_sets) == len(DOCUMENTS):
        first, second = DOCUMENTS
        if row_sets[first] != row_sets[second]:
            violations.append(
                Violation(
                    path=".",
                    line=0,
                    rule="decision-rows-consistent",
                    message=(
                        f"{first} and {second} must carry identical condition rows, so "
                        "neither can drift from the other"
                    ),
                    excerpt="",
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    """Check the two documents; return the exit code (0 is a clean tree)."""
    parser = argparse.ArgumentParser(
        prog="udv-validate-decision-layer",
        description=(
            "Check the R3/R9 decision layer (plan docs/dop3000/existing-sweep-analysis-plan.md "
            "§8.3 item 7, §8.4)"
        ),
    )
    parser.add_argument("--root", default=str(REPO), help="repository root to check")
    args = parser.parse_args(argv)

    root = Path(args.root)
    violations = check_repository(root)
    print(f"documents : {', '.join(DOCUMENTS)}")
    print(f"quantity  : {CANONICAL_TERM}")
    print(f"controls  : {CANONICAL_CONTROL_TERM}")
    if not violations:
        print("udv-validate-decision-layer: the decision layer is unconditional and its counts agree")
        return 0
    for violation in violations:
        where = f"{violation.path}:{violation.line}" if violation.line else violation.path
        print(
            f"udv-validate-decision-layer: {where}: {violation.rule}: {violation.message}",
            file=sys.stderr,
        )
        if violation.excerpt:
            print(f"    {violation.excerpt}", file=sys.stderr)
    print(f"udv-validate-decision-layer: {len(violations)} violation(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
