"""Visualization layer: time-synchronized per-channel heatmaps.

Usage:
    from udv_echo_process import extract, plot_all
    d = extract("data/echo/650.ADD")
    plot_all(d)

Every plot function saves to ``<output_dir>/<file_stem>/<name>.png`` by
default. Pass ``return_fig=True`` to get the ``matplotlib`` figure(s) back
instead of saving (needed for in-notebook display, e.g. via
``mo.mpl.interactive``); the figure is then left open for the caller.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from udv_echo_process.parser import ChannelFrame, ExtractedData

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = "outputs"


def _channel_time_axis(
    frames: list[ChannelFrame],
) -> tuple[np.ndarray, str]:
    """Return (time_values_seconds, axis_label) for a channel's frames.

    Raw format: TBD is cumulative → use TBD/1000 as time in seconds.
    Stat format: TBD is per-block constant → use block index as time.
    """
    tbds = np.array([f.tbd_ms for f in frames], dtype=float)
    is_stat = any(f.n_profiles is not None for f in frames)

    if is_stat and tbds.std() < 1.0 and len(tbds) > 1:
        blocks = np.array([f.block for f in frames])
        return (blocks - blocks.min() + 1).astype(float), "Block"

    return tbds / 1000, "Time [s]"


def _output_path(extracted: ExtractedData, output_dir: str, name: str) -> Path:
    parent = extracted.file_path.parent.name
    stem = extracted.file_path.stem
    out = Path(output_dir) / parent / stem
    out.mkdir(parents=True, exist_ok=True)
    return out / name


def _figure_for_channels(
    extracted: ExtractedData,
) -> tuple[dict[int, list[ChannelFrame]], list[int], int, int, int, object, object]:
    """Build a subplot grid sized to the number of channels and return setup."""
    by_ch = extracted.by_channel()
    channels = sorted(by_ch.keys())
    n_ch = len(channels)
    n_rows, n_cols, figsize = _subplot_layout(n_ch)
    fig, axes = plt.subplots(
        n_rows,
        n_cols,
        figsize=figsize,
        constrained_layout=True,
        squeeze=False,
    )
    return by_ch, channels, n_ch, n_rows, n_cols, fig, axes


def _hide_unused_axes(axes, n_ch: int) -> None:
    for idx in range(n_ch, len(axes.flat)):
        axes.flat[idx].set_visible(False)


def _finish_figure(
    fig,
    extracted: ExtractedData,
    output_dir: str,
    name: str,
    dpi: int,
    return_fig: bool,
) -> Path | object:
    """Save+close the figure (returning its Path) or hand it back open."""
    if return_fig:
        return fig
    out_path = _output_path(extracted, output_dir, name)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    logger.info("Saved: %s", out_path)
    return out_path


def _subplot_layout(
    n_ch: int,
) -> tuple[int, int, tuple[float, float]]:
    if n_ch <= 1:
        return 1, 1, (10, 6)
    if n_ch <= 2:
        return 1, n_ch, (7 * n_ch, 5)
    if n_ch <= 4:
        return 2, 2, (12, 8)
    n_cols = 3
    n_rows = (n_ch + n_cols - 1) // n_cols
    return n_rows, n_cols, (5.5 * n_cols, 4 * n_rows)


def plot_recording(
    extracted: ExtractedData,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    dpi: int = 150,
    return_fig: bool = False,
) -> Path | object:
    """Plot all channels as heatmaps on a synchronized time axis.

    Each subplot is a heatmap: x = time, y = gate depth, color = value.
    The time axis spans [min(time), max(time)] across all channels,
    so that measurements from different channels are directly comparable.

    By default saves to ``<output_dir>/<file_stem>/heatmap.png`` and returns
    the ``Path``; with ``return_fig=True`` returns the open figure instead.
    """
    by_ch, channels, n_ch, _n_rows, _n_cols, fig, axes = _figure_for_channels(extracted)

    channel_times = {ch: _channel_time_axis(by_ch[ch]) for ch in channels}
    time_label = next((label for _, label in channel_times.values()), "Time [s]")
    global_times = np.concatenate([t for t, _ in channel_times.values()])
    t_min = max(0.0, float(global_times.min()))
    t_max = float(global_times.max())

    for idx, ch in enumerate(channels):
        ax = axes.flat[idx]
        frames = by_ch[ch]
        gate_depths = np.array(frames[0].gate_depths_mm)
        times_s, _ = channel_times[ch]
        values = np.array([f.values for f in frames], dtype=float)
        meas_label = frames[0].meas_type.value

        # (T, G) → (G, T): y = gate depth, x = time
        C = values.T
        X, Y = np.meshgrid(times_s, gate_depths)

        cmap = "RdBu_r" if meas_label == "velocity" else "viridis"
        vmin = 0 if cmap == "viridis" else -np.percentile(np.abs(values), 98)
        vmax = np.percentile(values, 98)

        ax.pcolormesh(X, Y, C, shading="auto", cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_xlim(t_min, t_max)
        ax.set_title(f"Channel {ch}  ({meas_label})")
        ax.set_xlabel(time_label)
        ax.set_ylabel("Gate Depth [mm]")
        ax.invert_yaxis()

    _hide_unused_axes(axes, n_ch)

    return _finish_figure(fig, extracted, output_dir, "heatmap.png", dpi, return_fig)


def plot_channel_stats(
    extracted: ExtractedData,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    dpi: int = 150,
    return_fig: bool = False,
) -> Path | object:
    """Plot per-channel gate profile statistics: mean ± std across time.

    Each subplot shows one channel with mean signal (line) and
    ±1 standard deviation (shaded band) per gate depth.

    By default saves to ``<output_dir>/<file_stem>/profiles.png`` and returns
    the ``Path``; with ``return_fig=True`` returns the open figure instead.
    """
    by_ch, channels, n_ch, _n_rows, _n_cols, fig, axes = _figure_for_channels(extracted)

    for idx, ch in enumerate(channels):
        ax = axes.flat[idx]
        frames = by_ch[ch]
        gate_depths = np.array(frames[0].gate_depths_mm)
        values = np.array([f.values for f in frames], dtype=float)
        meas_label = frames[0].meas_type.value

        mean = values.mean(axis=0)
        std = values.std(axis=0)

        ax.plot(gate_depths, mean, color="C0", lw=1.5, label="Mean")
        ax.fill_between(
            gate_depths,
            mean - std,
            mean + std,
            alpha=0.25,
            color="C0",
            label="\u00b11 std",
        )

        ax.set_title(f"Channel {ch}  ({meas_label})")
        ax.set_xlabel("Gate Depth [mm]")
        ax.set_ylabel("Signal")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    _hide_unused_axes(axes, n_ch)

    return _finish_figure(fig, extracted, output_dir, "profiles.png", dpi, return_fig)


def plot_all(
    extracted: ExtractedData,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    dpi: int = 150,
    return_fig: bool = False,
) -> tuple[Path, Path] | tuple[object, object]:
    """Convenience: generate heatmap + profiles for one file.

    Returns a ``(Path, Path)`` pair by default, or a ``(fig_heatmap,
    fig_profiles)`` pair with ``return_fig=True``.
    """
    heatmap = plot_recording(
        extracted, output_dir=output_dir, dpi=dpi, return_fig=return_fig
    )
    profiles = plot_channel_stats(
        extracted, output_dir=output_dir, dpi=dpi, return_fig=return_fig
    )
    return heatmap, profiles


def discover_data_files(data_root: str | Path = "data") -> list[Path]:
    """Find valid .ADD files under ``data/<experiment>/`` (recursive).

    A file counts as valid when its first line carries the ``ASCUDOPV``
    magic header (mirrors the parser's content guard), so misnamed images
    are skipped. ``data_root`` defaults to the repo's ``data/`` directory.
    """
    root = Path(data_root)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        for p in sorted(d.rglob("*.ADD")):
            try:
                first = p.read_text(encoding="latin-1", errors="ignore").splitlines()[0]
                if "ASCUDOPV" in first:
                    files.append(p)
            except OSError, UnicodeDecodeError:
                # Skip unreadable files (e.g. the misnamed images tracked in
                # data/) — discovery is best-effort by design.
                pass
    return files
