"""Scientific payload: ``SignalData`` and its construction factories.

Plan §6.5. ``SignalData`` is the immutable per-channel signal: monotonically
increasing time and gate axes, a ``(T, G)`` value matrix, :class:`SampleSupport`
for every cell, and an optional row-level :class:`AcquisitionIndex`. Every
array is owned, C-contiguous and read-only (via ``ArrayModel``).

The explicit factories :func:`observed_signal` and :func:`missing_signal`
construct through the models, so all validation runs — they never bypass it.
"""

from __future__ import annotations

import numpy as np
from pydantic import model_validator

from udv_echo_process.models.acquisition import AcquisitionIndex
from udv_echo_process.models.base import ArrayModel, array_field
from udv_echo_process.models.support import SampleSupport, SupportKind


def _cells(count: int) -> str:
    return f"{count} cell" if count == 1 else f"{count} cells"


def _first_cell(mask: np.ndarray) -> tuple[int, int]:
    """Return the ``(time, gate)`` coordinate of the first ``True`` in ``mask``."""
    flat = int(np.flatnonzero(mask.ravel())[0])
    return int(flat // mask.shape[1]), int(flat % mask.shape[1])


def _mismatch_error(reason: str, mask: np.ndarray) -> str:
    time_i, gate_i = _first_cell(mask)
    return (
        f"{reason}: {_cells(int(mask.sum()))}, first at (time={time_i}, gate={gate_i})"
    )


def _require_finite_increasing(arr: np.ndarray, name: str) -> None:
    finite = np.isfinite(arr)
    if not finite.all():
        index = int(np.flatnonzero(~finite)[0])
        raise ValueError(
            f"{name} must be finite (no NaN/Infinity); index {index} has value "
            f"{arr[index]}"
        )
    violates = np.diff(arr) <= 0
    if violates.any():
        pos = int(np.flatnonzero(violates)[0])
        raise ValueError(
            f"{name} must be strictly increasing; index {pos + 1} violates with "
            f"adjacent values {arr[pos]} then {arr[pos + 1]}"
        )


class SignalData(ArrayModel):
    """Immutable per-channel UDV payload (plan §6.5).

    ``time_s`` and ``gate_depths_mm`` are finite and strictly increasing; every
    cell's value agrees with ``support.valid`` (finite iff valid, NaN iff not
    valid; Infinity is always rejected). When ``acquisition`` is present, every
    row containing an ``OBSERVED`` gate carries a real sample id and finite
    acquisition time; a row without any observed gate uses the synthetic
    sentinel.
    """

    time_s: array_field(np.float64, rank=1)
    gate_depths_mm: array_field(np.float64, rank=1)
    values: array_field(np.float64, rank=2)
    support: SampleSupport
    acquisition: AcquisitionIndex | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> SignalData:
        n_times = self.time_s.shape[0]
        n_gates = self.gate_depths_mm.shape[0]
        if n_times < 1:
            raise ValueError(
                f"time_s must contain at least one sample (T >= 1), got {n_times}"
            )
        if n_gates < 1:
            raise ValueError(
                f"gate_depths_mm must contain at least one gate (G >= 1), got {n_gates}"
            )
        _require_finite_increasing(self.time_s, "time_s")
        _require_finite_increasing(self.gate_depths_mm, "gate_depths_mm")

        expected = (n_times, n_gates)
        if self.values.shape != expected:
            raise ValueError(
                f"values must have shape (T, G) = {expected}, got {self.values.shape}"
            )
        if self.support.kind.shape != expected:
            raise ValueError(
                "support shape must equal values shape "
                f"{expected}, got {self.support.kind.shape}"
            )

        self._check_validity()
        if self.acquisition is not None:
            self._check_acquisition()
        return self

    def _check_validity(self) -> None:
        valid = self.support.valid
        values = self.values
        valid_needs_finite = valid & ~np.isfinite(values)
        invalid_needs_nan = (~valid) & ~np.isnan(values)
        mismatch = valid_needs_finite | invalid_needs_nan
        if mismatch.any():
            raise ValueError(
                _mismatch_error(
                    "support.valid must match value finiteness (valid=True needs "
                    "a finite value; valid=False needs NaN; Infinity is always "
                    "rejected)",
                    mismatch,
                )
            )

    def _check_acquisition(self) -> None:
        acquisition = self.acquisition
        assert acquisition is not None  # narrowed for type checkers
        n_times = self.time_s.shape[0]
        if acquisition.sample_id.shape[0] != n_times:
            raise ValueError(
                f"acquisition index must have length T = {n_times}, got "
                f"{acquisition.sample_id.shape[0]}"
            )
        observed_row = (self.support.kind == int(SupportKind.OBSERVED)).any(axis=1)
        real = (acquisition.sample_id >= 0) & np.isfinite(
            acquisition.acquisition_time_s
        )
        missing_real = observed_row & ~real
        if missing_real.any():
            row = int(np.flatnonzero(missing_real)[0])
            raise ValueError(
                "every row with an OBSERVED gate needs a nonnegative sample_id "
                f"and a finite acquisition time; row {row} has sample_id="
                f"{int(acquisition.sample_id[row])}, acquisition_time_s="
                f"{acquisition.acquisition_time_s[row]}"
            )
        not_synthetic = (~observed_row) & (acquisition.sample_id != -1)
        if not_synthetic.any():
            row = int(np.flatnonzero(not_synthetic)[0])
            raise ValueError(
                f"row {row} has no OBSERVED gate and must carry the synthetic "
                f"sentinel sample_id=-1, got {int(acquisition.sample_id[row])}"
            )


def observed_signal(
    time_s: object,
    gate_depths_mm: object,
    values: object,
    *,
    quality: object = None,
    acquisition: AcquisitionIndex | None = None,
) -> SignalData:
    """Build an all-``OBSERVED`` signal from real time/gate/value arrays.

    Every cell is :attr:`SupportKind.OBSERVED`; ``valid`` mirrors value
    finiteness, so a NaN cell is an *invalid observation* and needs an
    acquisition-quality reason supplied via ``quality`` (for example
    :attr:`QualityFlag.OUTLIER`). ``quality`` defaults to all-``NONE``.

    Args:
        time_s: per-row time coordinate, ``(T,)`` finite and increasing.
        gate_depths_mm: per-gate depth coordinate, ``(G,)`` finite and increasing.
        values: ``(T, G)`` value matrix.
        quality: optional ``(T, G)`` uint32 quality mask; defaults to ``NONE``.
        acquisition: optional row-level acquisition index of length ``T``.

    Returns:
        A validated :class:`SignalData` with owned read-only arrays.

    Raises:
        pydantic.ValidationError: when any ``SignalData``/``SampleSupport``
            invariant fails (this factory does not bypass validation).
    """
    values_arr = np.asarray(values, dtype=np.float64)
    shape = values_arr.shape
    kind = np.full(shape, int(SupportKind.OBSERVED), dtype=np.uint8)
    valid = np.isfinite(values_arr)
    if quality is None:
        quality_arr = np.zeros(shape, dtype=np.uint32)
    else:
        quality_arr = np.asarray(quality, dtype=np.uint32)
    support = SampleSupport(kind=kind, valid=valid, quality=quality_arr)
    return SignalData(
        time_s=np.asarray(time_s, dtype=np.float64),
        gate_depths_mm=np.asarray(gate_depths_mm, dtype=np.float64),
        values=values_arr,
        support=support,
        acquisition=acquisition,
    )


def missing_signal(
    time_s: object,
    gate_depths_mm: object,
    *,
    acquisition: AcquisitionIndex | None = None,
) -> SignalData:
    """Allocate an all-``MISSING`` signal over the given time/gate axes.

    ``values`` is NaN, and support is ``MISSING`` (``valid=False``, quality
    ``NONE``) in every cell. The axes define the ``(T, G)`` shape; the models
    validate the axes, the shape and the support/value relation.

    Args:
        time_s: per-row time coordinate, ``(T,)`` finite and increasing.
        gate_depths_mm: per-gate depth coordinate, ``(G,)`` finite and increasing.
        acquisition: optional row-level acquisition index of length ``T``.

    Returns:
        A validated :class:`SignalData` with owned read-only arrays.

    Raises:
        pydantic.ValidationError: when any invariant fails (not bypassed).
    """
    time_arr = np.asarray(time_s, dtype=np.float64)
    gate_arr = np.asarray(gate_depths_mm, dtype=np.float64)
    shape = (time_arr.shape[0], gate_arr.shape[0])
    support = SampleSupport(
        kind=np.zeros(shape, dtype=np.uint8),
        valid=np.zeros(shape, dtype=bool),
        quality=np.zeros(shape, dtype=np.uint32),
    )
    return SignalData(
        time_s=time_arr,
        gate_depths_mm=gate_arr,
        values=np.full(shape, np.nan, dtype=np.float64),
        support=support,
        acquisition=acquisition,
    )
