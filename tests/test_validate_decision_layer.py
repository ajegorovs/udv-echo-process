"""Focused tests for the R3/R9 decision-layer validator.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 7 (R3, R9) and
§8.4 require the decision layer to be rebuilt from the corrected grouped
artefacts, with one of the two allowed emissions designs and counts that agree
with the condition rows. ``tools/validate_decision_layer.py`` is that gate and
this file is its focused test.

Two halves:

- the rule engine, on synthetic documents — E128 may not be conditional, no
  E20-to-E64 displacement may be called a plateau test, the controls may not be
  called independent, a declared count that disagrees with the rows is drift, and
  a missing table is a schema failure;
- the committed tree — ``decision-table.md`` and ``sparse-parameter-set.md`` must
  come back clean, which is what makes the redesign in the same commit a gate
  rather than a claim.
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

#: The canonical condition rows of the unconditional-E128 design.
_ROWS = (
    ("CC1", "unique-condition", "0.617", "145", "4", "20", "medium", "no", "1", "crossing-burst-4"),
    ("CC2", "unique-condition", "0.617", "145", "18", "20", "medium", "no", "1", "crossing-burst-18"),
    ("CC3", "unique-condition", "2.960", "31", "4", "20", "medium", "no", "1", "crossing-burst-4"),
    ("CC4", "unique-condition", "2.960", "31", "18", "20", "medium", "no", "1", "crossing-burst-18"),
    ("E8", "unique-condition", "1.850", "50", "10", "8", "medium", "no", "1", "emissions-8"),
    ("E64", "unique-condition", "1.850", "50", "10", "64", "medium", "no", "1", "emissions-64"),
    ("E128", "unique-condition", "1.850", "50", "10", "128", "medium", "no", "1", "emissions-128"),
    ("D1", "unique-condition", "1.850", "50", "10", "20", "medium", "no", "1", "diagnostic-sensitivity"),
    ("REF-CTRL", "reference-control", "1.850", "50", "10", "20", "medium", "no", "3", "every-run"),
)

_COUNTS = (
    ("unique_new_conditions", "8"),
    ("reference_controls_per_run", "3"),
    ("jobs", "6"),
    ("recordings_first_pass", "26"),
)


def _rows_table(rows=_ROWS) -> str:
    lines = ["| " + " | ".join(tool_columns()) + " |", "|" + "---|" * len(tool_columns())]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def tool_columns():
    from_columns = (
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
    return from_columns


def _counts_table(counts=_COUNTS) -> str:
    lines = ["| count | value |", "|---|---|"]
    for key, value in counts:
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _document(rows=_ROWS, counts=_COUNTS, prose: str = "") -> str:
    body = prose or (
        "The quantity is the sole-pair observed-discrepancy screening threshold.\n"
        "The within-run reference controls sit at the beginning, middle and end of each run; "
        "their adjacent differences are correlated.\n"
        "one duplicated setting is not replicated axis coverage.\n"
    )
    return (
        "# Synthetic decision layer\n\n"
        f"{body}\n"
        f"{_rows_table(rows)}\n\n"
        f"{_counts_table(counts)}\n"
    )


# --------------------------------------------------------------------------- #
# the rule engine, on synthetic documents
# --------------------------------------------------------------------------- #


def test_the_canonical_names_are_the_ones_the_plan_rules(tool):
    assert tool.CANONICAL_TERM == "sole-pair observed-discrepancy screening threshold"
    assert tool.CANONICAL_CONTROL_TERM == "within-run reference controls"
    assert tool.DUPLICATED_SETTING_STATEMENT == "one duplicated setting is not replicated axis coverage"


def test_a_well_formed_document_is_clean(tool):
    text = _document()
    assert tool.scan_document(text, tool.SPARSE_SET) == []


def test_the_rows_are_parsed_with_their_columns(tool):
    rows = tool.parse_rows(_document(), tool.SPARSE_SET)
    assert [row.id for row in rows] == [row[0] for row in _ROWS]
    assert next(row for row in rows if row.id == "REF-CTRL").recordings == 3
    assert next(row for row in rows if row.id == "E128").emissions_per_profile == "128"


def test_the_counts_are_derived_from_the_rows(tool):
    rows = tool.parse_rows(_document(), tool.SPARSE_SET)
    assert tool.compute_counts(rows) == {
        "unique_new_conditions": 8,
        "reference_controls_per_run": 3,
        "jobs": 6,
        "recordings_first_pass": 26,
    }


def test_a_conditional_e128_row_is_a_violation(tool):
    rows = tuple(
        (row[0],) + row[1:7] + ("yes",) + row[8:] if row[0] == "E128" else row
        for row in _ROWS
    )
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "r3-conditional-condition" in rules_of(violations)


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


def test_a_declared_count_that_disagrees_with_the_rows_is_drift(tool):
    counts = tuple(
        (key, "7" if key == "unique_new_conditions" else value) for key, value in _COUNTS
    )
    violations = tool.scan_document(_document(counts=counts), tool.SPARSE_SET)
    assert "count-drift" in rules_of(violations)
    assert any("derive 8" in violation.message for violation in violations)


def test_a_missing_condition_row_is_a_violation(tool):
    rows = tuple(row for row in _ROWS if row[0] != "E128")
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "r3-missing-condition" in rules_of(violations)


def test_a_control_row_that_is_not_the_reference_is_a_violation(tool):
    rows = tuple(
        (row[0],) + row[1:5] + ("64",) + row[6:] if row[0] == "REF-CTRL" else row
        for row in _ROWS
    )
    violations = tool.scan_document(_document(rows=rows), tool.SPARSE_SET)
    assert "r9-control-is-reference" in rules_of(violations)


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


def test_a_missing_table_is_a_schema_failure(tool):
    violations = tool.scan_document("# No tables here\n", tool.SPARSE_SET)
    assert rules_of(violations) == {"decision-rows-schema"}


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


def _canonical_prose() -> str:
    return (
        "The quantity is the sole-pair observed-discrepancy screening threshold.\n"
        "The within-run reference controls sit at the beginning, middle and end of each run; "
        "their adjacent differences are correlated.\n"
        "one duplicated setting is not replicated axis coverage.\n"
    )


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
    rows = tool.parse_rows(
        (REPO / tool.SPARSE_SET).read_text(encoding="utf-8"), tool.SPARSE_SET
    )
    counts = tool.parse_counts(
        (REPO / tool.SPARSE_SET).read_text(encoding="utf-8"), tool.SPARSE_SET
    )
    assert counts == tool.compute_counts(rows)


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
