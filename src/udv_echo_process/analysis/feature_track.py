"""Coarse optical-flow (keypoint tracking) over consecutive frames.

Ported from ``references/wolfram/Mixer_velocimetry.nb`` ("Coarse Motion
Check"). A dense-ish grid of seed points is tracked between two frames with the
Lucas-Kanade method (``ImageFeatureTrack`` ~ ``cv2.calcOpticalFlowPyrLK``);
points that fail to track are discarded and the surviving
(start, displacement) pairs are returned / plotted.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


def track_grid_flow(
    prev: np.ndarray,
    nxt: np.ndarray,
    grid: int = 20,
) -> np.ndarray:
    """Track seed points on a ``grid``-pixel lattice between two frames.

    ``prev``/``nxt`` are grayscale 2-D arrays of equal shape. Returns an
    ``(N, 4)`` array of ``(x, y, dx, dy)`` float rows for the points that
    tracked successfully (Wolfram ``_Missing`` pairs are dropped).
    """
    prev = cv2.cvtColor(_as_uint8(prev), cv2.COLOR_GRAY2BGR)
    nxt = cv2.cvtColor(_as_uint8(nxt), cv2.COLOR_GRAY2BGR)

    h, w = prev.shape[:2]
    xs = np.arange(1.0, w, float(grid))
    ys = np.arange(1.0, h, float(grid))
    xx, yy = np.meshgrid(xs, ys)
    prev_pts = np.stack([xx.ravel(), yy.ravel()], axis=1).astype(np.float32)
    prev_pts = prev_pts.reshape(-1, 1, 2)

    next_pts, status, _err = cv2.calcOpticalFlowPyrLK(
        prev, nxt, prev_pts, None,
        winSize=(21, 21), maxLevel=3,
    )

    prev_pts = prev_pts.reshape(-1, 2)
    next_pts = next_pts.reshape(-1, 2)
    status = status.ravel().astype(bool)
    good_prev = prev_pts[status]
    good_next = next_pts[status]
    if good_next.size == 0:
        return np.empty((0, 4), dtype=np.float64)

    disp = good_next - good_prev
    return np.column_stack([good_prev, disp]).astype(np.float64)


def _as_uint8(img: np.ndarray) -> np.ndarray:
    arr = np.asarray(img)
    if arr.dtype == np.uint8:
        return arr
    lo = float(arr.min())
    hi = float(arr.max())
    if hi - lo <= 0:
        return np.zeros(arr.shape[:2], dtype=np.uint8)
    return ((arr - lo) / (hi - lo) * 255.0).astype(np.uint8)


def plot_flow(
    flow: np.ndarray,
    image_shape: tuple[int, int],
    out_path: str | Path,
    *,
    dpi: int = 150,
) -> Path:
    """Render a quiver plot of tracked displacement vectors to ``out_path``."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    h, w = image_shape[:2]
    fig, ax = plt.subplots(figsize=(w / dpi * 2, h / dpi * 2), dpi=dpi)
    if flow.size:
        x, y, dx, dy = flow.T
        q = ax.quiver(
            x, y, dx, dy,
            angles="xy", scale_units="xy", scale=1.0,
            color="tab:red",
        )
        ax.quiverkey(q, 0.95, 1.02, 5.0, "5 px", labelpos="N")
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.set_aspect("equal")
    ax.set_title("Lucas-Kanade coarse motion")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path