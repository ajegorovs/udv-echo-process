"""Visualization layer: time-synchronized per-channel heatmaps.

Usage:
    from viz_layer import plot_recording
    from parse_udv import extract
    d = extract("file.ADD")
    plot_recording(d)
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize

from parse_udv import ChannelFrame, ExtractedData, extract


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
    output_dir: str = "viz_output",
    dpi: int = 150,
) -> Path:
    """Plot all channels as heatmaps on a synchronized time axis.

    Each subplot is a heatmap: x = time, y = gate depth, color = value.
    The time axis spans [min(time), max(time)] across all channels,
    so that measurements from different channels are directly comparable.

    Saves to ``<output_dir>/<file_stem>/heatmap.png``.
    """
    by_ch = extracted.by_channel()
    channels = sorted(by_ch.keys())
    n_ch = len(channels)

    # Global time range across all channels
    global_times = []
    time_label = "Time [s]"
    for ch in channels:
        t, lbl = _channel_time_axis(by_ch[ch])
        global_times.extend(t)
        time_label = lbl

    t_min = max(0.0, min(global_times))
    t_max = max(global_times)

    n_rows, n_cols, figsize = _subplot_layout(n_ch)

    fig, axes = plt.subplots(
        n_rows, n_cols,
        figsize=figsize,
        constrained_layout=True,
        squeeze=False,
    )

    for idx, ch in enumerate(channels):
        row, col = divmod(idx, n_cols)
        ax = axes[row, col]

        frames = by_ch[ch]
        gate_depths = np.array(frames[0].gate_depths_mm)
        times_s, _ = _channel_time_axis(frames)
        values = np.array([f.values for f in frames], dtype=float)
        meas_label = frames[0].meas_type.value

        # (T, G) → (G, T): y = gate depth, x = time
        C = values.T
        X, Y = np.meshgrid(times_s, gate_depths)

        cmap = "RdBu_r" if meas_label == "velocity" else "viridis"
        vmin = 0 if cmap == "viridis" else -np.percentile(np.abs(values), 98)
        vmax = np.percentile(values, 98)

        ax.pcolormesh(X, Y, C, shading="auto", cmap=cmap,
                      vmin=vmin, vmax=vmax)

        ax.set_title(f"Channel {ch}  ({meas_label})")
        ax.set_xlabel(time_label)
        ax.set_ylabel("Gate Depth [mm]")
        ax.invert_yaxis()

    for idx in range(len(channels), n_rows * n_cols):
        axes.flat[idx].set_visible(False)

    out_path = _output_path(extracted, output_dir, "heatmap.png")
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    print(f"Saved: {out_path}")
    return out_path


def plot_channel_stats(
    extracted: ExtractedData,
    output_dir: str = "viz_output",
    dpi: int = 150,
) -> Path:
    """Plot per-channel gate profile statistics: mean ± std across time.

    Each subplot shows one channel with mean signal (line) and
    ±1 standard deviation (shaded band) per gate depth.

    Saves to ``<output_dir>/<file_stem>/profiles.png``.
    """
    by_ch = extracted.by_channel()
    channels = sorted(by_ch.keys())
    n_ch = len(channels)
    n_rows, n_cols, figsize = _subplot_layout(n_ch)

    fig, axes = plt.subplots(
        n_rows, n_cols,
        figsize=figsize,
        constrained_layout=True,
        squeeze=False,
    )

    for idx, ch in enumerate(channels):
        row, col = divmod(idx, n_cols)
        ax = axes[row, col]

        frames = by_ch[ch]
        gate_depths = np.array(frames[0].gate_depths_mm)
        values = np.array([f.values for f in frames], dtype=float)
        meas_label = frames[0].meas_type.value

        mean = values.mean(axis=0)
        std = values.std(axis=0)

        ax.plot(gate_depths, mean, color="C0", lw=1.5, label="Mean")
        ax.fill_between(gate_depths, mean - std, mean + std,
                        alpha=0.25, color="C0", label="\u00b11 std")

        ax.set_title(f"Channel {ch}  ({meas_label})")
        ax.set_xlabel("Gate Depth [mm]")
        ax.set_ylabel("Signal")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    for idx in range(len(channels), n_rows * n_cols):
        axes.flat[idx].set_visible(False)

    out_path = _output_path(extracted, output_dir, "profiles.png")
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    print(f"Saved: {out_path}")
    return out_path


def plot_all(extracted: ExtractedData, output_dir: str = "viz_output", dpi: int = 150) -> None:
    """Convenience: generate heatmap + profiles for one file."""
    plot_recording(extracted, output_dir=output_dir, dpi=dpi)
    plot_channel_stats(extracted, output_dir=output_dir, dpi=dpi)


def _discover_data_files() -> list[Path]:
    """Find valid .ADD files in data-* directories (recursive)."""
    files: list[Path] = []
    for d in sorted(Path(".").glob("data-*")):
        if d.is_dir():
            for p in sorted(d.rglob("*.ADD")):
                try:
                    first = p.read_text(encoding="latin-1", errors="ignore").splitlines()[0]
                    if "ASCUDOPV" in first:
                        files.append(p)
                except Exception:
                    pass
    return files


if __name__ == "__main__":
    output_dir = "viz_output"
    targets = sys.argv[1:] if len(sys.argv) > 1 else _discover_data_files()

    for t in targets:
        print(f"\n--- {t} ---")
        d = extract(t)
        plot_all(d, output_dir=output_dir)
