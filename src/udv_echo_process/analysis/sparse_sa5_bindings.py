"""SA5 — the frozen operand and contrast *binding*, before any effect value.

`docs/dop3000/sa5-sitting-effects-prespec.md` fixes seven oriented within-sitting
contrasts whose operand membership, acquisition order, achieved settings, view and
grid alignment must be identical for both mixer-enabled sittings. This module is that
contract as typed data plus the checks that bind a sitting to it — and **nothing else**:

- it computes no effect, no metric and no profile: it resolves *which recording* (or
  which four-run reduction) each contrast operand is, and refuses a sitting whose rows
  are not exactly the operands the prespecification froze;
- a :class:`SparseIngest`-shaped row (``reports/<plan>/points.csv``) or any mapping with
  the same cells binds through :func:`bind_sitting`, so the binding is a property of the
  committed per-pass inventory rather than of a hard-coded filename;
- the four ``cc*`` corners, the four ``cr1..cr4`` E20 members and the three single
  emissions points are pinned by planned job, point label, acquisition order and decoded
  achieved condition (burst, emissions, PRF, stored pitch, gates), while the block-local
  ``ctrl-*`` anchors are **excluded** from every operand;
- the primary window (the declared 12 s), the common physical support and each group's
  native gate grid are re-derived from the bound rows, so a window or grid change refuses
  instead of silently re-binding a different measurement.

The orientation and the interaction reduction are derived here as coefficient tables, not
evaluated: for each contrast the effect is ``M(high) - M(low)``; the pitch x burst
interaction is ``[M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]``. No velocity value is read,
computed or published by this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis.sparse_inventory import (
    DESIGNED_WINDOW_S,
    SparseIngestError,
)

#: The design's own constants, restated here only to *check* a decoded setting. The
#: sound speed is the frozen plan's (every point of both sittings records 1480 m/s), the
#: nominal RPM is the 12 s window's 100 revolutions, and the two pitches are the
#: reference window (1.85 mm x 50 gates) and the coarsest participating grid.
SOUND_SPEED_MS = 1480.0
NOMINAL_RPM = 500.0
REVOLUTION_S = 60.0 / NOMINAL_RPM
WINDOW_REVOLUTIONS = round(DESIGNED_WINDOW_S / REVOLUTION_S)  # 100
PRF_US = 600.0
DEPTH_START_MM = 10.138
DEPTH_END_MM = 98.938
COARSE_PITCH_MM = 2.96
REFERENCE_PITCH_MM = 1.85
REFERENCE_GATES = 50
CORNER_EMISSIONS = 20
REFERENCE_BURST = 10

#: The label prefix that marks a block-local anchor control. No operand may carry it.
CONTROL_PREFIX = "ctrl-"

#: Slacks: a decoded pitch against the ladder rung the application accepts, and a
#: reconstructed grid's last gate against the row's own stored last gate.
GRID_RTOL = 1e-6
GATE_TOLERANCE_MM = 1e-6

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


class Sa5BindingError(SparseIngestError):
    """A sitting's rows are not the operands the SA5 prespecification froze."""


# ── the frozen membership ──────────────────────────────────────────────


class CornerSpec(NamedTuple):
    """One corner of the 2x2 pitch x burst design, as the prespec fixes it."""

    label: str
    job: str
    order: int
    burst_length: int
    pitch_requested_mm: float
    gates: int


#: The four ``cc*`` corners, in label order. The job, the planned order and the burst
#: are the prespec's; ``pitch_requested_mm`` is the request the stored rung answers to.
CORNERS: tuple[CornerSpec, ...] = (
    CornerSpec("cc1", "burst-4", 2, 4, 0.617, 145),
    CornerSpec("cc2", "burst-18", 8, 18, 0.617, 145),
    CornerSpec("cc3", "burst-4", 4, 4, 2.96, 31),
    CornerSpec("cc4", "burst-18", 10, 18, 2.96, 31),
)

#: The corners that carry the coarse grid: their native supported depths are the common
#: knot set, and the interaction is aligned on it.
KNOT_LABELS: tuple[str, ...] = ("cc3", "cc4")
CC_LABELS: tuple[str, ...] = tuple(corner.label for corner in CORNERS)


class E20MemberSpec(NamedTuple):
    """One common-reference run the E20 operand averages, equally weighted."""

    label: str
    job: str
    order: int


