"""Tests for the visualization figure-returning mode and file discovery."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

from udv_echo_process import (
    ChannelFrame,
    ExtractedData,
    MeasType,
    extract,
    plot_all,
    plot_channel_stats,
    plot_recording,
)
from udv_echo_process.viz import discover_data_files

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
SINGLE_RAW = ROOT / "data/echo/650.ADD"
MULTI_RAW_VEL = ROOT / "data/4-sensor-velocity/200RPM_v2.ADD"


def test_plot_recording_saves_and_returns_path() -> None:
    d = extract(SINGLE_RAW)
    out = ROOT / "outputs" / "test_viz"
    result = plot_recording(d, output_dir=out, dpi=60)
    assert isinstance(result, Path)
    assert result.exists() and result.name == "heatmap.png"
    assert result.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_plot_recording_return_fig_returns_figure(tmp_path: Path) -> None:
    d = extract(SINGLE_RAW)
    fig = plot_recording(d, output_dir=tmp_path, return_fig=True)
    assert isinstance(fig, matplotlib.figure.Figure)
    import matplotlib.pyplot as plt

    plt.close(fig)
    # Nothing was saved when return_fig is used.
    assert not (tmp_path / "650" / "heatmap.png").exists()


def test_plot_channel_stats_return_fig() -> None:
    d = extract(SINGLE_RAW)
    fig = plot_channel_stats(d, return_fig=True)
    assert isinstance(fig, matplotlib.figure.Figure)
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_plot_all_return_fig_returns_pair() -> None:
    d = extract(SINGLE_RAW)
    figs = plot_all(d, return_fig=True)
    assert isinstance(figs, tuple) and len(figs) == 2
    assert all(isinstance(f, matplotlib.figure.Figure) for f in figs)
    import matplotlib.pyplot as plt

    for f in figs:
        plt.close(f)


def test_discover_data_files_finds_only_magic_udv_files() -> None:
    files = discover_data_files(ROOT / "data")
    names = [p.relative_to(ROOT / "data").as_posix() for p in files]
    # Real recordings are found...
    assert "echo/650.ADD" in names
    assert "4-sensor-velocity/200RPM_v2.ADD" in names
    assert "echo-4-sensors-2x2/300RPM.ADD" in names
    # ...and the two formerly-misnamed images (now .png/.jpg) are excluded.
    assert all(".png" not in n and ".jpg" not in n for n in names)
    # No .BDD entry: discovery is .ADD-scoped.
    assert all(n.endswith(".ADD") for n in names)
    # Every discovered file actually parses.
    for p in files:
        assert extract(p).frames, f"discovered but unparseable: {p}"


# ── mixed-quantity panels (93-column mux shape) ─────────────────────────
#
# A dual-group mux channel emits one velocity and one echo frame per physical
# row on the same channel/time/depth. Grouping panels by channel alone would
# interleave a velocity column group with an amplitude one on a single
# heatmap; panels must be keyed by (channel, meas_type) instead.


def _mixed_one_channel_data() -> ExtractedData:
    """Hand-built channel 6 carrying interleaved velocity + echo frames."""
    depths = [20.0 + i for i in range(3)]
    frames: list[ChannelFrame] = []
    for step in range(4):
        tbd = step * 3.2
        frames.append(
            ChannelFrame(
                channel=6,
                block=1,
                tbd_ms=tbd,
                meas_type=MeasType.VELOCITY,
                gate_depths_mm=depths,
                values=[-100.0 - step, -50.0 - step, -10.0 - step],
            )
        )
        frames.append(
            ChannelFrame(
                channel=6,
                block=1,
                tbd_ms=tbd,
                meas_type=MeasType.ECHO,
                gate_depths_mm=depths,
                values=[100.0 + step, 200.0 + step, 300.0 + step],
            )
        )
    return ExtractedData(file_path=Path("mux_mixed.ADD"), frames=frames)


def test_plot_recording_splits_mixed_quantity_into_two_labeled_panels() -> None:
    d = _mixed_one_channel_data()
    fig = plot_recording(d, return_fig=True)
    import matplotlib.pyplot as plt

    try:
        visible = [ax for ax in fig.axes if ax.get_visible()]
        assert len(visible) == 2
        by_title = {ax.get_title(): ax for ax in visible}
        assert set(by_title) == {"Channel 6  (velocity)", "Channel 6  (echo)"}

        velocity = np.ma.asarray(
            by_title["Channel 6  (velocity)"].collections[0].get_array()
        ).compressed()
        echo = np.ma.asarray(
            by_title["Channel 6  (echo)"].collections[0].get_array()
        ).compressed()
        # No value mixing: each panel carries exactly one quantity.
        assert velocity.size > 0 and bool(np.all(velocity < 0.0))
        assert echo.size > 0 and bool(np.all(echo >= 100.0))
    finally:
        plt.close(fig)


def test_plot_channel_stats_splits_mixed_quantity_into_two_labeled_panels() -> None:
    d = _mixed_one_channel_data()
    fig = plot_channel_stats(d, return_fig=True)
    import matplotlib.pyplot as plt

    try:
        visible = [ax for ax in fig.axes if ax.get_visible()]
        assert len(visible) == 2
        by_title = {ax.get_title(): ax for ax in visible}
        assert set(by_title) == {"Channel 6  (velocity)", "Channel 6  (echo)"}

        velocity = by_title["Channel 6  (velocity)"].get_lines()[0].get_ydata()
        echo = by_title["Channel 6  (echo)"].get_lines()[0].get_ydata()
        assert np.all(velocity < 0.0)
        assert np.all(echo >= 100.0)
    finally:
        plt.close(fig)


def test_plot_recording_single_echo_channel_stays_one_panel() -> None:
    """The (channel, meas_type) grouping does not over-split pure channels."""
    fig = plot_recording(extract(SINGLE_RAW), return_fig=True)
    import matplotlib.pyplot as plt

    try:
        visible = [ax for ax in fig.axes if ax.get_visible()]
        assert len(visible) == 1
        assert visible[0].get_title() == "Channel 4  (echo)"
    finally:
        plt.close(fig)


def test_plot_recording_multi_channel_velocity_keeps_one_panel_per_channel() -> None:
    """Distinct channels stay distinct panels, one per measured channel."""
    fig = plot_recording(extract(MULTI_RAW_VEL), return_fig=True)
    import matplotlib.pyplot as plt

    try:
        titles = {ax.get_title() for ax in fig.axes if ax.get_visible()}
        assert titles == {f"Channel {c}  (velocity)" for c in (6, 7, 8, 9)}
    finally:
        plt.close(fig)
