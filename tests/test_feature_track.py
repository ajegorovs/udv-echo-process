"""Tests for the Lucas-Kanade coarse-motion module (Mixer_velocimetry.nb port)."""

from __future__ import annotations

import numpy as np
import pytest

from udv_echo_process.analysis.feature_track import plot_flow, track_grid_flow


def _textured(h=96, w=112, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (h, w), dtype=np.uint8)


def test_track_grid_flow_reports_translation() -> None:
    shift_x, shift_y = 3, 4
    prev = _textured()
    nxt = np.roll(np.roll(prev, -shift_x, axis=1), -shift_y, axis=0)
    flow = track_grid_flow(prev, nxt, grid=20)
    assert flow.ndim == 2 and flow.shape[1] == 4
    assert len(flow) > 0
    mean_dx = flow[:, 2].mean()
    mean_dy = flow[:, 3].mean()
    assert mean_dx == pytest.approx(-shift_x, abs=3.0)
    assert mean_dy == pytest.approx(-shift_y, abs=3.0)


def test_track_grid_flow_zero_returns_empty_for_empty_frames() -> None:
    prev = np.zeros((40, 40), dtype=np.uint8)
    flow = track_grid_flow(prev, prev, grid=20)
    assert flow.size == 0


def test_plot_flow_writes_file(tmp_path) -> None:
    flow = np.array([[10.0, 10.0, 4.0, 0.0], [30.0, 10.0, 0.0, 5.0]])
    out = plot_flow(flow, (64, 96), tmp_path / "flow.png")
    assert out.exists() and out.stat().st_size > 0