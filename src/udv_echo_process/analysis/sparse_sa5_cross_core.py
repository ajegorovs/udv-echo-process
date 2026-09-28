"""SA5 cross-sitting comparison core — the pure §5 kernel over two frozen profiles.

This module is the **arithmetic** of the between-sitting comparison and nothing else. A caller
hands it the two sides' already-decoded, digest-bound effect arrays (:class:`EffectArrays`) and
the native comparison depths, and receives the typed §5 records: the per-knot difference rows
with the common-defined mask ``D`` over identical native knots, and then every prespecified
diagnostic — ``L``/``D̄``/``RMS(D)``, the sign composition and ``A_sign``, the Pearson shape
correlation, each side's numerical maximum and the localized-peak displacement/coincidence —
each defined or explicitly typed-empty (``docs/dop3000/sa5-cross-sitting-agreement-prespec.md``
§§3–5).

It is deliberately independent of the rest of the slice. It reads no file, verifies no digest,
matches no key, knows no sitting, plan, operand or repeat group, and imports neither the
input/binding layer (:mod:`sparse_sa5_cross_input`) nor the context/model layer
(:mod:`sparse_sa5_cross_models`). §6 repeat context is attached **afterward**, outside this
module, and can therefore have no effect on anything computed here: the same two array sides
always yield the same §5 records.

:class:`KnotComparison` and :class:`Diagnostics` are the core's own typed records, and their
validators are the typed-state contract — an empty reduction cannot be emitted as ``0``, an
undefined knot cannot carry a value, and peak displacement/coincidence exist only when both
sides are localized.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis.sparse_sa5_effects import (
    CONSTANT_TOLERANCE_REL,
    MIN_SHAPE_KNOTS,
)
from udv_echo_process.analysis.sparse_sa5_npz import EFFECT_STATE_CODES, EffectArrays
from udv_echo_process.models.base import ValueModel

__all__ = [
    "GATE_TOLERANCE_MM",
    "REASON_CONSTANT_PROFILE",
    "REASON_INSUFFICIENT_DEPTH",
    "Diagnostics",
    "KnotComparison",
    "comparison_diagnostics",
    "is_constant",
    "knot_comparison",
    "native_knots_match",
    "peak",
]

#: Two comparison knots are the *same* knot iff their depths agree within this (§3).
GATE_TOLERANCE_MM = 1e-6

#: The core's own typed-empty reasons for a numerical maximum that is not a localized peak.
REASON_INSUFFICIENT_DEPTH = "insufficient-depth-support"
REASON_CONSTANT_PROFILE = "constant-absolute-effect-profile"


def is_constant(values: np.ndarray) -> bool:
    """The engine's constancy rule, restated (within-sitting prespec §50)."""
    if values.size < 2:
        return True
    return float(np.ptp(values)) <= CONSTANT_TOLERANCE_REL * max(
        1.0, float(np.max(np.abs(values)))
    )


def native_knots_match(
    left: EffectArrays, right: EffectArrays, tolerance: float = GATE_TOLERANCE_MM
) -> bool:
    """Whether the two sides publish the same native knot set, within tolerance (§3).

    The comparison is made on the frozen native depths only: no resampling, no nearest-gate
    substitution and no interpolation, so a mismatch is reported as a grid mismatch and never
    silently narrowed.
    """
    if left.knots_mm.shape != right.knots_mm.shape:
        return False
    left_knots = np.asarray(left.knots_mm, dtype=float)
    right_knots = np.asarray(right.knots_mm, dtype=float)
    return float(np.abs(left_knots - right_knots).max(initial=0.0)) <= tolerance


def peak(values: np.ndarray, depths: np.ndarray) -> tuple[float, float]:
    """The largest absolute value and the shallower depth attaining it (§5)."""
    best = 0
    for index in range(1, int(values.size)):
        if abs(values[index]) > abs(values[best]):
            best = index
    return float(abs(values[best])), float(depths[best])


