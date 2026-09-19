"""Axis-agnostic native-grid and pairwise support for the WP2 axis analyses.

Shared by :mod:`udv_echo_process.analysis.resolution_ladder` and, later, by the
burst, PRF and TGC/power axes of the same plan. Nothing here knows which manifest
axis it is serving or what a row's key column is called: the callers select the
rows (``select_level_rows``) and hand this module decoded grids.

What it provides, and the contract each piece carries:

- **The common views** — :func:`window` cuts a recording at a shared *duration*
  (the timestamp bound, plan §3.1) and :func:`common_support` intersects depth
  ranges, so one physical support serves every cross-level summary (plan §3.2).
- **Native-grid spatial metrics** — :func:`spatial_gradient` and
  :func:`correlation_length` are computed on a level's *own* decoded gate grid,
  before any alignment, so no quantity here ever implies an upsampled resolution.
- **Pairwise alignment** — :func:`nearest_gate_indices` samples a finer profile at
  the coarser grid's knots by one nearest native gate: no interpolation, and the
  offset never exceeds half the finer pitch. :func:`depth_ranges` formats the knot
  runs where an effect cleared its threshold.
- **The decision threshold** — :class:`EnvelopeBinding` and :func:`read_envelope`
  read the committed WP1 repeatability envelope and bind it to the manifest hash of
  the run that will be compared to it.
- **Deterministic artefacts** — :func:`csv_text` and :func:`wrap_caption` are the
  writers the axes share, so every table and caption is formatted identically.

``NativeGridError`` is the error class every consumer re-exports under its own
name (``ResolutionLadderError`` today): one class, so a caller can catch a helper
failure and an axis failure with the same name.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ValueModel


class GradientStats(ValueModel):
    """Native-grid gate-to-gate gradient of one level's supported mean profile.

    ``|Δ mean| / pitch`` in mm/s per mm on the level's own grid (never a resampled
    one), attributed to the interval's midpoint depth.
    """

    pitch_mm: float
    intervals: int
    median_abs_mm_s_per_mm: float
    max_abs_mm_s_per_mm: float
    max_depth_mm: float


class CorrelationStats(ValueModel):
    """Native-grid spatial correlation length of the same mean profile.

    ``length_mm`` is the first lag whose normalized native autocovariance of the
    mean-removed profile falls below 1/e, in mm. ``reaches_floor`` is false when it
    does not fall below the floor within ``lag_max_mm`` (half the profile), and
    ``length_mm`` is then that cap — a lower bound, not a measurement.
    """

    pitch_mm: float
    floor: float
    length_mm: float
    lag_max_mm: float
    lag_cap_gates: int
    reaches_floor: bool


class EnvelopeBinding(ValueModel):
    """The committed WP1 repeatability envelope this axis is measured against.

    ``value_mm_s`` is the largest absolute per-gate mean difference of the only
    same-settings repeat: an **upper bound** on repeatability plus uncontrolled
    drift, not a repeatability estimate on its own.
    """

    path: str
    source_sha256: str
    metric: str
    units: str
    value_mm_s: float
    gate_index: int
    depth_mm: float
    median_abs_mean_difference_mm_s: float
    scope: str
    role: str = (
        "decision threshold: an effect smaller than this bound is not "
        "distinguishable from repeat-plus-drift"
    )


class NativeGridError(ValueError):
    """A WP2-resolution input is not the ladder the plan describes.

    Raised for a manifest that is missing, holds no ``res`` rows, repeats a row,
    carries an undecodable one, gives none a usable pitch or two of them one
    pitch; for a recoded cell that no longer matches the bytes; for a missing or
    re-bound WP1 envelope; and for a pair that cannot be aligned on the coarser
    grid. The command turns it into a non-zero exit naming the reason, never a
    traceback.
    """


CORRELATION_FLOOR = 1.0 / math.e

#: The plan's stated common physical support, with the tolerance its wording allows.
GRID_UNIFORMITY_RTOL = 1e-6
TOLERANCE_S = 1e-9

#: Column order of ``resolution-levels.csv``; the field order of :class:`LevelRow`
#: is the same tuple, so the table and the model cannot drift apart.
def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


#: The WP1 envelope metric every axis compares to, as its provenance records it.
ENVELOPE_METRIC = "max_gate_abs_mean_difference_mm_s"


def read_envelope(envelope_path: Path, manifest_sha256: str) -> EnvelopeBinding:
    """Read the committed WP1 envelope and bind it to this manifest.

    The threshold is *read* from the committed WP1 artefact, not recomputed here:
    the comparison must use the number the WP1 gate declared. Its recorded
    ``manifest.sha256`` is re-checked against the manifest the ladder is built from,
    so an envelope measured on another inventory cannot supply it silently.

    Raises:
        NativeGridError: when the file is missing or unreadable, carries no
            envelope for :data:`ENVELOPE_METRIC`, records no positive finite value,
            or was generated against a different manifest.
    """
    path = Path(envelope_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NativeGridError(
            f"cannot read the WP1 envelope {path}: {exc}"
        ) from exc
    recorded = str(((document.get("manifest") or {}).get("sha256")) or "")
    if recorded != manifest_sha256:
        raise NativeGridError(
            f"the WP1 envelope {path} records manifest {recorded or '<none>'}, the "
            f"ladder is built from {manifest_sha256}; the effects must be compared to "
            "an envelope measured on the same inventory"
        )
    envelope = document.get("envelope") or {}
    metric = str(envelope.get("metric") or "")
    if metric != ENVELOPE_METRIC:
        raise NativeGridError(
            f"the WP1 envelope {path} records metric {metric!r}, expected "
            f"{ENVELOPE_METRIC!r}"
        )
    value = float(envelope.get("value_mm_s") or 0.0)
    if not math.isfinite(value) or value <= 0.0:
        raise NativeGridError(
            f"the WP1 envelope {path} records value_mm_s="
            f"{envelope.get('value_mm_s')!r}; the threshold must be positive"
        )
    return EnvelopeBinding(
        path=path.as_posix(),
        source_sha256=sha256_file(path),
        metric=metric,
        units=str(envelope.get("units") or "mm/s"),
        value_mm_s=value,
        gate_index=int(envelope.get("gate_index") or 0),
        depth_mm=float(envelope.get("depth_mm") or 0.0),
        median_abs_mean_difference_mm_s=float(
            envelope.get("median_abs_mean_difference_mm_s") or 0.0
        ),
        scope=str(
            envelope.get("scope")
            or "upper bound on same-settings repeatability plus uncontrolled drift"
        ),
    )


#: Manifest cells re-checked against the decoded recording, in row-column order.
def window(
    values: np.ndarray, time_s: np.ndarray, window_s: float
) -> np.ndarray:
    """The leading ``window_s`` of a recording, cut by the recorded timestamps.

    Cutting on the timestamp means every level is cut at the same *duration* even
    though their profile counts differ (plan §3.1).
    """
    return values[time_s <= time_s[0] + window_s + TOLERANCE_S]


def common_support(ranges: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The intersection of the given ``(depth_min_mm, depth_max_mm)`` ranges.

    Raises:
        NativeGridError: when no range is given, a range is not a finite
            increasing interval, or the intersection is empty.
    """
    if not ranges:
        raise NativeGridError("common_support needs at least one depth range")
    for low, high in ranges:
        if not (math.isfinite(low) and math.isfinite(high) and low < high):
            raise NativeGridError(
                f"every depth range must be finite and increasing, got ({low}, {high})"
            )
    low = max(first for first, _ in ranges)
    high = min(second for _, second in ranges)
    if not low < high:
        raise NativeGridError(
            f"no common physical support: the depth ranges overlap on nothing better "
            f"than [{low}, {high}] mm"
        )
    return float(low), float(high)


