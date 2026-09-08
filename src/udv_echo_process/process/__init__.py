"""Processing transforms — pure, typed `Recording -> Recording` steps.

Skeleton for the rebuild. Once the sync layer lands, this holds the ordered
`Pipeline` composition plus `Recording -> Recording` transforms (sync,
resample). Per `docs/pipeline-conventions.md`, processing steps chain and
re-apply; terminal `Recording -> U` stages live in `analysis/`.
"""

from __future__ import annotations
