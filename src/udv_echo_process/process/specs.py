"""Discriminated transform-spec unions (plan §7.2 and §7.3, phase 5).

Phase 4 adds the filter union. Phase 5 adds the interpolation union in this
module. Each branch declares only the fields its method reads, so an
irrelevant parameter (``weight`` on a median spec, ``order`` on a linear spec)
is an ``extra="forbid"`` error rather than a silently ignored key (plan §14).

``FilterSpec`` and ``InterpSpec`` are *discriminated* unions: pydantic resolves
the branch from the ``method`` literal, so each union has exactly the
documented branches and no others. Because the alias is not itself callable,
callers construct a branch class directly
(``MedianFilterSpec(window=5, max_gap_s=0.04)``, ``LinearInterpSpec(...)``) and
readers parse a payload with ``TypeAdapter(FilterSpec)``.

The interpolation branches declare the three shared fields
(``extrapolation``, ``max_bracket_span_s``, ``long_gap``) *explicitly* on every
branch rather than in a bundled all-method parameter bag (the legacy
``InterpParams``/``InterpMethod`` pair is gone, plan §14). ``extrapolation``
values are ``"error" | "missing" | "nearest"`` — the legacy ``"nan"`` spelling
is ``"missing"`` now that support, not a NaN policy, controls validity.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ValueModel

__all__ = [
    "BsplineInterpSpec",
    "CubicInterpSpec",
    "ExtrapolationPolicy",
    "FilterSpec",
    "InterpSpec",
    "LinearInterpSpec",
    "LongGapPolicy",
    "MeanFilterSpec",
    "MedianFilterSpec",
    "MonotoneInterpSpec",
    "SavgolFilterSpec",
    "TvFilterSpec",
]

#: Upper bound of every method's uniform-cadence relative tolerance (plan §7.2).
_UNIFORM_RTOL_MAX: float = 0.05

#: Default uniform-cadence relative tolerance: accepts the 3% timebase jitter.
_UNIFORM_RTOL_DEFAULT: float = 0.01

#: What sampling outside a gate's overall valid domain does (plan §7.3).
ExtrapolationPolicy = Literal["error", "missing", "nearest"]

#: What a bracket wider than ``max_bracket_span_s`` does (plan §7.3).
LongGapPolicy = Literal["missing", "error"]


def _require_odd_window(value: int, info: ValidationInfo) -> int:
    """Reject an even ``window``: every windowed kernel needs a centre sample."""
    if value % 2 == 0:
        raise ValueError(
            f"{info.field_name} must be odd, got {value} "
            "(a windowed kernel needs a centre sample)"
        )
    return value


class MedianFilterSpec(ValueModel):
    """Rolling-median (outlier-robust) filter parameters.

    ``window`` is the odd boxcar width in samples; ``max_gap_s`` is the largest
    time gap a window may span (a larger gap starts a new segment).
    """

    method: Literal["median"] = "median"
    window: int = Field(ge=1)
    max_gap_s: float = Field(gt=0)

    @field_validator("window")
    @classmethod
    def _check_window(cls, value: int, info: ValidationInfo) -> int:
        return _require_odd_window(value, info)


class MeanFilterSpec(ValueModel):
    """Boxcar-average filter parameters (``window`` may be even)."""

    method: Literal["mean"] = "mean"
    window: int = Field(ge=1)
    max_gap_s: float = Field(gt=0)


class SavgolFilterSpec(ValueModel):
    """Savitzky-Golay (polynomial) filter parameters.

    ``window`` is odd and at least 3, ``polyorder`` is below ``window``, and
    ``uniform_rtol`` is the relative tolerance of the method's true-uniform-
    cadence requirement.
    """

    method: Literal["savgol"] = "savgol"
    window: int = Field(ge=3)
    polyorder: int = Field(ge=0)
    max_gap_s: float = Field(gt=0)
    uniform_rtol: float = Field(
        default=_UNIFORM_RTOL_DEFAULT, ge=0.0, le=_UNIFORM_RTOL_MAX
    )

    @field_validator("window")
    @classmethod
    def _check_window(cls, value: int, info: ValidationInfo) -> int:
        return _require_odd_window(value, info)

    @model_validator(mode="after")
    def _check_polyorder(self) -> SavgolFilterSpec:
        if self.polyorder >= self.window:
            raise ValueError(
                f"polyorder ({self.polyorder}) must be below window ({self.window})"
            )
        return self


class TvFilterSpec(ValueModel):
    """Total-variation (ROF) denoising parameters.

    ``weight`` is the ROF lambda (larger smooths more), ``iterations`` caps the
    Chambolle solver, and ``uniform_rtol`` is the true-uniform-cadence
    tolerance.
    """

    method: Literal["tv"] = "tv"
    weight: float = Field(gt=0)
    iterations: int = Field(ge=1)
    max_gap_s: float = Field(gt=0)
    uniform_rtol: float = Field(
        default=_UNIFORM_RTOL_DEFAULT, ge=0.0, le=_UNIFORM_RTOL_MAX
    )


#: One unambiguous filter spec: a discriminated union on ``method``.
FilterSpec = Annotated[
    MedianFilterSpec | MeanFilterSpec | SavgolFilterSpec | TvFilterSpec,
    Field(discriminator="method"),
]


# ── interpolation specs (plan §7.3) ──────────────────────────────────────


class LinearInterpSpec(ValueModel):
    """Piecewise-linear interpolation parameters (plan §7.3).

    Linear interpolation cannot overshoot a bracket and needs no uniform
    cadence, so it is the honest default across multiplexed gaps.
    ``extrapolation`` is the outside-the-valid-domain policy,
    ``max_bracket_span_s`` the widest source span one bracket may bridge, and
    ``long_gap`` what an over-long bracket does.
    """

    method: Literal["linear"] = "linear"
    extrapolation: ExtrapolationPolicy
    max_bracket_span_s: float = Field(gt=0)
    long_gap: LongGapPolicy


class MonotoneInterpSpec(ValueModel):
    """Shape-preserving (PCHIP) interpolation parameters (plan §7.3).

    Like ``linear`` it has no uniform-cadence requirement, but it is C1
    smooth while still being monotone between knots (no local overshoot).
    """

    method: Literal["monotone"] = "monotone"
    extrapolation: ExtrapolationPolicy
    max_bracket_span_s: float = Field(gt=0)
    long_gap: LongGapPolicy


class CubicInterpSpec(ValueModel):
    """Not-a-knot cubic-spline interpolation parameters (plan §7.3).

    Cubic splines may overshoot between knots, so every sampled source segment
    must be truly uniform under the shared SAVGOL/TV all-interval rule
    (``uniform_rtol`` is that tolerance).
    """

    method: Literal["cubic"] = "cubic"
    extrapolation: ExtrapolationPolicy
    max_bracket_span_s: float = Field(gt=0)
    long_gap: LongGapPolicy
    uniform_rtol: float = Field(
        default=_UNIFORM_RTOL_DEFAULT, ge=0.0, le=_UNIFORM_RTOL_MAX
    )


class BsplineInterpSpec(ValueModel):
    """Interpolating B-spline parameters (plan §7.3).

    ``order`` is the spline degree (1..5); an order-``k`` spline needs at least
    ``k + 1`` samples per sampled segment, so short segments raise a capacity
    error at apply time. Sampled segments must be truly uniform
    (``uniform_rtol``), like ``cubic``.
    """

    method: Literal["bspline"] = "bspline"
    extrapolation: ExtrapolationPolicy
    max_bracket_span_s: float = Field(gt=0)
    long_gap: LongGapPolicy
    order: int = Field(ge=1, le=5)
    uniform_rtol: float = Field(
        default=_UNIFORM_RTOL_DEFAULT, ge=0.0, le=_UNIFORM_RTOL_MAX
    )


#: One unambiguous interpolation spec: a discriminated union on ``method``.
InterpSpec = Annotated[
    LinearInterpSpec | MonotoneInterpSpec | CubicInterpSpec | BsplineInterpSpec,
    Field(discriminator="method"),
]
