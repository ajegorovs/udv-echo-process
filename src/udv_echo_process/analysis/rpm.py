"""RPM analysis from single-sensor UDV echo recordings.

The rotor speed is estimated by taking the FFT of the echo signal,
averaging the magnitude spectrum across gate depths, and dividing the
dominant peak frequency by two (the echo amplitude modulates at twice
the rotor frequency).

Ported from ``references/wolfram/UDV_Data_Analysis_Echo.txt``
(``Fourier`` section).

Two entry points share one private kernel, so the numerical algorithm cannot
drift between the two pipelines:

- :func:`rpm_from_echo` — the legacy ``.ADD``/``ExtractedData`` path, whose
  public signature and tuple result are unchanged;
- :func:`rpm_from_channel` — the artifact-model entry point, taking a
  per-channel ``ChannelBundle`` and returning the strict terminal
  :class:`~udv_echo_process.models.rpm.EchoRpmEstimate`. It is a terminal
  ``T -> U`` product: no derived artifact, no provenance node, no support or
  quality change, and the source bundle is never mutated.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from numpy.fft import rfft, rfftfreq
from pydantic import BaseModel

from udv_echo_process.models.identity import SignalQuantity
from udv_echo_process.models.rpm import EchoRpmEstimate, EchoRpmSettings
from udv_echo_process.parser import ExtractedData, MeasType
from udv_echo_process.provenance import ChannelBundle


class RpmResult(BaseModel):
    """Result of an RPM estimation for one recording."""

    setpoint_rpm: int
    measured_rpm: float
    peak_freq_hz: float
    rel_error_pct: float
    n_samples: int


class EchoRpmInputError(ValueError):
    """The channel bundle cannot enter echo-RPM estimation."""


def _require_single_echo_channel(extracted: ExtractedData) -> None:
    """Raise unless the recording is exactly one channel of pure echo data.

    Both the FFT peak estimator and the TBD-derived sample interval are
    defined for a single echo channel only. A mux export can carry velocity
    and echo frames on one channel; silently combining the two would corrupt
    the cadence (duplicated TBD rows make the interval look halved) and the
    spectrum, so a mixed measurement type is rejected rather than partially
    ignored.
    """
    channels = extracted.by_channel()
    if len(channels) != 1:
        raise ValueError(
            "expected single-channel echo data; got channels "
            f"{sorted(channels)} — call per channel instead"
        )
    types = {f.meas_type for f in extracted.frames}
    if types != {MeasType.ECHO}:
        got = "+".join(sorted(t.value for t in types)) if types else "none"
        raise ValueError(
            "expected echo data only; got "
            f"{got} — select a pure echo channel before calling"
        )


def mean_sample_interval_s(extracted: ExtractedData) -> float:
    """Mean sampling interval in seconds, derived from the TBD column.

    Raw UDV echo rows carry a cumulative ``tbd_ms``; the mean of the
    per-sample differences (÷1000) is the effective sample interval used
    by the FFT frequency axis.

    Defined for a single echo channel only: raises ``ValueError`` when the
    data spans more than one channel or mixes echo with velocity frames (a
    one-channel mux export), instead of silently averaging the wrong cadence.
    """
    _require_single_echo_channel(extracted)
    tbds = np.array([f.tbd_ms for f in extracted.frames], dtype=float)
    if len(tbds) < 2:
        raise ValueError("need at least 2 frames to derive a sample interval")
    return float(np.mean(np.diff(tbds))) / 1000.0


def _echo_rpm_spectrum(
    values: np.ndarray, dt_s: float
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return ``(frequencies_hz, spectrum, peak_index)`` for one echo matrix.

    The single implementation of the FFT peak /2 arithmetic, shared by
    :func:`rpm_from_echo` and :func:`rpm_from_channel` so the two pipelines
    cannot drift:

    - ``frequencies_hz = rfftfreq(profile_count, d=dt_s)``;
    - ``spectrum = abs(rfft(values, axis=0)).mean(axis=1)`` — the **unnormalised
      mean magnitude across depth gates**, not a power or PSD estimate;
    - ``peak_index = argmax(spectrum[1:]) + 1`` — bin 0 is always excluded, so
      the reported mode can never be the DC bin.

    Args:
        values: the ``(profile, gate)`` echo matrix.
        dt_s: the effective sampling interval in seconds calibrating the axis.

    Returns:
        The frequency axis, the gate-averaged magnitude spectrum and the
        selected (non-DC) peak index.
    """
    arr = np.asarray(values)
    n_samples = arr.shape[0]
    frequencies_hz = rfftfreq(n_samples, d=dt_s)
    spectrum = np.abs(rfft(arr, axis=0)).mean(axis=1)
    peak_index = int(np.argmax(spectrum[1:])) + 1
    return frequencies_hz, spectrum, peak_index


