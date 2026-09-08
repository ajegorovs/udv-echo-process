"""The whole measurement record — an ordered composition of channels.

``MultiplexedMeasurement`` is the "box" that holds the single-channel units of
one recording. It is primarily a *view of a rolling/multiplexed file* (e.g. the
DOP3000 ``.BDD`` multiplexing several channels sequentially); a single-channel
recording is simply this box with one element.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from udv_echo_process.models.base import Model
from udv_echo_process.models.channel_series import ChannelSeries
from udv_echo_process.models.io import MeasType, SourceSpec


class MultiplexedMeasurement(Model):
    """A measurement composed of one or more single-channel series.

    ``channels`` preserves the multiplexed **order** (round-robin sequence),
    so it is a list, not a dict — per-channel identity (``ChannelSeries.channel``)
    lives inside each element.

    No synchronization/geometry fields live here: sync derives offsets from each
    channel's real ``time_s`` and produces a derived common grid at call time;
    geometry is deferred.
    """

    file_path: Path
    source: SourceSpec
    header: str = ""
    comment: str = ""
    channels: list[ChannelSeries] = Field(default_factory=list)

    @property
    def meas_type(self) -> MeasType | None:
        """Measurement type if all channels agree, None if mixed."""
        types = {c.meas_type for c in self.channels}
        return types.pop() if len(types) == 1 else None

    @property
    def is_multiplexed(self) -> bool:
        return len(self.channels) > 1

    def by_channel(self) -> dict[int, ChannelSeries]:
        return {c.channel: c for c in self.channels}

    def describe(self) -> str:
        """Multi-line description of the measurement."""
        n = len(self.channels)
        head = (
            f"{self.file_path.name} · {self.source!s} · "
            f"{n} channel{'s' if n != 1 else ''} · {self.meas_type or 'mixed'}"
        )
        body = "\n".join(f"  {c.describe()}" for c in self.channels)
        return f"{head}\n{body}"
