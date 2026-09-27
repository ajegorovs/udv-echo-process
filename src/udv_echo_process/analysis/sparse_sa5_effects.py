"""SA5 within-sitting effect engine: seven oriented contrasts and the derived interaction.

``docs/dop3000/sa5-sitting-effects-prespec.md`` fixes seven oriented contrasts *per
sitting* whose operands, views, physical knots and reductions are frozen. This module
evaluates them, and only them, for **one sitting at a time**:

- it reads each recording's named observable through
  :func:`~udv_echo_process.analysis.sparse_sa5_metrics.read_metric_profile` — one scalar
  per ``(recording, view, metric, supported native gate)`` — on the two declared views
  (``primary-comparison`` for the three fluctuation statistics, and both that view and the
  labeled ``full-record`` view for the recurrence scalars and Φ);
- it binds the *committed per-pass inventory* to the **decoded** recordings the sitting's
  own pass produces, checking every operand's source digest, job, acquisition order and
  achieved settings against the decoded file before any number is read, so no substituted
  file and no stale row can enter an effect;
- it aligns each operand on the frozen WP3 rule — the coarsest participating grid's own
  native supported gate depths, each other operand read at its **nearest native gate** with
  the physical offset published, no interpolation — and reduces the E20 operand to the
  **exactly equal-weight mean of its four distinct common-reference runs**, refusing the
  E20 side at a knot (with the offending member and its own reason) whenever any of
  ``cr1..cr4`` is undefined there;
- it publishes, per contrast and metric/view, the per-depth effect profile first, then a
  depth summary whose signed average and RMS are trapezoidal integrals over only the
  *adjacent* knot pairs whose both endpoints define the effect — an undefined knot is never
  bridged or counted as a zero, and the covered depth and its fraction of the profile are
  stated — beside the physical weighting rule, the sign fractions over defined nonzero knots
  and the largest absolute effect with its depth; the signed depth average is never the only
  summary, because a spatially changing effect can cancel under averaging;
- it reports profile-shape correlation only where both compared profiles are nonconstant
  and sufficiently supported, and an explicit ``undefined`` with the reason otherwise;
- it describes same-whole-condition repeats (the four common-reference jobs, and each job's
  own block-local anchors) with their member labels and acquisition orders, as
  **descriptive** variation only — never a floor.

What is deliberately absent
---------------------------
No publication: nothing here writes a file, and no sitting table or document is rendered.
No cross-sitting arithmetic: :func:`measure_sitting` measures **one** sitting and returns
its typed result; the prespec's agreement step between the two sittings is a separate
artefact and is not offered here. No p-value, no post-hoc floor, no verdict on causality,
and no optimum. Gates and profiles inside one recording are correlated observations, never
replicates, so none is counted as one.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._native_grid import TOLERANCE_S
from udv_echo_process.analysis._sparse_pass import PassDecoding, decode_pass
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    WindowView,
    full_record_view,
    primary_view,
)
from udv_echo_process.analysis.sparse_inventory import (
    DESIGNED_WINDOW_S,
    SparseIngestError,
)
from udv_echo_process.analysis.sparse_passes import PassRef
from udv_echo_process.analysis.sparse_sa5_bindings import (
    REFERENCE_PITCH_MM,
    SittingBinding,
    bind_sitting,
    recording,
)
from udv_echo_process.analysis.sparse_sa5_metrics import (
    METRIC_UNITS,
    PRIMARY_METRICS,
    RECURRENCE_METRICS,
    SPECTRAL_METRICS,
    MetricName,
    MetricProfile,
    MetricState,
    read_metric_profile,
)
from udv_echo_process.analysis.sparse_spectral_characterization import DEFAULT_LOW_HZ
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CONTRAST_SOURCE",
    "ENDPOINTS",
    "INTERACTION_NAME",
    "METHOD",
    "MIN_SHAPE_KNOTS",
    "PROFILE_FIRST_RULE",
    "DepthEffects",
    "DepthSummary",
    "EffectState",
    "EndpointEffects",
    "KnotEffect",
    "OperandRead",
    "ProfileShape",
    "ReadAligned",
    "RepeatGroup",
    "RepeatMember",
    "SittingEffects",
    "SparseSa5EffectsError",
    "measure_binding",
    "measure_sitting",
]

#: The alignment tolerance, matching the binding's own gate tolerance.
GATE_TOLERANCE_MM = 1e-6
#: The relative tolerance a decoded pitch/window is compared with.
GRID_RTOL = 1e-6
#: The minimum number of defined common knots a profile correlation needs to be reported.
MIN_SHAPE_KNOTS = 3
#: A profile is treated as constant when its range is no more than this many times its own
#: scale. It is a floating-point constancy guard, not a screening threshold: a profile that
#: varies only by rounding noise is constant, and a correlation is not manufactured from it.
CONSTANT_TOLERANCE_REL = 1e-12


def _is_constant(values: np.ndarray) -> bool:
    """Whether a profile is constant to within floating-point rounding of its own scale."""
    if values.size < 2:
        return True
    scale = max(1.0, float(np.max(np.abs(values))))
    return float(np.ptp(values)) <= CONSTANT_TOLERANCE_REL * scale


#: The name of the derived pitch x burst interaction, one metric/view endpoint among the
#: sitting's results. It is not a fifth selection (prespec, "Oriented within-sitting
#: contrasts").
INTERACTION_NAME = "pitch_x_burst_interaction"
INTERACTION_EXPRESSION = "[M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]"

#: The rule the per-depth effect table is built under, stated once.
PROFILE_FIRST_RULE = (
    "publish E(z) first, with its valid common knots and units, then reduce it: the signed "
    "depth average, the RMS effect magnitude, the sign fractions over defined nonzero knots "
    "and the depth and signed value of the largest absolute effect (ties resolved by the "
    "shallower depth). The depth average and the RMS are trapezoidal integrals over the "
    "adjacent knot pairs whose *both* endpoints define the effect, so an undefined knot is "
    "never bridged and never counted as a zero; the covered depth and its fraction of the "
    "profile state how much of the profile the integral actually spans. On even spacing the "
    "two end knots carry half weight, so the equal-knot average is kept beside it. A signed "
    "average can cancel a spatially changing effect, so it is never the sole magnitude "
    "summary."
)

#: What the depth summary's weighting means.
WEIGHTING_RULE = (
    "trapezoidal physical weighting over the *adjacent pairs of valid common knots whose "
    "both endpoints define the effect*: each such interval contributes its own depth gap and "
    "no interval is bridged across an undefined knot. With L the summed width of those valid "
    "intervals (the covered depth), the signed depth average is "
    "sum((E_i + E_i+1)/2 * gap)/L and the RMS magnitude is "
    "sqrt(sum((E_i^2 + E_i+1^2)/2 * gap)/L). On a uniform, fully defined grid this is the "
    "ordinary trapezoid rule with half-weight end knots, and the separately reported "
    "equal-knot mean is not this integral. When no adjacent pair is valid L is zero, so the "
    "signed average and the RMS are not reported while the equal-knot average and the "
    "knot-wise sign fractions and extrema stay descriptive. The weights describe physical "
    "depth, not gate count."
)

METHOD = (
    "per sitting: bind the committed per-pass inventory to the decoded recordings (source "
    "digest, job, acquisition order, achieved settings all re-checked), read one scalar per "
    "(recording, view, metric, supported native gate) from the frozen SA1/SA2.4 slices, align "
    "each operand to the coarsest participating grid's native supported gate depths by "
    "nearest native gate (no interpolation), reduce E20 to the exactly equal-weight mean of "
    "its four common-reference runs (refusing the operand at a knot where any member is "
    "undefined), and form effect = M(high) - M(low) per knot. One sitting only: no "
    "cross-sitting arithmetic, no published table, no floor."
)

CONTRAST_SOURCE = (
    "seven oriented contrasts plus the derived pitch x burst interaction, exactly as "
    "docs/dop3000/sa5-sitting-effects-prespec.md fixes their operand membership, acquisition "
    "order and within-side reduction"
)


class SparseSa5EffectsError(SparseIngestError):
    """A sitting's effects cannot be measured as the prespec requires.

    Raised for a sitting that cannot be decoded, has no per-pass inventory, offers no
    operand the binding accepts, binds an operand whose decoded source digest or achieved
    settings disagree with the committed row, whose operands do not share their grids or a
    pitch, or whose recordings do not retain the declared primary window. A *refused
    measurement* - a constant trace, an unsupported 1/e decay, a declined spectral axis, an
    E20 member undefined at a knot - is not this error: it is a typed state on the gate row
    or the knot's effect.
    """


# ── per-record metric profiles, one per declared view ──────────────────


#: Every ``(metric, view)`` endpoint the prespec declares, in observable order: the three
#: fluctuation statistics on the primary comparison, then the two recurrence scalars and Φ,
#: each on the primary comparison and the full record.
ENDPOINTS: tuple[tuple[MetricName, SparseView], ...] = (
    *((metric, SparseView.PRIMARY) for metric in PRIMARY_METRICS),
    *(
        (metric, view)
        for metric in (*RECURRENCE_METRICS, *SPECTRAL_METRICS)
        for view in (SparseView.PRIMARY, SparseView.FULL_RECORD)
    ),
)


def _units(metric: MetricName) -> str:
    """The unit of one metric, read from the metric slice's own table."""
    return METRIC_UNITS[metric]


