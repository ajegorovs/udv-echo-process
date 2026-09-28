"""Tests for the cross-sitting comparison core's separation and its §5 purity.

Contract: ``docs/dop3000/sa5-cross-sitting-agreement-prespec.md`` §§5 and 11.10 — the §5
quantities are a function of the two sides' frozen arrays alone, and the §6 repeat context is
attached *beside* them, so a pair whose repeat context is unavailable or unverifiable carries
**identical** ``comparison_state``, ``label_state`` and §5 diagnostics to the same pair with a
selected context.

Pinned here:

- the core's dependency surface is closed — it imports no higher layer of the slice (no
  input/binding, no context/model layer, no orchestrator) and names no repeat-context symbol, so
  it cannot read a repeat group even by accident;
- the §5 records are the core's own, and the same two array sides always give the same §5
  records — computed with no quartet, digest or repeat context in scope at all;
- on the committed quartets, doctoring the published repeat ranges changes the quoted context
  and **nothing** of the comparison (state, label, knots and diagnostics are unchanged); and
- an anchor group doctored to carry ``min``/``max``/``spread`` still cannot publish a numerical
  range through the ``repeat-context-identity-unverifiable`` state (Amendment A1).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_sa5_cross_core as core
from udv_echo_process.analysis import sparse_sa5_cross_models as models
from udv_echo_process.analysis import sparse_sa5_cross_sitting as x
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.analysis.sparse_sa5_npz import MEMBER_DTYPES, EffectArrays

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "sparse-signal"
MEAN, PRIMARY = MetricName.MEAN, SparseView.PRIMARY
E8_CONTRAST = "E8_minus_E20"

#: The core's *closed* dependency surface: stdlib, numpy, pydantic and two leaf data modules.
_CORE_DEPENDENCIES = frozenset(
    {
        "__future__",
        "collections.abc",
        "math",
        "numpy",
        "pydantic",
        "udv_echo_process.analysis.sparse_sa5_effects",
        "udv_echo_process.analysis.sparse_sa5_npz",
        "udv_echo_process.models.base",
    }
)
_HIGHER_LAYERS = (
    "sparse_sa5_cross_input",
    "sparse_sa5_cross_models",
    "sparse_sa5_cross_sitting",
)


@pytest.fixture(scope="module")
def published():
    return x.load_published_quartets(REPORT_DIR)


@pytest.fixture(scope="module")
def comparison(published):
    return x.compare_cross_sitting(*published)


def _imported_modules(path: Path) -> set[str]:
    """Every module name the source imports, at any depth."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return imported


def test_the_core_imports_no_higher_layer_of_the_slice() -> None:
    imported = _imported_modules(Path(core.__file__))
    assert not any(name in _HIGHER_LAYERS for name in imported)
    assert imported == _CORE_DEPENDENCIES


def test_the_core_names_no_repeat_context_symbol() -> None:
    # `dir` reaches the module's whole namespace, so a stray import of the context layer would
    # show up here as surely as an own definition.
    for name in (*dir(core), *core.__all__):
        assert "repeat" not in name.lower(), name
        assert "e20" not in name.lower(), name
        assert "provenance" not in name.lower(), name
        assert "quartet" not in name.lower(), name
    assert not hasattr(core, "RepeatContext") and not hasattr(core, "SideContext")


def _arrays(effect_id, knots, effect, defined, state, participant_count=2):
    n, two, d = len(knots), (participant_count, len(knots)), MEMBER_DTYPES
    return EffectArrays(
        effect_id=effect_id,
        knot_count=n,
        participant_count=participant_count,
        knots_mm=np.ascontiguousarray(knots, dtype=d["knots_mm"]),
        effect=np.ascontiguousarray(effect, dtype=d["effect"]),
        defined=np.ascontiguousarray(defined, dtype=d["defined"]),
        state=np.ascontiguousarray(state, dtype=d["state"]),
        participant_gate_index=np.full(two, -1, dtype=d["participant_gate_index"]),
        participant_depth_mm=np.zeros(two, dtype=d["participant_depth_mm"]),
        participant_offset_mm=np.zeros(two, dtype=d["participant_offset_mm"]),
        participant_value=np.zeros(two, dtype=d["participant_value"]),
        participant_defined=np.zeros(two, dtype=d["participant_defined"]),
        participant_state=np.full(two, 6, dtype=d["participant_state"]),
    )


