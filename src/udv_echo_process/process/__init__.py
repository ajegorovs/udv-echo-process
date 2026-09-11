"""Processing transforms — pure, typed steps over the canonical models.

Stage 3 home: per-channel time resampling lives in ``sync.py``
(``resample`` and the four ``InterpSpec`` branches) per plan §7.3; the legacy
``InterpMethod``/``InterpParams``/``nan_policy`` surface is gone. Per-gate time
filtering lives in ``filter.py`` (``filter`` / ``filter_sequence``) with its
discriminated spec union in ``specs.py`` (``FilterSpec`` and its four branches)
per `docs/filter-design.md` §7 and plan §7.2; the interpolation union also lives
in ``specs.py``. The private segment/uniformity rules live in ``segments.py``.
Both transforms are closed ``ChannelBundle -> ChannelBundle`` steps that call
:func:`udv_echo_process.process.derive.derive`. Per
`docs/pipeline-conventions.md`, processing steps chain and re-apply; terminal
``Recording -> U`` stages live in ``analysis/``.
"""

from __future__ import annotations

from udv_echo_process.process.derive import (
    OPERATION_SCHEMA_VERSION,
    OPERATION_SPEC_REGISTRY,
    derive,
    derive_many,
    register_operation,
    resolve_operation_spec,
    revalidate_params,
    schema_version_for,
)
from udv_echo_process.process.filter import filter, filter_sequence
from udv_echo_process.process.specs import (
    BsplineInterpSpec,
    CubicInterpSpec,
    FilterSpec,
    InterpSpec,
    LinearInterpSpec,
    MeanFilterSpec,
    MedianFilterSpec,
    MonotoneInterpSpec,
    SavgolFilterSpec,
    SyncSpec,
    TvFilterSpec,
)
from udv_echo_process.process.sync import SYNC_KIND, resample, synchronize

__all__ = [
    "OPERATION_SCHEMA_VERSION",
    "OPERATION_SPEC_REGISTRY",
    "SYNC_KIND",
    "BsplineInterpSpec",
    "CubicInterpSpec",
    "FilterSpec",
    "InterpSpec",
    "LinearInterpSpec",
    "MeanFilterSpec",
    "MedianFilterSpec",
    "MonotoneInterpSpec",
    "SavgolFilterSpec",
    "SyncSpec",
    "TvFilterSpec",
    "derive",
    "derive_many",
    "filter",
    "filter_sequence",
    "register_operation",
    "resample",
    "resolve_operation_spec",
    "revalidate_params",
    "schema_version_for",
    "synchronize",
]
