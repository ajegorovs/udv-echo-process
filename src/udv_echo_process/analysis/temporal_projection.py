"""Chunk-wise temporal projections for single-channel images.

Computes per-pixel Min, Max, Mean, and StandardDeviation across a stack of
identically sized single-channel frames using a memory-bounded, streaming
algorithm that never holds the whole stack in memory.

Ported from ``references/wolfram/TemporalProjections_v1.1.0.wl``. The frames
are processed in chunks; partial states are merged with a parallel-reducible
Welford-style ``M2`` (sum of squared differences) accumulator, so the result is
exact and single-pass over the frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

_CONVENTIONS = ("sample", "population")


def _chunk_stats(chunk: np.ndarray) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reduce one chunk of frames into its exact aggregation state.

    Returns ``(count, min, max, mean, m2)`` where ``m2`` is the sum of squared
    deviations used for the (optionally sample-corrected) variance.
    """
    arr = chunk.astype(np.float64)  # (n, H, W)
    count = arr.shape[0]
    mn = arr.min(axis=0)
    mx = arr.max(axis=0)
    mean = arr.mean(axis=0)
    m2 = ((arr - mean) ** 2).sum(axis=0)
    return count, mn, mx, mean, m2


def _merge_states(
    n_a: int, min_a: np.ndarray, max_a: np.ndarray, mean_a: np.ndarray, m2_a: np.ndarray,
    n_b: int, min_b: np.ndarray, max_b: np.ndarray, mean_b: np.ndarray, m2_b: np.ndarray,
) -> tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Merge two aggregation states exactly (parallel-reduction step)."""
    n = n_a + n_b
    mn = np.minimum(min_a, min_b)
    mx = np.maximum(max_a, max_b)
    delta = mean_b - mean_a
    mean = mean_a + delta * (float(n_b) / n)
    m2 = m2_a + m2_b + delta**2 * (float(n_a * n_b) / n)
    return n, mn, mx, mean, m2


@dataclass(frozen=True)
class TemporalProjectionResult:
    """Result of a temporal projection over an image stack.

    ``count`` is the number of frames projected. Each array has the shape of
    a single frame (H, W).
    """

    count: int
    min_array: np.ndarray
    max_array: np.ndarray
    mean_array: np.ndarray
    std_array: np.ndarray


def temporal_projections(
    frames: Sequence[np.ndarray] | tuple[Callable[[np.ndarray], Sequence[np.ndarray]], int],
    *,
    chunk_size: int = 32,
    convention: str = "sample",
) -> TemporalProjectionResult:
    """Compute per-pixel temporal projections over a stack of single-channel frames.

    ``frames`` may be either a sequence of identically sized 2-D (H, W) arrays,
    or a ``(get_chunk, frame_count)`` pair where ``get_chunk`` accepts an array
    of 0-based frame indices and returns a list of 2-D arrays, enabling
    file-backed or otherwise streamed processing.

    ``chunk_size`` limits how many frames are materialized at once.
    ``convention`` is ``"sample"`` (divide variance by ``n-1``, the default) or
    ``"population"`` (divide by ``n``).
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be a positive integer, got {chunk_size}")
    if convention not in _CONVENTIONS:
        raise ValueError(f"convention must be one of {_CONVENTIONS}, got {convention!r}")

    get_chunk, frame_count = _resolve_source(frames)

    shape: tuple[int, int] | None = None
    n_total = 0
    merged = None

    for start in range(0, frame_count, chunk_size):
        stop = min(start + chunk_size, frame_count)
        chunk_frames = get_chunk(np.arange(start, stop))
        if not chunk_frames:
            raise ValueError(f"chunk beginning at frame {start} returned no frames")

        n_c, mn_c, mx_c, mean_c, m2_c = _chunk_stats(_validate(chunk_frames, shape))
        if shape is None:
            shape = m2_c.shape

        if merged is None:
            merged = (n_c, mn_c, mx_c, mean_c, m2_c)
        else:
            merged = _merge_states(*merged, n_c, mn_c, mx_c, mean_c, m2_c)
        n_total += n_c

    if merged is None:
        raise ValueError("no frames were supplied")

    n_total, mn, mx, mean, m2 = merged
    denominator = float(n_total - 1) if convention == "sample" else float(n_total)
    if denominator <= 0:
        raise ValueError(
            f"{convention} standard deviation requires more than one frame, got {n_total}"
        )
    variance = np.clip(m2 / denominator, 0.0, np.inf)
    std = np.sqrt(variance)

    return TemporalProjectionResult(
        count=n_total,
        min_array=mn,
        max_array=mx,
        mean_array=mean,
        std_array=std,
    )


def _resolve_source(
    frames: Sequence[np.ndarray] | tuple[Callable[[np.ndarray], Sequence[np.ndarray]], int],
) -> tuple[Callable[[np.ndarray], Sequence[np.ndarray]], int]:
    if isinstance(frames, tuple) and len(frames) == 2:
        get_chunk, frame_count = frames
        if frame_count < 1:
            raise ValueError("frame_count must be a positive integer")
        return get_chunk, frame_count
    arr = np.asarray(frames, dtype=object)
    if arr.size == 0:
        raise ValueError("no frames were supplied")
    length = len(frames)
    return lambda ids: [frames[i] for i in ids], length


def _validate(
    chunk_frames: Sequence[np.ndarray],
    shape: tuple[int, int] | None,
) -> np.ndarray:
    if not chunk_frames:
        raise ValueError("no frames were supplied")
    stacked = []
    for frame in chunk_frames:
        arr = np.asarray(frame)
        if arr.ndim != 2:
            raise ValueError(f"frames must be single-channel 2-D arrays, got {arr.ndim}-D")
        if shape is not None and arr.shape != shape:
            raise ValueError(
                f"all frames must have identical dimensions, got {arr.shape} != {shape}"
            )
        stacked.append(arr)
    return np.stack(stacked)