def test_the_section_5_records_come_from_the_two_array_sides_alone() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = np.ones(3, dtype=np.uint8), np.zeros(3, dtype=np.uint8)
    left = _arrays(
        "mean__primary-comparison__c",
        knots,
        np.asarray([0.0, 2.0, 4.0]),
        defined,
        state,
    )
    right = _arrays(
        "mean__primary-comparison__c",
        knots,
        np.asarray([1.0, 5.0, 9.0]),
        defined,
        state,
    )

    rows, definition = core.knot_comparison(knots, left, right)
    diag = core.comparison_diagnostics(rows, definition, left, right)

    assert isinstance(rows[0], core.KnotComparison) and isinstance(
        diag, core.Diagnostics
    )
    assert definition.tolist() == [True, True, True]
    assert [row.difference for row in rows] == [1.0, 3.0, 5.0]
    # D = [1, 3, 5] over a 4 mm span: L = 4, Dbar = 3.0, RMS = sqrt(11), E2 = 2 E1 + 1.
    assert diag.defined_count == 3 and diag.covered_depth_mm == pytest.approx(4.0)
    assert diag.signed_depth_average == pytest.approx(3.0)
    assert diag.rms_difference == pytest.approx(11.0**0.5)
    assert diag.sign_agreement == pytest.approx(1.0)
    assert diag.shape_correlation == pytest.approx(1.0)
    assert diag.peak_displacement == 0.0 and diag.peaks_coincide is True


def test_the_same_arrays_always_give_the_same_section_5_records() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = np.ones(3, dtype=np.uint8), np.zeros(3, dtype=np.uint8)
    left = _arrays("k", knots, np.asarray([0.0, 2.0, 4.0]), defined, state)
    right = _arrays("k", knots, np.asarray([1.0, 5.0, 9.0]), defined, state)
    first = core.comparison_diagnostics(
        *core.knot_comparison(knots, left, right), left, right
    )
    second = core.comparison_diagnostics(
        *core.knot_comparison(knots, left, right), left, right
    )
    assert first == second


def test_the_core_records_are_the_ones_the_slice_publishes() -> None:
    assert x.Diagnostics is core.Diagnostics
    assert x.KnotComparison is core.KnotComparison
    assert models.Diagnostics is core.Diagnostics
    assert models.KnotComparison is core.KnotComparison


def _doctor_repeats(quartet, mutate):
    """A copy of ``quartet`` whose published repeat groups were passed through ``mutate``."""
    document = dict(quartet.document)
    repeats = [dict(group) for group in document["repeats"]]
    for group in repeats:
        group["members"] = list(group["members"])
        mutate(group)
    document["repeats"] = repeats
    return dataclasses.replace(quartet, document=document)


def _one_context(record, operand: str):
    return {context.operand: context for context in record.context2.repeats}[operand]


def _same_common_reference(group) -> bool:
    members = tuple(str(member["label"]) for member in group["members"])
    return members == ("cr1", "cr2", "cr3", "cr4")


def test_a_doctored_repeat_range_changes_the_context_and_nothing_else(
    published, comparison
) -> None:
    live1, live2 = published

    def mutate(group):
        if _same_common_reference(group):
            group["condition"] = "doctored common-reference condition"
            group["min_value"], group["max_value"], group["spread"] = (
                -12345.0,
                98765.0,
                1.0,
            )

    doctored = x.compare_cross_sitting(live1, _doctor_repeats(live2, mutate))

    assert [r.comparison_state for r in doctored.records] == [
        r.comparison_state for r in comparison.records
    ]
    assert [r.label_state for r in doctored.records] == [
        r.label_state for r in comparison.records
    ]
    assert [r.diagnostics for r in doctored.records] == [
        r.diagnostics for r in comparison.records
    ]
    assert [r.knots for r in doctored.records] == [r.knots for r in comparison.records]
    assert [r.knots_mm for r in doctored.records] == [
        r.knots_mm for r in comparison.records
    ]

    # ... and the context really did change, so the invariance above is not vacuous.
    before = _one_context(comparison.record(PRIMARY, MEAN, E8_CONTRAST), "E20")
    after = _one_context(doctored.record(PRIMARY, MEAN, E8_CONTRAST), "E20")
    assert before.state is after.state is x.RepeatContextState.SELECTED
    assert (
        after.min_value == -12345.0
        and after.max_value == 98765.0
        and after.spread == 1.0
    )
    assert after.group_condition != before.group_condition
    # The corner operands' typed-empty context is likewise unchanged in state.
    corner = comparison.record(PRIMARY, MEAN, "pitch_at_burst_4")
    doctored_corner = doctored.record(PRIMARY, MEAN, "pitch_at_burst_4")
    assert [c.state for c in doctored_corner.context2.repeats] == [
        c.state for c in corner.context2.repeats
    ]


def test_an_anchor_group_cannot_be_bribed_into_a_numerical_range(published) -> None:
    live1, live2 = published

    def mutate(group):
        if any(str(member["label"]).startswith("ctrl-") for member in group["members"]):
            group["min_value"], group["max_value"], group["spread"] = -1.0, 1.0, 2.0

    doctored = x.compare_cross_sitting(live1, _doctor_repeats(live2, mutate))
    context = _one_context(doctored.record(PRIMARY, MEAN, E8_CONTRAST), "e8")
    assert context.state is x.RepeatContextState.UNVERIFIABLE
    assert (context.min_value, context.max_value, context.spread) == (None, None, None)
    assert context.identity_verified is False
