"""The single-channel measurement unit — the atomic pipeline type.

The whole package is built bottom-up from this one object: every channel of a
multiplexed/rolling recording is one ``ChannelSeries``, carrying *its own*
timestamps and *its own* static config. A recording is just an ordered list of
these (see ``models/measurement.py``).
"""

from __future__ import annotations

import numpy as np
from pydantic import Field, model_validator

from udv_echo_process.models.base import Model, shape_2d
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.io import MeasType


class ChannelSeries(Model):
    """One channel's time-resolved measurement.

    The canonical store for a channel: its own gate depths, its own sampled
    timestamps, and the 2-D ``values`` (profiles × gates) that fill the
    ``time_s`` × ``gate_depths_mm`` grid.

    ``time_s`` is the channel's **real** sampled times (no assumed round-robin
    ``DT``): time-syncing later interpolates these actual timestamps onto a
    common grid, deriving offsets from data — never from a hard-coded step.

    Invariant (T2, validated on construction):
        ``values.shape == (len(time_s), len(gate_depths_mm))`` and
        ``time_s`` is monotonically non-decreasing.
    """

    channel: int
    meas_type: MeasType
    gate_depths_mm: list[float]
    time_s: np.ndarray = Field(default_factory=lambda: np.array([]))
    values: np.ndarray = Field(default_factory=lambda: np.array([[]]))
    config: ChannelConfig = Field(default_factory=ChannelConfig)

    @model_validator(mode="after")
    def _check_shapes(self) -> ChannelSeries:
        n_gates = len(self.gate_depths_mm)
        if n_gates > 0 and not shape_2d(self.time_s, self.values, n_gates):
            raise ValueError(
                f"channel {self.channel}: values.shape={tuple(self.values.shape)} "
                f"mismatches gates={n_gates}, T={len(self.time_s)}"
            )
        if (
            self.time_s.ndim == 1
            and len(self.time_s) > 1
            and np.any(np.diff(self.time_s) < 0)
        ):
            raise ValueError(f"channel {self.channel}: time_s must be non-decreasing")
        return self

    @property
    def time_count(self) -> int:
        return len(self.time_s)

    @property
    def gate_count(self) -> int:
        return len(self.gate_depths_mm)

    def describe(self) -> str:
        """One-line summary of this channel's measurement."""
        t0 = self.time_s[0] if self.time_count else float("nan")
        t1 = self.time_s[-1] if self.time_count else float("nan")
        return (
            f"ch{self.channel} {self.meas_type.value} · "
            f"{self.time_count}×{self.gate_count} · "
            f"[{t0:.3f} → {t1:.3f}] s · config: {self.config.describe()}"
        )
