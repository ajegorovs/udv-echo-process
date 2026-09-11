"""Per-gate time resampling — the ``ChannelBundle -> ChannelBundle`` step.

``resample(bundle, spec, *, times | dt_s)`` interpolates each gate of one
channel independently along axis 0 (time) onto a caller-chosen target grid,
per plan §7.3 (the interpolation specs and their ten-row support-propagation
table) and §7.4 (the recording-level sync primitive consumes this). Every call
goes through :func:`udv_echo_process.process.derive.derive` — the single
constructor for transformed artifacts — so provenance, acquisition identity and
validated output construction are never bypassed (plan §7.1, §8.3).

Sampling is segment-aware: invalid cells and MISSING cells divide a gate into
segments, and a source bracket wider than the spec's ``max_bracket_span_s``
likewise divides them, so no bracket ever crosses a forbidden gap (plan §7.1,
§7.3, §14). Target times are compared against the source `time_s` with exact
float64 equality — never a tolerance match — so a target grid that deliberately
reuses source times reuses the array values and an exact ancestral knot keeps
its real row acquisition index (the phase-5 STOP/GO condition). A row keeps its
real acquisition index iff at least one gate's source cell on that exact row is
``OBSERVED`` (valid or invalid); every other row takes the synthetic sentinel.

Support is propagated, never invented: MISSING and invalid ``OBSERVED`` cells
are copied with their quality; between two valid knots the result is
``INTERPOLATED`` (or ``EXTRAPOLATED`` when either ancestor is extrapolated);
outside the overall valid domain the ``extrapolation`` policy decides. Synthetic
support can never be laundered into ``OBSERVED``: an exact synthetic knot keeps
its support kind and gains ``REINTERPOLATED``, and any synthetic contributor to
an interpolated value adds ``REINTERPOLATED`` too (plan §7.3, §14). CUBIC and
BSPLINE reuse the shared ``segments._require_truly_uniform`` all-interval rule;
LINEAR and MONOTONE have no uniformity requirement. All numerical kernels stay
private here.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator, make_interp_spline

from udv_echo_process.models.acquisition import AcquisitionIndex
from udv_echo_process.models.signal import SignalData
from udv_echo_process.models.support import QualityFlag, SampleSupport, SupportKind
from udv_echo_process.process.derive import derive, register_operation
from udv_echo_process.process.segments import _require_truly_uniform, _segment_rows
from udv_echo_process.process.specs import (
    BsplineInterpSpec,
    CubicInterpSpec,
    InterpSpec,
    LinearInterpSpec,
    MonotoneInterpSpec,
)
from udv_echo_process.provenance import ChannelBundle, implementation_ref

__all__ = ["resample"]

#: Operation kind per spec branch — the stable verb of plan §8.1. The verb is
#: ``interp`` (not ``resample``) so it matches the ``filter.<method>`` pattern.
_KIND_BY_SPEC_TYPE: dict[type, str] = {
    LinearInterpSpec: "interp.linear",
    MonotoneInterpSpec: "interp.monotone",
    CubicInterpSpec: "interp.cubic",
    BsplineInterpSpec: "interp.bspline",
}

register_operation("interp.linear", LinearInterpSpec)
register_operation("interp.monotone", MonotoneInterpSpec)
register_operation("interp.cubic", CubicInterpSpec)
register_operation("interp.bspline", BsplineInterpSpec)

#: Which build of the operation ran; ``resample`` is the public callable id.
_IMPLEMENTATION = implementation_ref("udv_echo_process.process.sync.resample")

#: Support-kind integers, resolved once.
_MISSING = int(SupportKind.MISSING)
_OBSERVED = int(SupportKind.OBSERVED)
_INTERPOLATED = int(SupportKind.INTERPOLATED)
_EXTRAPOLATED = int(SupportKind.EXTRAPOLATED)

#: Kinds produced by an earlier interpolation (i.e. not observed).
_SYNTHETIC_KINDS = frozenset({_INTERPOLATED, _EXTRAPOLATED})

#: Accumulated quality bits this transform can add (uint32 masks).
GAP_TOO_LONG = np.uint32(int(QualityFlag.GAP_TOO_LONG))
OUT_OF_RANGE = np.uint32(int(QualityFlag.OUT_OF_RANGE))
EXTRAPOLATED_FLAG = np.uint32(int(QualityFlag.EXTRAPOLATED))
REINTERPOLATED = np.uint32(int(QualityFlag.REINTERPOLATED))

#: Optional per-row id arrays carried through the resampled acquisition index.
_OPTIONAL_IDS = ("round_id", "visit_id", "profile_in_visit")


def resample(
    bundle: ChannelBundle,
    spec: InterpSpec,
    *,
    times: np.ndarray | None = None,
    dt_s: float | None = None,
) -> ChannelBundle:
    """Interpolate every gate of ``bundle`` onto a target time grid.

    A closed ``ChannelBundle -> ChannelBundle`` transform: it computes owned
    output arrays and routes them through
    :func:`udv_echo_process.process.derive.derive`, so the parent bundle and
    its graph are never mutated and exactly one operation record is added.

    Exactly one of ``times`` / ``dt_s`` is given. ``times`` must be 1-D, finite
    and strictly increasing. ``dt_s`` (s) must be finite, positive and no
    larger than the source span; the grid is exactly uniform — ``n =
    floor((t_end - t0) / dt_s)``, ``grid = t0 + arange(n + 1) * dt_s`` — so a
    residual tail shorter than ``dt_s`` is simply not represented (D6, the
    legacy shortened final interval is retired).

    Args:
        bundle: the validated per-channel input state.
        spec: one ``InterpSpec`` branch — ``linear`` / ``monotone`` / ``cubic``
            / ``bspline``.
        times: explicit target times; mutually exclusive with ``dt_s``.
        dt_s: uniform target spacing (s); mutually exclusive with ``times``.

    Returns:
        A new closed ``ChannelBundle`` on the target grid with its provenance
        edge.

    Raises:
        TypeError: when ``spec`` is not an ``InterpSpec`` branch.
        ValueError: on an invalid grid argument; an out-of-domain target under
            ``extrapolation="error"``; a bracket wider than
            ``max_bracket_span_s`` under ``long_gap="error"``; a sampled
            CUBIC/BSPLINE segment that is not truly uniform; or a sampled
            BSPLINE segment smaller than ``order + 1``. All of these raise
            before any artifact is created.
    """
    kind = _KIND_BY_SPEC_TYPE.get(type(spec))
    channel = bundle.artifact.acquisition.channel.device_channel
    if kind is None:
        raise TypeError(
            f"resample: channel {channel} expects an InterpSpec branch, got "
            f"{type(spec).__name__}"
        )
    _require_grid_args(times, dt_s)
    target = _target_times(bundle.artifact.data.time_s, times=times, dt_s=dt_s)
    data = _resampled_data(bundle.artifact.data, spec, target, channel=channel)
    return derive(
        bundle, kind=kind, spec=spec, implementation=_IMPLEMENTATION, data=data
    )


# ── target grid ──────────────────────────────────────────────────────────


def _require_grid_args(times: np.ndarray | None, dt_s: float | None) -> None:
    """Require exactly one of ``times`` / ``dt_s`` (plan §7.3, D6)."""
    if (times is None) == (dt_s is None):
        raise ValueError("resample: pass exactly one of times= or dt_s=")


def _target_times(
    t_src: np.ndarray, *, times: np.ndarray | None, dt_s: float | None
) -> np.ndarray:
    """Build the target time grid from ``times`` or a uniform ``dt_s`` (D6).

    ``dt_s`` produces an exactly uniform grid ``t0 + arange(n + 1) * dt_s``
    with ``n = floor((t_end - t0) / dt_s)``; the legacy ``np.arange`` grid with
    an appended shortened final interval is retired.
    """
    if times is not None:
        t = np.asarray(times, dtype=np.float64)
        if t.ndim != 1 or t.size == 0:
            raise ValueError("resample: times must be a non-empty 1-D array")
        if not np.isfinite(t).all():
            raise ValueError("resample: times must be finite")
        if not np.all(np.diff(t) > 0):
            idx = int(np.flatnonzero(np.diff(t) <= 0)[0]) + 1
            raise ValueError(
                "resample: times must be strictly increasing; first violation "
                f"at index {idx}"
            )
        return t

    dt = float(dt_s)
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError(f"resample: dt_s must be finite and positive, got {dt_s!r}")
    lo, hi = float(t_src[0]), float(t_src[-1])
    span = hi - lo
    n = math.floor(span / dt) if dt <= span else 0
    if dt > span or n < 1:
        raise ValueError(
            f"resample: dt_s={dt:.6g} s exceeds the source span [{lo:.6g}, {hi:.6g}] s"
        )
    return lo + np.arange(n + 1, dtype=np.float64) * dt


# ── private sampling and propagation ─────────────────────────────────────


def _resampled_data(
    data: SignalData, spec: InterpSpec, target: np.ndarray, *, channel: int
) -> SignalData:
    """Return a fresh resampled ``SignalData`` (owned arrays, parent untouched).

    One operation per gate: the target grid is shared, but each gate resolves
    its own support, segments and brackets. Every output array is rebuilt, so
    nothing is shared with the parent payload.
    """
    _, n_gates = data.values.shape
    n_out = target.shape[0]
    out_values = np.full((n_out, n_gates), np.nan, dtype=np.float64)
    out_kind = np.full((n_out, n_gates), np.uint8(_MISSING), dtype=np.uint8)
    out_valid = np.zeros((n_out, n_gates), dtype=bool)
    out_quality = np.zeros((n_out, n_gates), dtype=np.uint32)
    exact = _exact_source_rows(data.time_s, target)
    for gate in range(n_gates):
        _sample_gate(
            data.time_s,
            data.values[:, gate],
            data.support.kind[:, gate],
            data.support.valid[:, gate],
            data.support.quality[:, gate],
            target,
            exact,
            spec,
            gate=gate,
            channel=channel,
            out_values=out_values[:, gate],
            out_kind=out_kind[:, gate],
            out_valid=out_valid[:, gate],
            out_quality=out_quality[:, gate],
        )
    support = SampleSupport(kind=out_kind, valid=out_valid, quality=out_quality)
    return SignalData(
        time_s=target,
        gate_depths_mm=data.gate_depths_mm,
        values=out_values,
        support=support,
        acquisition=_resampled_acquisition(data, exact, n_out),
    )


def _exact_source_rows(t_src: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Return, per target row, the exactly matching source row or ``-1``.

    Times are compared with exact float64 equality (plan §7.3): a target grid
    that reuses source times must reuse the array values, never a nearby time
    matched within a tolerance.
    """
    pos = np.searchsorted(t_src, target, side="left")
    np.clip(pos, 0, t_src.size - 1, out=pos)
    return np.where(t_src[pos] == target, pos, -1).astype(np.int64)


