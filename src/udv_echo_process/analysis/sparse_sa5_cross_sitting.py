"""SA5 cross-sitting descriptive agreement — the between-sitting backend slice.

``docs/dop3000/sa5-cross-sitting-agreement-prespec.md`` adds *only* the between-sitting
comparison to the validated SA5 vocabulary. This module implements it as typed, in-memory
records: it reads the two published within-sitting quartets, verifies each side's v1 digest
chain, and emits **72 typed comparisons** — one per ``(view, metric, contrast-or-interaction)``
— with every prespecified §5 diagnostic, each sitting's own frozen §6 context quoted beside
them, and the two orthogonal typed states. Nothing is published, written, pooled or labelled.

A side whose digest chain, ``ok`` flag or checks do not hold refuses the run; the orientation
is fixed as ``live2 - live1``; pairs match on exact equality of ``(view, metric, contrast)``
*and* of the resolved ``effect_id`` (never parsed); the grid-vs-contrast rule is asserted; and
the comparison domain is first narrowed to the native knots **inside the two sides' support
intersection** (a comparison knot must lie inside both supports, §3), and only then are the §5
diagnostics computed on the common-defined knots (``D``, ``D̄``, ``RMS(D)``, ``A_sign``, the
shape correlation, the per-side numerical maxima and the localized-peak
displacement/coincidence), each defined or explicitly typed-empty. A comparable pair's
``comparison_reason`` names its established basis (``common-basis-established``), never the
absent resolvability rule. No within-sitting value is re-derived: the per-knot profile is read
from the digest-bound NPZ and the scalar context from the digest-bound CSV.
``comparison_state`` and ``label_state`` stay separate axes; ``label_state`` is only ever
``deferred-pending-review`` or absent, never a verdict.

Layering
--------
This module is the **orchestrator** and the slice's public surface; it is the only module that
knows all three layers, and it wires them one way:

* :mod:`sparse_sa5_cross_input` — binds the two quartets (digest chain), fixes the orientation,
  states ``grid`` as a function of the contrast, names the frozen 72 keys and resolves each key
  by exact triple/``effect_id`` matching;
* :mod:`sparse_sa5_cross_core` — the pure §5 kernel over the two sides' arrays (mask ``D``,
  ``D̄``/``RMS(D)``, the sign composition and ``A_sign``, the Pearson shape correlation, each
  side's maximum and the localized-peak displacement/coincidence). It is independent of the
  input layer, of the repeat context and of the run's records: the same arrays always give the
  same §5 output; and
* :mod:`sparse_sa5_cross_models` — the typed records, the state/reason vocabulary and the §6
  repeat context (the explicit mapping, the ``E20`` whole-achieved-condition identity proof, and
  the ``repeat-context-unavailable`` / ``repeat-context-identity-unverifiable`` typed-empties).

The context is **attached afterward**, in this module and after the core has run, so no repeat
state can reach a §5 quantity, a ``comparison_state`` or a ``label_state``.

Repeat context — the honest limit of the frozen quartet (§6). The prespec selects a repeat
group **by exact achieved identity**, but the published ``repeats`` rows carry only
``condition`` (prose) and their members' ``label``/``order``/``job`` — no structured
achieved-condition fields — so the explicit §6 mapping is implemented literally and validated
against what *is* published: ``E20`` selects the common-reference group, whose members
``cr1..cr4`` *are* the operand's own published members (whole-condition identity proved from
the quartet); the four corners and the interaction are typed-empty
``repeat-context-unavailable``; and ``e8``/``e64``/``e128`` name each operand's job
block-local anchor group, whose members are ``ctrl-*`` rows published **only** in ``repeats``
with no achieved condition anywhere — so identity **cannot** be established, the entry is
typed ``repeat-context-identity-unverifiable``, the named group's members and condition are
still quoted, but **no numerical repeat range is published** (a range would read as the
operand's own) and the run records a ``limitations`` entry. A context state never touches
``comparison_state`` or ``label_state``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from udv_echo_process.analysis import sparse_sa5_cross_core as core
from udv_echo_process.analysis import sparse_sa5_cross_input as binding
from udv_echo_process.analysis import sparse_sa5_cross_models as models
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_sa5_cross_core import (
    GATE_TOLERANCE_MM,
    REASON_CONSTANT_PROFILE,
    REASON_INSUFFICIENT_DEPTH,
    Diagnostics,
    KnotComparison,
)
from udv_echo_process.analysis.sparse_sa5_cross_input import (
    CORNER_GRID,
    EMISSIONS_GRID,
    LIVE1,
    LIVE2,
    ORIENTATION,
    REPORT_DIR,
    SCHEMA_ID,
    SITTING_NAMES,
    FrozenQuartet,
    effect_id,
    expected_grid,
    load_published_quartets,
    load_quartet,
)
from udv_echo_process.analysis.sparse_sa5_cross_models import (
    COMPARISON_STATES,
    LABEL_DEFERRED,
    REASON_COMMON_BASIS,
    REASON_EFFECT_ID,
    REASON_EMPTY_SUPPORT,
    REASON_GRID,
    REASON_MISSING_SIDE,
    REASON_NO_RULE,
    REASON_REPEAT_UNAVAILABLE,
    REASON_REPEAT_UNVERIFIABLE,
    REASON_TRIPLE,
    REASON_UNITS,
    REASON_WHOLLY_UNDEFINED,
    REPEAT_CONTEXT_MAPPING,
    REPEAT_REASONS,
    ComparisonState,
    CrossSittingComparison,
    EffectComparison,
    RepeatContext,
    RepeatContextMember,
    RepeatContextState,
    SideContext,
    SideProvenance,
    SparseSa5CrossSittingError,
)
from udv_echo_process.analysis.sparse_sa5_effects import INTERACTION_NAME
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName

__all__ = [
    "COMPARISON_STATES",
    "CORNER_GRID",
    "EMISSIONS_GRID",
    "GATE_TOLERANCE_MM",
    "INTERACTION_NAME",
    "LABEL_DEFERRED",
    "LIVE1",
    "LIVE2",
    "ORIENTATION",
    "REASON_COMMON_BASIS",
    "REASON_CONSTANT_PROFILE",
    "REASON_EFFECT_ID",
    "REASON_EMPTY_SUPPORT",
    "REASON_GRID",
    "REASON_INSUFFICIENT_DEPTH",
    "REASON_MISSING_SIDE",
    "REASON_NO_RULE",
    "REASON_REPEAT_UNAVAILABLE",
    "REASON_REPEAT_UNVERIFIABLE",
    "REASON_TRIPLE",
    "REASON_UNITS",
    "REASON_WHOLLY_UNDEFINED",
    "REPEAT_CONTEXT_MAPPING",
    "REPEAT_REASONS",
    "REPORT_DIR",
    "SCHEMA_ID",
    "SITTING_NAMES",
    "ComparisonState",
    "CrossSittingComparison",
    "Diagnostics",
    "EffectComparison",
    "FrozenQuartet",
    "KnotComparison",
    "RepeatContext",
    "RepeatContextMember",
    "RepeatContextState",
    "SideContext",
    "SideProvenance",
    "SparseSa5CrossSittingError",
    "compare_cross_sitting",
    "compare_published",
    "effect_id",
    "expected_grid",
    "load_published_quartets",
    "load_quartet",
]


def _fail(message: str) -> SparseSa5CrossSittingError:
    """One refusal message, as this slice's error."""
    return SparseSa5CrossSittingError(message)


