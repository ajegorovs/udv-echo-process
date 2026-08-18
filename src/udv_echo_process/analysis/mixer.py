"""Optical particle imaging for mixer velocimetry.

Ported from ``references/wolfram/Mixer_velocimetry.nb`` (the "Crop Images",
"Image Cleanup", and "De-flickering via Histogram Matching" sections). Given a
high-speed sequence of single-channel frames of illuminated tracer particles,
this builds a particle-region ROI, per-frame top-hat enhancement, a
morphological segmentation mask, and histogram-matched (de-flickered) output.

Pixel coordinates are top-left origin (row, col) as used by numpy arrays;
the Wolfram notebook's bottom-up ``{x, y}`` convention is adapted accordingly.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np
from skimage import exposure, filters, measure, morphology, segmentation

_TOP_HAT_RADIUS = 1
_CLOSING_RADIUS = 5
_OPENING_RADIUS = 15


def normalize(img: np.ndarray) -> np.ndarray:
    """``ImageAdjust`` — min-max scale a float array to [0, 1]."""
    arr = np.asarray(img, dtype=np.float64)
    mn = float(np.min(arr))
    mx = float(np.max(arr))
    if mx - mn <= 0:
        return np.zeros_like(arr, dtype=np.float64)
    return (arr - mn) / (mx - mn)


def tone_map(img: np.ndarray) -> np.ndarray:
    """``ColorToneMapping`` — approximate tone map (global Drago).

    ``img`` should be float in [0, 1]; returns float in [0, 1] (single channel).
    """
    arr = np.clip(np.asarray(img, dtype=np.float32), 0.0, 1.0)
    if arr.ndim == 2:
        bgr = cv2.merge([arr, arr, arr])
    else:
        bgr = arr
    tonemap = cv2.createTonemapDrago(gamma=1.0, saturation=1.0, bias=0.85)
    mapped = tonemap.process(bgr)
    out = mapped[..., 0] if arr.ndim == 2 else mapped
    return np.nan_to_num(out, nan=0.0)


def top_hat_enhanced(img: np.ndarray, radius: int = _TOP_HAT_RADIUS) -> np.ndarray:
    """``TopHatTransform[image, Disk[radius]]`` then ``ImageAdjust``."""
    adj = normalize(img)
    toned = tone_map(adj)
    top = morphology.white_tophat(
        toned,
        footprint=morphology.disk(radius),
    )
    return normalize(top)


def particle_mask(
    image: np.ndarray,
    *,
    closing_radius: int = _CLOSING_RADIUS,
    opening_radius: int = _OPENING_RADIUS,
) -> np.ndarray:
    """Segmentation mask of the particle region.

    Mirrors the notebook chain:
    ``MorphologicalBinarize[Cluster]`` -> ``Closing[Disk 5]`` ->
    ``DeleteBorderComponents`` -> ``FillingTransform`` ->
    ``DeleteSmallComponents`` -> ``Opening[Disk 15]``.
    """
    threshold = filters.threshold_otsu(image)
    binary = image > threshold
    binary = morphology.closing(binary, footprint=morphology.disk(closing_radius))
    binary = segmentation.clear_border(binary)
    binary = morphology.remove_small_holes(binary)
    binary = morphology.remove_small_objects(binary)
    binary = morphology.opening(binary, footprint=morphology.disk(opening_radius))
    return binary.astype(bool)


def largest_component_box(binary: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box ``(y0, x0, y1, x1)`` of the largest labelled component."""
    labels = measure.label(binary, connectivity=2)
    if labels.max() < 1:
        raise ValueError("no foreground components found")
    regions = measure.regionprops(labels)
    largest = max(regions, key=lambda r: r.area)
    y0, x0, y1, x1 = largest.bbox
    return int(y0), int(x0), int(y1), int(x1)


def scale_box(
    box: tuple[int, int, int, int],
    image_shape: tuple[int, int],
    scale: float = 1.0,
) -> tuple[int, int, int, int]:
    """Grow ``box`` around its center by ``scale`` and clamp to image bounds.

    ``box`` is ``(y0, x0, y1, x1)``; returns the enlarged, clamped box.
    """
    height, width = image_shape[:2]
    y0, x0, y1, x1 = box
    ycenter = 0.5 * (y0 + y1)
    xcenter = 0.5 * (x0 + x1)
    yhalf = 0.5 * (y1 - y0) * scale
    xhalf = 0.5 * (x1 - x0) * scale
    ny0 = max(0, int(round(ycenter - yhalf)))
    nx0 = max(0, int(round(xcenter - xhalf)))
    ny1 = min(height, int(round(ycenter + yhalf)))
    nx1 = min(width, int(round(xcenter + xhalf)))
    return ny0, nx0, ny1, nx1


def crop_to_box(
    frames: Sequence[np.ndarray],
    box: tuple[int, int, int, int],
) -> list[np.ndarray]:
    """``ImageTrim`` — crop every frame to ``(y0, x0, y1, x1)``."""
    y0, x0, y1, x1 = box
    return [np.asarray(f, dtype=f.dtype)[y0:y1, x0:x1] for f in frames]


def enrich_particles(
    frames: Sequence[np.ndarray],
    *,
    tophat_radius: int = _TOP_HAT_RADIUS,
) -> tuple[list[np.ndarray], np.ndarray, tuple[int, int, int, int]]:
    """Enhance tracer particles and report the particle-domain crop box.

    Returns ``(enhanced_frames, particle_mask, particle_box)``. The mask and
    box are derived from the first frame and reused across the sequence.
    ``enhanced_frames`` are already cropped to the particle domain.
    """
    stacked = np.stack([np.asarray(f, dtype=np.float64) for f in frames])
    first_raw = top_hat_enhanced(stacked[0], radius=tophat_radius)

    mask = particle_mask(first_raw)
    if not mask.any():
        raise ValueError("no particle region detected in the first frame")
    pbox = largest_component_box(mask)
    pbox = scale_box(pbox, stacked[0].shape, scale=1.0)

    enhanced = [
        normalize(mask * top_hat_enhanced(f, radius=tophat_radius)) for f in stacked
    ]
    return crop_to_box(enhanced, pbox), mask, pbox


def deflicker(
    frames: Sequence[np.ndarray],
    reference: np.ndarray | None = None,
) -> np.ndarray:
    """Histogram-match every frame to a reference to correct illumination flicker.

    ``reference`` defaults to the first frame. Returns a float64 stack with the
    same shape/frame count as the input.
    """
    stacked = np.stack([np.asarray(f, dtype=np.float64) for f in frames])
    ref = np.asarray(reference, dtype=np.float64) if reference is not None else stacked[0]
    matched = [exposure.match_histograms(f, ref) for f in stacked]
    return np.stack(matched)