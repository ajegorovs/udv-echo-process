"""Row-level acquisition index and acquisition mode (plan §6.4, §6.7).

Maps each ``(T,)`` payload row to its exact source acquisition, or marks it
wholly synthetic. ``sample_id == -1`` iff the actual acquisition time is NaN;
present optional ids are ``>= 0`` or exactly ``-1`` (unmatched/unknown).

``AcquisitionMode`` describes how a *recording*'s channels were acquired. It is
never inferred: only decoding may set it, and a file the format cannot prove
yields :attr:`AcquisitionMode.UNKNOWN` (plan §6.7, §14).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

import numpy as np
from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ArrayModel, ArraySpec, array_field


class AcquisitionMode(str, Enum):
    """How a recording's channels were acquired, or ``UNKNOWN`` if unprovable."""

    SIMULTANEOUS = "simultaneous"
    SEQUENTIAL = "sequential"
    ROLLING = "rolling"
    UNKNOWN = "unknown"


#: Optional per-row int64 index of length ``(T,)``.
_OptionalInt64 = Annotated[np.ndarray | None, ArraySpec(np.dtype(np.int64), rank=1)]

#: Optional id arrays, in the order they are reported.
_OPTIONAL_IDS = ("round_id", "visit_id", "profile_in_visit")


class _NullableArrayModel(ArrayModel):
    """``ArrayModel`` that also accepts ``None`` for a declared array field.

    The shared ``owned_array`` helper cannot read ``None``; the optional
    ``round_id`` / ``visit_id`` / ``profile_in_visit`` fields need ``None`` to
    mean "this index is absent". Present arrays still route through the shared
    ownership helper unchanged, so dtype/rank/ownership are enforced exactly as
    for required arrays.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _validate_array_fields(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return None
        return super()._validate_array_fields(value, info)


class AcquisitionIndex(_NullableArrayModel):
    """Per-row link to the exact source acquisition rows.

    ``sample_id`` is unique and nonnegative for acquired rows and ``-1`` for a
    wholly synthetic row; ``acquisition_time_s`` is the channel's actual
    measured time (NaN exactly where ``sample_id == -1``).
    """

    sample_id: array_field(np.int64, rank=1)
    acquisition_time_s: array_field(np.float64, rank=1)
    round_id: _OptionalInt64 = None
    visit_id: _OptionalInt64 = None
    profile_in_visit: _OptionalInt64 = None

    @model_validator(mode="after")
    def _check_invariants(self) -> AcquisitionIndex:
        length = self.sample_id.shape[0]
        if self.acquisition_time_s.shape[0] != length:
            raise ValueError(
                f"acquisition arrays must share length: sample_id={length}, "
                f"acquisition_time_s={self.acquisition_time_s.shape[0]}"
            )
        for name in _OPTIONAL_IDS:
            arr = getattr(self, name)
            if arr is not None and arr.shape[0] != length:
                raise ValueError(
                    f"acquisition arrays must share length: sample_id={length}, "
                    f"{name}={arr.shape[0]}"
                )
        self._check_sample_ids()
        self._check_times()
        self._check_optional_ids()
        self._check_synthetic_rows()
        return self

    def _check_sample_ids(self) -> None:
        sample_id = self.sample_id
        too_small = sample_id < -1
        if too_small.any():
            index = int(np.flatnonzero(too_small)[0])
            raise ValueError(
                f"sample_id must be >= 0 or exactly -1, got "
                f"{int(sample_id[index])} at index {index}"
            )
        acquired = sample_id[sample_id >= 0]
        if acquired.size:
            values, counts = np.unique(acquired, return_counts=True)
            duplicates = values[counts > 1]
            if duplicates.size:
                duplicate = int(duplicates[0])
                positions = np.flatnonzero(sample_id == duplicate)
                raise ValueError(
                    f"duplicate sample_id {duplicate} at index "
                    f"{int(positions[1])} (first seen at index "
                    f"{int(positions[0])})"
                )

    def _check_times(self) -> None:
        sample_id = self.sample_id
        times = self.acquisition_time_s
        is_nan = np.isnan(times)
        is_synthetic = sample_id == -1
        mismatch = is_nan != is_synthetic
        if mismatch.any():
            index = int(np.flatnonzero(mismatch)[0])
            raise ValueError(
                "sample_id == -1 must coincide with NaN acquisition time "
                f"({_cells(int(mismatch.sum()))}, first at index {index})"
            )
        finite_rows = np.flatnonzero(~is_nan)
        if finite_rows.size >= 2:
            finite = times[finite_rows]
            violates = np.diff(finite) <= 0
            if violates.any():
                pos = int(np.flatnonzero(violates)[0])
                raise ValueError(
                    "finite acquisition times must be strictly increasing; "
                    f"row {int(finite_rows[pos + 1])} violates with adjacent "
                    f"values {finite[pos]} then {finite[pos + 1]}"
                )

    def _check_optional_ids(self) -> None:
        for name in _OPTIONAL_IDS:
            arr = getattr(self, name)
            if arr is None:
                continue
            too_small = arr < -1
            if too_small.any():
                index = int(np.flatnonzero(too_small)[0])
                raise ValueError(
                    f"{name} must be >= 0 or exactly -1, got "
                    f"{int(arr[index])} at index {index}"
                )
        if self.profile_in_visit is not None and self.visit_id is None:
            raise ValueError("profile_in_visit requires visit_id to be present")

    def _check_synthetic_rows(self) -> None:
        synthetic = self.sample_id == -1
        if not synthetic.any():
            return
        for name in _OPTIONAL_IDS:
            arr = getattr(self, name)
            if arr is None:
                continue
            bad = synthetic & (arr != -1)
            if bad.any():
                index = int(np.flatnonzero(bad)[0])
                raise ValueError(
                    f"synthetic row (sample_id == -1) must be -1 in {name}, "
                    f"got {int(arr[index])} at index {index}"
                )


def _cells(count: int) -> str:
    return f"{count} cell" if count == 1 else f"{count} cells"
