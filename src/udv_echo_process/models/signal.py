"""Scientific payload and artifacts: ``SignalData`` and ``ChannelArtifact``.

Plan §6.5–§6.6. ``SignalData`` is the immutable per-channel signal:
monotonically increasing time and gate axes, a ``(T, G)`` value matrix,
:class:`SampleSupport` for every cell, and an optional row-level
:class:`AcquisitionIndex`. Every array is owned, C-contiguous and read-only
(via ``ArrayModel``).

``ChannelArtifact`` wraps one channel's payload with its acquisition identity,
descriptor and config plus a content-addressed ``artifact_id``. The explicit
factories :func:`observed_signal` and :func:`missing_signal` construct through
the models, so all validation runs — they never bypass it.

Contract note (resolved ambiguity): §6.6 fixes ``ChannelArtifact`` at exactly
five fields, so a *derived* artifact cannot self-check its id inside the model —
there is no sixth field to recompute from. Ids are therefore recomputed and
compared in the two constructors this phase actually uses: :func:`source_artifact`
for source payloads and ``process.derive.derive`` for transformed ones. The
bundle-wide id-versus-graph consistency check belongs to Phase 7's full bundle
validation.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np
from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models._canonical import canonical_json_bytes, stable_id
from udv_echo_process.models.acquisition import AcquisitionIndex
from udv_echo_process.models.base import ArrayModel, array_field
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.identity import AcquisitionRef, SignalDescriptor
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


# ── content-addressed artifact identity (plan §6.6) ─────────────────────

#: Opaque artifact-id form: ``sha256:`` plus 64 lower-case hex characters.
_ARTIFACT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")

#: Rows hashed per chunk by :func:`array_digest`. Chunking bounds the peak extra
#: allocation by the block, never the whole production array (plan §13).
_ARRAY_CHUNK_ROWS = 2048

#: Acquisition-index arrays, in the order they are hashed when present.
_ACQUISITION_ARRAY_NAMES = (
    "sample_id",
    "acquisition_time_s",
    "round_id",
    "visit_id",
    "profile_in_visit",
)


def array_digest(array: np.ndarray) -> str:
    """Return the content digest of one array as an opaque ``sha256:<hex>`` id.

    The digest covers the array's dtype, its shape and every element, read in
    bounded row chunks so a full ``.tobytes()`` copy of a production array is
    never materialized (plan §13). Including dtype and shape means two arrays
    with identical bytes but a different dtype/shape cannot collide.

    Args:
        array: any array-like; 0-d arrays are fed whole.

    Returns:
        A lower-case ``sha256:<64 hex>`` id.
    """
    arr = np.asarray(array)
    hasher = hashlib.sha256()
    hasher.update(
        canonical_json_bytes({"dtype": arr.dtype.str, "shape": list(arr.shape)})
    )
    if arr.ndim == 0:
        hasher.update(np.ascontiguousarray(arr).tobytes())
    else:
        for start in range(0, arr.shape[0], _ARRAY_CHUNK_ROWS):
            block = np.ascontiguousarray(arr[start : start + _ARRAY_CHUNK_ROWS])
            hasher.update(block.tobytes())
    return f"sha256:{hasher.hexdigest()}"


def _signal_array_digests(data: SignalData) -> dict[str, str]:
    """Return ``label -> digest`` for every scientific/support/index array."""
    digests = {
        "values": array_digest(data.values),
        "time_s": array_digest(data.time_s),
        "gate_depths_mm": array_digest(data.gate_depths_mm),
        "support.kind": array_digest(data.support.kind),
        "support.valid": array_digest(data.support.valid),
        "support.quality": array_digest(data.support.quality),
    }
    acquisition = data.acquisition
    if acquisition is not None:
        for name in _ACQUISITION_ARRAY_NAMES:
            arr = getattr(acquisition, name)
            if arr is not None:
                digests[f"acquisition.{name}"] = array_digest(arr)
    return digests


def source_artifact_id(
    acquisition: AcquisitionRef,
    descriptor: SignalDescriptor,
    config: ChannelConfig,
    data: SignalData,
) -> str:
    """Return the deterministic content id of a SOURCE :class:`ChannelArtifact`.

    Hashes the acquisition identity, the canonical JSON of descriptor and
    config, and the digest of every scientific/support/index array. Wall clock,
    source path and object address never participate (plan §6.6).

    Args:
        acquisition: acquisition identity the artifact was read from.
        descriptor: what the signal measures.
        config: per-channel instrument configuration.
        data: the validated payload.

    Returns:
        A lower-case ``sha256:<64 hex>`` id.
    """
    return stable_id(
        {
            "role": "source_artifact",
            "acquisition": acquisition.model_dump(mode="json"),
            "descriptor": descriptor.model_dump(mode="json"),
            "config": config.model_dump(mode="json"),
            "arrays": _signal_array_digests(data),
        }
    )


def derived_artifact_id(
    operation_id: str,
    acquisition: AcquisitionRef,
    descriptor: SignalDescriptor,
    config: ChannelConfig,
    data: SignalData,
) -> str:
    """Return the content id of an artifact produced by ``operation_id``.

    Extends the source equation with the producing operation id and hashes the
    output acquisition/descriptor/config canonical JSON plus the output
    payload/support/index array digests (plan §6.6, §8.2). Same operation and
    same output content always produce the same id.

    Args:
        operation_id: the operation that produced ``data``.
        acquisition: preserved acquisition identity.
        descriptor: output descriptor (parent's, or an explicit replacement).
        config: output config (parent's, or an explicit replacement).
        data: the validated output payload.

    Returns:
        A lower-case ``sha256:<64 hex>`` id.
    """
    return stable_id(
        {
            "role": "derived_artifact",
            "operation_id": operation_id,
            "acquisition": acquisition.model_dump(mode="json"),
            "descriptor": descriptor.model_dump(mode="json"),
            "config": config.model_dump(mode="json"),
            "arrays": _signal_array_digests(data),
        }
    )


class ChannelArtifact(ArrayModel):
    """One channel's closed payload plus its provenance identity (plan §6.6).

    Exactly five fields. ``artifact_id`` is validated for the opaque
    ``sha256:<64 lower-case hex>`` form here. Source ids are recomputed by
    :func:`source_artifact` and rechecked when :func:`source_bundle` registers a
    public root; derived ids are computed by ``process.derive.derive`` and
    checked by bundle/storage replay. A model cannot self-check a derived id
    because §6.6 fixes the field set at five; the bundle-wide id-versus-graph
    check is Phase 7's full bundle validation.
    """

    artifact_id: str
    acquisition: AcquisitionRef
    descriptor: SignalDescriptor
    config: ChannelConfig
    data: SignalData

    @field_validator("artifact_id")
    @classmethod
    def _check_artifact_id(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip()
        if not _ARTIFACT_ID_RE.fullmatch(text):
            raise ValueError(
                f"{info.field_name} must be an opaque lower-case "
                f"'sha256:<64 hex>' id, got {value!r}"
            )
        return text


def source_artifact(
    acquisition: AcquisitionRef,
    descriptor: SignalDescriptor,
    config: ChannelConfig,
    data: SignalData,
) -> ChannelArtifact:
    """Build a SOURCE :class:`ChannelArtifact`, recomputing and comparing its id.

    The id is never trusted from a caller: it is computed from the supplied
    identity/metadata/arrays, the artifact is constructed, the id is recomputed
    from the built model and a mismatch raises :class:`RuntimeError` (a hash or
    field drift, not bad user input).

    Args:
        acquisition: acquisition identity the artifact was read from.
        descriptor: what the signal measures.
        config: per-channel instrument configuration.
        data: the validated payload.

    Returns:
        A validated :class:`ChannelArtifact` whose id matches its content.

    Raises:
        RuntimeError: if the recomputed id differs from the constructed one.
    """
    artifact_id = source_artifact_id(acquisition, descriptor, config, data)
    artifact = ChannelArtifact(
        artifact_id=artifact_id,
        acquisition=acquisition,
        descriptor=descriptor,
        config=config,
        data=data,
    )
    recomputed = source_artifact_id(
        artifact.acquisition, artifact.descriptor, artifact.config, artifact.data
    )
    if recomputed != artifact.artifact_id:
        raise RuntimeError(
            "source artifact id is not reproducible: computed "
            f"{artifact_id!r}, recomputed {recomputed!r}"
        )
    return artifact


def _acquisition_equal(
    left: AcquisitionIndex | None,
    right: AcquisitionIndex | None,
    *,
    rtol: float,
    atol: float,
) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if not np.array_equal(left.sample_id, right.sample_id):
        return False
    if not np.allclose(
        left.acquisition_time_s,
        right.acquisition_time_s,
        rtol=rtol,
        atol=atol,
        equal_nan=True,
    ):
        return False
    for name in ("round_id", "visit_id", "profile_in_visit"):
        left_arr = getattr(left, name)
        right_arr = getattr(right, name)
        if (left_arr is None) != (right_arr is None):
            return False
        if left_arr is not None and not np.array_equal(left_arr, right_arr):
            return False
    return True


def signals_equal(
    left: SignalData,
    right: SignalData,
    *,
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> bool:
    """Explicit scientific equality of two :class:`SignalData` payloads.

    Float planes compare with :func:`numpy.allclose` (NaN treated as equal, so
    identical missingness compares equal); support and index planes compare
    with :func:`numpy.array_equal`. Never rely on model ``==`` for
    ndarray-bearing models (plan §6.6).

    Args:
        left: first payload.
        right: second payload.
        rtol: relative tolerance for float planes.
        atol: absolute tolerance for float planes.

    Returns:
        True when the payloads carry the same scientific content.
    """
    if left.values.shape != right.values.shape:
        return False
    if not np.allclose(left.values, right.values, rtol=rtol, atol=atol, equal_nan=True):
        return False
    if not np.allclose(left.time_s, right.time_s, rtol=rtol, atol=atol):
        return False
    if not np.allclose(left.gate_depths_mm, right.gate_depths_mm, rtol=rtol, atol=atol):
        return False
    if not (
        np.array_equal(left.support.kind, right.support.kind)
        and np.array_equal(left.support.valid, right.support.valid)
        and np.array_equal(left.support.quality, right.support.quality)
    ):
        return False
    return _acquisition_equal(left.acquisition, right.acquisition, rtol=rtol, atol=atol)


def artifacts_equal(left: ChannelArtifact, right: ChannelArtifact) -> bool:
    """Explicit equality of two artifacts: id, identity, metadata and payload.

    Uses :func:`signals_equal` for the ndarray-bearing payload; never model ``==``.
    """
    return (
        left.artifact_id == right.artifact_id
        and left.acquisition == right.acquisition
        and left.descriptor == right.descriptor
        and left.config == right.config
        and signals_equal(left.data, right.data)
    )
