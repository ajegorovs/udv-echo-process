"""Tests for the RPM analysis module and run_all batch helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from udv_echo_process import (
    ChannelFrame,
    ExtractedData,
    MeasType,
    extract,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)
from udv_echo_process.analysis.rpm import mean_sample_interval_s
from udv_echo_process.run_all import collect_results

ROOT = Path(__file__).resolve().parent.parent
SINGLE_RAW = ROOT / "data/echo/650.ADD"
MULTI_RAW = ROOT / "data/4-sensor-velocity/200RPM_v2.ADD"


def test_rpm_from_echo_returns_plausible_estimate() -> None:
    d = extract(SINGLE_RAW)
    rpm, peak_freq, n = rpm_from_echo(d, dt_s=0.0032)
    assert n == len(d.frames) == 4630
    assert np.isfinite(rpm)
    assert 0.0 < rpm < 2000.0
    assert peak_freq > 0.0


def test_mean_sample_interval_s_derived_from_data() -> None:
    d = extract(SINGLE_RAW)
    dt = mean_sample_interval_s(d)
    tbds = np.array([f.tbd_ms for f in d.frames])
    np.testing.assert_allclose(dt, np.mean(np.diff(tbds)) / 1000.0)
    # Real 650.ADD sample interval is ~3.18 ms, not exactly the old 0.0032.
    assert 0.003 < dt < 0.004


def test_rpm_from_echo_derives_dt_when_omitted() -> None:
    d = extract(SINGLE_RAW)
    rpm_a, *_ = rpm_from_echo(d, dt_s=0.0032)
    rpm_b, freq_b, n_b = rpm_from_echo(d)  # dt derived from data
    assert n_b == 4630
    assert np.isfinite(rpm_b)
    # Mean dT (3.182 ms) differs from the old magic constant; both sane.
    assert rpm_a > 0.0 and rpm_b > 0.0
    assert freq_b > 0.0


def test_rpm_from_echo_rejects_multi_channel() -> None:
    """Flattening all channels into one spectrum is wrong — must refuse."""
    d = extract(MULTI_RAW)
    assert sorted(d.by_channel()) == [6, 7, 8, 9]
    with pytest.raises(ValueError, match="single-channel"):
        rpm_from_echo(d, dt_s=0.0032)


# ── one-channel mixed-quantity guard (93-column mux shape) ──────────────
#
# A 93-column mux export emits two frames per physical row — one velocity
# and one echo — on the same channel, time and gate axis. Such a dataset
# has exactly one channel, so a per-channel count alone is not enough: the
# RPM / sample-interval paths must also reject the mixed measurement type
# instead of interleaving two quantities into one cadence or spectrum.


def _mixed_one_channel_data(channel: int = 6, n_rows: int = 4) -> ExtractedData:
    """Hand-built single channel carrying interleaved velocity + echo frames.

    The two quantities share channel/time/depth (mirroring the mux layout);
    only their measurement type and value scale differ, so a correct guard
    must key on the type, not the channel count.
    """
    depths = [20.0 + i for i in range(3)]
    frames: list[ChannelFrame] = []
    for step in range(n_rows):
        tbd = step * 3.2
        frames.append(
            ChannelFrame(
                channel=channel,
                block=1,
                tbd_ms=tbd,
                meas_type=MeasType.VELOCITY,
                gate_depths_mm=depths,
                values=[-100.0 - step, -50.0 - step, -10.0 - step],
            )
        )
        frames.append(
            ChannelFrame(
                channel=channel,
                block=1,
                tbd_ms=tbd,
                meas_type=MeasType.ECHO,
                gate_depths_mm=depths,
                values=[100.0 + step, 200.0 + step, 300.0 + step],
            )
        )
    return ExtractedData(file_path=Path("mux_mixed.ADD"), frames=frames)


def test_rpm_from_echo_rejects_one_channel_mixed_quantity() -> None:
    """A one-channel mux mix must not silently pick one quantity."""
    d = _mixed_one_channel_data()
    assert sorted(d.by_channel()) == [6]  # single channel: old guard passed
    assert d.meas_type is None  # ...but two measurement types are present
    with pytest.raises(ValueError, match="echo"):
        rpm_from_echo(d, dt_s=0.0032)
    with pytest.raises(ValueError, match="echo"):
        rpm_from_echo(d)  # derived-dt path is validated too


def test_mean_sample_interval_s_rejects_mixed_quantity() -> None:
    """The TBD cadence of a mixed one-channel dataset must not be averaged."""
    d = _mixed_one_channel_data()
    with pytest.raises(ValueError, match="echo"):
        mean_sample_interval_s(d)


def test_rpm_from_echo_rejects_single_channel_velocity() -> None:
    """A pure velocity channel is not echo data and must be refused."""
    depths = [20.0, 21.0]
    frames = [
        ChannelFrame(
            channel=6,
            block=1,
            tbd_ms=i * 3.2,
            meas_type=MeasType.VELOCITY,
            gate_depths_mm=depths,
            values=[-1.0 - i, -2.0 - i],
        )
        for i in range(4)
    ]
    d = ExtractedData(file_path=Path("velocity.ADD"), frames=frames)
    with pytest.raises(ValueError, match="echo"):
        rpm_from_echo(d, dt_s=0.0032)
    with pytest.raises(ValueError, match="echo"):
        mean_sample_interval_s(d)


def test_rpm_from_echo_accepts_single_channel_echo() -> None:
    """The guard stays narrow: pure one-channel echo data still computes."""
    depths = [20.0, 21.0]
    frames = [
        ChannelFrame(
            channel=4,
            block=1,
            tbd_ms=i * 3.2,
            meas_type=MeasType.ECHO,
            gate_depths_mm=depths,
            values=[10.0 + i, 20.0 + i],
        )
        for i in range(8)
    ]
    d = ExtractedData(file_path=Path("echo_only.ADD"), frames=frames)
    rpm, freq, n = rpm_from_echo(d)
    assert n == 8
    assert np.isfinite(rpm) and freq > 0.0
    assert mean_sample_interval_s(d) == pytest.approx(0.0032)


def test_setpoint_rpm_from_stem() -> None:
    assert setpoint_rpm_from_stem("650") == 650
    assert setpoint_rpm_from_stem("650.ADD") == 650
    assert setpoint_rpm_from_stem("200RPM") == 200
    assert setpoint_rpm_from_stem("200RPM_v2") == 200


def test_setpoint_rpm_from_stem_no_digits() -> None:
    with pytest.raises(ValueError):
        setpoint_rpm_from_stem("RPM")


def test_collect_results_sorted_by_setpoint() -> None:
    paths = [
        ROOT / "data/echo/200.ADD",
        ROOT / "data/echo/650.ADD",
        ROOT / "data/echo/300.ADD",
    ]
    datasets = {p.stem: extract(p) for p in paths}
    results = collect_results(datasets, dt_s=0.0032)
    setpoints = [r.setpoint_rpm for r in results]
    assert setpoints == [200, 300, 650]
    assert all(r.n_samples > 0 for r in results)
    assert all(np.isfinite(r.measured_rpm) for r in results)