# ── typed per-knot effects and refusals ────────────────────────────────


class EffectState(str, Enum):
    """Whether a per-knot effect (or one of its operands) was measured, or why not.

    ``defined`` is the only state that carries a value. ``undefined-alignment`` means a
    required gate fell farther than half the knot pitch from its knot, so no measurement at
    that knot exists; ``undefined-operand`` means the operand's own metric was undefined or
    refused there (a constant trace, an unsupported decay, a declined axis, an undefined E20
    member). Neither is a substituted zero.
    """

    DEFINED = "defined"
    UNDEFINED_OPERAND = "undefined-operand"
    UNDEFINED_ALIGNMENT = "undefined-alignment"


class ReadAligned(ValueModel):
    """One recording's metric read at one knot: the native gate used, its offset and value.

    ``aligned`` is ``False`` exactly when no gate lay within half the knot pitch of the
    knot, in which case ``depth_mm``/``value``/``state`` are ``None`` and ``reason`` states
    the offset. Where the read is aligned, ``state`` is the metric slice's own gate state and
    ``value`` its value (``None`` for a defined-zero-power or refused gate).
    """

    label: str
    gate_index: int | None
    depth_mm: float | None
    offset_mm: float | None
    value: float | None
    state: MetricState | None
    reason: str

    @model_validator(mode="after")
    def _check_the_read_is_aligned_or_refused(self) -> ReadAligned:
        if self.depth_mm is None:
            if (
                self.gate_index is not None
                or self.offset_mm is not None
                or self.value is not None
                or self.state is not None
            ):
                raise ValueError(
                    "an unaligned read carries no gate index, depth, offset or value"
                )
        else:
            if self.gate_index is None or self.gate_index < 0:
                raise ValueError(
                    "an aligned read states its nonnegative native gate index"
                )
            if self.offset_mm is None:
                raise ValueError(
                    "an aligned read states the gate's offset from its knot"
                )
            if not math.isfinite(self.depth_mm) or not math.isfinite(self.offset_mm):
                raise ValueError("an aligned read carries finite depths")
            if self.state is MetricState.DEFINED:
                if self.value is None or not math.isfinite(self.value):
                    raise ValueError("an aligned, defined read carries a finite value")
            elif self.value is not None:
                raise ValueError(
                    f"an aligned read in state {self.state} carries no value, got "
                    f"{self.value!r}: a number here would read as a measurement never taken"
                )
            if self.state is None:
                raise ValueError(
                    "an aligned read carries the metric slice's own gate state"
                )
        if not self.reason.strip():
            raise ValueError("every read states what it is")
        return self

    @property
    def aligned(self) -> bool:
        """Whether a native gate lay close enough to the knot to stand in for it."""
        return self.depth_mm is not None

    @property
    def defined(self) -> bool:
        """Whether this read carries a measured value."""
        return self.aligned and self.state is MetricState.DEFINED


class OperandRead(ValueModel):
    """One side of a contrast at one knot: a single recording, or the E20 four-run mean.

    ``members`` is that side's aligned reads (one for a recording operand, four for ``E20``),
    in the operand's own order. ``value`` is defined exactly when ``state`` is
    :data:`EffectState.DEFINED`; for the E20 mean it is the exactly equal-weight arithmetic
    mean of the four member values, and a single undefined member leaves the whole operand
    undefined at that knot with ``reason`` naming the member and quoting its own reason.
    """

    name: str
    kind: str
    members: tuple[ReadAligned, ...]
    value: float | None
    state: EffectState
    reason: str

    @model_validator(mode="after")
    def _check_the_operand_value_is_its_state(self) -> OperandRead:
        if not self.members:
            raise ValueError(f"the operand {self.name!r} has at least one member read")
        if self.state is EffectState.DEFINED:
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("a defined operand carries a finite value")
        elif self.value is not None:
            raise ValueError(
                f"a {self.state.value!r} operand carries no value, got {self.value!r}"
            )
        if not self.reason.strip():
            raise ValueError("every operand states what it is")
        return self

    @property
    def defined(self) -> bool:
        """Whether this operand was measured at the knot."""
        return self.state is EffectState.DEFINED


class KnotEffect(ValueModel):
    """One knot's effect: its operands, the oriented value, or a typed refusal.

    ``operands`` is the contrast's sides in contract order (high then low for a two-sided
    contrast; ``cc1, cc2, cc3, cc4`` for the interaction), and ``value`` the coefficient
    combination of their values. It is defined only when every operand is defined.
    """

    knot_index: int
    depth_mm: float
    operands: tuple[OperandRead, ...]
    state: EffectState
    value: float | None
    reason: str

    @model_validator(mode="after")
    def _check_the_effect_value_is_its_state(self) -> KnotEffect:
        if self.knot_index < 0:
            raise ValueError(f"a knot index cannot be negative, got {self.knot_index}")
        if not math.isfinite(self.depth_mm):
            raise ValueError(f"a knot depth must be finite, got {self.depth_mm!r}")
        if self.state is EffectState.DEFINED:
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("a defined effect carries a finite value")
        elif self.value is not None:
            raise ValueError(
                f"a {self.state.value!r} effect carries no value, got {self.value!r}: an "
                "undefined effect is named by its state and reason, never by a zero"
            )
        if not self.reason.strip():
            raise ValueError("every knot states why its effect is or is not reported")
        return self

    @property
    def defined(self) -> bool:
        """Whether the effect was measured at this knot."""
        return self.state is EffectState.DEFINED