#: The four E20 members, one per reference job, in the prespec's job/order.
E20_MEMBERS: tuple[E20MemberSpec, ...] = (
    E20MemberSpec("cr1", "common-reference-1", 6),
    E20MemberSpec("cr2", "common-reference-2", 12),
    E20MemberSpec("cr3", "common-reference-3", 17),
    E20MemberSpec("cr4", "common-reference-4", 22),
)
E20_LABELS: tuple[str, ...] = tuple(member.label for member in E20_MEMBERS)


class SingleEmissionsSpec(NamedTuple):
    """One single-recording emissions level: its own scientific row, no anchor."""

    label: str
    job: str
    order: int
    emissions: int


#: The three single emissions points, in ladder order. Each is *only* its scientific
#: recording: the job's ``ctrl-*`` anchors are never averaged into the operand.
SINGLE_EMISSIONS: tuple[SingleEmissionsSpec, ...] = (
    SingleEmissionsSpec("e8", "emissions-8", 14, 8),
    SingleEmissionsSpec("e64", "emissions-64", 19, 64),
    SingleEmissionsSpec("e128", "emissions-128", 24, 128),
)
SINGLE_LABELS: tuple[str, ...] = tuple(single.label for single in SINGLE_EMISSIONS)

#: Every label an operand may name, anchors excluded by construction.
OPERAND_LABELS: tuple[str, ...] = CC_LABELS + E20_LABELS + SINGLE_LABELS


# ── the seven oriented contrasts ───────────────────────────────────────


class Operand(NamedTuple):
    """One side of a contrast: a single recording, or the four-run E20 mean."""

    name: str
    kind: str
    members: tuple[str, ...]


def recording(label: str) -> Operand:
    """A one-recording operand: one scientific row, no anchor, no reduction."""
    return Operand(label, "recording", (label,))


#: The E20 operand: the arithmetic mean of ``cr1..cr4``, equal recording weights.
E20_OPERAND = Operand("E20", "mean-of-four", E20_LABELS)


class ContrastSpec(NamedTuple):
    """One oriented contrast: ``effect = M(high) - M(low)``, per knot and metric."""

    name: str
    high: Operand
    low: Operand
    reduction: str


CONTRASTS: tuple[ContrastSpec, ...] = (
    ContrastSpec(
        "pitch_at_burst_4",
        recording("cc3"),
        recording("cc1"),
        "one scientific recording on each side",
    ),
    ContrastSpec(
        "pitch_at_burst_18",
        recording("cc4"),
        recording("cc2"),
        "one scientific recording on each side",
    ),
    ContrastSpec(
        "burst_at_fine_pitch",
        recording("cc2"),
        recording("cc1"),
        "one scientific recording on each side",
    ),
    ContrastSpec(
        "burst_at_coarse_pitch",
        recording("cc4"),
        recording("cc3"),
        "one scientific recording on each side",
    ),
    ContrastSpec(
        "E8_minus_E20",
        recording("e8"),
        E20_OPERAND,
        "one E8 profile versus the equal-weight mean of four E20 profiles",
    ),
    ContrastSpec(
        "E64_minus_E20",
        recording("e64"),
        E20_OPERAND,
        "one E64 profile versus the equal-weight mean of four E20 profiles",
    ),
    ContrastSpec(
        "E128_minus_E20",
        recording("e128"),
        E20_OPERAND,
        "one E128 profile versus the equal-weight mean of four E20 profiles",
    ),
)

CONTRAST_NAMES: tuple[str, ...] = tuple(contrast.name for contrast in CONTRASTS)


class InteractionContribution(NamedTuple):
    """One corner's signed weight in the pitch x burst interaction, per common knot."""

    label: str
    coefficient: float


#: ``I = [M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]``, expanded: the coefficients below are
#: the *binding* of the interaction, not its value. The anchors carry no coefficient.
INTERACTION_CONTRIBUTIONS: tuple[InteractionContribution, ...] = (
    InteractionContribution("cc1", 1.0),
    InteractionContribution("cc2", -1.0),
    InteractionContribution("cc3", -1.0),
    InteractionContribution("cc4", 1.0),
)

INTERACTION_EXPRESSION = "[M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]"


