"""Typed terminal operating-state detection (absorption plan §4, D2/D5).

Coverage:

- ``StateDetectionSettings``/``OperatingStateInterval`` model invariants;
- synthetic edge cases for the detector's interval invariants: half-open,
  ordered, non-overlapping spans that cover the recording, transitions that
  belong to neither neighbour, the ``kept`` minimum-duration rule, and the
  single-state bypass that spans every profile;
- the explicit invalid-``SampleSupport`` policy (refused, never relabelled, no
  ``QualityFlag.EXCLUDED``);
- the input contract (axial-velocity descriptor only, a ``ChannelBundle``);
- a real steady velocity fixture (``data/4-sensor-velocity/200RPM.BDD`` channel
  6) whose decoded payload is byte-identical to the archived baseline capture;
- an OPTIONAL archived-baseline comparison, enabled by the
  ``UDV_ANALYSIS_ARCHIVE`` environment variable pointing at the private
  retirement pack, which replays the archived auto/single baseline on the
  archived detector input and compares the traces, thresholds, transitions and
  intervals exactly.

Honest limitation (archive ``limitations_probe``/B3): the archive contains **no
real multi-state velocity fixture** — every committed velocity recording is a
steady 200 RPM run with one state and zero transitions — so the real-data
comparison can only prove the degenerate single-interval path. The
multi-transition path is therefore exercised on synthetic regimes only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis.states import (
    StateDetectionInputError,
    detect_operating_states,
)
from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    OperatingStateDetection,
    OperatingStateInterval,
    QualityFlag,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    StateDetectionMode,
    StateDetectionSettings,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.provenance import ChannelBundle, select_channel, source_bundle

REPO = Path(__file__).resolve().parents[1]
FOUR_SENSOR = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")


# ── builders ─────────────────────────────────────────────────────────────


def _bundle(
    field: object,
    *,
    time_s: object = None,
    gate_depths: object = None,
    channel: int = 6,
    descriptor: SignalDescriptor = _VELOCITY,
    data: SignalData | None = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` for one velocity payload."""
    if data is None:
        arr = np.asarray(field, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr[:, None]
        n, g = arr.shape
        if time_s is None:
            time_s = np.arange(n, dtype=np.float64) * 0.1
        if gate_depths is None:
            gate_depths = np.linspace(10.0, 50.0, g)
        data = observed_signal(time_s, gate_depths, arr)
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    return source_bundle(source_artifact(ref, descriptor, ChannelConfig(), data))


def _interval(**over: object) -> OperatingStateInterval:
    base: dict[str, object] = {
        "interval_number": 1,
        "state_number": 1,
        "kept": True,
        "start_index": 0,
        "stop_index_exclusive": 10,
        "profile_count": 10,
        "relative_duration": 1.0,
        "start_time_s": 0.0,
        "end_time_s": 0.9,
        "duration_s": 1.0,
    }
    base.update(over)
    return OperatingStateInterval(**base)  # type: ignore[arg-type]


def _result(**over: object) -> OperatingStateDetection:
    base: dict[str, object] = {
        "mode": StateDetectionMode.AUTO,
        "settings": StateDetectionSettings(),
        "artifact_id": _ASSET_ID,
        "descriptor": _VELOCITY,
        "profile_count": 10,
        "gate_count": 2,
        "time_step_s": 0.1,
        "gate_spacing_mm": 1.0,
        "transition_indices": np.empty(0, dtype=np.int64),
        "intervals": (_interval(),),
        "variability": np.zeros(10, dtype=np.float64),
        "change_signal": np.zeros(10, dtype=np.float64),
        "base_threshold": 0.5,
        "applied_threshold": 0.25,
        "peak_prominence": 0.0,
    }
    base.update(over)
    return OperatingStateDetection(**base)  # type: ignore[arg-type]


def _two_regime_field(
    n: int = 400, g: int = 8
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A synthetic low-texture → high-texture regime change near index n/2."""
    time_s = np.arange(n, dtype=np.float64) * 0.1
    depth = np.linspace(10.0, 50.0, g)
    phase = np.arange(n, dtype=np.float64)[:, None]
    field = np.zeros((n, g), dtype=np.float64)
    half = n // 2
    field[:half] = 0.1 * np.sin(phase[:half] / 5.0)
    field[half:] = 6.0 * np.sin(phase[half:] / 3.0) * np.linspace(1.0, 2.0, g)
    return field, time_s, depth


_MULTI_STATE = StateDetectionSettings(
    local_time_radius_s=1.0,
    local_depth_radius_mm=6.0,
    derivative_sigma_s=0.4,
    peak_persistence_s=0.8,
    threshold_factor=0.5,
    peak_prominence_std_factor=0.2,
    minimum_relative_duration=0.01,
    threshold_histogram_bins=256,
)


# ── StateDetectionSettings ───────────────────────────────────────────────


class TestSettings:
    def test_defaults_are_the_archived_baseline_defaults(self) -> None:
        settings = StateDetectionSettings()
        assert settings.mode is StateDetectionMode.AUTO
        assert settings.local_time_radius_s == 5.5
        assert settings.local_depth_radius_mm == 7.0
        assert settings.derivative_sigma_s == 2.75
        assert settings.peak_persistence_s == 5.5
        assert settings.threshold_factor == 0.5
        assert settings.peak_prominence_std_factor == 0.2
        assert settings.minimum_relative_duration == 0.03
        assert settings.threshold_histogram_bins == 256

    def test_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings().mode = StateDetectionMode.SINGLE  # type: ignore[misc]

    def test_unknown_field_is_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings(local_time_radius_seconds=1.0)  # type: ignore[call-arg]

    @pytest.mark.parametrize(
        "field",
        [
            "local_time_radius_s",
            "local_depth_radius_mm",
            "derivative_sigma_s",
            "peak_persistence_s",
            "threshold_factor",
        ],
    )
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_scale_fields_must_be_positive_and_finite(self, field, bad) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings(**{field: bad})  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
    def test_prominence_factor_must_be_non_negative_and_finite(self, bad) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings(peak_prominence_std_factor=bad)

    def test_zero_prominence_factor_is_allowed(self) -> None:
        assert (
            StateDetectionSettings(
                peak_prominence_std_factor=0.0
            ).peak_prominence_std_factor
            == 0.0
        )

    @pytest.mark.parametrize("bad", [-0.01, 1.0, float("nan")])
    def test_minimum_relative_duration_must_lie_in_half_open_unit(self, bad) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings(minimum_relative_duration=bad)

    def test_minimum_relative_duration_zero_is_allowed(self) -> None:
        assert (
            StateDetectionSettings(
                minimum_relative_duration=0.0
            ).minimum_relative_duration
            == 0.0
        )

    @pytest.mark.parametrize("bad", [1, 0, -4])
    def test_histogram_bins_must_be_at_least_two(self, bad) -> None:
        with pytest.raises(ValidationError):
            StateDetectionSettings(threshold_histogram_bins=bad)

    def test_settings_round_trip_through_json(self) -> None:
        settings = StateDetectionSettings(
            mode=StateDetectionMode.SINGLE, threshold_factor=0.25
        )
        again = StateDetectionSettings.model_validate_json(settings.model_dump_json())
        assert again == settings


# ── OperatingStateInterval ───────────────────────────────────────────────


class TestIntervalModel:
    def test_valid_interval_round_trips(self) -> None:
        interval = _interval()
        assert (
            OperatingStateInterval.model_validate_json(interval.model_dump_json())
            == interval
        )

    def test_dropped_interval_has_no_state_number(self) -> None:
        interval = _interval(
            state_number=None,
            kept=False,
            profile_count=2,
            stop_index_exclusive=2,
            relative_duration=0.2,
            end_time_s=0.1,
            duration_s=0.2,
        )
        assert interval.state_number is None and not interval.kept

    @pytest.mark.parametrize(
        ("over", "message"),
        [
            ({"stop_index_exclusive": 0}, "greater than start_index"),
            ({"profile_count": 3}, "profile_count must equal"),
            ({"state_number": None}, "kept interval must carry"),
            ({"kept": False}, "dropped interval must have state_number=None"),
            ({"relative_duration": 0.0}, "relative_duration must lie"),
            ({"relative_duration": 1.5}, "relative_duration must lie"),
            ({"duration_s": 0.1}, "duration_s must cover"),
            ({"start_time_s": 5.0}, "end_time_s must not precede"),
        ],
    )
    def test_interval_invariants_are_enforced(self, over, message) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _interval(**over)
        assert message in str(excinfo.value)


# ── the result model invariants (hand-built violations) ──────────────────


class TestResultModel:
    def test_valid_result_constructs(self) -> None:
        result = _result()
        assert result.mode is StateDetectionMode.AUTO
        assert len(result.intervals) == 1

    def test_artifact_id_must_be_opaque_sha256(self) -> None:
        with pytest.raises(ValidationError):
            _result(artifact_id="not-an-id")

    def test_descriptor_must_be_axial_velocity(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(descriptor=_ECHO)
        assert "axial-velocity" in str(excinfo.value)

    def test_mode_must_match_settings(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(
                mode=StateDetectionMode.SINGLE,
                base_threshold=None,
                applied_threshold=None,
                peak_prominence=None,
            )
        assert "must match settings.mode" in str(excinfo.value)

    @pytest.mark.parametrize("field", ["variability", "change_signal"])
    def test_traces_must_match_profile_count(self, field) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(**{field: np.zeros(9, dtype=np.float64)})
        assert "shape (10,)" in str(excinfo.value)

    def test_intervals_must_start_at_zero(self) -> None:
        interval = _interval(
            start_index=2,
            stop_index_exclusive=10,
            profile_count=8,
            relative_duration=0.8,
            start_time_s=0.2,
            duration_s=0.8,
        )
        with pytest.raises(ValidationError) as excinfo:
            _result(intervals=(interval,))
        assert "first interval must start at index 0" in str(excinfo.value)

    def test_intervals_must_stop_at_profile_count(self) -> None:
        interval = _interval(
            stop_index_exclusive=9,
            profile_count=9,
            relative_duration=0.9,
            duration_s=0.9,
        )
        with pytest.raises(ValidationError) as excinfo:
            _result(intervals=(interval,))
        assert "last interval must stop at profile_count" in str(excinfo.value)

    def test_intervals_must_be_ordered_and_non_overlapping(self) -> None:
        first = _interval(
            stop_index_exclusive=6,
            profile_count=6,
            relative_duration=0.6,
            end_time_s=0.5,
            duration_s=0.6,
        )
        second = _interval(
            interval_number=2,
            state_number=2,
            start_index=5,
            stop_index_exclusive=10,
            profile_count=5,
            relative_duration=0.5,
            start_time_s=0.5,
            end_time_s=0.9,
            duration_s=0.5,
        )
        with pytest.raises(ValidationError) as excinfo:
            _result(intervals=(first, second), transition_indices=np.empty(0, np.int64))
        assert "ordered and non-overlapping" in str(excinfo.value)

    def test_uncovered_indices_must_be_exactly_the_transitions(self) -> None:
        first = _interval(
            stop_index_exclusive=5,
            profile_count=5,
            relative_duration=0.5,
            end_time_s=0.4,
            duration_s=0.5,
        )
        second = _interval(
            interval_number=2,
            state_number=2,
            start_index=7,
            stop_index_exclusive=10,
            profile_count=3,
            relative_duration=0.3,
            start_time_s=0.7,
            end_time_s=0.9,
            duration_s=0.3,
        )
        # a gap that is not a transition is rejected ...
        with pytest.raises(ValidationError) as excinfo:
            _result(intervals=(first, second), transition_indices=np.empty(0, np.int64))
        assert "uncovered indices are [5, 6]" in str(excinfo.value)
        # ... and accepted when it is exactly the transition set
        result = _result(
            intervals=(first, second), transition_indices=np.array([5, 6], np.int64)
        )
        assert result.transition_indices.tolist() == [5, 6]

    def test_transition_sample_belongs_to_no_interval(self) -> None:
        first = _interval(
            stop_index_exclusive=5,
            profile_count=5,
            relative_duration=0.5,
            end_time_s=0.4,
            duration_s=0.5,
        )
        second = _interval(
            interval_number=2,
            state_number=2,
            start_index=6,
            stop_index_exclusive=10,
            profile_count=4,
            relative_duration=0.4,
            start_time_s=0.6,
            end_time_s=0.9,
            duration_s=0.4,
        )
        result = _result(
            intervals=(first, second), transition_indices=np.array([5], np.int64)
        )
        assert result.transition_indices.tolist() == [5]
        with pytest.raises(ValidationError) as excinfo:
            _result(intervals=(first, second), transition_indices=np.empty(0, np.int64))
        assert "must be a transition" in str(excinfo.value)

    def test_kept_rule_is_enforced(self) -> None:
        interval = _interval(
            state_number=None,
            kept=False,
            stop_index_exclusive=3,
            profile_count=3,
            relative_duration=1.0,
            end_time_s=0.2,
            duration_s=0.3,
        )
        with pytest.raises(ValidationError) as excinfo:
            _result(
                profile_count=3,
                variability=np.zeros(3, np.float64),
                change_signal=np.zeros(3, np.float64),
                intervals=(interval,),
            )
        assert "share is above minimum_relative_duration" in str(excinfo.value)

    def test_applied_threshold_must_be_factor_times_base(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(applied_threshold=0.9)
        assert "threshold_factor * base_threshold" in str(excinfo.value)

    def test_auto_mode_requires_thresholds_and_three_profiles(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(base_threshold=None)
        assert "must report base_threshold" in str(excinfo.value)
        with pytest.raises(ValidationError) as excinfo:
            _result(
                profile_count=2,
                variability=np.zeros(2, np.float64),
                change_signal=np.zeros(2, np.float64),
                intervals=(
                    _interval(
                        stop_index_exclusive=2,
                        profile_count=2,
                        relative_duration=1.0,
                        end_time_s=0.1,
                        duration_s=0.2,
                    ),
                ),
            )
        assert "needs at least 3 profiles" in str(excinfo.value)

    def test_single_mode_is_one_span_with_no_detector_values(self) -> None:
        settings = StateDetectionSettings(mode=StateDetectionMode.SINGLE)
        result = _result(
            mode=StateDetectionMode.SINGLE,
            settings=settings,
            base_threshold=None,
            applied_threshold=None,
            peak_prominence=None,
        )
        assert len(result.intervals) == 1 and result.intervals[0].kept
        with pytest.raises(ValidationError) as excinfo:
            _result(
                mode=StateDetectionMode.SINGLE,
                settings=settings,
                base_threshold=0.5,
                applied_threshold=0.25,
            )
        assert "must be None" in str(excinfo.value)


# ── producer input contract ──────────────────────────────────────────────


class TestInputContract:
    def test_echo_channel_is_refused(self) -> None:
        bundle = _bundle(np.ones((20, 3)), descriptor=_ECHO)
        with pytest.raises(StateDetectionInputError) as excinfo:
            detect_operating_states(bundle)
        assert "axial-velocity" in str(excinfo.value)

    def test_non_bundle_is_a_type_error(self) -> None:
        with pytest.raises(TypeError):
            detect_operating_states("not a bundle")  # type: ignore[arg-type]

    def test_invalid_sample_support_is_refused_with_location(self) -> None:
        time_s = np.arange(20, dtype=np.float64) * 0.1
        depth = np.linspace(10.0, 50.0, 4)
        values = np.ones((20, 4), dtype=np.float64)
        values[5, 2] = np.nan
        quality = np.zeros((20, 4), dtype=np.uint32)
        quality[5, 2] = int(QualityFlag.OUTLIER)
        data = observed_signal(time_s, depth, values, quality=quality)
        bundle = _bundle(None, data=data)
        with pytest.raises(StateDetectionInputError) as excinfo:
            detect_operating_states(bundle)
        message = str(excinfo.value)
        assert "invalid cell" in message
        assert "(time=5, gate=2)" in message
        # the artifact is untouched: the invalid cell is still NaN / invalid
        assert np.isnan(bundle.artifact.data.values[5, 2])
        assert not bundle.artifact.data.support.valid[5, 2]

    def test_quality_flag_has_no_excluded_bit(self) -> None:
        assert not hasattr(QualityFlag, "EXCLUDED")

    def test_fewer_than_two_gates_is_refused(self) -> None:
        bundle = _bundle(np.ones((20, 1)))
        with pytest.raises(StateDetectionInputError) as excinfo:
            detect_operating_states(bundle)
        assert "at least 2 gates" in str(excinfo.value)

    def test_auto_needs_three_profiles_but_single_needs_two(self) -> None:
        field = np.ones((2, 4), dtype=np.float64)
        bundle = _bundle(field)
        with pytest.raises(StateDetectionInputError, match="at least 3 profiles"):
            detect_operating_states(bundle)
        result = detect_operating_states(
            bundle, StateDetectionSettings(mode=StateDetectionMode.SINGLE)
        )
        assert result.profile_count == 2

    def test_one_profile_is_refused(self) -> None:
        with pytest.raises(StateDetectionInputError, match="at least 2 profiles"):
            detect_operating_states(
                _bundle(np.ones((1, 4))),
                StateDetectionSettings(mode=StateDetectionMode.SINGLE),
            )


# ── synthetic edge/invariant behaviour ───────────────────────────────────


def _covered_indices(result: OperatingStateDetection) -> list[int]:
    covered: list[int] = []
    for interval in result.intervals:
        covered.extend(range(interval.start_index, interval.stop_index_exclusive))
    return covered


class TestSyntheticInvariants:
    def test_steady_field_is_one_state_with_no_transitions(self) -> None:
        result = detect_operating_states(_bundle(np.full((60, 5), 12.0)))
        assert result.mode is StateDetectionMode.AUTO
        assert result.transition_indices.size == 0
        assert len(result.intervals) == 1
        interval = result.intervals[0]
        assert (interval.start_index, interval.stop_index_exclusive) == (0, 60)
        assert interval.kept and interval.state_number == 1

    def test_intervals_cover_every_profile_except_transitions(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth), _MULTI_STATE
        )
        covered = _covered_indices(result)
        assert len(covered) == len(set(covered))  # half-open and non-overlapping
        assert sorted(covered + result.transition_indices.tolist()) == list(
            range(result.profile_count)
        )

    def test_transitions_belong_to_neither_neighbour(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth), _MULTI_STATE
        )
        assert result.transition_indices.size >= 1
        covered = set(_covered_indices(result))
        for transition in result.transition_indices.tolist():
            assert transition not in covered

            def span_of(index: int) -> int:
                return next(
                    i
                    for i, interval in enumerate(result.intervals)
                    if interval.start_index <= index < interval.stop_index_exclusive
                )

            left, right = transition - 1, transition + 1
            if left in covered and right in covered:
                assert span_of(left) != span_of(right)

    def test_a_regime_change_is_detected_near_the_true_boundary(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth), _MULTI_STATE
        )
        assert result.transition_indices.size >= 1
        # the synthetic change is at index 200; smoothing pulls it a little
        for transition in result.transition_indices.tolist():
            assert abs(transition - 200) <= 80, transition

    def test_minimum_relative_duration_drops_short_spans(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth),
            StateDetectionSettings(
                local_time_radius_s=1.0,
                local_depth_radius_mm=6.0,
                derivative_sigma_s=0.4,
                peak_persistence_s=0.8,
                minimum_relative_duration=0.6,
            ),
        )
        assert result.transition_indices.size >= 1
        assert any(not interval.kept for interval in result.intervals)
        assert all(
            interval.state_number is None
            for interval in result.intervals
            if not interval.kept
        )
        # the coverage invariant survives dropped spans
        covered = _covered_indices(result)
        assert sorted(covered + result.transition_indices.tolist()) == list(
            range(result.profile_count)
        )

    def test_single_mode_spans_the_full_recording(self) -> None:
        field, time_s, depth = _two_regime_field(n=300, g=6)
        bundle = _bundle(field, time_s=time_s, gate_depths=depth)
        result = detect_operating_states(
            bundle, StateDetectionSettings(mode=StateDetectionMode.SINGLE)
        )
        assert result.mode is StateDetectionMode.SINGLE
        assert result.transition_indices.size == 0
        assert len(result.intervals) == 1
        interval = result.intervals[0]
        assert (interval.start_index, interval.stop_index_exclusive) == (0, 300)
        assert interval.kept and interval.state_number == 1
        assert interval.relative_duration == 1.0
        assert result.base_threshold is None
        assert result.applied_threshold is None
        assert result.peak_prominence is None
        assert not result.variability.any()
        assert not result.change_signal.any()

    def test_interval_durations_add_one_sample_interval(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth), _MULTI_STATE
        )
        for interval in result.intervals:
            span = interval.end_time_s - interval.start_time_s
            assert interval.duration_s == pytest.approx(span + result.time_step_s)

    def test_detector_thresholds_are_consistent(self) -> None:
        field, time_s, depth = _two_regime_field()
        result = detect_operating_states(
            _bundle(field, time_s=time_s, gate_depths=depth), _MULTI_STATE
        )
        assert result.base_threshold is not None and result.base_threshold > 0.0
        assert result.applied_threshold == pytest.approx(0.5 * result.base_threshold)
        assert result.peak_prominence is not None and result.peak_prominence >= 0.0


# ── real steady velocity fixture ─────────────────────────────────────────


@pytest.fixture(scope="module")
def four_sensor() -> ChannelBundle:
    return select_channel(load(FOUR_SENSOR), ChannelKey(device_channel=6))


class TestRealFixture:
    def test_steady_recording_is_a_single_retained_state(self, four_sensor) -> None:
        result = detect_operating_states(four_sensor)
        assert result.profile_count == 400
        assert result.gate_count == 55
        assert result.transition_indices.size == 0
        assert len(result.intervals) == 1
        interval = result.intervals[0]
        assert (interval.start_index, interval.stop_index_exclusive) == (0, 400)
        assert interval.kept and interval.state_number == 1
        assert interval.relative_duration == 1.0

    def test_single_mode_matches_the_auto_degenerate_result(self, four_sensor) -> None:
        auto = detect_operating_states(four_sensor)
        single = detect_operating_states(
            four_sensor, StateDetectionSettings(mode=StateDetectionMode.SINGLE)
        )
        assert [
            (i.start_index, i.stop_index_exclusive, i.kept) for i in auto.intervals
        ] == [(i.start_index, i.stop_index_exclusive, i.kept) for i in single.intervals]

    def test_detection_is_deterministic(self, four_sensor) -> None:
        first = detect_operating_states(four_sensor)
        second = detect_operating_states(four_sensor)
        assert np.array_equal(first.variability, second.variability)
        assert np.array_equal(first.change_signal, second.change_signal)
        assert np.array_equal(first.transition_indices, second.transition_indices)

    def test_traces_are_owned_and_read_only(self, four_sensor) -> None:
        result = detect_operating_states(four_sensor)
        for array in (result.variability, result.change_signal):
            assert array.flags["OWNDATA"] is True
            assert array.flags["C_CONTIGUOUS"] is True
            assert array.flags["WRITEABLE"] is False
            assert not np.shares_memory(array, four_sensor.artifact.data.values)
        with pytest.raises(ValueError):
            result.variability[...] = 0.0

    def test_source_artifact_and_graph_are_unchanged(self, four_sensor) -> None:
        before_values = four_sensor.artifact.data.values.copy()
        before_quality = four_sensor.artifact.data.support.quality.copy()
        before_graph = four_sensor.graph
        before_id = four_sensor.artifact.artifact_id
        detect_operating_states(four_sensor)
        assert np.array_equal(
            four_sensor.artifact.data.values, before_values, equal_nan=True
        )
        assert np.array_equal(four_sensor.artifact.data.support.quality, before_quality)
        assert four_sensor.graph is before_graph
        assert four_sensor.graph.operations == ()
        assert four_sensor.artifact.artifact_id == before_id


# ── OPTIONAL archived-baseline comparison ────────────────────────────────
#
# Enabled only when UDV_ANALYSIS_ARCHIVE points at the private retirement pack
# (``1efe97d/``). Nothing in the committed suite embeds that absolute path.
# The archived auto cases ran the detector on the TV-filtered field (all 55
# gates valid, TV on), so the replayed input is the archived
# ``filtered_velocity_mm_s``; the archived single cases bypassed the detector.

_ARCHIVE = os.environ.get("UDV_ANALYSIS_ARCHIVE")
_CAPTURE = (
    Path(_ARCHIVE) / "baseline" / "capture"
    if _ARCHIVE
    else Path("<UDV_ANALYSIS_ARCHIVE-unset>")
)

requires_archive = pytest.mark.skipif(
    not _CAPTURE.is_dir(),
    reason="UDV_ANALYSIS_ARCHIVE is unset (archived baseline unavailable)",
)

_AUTO_CASES = ["200RPM-ch6-auto-calc", "200RPM_v2-ch6-auto-calc"]
_SINGLE_CASES = [
    "200RPM-ch6-single-calc",
    "200RPM-ch6-single-file",
    "200RPM_v2-ch6-single-calc",
]


def _archived(case: str) -> tuple[dict, dict]:
    capture = np.load(_CAPTURE / f"{case}.npz", allow_pickle=False)
    meta = json.loads((_CAPTURE / f"{case}.json").read_text())
    return {name: capture[name] for name in capture.files}, meta


def _archived_settings(meta: dict) -> StateDetectionSettings:
    raw = meta["config_exact"]["state_detection"]
    return StateDetectionSettings(
        mode=StateDetectionMode(raw["mode"]),
        local_time_radius_s=raw["local_time_radius_seconds"],
        local_depth_radius_mm=raw["local_depth_radius_mm"],
        derivative_sigma_s=raw["derivative_sigma_seconds"],
        peak_persistence_s=raw["peak_persistence_seconds"],
        threshold_factor=raw["threshold_factor"],
        peak_prominence_std_factor=raw["peak_prominence_std_factor"],
        minimum_relative_duration=raw["minimum_relative_duration"],
        threshold_histogram_bins=raw["threshold_histogram_bins"],
    )


def _archived_bundle(arrays: dict, column: str) -> ChannelBundle:
    return _bundle(
        arrays[column],
        time_s=arrays["time_s"],
        gate_depths=arrays["depth_mm_selected"],
    )


@requires_archive
class TestArchivedBaseline:
    @pytest.mark.parametrize("case", _AUTO_CASES)
    def test_auto_baseline_reproduces_exactly(self, case: str) -> None:
        arrays, meta = _archived(case)
        settings = _archived_settings(meta)
        result = detect_operating_states(
            _archived_bundle(arrays, "filtered_velocity_mm_s"), settings
        )
        expected = meta["state_detection"]
        assert np.array_equal(result.variability, arrays["variability_trace"])
        assert np.array_equal(result.change_signal, arrays["state_change_signal"])
        assert np.array_equal(result.transition_indices, arrays["transition_indices"])
        assert result.base_threshold == pytest.approx(expected["base_threshold"])
        assert result.applied_threshold == pytest.approx(expected["applied_threshold"])
        assert result.peak_prominence == pytest.approx(
            expected["applied_smoothed_peak_prominence"]
        )
        archived_intervals = meta["intervals"]
        assert len(result.intervals) == len(archived_intervals)
        for interval, reference in zip(
            result.intervals, archived_intervals, strict=True
        ):
            assert interval.start_index == reference["start_index"]
            assert interval.stop_index_exclusive == reference["stop_index_exclusive"]
            assert interval.profile_count == reference["profile_count"]
            assert interval.kept is reference["kept"]
            assert interval.state_number == reference["state_number"]
            assert interval.relative_duration == pytest.approx(
                reference["relative_duration"]
            )

    @pytest.mark.parametrize("case", _SINGLE_CASES)
    def test_single_baseline_spans_the_recording(self, case: str) -> None:
        arrays, meta = _archived(case)
        assert meta["state_detection"]["mode"] == "single"
        result = detect_operating_states(
            _archived_bundle(arrays, "velocity_mm_s"),
            StateDetectionSettings(mode=StateDetectionMode.SINGLE),
        )
        reference = meta["intervals"]
        assert len(result.intervals) == len(reference) == 1
        assert result.intervals[0].start_index == reference[0]["start_index"] == 0
        assert (
            result.intervals[0].stop_index_exclusive
            == reference[0]["stop_index_exclusive"]
            == result.profile_count
        )

    @pytest.mark.parametrize("case", _AUTO_CASES)
    def test_committed_fixture_matches_the_archived_payload(self, case: str) -> None:
        """The receiver's decoded channel is byte-identical to the archive."""
        arrays, meta = _archived(case)
        stem = Path(meta["source_file"]).name
        path = REPO / "data" / "4-sensor-velocity" / stem
        if not path.exists():
            pytest.skip(f"committed fixture {stem} is absent")
        channel = int(meta["measurement"]["selected_channel"])
        bundle = select_channel(load(path), ChannelKey(device_channel=channel))
        assert np.array_equal(bundle.artifact.data.time_s, arrays["time_s"])
        assert np.array_equal(
            bundle.artifact.data.gate_depths_mm, arrays["depth_mm_selected"]
        )
        assert np.array_equal(bundle.artifact.data.values, arrays["velocity_mm_s"])