class DepthSummary(ValueModel):
    """The reduction of one effect profile, with its weighting rule and valid count.

    The signed depth average and the RMS magnitude are trapezoidal integrals over the
    *adjacent pairs of valid knots whose both endpoints define the effect*
    (:data:`WEIGHTING_RULE`); ``covered_depth_mm`` is their summed width and
    ``coverage_fraction`` its fraction of the profile's own span, so an undefined knot is
    never bridged and a hole is visible as a shorter integral. The equal-knot average is kept
    beside them, and the sign fragments over *defined nonzero* knots and every extreme (with
    the depth it was reached at) stay descriptive even where no interval carries a term.
    """

    metric: MetricName
    view: SparseView
    units: str
    knot_count: int
    defined_count: int
    undefined_count: int
    weighting_rule: str
    covered_depth_mm: float
    coverage_fraction: float | None
    signed_depth_average: float | None
    equal_knot_average: float | None
    rms_magnitude: float | None
    positive_fraction: float | None
    negative_fraction: float | None
    zero_fraction: float | None
    min_value: float | None
    min_depth_mm: float | None
    max_value: float | None
    max_depth_mm: float | None
    max_abs_value: float | None
    max_abs_depth_mm: float | None
    statement: str

    @model_validator(mode="after")
    def _check_the_reduction_matches_its_valid_intervals(self) -> DepthSummary:
        """A refusal, a non-finite number or a zero-width integral cannot masquerade."""
        if self.knot_count < 1:
            raise ValueError("a depth summary describes at least one knot")
        if not 0 <= self.defined_count <= self.knot_count:
            raise ValueError(
                f"the summary's {self.defined_count} defined knot(s) do not fit its "
                f"{self.knot_count}"
            )
        if self.undefined_count != self.knot_count - self.defined_count:
            raise ValueError(
                f"the undefined count {self.undefined_count} is not {self.knot_count} less "
                f"the {self.defined_count} defined"
            )
        if not math.isfinite(self.covered_depth_mm) or self.covered_depth_mm < 0.0:
            raise ValueError(
                "the covered width is a finite, nonnegative depth, got "
                f"{self.covered_depth_mm!r}"
            )
        if self.coverage_fraction is not None and not (
            0.0 <= self.coverage_fraction <= 1.0
        ):
            raise ValueError(
                f"the coverage fraction lies in [0, 1], got {self.coverage_fraction!r}"
            )
        described = (
            "signed_depth_average",
            "equal_knot_average",
            "rms_magnitude",
            "positive_fraction",
            "negative_fraction",
            "zero_fraction",
            "min_value",
            "min_depth_mm",
            "max_value",
            "max_depth_mm",
            "max_abs_value",
            "max_abs_depth_mm",
        )
        for name in described:
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(
                    f"{name} is a finite number or None, got {value!r}: a non-finite "
                    "number would stand in for a measurement never taken"
                )
        integrated = self.covered_depth_mm > 0.0
        if integrated != (self.signed_depth_average is not None):
            raise ValueError(
                "the signed depth average is reported exactly when the valid adjacent "
                "intervals cover a positive depth; a zero-width profile carries no integral, "
                "and a zero here would read as a measured average"
            )
        if integrated != (self.rms_magnitude is not None):
            raise ValueError(
                "the RMS magnitude is reported exactly when the valid adjacent intervals "
                "cover a positive depth"
            )
        if integrated and self.coverage_fraction is None:
            raise ValueError(
                "a positively covered profile states its coverage fraction"
            )
        if self.defined_count == 0:
            if any(getattr(self, name) is not None for name in described):
                raise ValueError(
                    "a profile with no defined knot has no reduction: every description is "
                    "None, never a substituted zero"
                )
        else:
            if self.equal_knot_average is None:
                raise ValueError(
                    "a profile with a defined knot states its equal-knot average"
                )
            if self.min_value is None or self.max_value is None:
                raise ValueError("a profile with a defined knot states its extrema")
            if self.min_value > self.max_value:
                raise ValueError(
                    f"the minimum {self.min_value!r} exceeds the maximum {self.max_value!r}"
                )
        return self


class ProfileShape(ValueModel):
    """The profile-level comparison of a two-sided contrast, or its explicit refusal.

    Correlation is reported only when both compared profiles are defined on at least
    :data:`MIN_SHAPE_KNOTS` common knots and neither is constant; otherwise ``correlation``
    is ``None`` and ``reason`` says which condition failed. The interaction has no pair of
    compared profiles, so its shape is undefined with that reason.
    """

    metric: MetricName
    view: SparseView
    correlation: float | None
    defined_count: int
    rule: str
    reason: str

    @property
    def defined(self) -> bool:
        """Whether a correlation is reported."""
        return self.correlation is not None


def _require_finite(value: float, where: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise SparseSa5EffectsError(f"{where}: a non-finite number {value!r}")
    return number


class DepthEffects(ValueModel):
    """One contrast (or the interaction) for one metric/view: profile first, then summary.

    ``knots_mm`` and ``effects`` are the published per-depth profile; ``summary`` is its
    reduction; ``shape`` is the profile-level correlation or its refusal. ``support_mm`` is
    the intersection of the participating operands' depth extents.
    """

    name: str
    expression: str
    reduction: str
    metric: MetricName
    view: SparseView
    units: str
    operand_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    knots_mm: tuple[float, ...]
    support_mm: tuple[float, float]
    half_pitch_mm: float
    max_abs_offset_mm: float
    alignment_rule: str
    effects: tuple[KnotEffect, ...]
    summary: DepthSummary
    shape: ProfileShape

    @model_validator(mode="after")
    def _check_the_profile_is_one_effect_per_knot(self) -> DepthEffects:
        if len(self.effects) != len(self.knots_mm):
            raise ValueError(
                f"{self.name}: {len(self.effects)} effect row(s) for "
                f"{len(self.knots_mm)} knot(s): one effect per knot"
            )
        depths = [row.depth_mm for row in self.effects]
        if depths != sorted(depths):
            raise ValueError(
                f"{self.name}: the effect rows must be in increasing depth order"
            )
        if self.summary.defined_count != sum(1 for row in self.effects if row.defined):
            raise ValueError(
                f"{self.name}: the summary's defined count is not the profile's"
            )
        if self.summary.knot_count != len(self.effects):
            raise ValueError(
                f"{self.name}: the summary describes {self.summary.knot_count} knot(s), the "
                f"profile publishes {len(self.effects)}"
            )
        span = (
            float(self.knots_mm[-1] - self.knots_mm[0])
            if len(self.knots_mm) >= 2
            else 0.0
        )
        if self.summary.covered_depth_mm > span + GATE_TOLERANCE_MM:
            raise ValueError(
                f"{self.name}: the covered depth {self.summary.covered_depth_mm!r} mm "
                f"exceeds the profile's own {span!r} mm span"
            )
        return self

    def knot(self, depth_mm: float) -> KnotEffect:
        """The one effect at a knot depth, or a refusal naming it."""
        for row in self.effects:
            if row.depth_mm == depth_mm:
                return row
        raise SparseSa5EffectsError(
            f"{self.name}: no knot at {depth_mm!r} mm; the knots are "
            f"{[round(d, 3) for d in self.knots_mm]}"
        )


class EndpointEffects(ValueModel):
    """One ``(metric, view)`` endpoint: its seven contrasts and the derived interaction."""

    metric: MetricName
    view: SparseView
    units: str
    contrasts: tuple[DepthEffects, ...]
    interaction: DepthEffects


# ── descriptive repeats ────────────────────────────────────────────────


class RepeatMember(ValueModel):
    """One recording of a same-whole-condition repeat, named with its acquisition order."""

    label: str
    order: int
    job: str
    value: float | None
    defined_count: int
    state: MetricState | None
    reason: str


class RepeatGroup(ValueModel):
    """A set of recordings that share one whole achieved condition, described not screened.

    ``spread`` is the max-minus-min of the defined member scalars. It is **descriptive**: the
    prespec promotes no repeat range to a floor, so this is variation to see, never a
    threshold. Members and their acquisition orders are named, and the four distinct
    common-reference jobs are described as their own group rather than counted as four
    independent runs of one condition.
    """

    condition: str
    members: tuple[RepeatMember, ...]
    metric: MetricName
    view: SparseView
    units: str
    knot_count: int
    defined_members: int
    min_value: float | None
    max_value: float | None
    spread: float | None
    rule: str
    statement: str


class SittingEffects(ValueModel):
    """One sitting's typed within-sitting result, for every declared metric/view endpoint."""

    pass_name: str
    plan: str
    plan_fingerprint: str
    window_s: float
    window_revolutions: int
    support_mm: tuple[float, float]
    method: str
    contrast_source: str
    endpoints: tuple[EndpointEffects, ...]
    repeats: tuple[RepeatGroup, ...]
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every structural check holds."""
        return all(self.checks.values())

    def endpoint(
        self, metric: MetricName | str, view: SparseView | str
    ) -> EndpointEffects:
        """The one endpoint for a metric on a view, or a refusal naming the alternatives."""
        wanted_metric = MetricName(metric)
        wanted_view = SparseView(view)
        for item in self.endpoints:
            if item.metric is wanted_metric and item.view is wanted_view:
                return item
        raise SparseSa5EffectsError(
            f"this sitting has no {wanted_metric.value!r} endpoint on {wanted_view.value!r}; "
            f"its endpoints are "
            f"{[(e.metric.value, e.view.value) for e in self.endpoints]}"
        )

    def contrast(
        self, name: str, metric: MetricName | str, view: SparseView | str
    ) -> DepthEffects:
        """One named contrast of one endpoint, or a refusal naming the alternatives."""
        item = self.endpoint(metric, view)
        for effect in item.contrasts:
            if effect.name == name:
                return effect
        raise SparseSa5EffectsError(
            f"{item.metric.value}/{item.view.value}: no contrast {name!r}; the contrasts are "
            f"{[effect.name for effect in item.contrasts]}"
        )


# ── reading one sitting ────────────────────────────────────────────────


def _read_inventory(path: Path) -> tuple[dict[str, str], ...]:
    """The committed per-pass inventory rows under ``path``, or a refusal naming it."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SparseSa5EffectsError(
            f"cannot read the per-pass inventory {path}: {exc}. A sitting is measured from "
            "its own committed inventory; this module will not substitute one"
        ) from exc
    return tuple(csv.DictReader(text.splitlines()))