def rpm_from_echo(
    extracted: ExtractedData,
    dt_s: float | None = None,
) -> tuple[float, float, int]:
    """Estimate rotor RPM via the FFT peak /2 method.

    Returns ``(measured_rpm, peak_freq_hz, n_samples)``.

    ``dt_s`` is the sampling interval in seconds; when omitted it is derived
    from the parsed data via :func:`mean_sample_interval_s`. The FFT method
    is defined for **single-sensor echo** recordings only: it requires exactly
    one channel and every frame to be an echo measurement. Multi-channel data
    must be routed per channel (e.g. via :meth:`ExtractedData.by_channel`);
    a one-channel mux export that mixes velocity and echo frames raises
    ``ValueError`` rather than silently selecting one quantity.
    """
    _require_single_echo_channel(extracted)
    if dt_s is None:
        dt_s = mean_sample_interval_s(extracted)
    arr = np.array([f.values for f in extracted.frames])  # (T, G)
    n_samples = arr.shape[0]
    frequencies_hz, _spectrum, peak_index = _echo_rpm_spectrum(arr, dt_s)
    peak_freq = float(frequencies_hz[peak_index])
    rpm = peak_freq / 2 * 60
    return rpm, peak_freq, n_samples


def rpm_from_channel(
    bundle: ChannelBundle,
    settings: EchoRpmSettings | None = None,
) -> EchoRpmEstimate:
    """Estimate one echo channel's rotor RPM and return the terminal result.

    The artifact-model entry point (see the module docstring). Reads the
    channel bundle's ``(profile, gate)`` echo payload and returns a strict
    :class:`~udv_echo_process.models.rpm.EchoRpmEstimate`. The input bundle —
    its artifact, payload, support and provenance graph — is never modified and
    no derived artifact or operation node is created.

    The frequency axis is calibrated by the **full-span effective interval**
    ``(time_s[-1] - time_s[0]) / (N - 1)`` after an interval-regularity guard,
    never by the median adjacent interval: on a quantized DOP timebase the
    median is the dominant timestamp quantum (3.2 ms of an alternating
    3.1/3.2 ms axis), not the sampling period, and using it shifts every
    recovered RPM by ~1% (see :mod:`udv_echo_process.models.rpm`).

    Args:
        bundle: the per-channel bundle (from ``select_channel``) to analyse.
        settings: regularity tolerance; ``EchoRpmSettings()`` accepts the
            committed quasi-uniform echo recordings and refuses a
            structurally sampled axis.

    Returns:
        The validated terminal result, with owned read-only trace arrays.

    Raises:
        TypeError: ``bundle`` is not a ``ChannelBundle``, or ``settings`` is not
            an ``EchoRpmSettings``.
        EchoRpmInputError: the channel is not echo amplitude, carries an
            invalid ``SampleSupport`` cell, has fewer than two profiles or
            fewer than one gate, or its time axis is not quasi-uniform within
            ``settings.uniform_rtol``.
    """
    if not isinstance(bundle, ChannelBundle):
        raise TypeError(
            f"rpm_from_channel expects a ChannelBundle, got {type(bundle).__name__}"
        )
    config = EchoRpmSettings() if settings is None else settings
    if not isinstance(config, EchoRpmSettings):
        raise TypeError(
            f"settings must be an EchoRpmSettings, got {type(config).__name__}"
        )

    artifact = bundle.artifact
    data = artifact.data
    descriptor = artifact.descriptor
    if descriptor.quantity is not SignalQuantity.ECHO_AMPLITUDE:
        raise EchoRpmInputError(
            "echo RPM requires an echo-amplitude channel; channel "
            f"{artifact.acquisition.channel.device_channel} measures "
            f"{descriptor.quantity.value!r} ({descriptor.unit!r})"
        )

    invalid = ~data.support.valid
    if invalid.any():
        count = int(invalid.sum())
        flat = int(np.flatnonzero(invalid.ravel())[0])
        time_i, gate_i = divmod(flat, invalid.shape[1])
        noun = "cell" if count == 1 else "cells"
        raise EchoRpmInputError(
            f"echo RPM requires a fully valid channel: {count} invalid {noun}, "
            f"first at (time={time_i}, gate={gate_i}); invalid SampleSupport "
            "has no per-cell exclusion in this terminal step, so repair or "
            "select a fully observed channel first (the source artifact is "
            "left unchanged; no QualityFlag is set)"
        )

    field = data.values
    profile_count, gate_count = field.shape
    if profile_count < 2:
        raise EchoRpmInputError(
            "echo RPM needs at least 2 profiles (a sample interval must "
            f"exist), got {profile_count}"
        )
    if gate_count < 1:
        raise EchoRpmInputError(
            f"echo RPM needs at least 1 gate to average across, got {gate_count}"
        )

    axis = np.asarray(data.time_s, dtype=np.float64)
    intervals = np.diff(axis)
    representative_interval = float(np.median(intervals))
    time_step_s = float((axis[-1] - axis[0]) / (profile_count - 1))
    deviation = (
        float(np.max(np.abs(intervals - representative_interval)))
        / representative_interval
    )
    if deviation > config.uniform_rtol:
        raise EchoRpmInputError(
            "echo RPM requires a quasi-uniform time axis: the maximum relative "
            f"interval deviation {deviation!r} exceeds uniform_rtol "
            f"{config.uniform_rtol!r} (median interval "
            f"{representative_interval!r} s, full-span effective interval "
            f"{time_step_s!r} s); an rFFT cannot be calibrated on a "
            "structurally sampled (burst/visit) axis — resample to a uniform "
            "grid through the artifact process layer and estimate the derived "
            "bundle instead (the source artifact is left unchanged)"
        )

    frequencies_hz, spectrum, peak_index = _echo_rpm_spectrum(field, time_step_s)
    peak_freq_hz = float(frequencies_hz[peak_index])
    return EchoRpmEstimate(
        settings=config,
        artifact_id=artifact.artifact_id,
        descriptor=descriptor,
        profile_count=profile_count,
        gate_count=gate_count,
        time_step_s=time_step_s,
        max_relative_interval_deviation=deviation,
        peak_index=peak_index,
        peak_freq_hz=peak_freq_hz,
        rpm=peak_freq_hz / 2 * 60,
        frequencies_hz=frequencies_hz,
        spectrum=spectrum,
    )


def setpoint_rpm_from_stem(stem: str) -> int:
    """Extract the setpoint RPM from a filename stem like '650' or '200RPM_v2'."""
    m = re.search(r"(\d+)", Path(stem).stem)
    if not m:
        raise ValueError(f"cannot parse RPM setpoint from stem: {stem!r}")
    return int(m.group(1))


__all__ = [
    "EchoRpmInputError",
    "RpmResult",
    "mean_sample_interval_s",
    "rpm_from_channel",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
]