def _context(
    side: FrozenQuartet, key: str, contrast: str, metric: str, view: str
) -> SideContext:
    """One side's frozen scalar context with its per-operand §6 repeat contexts attached.

    This is the *only* place the repeat context enters a record, and it runs after the core has
    produced the §5 records: the context is attached beside them and never feeds back.
    """
    return models.side_context(
        sitting=side.sitting,
        cells=side.csv_rows[key],
        repeats=models.repeat_contexts(
            side.document, side.stem, contrast, metric, view
        ),
    )


def _compare_effect(
    metric: MetricName,
    view: SparseView,
    contrast: str,
    left: FrozenQuartet,
    right: FrozenQuartet,
) -> EffectComparison:
    """One typed comparison: match strictly, then compute every prespecified diagnostic."""
    key = effect_id(view, metric, contrast)
    left_record = binding.resolve_effect(left, metric, view, contrast)
    right_record = binding.resolve_effect(right, metric, view, contrast)
    present = right_record or left_record or {}
    grid, units = present.get("grid"), present.get("units")
    knot_count, participant_count = (
        present.get("knot_count"),
        present.get("participant_count"),
    )

    def build(
        state: ComparisonState,
        reason: str,
        label: str | None,
        diagnostics: Diagnostics | None = None,
        support_mm: tuple[float, float] | None = None,
        knots_mm: tuple[float, ...] = (),
        knots: tuple[KnotComparison, ...] = (),
    ) -> EffectComparison:
        return EffectComparison(
            effect_id=key,
            view=view.value,
            metric=metric.value,
            contrast=contrast,
            grid=None if grid is None else str(grid),
            units=None if units is None else str(units),
            knot_count=None if knot_count is None else int(knot_count),  # type: ignore[arg-type]
            participant_count=(
                None if participant_count is None else int(participant_count)  # type: ignore[arg-type]
            ),
            comparison_state=state,
            comparison_reason=reason,
            label_state=label,
            support_mm=support_mm,
            knots_mm=knots_mm,
            knots=knots,
            diagnostics=diagnostics,
            context1=_context(left, key, contrast, metric.value, view.value),
            context2=_context(right, key, contrast, metric.value, view.value),
        )

    def no(reason: str) -> EffectComparison:
        return build(ComparisonState.NOT_COMPARABLE, reason, None)

    if left_record is None or right_record is None:
        missing = "live-1" if left_record is None else "live-2"
        return no(
            f"{REASON_MISSING_SIDE}: the effect is not published on {missing}, so the pair is "
            "not matched"
        )
    if left_record.get("effect_id") != right_record.get("effect_id"):
        return no(REASON_EFFECT_ID)
    grid_expected = expected_grid(contrast)
    for record in (left_record, right_record):
        if record.get("grid") != grid_expected:
            return no(REASON_GRID)
        if record.get("units") != left_record.get("units"):
            return no(REASON_UNITS)
    structural = (
        "metric",
        "view",
        "contrast",
        "grid",
        "units",
        "knot_count",
        "participant_count",
    )
    if any(left_record.get(f) != right_record.get(f) for f in structural):
        return no(REASON_TRIPLE)

    left_arrays, right_arrays = left.arrays[key], right.arrays[key]
    if not core.native_knots_match(left_arrays, right_arrays):
        return no(REASON_GRID)
    support = (
        max(float(left_record["support_mm"][0]), float(right_record["support_mm"][0])),  # type: ignore[index]
        min(float(left_record["support_mm"][1]), float(right_record["support_mm"][1])),  # type: ignore[index]
    )
    if support[1] <= support[0]:
        return no(REASON_EMPTY_SUPPORT)
    # A comparison knot must lie inside both sides' supports (§3), so the comparison domain is
    # the native knots inside the support intersection. The domain is narrowed here, before any
    # row, mask or diagnostic is built: an excluded endpoint is not a comparison knot and can
    # influence neither the defined count, L, a signed/RMS reduction, a sign, the correlation,
    # a numerical maximum nor a localized peak.
    within = core.within_support(right_arrays.knots_mm, support)
    if not bool(within.any()):
        return no(REASON_EMPTY_SUPPORT)
    left_arrays = core.restrict(left_arrays, within)
    right_arrays = core.restrict(right_arrays, within)
    knots = np.asarray(right_arrays.knots_mm, dtype=float)

    rows, definition = core.knot_comparison(knots, left_arrays, right_arrays)
    if not bool(definition.any()):
        return no(REASON_WHOLLY_UNDEFINED)
    return build(
        ComparisonState.COMPARABLE,
        REASON_COMMON_BASIS,
        LABEL_DEFERRED,
        diagnostics=core.comparison_diagnostics(
            rows, definition, left_arrays, right_arrays
        ),
        support_mm=support,
        knots_mm=tuple(float(d) for d in knots),
        knots=rows,
    )


