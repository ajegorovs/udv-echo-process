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

from parse_udv import ChannelFrame, ExtractedData, extract, list_add_files, list_stat_add_files


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


def plot_recording(
    extracted: ExtractedData,
    output_dir: str = "viz_output",
    dpi: int = 150,
) -> Path:
    """Plot all channels as heatmaps on a synchronized time axis.

    Each subplot is a heatmap: x = time, y = gate depth, color = value.
    The time axis spans [min(time), max(time)] across all channels,
    so that measurements from different channels are directly comparable.
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

    # Figure layout
    if n_ch <= 1:
        n_rows, n_cols = 1, 1
        figsize = (10, 6)
    elif n_ch <= 2:
        n_rows, n_cols = 1, n_ch
        figsize = (7 * n_cols, 5)
    elif n_ch <= 4:
        n_rows, n_cols = 2, 2
        figsize = (12, 8)
    else:
        n_cols = 3
        n_rows = (n_ch + n_cols - 1) // n_cols
        figsize = (5.5 * n_cols, 4 * n_rows)

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
        values = np.array([f.values for f in frames], dtype=float)  # (T, G)
        meas_label = frames[0].meas_type.value

        # Transpose: (T, G) → (G, T) so y = gate depth, x = time
        C = values.T  # (G, T)
        X, Y = np.meshgrid(times_s, gate_depths)  # both (G, T)

        # Colormap
        cmap = "RdBu_r" if meas_label == "velocity" else "viridis"
        vmin = 0 if cmap == "viridis" else -np.percentile(np.abs(values), 98)
        vmax = np.percentile(values, 98)

        ax.pcolormesh(X, Y, C, shading="auto", cmap=cmap,
                      vmin=vmin, vmax=vmax)

        ax.set_title(f"Channel {ch}  ({meas_label})")
        ax.set_xlabel(time_label)
        ax.set_ylabel("Gate Depth [mm]")

        # Fix inverted y-axis: shallowest at top
        ax.invert_yaxis()

    # Hide unused subplots
    for idx in range(len(channels), n_rows * n_cols):
        axes.flat[idx].set_visible(False)

    # Save
    out_path = Path(output_dir) / f"{extracted.file_path.stem}_viz.png"
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    print(f"Saved: {out_path}")
    return out_path


if __name__ == "__main__":
    output_dir = "viz_output"
    targets = sys.argv[1:] if len(sys.argv) > 1 else [
        *[str(p) for p in list_add_files()],
        *[str(p) for p in list_stat_add_files()],
    ]

    for t in targets:
        print(f"\n--- {t} ---")
        d = extract(t)
        plot_recording(d, output_dir=output_dir)
