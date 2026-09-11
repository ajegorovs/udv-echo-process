"""Terminal operating-state detection for one axial-velocity channel.

Adapted from the retiring ``udv-analysis`` ``processing/states.py`` (absorption
plan §4, decisions D2/D5): the chain is **local-σ texture → depth median →
absolute Gaussian time derivative → Kittler–Illingworth minimum-error threshold
× factor → persistent peaks → half-open intervals**. It is a terminal ``T -> U``
producer here, not a ``ChannelBundle -> ChannelBundle`` transform: it takes the
receiver's per-channel bundle as *input*, adds no payload field, no quality flag
and no provenance node, and leaves the source artifact and graph untouched.

The input is the plan §7.1 :class:`~udv_echo_process.provenance.ChannelBundle`
bridged from a recording bundle, and its descriptor must measure
:attr:`~udv_echo_process.models.identity.SignalQuantity.AXIAL_VELOCITY`.

Invalid-sample policy (explicit, documented): ``SignalData`` marks an unusable
cell ``support.valid == False`` with a NaN value. This terminal step has no
per-cell exclusion concept — a local 2-D window cannot skip a hole without
changing the texture — so any invalid cell is refused with an
:class:`StateDetectionInputError` naming the count and first coordinate, exactly
as the source refused a non-finite field. It neither relabels support, nor adds
``QualityFlag.EXCLUDED``, nor mutates the artifact; the caller repairs or
selects a fully observed channel first.

The three state-detection invariants the source guaranteed are preserved:
intervals are half-open, ordered, non-overlapping and cover the whole recording;
a transition index is the boundary between neighbours and belongs to neither;
and ``single`` mode yields one interval spanning every profile.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d, uniform_filter
from scipy.signal import find_peaks

from udv_echo_process.models.identity import SignalDescriptor, SignalQuantity
from udv_echo_process.models.states import (
    OperatingStateDetection,
    OperatingStateInterval,
    StateDetectionMode,
    StateDetectionSettings,
)
from udv_echo_process.provenance import ChannelBundle


class StateDetectionInputError(ValueError):
    """The channel bundle cannot enter operating-state detection."""


def _minimum_error_threshold(values: np.ndarray, bins: int) -> float:
    """Return the Kittler–Illingworth minimum-error histogram threshold.

    The criterion is the standard one: pick the split minimising the mixture
    entropic error of the two Gaussian modes. A degenerate (near-constant)
    signal returns its maximum, and any non-finite criterion falls back to the
    maximum — never to a synthetic threshold.
    """
    samples = np.asarray(values, dtype=np.float64)
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise StateDetectionInputError(
            "cannot threshold an empty or non-finite change signal"
        )
    minimum, maximum = float(np.min(samples)), float(np.max(samples))
    if maximum <= minimum:
        return maximum
    histogram, edges = np.histogram(samples, bins=bins, range=(minimum, maximum))
    probabilities = histogram.astype(np.float64)
    probabilities /= probabilities.sum()
    centers = 0.5 * (edges[:-1] + edges[1:])
    weight_0 = np.cumsum(probabilities)
    weight_1 = 1.0 - weight_0
    first = np.cumsum(probabilities * centers)
    second = np.cumsum(probabilities * centers * centers)
    tiny = np.finfo(np.float64).eps
    mean_0 = first / np.maximum(weight_0, tiny)
    mean_1 = (first[-1] - first) / np.maximum(weight_1, tiny)
    variance_0 = second / np.maximum(weight_0, tiny) - mean_0 * mean_0
    variance_1 = (second[-1] - second) / np.maximum(weight_1, tiny) - mean_1 * mean_1
    valid = (weight_0 > 0) & (weight_1 > 0) & (variance_0 > tiny) & (variance_1 > tiny)
    criterion = np.full(bins, np.inf, dtype=np.float64)
    criterion[valid] = (
        1.0
        + 2.0
        * (
            weight_0[valid] * np.log(np.sqrt(variance_0[valid]))
            + weight_1[valid] * np.log(np.sqrt(variance_1[valid]))
        )
        - 2.0
        * (
            weight_0[valid] * np.log(weight_0[valid])
            + weight_1[valid] * np.log(weight_1[valid])
        )
    )
    if not np.any(np.isfinite(criterion)):
        return maximum
    return float(centers[np.argmin(criterion)])


def _persistent_peak_indices(
    signal: np.ndarray,
    scale: float,
    threshold: float,
    prominence_std_factor: float,
) -> tuple[np.ndarray, float]:
    """Return the persistent peak indices of ``signal`` and their prominence.

    A peak is *persistent* when it is the genuine maximum of the raw change
    signal inside a Gaussian-smoothed neighbourhood of width ``scale`` and
    exceeds ``threshold``. Peaks are not merged arbitrarily: the raw maximum
    within each broad peak's neighbourhood is selected, then de-duplicated.
    """
    values = np.asarray(signal, dtype=np.float64)
    if values.ndim != 1:
        raise StateDetectionInputError(
            f"the state-change signal must be one-dimensional, got rank {values.ndim}"
        )
    if values.size < 3 or np.max(values) <= threshold:
        return np.empty(0, dtype=np.int64), 0.0
    smoothed = gaussian_filter1d(values, sigma=scale, mode="reflect")
    prominence = prominence_std_factor * float(np.std(smoothed))
    broad_peaks, _ = find_peaks(smoothed, prominence=prominence)
    radius = max(1, int(np.ceil(scale)))
    selected: list[int] = []
    for broad_peak in broad_peaks:
        start = max(0, int(broad_peak) - radius)
        stop = min(values.size, int(broad_peak) + radius + 1)
        peak = start + int(np.argmax(values[start:stop]))
        if values[peak] > threshold:
            selected.append(peak)
    if not selected:
        return np.empty(0, dtype=np.int64), prominence
    return np.unique(np.asarray(selected, dtype=np.int64)), prominence


def _build_intervals(
    profile_count: int,
    transitions: np.ndarray,
    axis: np.ndarray,
    minimum_relative_duration: float,
) -> tuple[OperatingStateInterval, ...]:
    """Partition the recording except the transition samples.

    A transition at index ``t`` belongs to neither neighbour: the preceding
    span stops at ``t`` (exclusive) and the following span starts at ``t + 1``,
    so ``t`` itself is covered by no interval. Duplicate or out-of-range
    transitions are dropped and a boundary is clamped to ``[1,
    profile_count - 1]`` so a degenerate edge transition cannot truncate the
    recording. ``kept`` mirrors the settings rule: a candidate span longer than
    ``minimum_relative_duration * profile_count`` is a retained state and is
    numbered from 1 in interval order.
    """
    raw = np.asarray(transitions, dtype=np.int64)
    clipped = raw[(raw >= 1) & (raw < profile_count)]
    boundaries = np.unique(clipped)
    starts = np.concatenate(([0], boundaries + 1))
    stops = np.concatenate((boundaries, [profile_count]))
    sample_width = float(np.median(np.diff(axis))) if axis.size > 1 else 0.0
    intervals: list[OperatingStateInterval] = []
    state_number = 0
    number = 0
    for start, stop in zip(starts, stops, strict=True):
        if start >= stop:
            continue  # adjacent transitions leave no profile in between
        number += 1
        length = int(stop - start)
        kept = length > minimum_relative_duration * profile_count
        if kept:
            state_number += 1
        intervals.append(
            OperatingStateInterval(
                interval_number=number,
                state_number=state_number if kept else None,
                kept=bool(kept),
                start_index=int(start),
                stop_index_exclusive=int(stop),
                profile_count=length,
                relative_duration=float(length / profile_count),
                start_time_s=float(axis[start]),
                end_time_s=float(axis[stop - 1]),
                duration_s=float(axis[stop - 1] - axis[start] + sample_width),
            )
        )
    return tuple(intervals)


def _single_state_result(
    artifact_id: str,
    descriptor: SignalDescriptor,
    profile_count: int,
    gate_count: int,
    time_step_s: float,
    gate_spacing_mm: float,
    settings: StateDetectionSettings,
    axis: np.ndarray,
) -> OperatingStateDetection:
    """Build the bypassed-detector result: one interval over every profile."""
    intervals = _build_intervals(
        profile_count,
        np.empty(0, dtype=np.int64),
        axis,
        settings.minimum_relative_duration,
    )
    zeros = np.zeros(profile_count, dtype=np.float64)
    return OperatingStateDetection(
        mode=StateDetectionMode.SINGLE,
        settings=settings,
        artifact_id=artifact_id,
        descriptor=descriptor,
        profile_count=profile_count,
        gate_count=gate_count,
        time_step_s=time_step_s,
        gate_spacing_mm=gate_spacing_mm,
        transition_indices=np.empty(0, dtype=np.int64),
        intervals=intervals,
        variability=zeros.copy(),
        change_signal=zeros,
        base_threshold=None,
        applied_threshold=None,
        peak_prominence=None,
    )


def detect_operating_states(
    bundle: ChannelBundle,
    settings: StateDetectionSettings | None = None,
) -> OperatingStateDetection:
    """Detect operating-state intervals in one axial-velocity channel.

    Terminal producer (absorption plan §4). Reads the channel bundle's
    ``(T, G)`` velocity payload and returns a strict
    :class:`~udv_echo_process.models.states.OperatingStateDetection`. The input
    bundle — its artifact, payload, support and provenance graph — is never
    modified and no derived artifact or operation node is created.

    Args:
        bundle: the per-channel bundle (from ``select_channel``) to analyse.
        settings: detection parameters; ``StateDetectionSettings()`` defaults
            reproduce the archived baseline.

    Returns:
        The validated terminal result, with owned read-only trace arrays.

    Raises:
        StateDetectionInputError: the channel is not axial velocity, carries an
            invalid ``SampleSupport`` cell, has fewer than two gates or fewer
            than the mode's minimum profiles, or the change signal has no
            finite histogram support.
    """
    if not isinstance(bundle, ChannelBundle):
        raise TypeError(
            "detect_operating_states expects a ChannelBundle, got "
            f"{type(bundle).__name__}"
        )
    config = StateDetectionSettings() if settings is None else settings
    if not isinstance(config, StateDetectionSettings):
        raise TypeError(
            f"settings must be a StateDetectionSettings, got {type(config).__name__}"
        )

    artifact = bundle.artifact
    data = artifact.data
    descriptor = artifact.descriptor
    if descriptor.quantity is not SignalQuantity.AXIAL_VELOCITY:
        raise StateDetectionInputError(
            "operating-state detection requires an axial-velocity channel; "
            f"channel {artifact.acquisition.channel.device_channel} measures "
            f"{descriptor.quantity.value!r} ({descriptor.unit!r})"
        )

    support = data.support
    invalid = ~support.valid
    if invalid.any():
        count = int(invalid.sum())
        flat = int(np.flatnonzero(invalid.ravel())[0])
        time_i, gate_i = divmod(flat, invalid.shape[1])
        noun = "cell" if count == 1 else "cells"
        raise StateDetectionInputError(
            f"operating-state detection requires a fully valid channel: "
            f"{count} invalid {noun}, first at (time={time_i}, gate={gate_i}); "
            "invalid SampleSupport has no per-cell exclusion in this terminal "
            "step, so repair or select a fully observed channel first (the "
            "source artifact is left unchanged; no QualityFlag is set)"
        )

    field = data.values
    depths = data.gate_depths_mm
    axis = data.time_s
    profile_count, gate_count = field.shape
    if gate_count < 2:
        raise StateDetectionInputError(
            f"operating-state detection needs at least 2 gates, got {gate_count}"
        )
    if profile_count < 2:
        raise StateDetectionInputError(
            "operating-state detection needs at least 2 profiles (a sample "
            f"interval must exist), got {profile_count}"
        )
    if config.mode is StateDetectionMode.AUTO and profile_count < 3:
        raise StateDetectionInputError(
            f"automatic state detection needs at least 3 profiles, got {profile_count}"
        )

    time_step_s = float(np.median(np.diff(axis)))
    gate_spacing_mm = float(np.median(np.diff(depths)))

    if config.mode is StateDetectionMode.SINGLE:
        return _single_state_result(
            artifact.artifact_id,
            descriptor,
            profile_count,
            gate_count,
            time_step_s,
            gate_spacing_mm,
            config,
            axis,
        )

    time_radius = max(1, round(config.local_time_radius_s / time_step_s))
    depth_radius = max(1, round(config.local_depth_radius_mm / gate_spacing_mm))
    derivative_sigma = max(np.finfo(float).eps, config.derivative_sigma_s / time_step_s)
    persistence = max(np.finfo(float).eps, config.peak_persistence_s / time_step_s)

    # §4 chain: local-σ texture over the depth×time field, collapsed by a depth
    # median, then the absolute Gaussian time derivative of that profile trace.
    depth_time = np.ascontiguousarray(np.asarray(field, dtype=np.float32).T)
    minimum = float(np.min(depth_time))
    span = float(np.ptp(depth_time))
    normalized = (
        (depth_time - minimum) / span if span > 0 else np.zeros_like(depth_time)
    )
    window = (2 * depth_radius + 1, 2 * time_radius + 1)
    local_mean = uniform_filter(normalized, size=window, mode="reflect")
    local_second = uniform_filter(normalized * normalized, size=window, mode="reflect")
    local_std = np.sqrt(np.maximum(local_second - local_mean * local_mean, 0.0))
    variability = np.median(local_std, axis=0)
    derivative = gaussian_filter1d(
        variability, sigma=derivative_sigma, order=1, mode="reflect"
    )
    change = np.abs(derivative).astype(np.float64)
    change_span = float(np.ptp(change))
    change = (
        (change - float(np.min(change))) / change_span
        if change_span > 0
        else np.zeros_like(change)
    )

    base_threshold = _minimum_error_threshold(change, config.threshold_histogram_bins)
    applied_threshold = config.threshold_factor * base_threshold
    transitions, prominence = _persistent_peak_indices(
        change,
        persistence,
        applied_threshold,
        config.peak_prominence_std_factor,
    )
    intervals = _build_intervals(
        profile_count, transitions, axis, config.minimum_relative_duration
    )

    return OperatingStateDetection(
        mode=StateDetectionMode.AUTO,
        settings=config,
        artifact_id=artifact.artifact_id,
        descriptor=descriptor,
        profile_count=profile_count,
        gate_count=gate_count,
        time_step_s=time_step_s,
        gate_spacing_mm=gate_spacing_mm,
        transition_indices=transitions,
        intervals=intervals,
        variability=np.asarray(variability, dtype=np.float64),
        change_signal=change,
        base_threshold=base_threshold,
        applied_threshold=applied_threshold,
        peak_prominence=prominence,
    )


__all__ = [
    "StateDetectionInputError",
    "detect_operating_states",
]
