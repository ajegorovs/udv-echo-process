"""Per-gate time filtering — a sequence-capable smoothing/outlier layer.

Filters each gate's time series along axis 0 (time). Driving need (settled
2026-09-09, `docs/filter-design.md` §7): pre-process turbulent velocity
fields — smooth / remove outliers on the *measured* samples first, then
interpolate across gaps. Not aliasing correction (recording params are
configured to minimise that).

Sequence is native: ``filter`` is a closed ``ChannelSeries -> ChannelSeries``
transform (per `docs/pipeline-conventions.md` §4) and ``filter_sequence`` is
a plain fold — ``filter_sequence(s, [a, b]) == filter(filter(s, a), b)``.
Composition with ``resample`` (``process/sync.py``) is caller-chosen in
either order; nothing bakes an order into either stage.

Cadence rule (per method, not per layer):

- Index-window methods (MEDIAN / MEAN / SAVGOL) operate over *consecutive
  measured profiles*, so they are well-defined on the raw gappy series —
  that is the point (smooth the measurements, not the interpolated fiction).
- TV (ROF) is defined over sample *indices* and assumes uniform spacing, so
  it is a post-``resample`` filter — rejected on non-uniform input.

Always per gate, independent 1-D along time (never coupling neighbouring
gates); only ``values`` is transformed.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from pydantic import Field
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import savgol_filter
from skimage.restoration import denoise_tv_chambolle

from udv_echo_process.models.base import Model
from udv_echo_process.models.channel_series import ChannelSeries


class FilterMethod(str, Enum):
    """Fixed set of filter methods (never a bare ``str``)."""

    MEDIAN = "median"  # outlier-robust — the "remove outliers" tool
    MEAN = "mean"  # boxcar average — the "average the signal" tool
    SAVGOL = "savgol"  # Savitzky–Golay (smooth, preserves higher moments)
    TV = "tv"  # ROF total-variation (edge-preserving; uniform cadence only)


class FilterParams(Model):
    """Bundled per-method knobs, defaulted for every method (cf. InterpParams).

    Parameters live here rather than as flat ``FilterSpec`` fields so each
    method's knobs stay bundled and typed, and adding one never changes the
    ``filter(series, spec)`` call site. Only some fields are read per method:

    - MEDIAN / MEAN read ``window`` (boxcar width in samples).
    - SAVGOL reads ``window`` (must be odd and exceed ``polyorder``) and
      ``polyorder``.
    - TV reads ``weight`` (the ROF lambda; larger = smoother, data-scale
      dependent) and ``iterations`` (Chambolle solver cap).
    """

    window: int = Field(default=5, ge=1)  # MEDIAN/MEAN/SAVGOL, samples
    polyorder: int = Field(default=2, ge=0)  # SAVGOL (< window)
    weight: float = Field(default=1.0, gt=0)  # TV lambda (larger = smoother)
    iterations: int = Field(default=200, ge=1)  # TV solver cap


class FilterSpec(Model):
    """Parameters for one filtering pass over a ``ChannelSeries`` along time."""

    method: FilterMethod = FilterMethod.MEDIAN
    params: FilterParams = Field(default_factory=FilterParams)


def filter(series: ChannelSeries, spec: FilterSpec) -> ChannelSeries:
    """Apply one filter to each gate of ``series`` along time (axis 0).

    Pure transform: returns a *new* ``ChannelSeries`` on the same grid/gates
    with ``values`` filtered per gate; input never mutated; metadata + a deep
    copy of ``config`` carry through.
    """
    _require_filterable(series, spec)
    values = _apply(series.values, spec)
    return ChannelSeries(
        channel=series.channel,
        meas_type=series.meas_type,
        gate_depths_mm=list(series.gate_depths_mm),
        time_s=series.time_s,
        values=values,
        config=series.config.model_copy(deep=True),
    )


def filter_sequence(series: ChannelSeries, specs: list[FilterSpec]) -> ChannelSeries:
    """Apply ``specs`` in order — the sequence-of-filters entry point.

    A plain fold over ``filter``; composes freely with ``resample`` in either
    order (e.g. smooth the raw series, then interpolate across gaps).
    """
    for spec in specs:
        series = filter(series, spec)
    return series


# ── helpers ──────────────────────────────────────────────────────────────


def _apply(values: np.ndarray, spec: FilterSpec) -> np.ndarray:
    p = spec.params
    if spec.method is FilterMethod.MEDIAN:
        return median_filter(values, size=p.window, axes=0, mode="nearest")
    if spec.method is FilterMethod.MEAN:
        return uniform_filter1d(values, size=p.window, axis=0, mode="nearest")
    if spec.method is FilterMethod.SAVGOL:
        return np.column_stack(
            [
                savgol_filter(values[:, g], p.window, p.polyorder)
                for g in range(values.shape[1])
            ]
        )
    # TV — per-gate 1-D (never a 2-D image coupling gates)
    out = np.empty_like(values, dtype=np.float64)
    for g in range(values.shape[1]):
        out[:, g] = denoise_tv_chambolle(
            values[:, g], weight=p.weight, max_num_iter=p.iterations
        )
    return out


def _require_filterable(series: ChannelSeries, spec: FilterSpec) -> None:
    if series.time_count < 2:
        raise ValueError(
            f"filter: channel {series.channel} has {series.time_count} sample(s); "
            "need at least two time samples"
        )
    if series.gate_count == 0:
        raise ValueError(f"filter: channel {series.channel} has no gates")
    if not np.isfinite(series.values).all():
        n_bad = int(np.count_nonzero(~np.isfinite(series.values)))
        raise ValueError(
            f"filter: channel {series.channel} values hold {n_bad} non-finite "
            "entr(y/ies); clean the source before filtering"
        )
    p = spec.params
    if spec.method is FilterMethod.SAVGOL:
        if p.window <= p.polyorder:
            raise ValueError(
                f"filter: SAVGOL window ({p.window}) must exceed polyorder "
                f"({p.polyorder})"
            )
        if p.window % 2 == 0:
            raise ValueError(
                f"filter: SAVGOL window ({p.window}) must be odd "
                "(scipy savgol_filter requires an odd window_length)"
            )
    if spec.method is FilterMethod.TV and not _is_uniform(series.time_s):
        raise ValueError(
            "filter: TV is defined over sample indices and needs uniform "
            "cadence; run resample() first (or use MEDIAN/MEAN/SAVGOL)"
        )


def _is_uniform(t: np.ndarray, rtol: float = 0.05) -> bool:
    """Nominal-cadence check: interior intervals within ``rtol`` of their median.

    The final interval is excluded because ``resample`` (``sync.py``) emits a
    shortened final interval when the span is not an exact multiple of
    ``dt_s`` — that grid is the intended post-``resample`` input for TV.
    ``rtol`` defaults to 5%: the echo fixture carries periodic ~3% timebase
    jitter (3.1 vs 3.2 ms intervals), while a genuinely gappy multiplexed
    series misses whole visits (~15x the intra-visit cadence) and fails by
    orders of magnitude.
    """
    dt = np.diff(t)
    if dt.size < 2:
        return True
    inner = dt[:-1]
    return bool(np.allclose(inner, np.median(inner), rtol=rtol))