def compare_cross_sitting(
    live1: FrozenQuartet, live2: FrozenQuartet
) -> CrossSittingComparison:
    """Compare two digest-verified quartets as ``live2 - live1``, returning 72 typed records.

    The orientation is fixed by the two arguments' own names, so a reversed pair refuses, and
    the run writes nothing.

    Raises:
        SparseSa5CrossSittingError: for a reversed orientation, or a §6 mapping whose named
            group is absent from a side's published repeats (a publication defect).
    """
    if live1.sitting != LIVE1 or live2.sitting != LIVE2:
        raise _fail(
            f"the comparison is fixed as {ORIENTATION!r} by name; got "
            f"({live1.sitting!r}, {live2.sitting!r}). The reversed orientation is refused, "
            "never silently accepted"
        )
    records = tuple(
        _compare_effect(metric, view, contrast, live1, live2)
        for metric, view, contrast in binding.comparison_keys()
    )
    if len(records) != 72 or len({record.effect_id for record in records}) != len(
        records
    ):
        raise _fail("the comparison set is not the frozen 72 unique keys")

    unverifiable = sorted(
        {
            context.operand
            for record in records
            for context in (*record.context1.repeats, *record.context2.repeats)
            if context.state is RepeatContextState.UNVERIFIABLE
        }
    )
    limitations: tuple[str, ...] = ()
    if unverifiable:
        limitations = (
            (
                f"repeat-context whole-condition identity for {unverifiable} could not be "
                "established from the frozen quartets: the §6 mapping names each operand's job "
                "block-local anchor group, but those groups' members are ctrl-* rows published "
                "only in `repeats` and carry no achieved-condition fields, so no numerical repeat "
                "range is reported for them. This gap is accepted ancillary context, not a blocker: "
                "under the amended prespec §11.8 an identity-unverifiable entry whose numerical "
                "range is omitted satisfies the gate, and it neither blocks publication nor "
                "changes the run's `ok`, any `comparison_state` or any `label_state`."
            ),
        )
    checks = {
        "no_output_artifact_written": True,
        "fixed_orientation_live2_minus_live1": True,
        "seventy_two_comparisons": len(records) == 72,
        "every_effect_id_resolves_in_both_sittings": not any(
            record.comparison_reason.startswith(REASON_MISSING_SIDE)
            for record in records
        ),
        "comparison_and_label_states_kept_separate": all(
            (record.comparison_state is ComparisonState.COMPARABLE)
            == (record.label_state == LABEL_DEFERRED)
            for record in records
        ),
        "no_label_but_deferred_pending_review_is_written": all(
            record.label_state in (None, LABEL_DEFERRED) for record in records
        ),
        "no_recurrence_verdict": True,
        "repeat_context_identity_fully_established": not unverifiable,
        # The context axis is orthogonal: a repeat state never becomes a comparison_state, and
        # no repeat-context reason ever appears in a record's comparison_reason.
        "repeat_context_state_isolated_from_comparison_and_label": all(
            record.comparison_reason not in REPEAT_REASONS
            and record.comparison_state.value
            not in {s.value for s in RepeatContextState}
            for record in records
        ),
    }
    return CrossSittingComparison(
        schema_id=SCHEMA_ID,
        comparison=ORIENTATION,
        sitting1=LIVE1,
        sitting2=LIVE2,
        provenance1=live1.provenance(),
        provenance2=live2.provenance(),
        records=records,
        checks=checks,
        limitations=limitations,
    )


def compare_published(report_dir: Path = REPORT_DIR) -> CrossSittingComparison:
    """Load both published quartets, verify their chains, and compare them (§1–§10)."""
    live1, live2 = load_published_quartets(report_dir)
    return compare_cross_sitting(live1, live2)
