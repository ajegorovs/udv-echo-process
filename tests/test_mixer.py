"""Tests for the mixer particle-image pipeline (Mixer_velocimetry.nb port)."""

from __future__ import annotations

import numpy as np
import pytest

from udv_echo_process.analysis.mixer import (
    crop_to_box,
    deflicker,
    largest_component_box,
    normalize,
    particle_mask,
    scale_box,
    top_hat_enhanced,
)


def _specks(h=80, w=80, seed=3):
    """A dense field of 1 px bright specks in a ~40x40 region.

    Tiny specks survive the size-1 top-hat; the morphological chain's final
    ``Opening[Disk15]`` (31x31 element) requires a particle region much larger
    than the element to survive — so the region must be ~40x40, as in real data.
    """
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w), dtype=np.uint8)
    mask = rng.random((40, 40)) < 0.35
    img[15:55, 15:55][mask] = 200
    return img


def test_normalize_scales_to_unit_range() -> None:
    img = np.array([[0.0, 5.0, 15.0]])
    assert normalize(img).min() == 0.0
    assert normalize(img).max() == 1.0
    flat = normalize(np.full((2, 2), 3.0))
    assert np.all(flat == 0.0)


def test_top_hat_enhanced_shape_and_range() -> None:
    out = top_hat_enhanced(_specks())
    assert out.shape == (80, 80)
    assert out.min() >= 0.0
    assert out.max() <= 1.0


def test_particle_mask_detects_blobs() -> None:
    mask = particle_mask(top_hat_enhanced(_specks()))
    assert mask.dtype == np.bool_
    assert mask.sum() > 0


def test_largest_component_box_picks_biggest_blob() -> None:
    mask = particle_mask(top_hat_enhanced(_specks()))
    y0, x0, y1, x1 = largest_component_box(mask)
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2
    # centre of the dense speck region at rows 15:55, cols 15:55
    assert cx == pytest.approx(35.0, abs=8)
    assert cy == pytest.approx(35.0, abs=8)


def test_scale_box_grows_and_clamps() -> None:
    shape = (100, 100)
    box = (40, 40, 60, 60)
    grown = scale_box(box, shape, scale=2.0)
    assert grown[0] < box[0] and grown[2] > box[2]
    assert grown[1] < box[1] and grown[3] > box[3]

    edge = scale_box((0, 0, 20, 20), shape, scale=10.0)
    assert edge[0] >= 0 and edge[1] >= 0
    assert edge[2] <= 100 and edge[3] <= 100


def test_crop_to_box_slices_every_frame() -> None:
    frames = [np.arange(100).reshape(10, 10).astype(np.uint8)] * 3
    out = crop_to_box(frames, (2, 3, 7, 8))
    assert len(out) == 3
    assert out[0].shape == (5, 5)
    assert out[0][0, 0] == 2 * 10 + 3


def test_deflicker_matches_reference_histogram() -> None:
    rng = np.random.default_rng(0)
    ref = rng.integers(0, 180, (40, 40)).astype(np.uint8)
    img = np.clip(ref.astype(float) + 30, 0, 255).astype(np.uint8)
    matched = deflicker([img], reference=ref)[0]
    assert np.allclose(np.sort(matched), np.sort(ref.astype(float)), atol=6)


def test_deflicker_default_reference_is_first_frame() -> None:
    rng = np.random.default_rng(1)
    a = rng.integers(0, 180, (30, 30)).astype(np.uint8)
    b = np.clip(a.astype(float) + 80, 0, 255).astype(np.uint8)
    out = deflicker([a, b])
    assert out.ndim == 3
    assert out.shape[0] == 2
    assert np.allclose(np.sort(out[1]), np.sort(a.astype(float)), atol=6)