class KnotComparison(ValueModel):
    """One comparison knot: the two oriented effects, their difference and both states (§4)."""

    knot_index: int
    depth_mm: float
    defined: bool
    value1: float | None
    value2: float | None
    difference: float | None
    state1_code: int
    state1_text: str
    state2_code: int
    state2_text: str

    @model_validator(mode="after")
    def _check_the_knot_is_its_state(self) -> KnotComparison:
        if self.knot_index < 0 or not math.isfinite(self.depth_mm):
            raise ValueError(
                "a comparison knot carries a nonnegative index and finite depth"
            )
        if not self.defined:
            if any(v is not None for v in (self.value1, self.value2, self.difference)):
                raise ValueError(
                    "an undefined comparison knot carries no value: a number here would read as "
                    "a measurement never taken"
                )
            return self
        if self.value1 is None or self.value2 is None or self.difference is None:
            raise ValueError("a defined comparison knot carries both effects and D")
        if self.difference != self.value2 - self.value1:
            raise ValueError("D is E2 - E1 at every defined comparison knot")
        return self


def knot_comparison(
    knots: np.ndarray, left: EffectArrays, right: EffectArrays
) -> tuple[tuple[KnotComparison, ...], np.ndarray]:
    """The per-knot comparison rows and the boolean common-defined mask ``D`` over ``knots``."""
    definition = left.defined.astype(bool) & right.defined.astype(bool)
    rows: list[KnotComparison] = []
    for index in range(int(knots.size)):
        defined = bool(definition[index])
        code1, code2 = int(left.state[index]), int(right.state[index])
        value1 = float(left.effect[index]) if defined else None
        value2 = float(right.effect[index]) if defined else None
        rows.append(
            KnotComparison(
                knot_index=index,
                depth_mm=float(knots[index]),
                defined=defined,
                value1=value1,
                value2=value2,
                difference=(value2 - value1) if defined else None,
                state1_code=code1,
                state1_text=EFFECT_STATE_CODES[code1],
                state2_code=code2,
                state2_text=EFFECT_STATE_CODES[code2],
            )
        )
    return tuple(rows), definition


class Diagnostics(ValueModel):
    """The §5 comparison diagnostics over the common-defined knots, each typed-or-empty.

    Coverage: the comparison's own ``L``, ``|D|``, ``|S|`` and span. Reductions
    (``signed_depth_average``/``rms_difference``) are empty exactly when ``L = 0``; ``A_sign``
    is empty exactly when ``|S| = 0``; a numerical maximum is defined whenever ``|D| ≥ 1``, but
    a *localized peak* (and the displacement/coincidence that follow) only when both sides'
    absolute profiles are nonconstant over ``|D| ≥ 2`` knots.
    """

    span_mm: float
    covered_depth_mm: float
    coverage_fraction: float | None
    defined_count: int
    sign_count: int
    signed_depth_average: float | None
    rms_difference: float | None
    positive_count: int
    negative_count: int
    zero_count: int
    sign_agreement: float | None
    zero1_count: int
    zero2_count: int
    shape_correlation: float | None
    shape_defined_count: int
    shape_reason: str
    peak1_value: float | None
    peak1_depth: float | None
    peak2_value: float | None
    peak2_depth: float | None
    peak_localized1: bool
    peak_localized2: bool
    peak_reason1: str
    peak_reason2: str
    peak_displacement: float | None
    peaks_coincide: bool | None
    peak_displacement_reason: str

    @model_validator(mode="after")
    def _check_every_diagnostic_is_its_state(self) -> Diagnostics:
        if self.defined_count < 0 or self.sign_count < 0:
            raise ValueError("the common-defined and sign counts are nonnegative")
        integrated = self.covered_depth_mm > 0.0
        if integrated != (self.signed_depth_average is not None) or integrated != (
            self.rms_difference is not None
        ):
            raise ValueError(
                "D̄ and RMS(D) are reported exactly when L > 0, never 0 by default"
            )
        if (self.sign_count > 0) != (self.sign_agreement is not None):
            raise ValueError(
                "A_sign is reported exactly when |S| > 0, never 0 or 1 by default"
            )
        if self.defined_count == 0 and any(
            v is not None
            for v in (
                self.signed_depth_average,
                self.rms_difference,
                self.peak1_value,
                self.peak2_value,
            )
        ):
            raise ValueError(
                "an empty common domain carries no reduction and no maximum"
            )
        both = self.peak_localized1 and self.peak_localized2
        if both != (self.peak_displacement is not None) or both != (
            self.peaks_coincide is not None
        ):
            raise ValueError(
                "peak displacement and coincidence need both sides localized"
            )
        return self