def interaction_contributions() -> dict[str, float]:
    """The interaction's per-corner coefficients, as a mapping (label -> weight)."""
    return {item.label: item.coefficient for item in INTERACTION_CONTRIBUTIONS}


# ── one bound row ──────────────────────────────────────────────────────


class OperandRow(NamedTuple):
    """One row of the committed per-pass inventory, reduced to the cells SA5 binds on."""

    label: str
    job: str
    order: int
    identity: str
    relative_path: str
    source_sha256: str
    plan: str
    plan_fingerprint: str
    burst_length: int
    emissions_per_profile: int
    prf_us: float
    resolution_mm: float
    gates: int
    first_gate_mm: float
    last_gate_mm: float
    supported_gates: int
    window_s: float
    is_control: bool


def _number(source: Mapping[str, object], key: str, where: str) -> float:
    """One numeric cell, refused by name when absent, empty or not a number."""
    if key not in source:
        raise Sa5BindingError(f"{where}: no {key!r} cell to bind on")
    value = source[key]
    if isinstance(value, bool):
        raise Sa5BindingError(f"{where}: {key!r} is a boolean, not a number")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise Sa5BindingError(f"{where}: the {key!r} cell is empty")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise Sa5BindingError(
                f"{where}: {key!r} is {value!r}, not a number"
            ) from None
    raise Sa5BindingError(f"{where}: {key!r} is {value!r}, not a number")


def _integer(source: Mapping[str, object], key: str, where: str) -> int:
    """One integral cell, refused when it is not whole."""
    value = _number(source, key, where)
    if value != int(value):
        raise Sa5BindingError(f"{where}: {key!r} is {value!r}, not an integer")
    return int(value)


def _text(source: Mapping[str, object], key: str) -> str:
    """One text cell, an absent one becoming the empty string."""
    value = source.get(key)
    return "" if value is None else str(value)


def operand_row(source: Mapping[str, object]) -> OperandRow:
    """Reduce one inventory row to the cells SA5 binds on, or refuse by name.

    Accepts a ``points.csv`` row (every cell a string) or a caller-built mapping with the
    same keys; the two are treated identically so a test can mutate a real row.
    """
    where = str(source.get("relative_path") or source.get("identity") or "a row")
    path = _text(source, "relative_path")
    digest = _text(source, "source_sha256").strip().lower()
    return OperandRow(
        label=_text(source, "requested_label").strip(),
        job=_text(source, "job").strip(),
        order=_integer(source, "order", where),
        identity=_text(source, "identity").strip(),
        relative_path=path,
        source_sha256=digest,
        plan=_text(source, "plan").strip(),
        plan_fingerprint=_text(source, "plan_fingerprint").strip().lower(),
        burst_length=_integer(source, "burst_length", where),
        emissions_per_profile=_integer(source, "emissions_per_profile", where),
        prf_us=_number(source, "prf_period_us", where),
        resolution_mm=_number(source, "resolution_mm", where),
        gates=_integer(source, "gates", where),
        first_gate_mm=_number(source, "depth_min_mm", where),
        last_gate_mm=_number(source, "depth_max_mm", where),
        supported_gates=_integer(source, "supported_gates", where),
        window_s=_number(source, "window_s", where),
        is_control=_text(source, "is_control").strip().lower() == "true",
    )


def native_depths(row: OperandRow) -> tuple[float, ...]:
    """The row's native gate grid, reconstructed from its first gate, pitch and count."""
    return tuple(
        row.first_gate_mm + index * row.resolution_mm for index in range(row.gates)
    )


def _supported_count(row: OperandRow, support_mm: tuple[float, float]) -> int:
    """How many of the row's native gates lie inside the common physical support."""
    low, high = support_mm
    return sum(
        1
        for depth in native_depths(row)
        if low - GATE_TOLERANCE_MM <= depth <= high + GATE_TOLERANCE_MM
    )


# ── the bound sitting ──────────────────────────────────────────────────