def _operand_points(
    binding: SittingBinding, points: Sequence[object]
) -> dict[str, object]:
    """The one decoded recording per operand label, or a refusal naming what is missing."""
    by_label: dict[str, object] = {}
    for point in points:
        label = str(point.binding.point.label)  # type: ignore[attr-defined]
        by_label.setdefault(label, []).append(point)  # type: ignore[attr-defined]
    found: dict[str, object] = {}
    for row in binding.operands:
        matches = by_label.get(row.label, [])
        if len(matches) != 1:
            raise SparseSa5EffectsError(
                f"{binding.plan}: the decoded sitting holds {len(matches)} recording(s) "
                f"labelled {row.label!r}; the effect operand needs exactly one"
            )
        found[row.label] = matches[0]
    return found


def _require_source_matches(row, point, *, where: str) -> None:
    """Refuse unless the decoded recording is exactly the row the binding committed.

    The row's digest, identity, job, acquisition order, achieved settings and native grid are
    all re-checked against the decoded file: a stale row, a re-recorded file or a hand-typed
    inventory cannot enter an effect under a label the plan never bound it to.
    """
    label = row.label
    digest = str(getattr(point, "source_sha256", ""))
    if digest != row.source_sha256:
        raise SparseSa5EffectsError(
            f"{where}: the inventory records digest {row.source_sha256[:12]}... for "
            f"{label!r}, but the decoded recording hashes to {digest[:12] or '<none>'}...: "
            "an effect must be built on the file the inventory committed, never a "
            "substituted one"
        )
    if str(point.binding.point.label) != label:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} resolved to a recording labelled "
            f"{point.binding.point.label!r}"
        )
    if str(point.binding.job.job) != row.job:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} decodes to job {point.binding.job.job!r}, the inventory "
            f"binds it in {row.job!r}"
        )
    if int(point.binding.order) != row.order:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} is at acquisition order {int(point.binding.order)}, the "
            f"inventory binds order {row.order}"
        )
    config = point.config
    if int(config.burst_length or 0) != row.burst_length:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} decodes to burst {config.burst_length!r}, the inventory "
            f"binds burst {row.burst_length}"
        )
    if int(config.emissions_per_profile or 0) != row.emissions_per_profile:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} decodes to {config.emissions_per_profile!r} emissions per "
            f"profile, the inventory binds {row.emissions_per_profile}"
        )
    prf_us = 1e6 / float(config.pulse_repetition_freq_hz)
    if abs(prf_us - row.prf_us) > GRID_RTOL * row.prf_us:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} decodes to a PRF period of {prf_us!r} us, the inventory "
            f"binds {row.prf_us!r} us"
        )
    grid = np.asarray(point.depths, dtype=float)
    if grid.size != row.gates:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} stores {grid.size} gate(s), the inventory binds {row.gates}"
        )
    if (
        abs(float(grid[0]) - row.first_gate_mm) > GATE_TOLERANCE_MM
        or abs(float(grid[-1]) - row.last_gate_mm) > GATE_TOLERANCE_MM
    ):
        raise SparseSa5EffectsError(
            f"{where}: {label!r}'s decoded grid [{float(grid[0]):g}, {float(grid[-1]):g}] mm "
            f"is not the inventory's [{row.first_gate_mm:g}, {row.last_gate_mm:g}] mm"
        )
    if (
        abs(float(config.resolution_mm or 0.0) - row.resolution_mm)
        > GRID_RTOL * row.resolution_mm
    ):
        raise SparseSa5EffectsError(
            f"{where}: {label!r} decodes to pitch {config.resolution_mm!r} mm, the inventory "
            f"binds {row.resolution_mm!r} mm"
        )
    time_s = np.asarray(point.time_s, dtype=float)
    if time_s.size < 2 or float(time_s[-1] - time_s[0]) + TOLERANCE_S < row.window_s:
        raise SparseSa5EffectsError(
            f"{where}: {label!r} stores a span shorter than the declared "
            f"{row.window_s!r} s window, so it cannot enter the primary comparison"
        )


def _require_decoded_matches(
    binding: SittingBinding, operands: Mapping[str, object]
) -> None:
    """Every operand's decoded file must be the one the committed inventory bound."""
    for row in binding.operands:
        _require_source_matches(row, operands[row.label], where=binding.plan)


def _grids(
    binding: SittingBinding, operands: Mapping[str, object]
) -> tuple[bool, bool]:
    """Whether each group's operands share one native gate grid and pitch.

    Returns ``(corners_share_their_grids, emissions_share_the_reference_grid)``. The corners
    carry two grids (the fine pair at 0.6167 mm and the coarse pair at 2.96 mm); the E20
    members and the single emissions points must all share the reference window's own 1.85 mm
    grid, which is the equal-pitch check the prespec's emissions ladder requires.
    """

    def same(labels: Sequence[str]) -> bool:
        grids = [np.asarray(operands[label].depths, dtype=float) for label in labels]
        first = grids[0]
        return all(
            grid.shape == first.shape
            and float(np.abs(grid - first).max()) <= GATE_TOLERANCE_MM
            for grid in grids[1:]
        )

    fine = same([row.label for row in binding.corners if row.label in ("cc1", "cc2")])
    coarse = same([row.label for row in binding.corners if row.label in ("cc3", "cc4")])
    emissions_labels = [row.label for row in (*binding.e20, *binding.singles)]
    emissions = same(emissions_labels)
    if emissions:
        pitch = float(
            np.diff(np.asarray(operands[emissions_labels[0]].depths, float)).mean()
        )
        emissions = math.isclose(pitch, REFERENCE_PITCH_MM, rel_tol=GRID_RTOL)
    return (fine and coarse, emissions)


def _knot_grid(
    depths: Sequence[float], support_mm: tuple[float, float]
) -> tuple[float, ...]:
    """The knots a shared native grid contributes inside the common support."""
    low, high = support_mm
    return tuple(
        float(depth)
        for depth in depths
        if low - GATE_TOLERANCE_MM <= float(depth) <= high + GATE_TOLERANCE_MM
    )


