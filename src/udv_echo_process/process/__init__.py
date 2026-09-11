"""Processing transforms — pure, typed steps over the canonical models.

Stage 3 home: per-channel time resampling lives in ``sync.py``
(``InterpSpec`` + ``resample``) per `docs/interpolation-design.md` §7/§8, and
per-gate time filtering lives in ``filter.py`` (``FilterMethod`` /
``FilterParams`` / ``FilterSpec`` + ``filter`` / ``filter_sequence``) per
`docs/filter-design.md` §7. Once the sync layer grows, this package also
holds the ordered ``Pipeline`` composition. Per
`docs/pipeline-conventions.md`, processing steps chain and re-apply; terminal
``Recording -> U`` stages live in ``analysis/``.
"""

from __future__ import annotations

from udv_echo_process.process.derive import (
    OPERATION_SCHEMA_VERSION,
    OPERATION_SPEC_REGISTRY,
    derive,
    register_operation,
    resolve_operation_spec,
    revalidate_params,
    schema_version_for,
)
from udv_echo_process.process.filter import (
    FilterMethod,
    FilterParams,
    FilterSpec,
    filter,
    filter_sequence,
)
from udv_echo_process.process.sync import (
    InterpMethod,
    InterpParams,
    InterpSpec,
    resample,
)

__all__ = [
    "OPERATION_SCHEMA_VERSION",
    "OPERATION_SPEC_REGISTRY",
    "FilterMethod",
    "FilterParams",
    "FilterSpec",
    "InterpMethod",
    "InterpParams",
    "InterpSpec",
    "derive",
    "filter",
    "filter_sequence",
    "register_operation",
    "resample",
    "resolve_operation_spec",
    "revalidate_params",
    "schema_version_for",
]