class SittingBinding(NamedTuple):
    """One sitting's eleven operands, bound to the prespec's contract.

    No metric, profile or effect is here: ``corners``/``e20``/``singles`` name the
    recordings a contrast reads, and ``knot_depths_mm``/``emissions_depths_mm`` are the
    native grids the prespec aligns them on.
    """

    plan: str
    plan_fingerprint: str
    window_s: float
    window_revolutions: int
    support_mm: tuple[float, float]
    corners: tuple[OperandRow, ...]
    e20: tuple[OperandRow, ...]
    singles: tuple[OperandRow, ...]
    contrasts: tuple[ContrastSpec, ...]
    knot_depths_mm: tuple[float, ...]
    emissions_depths_mm: tuple[float, ...]
    control_labels: tuple[str, ...]

    @property
    def operands(self) -> tuple[OperandRow, ...]:
        """Every bound operand, in label order ``cc1..cc4, cr1..cr4, e8, e64, e128``."""
        return self.corners + self.e20 + self.singles

    def by_label(self, label: str) -> OperandRow:
        """The one bound operand whose label is ``label``, or a refusal naming it."""
        for row in self.operands:
            if row.label == label:
                return row
        raise Sa5BindingError(
            f"{self.plan}: {label!r} is not a bound SA5 operand; the operands are "
            f"{list(OPERAND_LABELS)}"
        )

    @property
    def control_context(self) -> tuple[str, ...]:
        """The block-local anchors present in the sitting — context, never operands."""
        return self.control_labels


def _require_operand(
    row: OperandRow,
    *,
    label: str,
    job: str,
    order: int,
    burst_length: int,
    emissions: int,
    pitch_requested_mm: float,
    gates: int,
    where: str,
) -> None:
    """Refuse a row that is not exactly one operand's planned, achieved condition."""
    if label.startswith(CONTROL_PREFIX) or row.is_control:
        raise Sa5BindingError(
            f"{where}: {label!r} is a block-local anchor control, and no anchor belongs "
            "to an SA5 effect operand"
        )
    if row.label != label:
        raise Sa5BindingError(
            f"{where}: the operand {label!r} resolved to a row labelled {row.label!r}"
        )
    if row.job != job:
        raise Sa5BindingError(
            f"{where}: {label!r} decodes to job {row.job!r}, the prespec places it in "
            f"{job!r}"
        )
    if row.order != order:
        raise Sa5BindingError(
            f"{where}: {label!r} is at acquisition order {row.order}, the prespec's "
            f"planned order is {order}"
        )
    if row.burst_length != burst_length:
        raise Sa5BindingError(
            f"{where}: {label!r} records burst {row.burst_length}, the operand's "
            f"condition is burst {burst_length}"
        )
    if row.emissions_per_profile != emissions:
        raise Sa5BindingError(
            f"{where}: {label!r} records {row.emissions_per_profile} emissions per "
            f"profile, the operand's condition is {emissions}"
        )
    if row.prf_us != PRF_US:
        raise Sa5BindingError(
            f"{where}: {label!r} records a PRF period of {row.prf_us!r} us, the design's "
            f"every-point value is {PRF_US}"
        )
    if row.gates != gates:
        raise Sa5BindingError(
            f"{where}: {label!r} stores {row.gates} gates, the operand's window is "
            f"{gates}"
        )
    accepted = clamp_resolution(pitch_requested_mm, SOUND_SPEED_MS)
    if abs(row.resolution_mm - accepted) > GRID_RTOL * abs(accepted):
        raise Sa5BindingError(
            f"{where}: {label!r} records pitch {row.resolution_mm!r} mm, the rung the "
            f"application accepts for the requested {pitch_requested_mm!r} mm is "
            f"{accepted!r} mm"
        )
    if abs(row.window_s - DESIGNED_WINDOW_S) > GRID_RTOL * DESIGNED_WINDOW_S:
        raise Sa5BindingError(
            f"{where}: {label!r} is bound in the {row.window_s!r} s window, the "
            f"prespec's primary view is the declared {DESIGNED_WINDOW_S!r} s"
        )