def _valid_intervals(
    knots: Sequence[float], effects: Sequence[KnotEffect]
) -> list[tuple[float, int, int]]:
    """The ``(width, left, right)`` of every adjacent pair that both endpoints define.

    Only a pair of *consecutive* knots whose effect is defined at both ends is an interval
    of the integral. An undefined knot is never bridged: the intervals on either side of it
    stay separate, so the summed width is exactly the depth the effect was measured over.
    """
    intervals: list[tuple[float, int, int]] = []
    for left in range(len(effects) - 1):
        if effects[left].defined and effects[left + 1].defined:
            intervals.append(
                (float(knots[left + 1]) - float(knots[left]), left, left + 1)
            )
    return intervals


def _align(
    profile: MetricProfile, knots: Sequence[float], *, half_pitch_mm: float
) -> tuple[ReadAligned, ...]:
    """Read one metric profile at each knot's nearest native gate, or refuse that knot.

    No interpolation, no resampling: the knot's value is the value the recording measured at
    the gate nearest it, and both the native depth used and its signed offset are carried.
    A gate farther than half the knot pitch from its knot is reported as an unaligned read
    with the offset in its reason, never rounded to a neighbour.
    """
    grid = np.asarray(profile.depths_mm, dtype=float)
    reads: list[ReadAligned] = []
    for knot in knots:
        index = int(np.abs(grid - float(knot)).argmin())
        depth = float(grid[index])
        offset = depth - float(knot)
        gate = profile.gates[index]
        if abs(offset) > half_pitch_mm + GATE_TOLERANCE_MM:
            reads.append(
                ReadAligned(
                    label=str(profile.provenance.point_label),
                    gate_index=None,
                    depth_mm=None,
                    offset_mm=None,
                    value=None,
                    state=None,
                    reason=(
                        f"the nearest native gate to the knot at {float(knot):.4f} mm is "
                        f"{depth:.4f} mm, an offset of {abs(offset):.4f} mm, which exceeds "
                        f"half the knot pitch ({half_pitch_mm:.4f} mm); no interpolation is "
                        "performed, so this knot has no read"
                    ),
                )
            )
            continue
        reads.append(
            ReadAligned(
                label=str(profile.provenance.point_label),
                gate_index=gate.gate_index,
                depth_mm=depth,
                offset_mm=offset,
                value=gate.value,
                state=gate.state,
                reason=gate.reason,
            )
        )
    return tuple(reads)


def _operand_at(
    name: str,
    kind: str,
    members: tuple[str, ...],
    reads: Mapping[str, tuple[ReadAligned, ...]],
    knot_index: int,
) -> OperandRead:
    """One operand's read at one knot, reducing the E20 mean or refusing by member."""
    member_reads = tuple(reads[label][knot_index] for label in members)
    if kind == "recording":
        read = member_reads[0]
        if read.defined:
            state = EffectState.DEFINED
        elif not read.aligned:
            state = EffectState.UNDEFINED_ALIGNMENT
        else:
            state = EffectState.UNDEFINED_OPERAND
        return OperandRead(
            name=name,
            kind=kind,
            members=member_reads,
            value=read.value if state is EffectState.DEFINED else None,
            state=state,
            reason=read.reason,
        )
    # mean-of-four: exactly equal recording weights, or an undefined operand.
    unaligned = [read for read in member_reads if not read.aligned]
    if unaligned:
        read = unaligned[0]
        return OperandRead(
            name=name,
            kind=kind,
            members=member_reads,
            value=None,
            state=EffectState.UNDEFINED_ALIGNMENT,
            reason=(
                f"the equal-weight mean of {list(members)} is undefined at this knot: member "
                f"{read.label!r} has no aligned read ({read.reason})"
            ),
        )
    missing = [read for read in member_reads if not read.defined]
    if missing:
        read = missing[0]
        return OperandRead(
            name=name,
            kind=kind,
            members=member_reads,
            value=None,
            state=EffectState.UNDEFINED_OPERAND,
            reason=(
                f"the equal-weight mean of {list(members)} is undefined at this knot: member "
                f"{read.label!r} defines no value here ({read.reason})"
            ),
        )
    values = [read.value for read in member_reads]
    return OperandRead(
        name=name,
        kind=kind,
        members=member_reads,
        value=sum(values) / len(values),
        state=EffectState.DEFINED,
        reason=(
            f"the exactly equal-weight arithmetic mean of the {len(members)} distinct "
            f"common-reference runs {list(members)}, each measured once on its own recording"
        ),
    )


def _summarise(
    *,
    metric: MetricName,
    view: SparseView,
    units: str,
    knots: Sequence[float],
    effects: Sequence[KnotEffect],
) -> DepthSummary:
    """One effect profile's reduction, with its weighting rule and valid count.

    The signed average and the RMS are trapezoidal integrals over the *adjacent* knot pairs
    whose both endpoints define the effect (:data:`WEIGHTING_RULE`); an undefined knot is
    never bridged, so the covered depth may be shorter than the profile and no gap is
    counted as a zero. The equal-knot average stays beside them and the knot-wise sign
    fractions and extrema stay descriptive even where the integral has no width.
    """
    knot_array = np.asarray(knots, dtype=float)
    total = len(effects)
    span = float(knot_array[-1] - knot_array[0]) if knot_array.size >= 2 else 0.0
    defined = [(index, row) for index, row in enumerate(effects) if row.defined]
    intervals = _valid_intervals(knot_array, effects)
    covered = float(sum(width for width, _, _ in intervals))
    coverage = covered / span if span > 0.0 else None
    if not defined:
        return DepthSummary(
            metric=metric,
            view=view,
            units=units,
            knot_count=total,
            defined_count=0,
            undefined_count=total,
            weighting_rule=WEIGHTING_RULE,
            covered_depth_mm=covered,
            coverage_fraction=coverage,
            signed_depth_average=None,
            equal_knot_average=None,
            rms_magnitude=None,
            positive_fraction=None,
            negative_fraction=None,
            zero_fraction=None,
            min_value=None,
            min_depth_mm=None,
            max_value=None,
            max_depth_mm=None,
            max_abs_value=None,
            max_abs_depth_mm=None,
            statement=(
                f"no knot of this {metric.value}/{view.value} profile defines an effect, so "
                "there is nothing to summarise: an undefined effect is never averaged as a "
                "zero, and no interval carries a trapezoid term"
            ),
        )
    indices = np.asarray([index for index, _ in defined], dtype=int)
    values = np.asarray([row.value for _, row in defined], dtype=float)
    value_at = {int(index): float(row.value) for index, row in defined}
    signed: float | None = None
    rms: float | None = None
    if covered > 0.0:
        first_moment = sum(
            (value_at[left] + value_at[right]) / 2.0 * width
            for width, left, right in intervals
        )
        second_moment = sum(
            (value_at[left] ** 2 + value_at[right] ** 2) / 2.0 * width
            for width, left, right in intervals
        )
        signed = float(first_moment / covered)
        rms = float(math.sqrt(second_moment / covered))
    equal = float(np.mean(values))
    nonzero = values[values != 0.0]
    positive = (
        float(np.count_nonzero(nonzero > 0.0) / nonzero.size) if nonzero.size else None
    )
    negative = (
        float(np.count_nonzero(nonzero < 0.0) / nonzero.size) if nonzero.size else None
    )
    zero = float(np.count_nonzero(values == 0.0) / values.size)
    lowest = int(np.argmin(values))
    highest = int(np.argmax(values))
    # Ties on the largest absolute effect resolve to the shallower depth: the rows are in
    # increasing depth order and a later equal magnitude does not displace an earlier one.
    worst = 0
    for position in range(1, values.size):
        if abs(values[position]) > abs(values[worst]):
            worst = position
    depths = knot_array[indices]
    if covered > 0.0:
        coverage_text = (
            f"the valid adjacent intervals cover {covered:g} mm of the profile's "
            f"{span:g} mm ({coverage:.3f} of it)"
        )
    else:
        coverage_text = (
            "no adjacent pair of defined knots exists, so the integral has no width and "
            "the signed average and the RMS are not reported"
        )
    return DepthSummary(
        metric=metric,
        view=view,
        units=units,
        knot_count=total,
        defined_count=len(defined),
        undefined_count=total - len(defined),
        weighting_rule=WEIGHTING_RULE,
        covered_depth_mm=covered,
        coverage_fraction=coverage,
        signed_depth_average=signed,
        equal_knot_average=equal,
        rms_magnitude=rms,
        positive_fraction=positive,
        negative_fraction=negative,
        zero_fraction=zero,
        min_value=float(values[lowest]),
        min_depth_mm=float(depths[lowest]),
        max_value=float(values[highest]),
        max_depth_mm=float(depths[highest]),
        max_abs_value=float(abs(values[worst])),
        max_abs_depth_mm=float(depths[worst]),
        statement=(
            f"{len(defined)} of {total} knots define this {units} effect. Physical "
            "weighting: only adjacent knot pairs whose both endpoints define the effect "
            "contribute, and the signed depth average and the RMS are trapezoidal integrals "
            "over their summed width, so an undefined knot is never bridged or counted as a "
            f"zero; {coverage_text}. The equal-knot average is beside them. The RMS "
            "magnitude cannot cancel a sign-changing effect; the sign fractions are over "
            "defined nonzero knots. Neither a maximum nor a peak position is a robust "
            "effect when the profile is flat or lightly supported."
        ),
    )


