"""SA5 cross-sitting context/model layer — the typed records and the §6 repeat context.

This module carries the *named* part of the between-sitting slice: the closed reason and state
vocabulary, the typed in-memory records a run emits (:class:`EffectComparison`,
:class:`CrossSittingComparison`, the §10 provenance and the §7 state split), each sitting's
frozen §6 scalar context, and the §6 repeat-context resolution — the explicit
``(contrast, operand) → repeat group`` mapping implemented literally, the ``E20``
whole-achieved-condition identity proof, and the two orthogonal typed-empty states
``repeat-context-unavailable`` and ``repeat-context-identity-unverifiable`` (Amendment A1).

It holds no arithmetic: the §5 quantities come from :mod:`sparse_sa5_cross_core`, and nothing
here is ever read by it. The context records are built from the *published* structures a caller
passes in — a parsed quartet document, its CSV cells — so this module does not import the
input/binding layer and the direction of dependency stays one-way (input → models → core).

Two rules are structural, not conventional:

* a repeat group attaches to an operand **only** through provable whole-achieved-condition
  identity (proved from the sitting's published ``provenance`` rows); a ``job``/``label``/
  ``order`` name or the group's prose ``condition`` string is **never** a substitute, so the
  ``e8``/``e64``/``e128`` anchors are typed ``repeat-context-identity-unverifiable`` with **no
  numerical range** rather than attached by name; and
* a repeat context is excluded from every comparison decision — it can never produce a
  ``comparison_state``, a ``label_state`` or a §5 quantity, and an unverifiable context can
  never make a pair non-comparable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import NamedTuple

from pydantic import model_validator

from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_inventory import SparseIngestError
from udv_echo_process.analysis.sparse_sa5_bindings import E20_MEMBERS
from udv_echo_process.analysis.sparse_sa5_cross_core import Diagnostics, KnotComparison
from udv_echo_process.analysis.sparse_sa5_effects import INTERACTION_NAME
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.models.base import ValueModel

__all__ = [
    "COMPARISON_STATES",
    "LABEL_DEFERRED",
    "REASON_COMMON_BASIS",
    "REASON_EFFECT_ID",
    "REASON_EMPTY_SUPPORT",
    "REASON_GRID",
    "REASON_MISSING_SIDE",
    "REASON_NO_RULE",
    "REASON_REPEAT_UNAVAILABLE",
    "REASON_REPEAT_UNVERIFIABLE",
    "REASON_TRIPLE",
    "REASON_UNITS",
    "REASON_WHOLLY_UNDEFINED",
    "REPEAT_CONTEXT_MAPPING",
    "REPEAT_REASONS",
    "ComparisonState",
    "CrossSittingComparison",
    "EffectComparison",
    "RepeatContext",
    "RepeatContextClause",
    "RepeatContextMember",
    "RepeatContextState",
    "SideContext",
    "SideProvenance",
    "SparseSa5CrossSittingError",
    "effect_id",
    "repeat_contexts",
    "side_context",
]


class SparseSa5CrossSittingError(SparseIngestError):
    """The comparison cannot be made: a bad side, input, orientation or publication defect.

    Raised for an input outside the two reproducibility sittings, a reversed orientation, a
    missing/unreadable/broken-digest quartet, a side not ``ok``, a container the codec
    refuses, a drifted effect record, or a §6 mapping whose named repeat group is absent. A
    *typed non-value* is not this error: it is a state on a record.
    """


class ComparisonState(str, Enum):
    """Whether a matched pair has a common comparison basis (§7)."""

    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not comparable"
    NOT_RESOLVABLE = "not resolvable with this design"


class RepeatContextState(str, Enum):
    """How one operand's §6 repeat context was resolved from the published groups."""

    SELECTED = "selected"
    UNAVAILABLE = "repeat-context-unavailable"
    UNVERIFIABLE = "repeat-context-identity-unverifiable"


COMPARISON_STATES: tuple[str, ...] = (
    "comparable",
    "not comparable",
    "not resolvable with this design",
)
LABEL_DEFERRED = "deferred-pending-review"

