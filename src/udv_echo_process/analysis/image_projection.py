"""Temporal projections over a folder of image frames.

Wraps ``temporal_projections`` with image loading and output saving so a
sequence of single-channel frame files (e.g. high-speed camera BMPs of
illuminated tracer particles) can be reduced to per-pixel Min / Max / Mean /
StandardDeviation images without loading every frame into memory.

Applies the "Temporal Projections" step of
``references/wolfram/Mixer_velocimetry.nb`` (via the ported
``TemporalProjections_v1.1.0.wl`` logic).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from udv_echo_process.analysis.temporal_projection import (
    TemporalProjectionResult,
    temporal_projections,
)

IMG_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def frame_paths(folder: str | Path) -> list[Path]:
    """Return sorted image paths in ``folder`` (any supported extension)."""
    paths = [
        p
        for p in Path(folder).iterdir()
        if p.is_file() and p.suffix.lower() in IMG_EXTS
    ]
    return sorted(paths)


def select_frames(
    paths: list[Path],
    *,
    step: int = 1,
    max_frames: int | None = None,
) -> list[Path]:
    """Pick a (sample) subsequence of ``paths``.

    Takes every ``step``-th path (starting at the first) and caps the total
    at ``max_frames`` when given.
    """
    if step < 1:
        raise ValueError(f"step must be a positive integer, got {step}")
    selected = paths[::step]
    if max_frames is not None and max_frames >= 1:
        selected = selected[:max_frames]
    return list(selected)


def project_images(
    paths: list[Path] | str,
    *,
    step: int = 1,
    max_frames: int | None = None,
    chunk_size: int = 32,
    convention: str = "sample",
) -> TemporalProjectionResult:
    """Load grayscale frames from ``paths`` and reduce them to temporal projections.

    Frames are loaded lazily in chunks via the ``temporal_projections``
    streaming interface, so only ``~chunk_size`` frames are in memory at once.
    If ``paths`` is a folder path it is globbed and sorted first.
    """
    if isinstance(paths, (str, Path)):
        paths = frame_paths(paths)
    selected = select_frames(paths, step=step, max_frames=max_frames)
    if not selected:
        raise ValueError("no image frames were found")

    def get_chunk(ids: np.ndarray) -> list[np.ndarray]:
        from PIL import Image

        frames = []
        for i in ids:
            im = Image.open(selected[int(i)])
            if im.mode != "L":
                im = im.convert("L")
            frames.append(np.asarray(im))
        return frames

    return temporal_projections(
        (get_chunk, len(selected)),
        chunk_size=chunk_size,
        convention=convention,
    )


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    mn = float(np.nanmin(arr))
    mx = float(np.nanmax(arr))
    if mx - mn <= 0:
        return np.zeros(arr.shape, dtype=np.uint8)
    out = (arr - mn) / (mx - mn) * 255.0
    return out.astype(np.uint8)


def save_projections(
    result: TemporalProjectionResult,
    out_dir: str | Path,
    *,
    prefix: str = "",
) -> dict[str, Path]:
    """Write the projection arrays as PNG images.

    Each map is min-max normalized to 0..255 for viewing (mirroring the
    notebook's ``ImageAdjust`` display convention). Returns a dict of
    ``name -> written path``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    arrays = {
        "min": result.min_array,
        "max": result.max_array,
        "mean": result.mean_array,
        "std": result.std_array,
    }

    written: dict[str, Path] = {}
    for name, arr in arrays.items():
        path = out_dir / f"{prefix}{name}.png"
        from PIL import Image

        Image.fromarray(_to_uint8(arr), mode="L").save(path)
        written[name] = path
    return written