"""Focused tests for the WP4 decision-layer validator.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §9.4 steps 4-5 (with
§8.3 item 7's R3/R9 rules still standing) require the WP4 schedule to be
executable as written:

- one shared row schema carries ``block``, ``job``, ``control_kind`` and
  ``executable``, so no document can describe a job it cannot run;
- the five scientific jobs (``burst-4``, ``burst-18``, ``emissions-8``,
  ``emissions-64``, ``emissions-128``) each repeat their **own** anchor as
  three block-local controls at that job's run-wide values;
- the true reference condition occurs only in **four separate
  common-reference jobs** placed between the scientific jobs, never inside a
  non-reference block;
- D1 is scientifically selected at the operator-approved sensitivity ``high``
  (read from the application's own dropdown, then restored without recording),
  is **blocked** and belongs to no executable job, so it can enter no
  executable total;
- the retired ``REF-CTRL | every-run`` construction — a reference control in
  every run — is refused outright, and no count may be declared in prose
  without agreeing with the rows.

Two halves, as before:

- the rule engine, on synthetic documents that mutate one field at a time;
- the committed tree — ``decision-table.md`` and ``sparse-parameter-set.md``
  must come back clean, which is what makes the redesign in the same commit a
  gate rather than a claim.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

#: Repository root, from this file's own location (``tests/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The validator under test.
TOOL_PATH = REPO / "tools" / "validate_decision_layer.py"


def _load_tool():
    """Import the validator from ``tools/`` (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("validate_decision_layer", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    assert TOOL_PATH.is_file(), f"the validator is missing: {TOOL_PATH}"
    return _load_tool()


def rules_of(violations) -> set[str]:
    return {violation.rule for violation in violations}


# --------------------------------------------------------------------------- #
# a synthetic document the tests mutate one field at a time
# --------------------------------------------------------------------------- #

#: The WP4 row schema the plan's §9.4 step 5 fixes, in order and no other.
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

#: The reference condition's sensitivity and D1's operator-approved value.
_REFERENCE_SENSITIVITY = "medium"
_D1_SENSITIVITY = "high"

#: The canonical WP4 rows, in execution order: five scientific jobs each with
#: their own block-local controls, four common-reference jobs between them, and
#: the blocked D1 diagnostic that belongs to no executable job.
_ROWS = (
    ("CC1", "unique-condition", "burst-4", "burst-4", "none", "0.617", "145", "4", "20", "medium", "no", "yes", "1"),
    ("CC3", "unique-condition", "burst-4", "burst-4", "none", "2.960", "31", "4", "20", "medium", "no", "yes", "1"),
    ("burst-4-CTRL", "block-local-control", "burst-4", "burst-4", "block-local", "1.850", "50", "4", "20", "medium", "no", "yes", "3"),
    ("CR1", "common-reference", "common-reference", "common-reference-1", "common-reference", "1.850", "50", "10", "20", "medium", "no", "yes", "1"),
    ("CC2", "unique-condition", "burst-18", "burst-18", "none", "0.617", "145", "18", "20", "medium", "no", "yes", "1"),
    ("CC4", "unique-condition", "burst-18", "burst-18", "none", "2.960", "31", "18", "20", "medium", "no", "yes", "1"),
    ("burst-18-CTRL", "block-local-control", "burst-18", "burst-18", "block-local", "1.850", "50", "18", "20", "medium", "no", "yes", "3"),
    ("CR2", "common-reference", "common-reference", "common-reference-2", "common-reference", "1.850", "50", "10", "20", "medium", "no", "yes", "1"),
    ("E8", "unique-condition", "emissions-8", "emissions-8", "none", "1.850", "50", "10", "8", "medium", "no", "yes", "1"),
    ("emissions-8-CTRL", "block-local-control", "emissions-8", "emissions-8", "block-local", "1.850", "50", "10", "8", "medium", "no", "yes", "3"),
    ("CR3", "common-reference", "common-reference", "common-reference-3", "common-reference", "1.850", "50", "10", "20", "medium", "no", "yes", "1"),
    ("E64", "unique-condition", "emissions-64", "emissions-64", "none", "1.850", "50", "10", "64", "medium", "no", "yes", "1"),
    ("emissions-64-CTRL", "block-local-control", "emissions-64", "emissions-64", "block-local", "1.850", "50", "10", "64", "medium", "no", "yes", "3"),
    ("CR4", "common-reference", "common-reference", "common-reference-4", "common-reference", "1.850", "50", "10", "20", "medium", "no", "yes", "1"),
    ("E128", "unique-condition", "emissions-128", "emissions-128", "none", "1.850", "50", "10", "128", "medium", "no", "yes", "1"),
    ("emissions-128-CTRL", "block-local-control", "emissions-128", "emissions-128", "block-local", "1.850", "50", "10", "128", "medium", "no", "yes", "3"),
    ("D1", "unique-condition", "sensitivity-diagnostic", "none", "none", "1.850", "50", "10", "20", "high", "no", "no", "1"),
)

#: The counts the rows above derive (7 + 15 + 4 = 26 first-pass recordings).
_COUNTS = (
    ("unique_new_conditions", "8"),
    ("blocked_conditions", "1"),
    ("executable_scientific_recordings", "7"),
    ("block_local_control_recordings", "15"),
    ("common_reference_recordings", "4"),
    ("executable_jobs", "9"),
    ("recordings_first_pass", "26"),
)

#: The superseded reference-control row: three reference recordings in every run.
_LEGACY_ROW = (
    "REF-CTRL", "reference-control", "every-run", "every-run", "block-local",
    "1.850", "50", "10", "20", "medium", "no", "yes", "3",
)


def _rows_table(rows=_ROWS) -> str:
    lines = ["| " + " | ".join(ROW_COLUMNS) + " |", "|" + "---|" * len(ROW_COLUMNS)]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _counts_table(counts=_COUNTS) -> str:
    lines = ["| count | value |", "|---|---|"]
    for key, value in counts:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _document(rows=_ROWS, counts=_COUNTS, prose: str = "") -> str:
    return (
        "# Synthetic decision layer\n\n"
        f"{prose or _canonical_prose()}\n"
        f"{_rows_table(rows)}\n\n"
        f"{_counts_table(counts)}\n"
    )


def _canonical_prose() -> str:
    return (
        "The quantity is the sole-pair observed-discrepancy screening threshold.\n"
        "Each scientific job repeats its own anchor as block-local controls at the beginning, "
        "middle and end of its run; their adjacent differences are correlated.\n"
        "The four common-reference checks sit in separate reference-only jobs between the "
        "scientific jobs.\n"
        "one duplicated setting is not replicated axis coverage.\n"
    )


def _set(rows, row_id: str, **changes) -> tuple:
    """``rows`` with ``row_id``'s named columns replaced."""
    index = {name: position for position, name in enumerate(ROW_COLUMNS)}
    out = []
    for row in rows:
        if row[0] == row_id:
            cells = list(row)
            for name, value in changes.items():
                cells[index[name]] = value
            row = tuple(cells)
        out.append(row)
    return tuple(out)


def _without(rows, row_id: str) -> tuple:
    return tuple(row for row in rows if row[0] != row_id)


def _with_legacy_row(rows) -> tuple:
    return tuple(rows) + (_LEGACY_ROW,)


# --------------------------------------------------------------------------- #
# the schema and the canonical names
# --------------------------------------------------------------------------- #


def test_the_row_schema_is_the_wp4_schedule_schema(tool):
    assert tool.ROW_COLUMNS == ROW_COLUMNS
    assert tool.ROW_KINDS == ("unique-condition", "block-local-control", "common-reference")
    assert tool.CONTROL_KINDS == ("none", "block-local", "common-reference")
    assert tool.SCIENTIFIC_JOBS == (
        "burst-4",
        "burst-18",
        "emissions-8",
        "emissions-64",
        "emissions-128",
    )
    assert tool.COUNT_KEYS == (
        "unique_new_conditions",
        "blocked_conditions",
        "executable_scientific_recordings",
        "block_local_control_recordings",
        "common_reference_recordings",
        "executable_jobs",
        "recordings_first_pass",
    )


def test_the_canonical_names_are_the_ones_the_plan_rules(tool):
    assert tool.CANONICAL_TERM == "sole-pair observed-discrepancy screening threshold"
    assert tool.DUPLICATED_SETTING_STATEMENT == "one duplicated setting is not replicated axis coverage"
    assert tool.CANONICAL_BLOCK_LOCAL_TERM == "block-local controls"
    assert tool.CANONICAL_COMMON_REFERENCE_TERM == "common-reference checks"


def test_d1_is_the_operator_approved_high_condition(tool):
    assert tool.D1_ID == "D1"
    assert tool.D1_SENSITIVITY == _D1_SENSITIVITY
    assert tool.REFERENCE_PARAMETERS["sensitivity"] == _REFERENCE_SENSITIVITY


def test_a_well_formed_document_is_clean(tool):
    assert tool.scan_document(_document(), tool.SPARSE_SET) == []


def test_the_rows_are_parsed_with_their_columns(tool):
    rows = tool.parse_rows(_document(), tool.SPARSE_SET)
    assert [row.id for row in rows] == [row[0] for row in _ROWS]
    control = next(row for row in rows if row.id == "burst-4-CTRL")
    assert (control.block, control.job, control.control_kind) == ("burst-4", "burst-4", "block-local")
    assert control.recordings == 3
    assert next(row for row in rows if row.id == "D1").sensitivity == _D1_SENSITIVITY
    assert next(row for row in rows if row.id == "E128").emissions_per_profile == "128"


def test_the_counts_are_derived_from_the_rows(tool):
    rows = tool.parse_rows(_document(), tool.SPARSE_SET)
    assert tool.compute_counts(rows) == {
        "unique_new_conditions": 8,
        "blocked_conditions": 1,
        "executable_scientific_recordings": 7,
        "block_local_control_recordings": 15,
        "common_reference_recordings": 4,
        "executable_jobs": 9,
        "recordings_first_pass": 26,
    }


# --------------------------------------------------------------------------- #
# WP4 vertical rules, one at a time
# --------------------------------------------------------------------------- #


def test_d1_at_the_reference_sensitivity_is_refused(tool):
    rows = _set(_ROWS, "D1", sensitivity=_REFERENCE_SENSITIVITY)
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "d1-sensitivity-reference" in rules_of(violations)


def test_d1_must_be_exactly_the_operator_approved_value(tool):
    for value in ("High", "HIGH", "higher", "high-plus", "medium-high", "unknown"):
        rows = _set(_ROWS, "D1", sensitivity=value)
        violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
        assert "d1-sensitivity-unapproved" in rules_of(violations), value


def test_a_common_reference_row_cannot_sit_in_a_non_reference_block(tool):
    rows = _set(_ROWS, "CR1", block="emissions-64")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "schedule-common-reference-block" in rules_of(violations)


def test_a_common_reference_job_must_be_a_reference_only_job(tool):
    rows = _set(_ROWS, "CR2", job="burst-18")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "schedule-common-reference-block" in rules_of(violations)


def test_a_common_reference_row_must_carry_the_reference_condition(tool):
    for field, value in (
        ("burst_cycles", "18"),
        ("emissions_per_profile", "64"),
        ("sensitivity", "high"),
    ):
        rows = _set(_ROWS, "CR3", **{field: value})
        violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
        assert "schedule-common-reference-settings" in rules_of(violations), field


def test_one_job_cannot_mix_its_run_wide_burst_or_emissions(tool):
    for row_id, change in (
        ("CC3", {"burst_cycles": "5"}),
        ("E64", {"emissions_per_profile": "32"}),
        ("burst-4-CTRL", {"burst_cycles": "18"}),
    ):
        rows = _set(_ROWS, row_id, **change)
        violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
        assert "schedule-run-wide-mixed" in rules_of(violations), (row_id, change)


def test_each_scientific_job_has_its_planned_run_wide_values(tool):
    # Mutate the whole job coherently: agreement alone is insufficient.
    changed = _ROWS
    for row_id in ("CC1", "CC3", "burst-4-CTRL"):
        changed = _set(changed, row_id, burst_cycles="18")
    assert "schedule-block-settings" in rules_of(
        tool.scan_document(_document(rows=changed), tool.SPARSE_SET)
    )


def test_a_scientific_condition_must_belong_to_its_planned_block_and_job(tool):
    rows = _set(_ROWS, "CC1", block="emissions-64")
    assert "schedule-condition-job" in rules_of(
        tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    )


def test_a_block_local_control_keeps_the_planned_anchor(tool):
    rows = _set(_ROWS, "burst-4-CTRL", resolution_mm="0.617", gates="145")
    assert "schedule-block-local-anchor" in rules_of(
        tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    )


def test_every_non_d1_scientific_condition_stays_at_medium(tool):
    rows = _set(_ROWS, "CC1", sensitivity="high")
    assert "schedule-scientific-sensitivity" in rules_of(
        tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    )


def test_a_block_local_control_must_belong_to_a_scientific_job(tool):
    rows = _set(_ROWS, "emissions-8-CTRL", block="common-reference", job="common-reference-3")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "schedule-block-local-job" in rules_of(violations)


def test_every_scientific_job_carries_three_block_local_controls(tool):
    rows = _set(_ROWS, "burst-4-CTRL", recordings="1")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "schedule-block-local-count" in rules_of(violations)


def test_one_common_reference_job_sits_between_each_scientific_pair(tool):
    dropped = _without(_ROWS, "CR4")
    violations = tool.scan_document(_document(rows=dropped), tool.SPARSE_SET)
    assert "schedule-common-reference-count" in rules_of(violations)

    doubled = _set(_ROWS, "CR1", recordings="2")
    violations = tool.scan_document(_document(rows=doubled), tool.SPARSE_SET)
    assert "schedule-common-reference-job" in rules_of(violations)


def test_the_retired_ref_ctrl_every_run_row_is_refused(tool):
    violations = tool.scan_document(_document(rows=_with_legacy_row(_ROWS)), tool.SPARSE_SET)
    assert "schedule-retired-ref-ctrl" in rules_of(violations)

    rows = _set(_ROWS, "CR1", job="every-run", block="every-run")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "schedule-retired-ref-ctrl" in rules_of(violations)


def test_the_documents_must_name_both_control_types(tool):
    prose = _canonical_prose().replace("block-local controls", "controls of the block")
    violations = tool.scan_document(_document(prose=prose), tool.SPARSE_SET)
    assert "r9-control-name" in rules_of(violations)

    prose = _canonical_prose().replace("common-reference checks", "between-job checks")
    violations = tool.scan_document(_document(prose=prose), tool.SPARSE_SET)
    assert "r9-control-name" in rules_of(violations)


def test_a_blocked_condition_cannot_enter_the_executable_totals(tool):
    rows = _set(_ROWS, "D1", executable="yes")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "d1-executable" in rules_of(violations)
    # … and the totals themselves refuse it: 7 scientific recordings, not 8.
    assert "count-drift" in rules_of(violations)
    derived = tool.compute_counts(tool.parse_rows(_document(rows=rows), tool.SPARSE_SET))
    assert derived["executable_scientific_recordings"] == 8
    assert derived["blocked_conditions"] == 0


def test_d1_must_belong_to_no_executable_job(tool):
    rows = _set(_ROWS, "D1", job="burst-18")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "d1-job" in rules_of(violations)

    rows = _set(_ROWS, "D1", block="whatever")
    assert "d1-block" in rules_of(tool.scan_document(_document(rows=rows), tool.SPARSE_SET))


def test_a_declared_count_that_disagrees_with_the_rows_is_drift(tool):
    counts = tuple(
        (key, "12" if key == "executable_jobs" else value) for key, value in _COUNTS
    )
    violations = tool.scan_document(_document(counts=counts), tool.SPARSE_SET)
    assert "count-drift" in rules_of(violations)
    assert any("derive 9" in violation.message for violation in violations)


def test_a_prose_only_total_must_match_the_derived_counts(tool):
    prose = "The first pass is 30 recordings across 12 executable jobs.\n" + _canonical_prose()
    violations = tool.scan_document(_document(prose=prose), tool.SPARSE_SET)
    assert "count-prose-total" in rules_of(violations)


def test_a_prose_total_that_the_rows_derive_survives(tool):
    prose = "The first pass is 26 recordings across 9 executable jobs.\n" + _canonical_prose()
    assert tool.scan_document(_document(prose=prose), tool.SPARSE_SET) == []


def test_a_retired_job_total_in_prose_is_refused(tool):
    prose = "Six jobs under today's writers carried three controls each.\n" + _canonical_prose()
    violations = tool.scan_document(_document(prose=prose), tool.SPARSE_SET)
    assert "count-prose-total" in rules_of(violations)


def test_a_missing_condition_row_is_a_violation(tool):
    violations = tool.scan_document(_document(rows=_without(_ROWS, "E128")), tool.SPARSE_SET)
    assert "r3-missing-condition" in rules_of(violations)


def test_a_conditional_e128_row_is_a_violation(tool):
    rows = _set(_ROWS, "E128", conditional="yes")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "r3-conditional-condition" in rules_of(violations)


def test_a_missing_table_is_a_schema_failure(tool):
    violations = tool.scan_document("# No tables here\n", tool.SPARSE_SET)
    assert rules_of(violations) == {"decision-rows-schema"}


# --------------------------------------------------------------------------- #
# the rule engine's prose rules, unchanged by the schedule
# --------------------------------------------------------------------------- #


def test_a_conditional_e128_sentence_is_a_violation(tool):
    for prose in (
        "E128 is acquired only if E64 is levelled.\n",
        "E128 is conditional on the next block.\n",
        "The trigger for E128 is the next design step.\n",
    ):
        violations = tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET)
        assert "r3-conditional-e128" in rules_of(violations), prose


def test_an_unconditional_e128_statement_survives(tool):
    prose = "E128 is an ordinary unconditional sparse point.\n" + _canonical_prose()
    assert tool.scan_document(_document(prose=prose), tool.SPARSE_SET) == []


def test_a_plateau_inference_is_a_violation(tool):
    for prose in (
        "E64 has plateaued, so the axis has levelled off.\n",
        "The E64 plateau test decides the next condition.\n",
    ):
        violations = tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET)
        assert "r3-plateau-inference" in rules_of(violations), prose