#: The closed reason vocabulary (§7 tables, §3/§5 typed-empties and §6 repeat contexts).
REASON_EFFECT_ID = "effect-id-mismatch"
REASON_TRIPLE = "triple-mismatch"
REASON_GRID = "grid-mismatch-pending-review"
REASON_UNITS = "units-mismatch"
REASON_WHOLLY_UNDEFINED = "side-wholly-undefined"
REASON_EMPTY_SUPPORT = "empty-common-support"
REASON_MISSING_SIDE = "side-effect-not-published"
#: The ``comparable`` basis: the pair's structural basis and common defined knots are established,
#: independent of the deferred recurrence label (§7).
REASON_COMMON_BASIS = "common-basis-established"
REASON_NO_RULE = "not-resolvable-unregistered"
REASON_REPEAT_UNAVAILABLE = (
    "no-published-repeat-group-matches-the-operand-whole-condition"
)
REASON_REPEAT_UNVERIFIABLE = (
    "anchor-members-whole-achieved-condition-is-not-published-in-the-quartet"
)
REPEAT_REASONS: frozenset[str] = frozenset(
    {REASON_REPEAT_UNAVAILABLE, REASON_REPEAT_UNVERIFIABLE}
)

_CLAUSE_UNAVAILABLE = "unavailable"
_CLAUSE_COMMON_REFERENCE = "common-reference"
_CLAUSE_ANCHOR = "block-local-anchor"


def effect_id(view: SparseView | str, metric: MetricName | str, contrast: str) -> str:
    """The deterministic effect id of §2: ``"<view>__<metric>__<contrast>"``."""
    return f"{SparseView(view).value}__{MetricName(metric).value}__{contrast}"


def _fail(message: str) -> SparseSa5CrossSittingError:
    """One refusal message, as this slice's error."""
    return SparseSa5CrossSittingError(message)


class SideProvenance(ValueModel):
    """One side's §10 provenance: name, plan identity, the three digests and verdicts."""

    sitting: str
    pass_name: str
    plan: str
    plan_fingerprint: str
    stem: str
    json_sha256: str
    npz_sha256: str
    csv_sha256: str
    checks_ok: bool
    artifact_checks_ok: bool


class RepeatContextMember(ValueModel):
    """One published repeat member, quoted verbatim (label, order, job, scalar, state)."""

    label: str
    order: int
    job: str
    value: float | None
    defined_count: int
    state: str | None
    reason: str


class RepeatContext(ValueModel):
    """One operand's §6 repeat context, resolved through the prespec's explicit mapping.

    A ``selected`` entry's whole-condition identity was established from published metadata; an
    ``unverifiable`` entry names the prespec's group but records that its achieved condition is
    not published, so no whole-condition match is claimed and no numerical range is carried; an
    ``unavailable`` entry is the typed-empty case. ``group_condition`` is the published group's
    own ``condition`` text, quoted — never parsed as a matcher.
    """

    operand: str
    clause: str
    state: RepeatContextState
    group_condition: str | None
    members: tuple[RepeatContextMember, ...]
    min_value: float | None
    max_value: float | None
    spread: float | None
    identity_verified: bool
    identity_basis: str
    reason: str

    @model_validator(mode="after")
    def _check_the_typed_state_is_its_evidence(self) -> RepeatContext:
        if not self.identity_basis.strip() or not self.reason.strip():
            raise ValueError("every repeat context states its basis and reason")
        numbers = (self.min_value, self.max_value, self.spread)
        if self.state is RepeatContextState.UNAVAILABLE:
            if (
                self.members
                or self.group_condition is not None
                or self.identity_verified
            ):
                raise ValueError(
                    "an unavailable context names no group, member or identity"
                )
            if any(v is not None for v in numbers):
                raise ValueError("an unavailable repeat context carries no range")
            return self
        if not self.members or self.group_condition is None:
            raise ValueError(
                f"a {self.state.value!r} context names its published group and quotes its members"
            )
        selected = self.state is RepeatContextState.SELECTED
        if self.identity_verified is not selected:
            raise ValueError(
                f"a {self.state.value!r} context sets identity_verified {selected!r}: only a "
                "selected group may claim whole-condition identity"
            )
        if not selected and any(v is not None for v in numbers):
            raise ValueError(
                "an unverifiable repeat context publishes no numerical range: the group's "
                "condition is not the operand's, so its range must not read as the operand's"
            )
        return self