def _shape(
    *,
    metric: MetricName,
    view: SparseView,
    effects: Sequence[KnotEffect],
) -> ProfileShape:
    """The high-vs-low profile correlation, or an explicit refusal with its reason."""
    rule = (
        "the Pearson correlation of the two compared profiles over the knots where both are "
        "defined, reported only when each is defined on at least "
        f"{MIN_SHAPE_KNOTS} common knots and neither is constant; a constant or "
        "lightly-supported profile has no correlation to report"
    )
    if not effects or len(effects[0].operands) != 2:
        return ProfileShape(
            metric=metric,
            view=view,
            correlation=None,
            defined_count=0,
            rule=rule,
            reason=(
                "the derived pitch x burst interaction has no pair of compared profiles: it "
                "is a difference of differences of four corner profiles, so no two-profile "
                "correlation is defined for it"
            ),
        )
    pairs = [
        (row.operands[0].value, row.operands[1].value) for row in effects if row.defined
    ]
    count = len(pairs)
    if count < MIN_SHAPE_KNOTS:
        return ProfileShape(
            metric=metric,
            view=view,
            correlation=None,
            defined_count=count,
            rule=rule,
            reason=(
                f"only {count} knot(s) define both compared profiles, fewer than the "
                f"{MIN_SHAPE_KNOTS} a correlation needs"
            ),
        )
    high = np.asarray([pair[0] for pair in pairs], dtype=float)
    low = np.asarray([pair[1] for pair in pairs], dtype=float)
    if _is_constant(high) or _is_constant(low):
        side = "high" if _is_constant(high) else "low"
        return ProfileShape(
            metric=metric,
            view=view,
            correlation=None,
            defined_count=count,
            rule=rule,
            reason=(
                f"the {side} profile is constant over the {count} common knots, so a "
                "correlation with a flat profile is undefined"
            ),
        )
    return ProfileShape(
        metric=metric,
        view=view,
        correlation=float(np.corrcoef(high, low)[0, 1]),
        defined_count=count,
        rule=rule,
        reason=(
            f"both profiles vary over the {count} common defined knots, so their Pearson "
            "correlation is reported; it describes shape only and is not a test"
        ),
    )


def _build_effects(
    *,
    name: str,
    expression: str,
    reduction: str,
    metric: MetricName,
    view: SparseView,
    units: str,
    operands: Sequence[object],
    coefficients: Sequence[float],
    reads: Mapping[str, tuple[ReadAligned, ...]],
    knots: Sequence[float],
    half_pitch_mm: float,
    support_mm: tuple[float, float],
    alignment_rule: str,
) -> DepthEffects:
    """One contrast (or the interaction) of one metric/view, aligned and reduced."""
    rows: list[KnotEffect] = []
    offsets: list[float] = []
    for index, knot in enumerate(knots):
        sides = tuple(
            _operand_at(operand.name, operand.kind, operand.members, reads, index)
            for operand in operands
        )
        for side in sides:
            for member in side.members:
                if member.aligned:
                    offsets.append(abs(member.offset_mm))  # type: ignore[arg-type]
        if any(side.state is EffectState.UNDEFINED_ALIGNMENT for side in sides):
            state = EffectState.UNDEFINED_ALIGNMENT
            value = None
            reason = next(
                side.reason
                for side in sides
                if side.state is EffectState.UNDEFINED_ALIGNMENT
            )
        elif any(side.state is EffectState.UNDEFINED_OPERAND for side in sides):
            state = EffectState.UNDEFINED_OPERAND
            value = None
            reason = next(
                side.reason
                for side in sides
                if side.state is EffectState.UNDEFINED_OPERAND
            )
        else:
            state = EffectState.DEFINED
            value = float(
                sum(
                    coefficient * side.value  # type: ignore[operator]
                    for coefficient, side in zip(coefficients, sides, strict=True)
                )
            )
            reason = (
                f"{expression}, with each operand measured once at its nearest native gate "
                f"to {float(knot):.4f} mm"
            )
        rows.append(
            KnotEffect(
                knot_index=index,
                depth_mm=float(knot),
                operands=sides,
                state=state,
                value=value,
                reason=reason,
            )
        )
    summary = _summarise(
        metric=metric, view=view, units=units, knots=knots, effects=rows
    )
    shape = _shape(metric=metric, view=view, effects=rows)
    return DepthEffects(
        name=name,
        expression=expression,
        reduction=reduction,
        metric=metric,
        view=view,
        units=units,
        operand_names=tuple(operand.name for operand in operands),
        coefficients=tuple(float(coefficient) for coefficient in coefficients),
        knots_mm=tuple(float(knot) for knot in knots),
        support_mm=(float(support_mm[0]), float(support_mm[1])),
        half_pitch_mm=float(half_pitch_mm),
        max_abs_offset_mm=float(max(offsets)) if offsets else 0.0,
        alignment_rule=alignment_rule,
        effects=tuple(rows),
        summary=summary,
        shape=shape,
    )


_ALIGNMENT_RULE = (
    "WP3 nearest-native alignment: the knots are the coarsest participating grid's own "
    "native supported gate depths inside the common support, and every other operand is read "
    "at its nearest NATIVE gate to each knot - no interpolation, no resampling, no fit. The "
    "native depth used and its signed offset are published per knot, and a knot whose "
    "nearest gate lies farther than half the knot pitch away carries no read rather than an "
    "interpolated one."
)


