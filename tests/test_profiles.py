"""Typed terminal robust velocity profiles (absorption plan §4, D1/D2/D5).

Coverage:

- ``RobustProfileSettings`` / ``TvL1Settings`` defaults (the archived baseline
  values), all parameter validators, and the settings the source had that are
  deliberately **not** absorbed (``max_workers``, ``reuse_saved_results``, an
  ``opencv`` backend, an ``enabled`` flag);
- the intentional strengthening: the TV stability rule is enforced at settings
  construction instead of mid-solve;
- ``RobustVelocityProfiles`` invariants: the artifact-id and descriptor ties,
  the ``1..N`` retained-state numbering, the ``(S, G)`` shapes, the per-gate
  status semantics and the NaN/count contract, plus the decision locks (no
  envelope arrays, no diagnostics dict);
- the producer input contract (bundle *and* detection of the same artifact,
  axial velocity only, fully valid support, at least one retained state) and
  the untouched source artifact/graph;
- the private 2-D TV-L1 kernel (constant-field exactness, determinism,
  non-finite and rank refusal) and the D1 privacy locks: no public
  ``FilterSpec`` branch, not exported, no OpenCV;
- synthetic behaviour: outlier rejection, the inclusive envelope, the
  constant-gate bypass, the disabled envelope, the sparse and empty envelope
  paths, the LP-failure-is-an-error path, the basis guard, and multi-state
  selection (kept spans only);
- the committed steady velocity fixture (``data/4-sensor-velocity/200RPM.BDD``
  channel 6);
- an OPTIONAL exact archived-baseline replay for **all five** retirement cases,
  enabled by the ``UDV_ANALYSIS_ARCHIVE`` environment variable pointing at the
  private retirement pack (``1efe97d/``).

Honest limitations (archive ``limitations_probe`` / B3):

- the archive contains **no real multi-state velocity fixture** — every
  committed velocity recording is a steady 200 RPM run with one state — so
  multi-state row selection is exercised on synthetic regimes only;
- the ``empty_envelope`` producer path is reached only by a deliberately sharp
  quantile band on a seeded random walk (the archived baseline never produced
  one), so it is covered by that construction; the *semantics* of an empty gate
  are additionally pinned by the result-model invariant tests;
- the dense ``sparse_quantile_envelope`` status requires
  ``fail_on_sparse_envelope=False``, which the archived cases do not use.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import get_args

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.sparse import csc_matrix

import udv_echo_process
from udv_echo_process import analysis, process
from udv_echo_process.analysis import _tv_l1, profiles
from udv_echo_process.analysis.profiles import (
    RobustProfileEnvelopeError,
    RobustProfileInputError,
    RobustProfileSolverError,
    _quantile_envelope_controls,
    _summarize_gate,
    extract_robust_profiles,
)
from udv_echo_process.analysis.states import detect_operating_states
from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    OperatingStateDetection,
    OperatingStateInterval,
    QualityFlag,
    RobustGateStatus,
    RobustProfileSettings,
    SignalDescriptor,
    SignalQuantity,
    StateDetectionMode,
    StateDetectionSettings,
    TvL1Settings,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.models.profiles import RobustVelocityProfiles
from udv_echo_process.process.specs import FilterSpec
from udv_echo_process.provenance import ChannelBundle, select_channel, source_bundle

REPO = Path(__file__).resolve().parents[1]
FOUR_SENSOR = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_OTHER_ASSET_ID = "sha256:" + "2" * 64
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_SINGLE = StateDetectionSettings(mode=StateDetectionMode.SINGLE)


# ── builders ─────────────────────────────────────────────────────────────


def _bundle(
    field: object,
    *,
    time_s: object = None,
    gate_depths: object = None,
    channel: int = 6,
    descriptor: SignalDescriptor = _VELOCITY,
    asset_id: str = _ASSET_ID,
    data: object = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` for one velocity payload."""
    if data is None:
        arr = np.asarray(field, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr[:, None]
        rows, gates = arr.shape
        if time_s is None:
            time_s = np.arange(rows, dtype=np.float64) * 0.1
        if gate_depths is None:
            gate_depths = np.linspace(10.0, 50.0, gates)
        data = observed_signal(time_s, gate_depths, arr)
    ref = AcquisitionRef(
        recording_id=recording_id_for(asset_id),
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    return source_bundle(source_artifact(ref, descriptor, ChannelConfig(), data))


def _detect(
    field: object,
    *,
    settings: StateDetectionSettings = _SINGLE,
    **over: object,
) -> tuple[ChannelBundle, OperatingStateDetection]:
    """Build a bundle and its own detection (the supported input pair)."""
    bundle = _bundle(field, **over)
    return bundle, detect_operating_states(bundle, settings)


def _total_variation(array: np.ndarray) -> float:
    """Isotropic (axis-summed) total variation of a 2-D field."""
    return float(
        np.sum(np.abs(np.diff(array, axis=0))) + np.sum(np.abs(np.diff(array, axis=1)))
    )


def _status_cells(result: RobustVelocityProfiles) -> list[str]:
    return [status.value for row in result.gate_status for status in row]


def _handmade_detection(
    bundle: ChannelBundle,
    *,
    profile_count: int | None = None,
    gate_count: int | None = None,
    descriptor: SignalDescriptor | None = None,
) -> OperatingStateDetection:
    """Hand-build a valid SINGLE-mode detection over ``bundle``'s geometry.

    ``detect_operating_states`` refuses an invalid ``SampleSupport`` cell and an
    echo descriptor before any profile work, so the profile producer's *own*
    model-level contract is probed with a directly constructed detection —
    which is a public, hand-buildable Pydantic model (as in ``test_states.py``).
    """
    rows, gates = bundle.artifact.data.values.shape
    total = rows if profile_count is None else profile_count
    interval = OperatingStateInterval(
        interval_number=1,
        state_number=1,
        kept=True,
        start_index=0,
        stop_index_exclusive=total,
        profile_count=total,
        relative_duration=1.0,
        start_time_s=0.0,
        end_time_s=0.1 * (total - 1),
        duration_s=0.1 * total,
    )
    return OperatingStateDetection(
        mode=StateDetectionMode.SINGLE,
        settings=_SINGLE,
        artifact_id=bundle.artifact.artifact_id,
        descriptor=bundle.artifact.descriptor if descriptor is None else descriptor,
        profile_count=total,
        gate_count=gates if gate_count is None else gate_count,
        time_step_s=0.1,
        gate_spacing_mm=1.0,
        transition_indices=np.empty(0, dtype=np.int64),
        intervals=(interval,),
        variability=np.zeros(total, dtype=np.float64),
        change_signal=np.zeros(total, dtype=np.float64),
        base_threshold=None,
        applied_threshold=None,
        peak_prominence=None,
    )


def _result(**over: object) -> RobustVelocityProfiles:
    """A hand-built (1 state x 2 gate) valid result for invariant tests."""
    base: dict[str, object] = {
        "settings": RobustProfileSettings(),
        "artifact_id": _ASSET_ID,
        "detection_artifact_id": _ASSET_ID,
        "descriptor": _VELOCITY,
        "gate_count": 2,
        "state_numbers": (1,),
        "median_velocity_mm_s": np.array([[10.0, 20.0]]),
        "median_absolute_deviation_mm_s": np.array([[1.0, 2.0]]),
        "retained_sample_count": np.array([[90, 80]], dtype=np.int64),
        "input_sample_count": np.array([100], dtype=np.int64),
        "gate_status": (
            (RobustGateStatus.QUANTILE_ENVELOPE, RobustGateStatus.QUANTILE_ENVELOPE),
        ),
    }
    base.update(over)
    return RobustVelocityProfiles(**base)  # type: ignore[arg-type]


_TWO_REGIME_DETECTION = StateDetectionSettings(
    local_time_radius_s=1.0,
    local_depth_radius_mm=6.0,
    derivative_sigma_s=0.4,
    peak_persistence_s=0.8,
    threshold_factor=0.5,
    peak_prominence_std_factor=0.2,
    minimum_relative_duration=0.01,
    threshold_histogram_bins=256,
)


def _two_regime_field(
    n: int = 400, g: int = 8
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A synthetic low-texture -> high-texture regime change near index n/2."""
    time_s = np.arange(n, dtype=np.float64) * 0.1
    depth = np.linspace(10.0, 50.0, g)
    phase = np.arange(n, dtype=np.float64)[:, None]
    field = np.zeros((n, g), dtype=np.float64)
    half = n // 2
    field[:half] = 0.1 * np.sin(phase[:half] / 5.0)
    field[half:] = 6.0 * np.sin(phase[half:] / 3.0) * np.linspace(1.0, 2.0, g)
    return field, time_s, depth


# ── TvL1Settings ─────────────────────────────────────────────────────────


class TestTvL1Settings:
    def test_defaults_are_the_archived_baseline_defaults(self) -> None:
        settings = TvL1Settings()
        assert settings.regularization == 0.5
        assert settings.max_iterations == 30
        assert settings.tolerance == 0.0
        assert settings.primal_step == 0.35
        assert settings.dual_step == 0.35

    def test_defaults_satisfy_the_stability_rule(self) -> None:
        settings = TvL1Settings()
        assert settings.primal_step * settings.dual_step * 8 < 1

    def test_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            TvL1Settings().regularization = 1.0  # type: ignore[misc]

    @pytest.mark.parametrize(
        "field", ["enabled", "method", "opencv_lambda", "max_workers"]
    )
    def test_unabsorbed_fields_are_forbidden(self, field) -> None:
        with pytest.raises(ValidationError):
            TvL1Settings(**{field: 1.0})  # type: ignore[arg-type]

    @pytest.mark.parametrize("field", ["regularization", "primal_step", "dual_step"])
    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_positive_fields(self, field, bad) -> None:
        with pytest.raises(ValidationError):
            TvL1Settings(**{field: bad})  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf")])
    def test_tolerance_must_be_non_negative(self, bad) -> None:
        with pytest.raises(ValidationError):
            TvL1Settings(tolerance=bad)

    @pytest.mark.parametrize("bad", [0, -3])
    def test_max_iterations_must_be_at_least_one(self, bad) -> None:
        with pytest.raises(ValidationError):
            TvL1Settings(max_iterations=bad)

    @pytest.mark.parametrize(
        ("primal", "dual"), [(0.35, 0.36), (0.5, 0.25), (1.0, 1.0)]
    )
    def test_unstable_step_pair_is_refused_at_construction(self, primal, dual) -> None:
        """Intentional strengthening: the source raised mid-solve."""
        with pytest.raises(ValidationError) as excinfo:
            TvL1Settings(primal_step=primal, dual_step=dual)
        assert "primal_step * dual_step * 8" in str(excinfo.value)

    def test_settings_round_trip_through_json(self) -> None:
        settings = TvL1Settings(regularization=0.25, max_iterations=5)
        again = TvL1Settings.model_validate_json(settings.model_dump_json())
        assert again == settings


# ── RobustProfileSettings ────────────────────────────────────────────────


class TestSettings:
    def test_defaults_are_the_archived_baseline_defaults(self) -> None:
        settings = RobustProfileSettings()
        assert settings.apply_tv_filter is True
        assert settings.tv_l1 == TvL1Settings()
        assert settings.use_quantile_envelope is True
        assert settings.lower_quantile == 0.05
        assert settings.upper_quantile == 0.95
        assert settings.knot_size_factor == 0.05
        assert settings.spline_order == 3
        assert settings.lp_methods == ("highs", "highs-ipm")
        assert settings.envelope_control_values == 500
        assert settings.envelope_tv_weight == 1.0
        assert settings.minimum_retained_fraction == 0.50
        assert settings.fail_on_sparse_envelope is True

    def test_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings().minimum_retained_fraction = 0.0  # type: ignore[misc]

    @pytest.mark.parametrize(
        "field", ["enabled", "max_workers", "reuse_saved_results", "method"]
    )
    def test_unabsorbed_fields_are_forbidden(self, field) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(**{field: 1})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "over",
        [
            {"lower_quantile": 0.5, "upper_quantile": 0.5},
            {"lower_quantile": 0.9, "upper_quantile": 0.1},
            {"lower_quantile": -0.1},
            {"upper_quantile": 1.1},
            {"lower_quantile": float("nan")},
        ],
    )
    def test_quantiles_must_be_ordered_and_bounded(self, over) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(**over)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [0.0, -0.5, float("nan"), float("inf")])
    def test_knot_size_factor_must_be_positive(self, bad) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(knot_size_factor=bad)

    @pytest.mark.parametrize("bad", [-1.0, -0.5, float("nan"), float("inf")])
    def test_envelope_tv_weight_must_be_non_negative(self, bad) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(envelope_tv_weight=bad)

    def test_zero_envelope_tv_weight_is_allowed(self) -> None:
        assert RobustProfileSettings(envelope_tv_weight=0.0).envelope_tv_weight == 0.0

    @pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
    def test_minimum_retained_fraction_must_lie_in_unit_interval(self, bad) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(minimum_retained_fraction=bad)

    @pytest.mark.parametrize(
        ("over", "bad"),
        [
            ({"spline_order": -1}, -1),
            ({"envelope_control_values": 1}, 1),
            ({"envelope_control_values": 0}, 0),
        ],
    )
    def test_structural_settings(self, over, bad) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(**over)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "methods", [(), ("highs", "highs"), ("",), ("highs", "  ")]
    )
    def test_lp_methods_must_be_unique_and_non_empty(self, methods) -> None:
        with pytest.raises(ValidationError):
            RobustProfileSettings(lp_methods=methods)

    def test_settings_round_trip_through_json(self) -> None:
        settings = RobustProfileSettings(
            use_quantile_envelope=False,
            minimum_retained_fraction=0.25,
            tv_l1=TvL1Settings(max_iterations=4),
        )
        again = RobustProfileSettings.model_validate_json(settings.model_dump_json())
        assert again == settings


# ── RobustVelocityProfiles invariants ────────────────────────────────────


class TestResultModel:
    def test_valid_result_constructs_and_round_trips_arrays(self) -> None:
        result = _result()
        assert result.state_numbers == (1,)
        assert result.gate_count == 2
        assert result.deviation_definition == "unscaled_median_absolute_deviation"

    def test_carries_no_envelope_arrays_or_diagnostics_dict(self) -> None:
        """Decision lock: the archive stores neither, so the model must not."""
        fields = set(RobustVelocityProfiles.model_fields)
        assert not any("envelope" in name for name in fields)
        assert "diagnostics" not in fields

    def test_artifact_id_must_be_opaque_sha256(self) -> None:
        with pytest.raises(ValidationError):
            _result(artifact_id="not-an-id")

    def test_both_artifact_ids_must_agree(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(detection_artifact_id=_OTHER_ASSET_ID)
        assert "must name the same source artifact" in str(excinfo.value)

    def test_descriptor_must_be_axial_velocity(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(descriptor=_ECHO)
        assert "axial-velocity" in str(excinfo.value)

    @pytest.mark.parametrize("numbers", [(), (2,), (1, 3)])
    def test_state_numbers_must_run_one_to_n(self, numbers) -> None:
        with pytest.raises(ValidationError):
            _result(state_numbers=numbers)

    def test_two_states_number_one_and_two(self) -> None:
        result = _result(
            state_numbers=(1, 2),
            median_velocity_mm_s=np.array([[10.0, 20.0], [30.0, 40.0]]),
            median_absolute_deviation_mm_s=np.zeros((2, 2)),
            retained_sample_count=np.array([[90, 80], [100, 100]], dtype=np.int64),
            input_sample_count=np.array([100, 100], dtype=np.int64),
            gate_status=(
                (
                    RobustGateStatus.QUANTILE_ENVELOPE,
                    RobustGateStatus.QUANTILE_ENVELOPE,
                ),
                (
                    RobustGateStatus.CONSTANT_OR_UNFILTERED,
                    RobustGateStatus.CONSTANT_OR_UNFILTERED,
                ),
            ),
        )
        assert result.gate_count == 2
        assert result.input_sample_count.tolist() == [100, 100]

    @pytest.mark.parametrize(
        "over",
        [
            {"median_velocity_mm_s": np.zeros((1, 3))},
            {"median_velocity_mm_s": np.zeros((2, 2))},
            {"median_absolute_deviation_mm_s": np.zeros((1, 3))},
            {"retained_sample_count": np.zeros((1, 3), dtype=np.int64)},
            {"input_sample_count": np.array([100, 100], dtype=np.int64)},
            {"gate_status": ()},
            {"gate_status": ((RobustGateStatus.QUANTILE_ENVELOPE,),)},
            {
                "gate_status": (
                    (
                        RobustGateStatus.QUANTILE_ENVELOPE,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                    ),
                )
            },
        ],
    )
    def test_shapes_must_match_the_state_and_gate_axes(self, over) -> None:
        with pytest.raises(ValidationError):
            _result(**over)

    def test_retained_must_not_exceed_input(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(retained_sample_count=np.array([[101, 80]], dtype=np.int64))
        assert "must not exceed input_sample_count" in str(excinfo.value)

    def test_empty_gate_requires_nan_medians_and_zero_count(self) -> None:
        cell = (
            np.array([[np.nan, np.nan]]),
            np.array([[np.nan, np.nan]]),
            np.array([[0, 0]], dtype=np.int64),
            (
                (
                    RobustGateStatus.EMPTY_ENVELOPE,
                    RobustGateStatus.EMPTY_ENVELOPE,
                ),
            ),
        )
        result = _result(
            median_velocity_mm_s=cell[0],
            median_absolute_deviation_mm_s=cell[1],
            retained_sample_count=cell[2],
            gate_status=cell[3],
            input_sample_count=np.array([100], dtype=np.int64),
        )
        assert np.isnan(result.median_velocity_mm_s).all()
        assert result.retained_sample_count.sum() == 0

    @pytest.mark.parametrize(
        "over",
        [
            {"retained_sample_count": np.array([[0, 80]], dtype=np.int64)},
            {"median_velocity_mm_s": np.array([[np.nan, 20.0]])},
            {"median_absolute_deviation_mm_s": np.array([[np.nan, 2.0]])},
            {
                "gate_status": (
                    (
                        RobustGateStatus.EMPTY_ENVELOPE,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                    ),
                )
            },
        ],
    )
    def test_empty_status_and_nan_contract_is_symmetric(self, over) -> None:
        with pytest.raises(ValidationError):
            _result(**over)

    def test_deviation_must_be_non_negative_and_finite(self) -> None:
        with pytest.raises(ValidationError):
            _result(median_absolute_deviation_mm_s=np.array([[-1.0, 2.0]]))
        with pytest.raises(ValidationError):
            _result(median_absolute_deviation_mm_s=np.array([[np.inf, 2.0]]))

    def test_constant_gate_must_retain_every_sample(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(
                retained_sample_count=np.array([[90, 80]], dtype=np.int64),
                gate_status=(
                    (
                        RobustGateStatus.CONSTANT_OR_UNFILTERED,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                    ),
                ),
            )
        assert "must retain every input sample" in str(excinfo.value)

    def test_disabled_envelope_requires_every_gate_to_bypass(self) -> None:
        settings = RobustProfileSettings(use_quantile_envelope=False)
        with pytest.raises(ValidationError) as excinfo:
            _result(settings=settings)
        assert "must report constant_or_unfiltered" in str(excinfo.value)
        allowed = _result(
            settings=settings,
            median_velocity_mm_s=np.array([[10.0, 20.0]]),
            median_absolute_deviation_mm_s=np.array([[1.0, 2.0]]),
            retained_sample_count=np.array([[100, 100]], dtype=np.int64),
            input_sample_count=np.array([100], dtype=np.int64),
            gate_status=(
                (
                    RobustGateStatus.CONSTANT_OR_UNFILTERED,
                    RobustGateStatus.CONSTANT_OR_UNFILTERED,
                ),
            ),
        )
        assert _status_cells(allowed) == ["unfiltered_or_constant"] * 2

    def test_sparse_status_is_forbidden_while_failing_on_sparse(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(
                retained_sample_count=np.array([[10, 80]], dtype=np.int64),
                gate_status=(
                    (
                        RobustGateStatus.SPARSE_QUANTILE_ENVELOPE,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                    ),
                ),
            )
        assert "fail_on_sparse_envelope" in str(excinfo.value)

    def test_sparse_status_requires_a_fraction_below_the_minimum(self) -> None:
        settings = RobustProfileSettings(fail_on_sparse_envelope=False)
        with pytest.raises(ValidationError) as excinfo:
            _result(
                settings=settings,
                retained_sample_count=np.array([[90, 80]], dtype=np.int64),
                gate_status=(
                    (
                        RobustGateStatus.SPARSE_QUANTILE_ENVELOPE,
                        RobustGateStatus.QUANTILE_ENVELOPE,
                    ),
                ),
            )
        assert "fewer than" in str(excinfo.value)
        allowed = _result(
            settings=settings,
            retained_sample_count=np.array([[10, 80]], dtype=np.int64),
            gate_status=(
                (
                    RobustGateStatus.SPARSE_QUANTILE_ENVELOPE,
                    RobustGateStatus.QUANTILE_ENVELOPE,
                ),
            ),
        )
        assert _status_cells(allowed)[0] == "sparse_quantile_envelope"

    def test_envelope_status_requires_the_minimum_fraction(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            _result(retained_sample_count=np.array([[10, 80]], dtype=np.int64))
        assert "must retain at least" in str(excinfo.value)

    def test_arrays_are_owned_read_only_and_do_not_alias_the_inputs(self) -> None:
        median = np.array([[10.0, 20.0]])
        result = _result(median_velocity_mm_s=median)
        median[0, 0] = 999.0
        assert result.median_velocity_mm_s[0, 0] == 10.0
        for name in (
            "median_velocity_mm_s",
            "median_absolute_deviation_mm_s",
            "retained_sample_count",
            "input_sample_count",
        ):
            array = getattr(result, name)
            assert array.flags["OWNDATA"] is True
            assert array.flags["C_CONTIGUOUS"] is True
            assert array.flags["WRITEABLE"] is False


# ── the private 2-D TV-L1 kernel (plan D1) ──────────────────────────────


class TestPrivateTvL1:
    def test_constant_field_is_returned_exactly(self) -> None:
        field = np.full((20, 5), 17.5)
        filtered = _tv_l1.tv_l1_primal_dual(field, TvL1Settings())
        np.testing.assert_array_equal(filtered, field)
        assert filtered.dtype == np.float64
        assert filtered.flags["OWNDATA"] is True

    def test_is_deterministic_and_finite(self) -> None:
        rng = np.random.default_rng(42)
        field = rng.normal(size=(30, 8))
        first = _tv_l1.tv_l1_primal_dual(field, TvL1Settings(max_iterations=4))
        second = _tv_l1.tv_l1_primal_dual(field, TvL1Settings(max_iterations=4))
        np.testing.assert_array_equal(first, second)
        assert np.all(np.isfinite(first))

    def test_smooths_without_touching_the_input(self) -> None:
        rng = np.random.default_rng(11)
        field = 20.0 + rng.normal(size=(40, 6))
        before = field.copy()
        filtered = _tv_l1.tv_l1_primal_dual(field, TvL1Settings())
        np.testing.assert_array_equal(field, before)
        assert not np.array_equal(filtered, field)
        assert filtered.shape == field.shape
        # TV is a total-variation penalty: it never increases the TV of the field
        assert _total_variation(filtered) <= _total_variation(field)

    def test_the_tolerance_stops_the_iteration_early(self) -> None:
        rng = np.random.default_rng(31)
        field = rng.normal(size=(30, 6)) * 5 + 20
        one_step = _tv_l1.tv_l1_primal_dual(field, TvL1Settings(max_iterations=1))
        converged = _tv_l1.tv_l1_primal_dual(
            field, TvL1Settings(tolerance=1.0, max_iterations=30)
        )
        np.testing.assert_array_equal(converged, one_step)
        assert not np.array_equal(
            converged, _tv_l1.tv_l1_primal_dual(field, TvL1Settings())
        )

    def test_single_profile_or_single_gate_field_does_not_crash(self) -> None:
        """A length-one axis carries no gradients; the source raised there."""
        for field in (
            np.arange(6, dtype=np.float64).reshape(6, 1),
            np.arange(6, dtype=np.float64).reshape(1, 6),
        ):
            filtered = _tv_l1.tv_l1_primal_dual(field, TvL1Settings())
            assert filtered.shape == field.shape
            assert np.all(np.isfinite(filtered))
            # the source clips the estimate into [0, 1] before rescaling
            assert filtered.min() >= field.min() - 1e-6
            assert filtered.max() <= field.max() + 1e-6

    @pytest.mark.parametrize(
        "field",
        [np.array([1.0, 2.0, 3.0]), np.full((4, 4), np.nan), np.full((4, 4), np.inf)],
    )
    def test_non_finite_or_non_2d_field_is_refused(self, field) -> None:
        with pytest.raises(ValueError):
            _tv_l1.tv_l1_primal_dual(field, TvL1Settings())

    def test_the_solver_is_private_to_the_analysis_chain(self) -> None:
        """Plan D1: no public filter branch, no export, no OpenCV."""
        union, _discriminator = get_args(FilterSpec)
        members = [member.__name__ for member in get_args(union)]
        assert members == [
            "MedianFilterSpec",
            "MeanFilterSpec",
            "SavgolFilterSpec",
            "TvFilterSpec",
        ]
        assert "tv_l1_primal_dual" not in analysis.__all__
        assert not hasattr(udv_echo_process, "tv_l1_primal_dual")
        for name in process.__all__ + analysis.__all__ + udv_echo_process.__all__:
            lowered = name.lower()
            assert "primal" not in lowered, name
            assert "denoise" not in lowered, name
            assert "_tv_l1" not in lowered, name
        assert not any(
            "tvl1" in member.__name__.lower() or "tv_l1" in member.__name__.lower()
            for member in get_args(union)
        )
        assert "cv2" not in sys.modules


# ── producer input contract ─────────────────────────────────────────────


class TestInputContract:
    def test_non_bundle_is_a_type_error(self) -> None:
        with pytest.raises(TypeError):
            extract_robust_profiles("not a bundle")  # type: ignore[arg-type]

    def test_non_detection_is_a_type_error(self) -> None:
        bundle = _bundle(np.ones((20, 3)))
        with pytest.raises(TypeError):
            extract_robust_profiles(bundle, "not a detection")  # type: ignore[arg-type]

    def test_wrong_settings_type_is_a_type_error(self) -> None:
        bundle, detection = _detect(np.ones((20, 3)))
        with pytest.raises(TypeError):
            extract_robust_profiles(
                bundle,
                detection,
                "not settings",  # type: ignore[arg-type]
            )

    def test_echo_channel_is_refused(self) -> None:
        bundle = _bundle(np.ones((20, 3)), descriptor=_ECHO)
        detection = _handmade_detection(bundle, descriptor=_VELOCITY)
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        assert "axial-velocity" in str(excinfo.value)

    def test_ties_the_result_to_both_artifact_ids(self) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        result = extract_robust_profiles(bundle, detection)
        assert result.artifact_id == bundle.artifact.artifact_id
        assert result.detection_artifact_id == detection.artifact_id
        assert result.descriptor == bundle.artifact.descriptor

    def test_detection_of_another_artifact_is_refused(self) -> None:
        bundle = _bundle(np.full((30, 4), 7.0))
        other = _bundle(np.full((30, 4), 7.0), channel=7, asset_id=_OTHER_ASSET_ID)
        detection = detect_operating_states(other, _SINGLE)
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        assert "different artifact" in str(excinfo.value)

    def test_descriptor_mismatch_is_refused(self) -> None:
        """A counterfeit descriptor (only constructible past validation)."""
        bundle, detection = _detect(np.full((30, 4), 7.0))
        counterfeit = SignalDescriptor.model_construct(
            quantity=SignalQuantity.AXIAL_VELOCITY, unit="m/s"
        )
        forged = detection.model_copy(update={"descriptor": counterfeit})
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, forged)
        assert "must describe the same channel" in str(excinfo.value)

    def test_gate_axis_mismatch_is_refused(self) -> None:
        bundle = _bundle(np.full((30, 4), 7.0))
        detection = _handmade_detection(bundle, gate_count=5)
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        assert "gate axis" in str(excinfo.value)

    def test_profile_axis_mismatch_is_refused(self) -> None:
        bundle = _bundle(np.full((30, 4), 7.0))
        detection = _handmade_detection(bundle, profile_count=31)
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        assert "profile axis" in str(excinfo.value)

    def test_invalid_support_is_refused_with_location(self) -> None:
        time_s = np.arange(20, dtype=np.float64) * 0.1
        depth = np.linspace(10.0, 50.0, 4)
        values = np.ones((20, 4), dtype=np.float64)
        values[5, 2] = np.nan
        quality = np.zeros((20, 4), dtype=np.uint32)
        quality[5, 2] = int(QualityFlag.OUTLIER)
        data = observed_signal(time_s, depth, values, quality=quality)
        bundle = _bundle(None, data=data)
        detection = _handmade_detection(bundle)
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        message = str(excinfo.value)
        assert "invalid cell" in message
        assert "(time=5, gate=2)" in message
        assert np.isnan(bundle.artifact.data.values[5, 2])
        assert not bundle.artifact.data.support.valid[5, 2]

    def test_a_detection_with_no_retained_state_is_refused(self) -> None:
        field, time_s, depth = _two_regime_field()
        bundle = _bundle(field, time_s=time_s, gate_depths=depth)
        detection = detect_operating_states(
            bundle,
            _TWO_REGIME_DETECTION.model_copy(
                update={"minimum_relative_duration": 0.99}
            ),
        )
        assert detection.intervals and not any(
            interval.kept for interval in detection.intervals
        )
        with pytest.raises(RobustProfileInputError) as excinfo:
            extract_robust_profiles(bundle, detection)
        assert "retained no state" in str(excinfo.value)

    def test_gate_summarizer_refuses_a_non_finite_vector(self) -> None:
        settings = RobustProfileSettings()
        for bad in (np.array([]), np.array([1.0, np.nan]), np.array([np.inf])):
            with pytest.raises(RobustProfileInputError):
                _summarize_gate(bad, settings)

    def test_basis_guard_refuses_a_non_partition_of_unity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _BadBasis:
            @staticmethod
            def design_matrix(index, knots, order, extrapolate=False):
                return csc_matrix(np.full((np.asarray(index).size, 4), 0.5))

        monkeypatch.setattr(profiles, "BSpline", _BadBasis)
        with pytest.raises(RobustProfileSolverError) as excinfo:
            _quantile_envelope_controls(
                np.arange(1, 5, dtype=np.float64),
                np.linspace(0.0, 1.0, 4),
                np.linspace(1.0, 4.0, 3),
                2,
                (0.05, 0.95),
                3,
                ("highs", "highs-ipm"),
            )
        assert "does not sum to one" in str(excinfo.value)

    def test_solver_failure_is_an_error_not_a_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FailedLP:
            success = False
            status = 4
            message = "synthetic infeasibility"
            x = None

        monkeypatch.setattr(profiles, "linprog", lambda *a, **k: _FailedLP())
        rng = np.random.default_rng(2)
        bundle, detection = _detect(rng.normal(size=(50, 3)) * 5 + 20)
        with pytest.raises(RobustProfileSolverError) as excinfo:
            extract_robust_profiles(bundle, detection)
        message = str(excinfo.value)
        assert "quantile LP failed" in message
        assert "synthetic infeasibility" in message


# ── synthetic behaviour ─────────────────────────────────────────────────


class TestSyntheticBehaviour:
    def test_outliers_are_rejected_by_the_envelope(self) -> None:
        n = 200
        clean = np.full(n, 10.0)
        contaminated = np.full(n, 10.0)
        contaminated[::50] = 500.0  # 4 outliers
        contaminated[::2] = 500.0  # 100 outliers: the raw median is now 500
        field = np.column_stack([clean, contaminated])
        bundle, detection = _detect(field)
        result = extract_robust_profiles(bundle, detection)
        assert np.median(field[:, 1]) == 255.0  # the contaminated gate's raw median
        assert result.median_velocity_mm_s[0, 1] == pytest.approx(10.0)
        # gate 0 is constant, so it bypasses the fit and retains every sample
        assert result.median_velocity_mm_s[0, 0] == 10.0
        assert result.retained_sample_count[0, 0] == 200
        assert result.retained_sample_count[0, 1] == 132
        assert _status_cells(result) == [
            "unfiltered_or_constant",
            "quantile_envelope",
        ]

    def test_the_envelope_drops_samples_of_a_noisy_gate(self) -> None:
        rng = np.random.default_rng(21)
        field = rng.normal(size=(120, 2)) * 3 + 20
        bundle, detection = _detect(field)
        result = extract_robust_profiles(bundle, detection)
        assert (result.retained_sample_count[0] < 120).all()
        assert _status_cells(result) == ["quantile_envelope"] * 2

    def test_constant_gate_bypasses_the_fit(self) -> None:
        field = np.full((60, 4), 12.5)
        bundle, detection = _detect(field)
        result = extract_robust_profiles(bundle, detection)
        np.testing.assert_array_equal(
            result.median_velocity_mm_s, np.full((1, 4), 12.5)
        )
        np.testing.assert_array_equal(
            result.median_absolute_deviation_mm_s, np.zeros((1, 4))
        )
        np.testing.assert_array_equal(result.retained_sample_count, 60)
        np.testing.assert_array_equal(result.input_sample_count, np.array([60]))
        assert _status_cells(result) == ["unfiltered_or_constant"] * 4

    def test_disabled_envelope_matches_the_raw_medians(self) -> None:
        rng = np.random.default_rng(5)
        field = rng.normal(size=(100, 3)) * 5 + 20
        bundle, detection = _detect(field)
        result = extract_robust_profiles(
            bundle,
            detection,
            RobustProfileSettings(use_quantile_envelope=False, apply_tv_filter=False),
        )
        np.testing.assert_allclose(
            result.median_velocity_mm_s[0], np.median(field, axis=0)
        )
        np.testing.assert_array_equal(result.retained_sample_count, 100)
        assert _status_cells(result) == ["unfiltered_or_constant"] * 3

    def test_sparse_envelope_fails_or_is_reported(self) -> None:
        alternating = np.tile([0.0, 100.0], 100)
        field = np.column_stack([alternating, alternating])
        bundle, detection = _detect(field)
        strict = RobustProfileSettings(
            minimum_retained_fraction=1.0,
            lower_quantile=0.49,
            upper_quantile=0.51,
        )
        with pytest.raises(RobustProfileEnvelopeError) as excinfo:
            extract_robust_profiles(bundle, detection, strict)
        assert "below the configured" in str(excinfo.value)

        lenient = RobustProfileSettings(
            minimum_retained_fraction=1.0,
            lower_quantile=0.49,
            upper_quantile=0.51,
            fail_on_sparse_envelope=False,
        )
        result = extract_robust_profiles(bundle, detection, lenient)
        assert _status_cells(result) == ["sparse_quantile_envelope"] * 2
        assert (result.retained_sample_count[0] > 0).all()
        assert (
            result.retained_sample_count[0] / result.input_sample_count[0] < 1.0
        ).all()

    def test_empty_envelope_reports_nan_statistics(self) -> None:
        rng = np.random.default_rng(7)
        walk = np.column_stack(
            [
                np.cumsum(rng.normal(size=200)) * 10,
                np.cumsum(rng.normal(size=200)) * 10,
            ]
        )
        bundle, detection = _detect(walk)
        result = extract_robust_profiles(
            bundle,
            detection,
            RobustProfileSettings(
                lower_quantile=0.499,
                upper_quantile=0.501,
                fail_on_sparse_envelope=False,
            ),
        )
        assert _status_cells(result) == ["empty_envelope"] * 2
        assert np.isnan(result.median_velocity_mm_s).all()
        assert np.isnan(result.median_absolute_deviation_mm_s).all()
        np.testing.assert_array_equal(result.retained_sample_count, 0)

    def test_the_fit_is_per_gate_not_across_gates(self) -> None:
        """Two gates with the same samples must give the same statistics."""
        rng = np.random.default_rng(13)
        column = rng.normal(size=120) * 3 + 15
        field = np.column_stack([column, column])
        bundle, detection = _detect(field)
        result = extract_robust_profiles(bundle, detection)
        assert result.median_velocity_mm_s[0, 0] == result.median_velocity_mm_s[0, 1]
        assert (
            result.median_absolute_deviation_mm_s[0, 0]
            == result.median_absolute_deviation_mm_s[0, 1]
        )
        assert result.retained_sample_count[0, 0] == result.retained_sample_count[0, 1]

    def test_only_retained_states_become_rows(self) -> None:
        field, time_s, depth = _two_regime_field()
        bundle = _bundle(field, time_s=time_s, gate_depths=depth)
        detection = detect_operating_states(bundle, _TWO_REGIME_DETECTION)
        kept = [interval for interval in detection.intervals if interval.kept]
        assert len(kept) >= 2
        result = extract_robust_profiles(bundle, detection)
        assert result.state_numbers == tuple(range(1, len(kept) + 1))
        assert result.median_velocity_mm_s.shape == (len(kept), 8)
        assert result.input_sample_count.tolist() == [
            interval.profile_count for interval in kept
        ]
        assert sum(result.input_sample_count) < detection.profile_count

    def test_a_one_profile_state_bypasses_the_fit(self) -> None:
        """A degenerate retained state must not break the 2-D preprocessing."""
        field = np.arange(12, dtype=np.float64).reshape(3, 4)
        bundle = _bundle(field)
        detection = OperatingStateDetection(
            mode=StateDetectionMode.AUTO,
            settings=StateDetectionSettings(),
            artifact_id=bundle.artifact.artifact_id,
            descriptor=bundle.artifact.descriptor,
            profile_count=3,
            gate_count=4,
            time_step_s=0.1,
            gate_spacing_mm=1.0,
            transition_indices=np.empty(0, dtype=np.int64),
            intervals=(
                OperatingStateInterval(
                    interval_number=1,
                    state_number=1,
                    kept=True,
                    start_index=0,
                    stop_index_exclusive=1,
                    profile_count=1,
                    relative_duration=1 / 3,
                    start_time_s=0.0,
                    end_time_s=0.0,
                    duration_s=0.1,
                ),
                OperatingStateInterval(
                    interval_number=2,
                    state_number=2,
                    kept=True,
                    start_index=1,
                    stop_index_exclusive=3,
                    profile_count=2,
                    relative_duration=2 / 3,
                    start_time_s=0.1,
                    end_time_s=0.2,
                    duration_s=0.2,
                ),
            ),
            variability=np.zeros(3, dtype=np.float64),
            change_signal=np.zeros(3, dtype=np.float64),
            base_threshold=0.5,
            applied_threshold=0.25,
            peak_prominence=0.0,
        )
        result = extract_robust_profiles(bundle, detection)
        assert result.state_numbers == (1, 2)
        assert result.input_sample_count.tolist() == [1, 2]
        np.testing.assert_array_equal(result.median_velocity_mm_s[0], field[0])
        np.testing.assert_array_equal(
            result.median_absolute_deviation_mm_s[0], np.zeros(4)
        )
        np.testing.assert_array_equal(result.retained_sample_count[0], 1)

    def test_extraction_is_deterministic(self) -> None:
        field, time_s, depth = _two_regime_field(n=200, g=5)
        bundle = _bundle(field, time_s=time_s, gate_depths=depth)
        detection = detect_operating_states(bundle, _SINGLE)
        first = extract_robust_profiles(bundle, detection)
        second = extract_robust_profiles(bundle, detection)
        np.testing.assert_array_equal(
            first.median_velocity_mm_s, second.median_velocity_mm_s
        )
        np.testing.assert_array_equal(
            first.retained_sample_count, second.retained_sample_count
        )
        assert first.gate_status == second.gate_status


# ── real steady velocity fixture ────────────────────────────────────────


@pytest.fixture(scope="module")
def four_sensor() -> ChannelBundle:
    return select_channel(load(FOUR_SENSOR), ChannelKey(device_channel=6))


@pytest.fixture(scope="module")
def fixture_detection(four_sensor: ChannelBundle) -> OperatingStateDetection:
    return detect_operating_states(four_sensor)


@pytest.fixture(scope="module")
def fixture_result(
    four_sensor: ChannelBundle, fixture_detection: OperatingStateDetection
) -> RobustVelocityProfiles:
    return extract_robust_profiles(four_sensor, fixture_detection)


class TestRealFixture:
    def test_shapes_and_retained_counts_match_the_archive(
        self, fixture_result: RobustVelocityProfiles
    ) -> None:
        assert fixture_result.state_numbers == (1,)
        assert fixture_result.gate_count == 55
        assert fixture_result.median_velocity_mm_s.shape == (1, 55)
        assert fixture_result.input_sample_count.tolist() == [400]
        assert fixture_result.retained_sample_count.min() == 352
        assert fixture_result.retained_sample_count.max() == 366
        fraction = (
            fixture_result.retained_sample_count / fixture_result.input_sample_count[0]
        )
        assert fraction.mean() == pytest.approx(0.897, abs=5e-4)
        assert set(_status_cells(fixture_result)) == {"quantile_envelope"}

    def test_every_gate_reports_a_finite_statistic(
        self, fixture_result: RobustVelocityProfiles
    ) -> None:
        assert np.isfinite(fixture_result.median_velocity_mm_s).all()
        assert np.isfinite(fixture_result.median_absolute_deviation_mm_s).all()
        assert (fixture_result.median_absolute_deviation_mm_s >= 0).all()
        assert (fixture_result.retained_sample_count <= 400).all()

    def test_result_arrays_are_owned_and_read_only(
        self, four_sensor: ChannelBundle, fixture_result: RobustVelocityProfiles
    ) -> None:
        for name in (
            "median_velocity_mm_s",
            "median_absolute_deviation_mm_s",
            "retained_sample_count",
            "input_sample_count",
        ):
            array = getattr(fixture_result, name)
            assert array.flags["OWNDATA"] is True
            assert array.flags["C_CONTIGUOUS"] is True
            assert array.flags["WRITEABLE"] is False
            assert not np.shares_memory(array, four_sensor.artifact.data.values)
        with pytest.raises(ValueError):
            fixture_result.median_velocity_mm_s[...] = 0.0

    def test_source_artifact_and_graph_are_unchanged(
        self, four_sensor: ChannelBundle
    ) -> None:
        before_values = four_sensor.artifact.data.values.copy()
        before_quality = four_sensor.artifact.data.support.quality.copy()
        before_graph = four_sensor.graph
        before_id = four_sensor.artifact.artifact_id
        detection = detect_operating_states(four_sensor)
        extract_robust_profiles(four_sensor, detection)
        assert np.array_equal(
            four_sensor.artifact.data.values, before_values, equal_nan=True
        )
        assert np.array_equal(four_sensor.artifact.data.support.quality, before_quality)
        assert four_sensor.graph is before_graph
        assert four_sensor.graph.operations == ()
        assert four_sensor.artifact.artifact_id == before_id

    def test_single_mode_detection_gives_the_same_arrays(
        self, four_sensor: ChannelBundle, fixture_result: RobustVelocityProfiles
    ) -> None:
        single = extract_robust_profiles(
            four_sensor, detect_operating_states(four_sensor, _SINGLE)
        )
        np.testing.assert_array_equal(
            single.median_velocity_mm_s, fixture_result.median_velocity_mm_s
        )
        np.testing.assert_array_equal(
            single.retained_sample_count, fixture_result.retained_sample_count
        )

    def test_the_tv_flag_changes_the_profile_summary(
        self,
        four_sensor: ChannelBundle,
        fixture_detection: OperatingStateDetection,
    ) -> None:
        """The 2-D preprocessing is applied per retained state when enabled."""
        with_tv = extract_robust_profiles(
            four_sensor, fixture_detection, RobustProfileSettings(apply_tv_filter=True)
        )
        without_tv = extract_robust_profiles(
            four_sensor, fixture_detection, RobustProfileSettings(apply_tv_filter=False)
        )
        assert with_tv.settings.apply_tv_filter is True
        assert without_tv.settings.apply_tv_filter is False
        assert not np.array_equal(
            with_tv.median_velocity_mm_s, without_tv.median_velocity_mm_s
        )

    def test_the_envelope_tv_weight_is_honoured(
        self,
        four_sensor: ChannelBundle,
        fixture_detection: OperatingStateDetection,
    ) -> None:
        """``envelope_tv_weight=0`` skips the Chambolle smoothing of the fit."""
        unsmoothed = extract_robust_profiles(
            four_sensor,
            fixture_detection,
            RobustProfileSettings(envelope_tv_weight=0.0),
        )
        smoothed = extract_robust_profiles(
            four_sensor, fixture_detection, RobustProfileSettings()
        )
        assert not np.array_equal(
            smoothed.retained_sample_count, unsmoothed.retained_sample_count
        )
        assert not np.array_equal(
            smoothed.median_velocity_mm_s, unsmoothed.median_velocity_mm_s
        )

    def test_non_default_fit_parameters_reach_the_algorithm(
        self,
        four_sensor: ChannelBundle,
        fixture_detection: OperatingStateDetection,
    ) -> None:
        """Every absorbed knob must change the fit, not be silently ignored."""
        coarse = extract_robust_profiles(
            four_sensor,
            fixture_detection,
            RobustProfileSettings(
                envelope_control_values=8,
                knot_size_factor=0.5,
                spline_order=1,
                lp_methods=("highs-ipm",),
                minimum_retained_fraction=0.0,
            ),
        )
        default = extract_robust_profiles(
            four_sensor, fixture_detection, RobustProfileSettings()
        )
        assert coarse.settings.envelope_control_values == 8
        assert not np.array_equal(
            coarse.median_velocity_mm_s, default.median_velocity_mm_s
        )
        assert set(_status_cells(coarse)) <= {"quantile_envelope"}


# ── OPTIONAL exact archived-baseline replay ─────────────────────────────
#
# Enabled only when UDV_ANALYSIS_ARCHIVE points at the private retirement pack
# (``1efe97d/``). Nothing in the committed suite embeds that absolute path.
# Each case replays the archived channel payload through this pipeline with the
# archived settings and compares every per-gate array, plus the TV field, with
# the archived capture exactly (``np.array_equal``, no tolerance).

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

#: case -> detection mode the archived run used.
_CASES = {
    "200RPM-ch6-single-calc": StateDetectionMode.SINGLE,
    "200RPM-ch6-auto-calc": StateDetectionMode.AUTO,
    "200RPM-ch6-single-file": StateDetectionMode.SINGLE,
    "200RPM_v2-ch6-single-calc": StateDetectionMode.SINGLE,
    "200RPM_v2-ch6-auto-calc": StateDetectionMode.AUTO,
}


def _archived(case: str) -> tuple[dict, dict]:
    capture = np.load(_CAPTURE / f"{case}.npz", allow_pickle=False)
    meta = json.loads((_CAPTURE / f"{case}.json").read_text())
    return {name: capture[name] for name in capture.files}, meta


def _archived_settings(meta: dict) -> RobustProfileSettings:
    """Translate the archived resolved config into this run's settings."""
    raw = meta["config_exact"]["profiles"]
    tv = meta["config_exact"]["tv_filter"]
    assert raw["enabled"] is True
    assert tv["method"] == "custom"
    assert tv["enabled"] is True
    return RobustProfileSettings(
        apply_tv_filter=bool(raw["apply_tv_filter"]),
        tv_l1=TvL1Settings(
            regularization=tv["regularization"],
            max_iterations=tv["max_iterations"],
            tolerance=tv["tolerance"],
            primal_step=tv["primal_step"],
            dual_step=tv["dual_step"],
        ),
        use_quantile_envelope=bool(raw["use_quantile_envelope"]),
        lower_quantile=raw["lower_quantile"],
        upper_quantile=raw["upper_quantile"],
        knot_size_factor=raw["knot_size_factor"],
        spline_order=raw["spline_order"],
        lp_methods=tuple(raw["lp_methods"]),
        envelope_control_values=raw["envelope_control_values"],
        envelope_tv_weight=raw["envelope_tv_weight"],
        minimum_retained_fraction=raw["minimum_retained_fraction"],
        fail_on_sparse_envelope=bool(raw["fail_on_sparse_envelope"]),
    )


@requires_archive
class TestArchivedBaseline:
    @pytest.mark.parametrize("case", sorted(_CASES))
    def test_profiles_reproduce_the_archived_arrays_exactly(self, case: str) -> None:
        arrays, meta = _archived(case)
        mode = _CASES[case]
        bundle = _bundle(
            arrays["velocity_mm_s"],
            time_s=arrays["time_s"],
            gate_depths=arrays["depth_mm_selected"],
        )
        detection = detect_operating_states(bundle, StateDetectionSettings(mode=mode))
        result = extract_robust_profiles(bundle, detection, _archived_settings(meta))
        assert result.state_numbers == (1,)
        np.testing.assert_array_equal(
            result.median_velocity_mm_s, arrays["profile_median_velocity_mm_s"]
        )
        np.testing.assert_array_equal(
            result.median_absolute_deviation_mm_s,
            arrays["profile_mad_velocity_mm_s"],
        )
        np.testing.assert_array_equal(
            result.retained_sample_count, arrays["profile_retained_sample_count"]
        )
        np.testing.assert_array_equal(
            result.input_sample_count, arrays["profile_input_sample_count"]
        )
        assert set(_status_cells(result)) == {"quantile_envelope"}
        reference = meta["profile_states"][0]
        assert (
            int(np.isfinite(result.median_velocity_mm_s).sum())
            == reference["finite_profile_gate_count"]
        )
        assert float(
            np.mean(result.retained_sample_count / result.input_sample_count[:, None])
        ) == pytest.approx(reference["mean_retained_fraction"], abs=5e-4)
        assert (
            int(result.retained_sample_count.min())
            == reference["minimum_retained_count"]
        )
        assert (
            int(result.retained_sample_count.max())
            == reference["maximum_retained_count"]
        )

    @pytest.mark.parametrize("case", sorted(_CASES))
    def test_private_tv_field_matches_the_archived_filtered_field(
        self, case: str
    ) -> None:
        arrays, meta = _archived(case)
        settings = _archived_settings(meta)
        filtered = _tv_l1.tv_l1_primal_dual(arrays["velocity_mm_s"], settings.tv_l1)
        np.testing.assert_array_equal(filtered, arrays["filtered_velocity_mm_s"])

    @pytest.mark.parametrize("case", sorted(_CASES))
    def test_committed_fixture_matches_the_archived_payload(self, case: str) -> None:
        """The receiver's decoded channel is byte-identical to the archive.

        The archived ``-file`` case was decoded with the ``File`` depth source,
        whose rounded gate depths differ from the receiver's ``Calc``
        reconstruction by up to 0.05 mm (plan §2); the payload itself is
        identical in every case.
        """
        arrays, meta = _archived(case)
        stem = Path(meta["source_file"]).name
        path = REPO / "data" / "4-sensor-velocity" / stem
        if not path.exists():
            pytest.skip(f"committed fixture {stem} is absent")
        channel = int(meta["measurement"]["selected_channel"])
        bundle = select_channel(load(path), ChannelKey(device_channel=channel))
        np.testing.assert_array_equal(bundle.artifact.data.time_s, arrays["time_s"])
        np.testing.assert_array_equal(
            bundle.artifact.data.values, arrays["velocity_mm_s"]
        )
        depths = bundle.artifact.data.gate_depths_mm
        if meta["measurement"]["bdd_depth_source"] == "Calc":
            np.testing.assert_array_equal(depths, arrays["depth_mm_selected"])
        else:
            assert np.max(np.abs(depths - arrays["depth_mm_selected"])) <= 0.05
