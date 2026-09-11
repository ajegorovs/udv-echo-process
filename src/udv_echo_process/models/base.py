"""Shared Pydantic model conventions for udv_echo_process.

Frozen value bases (plan §6.1):

- :class:`ValueModel` — immutable, ``extra="forbid"``, validates defaults;
  every field must round-trip through ``model_dump(mode="json")``.
- :class:`ArrayModel` — a ``ValueModel`` that additionally permits
  ``np.ndarray`` fields and routes each one through the shared
  :func:`owned_array` helper, so a stored buffer is an owned, C-contiguous,
  read-only copy that never shares memory with the caller's input.

Phase 9 removed the legacy mutable ``Model`` base and its ``shape_2d`` helper
together with ``ChannelSeries``/``MultiplexedMeasurement``; only the two frozen
bases above and their shared array helpers remain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator


class ValueModel(BaseModel):
    """Immutable, strict, JSON-round-trippable value-object base (plan §6.1).

    ``frozen=True`` makes instances hashable (so a ``ValueModel`` can key a
    dict); ``extra="forbid"`` rejects undeclared fields; ``validate_default``
    runs validators over defaults too. ``arbitrary_types_allowed`` is
    deliberately *not* set — use :class:`ArrayModel` for ndarray fields.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
    )


#: dtypes rejected by :func:`owned_array`: object, string (str/bytes),
#: structured/void and complex.
#:
#: ``np.dtype.kind`` codes: object ``O``, unicode ``U``, bytes ``S``, void
#: (structured) ``V``, complex ``c``.
_UNSUPPORTED_DTYPE_KINDS = frozenset({"O", "U", "S", "V", "c"})


@dataclass(frozen=True, slots=True)
class ArraySpec:
    """Declared dtype/rank/shape contract for one owned ndarray field."""

    dtype: np.dtype
    rank: int
    shape: tuple[int, ...] | None = None


def owned_array(
    value: object,
    *,
    field_name: str,
    dtype: np.dtype | str | type,
    rank: int,
    shape: tuple[int, ...] | None = None,
) -> np.ndarray:
    """Validate one ndarray field and return an owned, read-only C array.

    This is the single helper every ndarray field validator must call
    (plan §6.1). It:

    1. rejects object, string, structured and complex input dtypes;
    2. converts with the field's exact ``dtype`` and C order;
    3. copies unconditionally, so the result owns its data (``OWNDATA``) and
       never shares memory with the caller's input;
    4. marks the resulting buffer non-writeable; and
    5. raises a field-named error reporting expected *and* actual
       dtype/rank/shape.

    Args:
        value: raw field value (ndarray, list or other array-like).
        field_name: model field name used to prefix error messages.
        dtype: exact numpy dtype the field stores.
        rank: required number of dimensions.
        shape: exact required shape, or ``None`` to accept any shape of ``rank``.

    Returns:
        A new C-contiguous, owned, read-only ``np.ndarray`` of ``dtype``.

    Raises:
        ValueError: for an unsupported input dtype (including the object array
            a ragged list produces), a rank/shape mismatch, or input that
            cannot be interpreted/converted. Pydantic wraps it as a
            ``ValidationError``.
    """
    expected = np.dtype(dtype)
    expected_txt = _describe_expected(expected, rank, shape)
    try:
        arr = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"field {field_name!r}: cannot read input as an array ({exc}); "
            f"expected {expected_txt}"
        ) from exc
    if arr.dtype.kind in _UNSUPPORTED_DTYPE_KINDS:
        raise ValueError(
            f"field {field_name!r}: unsupported dtype {arr.dtype.name!r} "
            "(object/string/structured/complex are rejected); "
            f"expected {expected_txt}, got {_describe_actual(arr)}"
        )
    if arr.ndim != rank or (shape is not None and tuple(arr.shape) != tuple(shape)):
        raise ValueError(
            f"field {field_name!r}: expected {expected_txt}, got {_describe_actual(arr)}"
        )
    try:
        out = np.array(arr, dtype=expected, order="C", copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"field {field_name!r}: cannot convert {_describe_actual(arr)} "
            f"to {expected_txt}: {exc}"
        ) from exc
    out.flags.writeable = False
    return out


def _describe_actual(arr: np.ndarray) -> str:
    return f"dtype {arr.dtype.name}, rank {arr.ndim}, shape {tuple(arr.shape)}"


def _describe_expected(
    dtype: np.dtype, rank: int, shape: tuple[int, ...] | None
) -> str:
    shape_txt = "any" if shape is None else str(tuple(shape))
    return f"dtype {dtype.name}, rank {rank}, shape {shape_txt}"


def array_field(
    dtype: np.dtype | str | type,
    *,
    rank: int,
    shape: tuple[int, ...] | None = None,
) -> Any:
    """Declare an :class:`ArrayModel` field routed through :func:`owned_array`.

    Usage::

        class SignalData(ArrayModel):
            values: array_field(np.float64, rank=2)      # (T, G), any shape
            times_s: array_field(np.float64, rank=1)     # (T,)

    The returned annotation carries an :class:`ArraySpec`; the inherited
    :class:`ArrayModel` validator reads it and calls ``owned_array`` with the
    field's own name, guaranteeing an owned read-only C copy and field-named
    errors.
    """
    return Annotated[np.ndarray, ArraySpec(np.dtype(dtype), rank=rank, shape=shape)]


class ArrayModel(ValueModel):
    """A :class:`ValueModel` that stores ndarray fields owned and read-only.

    Adds ``arbitrary_types_allowed`` while retaining frozen/extra/validate
    policy. Declare an array field with :func:`array_field`; the inherited
    validator copies it via the shared :func:`owned_array` helper. Because the
    model is frozen and ``model_copy(update=...)`` skips validation, use
    construction (not ``update``) for any array data change.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        arbitrary_types_allowed=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def _validate_array_fields(cls, value: object, info: ValidationInfo) -> object:
        spec = _array_spec(cls, info.field_name)
        if spec is None:
            return value
        return owned_array(
            value,
            field_name=info.field_name,
            dtype=spec.dtype,
            rank=spec.rank,
            shape=spec.shape,
        )


def _array_spec(cls: type[ArrayModel], field_name: str) -> ArraySpec | None:
    """Return the :class:`ArraySpec` declared on ``field_name``, if any."""
    field = cls.model_fields.get(field_name)
    if field is None:
        return None
    for meta in field.metadata:
        if isinstance(meta, ArraySpec):
            return meta
    return None