def _endpoint(
    metric: MetricName,
    view: SparseView,
    *,
    binding: SittingBinding,
    profile_for,
    corner_knots: Sequence[float],
    emissions_knots: Sequence[float],
) -> EndpointEffects:
    """The seven contrasts and the interaction of one ``(metric, view)`` endpoint."""
    units = _units(metric)

    def reads_on(knots: Sequence[float], half_pitch_mm: float, wanted: Iterable[str]):
        return {
            label: _align(profile_for(label), knots, half_pitch_mm=half_pitch_mm)
            for label in wanted
        }

    corner_half = float(np.diff(np.asarray(corner_knots, float)).mean()) / 2.0
    emissions_half = float(np.diff(np.asarray(emissions_knots, float)).mean()) / 2.0

    contrasts: list[DepthEffects] = []
    for contrast in binding.contrasts:
        labels_here = tuple(
            dict.fromkeys((*contrast.high.members, *contrast.low.members))
        )
        uses_corners = all(
            label in {row.label for row in binding.corners} for label in labels_here
        )
        knots = corner_knots if uses_corners else emissions_knots
        half = corner_half if uses_corners else emissions_half
        support = _participating_support([profile_for(label) for label in labels_here])
        effects = _build_effects(
            name=contrast.name,
            expression=f"M({contrast.high.name}) - M({contrast.low.name})",
            reduction=contrast.reduction,
            metric=metric,
            view=view,
            units=units,
            operands=(contrast.high, contrast.low),
            coefficients=(1.0, -1.0),
            reads=reads_on(knots, half, labels_here),
            knots=knots,
            half_pitch_mm=half,
            support_mm=support,
            alignment_rule=_ALIGNMENT_RULE,
        )
        contrasts.append(effects)

    corner_labels = tuple(row.label for row in binding.corners)
    interaction = _build_effects(
        name=INTERACTION_NAME,
        expression=INTERACTION_EXPRESSION,
        reduction=(
            "the difference of differences of the four corners at each common knot: the "
            "pitch contrast at burst 18 minus the pitch contrast at burst 4, equally the "
            "burst contrast at the coarse pitch minus the burst contrast at the fine pitch"
        ),
        metric=metric,
        view=view,
        units=units,
        operands=tuple(recording(label) for label in corner_labels),
        coefficients=(1.0, -1.0, -1.0, 1.0),
        reads=reads_on(corner_knots, corner_half, corner_labels),
        knots=corner_knots,
        half_pitch_mm=corner_half,
        support_mm=_participating_support(
            [profile_for(label) for label in corner_labels]
        ),
        alignment_rule=_ALIGNMENT_RULE,
    )
    return EndpointEffects(
        metric=metric,
        view=view,
        units=units,
        contrasts=tuple(contrasts),
        interaction=interaction,
    )


def _participating_support(profiles: Sequence[MetricProfile]) -> tuple[float, float]:
    """The intersection of the participating profiles' own depth extents."""
    low = max(
        profile.provenance.participating_depth_extent_mm[0] for profile in profiles
    )
    high = min(
        profile.provenance.participating_depth_extent_mm[1] for profile in profiles
    )
    if not high > low:
        raise SparseSa5EffectsError(
            f"the participating profiles' depth extents intersect in {low!r}..{high!r} mm, "
            "which is empty"
        )
    return (float(low), float(high))


# ── descriptive same-condition repeats, never a floor ──────────────────


def _repeat_members(members, knots, half_pitch_mm, get) -> tuple[RepeatMember, ...]:
    """One group's member scalars, each named with its own acquisition order."""
    rows: list[RepeatMember] = []
    for point in members:
        profile = get(point)
        reads = _align(profile, knots, half_pitch_mm=half_pitch_mm)
        defined = [read.value for read in reads if read.defined]
        if defined:
            rows.append(
                RepeatMember(
                    label=str(point.binding.point.label),
                    order=int(point.binding.order),
                    job=str(point.binding.job.job),
                    value=float(sum(defined) / len(defined)),
                    defined_count=len(defined),
                    state=MetricState.DEFINED,
                    reason=(
                        f"the unweighted mean of this recording's {len(defined)} defined "
                        f"knot(s) of the group's {len(knots)}"
                    ),
                )
            )
        else:
            rows.append(
                RepeatMember(
                    label=str(point.binding.point.label),
                    order=int(point.binding.order),
                    job=str(point.binding.job.job),
                    value=None,
                    defined_count=0,
                    state=None,
                    reason=(
                        "no gate of this recording defines the metric on the group's knots, "
                        "so it contributes no scalar"
                    ),
                )
            )
    return tuple(rows)


def _repeat_group(
    *,
    condition: str,
    members,
    metric: MetricName,
    view: SparseView,
    units: str,
    get,
) -> RepeatGroup:
    """One whole-condition repeat group, reduced to a descriptive spread."""
    first_profile = get(members[0])
    knots = tuple(float(depth) for depth in first_profile.depths_mm)
    half = (
        float(np.diff(np.asarray(knots, float)).mean()) / 2.0 if len(knots) > 1 else 0.0
    )
    rows = _repeat_members(members, knots, half, get)
    values = [row.value for row in rows if row.value is not None]
    spread = float(max(values) - min(values)) if len(values) >= 2 else None
    return RepeatGroup(
        condition=condition,
        members=rows,
        metric=metric,
        view=view,
        units=units,
        knot_count=len(knots),
        defined_members=len(values),
        min_value=float(min(values)) if values else None,
        max_value=float(max(values)) if values else None,
        spread=spread,
        rule=(
            "descriptive only: each member is measured once on its own recording, over that "
            "group's shared native supported knots, and the spread is the max-minus-min of "
            "the defined member scalars. The prespec promotes no repeat range to a floor and "
            "no gate, profile or recording here is a replicate, so this number is variation "
            "to see, never a threshold"
        ),
        statement=(
            f"{len(values)} of {len(rows)} member(s) define this {units} scalar on "
            f"{len(knots)} shared knot(s)"
            + (
                f"; the descriptive spread is {spread}"
                if spread is not None
                else "; fewer than two members define a scalar, so no spread is reported"
            )
        ),
    )


def _repeats_for(
    *,
    binding: SittingBinding,
    sequence: Sequence[object],
    operand_points: Mapping[str, object],
    metric: MetricName,
    view: SparseView,
    get,
) -> tuple[RepeatGroup, ...]:
    """Every whole-condition repeat group of one endpoint: the reference runs and anchors."""
    units = _units(metric)
    groups: list[RepeatGroup] = []
    reference = [operand_points[row.label] for row in binding.e20]
    groups.append(
        _repeat_group(
            condition=(
                "the common-reference condition: four distinct reference jobs (the four E20 "
                "runs), whose individual results stay visible as sequence context"
            ),
            members=sorted(reference, key=lambda point: int(point.binding.order)),
            metric=metric,
            view=view,
            units=units,
            get=get,
        )
    )
    by_job: dict[str, list[object]] = {}
    for point in sequence:
        if str(point.binding.point.label).startswith("ctrl-"):
            by_job.setdefault(str(point.binding.job.job), []).append(point)
    for job in sorted(by_job):
        members = sorted(by_job[job], key=lambda point: int(point.binding.order))
        if len(members) < 2:
            continue
        groups.append(
            _repeat_group(
                condition=(
                    f"the block-local anchor controls of job {job!r}: the same achieved "
                    "condition recorded before, inside and after the job's scientific row"
                ),
                members=members,
                metric=metric,
                view=view,
                units=units,
                get=get,
            )
        )
    return tuple(groups)


# ── measuring one sitting ──────────────────────────────────────────────


def _e20_is_the_equal_weight_mean(
    endpoints: Sequence[EndpointEffects], binding: SittingBinding
) -> bool:
    """Whether every defined E20 operand is the exactly equal-weight mean of ``cr1..cr4``."""
    labels = tuple(row.label for row in binding.e20)
    jobs = {row.job for row in binding.e20}
    if len(jobs) != 4:
        return False
    for endpoint in endpoints:
        for effect in endpoint.contrasts:
            for row in effect.effects:
                for side in row.operands:
                    if side.kind != "mean-of-four":
                        continue
                    if tuple(member.label for member in side.members) != labels:
                        return False
                    if side.defined:
                        values = [member.value for member in side.members]
                        if any(value is None for value in values):
                            return False
                        if side.value != sum(values) / len(values):
                            return False
    return True


