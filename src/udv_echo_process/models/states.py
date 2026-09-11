"""Terminal operating-state detection results (absorption plan §4, D2).

The retiring ``udv-analysis`` package detected discrete operating states by
collapsing a depth-resolved local-variability texture to a profile-axis signal,
differentiating it in time, thresholding the absolute derivative and keeping
persistent peaks (its ``processing/states.py``). That is a **terminal
``T -> U`` product** here, not an intermediate transform: it adds no
``SignalData`` field, no ``QualityFlag`` and no provenance node, and it never
mutates the source artifact or graph (plan §4, §6; D2, D5).

This module owns the immutable terminal result. Settings and interval records
are JSON-oriented; trace arrays are owned in-memory ndarrays and belong in the
separate JSON/CSV/NPZ export boundary planned for the rest of Phase 2:

- :class:`StateDetectionMode` — the two supported runs (``auto``/``single``);
- :class:`StateDetectionSettings` — the frozen analysis parameters;
- :class:`OperatingStateInterval` — one half-open ``[start, stop)`` span;
- :class:`OperatingStateDetection` — the strict terminal result, whose two
  ndarray traces are owned, C-contiguous and read-only via ``array_field``.

The invariants the detector must satisfy are enforced here so an inconsistent
result is unconstructible: the intervals are half-open, ordered and
non-overlapping and cover every profile except the transition samples — a
transition belongs to neither neighbour, so it is exactly the set of indices no
interval covers — a retained span is a ``kept`` interval, and single-state mode
is one interval over every profile.
"""

from __future__ import annotations

import math
import re
from enum import Enum

import numpy as np
from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.models.identity import SignalDescriptor, SignalQuantity

#: Opaque artifact-id form: ``sha256:`` plus 64 lower-case hex characters.
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


class StateDetectionMode(str, Enum):
    """How a recording's operating-state intervals were obtained.

    ``AUTO`` runs the spectral-texture detector; ``SINGLE`` is the explicit
    user declaration that the whole recording is one state, so the detector is
    bypassed and a single interval spans every profile.
    """

    AUTO = "auto"
    SINGLE = "single"