def comparison_diagnostics(
    rows: Sequence[KnotComparison],
    definition: np.ndarray,
    left: EffectArrays,
    right: EffectArrays,
) -> Diagnostics:
    """Every §5 diagnostic, each defined or explicitly typed-empty."""
    knots = np.asarray([row.depth_mm for row in rows], dtype=float)
    effect1 = np.asarray(left.effect, dtype=float)
    effect2 = np.asarray(right.effect, dtype=float)
    difference = effect2 - effect1
    indices = np.flatnonzero(definition)
    count = int(indices.size)
    span = float(knots[-1] - knots[0]) if knots.size >= 2 else 0.0

    intervals = [
        (float(knots[k + 1] - knots[k]), k, k + 1)
        for k in range(int(knots.size) - 1)
        if definition[k] and definition[k + 1]
    ]
    covered = float(sum(width for width, _, _ in intervals))
    coverage = covered / span if span > 0.0 else None
    signed = rms = None
    if covered > 0.0:
        first = sum((difference[a] + difference[b]) / 2.0 * w for w, a, b in intervals)
        second = sum(
            (difference[a] ** 2 + difference[b] ** 2) / 2.0 * w for w, a, b in intervals
        )
        signed, rms = float(first / covered), float(math.sqrt(second / covered))

    gaps = difference[indices]
    positive = int(np.count_nonzero(gaps > 0.0))
    negative = int(np.count_nonzero(gaps < 0.0))
    zero = int(np.count_nonzero(gaps == 0.0))
    zero1 = int(np.count_nonzero(effect1[indices] == 0.0))
    zero2 = int(np.count_nonzero(effect2[indices] == 0.0))

    sign = [k for k in indices if effect2[k] != 0.0 and effect1[k] != 0.0]
    sign_count = len(sign)
    agreement = None
    if sign_count:
        agree = sum(1 for k in sign if (effect2[k] > 0.0) == (effect1[k] > 0.0))
        agreement = float(agree / sign_count)

    values1, values2 = effect1[indices], effect2[indices]
    shape = None
    if count < MIN_SHAPE_KNOTS:
        shape_reason = (
            f"only {count} knot(s) define both effects, fewer than the {MIN_SHAPE_KNOTS} a "
            "correlation needs"
        )
    elif is_constant(values1) or is_constant(values2):
        who = "live-1" if is_constant(values1) else "live-2"
        shape_reason = f"the {who} profile is constant over the common defined knots"
    else:
        shape, shape_reason = float(np.corrcoef(values2, values1)[0, 1]), ""

    depths = knots[indices]
    peak1, peak2 = peak(values1, depths), peak(values2, depths)
    localized1 = count >= 2 and not is_constant(np.abs(values1))
    localized2 = count >= 2 and not is_constant(np.abs(values2))

    def why(localized: bool) -> str:
        if localized:
            return ""
        return REASON_INSUFFICIENT_DEPTH if count < 2 else REASON_CONSTANT_PROFILE

    both = localized1 and localized2
    displacement, coincide, displacement_reason = None, None, ""
    if both:
        displacement = float(peak2[1] - peak1[1])
        coincide = bool(abs(displacement) <= GATE_TOLERANCE_MM)
    else:
        displacement_reason = why(False)
    return Diagnostics(
        span_mm=span,
        covered_depth_mm=covered,
        coverage_fraction=coverage,
        defined_count=count,
        sign_count=sign_count,
        signed_depth_average=signed,
        rms_difference=rms,
        positive_count=positive,
        negative_count=negative,
        zero_count=zero,
        sign_agreement=agreement,
        zero1_count=zero1,
        zero2_count=zero2,
        shape_correlation=shape,
        shape_defined_count=count,
        shape_reason=shape_reason,
        peak1_value=None if peak1 is None else peak1[0],
        peak1_depth=None if peak1 is None else peak1[1],
        peak2_value=None if peak2 is None else peak2[0],
        peak2_depth=None if peak2 is None else peak2[1],
        peak_localized1=localized1,
        peak_localized2=localized2,
        peak_reason1=why(localized1),
        peak_reason2=why(localized2),
        peak_displacement=displacement,
        peaks_coincide=coincide,
        peak_displacement_reason=displacement_reason,
    )
