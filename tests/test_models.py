"""Tests for the models layer — the authoritative type contracts.

Covers the T2 (structural) validation on ``ChannelSeries``, the
composition/container behaviour of ``MultiplexedMeasurement``, and the source/
config descriptors.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    ChannelConfig,
    ChannelSeries,
    MeasType,
    MultiplexedMeasurement,
    SourceFormat,
    SourceSpec,
)


def make_series(
    channel: int = 4, t: np.ndarray | None = None, gates: int = 2
) -> ChannelSeries:
    """Build a small, valid ChannelSeries for reuse (3 timesteps × gates)."""
    t = np.array([0.0, 0.1, 0.2]) if t is None else t
    return ChannelSeries(
        channel=channel,
        meas_type=MeasType.ECHO,
        gate_depths_mm=[1.0, 2.0][:gates],
        time_s=t,
        values=np.full((len(t), gates), 1.0),
    )


# ── ChannelSeries ───────────────────────────────────────────────────────


class TestChannelSeries:
    def test_valid_build(self):
        cs = make_series()
        assert cs.channel == 4
        assert cs.time_count == 3
        assert cs.gate_count == 2
        assert cs.meas_type == MeasType.ECHO

    def test_shape_mismatch_rejected(self):
        # values (3,1) but gates == 2
        with pytest.raises(ValidationError):
            ChannelSeries(
                channel=4,
                meas_type=MeasType.ECHO,
                gate_depths_mm=[1.0, 2.0],
                time_s=np.array([0.0, 0.1, 0.2]),
                values=np.zeros((3, 1)),
            )

    def test_non_monotonic_time_rejected(self):
        with pytest.raises(ValidationError):
            make_series(t=np.array([0.0, 0.3, 0.1]))

    def test_config_defaults_to_empty(self):
        s = make_series()
        assert isinstance(s.config, ChannelConfig)
        assert s.config.sound_speed_ms is None

    def test_config_carried_with_channel(self):
        s = make_series()
        s.config = ChannelConfig(sound_speed_ms=2740.0, n_gates=26)
        assert s.config.sound_speed_ms == 2740.0


# ── MultiplexedMeasurement ──────────────────────────────────────────────


class TestMultiplexedMeasurement:
    def _meas(self, n_channels: int = 1) -> MultiplexedMeasurement:
        return MultiplexedMeasurement(
            file_path=Path("test.BDD"),
            source=SourceSpec(
                vendor="Signal Processing SA",
                device="DOP 3010",
                format=SourceFormat.BDD,
            ),
            channels=[make_series(channel=c) for c in range(1, n_channels + 1)],
        )

    def test_single_channel_not_multiplexed(self):
        m = self._meas(n_channels=1)
        assert m.is_multiplexed is False
        assert m.meas_type == MeasType.ECHO

    def test_multiplexed_order_preserved(self):
        m = self._meas(n_channels=3)
        assert m.is_multiplexed is True
        assert [c.channel for c in m.channels] == [1, 2, 3]

    def test_by_channel(self):
        m = self._meas(n_channels=3)
        assert set(m.by_channel()) == {1, 2, 3}
        assert m.by_channel()[2].channel == 2

    def test_mixed_meas_type_returns_none(self):
        a = make_series(channel=1)
        b = make_series(channel=2)
        b.meas_type = MeasType.VELOCITY
        m = MultiplexedMeasurement(
            file_path=Path("x.BDD"),
            source=SourceSpec(format=SourceFormat.BDD),
            channels=[a, b],
        )
        assert m.meas_type is None

    def test_file_spec_round_trip(self):
        m = self._meas(n_channels=1)
        assert Path(m.file_path).name.endswith(".BDD")
        assert m.source == SourceSpec(
            vendor="Signal Processing SA", device="DOP 3010", format=SourceFormat.BDD
        )


# ── SourceSpec / ChannelConfig descriptors ──────────────────────────────


class TestDescriptors:
    def test_source_spec_defaults(self):
        spec = SourceSpec(
            vendor="Signal Processing SA", device="DOP 3010", format=SourceFormat.BDD
        )
        assert spec.format == SourceFormat.BDD
        assert "DOP 3010" in str(spec)

    def test_channel_config_always_constructible(self):
        c = ChannelConfig()
        assert c.n_gates is None
        assert (
            len(ChannelConfig.model_fields) > 5
        )  # broad charset across acous/gate/physics/tgc