def _require_source(row: OperandRow, where: str) -> None:
    """Refuse a row with no usable source identity: file, digest and plan."""
    if not row.relative_path:
        raise Sa5BindingError(f"{where}: {row.label!r} names no recording")
    if not _HEX64.match(row.source_sha256):
        raise Sa5BindingError(
            f"{where}: {row.label!r} carries no sha256 source digest "
            f"({row.source_sha256!r})"
        )
    if not row.identity:
        raise Sa5BindingError(f"{where}: {row.label!r} carries no identity")
    if not row.identity.endswith(f"-{row.label}"):
        raise Sa5BindingError(
            f"{where}: {row.label!r} has identity {row.identity!r}, which does not end "
            f"with its label"
        )
    if not row.relative_path.startswith(row.identity):
        raise Sa5BindingError(
            f"{where}: {row.label!r} is stored as {row.relative_path!r}, which is not "
            f"the identity {row.identity!r}"
        )
    if not row.plan:
        raise Sa5BindingError(f"{where}: {row.label!r} names no plan")
    if not _HEX64.match(row.plan_fingerprint):
        raise Sa5BindingError(
            f"{where}: {row.label!r} carries no plan fingerprint "
            f"({row.plan_fingerprint!r})"
        )
    depths = native_depths(row)
    if abs(depths[-1] - row.last_gate_mm) > GATE_TOLERANCE_MM:
        raise Sa5BindingError(
            f"{where}: {row.label!r}'s stored depth {row.last_gate_mm!r} mm is not its "
            f"own native grid's last gate {depths[-1]!r} mm"
        )


def _support_of(rows: Sequence[OperandRow]) -> tuple[float, float]:
    """The common physical support: the intersection of the rows' decoded ranges."""
    if not rows:
        raise Sa5BindingError("no rows to bind, so no common support exists")
    low = max(row.first_gate_mm for row in rows)
    high = min(row.last_gate_mm for row in rows)
    if not high > low:
        raise Sa5BindingError(
            f"the rows' depth ranges intersect in {low!r}..{high!r} mm, which is empty"
        )
    return (low, high)


def _require_same_grid(
    rows: Sequence[OperandRow], *, what: str, where: str
) -> tuple[float, ...]:
    """Refuse unless every row shares one native gate grid, and return it."""
    first = rows[0]
    grid = native_depths(first)
    for row in rows[1:]:
        if (
            row.first_gate_mm != first.first_gate_mm
            or row.gates != first.gates
            or abs(row.resolution_mm - first.resolution_mm)
            > GRID_RTOL * abs(first.resolution_mm)
        ):
            raise Sa5BindingError(
                f"{where}: {row.label!r} does not record {first.label!r}'s native gate "
                f"grid, so {what} cannot be aligned without interpolation"
            )
    return grid


def _require_pitch(grid: Sequence[float], pitch_mm: float, *, where: str, what: str):
    """Refuse a grid whose uniform step is not the declared pitch."""
    if len(grid) < 2:
        raise Sa5BindingError(f"{where}: the {what} needs two gates, found {len(grid)}")
    steps = [grid[index + 1] - grid[index] for index in range(len(grid) - 1)]
    for step in steps:
        if abs(step - pitch_mm) > GRID_RTOL * pitch_mm:
            raise Sa5BindingError(
                f"{where}: the {what}'s gate pitch is {step!r} mm, the prespec's "
                f"coarsest participating pitch is {pitch_mm!r} mm"
            )


