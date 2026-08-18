"""RPM analysis from single-sensor UDV echo recordings.

The rotor speed is estimated by taking the FFT of the echo signal,
averaging the magnitude spectrum across gate depths, and dividing the
dominant peak frequency by two (the echo amplitude modulates at twice
the rotor frequency).

Ported from ``references/wolfram/UDV_Data_Analysis_Echo.txt``
(``Fourier`` section).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.fft import rfft, rfftfreq

from udv_echo_process.parser import ExtractedData


@dataclass(frozen=True)
class RpmResult:
    """Result of an RPM estimation for one recording."""

    setpoint_rpm: int
    measured_rpm: float
    peak_freq_hz: float
    rel_error_pct: float
    n_samples: int


def rpm_from_echo(
    extracted: ExtractedData,
    dt_s: float,
) -> tuple[float, float, int]:
    """Estimate rotor RPM via the FFT peak /2 method.

    Returns ``(measured_rpm, peak_freq_hz, n_samples)``.
    """
    arr = np.array([f.values for f in extracted.frames])  # (T, G)
    n_samples = arr.shape[0]
    freqs = rfftfreq(n_samples, d=dt_s)
    spec = np.abs(rfft(arr, axis=0)).mean(axis=1)
    peak_idx = int(np.argmax(spec[1:])) + 1
    peak_freq = freqs[peak_idx]
    rpm = peak_freq / 2 * 60
    return rpm, peak_freq, n_samples


def setpoint_rpm_from_stem(stem: str) -> int:
    """Extract the setpoint RPM from a filename stem like '650' or '200RPM_v2'."""
    m = re.search(r"(\d+)", Path(stem).stem)
    if not m:
        raise ValueError(f"cannot parse RPM setpoint from stem: {stem!r}")
    return int(m.group(1))