class SideContext(ValueModel):
    """One side's frozen magnitude/coverage context, quoted from its CSV, plus repeats."""

    sitting: str
    units: str | None
    rms_magnitude: float | None
    signed_depth_average: float | None
    equal_knot_average: float | None
    max_abs_value: float | None
    max_abs_depth_mm: float | None
    covered_depth_mm: float | None
    coverage_fraction: float | None
    defined_count: int | None
    undefined_alignment_count: int | None
    undefined_operand_count: int | None
    knot_count: int | None
    repeats: tuple[RepeatContext, ...]


class EffectComparison(ValueModel):
    """One typed comparison: the matched key, the two states, the knots and the context."""

    effect_id: str
    view: str
    metric: str
    contrast: str
    grid: str | None
    units: str | None
    knot_count: int | None
    participant_count: int | None
    comparison_state: ComparisonState
    comparison_reason: str
    label_state: str | None
    support_mm: tuple[float, float] | None
    knots_mm: tuple[float, ...]
    knots: tuple[KnotComparison, ...]
    diagnostics: Diagnostics | None
    context1: SideContext
    context2: SideContext

    @model_validator(mode="after")
    def _check_the_states_stay_separate(self) -> EffectComparison:
        comparable = self.comparison_state is ComparisonState.COMPARABLE
        if comparable and self.diagnostics is None:
            raise ValueError("a comparable pair carries its §5 diagnostics")
        if comparable and self.label_state != LABEL_DEFERRED:
            raise ValueError(
                "in v1 a comparable pair's label_state is deferred-pending-review"
            )
        if not comparable and self.label_state is not None:
            raise ValueError(
                "a non-comparable pair carries no recurrence label: its comparison_state is "
                "never written into the label field"
            )
        if self.comparison_state is ComparisonState.NOT_RESOLVABLE:
            raise ValueError(
                "no resolvability rule is registered, so this outcome never emits"
            )
        if len(self.knots) != len(self.knots_mm):
            raise ValueError("one comparison knot per comparison depth")
        if not self.comparison_reason.strip():
            raise ValueError("every comparison states why it is or is not comparable")
        return self


class CrossSittingComparison(ValueModel):
    """The whole run's typed result: the 72 comparisons, the two sides and the checks."""

    schema_id: str
    comparison: str
    sitting1: str
    sitting2: str
    provenance1: SideProvenance
    provenance2: SideProvenance
    records: tuple[EffectComparison, ...]
    checks: Mapping[str, bool]
    limitations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """True when structural comparison checks hold; context limits are ancillary."""
        return all(
            value
            for name, value in self.checks.items()
            if name != "repeat_context_identity_fully_established"
        )

    def record(
        self, view: SparseView | str, metric: MetricName | str, contrast: str
    ) -> EffectComparison:
        """The one comparison for a key, or a refusal naming it."""
        key = effect_id(view, metric, contrast)
        for item in self.records:
            if item.effect_id == key:
                return item
        raise _fail(f"this comparison has no effect {key!r}")


# ── §6 repeat context: the explicit mapping and its three states ────────


class RepeatContextClause(NamedTuple):
    """One prespec-fixed (contrast, operand) → repeat-group mapping entry (§6)."""

    contrast: str
    operand: str
    kind: str
    job: str = ""


def _corners(contrast: str, *operands: str) -> tuple[RepeatContextClause, ...]:
    """The ``unavailable`` clauses of one contrast's distinct corner operands."""
    return tuple(
        RepeatContextClause(contrast, operand, _CLAUSE_UNAVAILABLE)
        for operand in operands
    )


def _emissions(
    contrast: str, operand: str, job: str
) -> tuple[RepeatContextClause, ...]:
    """The two clauses of one emissions contrast: its anchor operand, then ``E20``."""
    return (
        RepeatContextClause(contrast, operand, _CLAUSE_ANCHOR, job),
        RepeatContextClause(contrast, "E20", _CLAUSE_COMMON_REFERENCE),
    )


