"""Discriminated transform-spec unions (plan §7.2, extended in phase 5).

Phase 4 adds the filter union. Phase 5 adds the interpolation unions in this
module. Each branch declares only the fields its method reads, so an
irrelevant parameter (``weight`` on a median spec) is an ``extra="forbid"``
error rather than a silently ignored key (plan §14).

``FilterSpec`` is a *discriminated* union: pydantic resolves the branch from
the ``method`` literal, so the union has exactly the four documented branches
and no others. Because the alias is not itself callable, callers construct a
branch class directly (``MedianFilterSpec(window=5, max_gap_s=0.04)``) and
readers parse a payload with ``TypeAdapter(FilterSpec)``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ValueModel

__all__ = [
    "FilterSpec",
    "MeanFilterSpec",
    "MedianFilterSpec",
    "SavgolFilterSpec",
    "TvFilterSpec",
]

#: Upper bound of every method's uniform-cadence relative tolerance (plan §7.2).
_UNIFORM_RTOL_MAX: float = 0.05

#: Default uniform-cadence relative tolerance: accepts the 3% timebase jitter.
_UNIFORM_RTOL_DEFAULT: float = 0.01


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
