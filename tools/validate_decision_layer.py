"""Validate the WP4 schedule and decision layer of the mixer-sensitivity documents.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 7 (the R3/R9
redesign), §8.4, and §9.4 steps 4-5 (the executable-schedule rebuild) require
that the decision layer be rebuilt *only* from the corrected grouped artefacts,
that the emissions extension be a choice between two allowed designs, that every
condition/control/job count be derived from the documents' own rows rather than
preserved as prose, and that the schedule the rows describe be one today's
writers can actually execute.

The two documents it checks — ``reports/mixer-sensitivity-analysis/decision-table.md``
and ``docs/dop3000/sparse-parameter-set.md`` — each carry two machine-readable
tables:

- the **condition rows**, one row per sparse condition plus one row per control
  set, with the columns ``ID · kind · block · job · control_kind ·
  resolution_mm · gates · burst_cycles · emissions_per_profile · sensitivity ·
  conditional · executable · recordings``;
- the **counts table**, ``count · value``, which must equal the counts recomputed
  from those rows.

Everything the gate refuses is a ruling this step owns:

- **R3 — E128 is an ordinary, unconditional sparse point.** No condition row may
  be ``conditional = yes``, and no live text may make E128 conditional (a trigger,
  an "only if", a "conditional eighth condition"). Because E128 is unconditional,
  there is no plateau test: the word *plateau* is refused unless the clause
  explicitly negates it, so no E20-to-E64 displacement can be called one.
- **R9 — the controls are correlated drift diagnostics**, and the schedule names
  them apart: **block-local controls** repeat a job's own anchor at that job's
  run-wide values, and **common-reference checks** are the true reference
  condition in separate reference-only jobs. Text that calls either type
  "independent" is refused unless explicitly negated, and the retired schedule
  name ``within-run reference controls`` survives only inside a clause that
  retires it.
- **§9.2/§9.4 — the schedule must be executable.** ``CampaignDefinition`` carries
  ``burst_length`` and ``emissions_per_profile`` once per campaign, so every row
  of one job must agree on those run-wide values; a common-reference row cannot
  sit inside a non-reference block; the reference condition gets its own jobs,
  one between each pair of scientific jobs; the superseded ``REF-CTRL |
  every-run`` row is refused outright; each scientific job carries its three
  block-local control recordings.
- **§9.3 — D1 is the one scientifically selected, blocked diagnostic.** It must
  differ from the reference sensitivity, equal the operator-approved value read
  from the application's own dialog (``high``, restored without recording), carry
  no executable job, and enter no executable total.
- **§10 — a same-setting repeat is named, not denied.** Each of the three
  one-condition emissions jobs carries a block-local control at the designated
  scientific row's *own* resolution, gates and sensitivity, so E8, E64 and E128 are
  acquired four times inside one run; where the rows derive such a repeat, no live
  text may claim the level is recorded once or that the controls do not replicate a
  condition. The two burst jobs are deliberately not repeats — their controls stay
  at the 1.850 mm / 50-gate anchor while CC1-CC4 move resolution and gate count.
- **Counts.** The declared counts must equal the counts derived from the rows, no
  count may be asserted in prose without agreeing with them, and the two
  documents' rows must be identical, so neither count nor row set can drift while
  the prose stays.
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

# The tool is stdlib-only apart from this one shared vocabulary: the singular-coverage
# claims are the same list the four analysis modules already consume, so importing it
# keeps a single definition of the banned prose instead of a silent second copy.
from udv_echo_process.analysis._native_grid import SINGULAR_REALIZATION_CLAIMS

#: Repository root, from this file's own location (``tools/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The decision layer: the decision table and the design document it gates.
DECISION_TABLE = "reports/mixer-sensitivity-analysis/decision-table.md"
SPARSE_SET = "docs/dop3000/sparse-parameter-set.md"
DOCUMENTS: tuple[str, ...] = (DECISION_TABLE, SPARSE_SET)

#: The live name of the sole-pair quantity (§8.2 R2), spelled exactly.
CANONICAL_TERM = "sole-pair observed-discrepancy screening threshold"

#: The live names of the two control types (§9.2), spelled exactly. They are
#: different things — a block-local control repeats a job's *own* anchor, a
#: common-reference check repeats the true reference condition — and the
#: retired single name (see :data:`RETIRED_CONTROL_NAME_RE`) conflated them.
CANONICAL_BLOCK_LOCAL_TERM = "block-local controls"
CANONICAL_COMMON_REFERENCE_TERM = "common-reference checks"

#: The R1 grouped-realization statement both documents must carry.
DUPLICATED_SETTING_STATEMENT = "one duplicated setting is not replicated axis coverage"

#: The corrected name of the resolution residual (R7).
CORRECTED_RESIDUAL_NAME = "normalized reconstruction-residual variance"

#: The machine-readable condition-row columns, in order and no other.
ROW_COLUMNS: tuple[str, ...] = (
    "ID",
    "kind",
    "block",
    "job",
    "control_kind",
    "resolution_mm",
    "gates",
    "burst_cycles",
    "emissions_per_profile",
    "sensitivity",
    "conditional",
    "executable",
    "recordings",
)

#: The machine-readable counts-table columns, in order and no other.
COUNT_COLUMNS: tuple[str, ...] = ("count", "value")

#: The row kinds: a sparse condition, a block-local control set, or a
#: common-reference check.
CONDITION_KIND = "unique-condition"
BLOCK_LOCAL_KIND = "block-local-control"
COMMON_REFERENCE_KIND = "common-reference"
ROW_KINDS: tuple[str, ...] = (CONDITION_KIND, BLOCK_LOCAL_KIND, COMMON_REFERENCE_KIND)

#: The ``control_kind`` values. ``none`` is the explicit "not a control" value,
#: so a missing control kind can never be read as one of the two real kinds.
NO_CONTROL_KIND = "none"
BLOCK_LOCAL_CONTROL_KIND = "block-local"
COMMON_REFERENCE_CONTROL_KIND = "common-reference"
CONTROL_KINDS: tuple[str, ...] = (
    NO_CONTROL_KIND,
    BLOCK_LOCAL_CONTROL_KIND,
    COMMON_REFERENCE_CONTROL_KIND,
)

#: The two values of the ``conditional`` column. ``yes`` is refused outright.
CONDITIONAL_VALUES: tuple[str, ...] = ("yes", "no")

#: The two values of the ``executable`` column.
EXECUTABLE_YES = "yes"
EXECUTABLE_NO = "no"
EXECUTABLE_VALUES: tuple[str, ...] = (EXECUTABLE_YES, EXECUTABLE_NO)

#: The eight unique conditions of the unconditional-E128 design.
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

#: The one condition whose conditionality this gate rules on by name.
UNCONDITIONAL_ID = "E128"

#: The five scientific jobs of the WP4 execution schedule (§9.2). Each holds one
#: run-wide burst and emissions value and one block's worth of points.
SCIENTIFIC_JOBS: tuple[str, ...] = (
    "burst-4",
    "burst-18",
    "emissions-8",
    "emissions-64",
    "emissions-128",
)
SCIENTIFIC_JOB_RUN_WIDE: dict[str, tuple[str, str]] = {
    "burst-4": ("4", "20"),
    "burst-18": ("18", "20"),
    "emissions-8": ("10", "8"),
    "emissions-64": ("10", "64"),
    "emissions-128": ("10", "128"),
}
CONDITION_JOBS: dict[str, str] = {
    "CC1": "burst-4", "CC3": "burst-4",
    "CC2": "burst-18", "CC4": "burst-18",
    "E8": "emissions-8", "E64": "emissions-64", "E128": "emissions-128",
}
BLOCK_LOCAL_ANCHOR: tuple[str, str] = ("1.850", "50")

#: The block and control-kind marker of a common-reference job.
COMMON_REFERENCE_BLOCK = "common-reference"

#: The job marker of a row that belongs to no executable job (the blocked D1).
BLOCKED_JOB = "none"

#: One common-reference job sits between each pair of scientific jobs, and each
#: carries exactly one recording of the reference condition.
COMMON_REFERENCE_RECORDINGS_PER_JOB = 1

#: Every scientific job repeats its own anchor three times: beginning, middle
#: and end of the run.
BLOCK_LOCAL_CONTROLS_PER_JOB = 3

#: The run-wide fields ``CampaignDefinition`` fixes once per campaign, so every
#: row of one job must agree on them.
RUN_WIDE_FIELDS: tuple[str, ...] = ("burst_cycles", "emissions_per_profile")

#: §10: the scientific settings a designated scientific row and a block-local control
#: must agree on for that control to be an additional realization of the same
#: condition. ``burst_cycles`` and ``emissions_per_profile`` are *not* in the list:
#: they are run-wide, and :func:`_schedule_rules` already refuses a job whose rows
#: disagree on them, so a same-setting repeat is decided by the point settings alone.
REALIZATION_FIELDS: tuple[str, ...] = ("resolution_mm", "gates", "sensitivity")

#: §10: the claims that can contradict a row-derived repeat. The shared
#: :data:`SINGULAR_REALIZATION_CLAIMS` vocabulary is the one the analysis modules
#: already consume; the additions are the control-denial forms the decision documents
#: use. Deliberately narrow — no global ban on the word "replicate", because the
#: corrected prose legitimately says "not independent run-level replication".
REPEATED_REALIZATION_CLAIMS: tuple[re.Pattern[str], ...] = SINGULAR_REALIZATION_CLAIMS + (
    re.compile(r"\bone recording per condition\b", re.IGNORECASE),
    re.compile(r"\bcontrols? do not (?:replicate|repeat)\b", re.IGNORECASE),
    re.compile(r"\bdo not replicate a condition\b", re.IGNORECASE),
    re.compile(r"\bis still one recording\b", re.IGNORECASE),
)

#: The superseded schedule construction: a reference control in every run.
RETIRED_CONTROL_ID = "REF-CTRL"
RETIRED_JOB = "every-run"

#: The one condition that is scientifically selected but blocked, and the exact
#: operator-approved sensitivity value immediately above ``medium`` (§9.3), read
#: from the application's sidebar sensitivity dropdown and restored without
#: recording.
D1_ID = "D1"
D1_SENSITIVITY = "high"
D1_BLOCK = "sensitivity-diagnostic"

#: The reference condition's decoded values, which every common-reference row
#: must carry.
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
    "blocked_conditions",
    "executable_scientific_recordings",
    "block_local_control_recordings",
    "common_reference_recordings",
    "executable_jobs",
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

#: §9.2: the name that conflated the two control types. It survives only in a
#: clause that retires it ("no longer", "not").
RETIRED_CONTROL_NAME_RE = re.compile(r"within-run reference controls?\b", re.IGNORECASE)

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

#: §9.2/§9.4: a count asserted in prose must agree with the rows. The marker
#: keeps the rule on *totals* — "three recordings per job" is a position rule,
#: not a first-pass total — and the two declarations name the two counts a
#: schedule can be read for.
PROSE_TOTAL_MARKER_RE = re.compile(
    r"\bfirst[- ]pass\b|\bin total\b|\baltogether\b|\bunder today's writers?\b|"
    r"\bexecutable jobs?\b",
    re.IGNORECASE,
)
_NUMBER = r"\d+|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
PROSE_JOBS_DECL_RE = re.compile(rf"(?P<n>{_NUMBER})\s+(?:executable\s+)?jobs?\b", re.IGNORECASE)
PROSE_RECORDINGS_DECL_RE = re.compile(
    rf"(?P<n>{_NUMBER})\s+(?:first-pass\s+)?recordings?\b", re.IGNORECASE
)
NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

#: The separator cells of a markdown table.
_SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")


class DecisionLayerError(Exception):
    """A document cannot be read as the decision layer this gate checks."""


@dataclass(frozen=True)
class Row:
    """One machine-readable condition, block-local-control or common-reference row."""

    id: str
    kind: str
    block: str
    job: str
    control_kind: str
    resolution_mm: str
    gates: str
    burst_cycles: str
    emissions_per_profile: str
    sensitivity: str
    conditional: str
    executable: str
    recordings: int

    def run_wide(self) -> tuple[str, ...]:
        """This row's run-wide values, in :data:`RUN_WIDE_FIELDS` order."""
        return tuple(getattr(self, field) for field in RUN_WIDE_FIELDS)


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
    """The schedule rows of ``text``, or a :class:`DecisionLayerError`."""
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
        recordings = cells[ROW_COLUMNS.index("recordings")]
        if not recordings.isdigit():
            raise DecisionLayerError(
                f"{path}:{number}: recordings must be an integer, got {recordings!r}"
            )
        values = dict(zip(ROW_COLUMNS, cells))
        rows.append(
            Row(
                id=values["ID"],
                kind=values["kind"],
                block=values["block"],
                job=values["job"],
                control_kind=values["control_kind"],
                resolution_mm=values["resolution_mm"],
                gates=values["gates"],
                burst_cycles=values["burst_cycles"],
                emissions_per_profile=values["emissions_per_profile"],
                sensitivity=values["sensitivity"],
                conditional=values["conditional"],
                executable=values["executable"],
                recordings=int(recordings),
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

    A blocked row (:data:`EXECUTABLE_NO`) is scientifically selected but belongs
    to no executable job, so it enters ``unique_new_conditions`` and
    ``blocked_conditions`` and *no* recording total; ``executable_jobs`` counts
    the distinct jobs the executable rows need under today's writers; and
    ``recordings_first_pass`` is the sum of the three recording kinds rather
    than a number of its own.
    """
    conditions = [row for row in rows if row.kind == CONDITION_KIND]
    blocked = [row for row in conditions if row.executable != EXECUTABLE_YES]
    executable = [
        row for row in rows if row.executable == EXECUTABLE_YES and row.job != BLOCKED_JOB
    ]
    scientific = [row for row in conditions if row.executable == EXECUTABLE_YES]
    block_local = [row for row in rows if row.control_kind == BLOCK_LOCAL_CONTROL_KIND]
    common_reference = [row for row in rows if row.control_kind == COMMON_REFERENCE_CONTROL_KIND]
    scientific_recordings = sum(row.recordings for row in scientific)
    block_local_recordings = sum(row.recordings for row in block_local)
    common_reference_recordings = sum(row.recordings for row in common_reference)
    return {
        "unique_new_conditions": len(conditions),
        "blocked_conditions": len(blocked),
        "executable_scientific_recordings": scientific_recordings,
        "block_local_control_recordings": block_local_recordings,
        "common_reference_recordings": common_reference_recordings,
        "executable_jobs": len({row.job for row in executable}),
        "recordings_first_pass": scientific_recordings
        + block_local_recordings
        + common_reference_recordings,
    }


def repeated_realizations(rows: tuple[Row, ...]) -> dict[str, tuple[str, ...]]:
    """§10 — designated scientific rows that a block-local control re-acquires at
    identical settings.

    A block-local control repeats its own job's anchor at that job's run-wide values,
    so for a one-condition emissions job the control lands on the designated
    scientific row's own point settings: that level is then acquired once per control
    recording as well as once for the condition. The burst jobs are deliberately not
    repeats — their controls stay at 1.850 mm / 50 gates while CC1-CC4 move resolution
    and gate count — so the comparison is per job and on :data:`REALIZATION_FIELDS`.
    """
    repeated: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if row.kind != CONDITION_KIND:
            continue
        settings = tuple(getattr(row, field) for field in REALIZATION_FIELDS)
        controls = sorted(
            other.id
            for other in rows
            if other.job == row.job
            and other.kind == BLOCK_LOCAL_KIND
            and tuple(getattr(other, field) for field in REALIZATION_FIELDS) == settings
        )
        if controls:
            repeated[row.id] = tuple(controls)
    return repeated


# --------------------------------------------------------------------------- #
# the rule engine
# --------------------------------------------------------------------------- #


def _row(path: str, rule: str, message: str) -> Violation:
    """A row-level violation: no line number, the row itself is the subject."""
    return Violation(path=path, line=0, rule=rule, message=message, excerpt="")


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


def _schedule_rules(rows: tuple[Row, ...], path: str) -> list[Violation]:
    """§9.2/§9.4: the schedule the rows describe must be executable.

    ``CampaignDefinition`` fixes ``burst_length`` and ``emissions_per_profile``
    once per campaign, so a job is a set of rows that agree on both; a
    common-reference check is the true reference condition and therefore lives
    in its own reference-only job, never inside a burst or emissions block; and
    the retired ``REF-CTRL | every-run`` construction is refused by name.
    """
    violations: list[Violation] = []

    for row in rows:
        if row.id == RETIRED_CONTROL_ID or row.job == RETIRED_JOB or row.block == RETIRED_JOB:
            violations.append(
                _row(
                    path,
                    "schedule-retired-ref-ctrl",
                    (
                        f"{row.id}: the {RETIRED_CONTROL_ID} | {RETIRED_JOB} construction is "
                        "retired: a job whose run-wide burst or emissions value is not the "
                        "reference cannot hold reference-condition recordings"
                    ),
                )
            )

    for row in rows:
        is_control = row.kind in (BLOCK_LOCAL_KIND, COMMON_REFERENCE_KIND)
        expects_block_local = row.kind == BLOCK_LOCAL_KIND
        expects_common = row.kind == COMMON_REFERENCE_KIND
        if row.control_kind not in CONTROL_KINDS:
            violations.append(
                _row(
                    path,
                    "schedule-control-kind",
                    (
                        f"{row.id}: control_kind must be one of {CONTROL_KINDS}, "
                        f"got {row.control_kind!r}"
                    ),
                )
            )
        elif (row.control_kind == BLOCK_LOCAL_CONTROL_KIND) != expects_block_local or (
            row.control_kind == COMMON_REFERENCE_CONTROL_KIND
        ) != expects_common:
            violations.append(
                _row(
                    path,
                    "schedule-control-kind",
                    (
                        f"{row.id}: kind {row.kind!r} and control_kind {row.control_kind!r} "
                        "disagree; a control row must carry the kind and the control kind of "
                        "the same control type, and a condition must carry "
                        f"{NO_CONTROL_KIND!r}"
                    ),
                )
            )
        if is_control and row.executable != EXECUTABLE_YES:
            violations.append(
                _row(
                    path,
                    "schedule-control-executable",
                    f"{row.id}: control recordings are executable first-pass recordings",
                )
            )

    jobs: dict[str, list[Row]] = {}
    for row in rows:
        if row.job == BLOCKED_JOB:
            continue
        jobs.setdefault(row.job, []).append(row)
    for job, members in sorted(jobs.items()):
        values = {member.run_wide() for member in members}
        if len(values) > 1:
            violations.append(
                _row(
                    path,
                    "schedule-run-wide-mixed",
                    (
                        f"{job}: {RUN_WIDE_FIELDS} are run-wide, so every row of the job must "
                        "agree on them; the rows carry "
                        + ", ".join(sorted(str(value) for value in values))
                    ),
                )
            )

    scientific_jobs = set(SCIENTIFIC_JOBS)
    for job, expected in SCIENTIFIC_JOB_RUN_WIDE.items():
        for row in jobs.get(job, []):
            if row.run_wide() != expected:
                violations.append(_row(
                    path,
                    "schedule-block-settings",
                    f"{row.id}: {job} requires run-wide values {expected}, got {row.run_wide()}",
                ))

    for row in rows:
        expected_job = CONDITION_JOBS.get(row.id)
        if expected_job is not None and (row.block != expected_job or row.job != expected_job):
            violations.append(_row(
                path,
                "schedule-condition-job",
                f"{row.id}: condition belongs to block/job {expected_job!r}, got {row.block!r}/{row.job!r}",
            ))
        if row.kind == CONDITION_KIND and row.id != D1_ID and row.sensitivity != REFERENCE_PARAMETERS["sensitivity"]:
            violations.append(_row(
                path,
                "schedule-scientific-sensitivity",
                f"{row.id}: every non-D1 scientific condition stays at sensitivity 'medium', got {row.sensitivity!r}",
            ))

    for job in SCIENTIFIC_JOBS:
        recordings = sum(
            row.recordings
            for row in rows
            if row.job == job and row.control_kind == BLOCK_LOCAL_CONTROL_KIND
        )
        if recordings != BLOCK_LOCAL_CONTROLS_PER_JOB:
            violations.append(
                _row(
                    path,
                    "schedule-block-local-count",
                    (
                        f"{job}: every scientific job repeats its own anchor at that job's "
                        f"run-wide values as "
                        f"{BLOCK_LOCAL_CONTROLS_PER_JOB} block-local controls "
                        f"(beginning/middle/end), got {recordings} recording(s)"
                    ),
                )
            )

    for row in rows:
        is_block_local_row = (
            row.kind == BLOCK_LOCAL_KIND or row.control_kind == BLOCK_LOCAL_CONTROL_KIND
        )
        if is_block_local_row and (row.block not in scientific_jobs or row.job != row.block):
            violations.append(
                _row(
                    path,
                    "schedule-block-local-job",
                    (
                        f"{row.id}: a block-local control belongs to one scientific job "
                        f"({list(SCIENTIFIC_JOBS)}) and to that job's block, got block "
                        f"{row.block!r} and job {row.job!r}"
                    ),
                )
            )
        if is_block_local_row and (row.resolution_mm, row.gates) != BLOCK_LOCAL_ANCHOR:
            violations.append(_row(
                path,
                "schedule-block-local-anchor",
                f"{row.id}: block-local controls use the 1.850 mm / 50-gate anchor, got {row.resolution_mm}/{row.gates}",
            ))

    common_jobs = sorted(
        {
            row.job
            for row in rows
            if row.kind == COMMON_REFERENCE_KIND or row.control_kind == COMMON_REFERENCE_CONTROL_KIND
        }
    )
    expected_common_jobs = len(SCIENTIFIC_JOBS) - 1
    if len(common_jobs) != expected_common_jobs:
        violations.append(
            _row(
                path,
                "schedule-common-reference-count",
                (
                    "one common-reference job belongs between each pair of scientific jobs: "
                    f"{expected_common_jobs} expected for {len(SCIENTIFIC_JOBS)} scientific "
                    f"jobs, got {len(common_jobs)}"
                ),
            )
        )
    for job in common_jobs:
        recordings = sum(
            row.recordings
            for row in rows
            if row.job == job and row.kind == COMMON_REFERENCE_KIND
        )
        if recordings != COMMON_REFERENCE_RECORDINGS_PER_JOB:
            violations.append(
                _row(
                    path,
                    "schedule-common-reference-job",
                    (
                        f"{job}: a common-reference job is a between-job check of the true "
                        f"reference condition and carries "
                        f"{COMMON_REFERENCE_RECORDINGS_PER_JOB} recording, got {recordings}"
                    ),
                )
            )
    for row in rows:
        if row.kind != COMMON_REFERENCE_KIND and row.control_kind != COMMON_REFERENCE_CONTROL_KIND:
            continue
        if row.block != COMMON_REFERENCE_BLOCK or row.job in scientific_jobs or row.job == BLOCKED_JOB:
            violations.append(
                _row(
                    path,
                    "schedule-common-reference-block",
                    (
                        f"{row.id}: a common-reference check sits in a reference-only job "
                        f"(block {COMMON_REFERENCE_BLOCK!r}, its own job), not inside the "
                        f"block {row.block!r} / job {row.job!r}"
                    ),
                )
            )
        for field, expected in REFERENCE_PARAMETERS.items():
            if getattr(row, field) != expected:
                violations.append(
                    _row(
                        path,
                        "schedule-common-reference-settings",
                        (
                            f"{row.id}: a common-reference check repeats the reference "
                            f"condition, so {field} must be {expected!r}, got "
                            f"{getattr(row, field)!r}"
                        ),
                    )
                )
    return violations


def _row_rules(rows: tuple[Row, ...], path: str) -> list[Violation]:
    """R3 plus §9.3: the rows may not make a condition conditional, and D1 is blocked."""
    violations: list[Violation] = list(_schedule_rules(rows, path))
    ids = [row.id for row in rows]
    for condition_id in REQUIRED_CONDITION_IDS:
        if condition_id not in ids:
            violations.append(
                _row(
                    path,
                    "r3-missing-condition",
                    f"the unconditional-E128 design requires a condition row for {condition_id}",
                )
            )
    if not any(row.kind == BLOCK_LOCAL_KIND for row in rows):
        violations.append(
            _row(
                path,
                "schedule-missing-control",
                "the WP4 schedule requires at least one block-local-control row",
            )
        )
    if not any(row.kind == COMMON_REFERENCE_KIND for row in rows):
        violations.append(
            _row(
                path,
                "schedule-missing-control",
                "the WP4 schedule requires at least one common-reference row",
            )
        )
    for row in rows:
        if row.kind not in ROW_KINDS:
            violations.append(
                _row(
                    path,
                    "r3-row-kind",
                    f"{row.id}: kind must be one of {ROW_KINDS}, got {row.kind!r}",
                )
            )
        if row.conditional not in CONDITIONAL_VALUES:
            violations.append(
                _row(
                    path,
                    "r3-conditional-value",
                    (
                        f"{row.id}: conditional must be one of {CONDITIONAL_VALUES}, "
                        f"got {row.conditional!r}"
                    ),
                )
            )
        if row.executable not in EXECUTABLE_VALUES:
            violations.append(
                _row(
                    path,
                    "schedule-executable-value",
                    (
                        f"{row.id}: executable must be one of {EXECUTABLE_VALUES}, "
                        f"got {row.executable!r}"
                    ),
                )
            )
        if row.kind == CONDITION_KIND and row.conditional != "no":
            violations.append(
                _row(
                    path,
                    "r3-conditional-condition",
                    (
                        f"{row.id} is conditional ({row.conditional!r}): the design makes "
                        "every sparse condition unconditional"
                    ),
                )
            )
    if UNCONDITIONAL_ID in ids:
        row = next(row for row in rows if row.id == UNCONDITIONAL_ID)
        if row.kind != CONDITION_KIND:
            violations.append(
                _row(
                    path,
                    "r3-e128-ordinary-point",
                    (
                        f"{UNCONDITIONAL_ID} must be an ordinary sparse point "
                        f"({CONDITION_KIND}), got {row.kind!r}"
                    ),
                )
            )

    d1 = next((row for row in rows if row.id == D1_ID), None)
    if d1 is not None:
        if d1.kind != CONDITION_KIND:
            violations.append(
                _row(
                    path,
                    "d1-kind",
                    f"{D1_ID} is a scientifically selected sparse condition, got kind {d1.kind!r}",
                )
            )
        if d1.sensitivity == REFERENCE_PARAMETERS["sensitivity"]:
            violations.append(
                _row(
                    path,
                    "d1-sensitivity-reference",
                    (
                        f"{D1_ID}: the diagnostic must differ from the reference sensitivity "
                        f"{REFERENCE_PARAMETERS['sensitivity']!r}, got {d1.sensitivity!r}"
                    ),
                )
            )
        if d1.sensitivity != D1_SENSITIVITY:
            violations.append(
                _row(
                    path,
                    "d1-sensitivity-unapproved",
                    (
                        f"{D1_ID}: sensitivity must be exactly the operator-approved value "
                        f"{D1_SENSITIVITY!r} read from the application's own dialog, got "
                        f"{d1.sensitivity!r}"
                    ),
                )
            )
        if d1.executable != EXECUTABLE_NO:
            violations.append(
                _row(
                    path,
                    "d1-executable",
                    (
                        f"{D1_ID}: the diagnostic is scientifically selected but blocked while "
                        f"the sensitivity write/read path and the echo/energy recording surface "
                        f"are missing, so executable must be {EXECUTABLE_NO!r}, got "
                        f"{d1.executable!r}; it may enter no executable total"
                    ),
                )
            )
        executable_jobs = {
            row.job for row in rows if row.executable == EXECUTABLE_YES and row.job != BLOCKED_JOB
        }
        if d1.job != BLOCKED_JOB and d1.job in executable_jobs:
            violations.append(
                _row(
                    path,
                    "d1-job",
                    (
                        f"{D1_ID}: belongs to no executable job, got job {d1.job!r} of the "
                        f"executable jobs {sorted(executable_jobs)}"
                    ),
                )
            )
        if d1.block in executable_jobs:
            violations.append(
                _row(
                    path,
                    "d1-job",
                    (
                        f"{D1_ID}: block {d1.block!r} names an executable job; the blocked "
                        f"diagnostic is {D1_BLOCK!r} and belongs to no executable job"
                    ),
                )
            )
        if d1.block != D1_BLOCK:
            violations.append(_row(
                path,
                "d1-block",
                f"{D1_ID}: blocked diagnostic must use block {D1_BLOCK!r}, got {d1.block!r}",
            ))
    return violations


def _repeated_realization_rules(
    rows: tuple[Row, ...], text: str, path: str
) -> list[Violation]:
    """§10: prose may not deny the same-setting repeats the rows themselves derive.

    The rule is row-derived from end to end: when :func:`repeated_realizations` finds
    no block-local control that re-acquires a designated scientific row's settings,
    not one line of the document is read; when it does, a singular-coverage claim is a
    contradiction of the schedule, and each hit is reported once per derived repeat so
    every condition and every control recording behind it is named.

    The patterns are deliberately *not* routed through :func:`_negated`: the
    control-denial form ("the controls do not replicate a condition") is itself a
    negation, so :func:`_negated` would suppress the very claim this rule exists to
    catch. That is why the vocabulary is narrow instead — the corrected prose may say
    "not independent run-level replication" without being refused.
    """
    repeated = repeated_realizations(rows)
    if not repeated:
        return []
    fields = ", ".join(REALIZATION_FIELDS)
    violations: list[Violation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in REPEATED_REALIZATION_CLAIMS:
            match = pattern.search(line)
            if match is None:
                continue
            for condition_id, control_ids in sorted(repeated.items()):
                controls = ", ".join(control_ids)
                violations.append(
                    Violation(
                        path=path,
                        line=number,
                        rule="schedule-repeated-realization-prose",
                        message=(
                            f"{condition_id}: the rows make this condition a repeated "
                            f"realization — the block-local control(s) {controls} re-acquire "
                            f"it at identical {fields} — so {match.group(0)!r} contradicts "
                            "the schedule §10 derives"
                        ),
                        excerpt=line.strip()[:200],
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
                _row(path, "count-missing", f"the counts table must declare {key!r}")
            )
            continue
        if counts[key] != computed[key]:
            violations.append(
                _row(
                    path,
                    "count-drift",
                    f"{key}: the table declares {counts[key]}, the rows derive {computed[key]}",
                )
            )
    for key in counts:
        if key not in COUNT_KEYS:
            violations.append(
                _row(
                    path,
                    "count-unknown",
                    f"the counts table declares an unknown count {key!r}",
                )
            )
    return violations


def _prose_total_rules(
    text: str, computed: dict[str, int], path: str
) -> list[Violation]:
    """§9.2: of the counts a schedule can be read for, prose must agree with the rows."""
    violations: list[Violation] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("|"):
            continue
        if PROSE_TOTAL_MARKER_RE.search(line) is None:
            continue
        for pattern, key, label in (
            (PROSE_JOBS_DECL_RE, "executable_jobs", "executable jobs"),
            (PROSE_RECORDINGS_DECL_RE, "recordings_first_pass", "first-pass recordings"),
        ):
            for found in pattern.finditer(line):
                raw = found.group("n").lower()
                declared = int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw)
                if declared is None or declared == computed[key]:
                    continue
                violations.append(
                    Violation(
                        path=path,
                        line=number,
                        rule="count-prose-total",
                        message=(
                            f"the line declares {found.group(0)!r}; the rows derive "
                            f"{computed[key]} {label}, so the total belongs to the rows"
                        ),
                        excerpt=line.strip()[:200],
                    )
                )
    return violations


def _text_rules(text: str, path: str) -> list[Violation]:
    """The R1/R2/R3/R7/R9 rules that read the prose, not the tables."""
    violations: list[Violation] = []
    lowered = text.lower()

    if CANONICAL_TERM not in lowered:
        violations.append(
            _row(
                path,
                "r2-canonical-name",
                f"the quantity must be named {CANONICAL_TERM!r} in this document",
            )
        )
    for term in (CANONICAL_BLOCK_LOCAL_TERM, CANONICAL_COMMON_REFERENCE_TERM):
        if term not in lowered:
            violations.append(
                _row(
                    path,
                    "r9-control-name",
                    (
                        f"the two control types must be named apart; this document does not "
                        f"name {term!r}"
                    ),
                )
            )
    if DUPLICATED_SETTING_STATEMENT not in lowered:
        violations.append(
            _row(
                path,
                "r1-duplicated-setting",
                f"the document must state that {DUPLICATED_SETTING_STATEMENT!r}",
            )
        )
    if not any(
        ADJACENT_RE.search(line) and CORRELATED_RE.search(line)
        for line in text.splitlines()
    ):
        violations.append(
            _row(
                path,
                "r9-correlated-controls",
                (
                    "the document must state that the adjacent differences of a job's "
                    "block-local controls are correlated"
                ),
            )
        )

    for number, line in enumerate(text.splitlines(), start=1):
        found = RETIRED_CONTROL_NAME_RE.search(line)
        if found is not None and not _negated(line, found.start(), found.end()):
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="schedule-retired-control-name",
                    message=(
                        "the retired name conflated the two control types: a block-local "
                        "control repeats its own job's anchor, and only a common-reference "
                        "job repeats the reference condition"
                    ),
                    excerpt=line.strip()[:200],
                )
            )

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
            match = pattern.search(line)
            if match is None or _negated(line, match.start(), match.end()):
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
            match = pattern.search(line)
            if match is None or _negated(line, match.start(), match.end()):
                continue
            violations.append(
                Violation(
                    path=path,
                    line=number,
                    rule="r9-independent-control",
                    message=(
                        f"{name}: the controls are correlated drift diagnostics and their "
                        "adjacent differences are correlated"
                    ),
                    excerpt=line.strip()[:200],
                )
            )
            break

        for name, pattern in STALE_THRESHOLD_PATTERNS:
            match = pattern.search(line)
            if match is None or _negated(line, match.start(), match.end()):
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
    """Every R1/R2/R3/R7/R9 and WP4 schedule violation in one document's text.

    ``check_repository`` reaches the §10 row-derived rule through this per-document
    entry point, so both callers see the same rules.
    """
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
    violations.extend(_repeated_realization_rules(rows, text, path))
    violations.extend(_count_rules(rows, counts, path))
    violations.extend(_prose_total_rules(text, compute_counts(rows), path))
    violations.extend(_text_rules(text, path))
    if path == DECISION_TABLE:
        lowered = text.lower()
        for label, fact in REQUIRED_DECISION_FACTS:
            if fact.lower() not in lowered:
                violations.append(
                    _row(
                        path,
                        "r2-grouped-evidence",
                        f"the decision table must cite the corrected {label} ({fact!r})",
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
                _row(
                    ".",
                    "checker-integrity",
                    f"missing decision-layer document: {relative}",
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
                _row(
                    ".",
                    "decision-rows-consistent",
                    (
                        f"{first} and {second} must carry identical condition rows, so "
                        "neither can drift from the other"
                    ),
                )
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    """Check the two documents; return the exit code (0 is a clean tree)."""
    parser = argparse.ArgumentParser(
        prog="udv-validate-decision-layer",
        description=(
            "Check the WP4 schedule and the R3/R9 decision layer (plan "
            "docs/dop3000/existing-sweep-analysis-plan.md §8.3 item 7, §8.4, §9.4)"
        ),
    )
    parser.add_argument("--root", default=str(REPO), help="repository root to check")
    args = parser.parse_args(argv)

    root = Path(args.root)
    violations = check_repository(root)
    print(f"documents : {', '.join(DOCUMENTS)}")
    print(f"quantity  : {CANONICAL_TERM}")
    print(f"controls  : {CANONICAL_BLOCK_LOCAL_TERM} / {CANONICAL_COMMON_REFERENCE_TERM}")
    print(f"D1        : {D1_ID} at sensitivity {D1_SENSITIVITY!r}, blocked")
    if not violations:
        print("udv-validate-decision-layer: the WP4 schedule is executable and its counts agree")
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
