"""Per-channel time resampling — the interpolation layer (pipeline Stage 3).

One ``ChannelSeries`` is one sensor's measurement over time: its own real
``time_s`` and a ``(T, G)`` ``values`` grid. ``resample`` interpolates each
gate independently along axis 0 (time) onto a caller-chosen time grid, per
`docs/interpolation-design.md` §7/§8 — the "as-if-simultaneous per-sensor
series" step of the sync pipeline.

Contract (settled in that doc):

- **Closed transform.** ``resample(series, spec, *, times | dt_s) ->
  ChannelSeries``; re-interpolation is just applying it again. Two-phase
  fit/sample is deliberately not built.
- **Recipe is a ``Spec`` in ``process/``** (not ``models/``): ``InterpSpec``
  = method (constrained ``Enum``) + extrapolation policy + NaN policy +
  bundled per-method params. No knots are copied into it and no live
  interpolant is stored; scipy objects are materialized per call.
- **Per-gate 1-D, vectorized.** The shared knot vector is ``time_s``;
  ``gate_depths_mm`` / axis 1 are untouched (spatial interpolation is out of
  scope).
- **Extrapolation is explicit** — default ``"error"``, never the silent
  endpoint clamp ``np.interp`` applies by default.
- **Methods are honest about what is recoverable:** ``LINEAR`` (default)
  cannot overshoot across the inter-visit gaps of a multiplexed recording;
  ``MONOTONE`` (PCHIP) is shape-preserving; ``CUBIC`` / ``BSPLINE`` are for
  uniform, gap-free data where smoothness is safe and overshoot acceptable.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

import numpy as np
from pydantic import Field
from scipy.interpolate import CubicSpline, PchipInterpolator, make_interp_spline

from udv_echo_process.models.base import Model
from udv_echo_process.models.channel_series import ChannelSeries

Extrapolation = Literal["error", "nan", "nearest"]
NanPolicy = Literal["error", "propagate"]


class InterpMethod(str, Enum):
    """Fixed set of interpolation methods (never a bare ``str``).

    ``LINEAR`` is the default and the "honest" regime: piecewise-linear
    interpolation cannot overshoot, so it is safe across the inter-visit gaps
    of a multiplexed recording. ``MONOTONE`` is PCHIP-style shape-preserving
    (C1, no local overshoot). ``CUBIC`` (not-a-knot cubic spline) and
    ``BSPLINE`` (order from ``InterpParams.spline_order``) may overshoot
    between knots and are intended for uniform, gap-free data (e.g. the echo
    fixture).
    """

    LINEAR = "linear"
    MONOTONE = "monotone"
    CUBIC = "cubic"
    BSPLINE = "bspline"


class InterpParams(Model):
    """Bundled per-method interpolation parameters (defaults for every method).

    Parameters live here rather than as flat ``InterpSpec`` fields so each
    method's knobs stay bundled and typed, and adding one never changes the
    ``resample(series, spec)`` call site.

    Only ``BSPLINE`` reads ``spline_order`` today; other methods ignore it
    (documented, not an error — the field carries a default for every method).
    Some parameters are data-count dependent: a spline of order ``k`` needs at
    least ``k + 1`` knots, which cannot be checked at spec construction (the
    spec does not know the series length) — ``resample`` validates it at apply
    time with a clear error.
    """

    spline_order: int = Field(
        default=3, ge=1, description="B-spline degree (BSPLINE only)"
    )


class InterpSpec(Model):
    """Parameters for resampling one ``ChannelSeries`` onto a time grid.

    Fields:
        method: interpolation regime (see ``InterpMethod``). Default LINEAR.
        extrapolation: what sampling *outside* the series' time bounds does —
            ``"error"`` (default) raises; ``"nan"`` fills those rows with NaN;
            ``"nearest"`` clamps to the edge value. Never a silent clamp.
        nan_policy: how NaN in the *source values* is treated — ``"error"``
            (default) rejects it up front; ``"propagate"`` carries it through
            (LINEAR only; spline methods cannot fit through NaN knots).
        params: bundled per-method parameters (``InterpParams``).
    """

    method: InterpMethod = InterpMethod.LINEAR
    extrapolation: Extrapolation = "error"
    nan_policy: NanPolicy = "error"
    params: InterpParams = Field(default_factory=InterpParams)


def resample(
    series: ChannelSeries,
    spec: InterpSpec,
    *,
    times: np.ndarray | None = None,
    dt_s: float | None = None,
) -> ChannelSeries:
    """Interpolate ``series`` per gate onto a target time grid.

    A pure transform: returns a *new* ``ChannelSeries`` whose ``time_s`` is
    the target grid and whose ``values`` are the per-gate 1-D interpolations
    of the source along axis 0. The input is never mutated; ``channel``,
    ``meas_type``, ``gate_depths_mm`` and a deep copy of ``config`` carry
    through.

    Exactly one of ``times`` / ``dt_s`` must be given. ``times`` must be
    1-D, finite and strictly increasing. ``dt_s`` (s) must be positive and
    no larger than the series' span; the grid spans ``[time_s[0],
    time_s[-1]]`` inclusive, with a shortened final interval when the span is
    not an exact multiple.

    Args:
        series: the source channel measurement (its own real ``time_s``).
        spec: method + policies + per-method params.
        times: explicit target times; mutually exclusive with ``dt_s``.
        dt_s: uniform target spacing (s); mutually exclusive with ``times``.

    Returns:
        A new ``ChannelSeries`` on the target grid (same gates/channel/config).

    Raises:
        ValueError: on an invalid grid argument; a source with fewer than two
            samples, non-finite or non-strictly-increasing ``time_s`` (the
            uniform duplicate-knot rule — DOP instruments never emit repeated
            timestamps; duplicate-tolerant handling for other devices is future
            work); NaN source values under ``nan_policy="error"`` (or NaN plus
            a spline method under ``"propagate"``); a spline order the sample
            count cannot support; requested times outside the source bounds
            under ``extrapolation="error"``.
    """
    _require_valid_grid(times, dt_s)
    t_src = _require_series_time(series)
    values = series.values

    if spec.nan_policy == "error":
        if not np.isfinite(values).all():
            n_bad = int(np.count_nonzero(~np.isfinite(values)))
            raise ValueError(
                f"resample: nan_policy='error' but source values hold {n_bad} "
                "non-finite entr(y/ies); use nan_policy='propagate' to carry "
                "them (LINEAR) or clean the source"
            )
    elif (
        spec.nan_policy == "propagate"
        and not np.isfinite(values).all()
        and spec.method is not InterpMethod.LINEAR
    ):
        raise ValueError(
            "resample: nan_policy='propagate' with non-finite source "
            "values is only defined for LINEAR; "
            f"{spec.method.value} splines cannot fit through NaN knots — "
            "use LINEAR or nan_policy='error'"
        )

    _require_spline_capacity(spec, series.time_count)

    t_target = _target_times(t_src, times=times, dt_s=dt_s)

    lo, hi = t_src[0], t_src[-1]
    out_mask = (t_target < lo) | (t_target > hi)
    if spec.extrapolation == "error" and out_mask.any():
        raise ValueError(
            "resample: extrapolation='error' but requested times lie outside "
            f"the source span [{lo:.6g}, {hi:.6g}] s "
            f"({int(out_mask.sum())} of {t_target.size} samples); use "
            "'nan' or 'nearest' to allow out-of-bounds sampling"
        )

    # Evaluate on the clipped grid: in-bounds everywhere, so no method ever
    # sees an out-of-range argument (scipy splines would extrapolate silently).
    t_eval = np.clip(t_target, lo, hi)
    sampled = _sample(spec, series, t_eval)

    if spec.extrapolation == "nan" and out_mask.any():
        sampled = sampled.copy()
        sampled[out_mask, :] = np.nan

    return ChannelSeries(
        channel=series.channel,
        meas_type=series.meas_type,
        gate_depths_mm=list(series.gate_depths_mm),
        time_s=t_target,
        values=sampled,
        config=series.config.model_copy(deep=True),
    )


# ── helpers ──────────────────────────────────────────────────────────────


def _require_valid_grid(times: np.ndarray | None, dt_s: float | None) -> None:
    if (times is None) == (dt_s is None):
        raise ValueError("resample: pass exactly one of times= or dt_s=")


def _require_series_time(series: ChannelSeries) -> np.ndarray:
    t = series.time_s
    if t.ndim != 1 or t.size < 2:
        raise ValueError(
            f"resample: channel {series.channel} has {t.size} sample(s); "
            "interpolation needs at least two strictly increasing times"
        )
    if not np.isfinite(t).all():
        raise ValueError(f"resample: channel {series.channel} time_s is not finite")
    if not np.all(np.diff(t) > 0):
        idx = int(np.flatnonzero(np.diff(t) <= 0)[0]) + 1
        raise ValueError(
            f"resample: channel {series.channel} time_s must be strictly "
            f"increasing; first violation at index {idx} (time_s[{idx}] <= "
            f"time_s[{idx - 1}]). Duplicate timestamps are not produced by DOP "
            "instruments; duplicate-tolerant handling is future work"
        )
    if series.gate_count == 0:
        raise ValueError(f"resample: channel {series.channel} has no gates")
    return t


def _require_spline_capacity(spec: InterpSpec, n_samples: int) -> None:
    if spec.method is InterpMethod.BSPLINE:
        order = spec.params.spline_order
        if n_samples < order + 1:
            raise ValueError(
                f"resample: BSPLINE order {order} needs at least {order + 1} "
                f"samples; channel has {n_samples}. Lower "
                "InterpParams.spline_order or use LINEAR/MONOTONE"
            )
    elif spec.method in (InterpMethod.MONOTONE, InterpMethod.CUBIC):
        if n_samples < 2:  # pragma: no cover - guarded earlier, kept for clarity
            raise ValueError(
                f"resample: {spec.method.value} needs at least two samples"
            )


def _target_times(
    t_src: np.ndarray, *, times: np.ndarray | None, dt_s: float | None
) -> np.ndarray:
    if times is not None:
        t = np.asarray(times, dtype=float)
        if t.ndim != 1 or t.size == 0:
            raise ValueError("resample: times must be a non-empty 1-D array")
        if not np.isfinite(t).all():
            raise ValueError("resample: times must be finite")
        if not np.all(np.diff(t) > 0):
            idx = int(np.flatnonzero(np.diff(t) <= 0)[0]) + 1
            raise ValueError(
                f"resample: times must be strictly increasing; first violation "
                f"at index {idx}"
            )
        return t

    dt = float(dt_s)
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError(f"resample: dt_s must be finite and positive, got {dt_s!r}")
    lo, hi = t_src[0], t_src[-1]
    if dt > hi - lo:
        raise ValueError(
            f"resample: dt_s={dt:.6g} s exceeds the series span [{lo:.6g}, {hi:.6g}] s"
        )
    grid = np.arange(lo, hi, dt)
    if grid.size == 0 or grid[-1] < hi - 1e-12 * max(1.0, abs(hi)):
        grid = np.concatenate([grid, [hi]])
    return grid


def _sample(spec: InterpSpec, series: ChannelSeries, t_eval: np.ndarray) -> np.ndarray:
    """Evaluate the per-gate interpolant of ``series`` at in-bounds ``t_eval``."""
    t = series.time_s
    v = series.values
    if spec.method is InterpMethod.LINEAR:
        return np.column_stack(
            [np.interp(t_eval, t, v[:, g]) for g in range(v.shape[1])]
        )
    if spec.method is InterpMethod.MONOTONE:
        return PchipInterpolator(t, v, axis=0)(t_eval)
    if spec.method is InterpMethod.CUBIC:
        return CubicSpline(t, v, axis=0)(t_eval)
    # BSPLINE
    spline = make_interp_spline(t, v, k=spec.params.spline_order, axis=0)
    return spline(t_eval)
