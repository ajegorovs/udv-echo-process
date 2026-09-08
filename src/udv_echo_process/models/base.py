"""Shared Pydantic model conventions for udv_echo_process.

All data structures in this package are Pydantic ``BaseModel`` subclasses
(numpy-backed fields require ``arbitrary_types_allowed`` in their config;
see `docs/pipeline-conventions.md`).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base for all numpy-backed domain models.

    Pydantic v2 refuses to generate a schema for ``np.ndarray`` unless
    ``arbitrary_types_allowed`` is set, so every model that stores raw
    arrays (``ChannelSeries``) inherits this. Models with only plain
    Python field types may subclass ``Model`` too for uniformity.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)


def shape_2d(time_s: np.ndarray, values: np.ndarray, n_gates: int) -> bool:
    """Structural (T2) check shared by the series model.

    ``values`` must be 2-D with shape ``(len(time_s), n_gates)``.

    Args:
        time_s: per-channel time vector.
        values: profile data matrix.
        n_gates: number of depth gates.

    Returns:
        True when the shapes are mutually consistent.
    """
    return values.ndim == 2 and values.shape == (len(time_s), n_gates)