def in_support(depths: np.ndarray, support: tuple[float, float]) -> np.ndarray:
    """Boolean mask of the native gates inside the common physical support."""
    return (depths >= support[0] - TOLERANCE_S) & (depths <= support[1] + TOLERANCE_S)


def nearest_gate_indices(grid: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Index of the nearest entry of ``grid`` for every value in ``targets``.

    This is the only alignment this module uses: a finer profile is *sampled* at the
    coarser knots, so an offset never exceeds half the finer grid's own pitch.
    """
    values = np.asarray(grid, dtype=float).reshape(-1)
    wanted = np.asarray(targets, dtype=float).reshape(-1)
    if values.size == 0:
        raise NativeGridError("nearest_gate_indices needs a non-empty grid")
    if wanted.size == 0:
        return np.empty(0, dtype=int)
    if values.size == 1:
        return np.zeros(wanted.size, dtype=int)
    return np.abs(values[None, :] - wanted[:, None]).argmin(axis=1).astype(int)


def grid_and_profile(
    depths_mm: np.ndarray, profile_mm_s: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Validate one native grid and its profile; return both and the pitch."""
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    profile = np.asarray(profile_mm_s, dtype=float).reshape(-1)
    if depths.size != profile.size:
        raise NativeGridError(
            f"the depth grid ({depths.size}) and the profile ({profile.size}) must "
            "hold one entry per gate"
        )
    if depths.size < 2:
        raise NativeGridError(
            f"at least two gates are needed for a native spatial metric, got "
            f"{depths.size}"
        )
    if not (np.all(np.isfinite(depths)) and np.all(np.isfinite(profile))):
        raise NativeGridError("the native grid and its profile must be finite")
    steps = np.diff(depths)
    pitch = float(steps.mean())
    if not np.all(steps > 0.0) or not math.isfinite(pitch) or pitch <= 0.0:
        raise NativeGridError(
            f"the native gate pitch must be positive and increasing, got steps "
            f"including {steps.min()!r}"
        )
    deviation = float(np.abs(steps - pitch).max())
    if deviation > GRID_UNIFORMITY_RTOL * pitch:
        raise NativeGridError(
            f"the native gate grid is not uniform: steps deviate by {deviation:.3g} mm "
            f"from the {pitch:g} mm mean pitch"
        )
    return depths, profile, pitch


def spatial_gradient(depths_mm: np.ndarray, profile_mm_s: np.ndarray) -> GradientStats:
    """Native-grid gate-to-gate gradient of one depth-resolved mean profile.

    Computed on the profile's *own* grid, before any cross-level alignment:
    ``|mean[k + 1] - mean[k]| / pitch`` in mm/s per mm, at the interval midpoint. A
    relative-spread statement, not a shear-rate measurement.

    Raises:
        NativeGridError: for fewer than two gates, a non-increasing or
            non-uniform grid, or a depth grid that does not match the profile.
    """
    depths, profile, pitch = grid_and_profile(depths_mm, profile_mm_s)
    gradient = np.abs(np.diff(profile)) / pitch
    worst = int(np.argmax(gradient))
    return GradientStats(
        pitch_mm=pitch,
        intervals=int(gradient.size),
        median_abs_mm_s_per_mm=float(np.median(gradient)),
        max_abs_mm_s_per_mm=float(gradient[worst]),
        max_depth_mm=float(0.5 * (depths[worst] + depths[worst + 1])),
    )


def correlation_length(
    depths_mm: np.ndarray, profile_mm_s: np.ndarray
) -> CorrelationStats:
    """Native-grid spatial correlation length of one depth-resolved mean profile.

    The mean-removed profile's normalized autocovariance (biased, divided by
    ``N · var``) is evaluated on its own grid; the length is the first lag whose
    value falls below 1/e, in mm. The lag grid stops at ``floor((gates - 1) / 2)``
    gates — half the supported profile.

    Raises:
        NativeGridError: for fewer than two gates, a constant profile (its
            autocovariance is undefined), or a non-uniform or mismatched grid.
    """
    _depths, profile, pitch = grid_and_profile(depths_mm, profile_mm_s)
    centred = profile - profile.mean()
    variance = float(np.mean(np.square(centred)))
    if variance == 0.0:
        raise NativeGridError(
            "a constant mean profile has no spatial correlation length: this gate "
            "grid resolves no variation"
        )
    autocovariance = (
        np.correlate(centred, centred, mode="full")[centred.size - 1 :]
        / (centred.size * variance)
    )
    cap = (centred.size - 1) // 2
    below = np.flatnonzero(autocovariance[: cap + 1] < CORRELATION_FLOOR)
    lag = int(below[0]) if below.size else cap
    return CorrelationStats(
        pitch_mm=pitch,
        floor=float(CORRELATION_FLOOR),
        length_mm=float(lag * pitch),
        lag_max_mm=float(cap * pitch),
        lag_cap_gates=cap,
        reaches_floor=bool(below.size),
    )


def depth_ranges(knots: np.ndarray, flagged: np.ndarray) -> str:
    """Depth ranges of the flagged knots as ``low..high``, runs joined by ``"; "``.

    The flag exists only at the common knots, so a range names the first and last
    flagged knot of one contiguous run of the knot grid.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_flagged in enumerate(bool(flag) for flag in flagged):
        if is_flagged and start is None:
            start = index
        elif not is_flagged and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, flagged.size - 1))
    return "; ".join(f"{knots[low]:.6g}..{knots[high]:.6g}" for low, high in runs)


def csv_text(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> str:
    """Render rows as CSV text (LF endings, one trailing newline)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: format_cell(row[column]) for column in columns})
    return buffer.getvalue()


def wrap_caption(text: str, width: int = 168) -> str:
    """Wrap the caption into the figure's footnote without breaking words."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + len(word) + 1 <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


