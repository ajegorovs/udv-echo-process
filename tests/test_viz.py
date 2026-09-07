"""Tests for the visualization figure-returning mode and file discovery."""

from __future__ import annotations

from pathlib import Path

import matplotlib

from udv_echo_process import extract, plot_all, plot_channel_stats, plot_recording
from udv_echo_process.viz import discover_data_files

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
SINGLE_RAW = ROOT / "data/echo/650.ADD"


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
