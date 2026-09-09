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
    "FilterMethod",
    "FilterParams",
    "FilterSpec",
    "InterpMethod",
    "InterpParams",
    "InterpSpec",
    "filter",
    "filter_sequence",
    "resample",
]