def test_a_negated_plateau_statement_survives(tool):
    prose = "no E20-to-E64 displacement may be called a plateau test.\n" + _canonical_prose()
    assert tool.scan_document(_document(prose=prose), tool.SPARSE_SET) == []


def test_an_independent_control_claim_is_a_violation(tool):
    for prose in (
        "Three independent recordings of the reference condition.\n",
        "The controls are independent observations of the anchor.\n",
        "This gives an independent difference between adjacent controls.\n",
    ):
        violations = tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET)
        assert "r9-independent-control" in rules_of(violations), prose


def test_a_negated_independence_statement_survives(tool):
    prose = "The controls are not independent references and their adjacent differences are correlated.\n"
    assert tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET) == []


def test_a_stale_floor_or_bound_semantics_is_a_violation(tool):
    for prose in (
        "The temporal floor is taken from the same-settings pair.\n",
        "The repeat floor is 0.3 Hz.\n",
        "The difference is an upper bound on repeatability.\n",
        "It bounds repeatability plus uncontrolled drift.\n",
    ):
        violations = tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET)
        assert "r2-stale-threshold-semantics" in rules_of(violations), prose


def test_a_below_threshold_indistinguishability_claim_is_a_violation(tool):
    for prose in (
        "The two settings are indistinguishable on this evidence.\n",
        "The 18 versus 20 cycle comparison is unresolvable.\n",
    ):
        violations = tool.scan_document(_document(prose=prose + _canonical_prose()), tool.SPARSE_SET)
        assert "r2-indistinguishability-claim" in rules_of(violations), prose


