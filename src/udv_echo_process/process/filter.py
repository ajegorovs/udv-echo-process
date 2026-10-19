"""Per-gate time filtering — the ``ChannelBundle -> ChannelBundle`` step.

Filters each gate's time series along axis 0 (time): MEDIAN / MEAN / SAVGOL on
scipy, TV (ROF) on scikit-image. Driving need (settled 2026-09-09,
`docs/filter-design.md` §7): pre-process turbulent velocity fields — smooth /
remove outliers on the *measured* samples first, then interpolate across gaps.

The public API is the closed ``filter(bundle: ChannelBundle, spec: FilterSpec)
-> ChannelBundle`` transform plus ``filter_sequence``, a plain fold:
``filter_sequence(b, [a, c]) == filter(filter(b, a), c)``. Every call goes
through :func:`udv_echo_process.process.derive.derive` — the single constructor
for transformed artifacts — so provenance, acquisition identity and validated
output construction are never bypassed or hand-rolled (plan §7.1, §8.3).

Propagation follows plan §7.2 row by row: MISSING and invalid cells are
excluded and divide a gate into segments; a valid cell keeps its support kind
and gains ``FILTERED`` (plus ``EDGE_AFFECTED`` where the kernel used
padded/truncated edge context); a segment too short for a method is copied
unchanged, never falsely ``FILTERED``. MEDIAN/MEAN windows are clipped only at
segment edges by their documented nearest-edge behaviour and never cross an
invalid cell or a gap above ``max_gap_s``. SAVGOL/TV additionally require every
processed segment to be truly uniform over *all* adjacent intervals (the old
"ignore the final interval" rule is superseded) and raise a diagnostic error
otherwise. Minimum processed lengths: SAVGOL ``window``, TV 2; MEDIAN and MEAN
have none (a 1-sample segment is processed).

Always per gate, independent 1-D along time (never coupling neighbouring
gates); only ``values`` and the accumulated quality change. ``filter``'s
optional ``gates`` selection restricts one pass to some of a payload's gates —
for a reader who is looking at one gate, filtering the other 54 is wasted work —
and every gate it does *not* name keeps its values and quality bit for bit. The
numerical kernels stay private here and the segment/uniformity rules live in the
private ``udv_echo_process.process.segments`` helper.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from scipy.signal import savgol_filter
from skimage.restoration import denoise_tv_chambolle

from udv_echo_process.models.acquisition import AcquisitionIndex
from udv_echo_process.models.signal import SignalData
from udv_echo_process.models.support import QualityFlag, SampleSupport
from udv_echo_process.process.derive import derive, register_operation
from udv_echo_process.process.segments import _require_truly_uniform, _segment_rows
from udv_echo_process.process.specs import (
    FilterSpec,
    MeanFilterSpec,
    MedianFilterSpec,
    SavgolFilterSpec,
    TvFilterSpec,
)
from udv_echo_process.provenance import ChannelBundle, implementation_ref

__all__ = ["filter", "filter_sequence"]

#: Accumulated quality bits this transform can add (uint32 masks).
FILTERED = np.uint32(int(QualityFlag.FILTERED))
EDGE_AFFECTED = np.uint32(int(QualityFlag.EDGE_AFFECTED))

#: Operation kind per spec branch — the stable verb of plan §8.1.
_KIND_BY_SPEC_TYPE: dict[type, str] = {
    MedianFilterSpec: "filter.median",
    MeanFilterSpec: "filter.mean",
    SavgolFilterSpec: "filter.savgol",
    TvFilterSpec: "filter.tv",
}

register_operation("filter.median", MedianFilterSpec)
register_operation("filter.mean", MeanFilterSpec)
register_operation("filter.savgol", SavgolFilterSpec)
register_operation("filter.tv", TvFilterSpec)

#: Which build of the operation ran; ``filter`` is the public callable id.
_IMPLEMENTATION = implementation_ref("udv_echo_process.process.filter.filter")


def filter(
    bundle: ChannelBundle,
    spec: FilterSpec,
    *,
    gates: Sequence[int] | None = None,
) -> ChannelBundle:
    """Apply one filter along time (axis 0) to ``gates`` of ``bundle``.

    A closed ``ChannelBundle -> ChannelBundle`` transform. It computes owned
    output arrays and routes them through
    :func:`udv_echo_process.process.derive.derive`, so the parent bundle and
    its graph are never mutated and exactly one operation record is added.

    Args:
        bundle: the validated per-channel input state.
        spec: one ``FilterSpec`` branch — ``median`` / ``mean`` / ``savgol`` /
            ``tv``.
        gates: which gates of the payload this pass processes, by index in the
            payload's own order. ``None`` (the default) processes every gate.
            This is a *selection* argument on the transform — the shape
            ``resample`` uses for its target grid — so it is deliberately **not**
            part of the recorded ``params_json``, which is built from ``spec``
            alone (plan §8.3); two differently scoped passes stay
            distinguishable because a derived artifact's id is computed from its
            output data. Gates are validated, never dropped: an index outside
            the payload, an empty selection, a duplicate or a non-integer raises.

    Returns:
        A new closed ``ChannelBundle`` with the filtered payload and its
        provenance edge.

    Raises:
        TypeError: when ``spec`` is not a ``FilterSpec`` branch, or when a gate index
            is not an integer.
        ValueError: when a SAVGOL/TV segment is not truly uniform (never
            silently skipped), or when ``gates`` does not name a usable,
            duplicate-free set of this payload's gates.
    """
    kind = _KIND_BY_SPEC_TYPE.get(type(spec))
    if kind is None:
        channel = bundle.artifact.acquisition.channel.device_channel
        raise TypeError(
            f"filter: channel {channel} expects a FilterSpec branch, got "
            f"{type(spec).__name__}"
        )
    data = _filtered_data(
        bundle.artifact.data,
        spec,
        channel=bundle.artifact.acquisition.channel.device_channel,
        gates=gates,
    )
    return derive(
        bundle, kind=kind, spec=spec, implementation=_IMPLEMENTATION, data=data
    )


def filter_sequence(
    bundle: ChannelBundle,
    specs: list[FilterSpec],
    *,
    gates: Sequence[int] | None = None,
) -> ChannelBundle:
    """Apply ``specs`` in order — the sequence-of-filters entry point.

    A plain fold over :func:`filter`: ``filter_sequence(b, [a, c])`` equals
    ``filter(filter(b, a), c)``. Each element adds exactly one operation
    record; an empty sequence returns ``bundle`` unchanged. ``gates`` is the
    same selection :func:`filter` takes and it applies to every element of the
    sequence; scope one pass differently by calling :func:`filter` directly for
    it.
    """
    for spec in specs:
        bundle = filter(bundle, spec, gates=gates)
    return bundle


# ── private kernels and propagation ──────────────────────────────────────


def _selected_gates(gates: Sequence[int] | None, *, n_gates: int) -> tuple[int, ...]:
    """Validate a gate selection against the payload's own width.

    Args:
        gates: the caller's selection, or ``None`` to process every gate.
        n_gates: the payload's gate count.

    Returns:
        The gate indices to process, in the caller's order.

    Raises:
        ValueError: an empty selection, a non-integer index, a duplicate or an
            index outside ``[0, n_gates)`` — each named in the message, never
            silently dropped or normalised away.
    """
    if gates is None:
        return tuple(range(n_gates))
    selected = tuple(gates)
    if not selected:
        raise ValueError(
            "filter: gates= selects no gate; omit it to process every gate"
        )
    indices: list[int] = []
    for gate in selected:
        if isinstance(gate, bool) or not isinstance(gate, (int, np.integer)):
            raise TypeError(f"filter: gate indices must be integers, got {gate!r}")
        if not 0 <= int(gate) < n_gates:
            raise ValueError(
                f"filter: gate {int(gate)} is outside this payload's {n_gates} gates "
                f"(valid indices 0..{n_gates - 1})"
            )
        indices.append(int(gate))
    duplicates = sorted({gate for gate in indices if indices.count(gate) > 1})
    if duplicates:
        raise ValueError(f"filter: gates= names {duplicates} more than once")
    return tuple(indices)


def _filtered_data(
    data: SignalData,
    spec: FilterSpec,
    *,
    channel: int,
    gates: Sequence[int] | None = None,
) -> SignalData:
    """Return a fresh filtered ``SignalData`` (owned arrays, parent untouched).

    ``values`` and the accumulated ``quality`` are rebuilt; only the gates in
    ``gates`` are processed (every gate by default), and an unprocessed gate is
    copied through bit for bit — no value, support kind or quality change.
    Support kinds, validity, the time/gate axes and the row-level acquisition
    index are carried through, each through the owning model, so no array is
    shared with the parent.
    """
    values = np.array(data.values, dtype=np.float64, copy=True)
    quality = np.array(data.support.quality, copy=True)
    for gate in _selected_gates(gates, n_gates=values.shape[1]):
        _filter_gate(
            values[:, gate],
            quality[:, gate],
            data.support.valid[:, gate],
            data.time_s,
            spec,
            channel=channel,
        )
    support = SampleSupport(
        kind=data.support.kind, valid=data.support.valid, quality=quality
    )
    return SignalData(
        time_s=data.time_s,
        gate_depths_mm=data.gate_depths_mm,
        values=values,
        support=support,
        acquisition=_fresh_acquisition(data.acquisition),
    )


def _filter_gate(
    values: np.ndarray,
    quality: np.ndarray,
    valid: np.ndarray,
    time_s: np.ndarray,
    spec: FilterSpec,
    *,
    channel: int,
) -> None:
    """Filter one gate in place over its valid, time-contiguous segments.

    A segment shorter than the method's minimum is left untouched (plan §7.2
    row 6: copied unchanged, never falsely ``FILTERED``). A processed
    SAVGOL/TV segment must be truly uniform or the operation raises. Every
    filtered cell keeps its support kind and gains ``FILTERED``; cells whose
    window reached past a segment edge additionally gain ``EDGE_AFFECTED``.
    """
    for start, stop in _segment_rows(time_s, valid, spec.max_gap_s):
        if stop - start < _min_segment_length(spec):
            continue
        if isinstance(spec, (SavgolFilterSpec, TvFilterSpec)):
            _require_truly_uniform(
                time_s,
                start,
                stop,
                method=spec.method,
                channel=channel,
                uniform_rtol=spec.uniform_rtol,
            )
        values[start:stop] = _kernel(values[start:stop], spec)
        quality[start:stop] |= FILTERED
        half = _edge_half_width(spec)
        if half > 0:
            left = min(half, stop - start)
            quality[start : start + left] |= EDGE_AFFECTED
            quality[max(start, stop - half) : stop] |= EDGE_AFFECTED


def _kernel(segment: np.ndarray, spec: FilterSpec) -> np.ndarray:
    """Run the method's 1-D kernel over one segment (returns ``float64``).

    MEDIAN uses ``median_filter`` and MEAN ``uniform_filter1d``, both with
    ``mode="nearest"``, so their windows are clipped only at the segment edges;
    SAVGOL uses scipy's default ``interp`` edge handling; TV is the Chambolle
    ROF solver over the whole segment.
    """
    if isinstance(spec, MedianFilterSpec):
        return median_filter(segment, size=spec.window, mode="nearest")
    if isinstance(spec, MeanFilterSpec):
        return uniform_filter1d(segment, size=spec.window, mode="nearest")
    if isinstance(spec, SavgolFilterSpec):
        return savgol_filter(segment, spec.window, spec.polyorder)
    assert isinstance(spec, TvFilterSpec)  # the kind map guards this too
    return denoise_tv_chambolle(
        segment, weight=spec.weight, max_num_iter=spec.iterations
    )


def _min_segment_length(spec: FilterSpec) -> int:
    """Smallest segment a method can process: SAVGOL ``window``, TV 2.

    MEDIAN and MEAN have no minimum — a 1-sample segment is processed with a
    nearest-edge-clipped window — so their bound is a single row.
    """
    if isinstance(spec, SavgolFilterSpec):
        return spec.window
    if isinstance(spec, TvFilterSpec):
        return 2
    return 1


def _edge_half_width(spec: FilterSpec) -> int:
    """How many rows at each segment edge used padded/truncated context.

    MEDIAN/MEAN pad by nearest replication and SAVGOL fits its polynomial to
    the truncated edge window, so their first and last ``window // 2`` rows are
    edge-affected. TV solves the whole segment with natural boundary
    differences and has no window, so it adds no ``EDGE_AFFECTED``.
    """
    if isinstance(spec, TvFilterSpec):
        return 0
    return spec.window // 2


def _fresh_acquisition(
    acquisition: AcquisitionIndex | None,
) -> AcquisitionIndex | None:
    """Rebuild the row-level acquisition index so no array is shared."""
    if acquisition is None:
        return None
    return AcquisitionIndex(
        sample_id=acquisition.sample_id,
        acquisition_time_s=acquisition.acquisition_time_s,
        round_id=acquisition.round_id,
        visit_id=acquisition.visit_id,
        profile_in_visit=acquisition.profile_in_visit,
    )
