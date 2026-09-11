"""Per-cell support and quality flags for UDV signal payloads (plan §6.3).

Three axes that must never be collapsed:

- :class:`SupportKind` (uint8) — whether/where acquisition support exists;
- ``valid`` (bool) — whether the stored numeric value is usable *right now*;
- :class:`QualityFlag` (uint32) — why a value is unusable or what a transform
  did to it.

Unknown support values and undeclared quality bits are rejected at
construction, reporting the offending integer and its first index (§11).
"""

from __future__ import annotations

from enum import IntEnum, IntFlag

import numpy as np
from pydantic import model_validator

from udv_echo_process.models.base import ArrayModel, array_field


class SupportKind(IntEnum):
    """How a payload cell is backed by acquisition support (uint8 on disk)."""

    MISSING = 0
    OBSERVED = 1
    INTERPOLATED = 2
    EXTRAPOLATED = 3


class QualityFlag(IntFlag):
    """Accumulated support/quality bits (uint32 bit mask, plan §6.3).

    Flags accumulate by bitwise OR and are never cleared by a transform.
    """

    NONE = 0
    DEVICE_INVALID = 1 << 0
    LOW_SIGNAL = 1 << 1
    SATURATED = 1 << 2
    OUT_OF_RANGE = 1 << 3
    TIMESTAMP_ANOMALY = 1 << 4
    ALIASED = 1 << 5
    OUTLIER = 1 << 6
    GAP_TOO_LONG = 1 << 7
    FILTERED = 1 << 8
    EDGE_AFFECTED = 1 << 9
    EXTRAPOLATED = 1 << 10
    REINTERPOLATED = 1 << 11
    TIME_ALIGNED = 1 << 12
    ALIGNMENT_UNCERTAIN = 1 << 13


#: Every declared bit OR-ed together. The members are distinct single bits, so
#: a plain sum is the mask. Quality integers with any bit outside it are
#: rejected at construction.
DECLARED_QUALITY_MASK: int = sum(int(v) for v in QualityFlag.__members__.values())

#: ``quality & _UNDECLARED_MASK`` is nonzero for any undeclared bit.
_UNDECLARED_MASK = ~np.uint32(DECLARED_QUALITY_MASK)

#: Reasons that may explain an invalid ``OBSERVED`` cell (plan §6.3).
ACQUISITION_QUALITY_REASONS: QualityFlag = (
    QualityFlag.DEVICE_INVALID
    | QualityFlag.LOW_SIGNAL
    | QualityFlag.SATURATED
    | QualityFlag.OUT_OF_RANGE
    | QualityFlag.ALIASED
    | QualityFlag.OUTLIER
)

#: 256-entry lookup: True for every declared ``SupportKind`` value.
_VALID_KIND = np.zeros(256, dtype=bool)
_VALID_KIND[0 : len(SupportKind)] = True


def _first_cell(mask: np.ndarray) -> tuple[int, int]:
    """Return the ``(time, gate)`` coordinate of the first ``True`` in ``mask``."""
    flat = int(np.flatnonzero(mask.ravel())[0])
    return int(flat // mask.shape[1]), int(flat % mask.shape[1])


def _cells(count: int) -> str:
    return f"{count} cell" if count == 1 else f"{count} cells"


def _relation_error(reason: str, mask: np.ndarray) -> str:
    """Format a support-relation violation with count and first ``(t, g)``."""
    time_i, gate_i = _first_cell(mask)
    return (
        f"{reason}: {_cells(int(mask.sum()))}, first at (time={time_i}, gate={gate_i})"
    )


class SampleSupport(ArrayModel):
    """Per-cell support kind, current-validity flag and accumulated quality.

    All three arrays share one shape ``(T, G)``. ``MISSING`` is always invalid;
    ``INTERPOLATED``/``EXTRAPOLATED`` are always valid; an invalid ``OBSERVED``
    cell must carry an acquisition-quality reason; ``EXTRAPOLATED`` support
    always includes :attr:`QualityFlag.EXTRAPOLATED`.
    """

    kind: array_field(np.uint8, rank=2)
    valid: array_field(np.bool_, rank=2)
    quality: array_field(np.uint32, rank=2)

    @model_validator(mode="after")
    def _check_invariants(self) -> SampleSupport:
        if not (self.kind.shape == self.valid.shape == self.quality.shape):
            raise ValueError(
                "support component shapes must be identical, got "
                f"kind={self.kind.shape}, valid={self.valid.shape}, "
                f"quality={self.quality.shape}"
            )

        unknown = ~_VALID_KIND[self.kind]
        if unknown.any():
            time_i, gate_i = _first_cell(unknown)
            flat = time_i * self.kind.shape[1] + gate_i
            raise ValueError(
                f"unknown support value {int(self.kind[time_i, gate_i])} at "
                f"index {flat} (time={time_i}, gate={gate_i}); declared "
                "SupportKind values are 0..3"
            )

        undeclared = (self.quality & _UNDECLARED_MASK) != 0
        if undeclared.any():
            time_i, gate_i = _first_cell(undeclared)
            flat = time_i * self.quality.shape[1] + gate_i
            raise ValueError(
                "undeclared quality bits in value "
                f"{int(self.quality[time_i, gate_i])} at index {flat} "
                f"(time={time_i}, gate={gate_i}); declared mask is "
                f"0x{DECLARED_QUALITY_MASK:08x}"
            )

        missing = self.kind == int(SupportKind.MISSING)
        bad_missing = missing & self.valid
        if bad_missing.any():
            raise ValueError(
                _relation_error("MISSING support must have valid=False", bad_missing)
            )

        estimated = (self.kind == int(SupportKind.INTERPOLATED)) | (
            self.kind == int(SupportKind.EXTRAPOLATED)
        )
        bad_estimated = estimated & ~self.valid
        if bad_estimated.any():
            raise ValueError(
                _relation_error(
                    "INTERPOLATED/EXTRAPOLATED support must have valid=True",
                    bad_estimated,
                )
            )

        invalid_observed = (self.kind == int(SupportKind.OBSERVED)) & ~self.valid
        reasons = (self.quality & np.uint32(int(ACQUISITION_QUALITY_REASONS))) != 0
        unexplained = invalid_observed & ~reasons
        if unexplained.any():
            raise ValueError(
                _relation_error(
                    "invalid OBSERVED support needs an acquisition-quality reason",
                    unexplained,
                )
            )

        extrapolated = self.kind == int(SupportKind.EXTRAPOLATED)
        flagged = (self.quality & np.uint32(int(QualityFlag.EXTRAPOLATED))) != 0
        unflagged = extrapolated & ~flagged
        if unflagged.any():
            raise ValueError(
                _relation_error(
                    "EXTRAPOLATED support must include QualityFlag.EXTRAPOLATED",
                    unflagged,
                )
            )

        return self
