"""Terminal echo-RPM estimate for one echo-amplitude channel.

The rotor speed of a single-sensor echo recording is estimated from the FFT of
its ``(profile, gate)`` amplitude matrix: the magnitude spectrum is averaged
across gate depths, DC is excluded, the dominant remaining mode is selected and
converted with ``rpm = peak_frequency_hz / 2 * 60``. That is a **terminal
``T -> U`` product** here, not a ``ChannelBundle -> ChannelBundle`` transform:
it adds no ``SignalData`` field, no ``SupportKind``/``QualityFlag``, no
provenance node and no storage payload, and it never mutates the source
artifact or graph (the same shape as :mod:`udv_echo_process.models.states` and
:mod:`udv_echo_process.models.profiles`).

Three contract points this module owns:

- **Frequency calibration.** The FFT frequency axis is calibrated by the
  *full-span effective interval* ``(t[-1] - t[0]) / (N - 1)``, never by the
  median adjacent interval. A quantized DOP timebase alternates between two
  timestamp quanta (``3.1``/``3.2`` ms on the committed echo fixtures), so the
  median is the dominant quantum rather than the sampling period; using it
  shifts every recovered RPM by ~1%.
- **Regularity guard.** ``np.fft.rfft`` assumes uniformly spaced samples, so the
  measured worst-case relative deviation of the adjacent intervals from their
  median is recorded on the result and must not exceed
  :attr:`EchoRpmSettings.uniform_rtol`. A structurally sampled (burst/visit)
  axis is refused instead of being silently compacted onto its median cadence.
- **The ``/2`` factor is rig-specific.** The echo amplitude of this campaign
  modulates at twice the rotor frequency (two echo features per revolution).
  It is not a universal Doppler identity, so the factor is fixed in the
  estimator's contract rather than exposed as a setting.

Only settings and scalars are JSON-oriented; the two trace arrays
(:attr:`EchoRpmEstimate.frequencies_hz`, :attr:`EchoRpmEstimate.spectrum`) are
owned in-memory ndarrays and belong in the separate JSON/CSV/NPZ export
boundary, not in a manifest.
"""

from __future__ import annotations

import math
import re

import numpy as np
from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.models.identity import SignalDescriptor, SignalQuantity

#: Opaque artifact-id form: ``sha256:`` plus 64 lower-case hex characters.
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