#: §6's explicit mapping for the seven oriented contrasts and the interaction, transcribed
#: verbatim from the prespec table (published names, operand order, and the named group).
REPEAT_CONTEXT_MAPPING: tuple[RepeatContextClause, ...] = (
    *_corners("pitch_at_burst_4", "cc1", "cc3"),
    *_corners("pitch_at_burst_18", "cc2", "cc4"),
    *_corners("burst_at_fine_pitch", "cc1", "cc2"),
    *_corners("burst_at_coarse_pitch", "cc3", "cc4"),
    *_emissions("E8_minus_E20", "e8", "emissions-8"),
    *_emissions("E64_minus_E20", "e64", "emissions-64"),
    *_emissions("E128_minus_E20", "e128", "emissions-128"),
    *_corners(INTERACTION_NAME, "cc1", "cc2", "cc3", "cc4"),
)

_E20_LABELS = tuple(member.label for member in E20_MEMBERS)


def _repeat_member(row: Mapping[str, object]) -> RepeatContextMember:
    """One published repeat member quoted verbatim."""
    value, state = row.get("value"), row.get("state")
    return RepeatContextMember(
        label=str(row["label"]),
        order=int(row["order"]),  # type: ignore[arg-type]
        job=str(row["job"]),
        value=None if value is None else float(value),  # type: ignore[arg-type]
        defined_count=int(row["defined_count"]),  # type: ignore[arg-type]
        state=None if state is None else str(state),
        reason=str(row["reason"]),
    )


def _groups_for(
    document: Mapping[str, object], stem: str, metric: str, view: str
) -> tuple[Mapping[str, object], ...]:
    """Every published repeat group of one ``(metric, view)`` endpoint."""
    repeats = document.get("repeats")
    if not isinstance(repeats, list):
        raise _fail(f"{stem}.json publishes no repeats list")
    return tuple(
        group
        for group in repeats
        if isinstance(group, dict)
        and group.get("metric") == metric
        and group.get("view") == view
    )


def _one_group(
    matches: Sequence[Mapping[str, object]], what: str
) -> Mapping[str, object]:
    """Exactly one located group, or a refusal: a publication defect is never narrowed."""
    if len(matches) != 1:
        raise _fail(
            f"the §6 mapping names {what}, but the sitting's published repeats carry "
            f"{len(matches)} such group(s): a publication defect, never a silently narrowed mapping"
        )
    return matches[0]


def _anchor_group(
    groups: Sequence[Mapping[str, object]], job: str
) -> Mapping[str, object]:
    """The one published block-local anchor group of one job, or a refusal naming it."""
    return _one_group(
        [
            group
            for group in groups
            if group.get("members")
            and all(
                str(member["job"]) == job and str(member["label"]).startswith("ctrl-")
                for member in group["members"]  # type: ignore[union-attr]
            )
        ],
        f"the block-local anchor group of job {job!r}",
    )