def measure_binding(
    binding: SittingBinding,
    points: Iterable[object],
    *,
    pass_name: str = "",
    low_hz: float = DEFAULT_LOW_HZ,
    max_lag_s: float | None = None,
) -> SittingEffects:
    """Measure one bound sitting's effects from its decoded recordings, or refuse by name.

    Args:
        binding: the frozen operand/contrast binding of one sitting
            (:func:`~udv_echo_process.analysis.sparse_sa5_bindings.bind_sitting`).
        points: the sitting's decoded recordings (any objects carrying ``values``,
            ``time_s``, ``depths``, ``config``, ``source_sha256`` and a ``binding`` with
            ``job.job``/``point.label``/``order`` — a :class:`DecodedPoint` or a test
            stand-in with the same surface).
        pass_name: the label carried on the result.
        low_hz: the Φ band edge in Hz, passed to the Φ metric slice.
        max_lag_s: the declared recurrence lag domain in seconds, applied to the recurrence
            endpoints; ``None`` uses the estimator's own default.

    Returns:
        :class:`SittingEffects` — every declared ``(metric, view)`` endpoint's seven
        contrasts and the derived interaction, plus the descriptive repeat groups.

    Raises:
        SparseSa5EffectsError: for a missing, duplicated or mismatched decoded operand, a
            digest or achieved setting that is not the bound one, a group that does not
            share its grid or pitch, or a recording that does not retain the declared
            window.
    """
    sequence = tuple(points)
    operand_points = _operand_points(binding, sequence)
    _require_decoded_matches(binding, operand_points)
    corners_ok, emissions_ok = _grids(binding, operand_points)

    support = binding.support_mm
    window_s = binding.window_s
    primary_views: dict[str, WindowView] = {}
    full_views: dict[str, WindowView] = {}

    def views_of(point: object) -> tuple[WindowView, WindowView]:
        key = str(point.relative_path)  # type: ignore[attr-defined]
        if key not in primary_views:
            primary_views[key] = primary_view(
                point, window_s=window_s, support_mm=support
            )
            full_views[key] = full_record_view(point, support_mm=support)
        return primary_views[key], full_views[key]

    for point in operand_points.values():
        views_of(point)
    for point in sequence:
        if str(point.binding.point.label).startswith("ctrl-"):  # type: ignore[attr-defined]
            views_of(point)

    cache: dict[tuple[str, str, str], MetricProfile] = {}

    def profile_of(
        point: object, metric: MetricName, view: SparseView
    ) -> MetricProfile:
        key = (str(point.relative_path), metric.value, view.value)  # type: ignore[attr-defined]
        if key not in cache:
            primary, full = views_of(point)
            window = primary if view is SparseView.PRIMARY else full
            cache[key] = read_metric_profile(
                window,
                metric=metric,
                low_hz=low_hz,
                max_lag_s=max_lag_s if metric in RECURRENCE_METRICS else None,
            )
        return cache[key]

    corner_knots = binding.knot_depths_mm
    emissions_knots = _knot_grid(binding.emissions_depths_mm, support)
    if len(emissions_knots) < 2:
        raise SparseSa5EffectsError(
            f"{binding.plan}: the emissions ladder's reference grid contributes "
            f"{len(emissions_knots)} knot(s) inside the common support; an alignment needs two"
        )

    endpoints: list[EndpointEffects] = []
    for metric, view in ENDPOINTS:

        def profile_for(label: str, _metric=metric, _view=view) -> MetricProfile:
            return profile_of(operand_points[label], _metric, _view)

        endpoints.append(
            _endpoint(
                metric,
                view,
                binding=binding,
                profile_for=profile_for,
                corner_knots=corner_knots,
                emissions_knots=emissions_knots,
            )
        )

    repeats: list[RepeatGroup] = []
    for metric, view in ENDPOINTS:

        def get(point: object, _metric=metric, _view=view) -> MetricProfile:
            return profile_of(point, _metric, _view)

        repeats.extend(
            _repeats_for(
                binding=binding,
                sequence=sequence,
                operand_points=operand_points,
                metric=metric,
                view=view,
                get=get,
            )
        )

    operand_labels = tuple(row.label for row in binding.operands)
    checks = {
        "operands_bound_to_decoded_sources": True,
        "inventory_digest_matches_every_operand": True,
        "achieved_settings_match_every_operand": True,
        "corners_share_their_own_grids": bool(corners_ok),
        "emissions_operands_share_the_reference_pitch_and_grid": bool(emissions_ok),
        "every_endpoint_has_one_effect_per_knot": all(
            len(effect.effects) == len(effect.knots_mm)
            for endpoint in endpoints
            for effect in (*endpoint.contrasts, endpoint.interaction)
        ),
        "e20_is_the_equal_weight_mean_of_the_four_runs": _e20_is_the_equal_weight_mean(
            endpoints, binding
        ),
        "no_block_local_anchor_enters_an_operand": all(
            not label.startswith("ctrl-") for label in operand_labels
        ),
        "repeats_name_their_members_and_orders": all(
            len(group.members) >= 2
            and all(member.order >= 0 for member in group.members)
            for group in repeats
        ),
        "window_is_the_declared_primary": math.isclose(
            window_s, DESIGNED_WINDOW_S, rel_tol=0.0, abs_tol=1e-12
        ),
        "no_cross_sitting_arithmetic": True,
    }
    return SittingEffects(
        pass_name=pass_name or binding.plan,
        plan=binding.plan,
        plan_fingerprint=binding.plan_fingerprint,
        window_s=window_s,
        window_revolutions=binding.window_revolutions,
        support_mm=(float(support[0]), float(support[1])),
        method=METHOD,
        contrast_source=CONTRAST_SOURCE,
        endpoints=tuple(endpoints),
        repeats=tuple(repeats),
        checks=checks,
    )


def measure_sitting(
    pass_ref: PassRef,
    *,
    dataset_root: Path | None = None,
    plan_path: Path | None = None,
    report_dir: Path | None = None,
    low_hz: float = DEFAULT_LOW_HZ,
    max_lag_s: float | None = None,
) -> SittingEffects:
    """Measure one committed sitting's within-sitting effects, typed, or refuse by name.

    The sitting's recordings are decoded through the shared loader
    (:func:`~udv_echo_process.analysis._sparse_pass.decode_pass`), its committed per-pass
    inventory is bound to this sitting's own plan, and the two are reconciled operand by
    operand before any effect is measured.

    Args:
        pass_ref: one committed pass (:class:`PassRef`).
        dataset_root: the dataset root, or the ref's own.
        plan_path: the run-plan file, or the ref's own.
        report_dir: the directory holding this pass's ``points.csv``, or the ref's own
            ``report_dir``.
        low_hz: the Φ band edge in Hz.
        max_lag_s: the declared recurrence lag domain in seconds.

    Returns:
        :class:`SittingEffects` for **this sitting alone**.

    Raises:
        SparseSa5EffectsError: for a sitting with no inventory directory, a pass the shared
            loader refuses, or any condition :func:`measure_binding` refuses.
    """
    root = Path(dataset_root) if dataset_root is not None else Path(pass_ref.root)
    plan = Path(plan_path) if plan_path is not None else Path(pass_ref.plan_path)
    decoded: PassDecoding = decode_pass(root, plan_path=plan, plan_name=pass_ref.name)
    directory = Path(report_dir) if report_dir is not None else pass_ref.report_dir
    if directory is None:
        raise SparseSa5EffectsError(
            f"{pass_ref.name}: this pass has no per-pass inventory directory, so no SA5 "
            "effect can be bound from it"
        )
    rows = _read_inventory(directory / "points.csv")
    binding = bind_sitting(rows, plan_name=pass_ref.name, support_mm=decoded.support_mm)
    return measure_binding(
        binding,
        decoded.points,
        pass_name=pass_ref.name,
        low_hz=low_hz,
        max_lag_s=max_lag_s,
    )