def bind_sitting(
    rows: Iterable[Mapping[str, object]],
    *,
    plan_name: str | None = None,
    support_mm: tuple[float, float] | None = None,
) -> SittingBinding:
    """Bind one sitting's committed rows to the frozen SA5 operand contract.

    Args:
        rows: the sitting's per-pass inventory rows (``points.csv``-shaped). Extra rows
            (the ``ctrl-*`` anchors, other jobs) are used only to derive the common
            support and the control context; they never enter an operand.
        plan_name: the pass name every operand row must name, or ``None`` to take the
            rows' own plan.
        support_mm: an explicit common support, or ``None`` to derive it as the
            intersection of the rows' decoded depth ranges.

    Returns:
        :class:`SittingBinding` — the eleven operands, their plans, the two native grids,
        the seven contrasts and the interaction coefficients. No metric is computed.

    Raises:
        Sa5BindingError: for a missing, duplicated or mislabelled operand, a wrong job
            or acquisition order, a mismatched achieved setting, PRF, grid or window, a
            source identity or digest that cannot be bound, a grid that is not shared
            within its group, or an anchor offered as an operand.
    """
    parsed = [operand_row(row) for row in rows]
    by_label: dict[str, OperandRow] = {}
    for row in parsed:
        if row.label not in OPERAND_LABELS:
            continue  # anchors and other jobs are context, never operands
        if row.label in by_label:
            raise Sa5BindingError(
                f"the sitting holds more than one recording labelled {row.label!r}"
            )
        by_label[row.label] = row

    support = support_mm if support_mm is not None else _support_of(parsed)
    plan = plan_name or (parsed[0].plan if parsed else "")
    where = plan or "the sitting"

    corners: list[OperandRow] = []
    for spec in CORNERS:
        row = by_label.get(spec.label)
        if row is None:
            raise Sa5BindingError(
                f"{where}: the 2x2 is missing the {spec.label!r} corner of job "
                f"{spec.job!r} at planned order {spec.order}"
            )
        _require_operand(
            row,
            label=spec.label,
            job=spec.job,
            order=spec.order,
            burst_length=spec.burst_length,
            emissions=CORNER_EMISSIONS,
            pitch_requested_mm=spec.pitch_requested_mm,
            gates=spec.gates,
            where=where,
        )
        corners.append(row)

    e20: list[OperandRow] = []
    for member in E20_MEMBERS:
        row = by_label.get(member.label)
        if row is None:
            raise Sa5BindingError(
                f"{where}: the E20 operand is missing the {member.label!r} member of "
                f"job {member.job!r} at planned order {member.order}"
            )
        _require_operand(
            row,
            label=member.label,
            job=member.job,
            order=member.order,
            burst_length=REFERENCE_BURST,
            emissions=CORNER_EMISSIONS,
            pitch_requested_mm=REFERENCE_PITCH_MM,
            gates=REFERENCE_GATES,
            where=where,
        )
        e20.append(row)

    singles: list[OperandRow] = []
    for single in SINGLE_EMISSIONS:
        row = by_label.get(single.label)
        if row is None:
            raise Sa5BindingError(
                f"{where}: the emissions ladder is missing the {single.label!r} point of "
                f"job {single.job!r} at planned order {single.order}"
            )
        _require_operand(
            row,
            label=single.label,
            job=single.job,
            order=single.order,
            burst_length=REFERENCE_BURST,
            emissions=single.emissions,
            pitch_requested_mm=REFERENCE_PITCH_MM,
            gates=REFERENCE_GATES,
            where=where,
        )
        singles.append(row)

    operands = corners + e20 + singles
    for row in operands:
        _require_source(row, where)
        if row.plan != plan:
            raise Sa5BindingError(
                f"{where}: {row.label!r} is stamped with plan {row.plan!r}, the sitting "
                f"is {plan!r}"
            )
        if _supported_count(row, support) != row.supported_gates:
            raise Sa5BindingError(
                f"{where}: {row.label!r} claims {row.supported_gates} supported gates "
                f"inside {support}, the derived count is "
                f"{_supported_count(row, support)}"
            )

    digests = [row.source_sha256 for row in operands]
    if len(set(digests)) != len(digests):
        raise Sa5BindingError(
            f"{where}: two operands share one source digest; every operand is a distinct "
            "recording"
        )
    fingerprints = {row.plan_fingerprint for row in operands}
    if len(fingerprints) != 1:
        raise Sa5BindingError(
            f"{where}: the operands carry {len(fingerprints)} distinct plan "
            "fingerprints; one sitting has one plan"
        )

    fine = _require_same_grid(corners[:2], what="the fine-pitch corners", where=where)
    coarse = _require_same_grid(corners[2:], what="the knot set", where=where)
    _require_pitch(
        fine,
        clamp_resolution(0.617, SOUND_SPEED_MS),
        where=where,
        what="fine-pitch corner grid",
    )
    _require_pitch(coarse, COARSE_PITCH_MM, where=where, what="common knot set")
    emissions_grid = _require_same_grid(
        e20 + singles, what="the emissions ladder", where=where
    )
    _require_pitch(
        emissions_grid,
        REFERENCE_PITCH_MM,
        where=where,
        what="reference-window grid",
    )

    controls = tuple(sorted({row.label for row in parsed if row.is_control}))
    return SittingBinding(
        plan=plan,
        plan_fingerprint=next(iter(fingerprints)),
        window_s=DESIGNED_WINDOW_S,
        window_revolutions=WINDOW_REVOLUTIONS,
        support_mm=(float(support[0]), float(support[1])),
        corners=tuple(corners),
        e20=tuple(e20),
        singles=tuple(singles),
        contrasts=CONTRASTS,
        knot_depths_mm=coarse,
        emissions_depths_mm=emissions_grid,
        control_labels=controls,
    )