def test_a_missing_duplicated_setting_statement_is_a_violation(tool):
    prose = _canonical_prose().replace(
        "one duplicated setting is not replicated axis coverage.\n", ""
    )
    violations = tool.scan_document(_document(prose=prose), tool.SPARSE_SET)
    assert "r1-duplicated-setting" in rules_of(violations)


def test_the_decision_table_must_cite_the_corrected_grouped_numbers(tool):
    prose = _canonical_prose() + "The grouped evidence is corrected.\n"
    violations = tool.scan_document(_document(prose=prose), tool.DECISION_TABLE)
    assert "r2-grouped-evidence" in rules_of(violations)


# --------------------------------------------------------------------------- #
# the committed tree
# --------------------------------------------------------------------------- #


def test_the_two_documents_are_the_decision_layer(tool):
    assert tool.DOCUMENTS == (
        "reports/mixer-sensitivity-analysis/decision-table.md",
        "docs/dop3000/sparse-parameter-set.md",
    )


def test_the_committed_tree_passes_the_check(tool):
    """The redesign is the fix: every violation the validator names is ruled on here."""
    violations = tool.check_repository(REPO)
    assert violations == [], "\n".join(
        f"{violation.path}:{violation.line}: {violation.rule}: {violation.message}"
        for violation in violations
    )


def test_the_committed_rows_agree_between_the_documents(tool):
    decision = tool.parse_rows(
        (REPO / tool.DECISION_TABLE).read_text(encoding="utf-8"), tool.DECISION_TABLE
    )
    sparse = tool.parse_rows(
        (REPO / tool.SPARSE_SET).read_text(encoding="utf-8"), tool.SPARSE_SET
    )
    assert decision == sparse


def test_the_committed_counts_agree_with_the_rows(tool):
    text = (REPO / tool.SPARSE_SET).read_text(encoding="utf-8")
    assert tool.parse_counts(text, tool.SPARSE_SET) == tool.compute_counts(
        tool.parse_rows(text, tool.SPARSE_SET)
    )


def test_main_exits_zero_on_the_committed_tree(tool, capsys):
    assert tool.main(["--root", str(REPO)]) == 0
    captured = capsys.readouterr()
    assert tool.CANONICAL_TERM in captured.out


def test_main_exits_non_zero_on_a_violating_tree(tool, tmp_path, capsys):
    (tmp_path / tool.SPARSE_SET).parent.mkdir(parents=True)
    (tmp_path / tool.SPARSE_SET).write_text("# nothing\n", encoding="utf-8")
    assert tool.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "missing decision-layer document" in captured.err