def _common_reference_group(
    groups: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """The one published common-reference group (members ``cr1..cr4``), or a refusal."""
    return _one_group(
        [
            group
            for group in groups
            if tuple(str(m["label"]) for m in group["members"])  # type: ignore[union-attr]
            == _E20_LABELS
        ],
        f"the common-reference group ({list(_E20_LABELS)})",
    )


#: The three §6 repeat-context bases, quoted as they are explained to a reader.
_UNAVAILABLE_BASIS = (
    "the prespec fixes no published repeat group for this operand: its own stored window is "
    "not the reference window every published group records"
)
_SELECTED_BASIS = (
    "the group's members are the operand's own published members, whose whole achieved "
    "conditions appear in the provenance rows"
)
_ANCHOR_BASIS = (
    "the prespec names this operand's job anchor group, but the group's members are ctrl-* rows "
    "published only in `repeats`, which carry no achieved-condition fields; whole-condition "
    "identity is not establishable from the frozen quartet, and job/label is never substituted "
    "for it"
)


def repeat_contexts(
    document: Mapping[str, object], stem: str, contrast: str, metric: str, view: str
) -> tuple[RepeatContext, ...]:
    """Every distinct operand's §6 repeat context for one contrast on one endpoint."""
    groups = _groups_for(document, stem, metric, view)
    provenance = {
        str(row["label"]): row
        for row in document["provenance"]  # type: ignore[union-attr]
    }

    def make(
        clause: RepeatContextClause,
        state: RepeatContextState,
        basis: str,
        reason: str,
        group: Mapping[str, object] | None = None,
    ) -> RepeatContext:
        if group is None:
            return RepeatContext(
                operand=clause.operand,
                clause=clause.kind,
                state=state,
                group_condition=None,
                members=(),
                min_value=None,
                max_value=None,
                spread=None,
                identity_verified=False,
                identity_basis=basis,
                reason=reason,
            )
        numbers = state is RepeatContextState.SELECTED
        spread = group.get("spread")
        return RepeatContext(
            operand=clause.operand,
            clause=clause.kind,
            state=state,
            group_condition=str(group["condition"]),
            members=tuple(_repeat_member(r) for r in group["members"]),  # type: ignore[union-attr]
            min_value=float(group["min_value"]) if numbers else None,  # type: ignore[arg-type]
            max_value=float(group["max_value"]) if numbers else None,  # type: ignore[arg-type]
            spread=None if not numbers or spread is None else float(spread),  # type: ignore[arg-type]
            identity_verified=numbers,
            identity_basis=basis,
            reason=reason,
        )

    contexts: list[RepeatContext] = []
    for clause in (e for e in REPEAT_CONTEXT_MAPPING if e.contrast == contrast):
        if clause.kind == _CLAUSE_UNAVAILABLE:
            contexts.append(
                make(
                    clause,
                    RepeatContextState.UNAVAILABLE,
                    _UNAVAILABLE_BASIS,
                    REASON_REPEAT_UNAVAILABLE,
                )
            )
        elif clause.kind == _CLAUSE_COMMON_REFERENCE:
            group = _common_reference_group(groups)
            for row in group["members"]:  # type: ignore[union-attr]
                label = str(row["label"])
                published = provenance.get(label)
                if published is None:
                    raise _fail(
                        f"the common-reference group names {label!r}, not a published provenance "
                        "row, so its achieved condition cannot be read"
                    )
                if str(row["job"]) != str(published["job"]) or int(row["order"]) != int(
                    published["order"]
                ):
                    raise _fail(
                        f"the common-reference group's {label!r} row is not the published "
                        "provenance row of the same job and order"
                    )
            contexts.append(
                make(
                    clause,
                    RepeatContextState.SELECTED,
                    _SELECTED_BASIS,
                    "the operand and every group member are the same published recordings with "
                    "the same achieved condition",
                    group,
                )
            )
        else:  # block-local anchor: ctrl-* rows carry no achieved-condition fields
            contexts.append(
                make(
                    clause,
                    RepeatContextState.UNVERIFIABLE,
                    _ANCHOR_BASIS,
                    REASON_REPEAT_UNVERIFIABLE,
                    _anchor_group(groups, clause.job),
                )
            )
    return tuple(contexts)


def _num(
    cells: Mapping[str, str], column: str, cast: type = float
) -> float | int | None:
    """One CSV scalar, or ``None`` for the empty field."""
    text = cells.get(column, "")
    return None if text == "" else cast(text)


def side_context(
    sitting: str,
    cells: Mapping[str, str],
    repeats: tuple[RepeatContext, ...],
) -> SideContext:
    """One side's frozen magnitude/coverage context, quoted from its own CSV row."""
    return SideContext(
        sitting=sitting,
        units=(cells.get("units") or None),
        rms_magnitude=_num(cells, "rms_magnitude"),
        signed_depth_average=_num(cells, "signed_depth_average"),
        equal_knot_average=_num(cells, "equal_knot_average"),
        max_abs_value=_num(cells, "max_abs_value"),
        max_abs_depth_mm=_num(cells, "max_abs_depth_mm"),
        covered_depth_mm=_num(cells, "covered_depth_mm"),
        coverage_fraction=_num(cells, "coverage_fraction"),
        defined_count=_num(cells, "defined_count", int),
        undefined_alignment_count=_num(cells, "undefined_alignment_count", int),
        undefined_operand_count=_num(cells, "undefined_operand_count", int),
        knot_count=_num(cells, "knot_count", int),
        repeats=repeats,
    )
