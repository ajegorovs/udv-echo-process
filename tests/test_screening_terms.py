"""Focused tests for the R2/R9 terminology checker.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 3 (R2) and §8.4
require a *mechanical* text check: the sole same-settings difference is named the
**sole-pair observed-discrepancy screening threshold** everywhere, the retired
phrases are gone from live text, and beginning/middle/end controls are named
``within-run reference controls`` without calling them or their adjacent
differences independent.

``tools/check_screening_terms.py`` is that check and this file is its focused
test. Two halves:

- the rule engine, on synthetic text — a positive claim is a violation, an
  explicit negation is not, a marked defect-history quotation is exempt only
  through an exact allowlist entry, and a *stale* allowlist entry is itself a
  failure (so an exemption cannot quietly outlive the text it exempts);
- the committed tree — the real ``src/``, ``docs/`` and ``reports/`` text must
  come back clean, which is what makes the rename in the same commit a gate
  rather than a claim.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

#: Repository root, from this file's own location (``tests/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The checker under test.
TOOL_PATH = REPO / "tools" / "check_screening_terms.py"


def _load_tool():
    """Import the checker from ``tools/`` (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("check_screening_terms", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    assert TOOL_PATH.is_file(), f"the checker is missing: {TOOL_PATH}"
    return _load_tool()


@pytest.fixture()
def no_allowlist(tool):
    return ()


def rules_of(violations) -> set[str]:
    return {violation.rule for violation in violations}


def _lines(violations):
    """Only the line rules: the file-scope name rules are reported at line 0."""
    return [violation for violation in violations if violation.line]


# --------------------------------------------------------------------------- #
# the rule engine, on synthetic text
# --------------------------------------------------------------------------- #


def test_the_canonical_name_is_the_term_the_plan_rules(tool):
    assert tool.CANONICAL_TERM == "sole-pair observed-discrepancy screening threshold"
    assert tool.CANONICAL_CONTROL_TERM == "within-run reference controls"


def test_every_retired_phrase_of_the_plan_is_ruled_on(tool):
    """§8.3 item 3's list, verbatim, plus the superseded envelope/bound names."""
    for phrase in (
        "is an upper bound",
        "as an upper bound",
        "inside the bound",
        "repeatability bound",
        "repeatability envelope",
        "observed discrepancy from the sole same-settings pair",
    ):
        assert phrase in tool.RETIRED_PHRASES


def test_a_retired_phrase_is_a_violation(tool, no_allowlist):
    text = "The difference is an upper bound on same-setting repeatability.\n"
    violations = tool.scan_text(text, "src/udv_echo_process/analysis/axis.py", allowlist=no_allowlist)
    assert "r2-retired-phrase" in rules_of(violations)
    assert violations[0].line == 1


def test_every_retired_phrase_is_caught_one_by_one(tool, no_allowlist):
    for phrase in (
        "is an upper bound",
        "as an upper bound",
        "inside the bound",
        "repeatability bound",
        "repeatability envelope",
        "observed discrepancy from the sole same-settings pair",
    ):
        text = f"Line zero.\nThe quantity {phrase} for the pair.\n"
        violations = tool.scan_text(text, "reports/x/README.md", allowlist=no_allowlist)
        assert "r2-retired-phrase" in rules_of(violations), phrase


@pytest.mark.parametrize(
    "text",
    (
        "An effect smaller than this bound is not distinguishable from repeat-plus-drift.\n",
        "Below the threshold cannot be distinguished from drift.\n",
        "Inside the threshold means indistinguishable.\n",
    ),
)
def test_indistinguishability_claims_from_one_pair_are_violations(tool, no_allowlist, text):
    violations = tool.scan_text(
        text,
        "src/udv_echo_process/analysis/_native_grid.py",
        allowlist=no_allowlist,
    )
    assert "r2-indistinguishability-claim" in rules_of(violations)


@pytest.mark.parametrize(
    "text",
    (
        "The temporal floor is taken from the same-settings pair.\n",
        "The same-settings repeat floor is 0.3 Hz.\n",
        "A smaller bandwidth loss is not separable from repeat-plus-drift.\n",
    ),
)
def test_temporal_floor_inferences_from_one_pair_are_violations(tool, no_allowlist, text):
    violations = tool.scan_text(
        text,
        "src/udv_echo_process/analysis/burst_ladder.py",
        allowlist=no_allowlist,
    )
    assert "r2-temporal-floor-claim" in rules_of(violations)


def test_an_explicit_negation_is_not_a_violation(tool, no_allowlist):
    """A statement that the quantity is *not* a bound must survive."""
    for text in (
        "It is the sole-pair observed-discrepancy screening threshold, not a bound on either.\n",
        (
            "so it does not bound repeatability or drift (an explicit negation, not a positive "
            "bound claim).\n"
        ),
        "Neither outcome proves an axis effect or bounds possible drift.\n",
        "without interpreting either outcome as proof of an axis effect or a bound on drift.\n",
        "The two profiles are not independent replicates.\n",
    ):
        violations = tool.scan_text(text, "docs/dop3000/existing-sweep-analysis-plan.md", allowlist=no_allowlist)
        assert _lines(violations) == [], (text, violations)


def test_a_bare_negative_sentence_does_not_excuse_a_claim(tool, no_allowlist):
    """``no``/``nothing`` in the same sentence is not a negation of the claim itself."""
    text = "No measured level differs from any other by more than the envelope.\n"
    violations = tool.scan_text(text, "reports/mixer-sensitivity-analysis/README.md", allowlist=no_allowlist)
    assert violations, text


def test_an_allowlisted_defect_quotation_is_exempt(tool):
    path = "docs/dop3000/existing-sweep-analysis-plan.md"
    entry = tool.AllowlistEntry(path=path, snippet="marked defect-history quotation")
    text = (
        "| R2 | the sole same-settings difference was called an upper bound | the marked "
        "defect-history quotation is preserved here (retired); the live name is the "
        "sole-pair observed-discrepancy screening threshold |\n"
        "The written decision table still calls it the repeatability envelope.\n"
    )
    violations = tool.scan_text(text, path, allowlist=(entry,))
    assert {violation.line for violation in _lines(violations)} == {2}
    # ... and without the entry the same text is a violation.
    assert {violation.line for violation in _lines(tool.scan_text(text, path, allowlist=()))} == {1, 2}


def test_an_allowlist_entry_exempts_only_its_own_line(tool):
    path = "docs/dop3000/sparse-parameter-set.md"
    entry = tool.AllowlistEntry(path=path, snippet="historical commit subject")
    text = (
        "4. `feat(analysis): quantify the reference-repeat bound` — historical commit subject.\n"
        "The committed repeatability bound is 19.17 mm/s.\n"
    )
    violations = tool.scan_text(text, path, allowlist=(entry,))
    assert violations, "the second line is not exempt"
    assert all("historical commit subject" not in violation.excerpt for violation in violations)


def test_a_stale_allowlist_entry_fails(tool, tmp_path):
    entry = tool.AllowlistEntry(path="docs/dop3000/plan.md", snippet="marked defect-history quotation")
    (tmp_path / "docs" / "dop3000").mkdir(parents=True)
    (tmp_path / "docs" / "dop3000" / "plan.md").write_text(
        "Nothing here quotes the defect.\n", encoding="utf-8"
    )
    problems = tool.stale_allowlist(tmp_path, allowlist=(entry,))
    assert problems
    assert "marked defect-history quotation" in problems[0]

    (tmp_path / "docs" / "dop3000" / "plan.md").write_text(
        "a marked defect-history quotation (retired)\n", encoding="utf-8"
    )
    assert tool.stale_allowlist(tmp_path, allowlist=(entry,)) == []


def test_the_committed_allowlist_entries_are_all_live(tool):
    assert tool.stale_allowlist(REPO) == []


def test_the_committed_allowlist_is_only_defect_history(tool):
    """An exemption must be a marked quotation, never a live document."""
    assert tool.ALLOWLIST
    for entry in tool.ALLOWLIST:
        assert entry.path.startswith("docs/dop3000/existing-sweep-analysis-plan.md"), entry
        assert entry.snippet.strip(), entry


def test_bare_envelope_names_the_quantity_and_is_a_violation(tool, no_allowlist):
    text = "Every level is compared with the WP1 envelope of 19.3701 mm/s.\n"
    violations = tool.scan_text(
        text, "reports/mixer-sensitivity-analysis/README.md", allowlist=no_allowlist
    )
    assert "r2-bare-envelope" in rules_of(violations)


def test_bare_envelope_outside_the_quantity_units_is_not_banned(tool, no_allowlist):
    """The signal sense of 'envelope' is a different concept and stays legal."""
    text = "The received signal envelope sets the depth/velocity envelope of the window.\n"
    assert tool.scan_text(text, "docs/dop3000/measurements-and-recordings.md", allowlist=no_allowlist) == []
    assert tool.scan_text(text, "src/udv_echo_process/viz.py", allowlist=no_allowlist) == []


def test_the_statistical_quantile_envelope_is_not_banned(tool, no_allowlist):
    """The profile quantile envelope is a different quantity: the ban is not global."""
    for path in (
        "src/udv_echo_process/models/profiles.py",
        "src/udv_echo_process/analysis/profiles.py",
        "src/udv_echo_process/export.py",
    ):
        text = (
            "the fitted quantile envelope bounds the gate per depth\n"
            "an empty envelope returns NaN, so the CSV carries the empty_envelope token\n"
        )
        assert tool.scan_text(text, path, allowlist=no_allowlist) == [], path


def test_the_statistical_envelope_files_must_exist(tool):
    """A file-level exemption may not silently outlive its file."""
    assert tool.STATISTICAL_ENVELOPE_FILES
    for relative in tool.STATISTICAL_ENVELOPE_FILES:
        assert (REPO / relative).is_file(), relative


def test_a_positive_bound_word_around_the_quantity_is_a_violation(tool, no_allowlist):
    for text in (
        "The committed WP1 bound both axes are measured against.\n",
        "Every effect is bounded by the same-settings pair.\n",
        "The repeat bounds repeatability plus uncontrolled drift.\n",
    ):
        violations = tool.scan_text(text, "src/udv_echo_process/analysis/axis.py", allowlist=no_allowlist)
        assert "r2-positive-bound-word" in rules_of(violations), text


def test_an_unrelated_bound_word_is_not_a_violation(tool, no_allowlist):
    """Unrelated uses are reworded in the tree, not banned by the checker."""
    text = "The array index is clamped inside its bounds before the write.\n"
    assert tool.scan_text(text, "src/udv_echo_process/acquire/ui/layout.py", allowlist=no_allowlist) == []


def test_an_above_below_statement_must_carry_the_screening_interpretation(tool, no_allowlist):
    bad = "0 of 141 knots sit above the 19.3701 mm/s threshold.\n"
    violations = tool.scan_text(bad, "reports/x/README.md", allowlist=no_allowlist)
    assert "r2-above-below" in rules_of(violations)

    good = (
        "0 of 141 knots sit above the sole-pair observed-discrepancy screening threshold, a "
        "screening outcome that does not prove an axis effect.\n"
    )
    assert tool.scan_text(good, "reports/x/README.md", allowlist=no_allowlist) == []


def test_a_document_must_name_the_canonical_term(tool, tmp_path):
    """A live unit that carries the quantity must carry its new name."""
    unit = tool.R2_TEXT_UNITS[0]
    plain = "This axis compares every pair with the committed 19.3701 mm/s envelope.\n"
    violations = tool.scan_text(plain, unit, allowlist=())
    assert "r2-canonical-name" in rules_of(violations)

    named = (
        "This axis compares every pair with the sole-pair observed-discrepancy screening "
        "threshold.\n"
    )
    assert tool.scan_text(named, unit, allowlist=()) == []


def test_the_r2_and_r9_name_bearing_units_are_declared_and_exist(tool):
    for relative in tool.R2_TEXT_UNITS + tool.R9_TEXT_UNITS:
        assert (REPO / relative).is_file(), relative


def test_an_independent_control_claim_is_a_violation(tool, no_allowlist):
    path = "docs/dop3000/sparse-parameter-set.md"
    for text in (
        "**Independent reference controls at the beginning, middle and end of each run.**\n",
        "Three independent recordings of the reference condition.\n",
        "Two independent within-run differences instead of one.\n",
        "That gives an independent difference between adjacent controls.\n",
        "The controls are independent observations of the anchor.\n",
    ):
        violations = tool.scan_text(text, path, allowlist=no_allowlist)
        assert "r9-independent-control" in rules_of(violations), text


def test_a_negated_independence_statement_survives(tool, no_allowlist):
    for text in (
        "No gate and no profile is an independent experimental replicate.\n",
        "The two profiles are not independent replicates and the difference is one observation.\n",
        "They are not independent references: the adjacent differences share the middle control.\n",
    ):
        assert tool.scan_text(text, "src/udv_echo_process/analysis/axis.py", allowlist=no_allowlist) == []


def test_the_control_documents_must_name_within_run_reference_controls(tool, no_allowlist):
    unit = tool.R9_TEXT_UNITS[0]
    text = "Three recordings of the reference condition, at the beginning, middle and end of each run.\n"
    violations = tool.scan_text(text, unit, allowlist=no_allowlist)
    assert "r9-canonical-control-name" in rules_of(violations)

    named = (
        "The within-run reference controls sit at the beginning, middle and end of each run: one "
        "minimum within-run drift diagnostic.\n"
    )
    assert _lines(tool.scan_text(named, unit, allowlist=no_allowlist)) == []


# --------------------------------------------------------------------------- #
# the scope of the sweep
# --------------------------------------------------------------------------- #


def test_the_scope_is_the_three_text_roots(tool):
    assert tool.SCOPE_DIRS == ("src", "docs", "reports")
    assert tool.SCOPE_SUFFIXES == (".py", ".md")
    assert tool.EXCLUDED_PREFIXES == ("docs/dop3000/manual-reference/",)


def test_in_scope_selects_only_python_and_markdown_outside_the_vendor_manual(tool):
    assert tool.in_scope("src/udv_echo_process/cli.py")
    assert tool.in_scope("docs/dop3000/existing-sweep-analysis-plan.md")
    assert tool.in_scope("reports/mixer-sensitivity-analysis/README.md")
    assert not tool.in_scope("docs/dop3000/manual-reference/dop3000-manual.md")
    assert not tool.in_scope("reports/mixer-sensitivity-analysis/manifest.csv")
    assert not tool.in_scope("reports/mixer-sensitivity-analysis/qc-summary.json")
    assert not tool.in_scope("tests/test_screening_terms.py")
    assert not tool.in_scope("tools/check_screening_terms.py")


def test_the_committed_scope_sees_the_tree(tool):
    files = [path.as_posix() for path in tool.scope_files(REPO)]
    assert "src/udv_echo_process/analysis/reference_repeat.py" in files
    assert "docs/dop3000/sparse-parameter-set.md" in files
    assert "reports/mixer-sensitivity-analysis/decision-table.md" in files
    assert not [name for name in files if "manual-reference" in name]


# --------------------------------------------------------------------------- #
# the committed tree
# --------------------------------------------------------------------------- #


def test_the_committed_tree_passes_the_check(tool):
    """The rename is the fix: every violation the checker names is reworded here."""
    violations = tool.check_repository(REPO)
    assert violations == [], "\n".join(
        f"{violation.path}:{violation.line}: {violation.rule}: {violation.message}"
        for violation in violations
    )


def test_main_exits_zero_on_the_committed_tree(tool, capsys):
    assert tool.main(["--root", str(REPO)]) == 0
    captured = capsys.readouterr()
    assert tool.CANONICAL_TERM in captured.out


def test_main_exits_non_zero_on_a_violating_tree(tool, tmp_path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "live.md").write_text(
        "The committed repeatability envelope is 19.3701 mm/s.\n", encoding="utf-8"
    )
    assert tool.main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "repeatability envelope" in captured.err