def _sample_gate(
    t: np.ndarray,
    v: np.ndarray,
    src_kind: np.ndarray,
    src_valid: np.ndarray,
    src_q: np.ndarray,
    target: np.ndarray,
    exact: np.ndarray,
    spec: InterpSpec,
    *,
    gate: int,
    channel: int,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Resolve one gate's target rows under the §7.3 propagation table.

    Exact rows are copied first (rows 1-3), then out-of-domain rows take the
    ``extrapolation`` policy, then interior rows are classified into the
    between-two-valid-knots row (4), the invalid/missing-endpoint row (5) and
    the over-long bracket row (6). A bracket whose span exceeds
    ``max_bracket_span_s`` raises under ``long_gap="error"`` before anything is
    written for it.
    """
    exact_mask = exact >= 0
    for j in np.flatnonzero(exact_mask):
        _copy_knot(
            int(exact[j]),
            int(j),
            v,
            src_kind,
            src_valid,
            src_q,
            out_values,
            out_kind,
            out_valid,
            out_quality,
        )

    valid_rows = np.flatnonzero(src_valid)
    if valid_rows.size == 0:
        _handle_empty_domain(
            target,
            exact_mask,
            spec,
            gate=gate,
            channel=channel,
            out_values=out_values,
            out_kind=out_kind,
            out_valid=out_valid,
            out_quality=out_quality,
        )
        return

    lo = float(t[valid_rows[0]])
    hi = float(t[valid_rows[-1]])
    below = (~exact_mask) & (target < lo)
    above = (~exact_mask) & (target > hi)
    outside = below | above
    if outside.any():
        _apply_extrapolation(
            below,
            above,
            t,
            v,
            src_q,
            int(valid_rows[0]),
            int(valid_rows[-1]),
            spec,
            gate=gate,
            channel=channel,
            out_values=out_values,
            out_kind=out_kind,
            out_valid=out_valid,
            out_quality=out_quality,
        )

    idx = np.flatnonzero(~exact_mask & ~outside)
    if idx.size == 0:
        return
    pos = np.searchsorted(t, target[idx], side="left")
    a = pos - 1
    b = pos
    ok = src_valid[a] & src_valid[b]
    too_long = (t[b] - t[a]) > spec.max_bracket_span_s

    for j, aa, bb in zip(idx[~ok], a[~ok], b[~ok]):
        _mark_gap(
            int(j),
            np.uint32(src_q[aa]) | np.uint32(src_q[bb]),
            out_values,
            out_kind,
            out_valid,
            out_quality,
        )

    over = ok & too_long
    if over.any():
        _handle_long_bracket(
            over,
            idx,
            a,
            b,
            t,
            src_q,
            spec,
            gate=gate,
            channel=channel,
            out_values=out_values,
            out_kind=out_kind,
            out_valid=out_valid,
            out_quality=out_quality,
        )

    good = ok & ~too_long
    if not good.any():
        return
    good_idx = idx[good]
    good_a = a[good]
    segments = _segment_rows(t, src_valid, spec.max_bracket_span_s)
    seg_of_row = np.full(t.size, -1, dtype=np.int64)
    for segment_index, (start, stop) in enumerate(segments):
        seg_of_row[start:stop] = segment_index
    for segment_index, (start, stop) in enumerate(segments):
        selected = seg_of_row[good_a] == segment_index
        if not selected.any():
            continue
        _require_segment(spec, t, start, stop, channel=channel, gate=gate)
        sampled = _interpolate(
            spec, t[start:stop], v[start:stop], target[good_idx[selected]]
        )
        for j, aa, bb, value in zip(
            good_idx[selected], good_a[selected], good_a[selected] + 1, sampled
        ):
            _write_interpolated(
                int(j),
                float(value),
                int(aa),
                int(bb),
                src_kind,
                src_q,
                out_values,
                out_kind,
                out_valid,
                out_quality,
            )


def _copy_knot(
    i: int,
    j: int,
    v: np.ndarray,
    src_kind: np.ndarray,
    src_valid: np.ndarray,
    src_q: np.ndarray,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Copy an exact source knot (table rows 1-3), never laundering support.

    A valid knot keeps its value, kind and quality; a synthetic knot keeps its
    ``INTERPOLATED``/``EXTRAPOLATED`` kind and gains ``REINTERPOLATED``; an
    invalid or missing knot is NaN and keeps its kind and quality.
    """
    kind = int(src_kind[i])
    valid = bool(src_valid[i])
    out_kind[j] = np.uint8(kind)
    out_valid[j] = valid
    out_values[j] = float(v[i]) if valid else np.nan
    quality = np.uint32(src_q[i])
    if kind in _SYNTHETIC_KINDS:
        quality |= REINTERPOLATED
    out_quality[j] = quality


def _write_interpolated(
    j: int,
    value: float,
    a: int,
    b: int,
    src_kind: np.ndarray,
    src_q: np.ndarray,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Write a between-two-valid-knots value (table row 4).

    ``EXTRAPOLATED`` if either ancestor is extrapolated (extrapolated ancestry
    dominates), otherwise ``INTERPOLATED``; quality is the OR of both ancestor
    masks, plus ``EXTRAPOLATED`` and/or ``REINTERPOLATED`` where applicable.
    """
    kind_a = int(src_kind[a])
    kind_b = int(src_kind[b])
    quality = np.uint32(src_q[a]) | np.uint32(src_q[b])
    if kind_a == _EXTRAPOLATED or kind_b == _EXTRAPOLATED:
        out_kind[j] = np.uint8(_EXTRAPOLATED)
        quality |= EXTRAPOLATED_FLAG
    else:
        out_kind[j] = np.uint8(_INTERPOLATED)
    if kind_a in _SYNTHETIC_KINDS or kind_b in _SYNTHETIC_KINDS:
        quality |= REINTERPOLATED
    out_values[j] = value
    out_valid[j] = True
    out_quality[j] = quality


def _mark_gap(
    j: int,
    quality: np.uint32,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Mark a failed bracket (table rows 5-6): NaN, ``MISSING``, ``GAP_TOO_LONG``."""
    out_values[j] = np.nan
    out_kind[j] = np.uint8(_MISSING)
    out_valid[j] = False
    out_quality[j] = quality | GAP_TOO_LONG


def _handle_long_bracket(
    over: np.ndarray,
    idx: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    t: np.ndarray,
    src_q: np.ndarray,
    spec: InterpSpec,
    *,
    gate: int,
    channel: int,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Resolve brackets wider than ``max_bracket_span_s`` (table row 6).

    ``long_gap="error"`` raises before any artifact is created, naming the
    channel, gate and the first offending bracket's times, span and limit;
    ``long_gap="missing"`` yields NaN/``MISSING`` with the ancestors' quality
    OR-ed with ``GAP_TOO_LONG``.
    """
    if spec.long_gap == "error":
        first = int(np.flatnonzero(over)[0])
        aa = int(a[first])
        bb = int(b[first])
        raise ValueError(
            f"interp.{spec.method}: channel {channel} gate {gate} bracket "
            f"[{float(t[aa]):.6g}, {float(t[bb]):.6g}] s spans "
            f"{float(t[bb] - t[aa]):.6g} s, over max_bracket_span_s="
            f"{spec.max_bracket_span_s:.6g} (long_gap='error')"
        )
    for j, aa, bb in zip(idx[over], a[over], b[over]):
        _mark_gap(
            int(j),
            np.uint32(src_q[aa]) | np.uint32(src_q[bb]),
            out_values,
            out_kind,
            out_valid,
            out_quality,
        )


def _apply_extrapolation(
    below: np.ndarray,
    above: np.ndarray,
    t: np.ndarray,
    v: np.ndarray,
    src_q: np.ndarray,
    first: int,
    last: int,
    spec: InterpSpec,
    *,
    gate: int,
    channel: int,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Resolve out-of-domain target rows under the ``extrapolation`` policy.

    ``error`` raises with the offending count and the valid source bounds;
    ``missing`` yields NaN/``MISSING`` with the edge quality OR ``OUT_OF_RANGE``;
    ``nearest`` yields the finite nearest-edge value as ``EXTRAPOLATED`` with
    the edge quality OR ``EXTRAPOLATED`` OR ``OUT_OF_RANGE``. It applies only
    outside the overall valid domain and never bridges an internal long gap.
    """
    count = int(below.sum() + above.sum())
    if spec.extrapolation == "error":
        raise ValueError(
            f"interp.{spec.method}: channel {channel} gate {gate}: {count} target "
            f"row(s) lie outside the valid source domain "
            f"[{float(t[first]):.6g}, {float(t[last]):.6g}] s "
            "(extrapolation='error')"
        )
    for j in np.flatnonzero(below):
        _extrapolate_row(
            int(j), first, v, src_q, spec, out_values, out_kind, out_valid, out_quality
        )
    for j in np.flatnonzero(above):
        _extrapolate_row(
            int(j), last, v, src_q, spec, out_values, out_kind, out_valid, out_quality
        )


def _extrapolate_row(
    j: int,
    edge: int,
    v: np.ndarray,
    src_q: np.ndarray,
    spec: InterpSpec,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Write one out-of-domain row from the nearest valid edge cell."""
    quality = np.uint32(src_q[edge])
    if spec.extrapolation == "missing":
        out_values[j] = np.nan
        out_kind[j] = np.uint8(_MISSING)
        out_valid[j] = False
        out_quality[j] = quality | OUT_OF_RANGE
        return
    out_values[j] = float(v[edge])
    out_kind[j] = np.uint8(_EXTRAPOLATED)
    out_valid[j] = True
    out_quality[j] = quality | EXTRAPOLATED_FLAG | OUT_OF_RANGE


def _handle_empty_domain(
    target: np.ndarray,
    exact_mask: np.ndarray,
    spec: InterpSpec,
    *,
    gate: int,
    channel: int,
    out_values: np.ndarray,
    out_kind: np.ndarray,
    out_valid: np.ndarray,
    out_quality: np.ndarray,
) -> None:
    """Resolve a gate with no valid source sample at all.

    Every non-exact target is outside an empty valid domain. ``error`` raises;
    ``missing`` yields NaN/``MISSING`` with ``OUT_OF_RANGE``; ``nearest`` has no
    finite edge to clamp to, so it degrades to ``MISSING`` with ``GAP_TOO_LONG``
    (recorded deviation — the policy cannot be honoured without a value).
    """
    idx = np.flatnonzero(~exact_mask)
    if idx.size == 0:
        return
    if spec.extrapolation == "error":
        raise ValueError(
            f"interp.{spec.method}: channel {channel} gate {gate}: "
            f"{idx.size} target row(s) requested but the gate has no valid "
            "source sample to bound the domain (extrapolation='error')"
        )
    quality = OUT_OF_RANGE if spec.extrapolation == "missing" else GAP_TOO_LONG
    for j in idx:
        out_values[j] = np.nan
        out_kind[j] = np.uint8(_MISSING)
        out_valid[j] = False
        out_quality[j] = quality


def _require_segment(
    spec: InterpSpec, t: np.ndarray, start: int, stop: int, *, channel: int, gate: int
) -> None:
    """Validate one sampled source segment before its kernel runs.

    Capacity first: BSPLINE order ``k`` needs ``k + 1`` samples per sampled
    segment, everything else needs two. Then, for CUBIC/BSPLINE only, the
    shared all-interval true-uniformity rule
    (:func:`udv_echo_process.process.segments._require_truly_uniform`) names the
    error ``interp.<method>``.
    """
    required = _required_samples(spec)
    if stop - start < required:
        detail = (
            f" (order {spec.order} needs order + 1)"
            if isinstance(spec, BsplineInterpSpec)
            else ""
        )
        raise ValueError(
            f"interp.{spec.method}: channel {channel} gate {gate} needs at least "
            f"{required} samples per sampled segment, but segment rows "
            f"[{start}, {stop}) has {stop - start}{detail}"
        )
    if isinstance(spec, (CubicInterpSpec, BsplineInterpSpec)):
        _require_truly_uniform(
            t,
            start,
            stop,
            method=spec.method,
            channel=channel,
            uniform_rtol=spec.uniform_rtol,
            prefix="interp",
        )


def _required_samples(spec: InterpSpec) -> int:
    """Smallest segment a method can sample: BSPLINE ``order + 1``, else two."""
    if isinstance(spec, BsplineInterpSpec):
        return spec.order + 1
    return 2


def _interpolate(
    spec: InterpSpec, t_seg: np.ndarray, v_seg: np.ndarray, xs: np.ndarray
) -> np.ndarray:
    """Evaluate the method's 1-D kernel on one segment at interior targets.

    LINEAR uses ``np.interp``, MONOTONE ``PchipInterpolator``, CUBIC
    ``CubicSpline`` and BSPLINE ``make_interp_spline(k=order)``; each kernel is
    fit on the *segment's* knots only, so no bracket crosses a gap.
    """
    if isinstance(spec, LinearInterpSpec):
        return np.interp(xs, t_seg, v_seg)
    if isinstance(spec, MonotoneInterpSpec):
        return PchipInterpolator(t_seg, v_seg)(xs)
    if isinstance(spec, CubicInterpSpec):
        return CubicSpline(t_seg, v_seg)(xs)
    assert isinstance(spec, BsplineInterpSpec)  # the kind map guards this too
    return make_interp_spline(t_seg, v_seg, k=spec.order)(xs)


def _resampled_acquisition(
    data: SignalData, exact: np.ndarray, n_out: int
) -> AcquisitionIndex | None:
    """Map the source row acquisition index onto the target rows.

    An exact row keeps its real index iff at least one gate's source cell on
    that row is ``OBSERVED`` (valid or invalid); every other row is wholly
    synthetic (``sample_id == -1``, NaN acquisition time, ``-1`` in every
    present optional id). Returns ``None`` when the parent carries no index.
    """
    src = data.acquisition
    if src is None:
        return None
    n_src = data.time_s.shape[0]
    observed_row = (data.support.kind == np.uint8(_OBSERVED)).any(axis=1)
    pos = np.clip(exact, 0, n_src - 1)
    real = (exact >= 0) & observed_row[pos]
    sample_id = np.full(n_out, -1, dtype=np.int64)
    acquisition_time_s = np.full(n_out, np.nan, dtype=np.float64)
    sample_id[real] = src.sample_id[pos[real]]
    acquisition_time_s[real] = src.acquisition_time_s[pos[real]]
    optional: dict[str, np.ndarray | None] = {}
    for name in _OPTIONAL_IDS:
        arr = getattr(src, name)
        if arr is None:
            optional[name] = None
            continue
        carried = np.full(n_out, -1, dtype=np.int64)
        carried[real] = arr[pos[real]]
        optional[name] = carried
    return AcquisitionIndex(
        sample_id=sample_id,
        acquisition_time_s=acquisition_time_s,
        round_id=optional["round_id"],
        visit_id=optional["visit_id"],
        profile_in_visit=optional["profile_in_visit"],
    )
