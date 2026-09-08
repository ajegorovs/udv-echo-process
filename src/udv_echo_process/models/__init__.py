"""Shared Pydantic models — the authoritative type layer.

`models/` imports nothing from `io`/`process`/`analysis`/`viz`; everything else
imports `models`. This one-way rule is what keeps the layers swappable and the
import graph cycle-free (the key correctness constraint of the rebuild).
"""

from __future__ import annotations

from udv_echo_process.models.base import Model, shape_2d
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.channel_series import ChannelSeries
from udv_echo_process.models.io import MeasType, SourceFormat, SourceSpec
from udv_echo_process.models.measurement import MultiplexedMeasurement

__all__ = [
    "ChannelConfig",
    "ChannelSeries",
    "MeasType",
    "Model",
    "MultiplexedMeasurement",
    "SourceFormat",
    "SourceSpec",
    "shape_2d",
]