class EchoRpmSettings(ValueModel):
    """Frozen parameters for one echo-RPM estimation run.

    Exactly one parameter exists, and it is the input's regularity guard rather
    than an algorithm knob:

    ``uniform_rtol``
        maximum allowed relative deviation of an adjacent time interval from
        the axis' median interval, for the rFFT's uniform-spacing assumption to
        hold. Bounded by a hard ``0.05`` ceiling: the committed single-channel
        echo recordings deviate by 3.125% (they pass), while a burst-sampled
        recording deviates by ~46x (it is refused) — a larger tolerance would
        not make an irregular axis uniform, it would only hide the defect.

    Deliberately absent: a raw ``lowest_bin_index`` (a bin index is
    recording-length-dependent and would let the DC bin report a misleading
    0 RPM — the estimator excludes exactly the DC bin and searches every other
    rFFT bin), a ``dt_s`` override (overriding a scalar cannot make irregular
    samples uniform; resample through the artifact process layer and estimate
    the derived bundle instead) and any windowing, detrending, peak
    interpolation or confidence threshold (all out of scope for this port).
    """

    uniform_rtol: float = 0.05

    @field_validator("uniform_rtol")
    @classmethod
    def _check_uniform_rtol(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 0.05:
            raise ValueError(
                f"{info.field_name} must be finite and lie in [0, 0.05], got "
                f"{value!r} (the committed quasi-uniform echo recordings need "
                "0.03125; a structural gap is never tolerated)"
            )
        return float(value)


class EchoRpmEstimate(ArrayModel):
    """Strict terminal result of one echo channel's RPM estimation.

    Ties the estimate to the ``artifact_id`` it read (the SOURCE artifact is
    unchanged and no derived artifact exists, so there is no provenance edge).
    ``time_step_s`` is the effective full-span sampling interval the FFT
    frequency axis was calibrated with and ``max_relative_interval_deviation``
    is the measured worst-case interval deviation that the guard admitted, so a
    consumer can see exactly how uniform the axis really was.

    ``peak_index`` indexes both ``frequencies_hz`` and ``spectrum``, and the
    two trace arrays are owned, C-contiguous and read-only through
    :func:`~udv_echo_process.models.base.array_field`.
    """

    settings: EchoRpmSettings
    artifact_id: str
    descriptor: SignalDescriptor
    profile_count: int
    gate_count: int
    time_step_s: float
    max_relative_interval_deviation: float
    peak_index: int
    peak_freq_hz: float
    rpm: float
    frequencies_hz: array_field(np.float64, rank=1)
    spectrum: array_field(np.float64, rank=1)

    @field_validator("artifact_id")
    @classmethod
    def _check_artifact_id(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip()
        if not _SHA256_ID_RE.fullmatch(text):
            raise ValueError(
                f"{info.field_name} must be an opaque lower-case "
                f"'sha256:<64 hex>' id, got {value!r}"
            )
        return text

    @field_validator("profile_count")
    @classmethod
    def _check_profile_count(cls, value: int) -> int:
        if value < 2:
            raise ValueError(
                f"profile_count must be >= 2 (a sample interval must exist), "
                f"got {value}"
            )
        return int(value)

    @field_validator("gate_count")
    @classmethod
    def _check_gate_count(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"gate_count must be >= 1, got {value}")
        return int(value)

    @field_validator("time_step_s")
    @classmethod
    def _check_time_step(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and positive, got {value!r}"
            )
        return float(value)

    @field_validator("max_relative_interval_deviation")
    @classmethod
    def _check_deviation(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and non-negative, got {value!r}"
            )
        return float(value)

    @model_validator(mode="after")
    def _check_invariants(self) -> EchoRpmEstimate:
        if self.descriptor.quantity is not SignalQuantity.ECHO_AMPLITUDE:
            raise ValueError(
                "echo RPM is defined for an echo-amplitude channel, got "
                f"{self.descriptor.quantity.value!r} ({self.descriptor.unit!r}); "
                "a velocity channel needs a velocity-domain estimator, not the "
                "echo FFT peak method"
            )

        expected_bins = self.profile_count // 2 + 1
        if self.frequencies_hz.shape != (expected_bins,):
            raise ValueError(
                "frequencies_hz must have shape "
                f"({expected_bins},) for {self.profile_count} profiles, got "
                f"{self.frequencies_hz.shape}"
            )
        if self.spectrum.shape != (expected_bins,):
            raise ValueError(
                f"spectrum must have shape ({expected_bins},), got "
                f"{self.spectrum.shape}"
            )
        if not np.isfinite(self.spectrum).all():
            index = int(np.flatnonzero(~np.isfinite(self.spectrum))[0])
            raise ValueError(
                f"spectrum must be finite (no NaN/Infinity); index {index} has "
                f"value {self.spectrum[index]}"
            )
        if not np.isfinite(self.frequencies_hz).all():
            index = int(np.flatnonzero(~np.isfinite(self.frequencies_hz))[0])
            raise ValueError(
                f"frequencies_hz must be finite; index {index} has value "
                f"{self.frequencies_hz[index]}"
            )
        if (self.spectrum < 0.0).any():
            index = int(np.flatnonzero(self.spectrum < 0.0)[0])
            raise ValueError(
                "spectrum must be non-negative (it is a magnitude spectrum); "
                f"index {index} has value {self.spectrum[index]}"
            )

        if not 1 <= self.peak_index < expected_bins:
            raise ValueError(
                f"peak_index must lie in [1, {expected_bins - 1}] (the DC bin is "
                f"always excluded), got {self.peak_index}"
            )
        expected_peak = int(np.argmax(self.spectrum[1:])) + 1
        if self.peak_index != expected_peak:
            raise ValueError(
                "peak_index must be the maximum of the non-DC spectrum "
                f"(argmax(spectrum[1:]) + 1 = {expected_peak}), got "
                f"{self.peak_index}"
            )

        expected_axis = np.fft.rfftfreq(self.profile_count, d=self.time_step_s)
        if not np.array_equal(self.frequencies_hz, expected_axis):
            raise ValueError(
                "frequencies_hz must equal the rfftfreq frequency axis for "
                f"{self.profile_count} profiles at time_step_s="
                f"{self.time_step_s!r} (rfftfreq(profile_count, d=time_step_s)); "
                "it does not, so the peak frequency would be mislabelled"
            )
        if self.peak_freq_hz != float(self.frequencies_hz[self.peak_index]):
            raise ValueError(
                "peak_freq_hz must equal frequencies_hz[peak_index] "
                f"({float(self.frequencies_hz[self.peak_index])!r}), got "
                f"{self.peak_freq_hz!r}"
            )
        expected_rpm = self.peak_freq_hz / 2 * 60
        if self.rpm != expected_rpm:
            raise ValueError(
                "rpm must equal peak_freq_hz / 2 * 60 (the rig-specific "
                f"two-features-per-revolution factor), got {self.rpm!r} for "
                f"{expected_rpm!r}"
            )
        if self.max_relative_interval_deviation > self.settings.uniform_rtol:
            raise ValueError(
                "max_relative_interval_deviation must not exceed "
                f"settings.uniform_rtol ({self.settings.uniform_rtol!r}), got "
                f"{self.max_relative_interval_deviation!r}: an axis that "
                "irregular cannot be calibrated by one rFFT interval"
            )
        return self


__all__ = [
    "EchoRpmEstimate",
    "EchoRpmSettings",
]