def _require_finite(value: float, *, field_name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return value


class StateDetectionSettings(ValueModel):
    """Frozen parameters for one operating-state detection run.

    Unit-bearing scales are physical seconds/millimetres; the detector converts
    them to integer profile/gate radii against the channel's own median sample
    and gate spacings. Defaults mirror the values the retiring package
    documented as its defaults, so ``StateDetectionSettings()`` reproduces the
    archived baseline runs. There is no TOML/config plane and no ``off`` mode:
    a caller either declares a single state or runs the detector (plan D3/D5).
    """

    mode: StateDetectionMode = StateDetectionMode.AUTO
    local_time_radius_s: float = 5.5
    local_depth_radius_mm: float = 7.0
    derivative_sigma_s: float = 2.75
    peak_persistence_s: float = 5.5
    threshold_factor: float = 0.5
    peak_prominence_std_factor: float = 0.2
    minimum_relative_duration: float = 0.03
    threshold_histogram_bins: int = 256

    @field_validator(
        "local_time_radius_s",
        "local_depth_radius_mm",
        "derivative_sigma_s",
        "peak_persistence_s",
        "threshold_factor",
    )
    @classmethod
    def _check_positive_finite(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and positive, got {value!r}"
            )
        return float(value)

    @field_validator("peak_prominence_std_factor")
    @classmethod
    def _check_nonnegative_finite(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and non-negative, got {value!r}"
            )
        return float(value)

    @field_validator("minimum_relative_duration")
    @classmethod
    def _check_relative_duration(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or not 0.0 <= value < 1.0:
            raise ValueError(f"{info.field_name} must lie in [0, 1), got {value!r}")
        return float(value)

    @field_validator("threshold_histogram_bins")
    @classmethod
    def _check_histogram_bins(cls, value: int, info: ValidationInfo) -> int:
        if value < 2:
            raise ValueError(f"{info.field_name} must be at least 2, got {value}")
        return int(value)


class OperatingStateInterval(ValueModel):
    """One candidate operating-state span as a half-open index range.

    ``[start_index, stop_index_exclusive)`` covers ``profile_count`` profiles;
    ``relative_duration`` is that count over the recording's profile count.
    ``kept`` marks a *retained* state span (longer than the settings' minimum
    relative duration); a dropped candidate keeps ``state_number=None`` and
    exists so the candidate spans still partition the recording.
    ``start_time_s``/``end_time_s`` are the first/last profile times and
    ``duration_s`` adds one sample interval, exactly as the source reported.
    """

    interval_number: int
    state_number: int | None
    kept: bool
    start_index: int
    stop_index_exclusive: int
    profile_count: int
    relative_duration: float
    start_time_s: float
    end_time_s: float
    duration_s: float

    @field_validator("interval_number", "state_number")
    @classmethod
    def _check_positive_number(
        cls, value: int | None, info: ValidationInfo
    ) -> int | None:
        if value is None:
            return None
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1, got {value}")
        return int(value)

    @field_validator("start_index")
    @classmethod
    def _check_start_index(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"start_index must be >= 0, got {value}")
        return int(value)

    @model_validator(mode="after")
    def _check_invariants(self) -> OperatingStateInterval:
        if self.stop_index_exclusive <= self.start_index:
            raise ValueError(
                "stop_index_exclusive must be greater than start_index "
                f"(got [{self.start_index}, {self.stop_index_exclusive}))"
            )
        expected_count = self.stop_index_exclusive - self.start_index
        if self.profile_count != expected_count:
            raise ValueError(
                f"profile_count must equal stop_index_exclusive - start_index "
                f"({expected_count}), got {self.profile_count}"
            )
        if self.state_number is None and self.kept:
            raise ValueError("a kept interval must carry a state_number (got None)")
        if self.state_number is not None and not self.kept:
            raise ValueError(
                f"a dropped interval must have state_number=None, got "
                f"{self.state_number}"
            )
        if not math.isfinite(self.relative_duration) or not (
            0.0 < self.relative_duration <= 1.0
        ):
            raise ValueError(
                f"relative_duration must lie in (0, 1], got {self.relative_duration!r}"
            )
        for name in ("start_time_s", "end_time_s", "duration_s"):
            _require_finite(getattr(self, name), field_name=name)
        if self.end_time_s < self.start_time_s:
            raise ValueError(
                "end_time_s must not precede start_time_s "
                f"({self.start_time_s!r} then {self.end_time_s!r})"
            )
        if self.duration_s < self.end_time_s - self.start_time_s:
            raise ValueError(
                "duration_s must cover the interval's time extent, got "
                f"{self.duration_s!r} for {self.end_time_s - self.start_time_s!r}"
            )
        return self


class OperatingStateDetection(ArrayModel):
    """Strict terminal result of one channel's operating-state detection.

    Ties the detection to the ``artifact_id`` it read (the SOURCE artifact is
    unchanged and the result is not a derived artifact, so there is no
    provenance edge). ``variability`` is the depth-median local-standard-
    deviation trace; ``change_signal`` is its normalized absolute Gaussian time
    derivative. ``transition_indices`` are the transition samples each of which
    belongs to *neither* neighbour (the intervals cover every other profile);
    ``intervals`` are half-open, ordered and non-overlapping, and carry the
    ``kept`` state spans. ``base_threshold``/``applied_threshold``/
    ``peak_prominence`` are ``None`` only in ``SINGLE`` mode, where the detector
    is bypassed.
    """

    mode: StateDetectionMode
    settings: StateDetectionSettings
    artifact_id: str
    descriptor: SignalDescriptor
    profile_count: int
    gate_count: int
    time_step_s: float
    gate_spacing_mm: float
    transition_indices: array_field(np.int64, rank=1)
    intervals: tuple[OperatingStateInterval, ...]
    variability: array_field(np.float64, rank=1)
    change_signal: array_field(np.float64, rank=1)
    base_threshold: float | None
    applied_threshold: float | None
    peak_prominence: float | None

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
        if value < 1:
            raise ValueError(f"profile_count must be >= 1, got {value}")
        return int(value)

    @field_validator("gate_count")
    @classmethod
    def _check_gate_count(cls, value: int) -> int:
        if value < 2:
            raise ValueError(f"gate_count must be >= 2, got {value}")
        return int(value)

    @field_validator("time_step_s", "gate_spacing_mm")
    @classmethod
    def _check_positive_spacing(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and positive, got {value!r}"
            )
        return float(value)

    @model_validator(mode="after")
    def _check_invariants(self) -> OperatingStateDetection:
        total = self.profile_count
        if self.descriptor.quantity is not SignalQuantity.AXIAL_VELOCITY:
            raise ValueError(
                "operating-state detection is defined for an axial-velocity "
                f"channel, got {self.descriptor.quantity.value!r}"
            )
        if self.mode is not self.settings.mode:
            raise ValueError(
                f"mode {self.mode.value!r} must match settings.mode "
                f"{self.settings.mode.value!r}"
            )
        if self.variability.shape != (total,):
            raise ValueError(
                f"variability must have shape ({total},), got {self.variability.shape}"
            )
        if self.change_signal.shape != (total,):
            raise ValueError(
                f"change_signal must have shape ({total},), got "
                f"{self.change_signal.shape}"
            )
        if not np.isfinite(self.variability).all():
            raise ValueError("variability must be finite")
        if not np.isfinite(self.change_signal).all():
            raise ValueError("change_signal must be finite")

        self._check_intervals()
        self._check_transitions()
        self._check_mode()
        return self

    def _check_intervals(self) -> None:
        total = self.profile_count
        intervals = self.intervals
        if not intervals:
            raise ValueError("intervals must contain at least one span")
        if intervals[0].start_index != 0:
            raise ValueError(
                "the first interval must start at index 0, got "
                f"{intervals[0].start_index}"
            )
        if intervals[-1].stop_index_exclusive != total:
            raise ValueError(
                "the last interval must stop at profile_count "
                f"({total}), got {intervals[-1].stop_index_exclusive}"
            )
        state_number = 0
        for index, interval in enumerate(intervals):
            if interval.interval_number != index + 1:
                raise ValueError(
                    f"interval_number must be {index + 1} at position {index}, "
                    f"got {interval.interval_number}"
                )
            if index:
                previous = intervals[index - 1]
                if interval.start_index < previous.stop_index_exclusive:
                    raise ValueError(
                        "intervals must be ordered and non-overlapping; "
                        f"interval {index + 1} starts at "
                        f"{interval.start_index} but interval {index} stopped "
                        f"at {previous.stop_index_exclusive}"
                    )
            retained = (
                interval.profile_count > self.settings.minimum_relative_duration * total
            )
            if interval.kept != retained:
                raise ValueError(
                    f"interval {interval.interval_number} kept="
                    f"{interval.kept} but its {interval.profile_count}/"
                    f"{total} share is {'' if retained else 'not '}above "
                    "minimum_relative_duration"
                )
            expected_relative = interval.profile_count / total
            if not math.isclose(
                interval.relative_duration, expected_relative, rel_tol=1e-9
            ):
                raise ValueError(
                    f"interval {interval.interval_number} relative_duration "
                    f"{interval.relative_duration!r} does not match "
                    f"{interval.profile_count}/{total}"
                )
            expected_duration = (
                interval.end_time_s - interval.start_time_s + self.time_step_s
            )
            if not math.isclose(
                interval.duration_s,
                expected_duration,
                rel_tol=1e-9,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"interval {interval.interval_number} duration_s "
                    f"{interval.duration_s!r} must equal its time extent plus "
                    f"one sample interval ({expected_duration!r})"
                )
            if interval.kept:
                state_number += 1
                if interval.state_number != state_number:
                    raise ValueError(
                        "kept state_number values must run 1..N in interval "
                        f"order; interval {interval.interval_number} has "
                        f"state_number {interval.state_number}, expected "
                        f"{state_number}"
                    )

    def _check_transitions(self) -> None:
        total = self.profile_count
        covered = np.zeros(total, dtype=bool)
        for interval in self.intervals:
            covered[interval.start_index : interval.stop_index_exclusive] = True
        uncovered = np.flatnonzero(~covered).astype(np.int64)
        if not np.array_equal(uncovered, self.transition_indices):
            raise ValueError(
                "every profile not covered by an interval must be a transition "
                f"and vice versa: uncovered indices are {uncovered.tolist()}, "
                f"got transition_indices {self.transition_indices.tolist()} "
                "(a transition belongs to neither neighbour)"
            )

    def _check_mode(self) -> None:
        thresholds = (
            self.base_threshold,
            self.applied_threshold,
            self.peak_prominence,
        )
        if self.mode is StateDetectionMode.SINGLE:
            if len(self.intervals) != 1:
                raise ValueError(
                    "single-state mode must yield exactly one interval spanning "
                    f"the recording, got {len(self.intervals)}"
                )
            if self.transition_indices.size:
                raise ValueError(
                    "single-state mode bypasses the detector and must have no "
                    "transition_indices"
                )
            if any(value is not None for value in thresholds):
                raise ValueError(
                    "single-state mode bypasses the detector, so "
                    "base_threshold/applied_threshold/peak_prominence must be "
                    "None"
                )
            return
        if self.profile_count < 3:
            raise ValueError(
                "automatic state detection needs at least 3 profiles, got "
                f"{self.profile_count}"
            )
        if any(value is None for value in thresholds):
            raise ValueError(
                "automatic state detection must report base_threshold, "
                "applied_threshold and peak_prominence"
            )
        for name in ("base_threshold", "applied_threshold", "peak_prominence"):
            _require_finite(getattr(self, name), field_name=name)
        base = self.base_threshold
        applied = self.applied_threshold
        assert base is not None and applied is not None  # narrowed by the check
        expected = self.settings.threshold_factor * base
        if not math.isclose(applied, expected, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                "applied_threshold must equal threshold_factor * "
                f"base_threshold ({expected!r}), got {applied!r}"
            )


__all__ = [
    "OperatingStateDetection",
    "OperatingStateInterval",
    "StateDetectionMode",
    "StateDetectionSettings",
]
