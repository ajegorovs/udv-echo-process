"""Phase 5 artifact-resample tests: the interpolation union and ``resample``.

Plan §7.1 (common rules), §7.3 (the interpolation specs and their TEN-row
support-propagation table), §7.4 (context), §8.3 (``derive()``), §11 (error
text), §13/§14 and the Phase 5 section. The target-grid rule is ruling D6: a
``dt_s`` grid is exactly uniform (``t0 + arange(n + 1) * dt_s``), so the legacy
shortened final interval is retired.

Coverage:

- spec tests: the union has exactly four branches, every branch declares the
  three shared fields explicitly (plus only its own knobs), irrelevant/legacy
  fields are ``extra="forbid"`` errors and no ``nan_policy``/``InterpParams``
  remains;
- a table-driven pass over every row of the §7.3 propagation table: exact
  observed / interpolated / extrapolated / invalid / missing knots, the
  between-two-valid-knots ancestry matrix, invalid and missing brackets, the
  ``long_gap`` missing-vs-error split, the three extrapolation policies and the
  row-index sentinels;
- segment-aware sampling: no bracket crosses a MISSING/invalid cell or a gap
  over ``max_bracket_span_s``; strict CUBIC/BSPLINE uniformity (all intervals)
  and BSPLINE capacity naming method/required/actual;
- a three-generation test (observed -> interpolation -> re-interpolation)
  proving synthetic support is never laundered into ``OBSERVED`` and the parent
  arrays are unchanged;
- ``dt_s`` target-grid tests from ruling D6, including that the output then
  passes a TV/SAVGOL/CUBIC uniformity check;
- metadata/acquisition preservation, the deterministic operation+artifact ids
  (in-process and across two processes) and memory ownership;
- synthetic signals first, then the real ``.BDD`` fixtures through the same
  test adapter ``tests/test_artifact_filter.py`` uses.

Recorded deviations (owner decisions the plan does not spell out) are marked
inline next to the test that locks them in.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError

from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    QualityFlag,
    SampleSupport,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    SupportKind,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import (
    BsplineInterpSpec,
    CubicInterpSpec,
    InterpSpec,
    LinearInterpSpec,
    MonotoneInterpSpec,
    SavgolFilterSpec,
    TvFilterSpec,
    filter,
    resample,
)
from udv_echo_process.provenance import ChannelBundle, source_bundle

MISSING = int(SupportKind.MISSING)
OBSERVED = int(SupportKind.OBSERVED)
INTERPOLATED = int(SupportKind.INTERPOLATED)
EXTRAPOLATED = int(SupportKind.EXTRAPOLATED)

GAP_TOO_LONG = int(QualityFlag.GAP_TOO_LONG)
OUT_OF_RANGE = int(QualityFlag.OUT_OF_RANGE)
EXTRAPOLATED_FLAG = int(QualityFlag.EXTRAPOLATED)
REINTERPOLATED = int(QualityFlag.REINTERPOLATED)
OUTLIER = int(QualityFlag.OUTLIER)

REPO = Path(__file__).resolve().parents[1]
ECHO_PATH = REPO / "data" / "echo" / "650.BDD"
FOUR_SENSOR_PATH = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")

_ADAPTER = TypeAdapter(InterpSpec)


# ── builders and spec helpers ────────────────────────────────────────────


def lin(
    *,
    extrapolation: str = "error",
    max_bracket_span_s: float = 1.0,
    long_gap: str = "missing",
) -> LinearInterpSpec:
    return LinearInterpSpec(
        extrapolation=extrapolation,
        max_bracket_span_s=max_bracket_span_s,
        long_gap=long_gap,
    )


def mono(
    *,
    extrapolation: str = "error",
    max_bracket_span_s: float = 1.0,
    long_gap: str = "missing",
) -> MonotoneInterpSpec:
    return MonotoneInterpSpec(
        extrapolation=extrapolation,
        max_bracket_span_s=max_bracket_span_s,
        long_gap=long_gap,
    )


def cub(
    *,
    extrapolation: str = "error",
    max_bracket_span_s: float = 1.0,
    long_gap: str = "missing",
    uniform_rtol: float = 0.01,
) -> CubicInterpSpec:
    return CubicInterpSpec(
        extrapolation=extrapolation,
        max_bracket_span_s=max_bracket_span_s,
        long_gap=long_gap,
        uniform_rtol=uniform_rtol,
    )


def bspl(
    *,
    order: int = 3,
    extrapolation: str = "error",
    max_bracket_span_s: float = 1.0,
    long_gap: str = "missing",
    uniform_rtol: float = 0.01,
) -> BsplineInterpSpec:
    return BsplineInterpSpec(
        extrapolation=extrapolation,
        max_bracket_span_s=max_bracket_span_s,
        long_gap=long_gap,
        order=order,
        uniform_rtol=uniform_rtol,
    )


def _col(value: object, shape: tuple[int, int]) -> np.ndarray:
    arr = np.asarray(value)
    if arr.ndim == 1:
        arr = arr[:, None]
    return arr


def make_bundle(
    time_s: object,
    values: object,
    *,
    gate_depths: object = None,
    kind: object = None,
    valid: object = None,
    quality: object = None,
    descriptor: SignalDescriptor = _ECHO,
    channel: int = 4,
    config: ChannelConfig | None = None,
    acquisition: AcquisitionIndex | None = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` from explicit payload arrays.

    ``values`` is coerced to NaN wherever a cell is invalid, so a caller can
    pass a finite placeholder for a MISSING / invalid-OBSERVED cell.
    """
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    shape = arr.shape
    if gate_depths is None:
        gate_depths = np.arange(shape[1], dtype=np.float64)
    if kind is None:
        kind = np.full(shape, OBSERVED, np.uint8)
    else:
        kind = _col(kind, shape).astype(np.uint8)
    if valid is None:
        valid = np.isfinite(arr)
    else:
        valid = _col(valid, shape).astype(bool)
    # MISSING support is always invalid (SampleSupport invariant), and an
    # invalid cell always stores NaN, so a finite placeholder is coerced.
    valid = valid & (kind != MISSING)
    if quality is None:
        quality = np.zeros(shape, np.uint32)
    else:
        quality = _col(quality, shape).astype(np.uint32)
    arr = np.where(valid, arr, np.nan)
    support = SampleSupport(kind=kind, valid=valid, quality=quality)
    data = SignalData(
        time_s=np.asarray(time_s, np.float64),
        gate_depths_mm=np.asarray(gate_depths, np.float64),
        values=arr,
        support=support,
        acquisition=acquisition,
    )
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    cfg = ChannelConfig() if config is None else config
    return source_bundle(source_artifact(ref, descriptor, cfg, data))


def _arrays(data: SignalData) -> list[np.ndarray]:
    arrays = [data.time_s, data.gate_depths_mm, data.values]
    arrays += [data.support.kind, data.support.valid, data.support.quality]
    if data.acquisition is not None:
        for name in (
            "sample_id",
            "acquisition_time_s",
            "round_id",
            "visit_id",
            "profile_in_visit",
        ):
            arr = getattr(data.acquisition, name)
            if arr is not None:
                arrays.append(arr)
    return arrays


T5 = np.array([0.0, 0.1, 0.2, 0.3, 0.4])


def _table_bundle() -> ChannelBundle:
    """A single valid ramp of five OBSERVED knots at ``T5``."""
    return make_bundle(T5, [0.0, 1.0, 2.0, 3.0, 4.0])


# ── spec: branch parsing, fields and invariants ──────────────────────────

_SHARED = {"method", "extrapolation", "max_bracket_span_s", "long_gap"}


class TestInterpSpecBranches:
    def test_union_has_exactly_the_four_documented_branches(self):
        schema = _ADAPTER.core_schema
        assert schema["type"] == "tagged-union"
        assert schema["discriminator"] == "method"
        assert set(schema["choices"]) == {"linear", "monotone", "cubic", "bspline"}
        minimal = {
            "linear": {
                "method": "linear",
                "extrapolation": "error",
                "max_bracket_span_s": 0.04,
                "long_gap": "missing",
            },
            "monotone": {
                "method": "monotone",
                "extrapolation": "error",
                "max_bracket_span_s": 0.04,
                "long_gap": "missing",
            },
            "cubic": {
                "method": "cubic",
                "extrapolation": "error",
                "max_bracket_span_s": 0.04,
                "long_gap": "missing",
            },
            "bspline": {
                "method": "bspline",
                "extrapolation": "error",
                "max_bracket_span_s": 0.04,
                "long_gap": "missing",
                "order": 3,
            },
        }
        expected = {
            "linear": LinearInterpSpec,
            "monotone": MonotoneInterpSpec,
            "cubic": CubicInterpSpec,
            "bspline": BsplineInterpSpec,
        }
        for tag, payload in minimal.items():
            assert type(_ADAPTER.validate_python(payload)) is expected[tag]

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (
                {
                    "method": "linear",
                    "extrapolation": "nearest",
                    "max_bracket_span_s": 0.5,
                    "long_gap": "error",
                },
                LinearInterpSpec,
            ),
            (
                {
                    "method": "monotone",
                    "extrapolation": "missing",
                    "max_bracket_span_s": 0.5,
                    "long_gap": "missing",
                },
                MonotoneInterpSpec,
            ),
            (
                {
                    "method": "cubic",
                    "extrapolation": "error",
                    "max_bracket_span_s": 0.5,
                    "long_gap": "missing",
                    "uniform_rtol": 0.05,
                },
                CubicInterpSpec,
            ),
            (
                {
                    "method": "bspline",
                    "extrapolation": "error",
                    "max_bracket_span_s": 0.5,
                    "long_gap": "missing",
                    "order": 5,
                    "uniform_rtol": 0.0,
                },
                BsplineInterpSpec,
            ),
        ],
    )
    def test_each_branch_parses_with_its_relevant_fields(self, payload, expected):
        spec = _ADAPTER.validate_python(payload)
        assert type(spec) is expected
        for field, value in payload.items():
            assert getattr(spec, field) == value

    def test_linear_and_monotone_declare_only_the_shared_fields(self):
        assert set(LinearInterpSpec.model_fields) == _SHARED
        assert set(MonotoneInterpSpec.model_fields) == _SHARED

    def test_cubic_declares_the_shared_fields_plus_a_uniform_tolerance(self):
        assert set(CubicInterpSpec.model_fields) == _SHARED | {"uniform_rtol"}
        assert cub().uniform_rtol == 0.01

    def test_bspline_declares_order_and_a_uniform_tolerance(self):
        assert set(BsplineInterpSpec.model_fields) == _SHARED | {
            "order",
            "uniform_rtol",
        }
        spec = bspl(order=2)
        assert spec.order == 2
        assert spec.uniform_rtol == 0.01

    def test_discriminator_field_is_required(self):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"max_bracket_span_s": 1.0})

    def test_unknown_method_is_rejected(self):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(
                {
                    "method": "fourier",
                    "extrapolation": "error",
                    "max_bracket_span_s": 1.0,
                    "long_gap": "missing",
                }
            )

    @pytest.mark.parametrize(
        "payload",
        [
            {
                "method": "linear",
                "extrapolation": "error",
                "max_bracket_span_s": 1.0,
                "long_gap": "missing",
                "order": 3,
            },
            {
                "method": "linear",
                "extrapolation": "error",
                "max_bracket_span_s": 1.0,
                "long_gap": "missing",
                "uniform_rtol": 0.01,
            },
            {
                "method": "monotone",
                "extrapolation": "error",
                "max_bracket_span_s": 1.0,
                "long_gap": "missing",
                "order": 2,
            },
            {
                "method": "cubic",
                "extrapolation": "error",
                "max_bracket_span_s": 1.0,
                "long_gap": "missing",
                "weight": 1.0,
            },
            {
                "method": "bspline",
                "extrapolation": "error",
                "max_bracket_span_s": 1.0,
                "long_gap": "missing",
                "order": 3,
                "window": 5,
            },
        ],
        ids=[
            "linear-order",
            "linear-uniform_rtol",
            "monotone-order",
            "cubic-weight",
            "bspline-window",
        ],
    )
    def test_irrelevant_fields_are_forbidden(self, payload):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(payload)

    @pytest.mark.parametrize(
        "payload",
        [
            {"params": {"spline_order": 3}},
            {"spline_order": 3},
            {"nan_policy": "propagate"},
            {"nan_policy": "error"},
        ],
        ids=["params", "spline_order", "nan-propagate", "nan-error"],
    )
    def test_legacy_fields_are_gone(self, payload):
        base = {
            "method": "linear",
            "extrapolation": "error",
            "max_bracket_span_s": 1.0,
            "long_gap": "missing",
        }
        base.update(payload)
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(base)

    @pytest.mark.parametrize(
        "field", ["extrapolation", "max_bracket_span_s", "long_gap"]
    )
    def test_shared_fields_are_required(self, field):
        payload = {
            "method": "linear",
            "extrapolation": "error",
            "max_bracket_span_s": 1.0,
            "long_gap": "missing",
        }
        del payload[field]
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(payload)

    @pytest.mark.parametrize("value", [0.0, -1.0, -0.5])
    def test_max_bracket_span_s_must_be_positive(self, value):
        with pytest.raises(ValidationError):
            lin(max_bracket_span_s=value)

    @pytest.mark.parametrize("value", ["nan", "clamp", "extrapolate"])
    def test_extrapolation_rejects_the_legacy_nan_spelling(self, value):
        with pytest.raises(ValidationError):
            lin(extrapolation=value)

    @pytest.mark.parametrize("value", ["error", "missing", "nearest"])
    def test_extrapolation_accepts_the_three_documented_policies(self, value):
        assert lin(extrapolation=value).extrapolation == value

    @pytest.mark.parametrize("value", ["missing", "error"])
    def test_long_gap_accepts_the_two_documented_policies(self, value):
        assert lin(long_gap=value).long_gap == value

    def test_long_gap_rejects_an_unknown_policy(self):
        with pytest.raises(ValidationError):
            lin(long_gap="nearest")

    @pytest.mark.parametrize("order", [0, 6, -1])
    def test_bspline_order_must_be_in_one_to_five(self, order):
        with pytest.raises(ValidationError):
            bspl(order=order)

    @pytest.mark.parametrize("order", [1, 5])
    def test_bspline_order_accepts_the_closed_range(self, order):
        assert bspl(order=order).order == order

    @pytest.mark.parametrize("value", [-0.01, 0.051, 1.0])
    def test_uniform_rtol_is_capped_at_five_percent(self, value):
        with pytest.raises(ValidationError):
            cub(uniform_rtol=value)
        with pytest.raises(ValidationError):
            bspl(uniform_rtol=value)

    @pytest.mark.parametrize("value", [0.0, 0.05])
    def test_uniform_rtol_accepts_the_closed_range(self, value):
        assert cub(uniform_rtol=value).uniform_rtol == value
        assert bspl(uniform_rtol=value).uniform_rtol == value

    def test_no_bundled_all_method_parameter_bag_remains(self):
        import udv_echo_process
        from udv_echo_process import process

        for module in (udv_echo_process, process):
            assert not hasattr(module, "InterpParams")
            assert not hasattr(module, "InterpMethod")
        for branch in (
            LinearInterpSpec,
            MonotoneInterpSpec,
            CubicInterpSpec,
            BsplineInterpSpec,
        ):
            assert "nan_policy" not in branch.model_fields
            assert "params" not in branch.model_fields
            assert "spline_order" not in branch.model_fields

    def test_nan_policy_is_absent_from_the_spec_source(self):
        source = (REPO / "src" / "udv_echo_process" / "process" / "specs.py").read_text(
            encoding="utf-8"
        )
        assert "nan_policy" not in source


# ── §7.3 propagation table, row by row ───────────────────────────────────


class TestPropagationTable:
    def test_row_exact_valid_observed_knot_copies_value_kind_and_quality(self):
        out = resample(_table_bundle(), lin(), times=T5).artifact.data
        assert np.allclose(out.values[:, 0], [0.0, 1.0, 2.0, 3.0, 4.0])
        assert np.array_equal(out.support.kind[:, 0], np.full(5, OBSERVED, np.uint8))
        assert out.support.valid.all()
        assert np.array_equal(out.support.quality[:, 0], np.zeros(5, np.uint32))

    def test_row_exact_valid_interpolated_knot_keeps_kind_and_gains_reinterpolated(
        self,
    ):
        bundle = make_bundle(
            T5, [0.0, 1.0, 2.0, 3.0, 4.0], kind=np.full((5, 1), INTERPOLATED, np.uint8)
        )
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.array_equal(
            out.support.kind[:, 0], np.full(5, INTERPOLATED, np.uint8)
        )
        assert np.array_equal(
            out.support.quality[:, 0], np.full(5, REINTERPOLATED, np.uint32)
        )

    def test_row_exact_valid_extrapolated_knot_keeps_kind_and_gains_reinterpolated(
        self,
    ):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            kind=np.full((5, 1), EXTRAPOLATED, np.uint8),
            quality=np.full((5, 1), EXTRAPOLATED_FLAG, np.uint32),
        )
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.array_equal(
            out.support.kind[:, 0], np.full(5, EXTRAPOLATED, np.uint8)
        )
        assert np.array_equal(
            out.support.quality[:, 0],
            np.full(5, EXTRAPOLATED_FLAG | REINTERPOLATED, np.uint32),
        )

    def test_row_exact_invalid_observed_knot_is_nan_observed_with_its_reason(self):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            kind=np.full((5, 1), OBSERVED, np.uint8),
            valid=[True, True, False, True, True],
            quality=[0, 0, OUTLIER, 0, 0],
        )
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.isnan(out.values[2, 0])
        assert out.support.kind[2, 0] == OBSERVED
        assert not out.support.valid[2, 0]
        assert out.support.quality[2, 0] == OUTLIER

    def test_row_exact_missing_knot_is_nan_missing_and_copies_quality(self):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            kind=[OBSERVED, OBSERVED, MISSING, OBSERVED, OBSERVED],
            quality=[0, 0, GAP_TOO_LONG, 0, 0],
        )
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.isnan(out.values[2, 0])
        assert out.support.kind[2, 0] == MISSING
        assert not out.support.valid[2, 0]
        assert out.support.quality[2, 0] == GAP_TOO_LONG

    def test_row_between_two_valid_knots_is_interpolated(self):
        out = resample(_table_bundle(), lin(), times=[0.05, 0.15, 0.25, 0.35])
        data = out.artifact.data
        assert np.allclose(data.values[:, 0], [0.5, 1.5, 2.5, 3.5])
        assert np.array_equal(
            data.support.kind[:, 0], np.full(4, INTERPOLATED, np.uint8)
        )
        assert data.support.valid.all()
        assert np.array_equal(data.support.quality[:, 0], np.zeros(4, np.uint32))

    @pytest.mark.parametrize(
        ("kinds", "expected_kind", "expected_quality"),
        [
            ((OBSERVED, OBSERVED), INTERPOLATED, 0),
            ((OBSERVED, INTERPOLATED), INTERPOLATED, REINTERPOLATED),
            ((INTERPOLATED, INTERPOLATED), INTERPOLATED, REINTERPOLATED),
            (
                (OBSERVED, EXTRAPOLATED),
                EXTRAPOLATED,
                EXTRAPOLATED_FLAG | REINTERPOLATED,
            ),
            (
                (INTERPOLATED, EXTRAPOLATED),
                EXTRAPOLATED,
                EXTRAPOLATED_FLAG | REINTERPOLATED,
            ),
            (
                (EXTRAPOLATED, EXTRAPOLATED),
                EXTRAPOLATED,
                EXTRAPOLATED_FLAG | REINTERPOLATED,
            ),
        ],
        ids=[
            "observed-observed",
            "observed-interpolated",
            "interpolated-interpolated",
            "observed-extrapolated",
            "interpolated-extrapolated",
            "extrapolated-extrapolated",
        ],
    )
    def test_row_ancestry_matrix_between_two_valid_knots(
        self, kinds, expected_kind, expected_quality
    ):
        kind = np.array([kinds[0], kinds[1], OBSERVED, OBSERVED, OBSERVED], np.uint8)
        quality = np.where(
            kind == EXTRAPOLATED, EXTRAPOLATED_FLAG, np.zeros(5, np.int64)
        ).astype(np.uint32)
        bundle = make_bundle(
            T5, np.arange(5, dtype=np.float64), kind=kind, quality=quality
        )
        out = resample(bundle, lin(), times=[0.05]).artifact.data
        assert out.values[0, 0] == pytest.approx(0.5)
        assert out.support.kind[0, 0] == expected_kind
        assert out.support.quality[0, 0] == expected_quality

    def test_row_missing_bracket_endpoint_is_missing_with_gap_too_long(self):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            kind=[OBSERVED, OBSERVED, MISSING, OBSERVED, OBSERVED],
        )
        data = resample(bundle, lin(), times=[0.15, 0.25]).artifact.data
        assert np.isnan(data.values).all()
        assert np.array_equal(data.support.kind[:, 0], [MISSING, MISSING])
        assert not data.support.valid.any()
        assert np.array_equal(
            data.support.quality[:, 0], np.full(2, GAP_TOO_LONG, np.uint32)
        )

    def test_row_invalid_bracket_endpoint_is_missing_with_endpoint_reason(self):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            valid=[True, True, False, True, True],
            quality=[0, 0, OUTLIER, 0, 0],
        )
        data = resample(bundle, lin(), times=[0.15, 0.25]).artifact.data
        assert np.isnan(data.values).all()
        assert np.array_equal(data.support.kind[:, 0], [MISSING, MISSING])
        assert np.array_equal(
            data.support.quality[:, 0], np.full(2, OUTLIER | GAP_TOO_LONG, np.uint32)
        )

    def test_row_bracket_over_the_limit_long_gap_missing_is_missing(self):
        bundle = make_bundle([0.0, 0.1, 5.0, 5.1], [0.0, 1.0, 2.0, 3.0])
        data = resample(
            bundle, lin(max_bracket_span_s=1.0), times=[0.05, 2.0, 5.05]
        ).artifact.data
        assert np.allclose(data.values[[0, 2], 0], [0.5, 2.5])
        assert np.isnan(data.values[1, 0])
        assert data.support.kind[1, 0] == MISSING
        assert not data.support.valid[1, 0]
        assert data.support.quality[1, 0] == GAP_TOO_LONG

    def test_row_bracket_over_the_limit_long_gap_error_raises_before_artifact(self):
        bundle = make_bundle([0.0, 0.1, 5.0, 5.1], [0.0, 1.0, 2.0, 3.0])
        with pytest.raises(ValueError) as excinfo:
            resample(
                bundle,
                lin(max_bracket_span_s=1.0, long_gap="error"),
                times=[2.0],
            )
        text = str(excinfo.value)
        assert "interp.linear" in text
        assert "channel 4" in text
        assert "gate 0" in text
        assert "[0.1, 5]" in text
        assert "4.9" in text
        assert "max_bracket_span_s=1" in text
        # no artifact was created and the parent is untouched
        assert bundle.graph.operations == ()
        assert bundle.graph.derivations == ()

    def test_row_outside_domain_error_raises_with_count_and_source_bounds(self):
        bundle = _table_bundle()
        with pytest.raises(ValueError) as excinfo:
            resample(bundle, lin(extrapolation="error"), times=[-1.0, 0.35, 5.0])
        text = str(excinfo.value)
        assert "interp.linear" in text
        assert "channel 4" in text
        assert "gate 0" in text
        assert "2 target row(s)" in text
        assert "[0, 0.4] s" in text
        assert "extrapolation='error'" in text
        assert bundle.graph.operations == ()

    def test_row_outside_domain_missing_is_nan_missing_with_out_of_range(self):
        data = resample(
            _table_bundle(), lin(extrapolation="missing"), times=[-1.0, 0.35, 5.0]
        ).artifact.data
        assert np.isnan(data.values[[0, 2], 0]).all()
        assert np.allclose(data.values[1, 0], 3.5)
        assert np.array_equal(data.support.kind[[0, 2], 0], [MISSING, MISSING])
        assert not data.support.valid[[0, 2], 0].any()
        assert np.array_equal(
            data.support.quality[[0, 2], 0], np.full(2, OUT_OF_RANGE, np.uint32)
        )

    def test_row_outside_domain_nearest_clamps_as_extrapolated(self):
        data = resample(
            _table_bundle(), lin(extrapolation="nearest"), times=[-1.0, 0.35, 5.0]
        ).artifact.data
        assert data.values[0, 0] == pytest.approx(0.0)
        assert data.values[2, 0] == pytest.approx(4.0)
        assert data.values[1, 0] == pytest.approx(3.5)
        assert np.array_equal(
            data.support.kind[[0, 2], 0], np.full(2, EXTRAPOLATED, np.uint8)
        )
        assert np.array_equal(
            data.support.quality[[0, 2], 0],
            np.full(2, EXTRAPOLATED_FLAG | OUT_OF_RANGE, np.uint32),
        )

    def test_row_outside_domain_missing_keeps_the_edge_quality(self):
        bundle = make_bundle(
            T5,
            [0.0, 1.0, 2.0, 3.0, 4.0],
            quality=[OUTLIER, 0, 0, 0, 0],
        )
        data = resample(
            bundle, lin(extrapolation="missing"), times=[-1.0, 5.0]
        ).artifact.data
        assert data.support.quality[0, 0] == OUTLIER | OUT_OF_RANGE
        assert data.support.quality[1, 0] == OUT_OF_RANGE

    def test_nearest_does_not_bridge_an_internal_long_gap(self):
        # inside the overall valid domain, so the over-long bracket rule -- not
        # the extrapolation policy -- decides the row
        bundle = make_bundle([0.0, 0.1, 5.0], [0.0, 1.0, 2.0])
        data = resample(
            bundle, lin(extrapolation="nearest", max_bracket_span_s=1.0), times=[2.0]
        ).artifact.data
        assert np.isnan(data.values[0, 0])
        assert data.support.kind[0, 0] == MISSING
        assert data.support.quality[0, 0] == GAP_TOO_LONG

    def test_gates_are_resampled_independently(self):
        values = np.column_stack(
            [np.arange(5, dtype=np.float64), np.arange(5, dtype=np.float64) * 10.0]
        )
        bundle = make_bundle(T5, values)
        data = resample(bundle, lin(), times=[0.05, 0.15]).artifact.data
        assert np.allclose(data.values[:, 0], [0.5, 1.5])
        assert np.allclose(data.values[:, 1], [5.0, 15.0])


# ── segment-aware sampling and strict spline rules ───────────────────────


class TestSegmentsAndUniformity:
    def test_linear_has_no_uniformity_requirement(self):
        # rows 2->3 is a 0.3 s interval on a 0.1 s cadence: non-uniform
        bundle = make_bundle([0.0, 0.1, 0.2, 0.5, 0.6, 0.7], np.arange(6, dtype=float))
        data = resample(
            bundle, lin(max_bracket_span_s=10.0), times=[0.25]
        ).artifact.data
        assert data.support.kind[0, 0] == INTERPOLATED
        assert np.isfinite(data.values[0, 0])

    def test_monotone_has_no_uniformity_requirement(self):
        bundle = make_bundle([0.0, 0.1, 0.2, 0.5, 0.6, 0.7], np.arange(6, dtype=float))
        data = resample(
            bundle, mono(max_bracket_span_s=10.0), times=[0.25]
        ).artifact.data
        assert data.support.kind[0, 0] == INTERPOLATED
        assert np.isfinite(data.values[0, 0])

    def test_cubic_rejects_a_non_uniform_sampled_segment_with_a_full_diagnostic(self):
        bundle = make_bundle([0.0, 0.1, 0.2, 0.5, 0.6, 0.7], np.ones(6))
        with pytest.raises(ValueError) as excinfo:
            resample(bundle, cub(max_bracket_span_s=10.0), times=[0.25])
        text = str(excinfo.value)
        assert "interp.cubic" in text
        assert "channel 4" in text
        assert "segment rows [0, 6)" in text
        assert "median dt=0.1" in text
        assert "worst dt=0.3" in text
        assert "uniform_rtol=0.01" in text

    def test_cubic_passes_at_the_tolerance_that_holds(self):
        # one 3% interval: above the 1% default, inside the 5% cap
        bundle = make_bundle([0.0, 0.1, 0.2, 0.303, 0.403], np.ones(5))
        with pytest.raises(ValueError):
            resample(bundle, cub(max_bracket_span_s=10.0), times=[0.25])
        data = resample(
            bundle, cub(max_bracket_span_s=10.0, uniform_rtol=0.05), times=[0.25]
        ).artifact.data
        assert np.isfinite(data.values[0, 0])

    def test_bspline_rejects_a_non_uniform_sampled_segment(self):
        bundle = make_bundle([0.0, 0.1, 0.2, 0.5, 0.6, 0.7], np.ones(6))
        with pytest.raises(ValueError, match="interp.bspline"):
            resample(bundle, bspl(order=3, max_bracket_span_s=10.0), times=[0.25])

    def test_cubic_and_bspline_check_the_final_interval_too(self):
        # the superseded legacy rule ignored the last interval; a signal that
        # differs only there must still be rejected
        bundle = make_bundle([0.0, 0.1, 0.2, 0.3, 3.0], np.ones(5))
        for spec in (
            cub(max_bracket_span_s=10.0),
            bspl(order=3, max_bracket_span_s=10.0),
        ):
            with pytest.raises(ValueError) as excinfo:
                resample(bundle, spec, times=[0.25])
            text = str(excinfo.value)
            assert "segment rows [0, 5)" in text
            assert "worst dt=2.7" in text

    def test_capacity_error_names_method_required_and_actual(self):
        bundle = make_bundle(np.arange(4, dtype=np.float64) * 0.1, np.ones(4))
        with pytest.raises(ValueError) as excinfo:
            resample(bundle, bspl(order=4), times=[0.15])
        text = str(excinfo.value)
        assert "interp.bspline" in text
        assert "at least 5 samples" in text
        assert "segment rows [0, 4)" in text
        assert "has 4" in text
        # order 3 fits the same four rows
        data = resample(bundle, bspl(order=3), times=[0.15]).artifact.data
        assert np.isfinite(data.values[0, 0])

    def test_only_sampled_segments_are_capacity_checked(self):
        # a six-row segment (fits order 5) plus a two-row segment that is not
        # sampled until a target lands inside it
        time_s = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 5.0, 5.1])
        bundle = make_bundle(time_s, np.ones(8))
        ok = resample(bundle, bspl(order=5), times=[0.25]).artifact.data
        assert np.isfinite(ok.values[0, 0])
        with pytest.raises(ValueError, match="interp.bspline"):
            resample(bundle, bspl(order=5), times=[0.25, 5.05])


# ── the exact-time rule and row acquisition index (STOP/GO) ──────────────


class TestRowAcquisitionIndex:
    T = T5

    def _index(self, sample_id, times) -> AcquisitionIndex:
        return AcquisitionIndex(
            sample_id=np.asarray(sample_id, np.int64),
            acquisition_time_s=np.asarray(times, np.float64),
        )

    def test_exact_ancestral_rows_preserve_the_real_acquisition_index(self):
        acquisition = self._index(np.arange(5) + 10, T5)
        bundle = make_bundle(T5, np.arange(5, dtype=float), acquisition=acquisition)
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.array_equal(out.acquisition.sample_id, np.arange(5) + 10)
        assert np.allclose(out.acquisition.acquisition_time_s, T5)

    def test_non_exact_rows_take_the_synthetic_sentinel(self):
        acquisition = self._index(np.arange(5) + 10, T5)
        bundle = make_bundle(T5, np.arange(5, dtype=float), acquisition=acquisition)
        out = resample(bundle, lin(), times=[0.05, 0.15, 0.25]).artifact.data
        assert np.array_equal(out.acquisition.sample_id, [-1, -1, -1])
        assert np.isnan(out.acquisition.acquisition_time_s).all()

    def test_a_row_whose_exact_cells_are_all_missing_takes_the_sentinel(self):
        # gate 1 misses every row; gate 0 misses row 2, so that row -- and only
        # it -- is wholly synthetic in the source index
        kind = np.full((5, 2), OBSERVED, np.uint8)
        kind[2, 0] = MISSING
        kind[:, 1] = MISSING
        values = np.column_stack([np.arange(5, dtype=float), np.arange(5, dtype=float)])
        acquisition = self._index([10, 11, -1, 13, 14], [0.0, 0.1, np.nan, 0.3, 0.4])
        bundle = make_bundle(T5, values, kind=kind, acquisition=acquisition)
        out = resample(bundle, lin(), times=T5).artifact.data
        assert np.array_equal(out.acquisition.sample_id, [10, 11, -1, 13, 14])
        assert out.support.kind[2, 0] == MISSING
        assert out.support.kind[0, 1] == MISSING

    def test_the_row_keeps_its_index_when_another_gate_is_observed(self):
        # gate 1 is MISSING on row 2 but gate 0 is a real observation there
        kind = np.full((5, 2), OBSERVED, np.uint8)
        kind[2, 1] = MISSING
        values = np.column_stack([np.arange(5, dtype=float), np.arange(5, dtype=float)])
        acquisition = self._index(np.arange(5) + 10, T5)
        bundle = make_bundle(T5, values, kind=kind, acquisition=acquisition)
        out = resample(bundle, lin(), times=T5).artifact.data
        assert out.support.kind[2, 1] == MISSING
        assert out.acquisition.sample_id[2] == 12

    def test_optional_ids_are_carried_on_exact_rows_and_minus_one_otherwise(self):
        acquisition = AcquisitionIndex(
            sample_id=np.arange(5, dtype=np.int64) + 10,
            acquisition_time_s=T5,
            round_id=np.full(5, 7, np.int64),
            visit_id=np.arange(5, dtype=np.int64),
            profile_in_visit=np.arange(5, dtype=np.int64) * 3,
        )
        bundle = make_bundle(T5, np.arange(5, dtype=float), acquisition=acquisition)
        exact = resample(bundle, lin(), times=T5).artifact.data
        assert np.array_equal(exact.acquisition.round_id, np.full(5, 7))
        assert np.array_equal(exact.acquisition.visit_id, np.arange(5))
        assert np.array_equal(exact.acquisition.profile_in_visit, np.arange(5) * 3)
        interp = resample(bundle, lin(), times=[0.05, 0.15]).artifact.data
        assert np.array_equal(interp.acquisition.round_id, [-1, -1])
        assert np.array_equal(interp.acquisition.visit_id, [-1, -1])
        assert np.array_equal(interp.acquisition.profile_in_visit, [-1, -1])

    def test_absent_optional_ids_stay_absent(self):
        acquisition = self._index(np.arange(5) + 10, T5)
        bundle = make_bundle(T5, np.arange(5, dtype=float), acquisition=acquisition)
        out = resample(bundle, lin(), times=T5).artifact.data
        assert out.acquisition.round_id is None
        assert out.acquisition.visit_id is None
        assert out.acquisition.profile_in_visit is None

    def test_no_parent_index_yields_no_output_index(self):
        out = resample(_table_bundle(), lin(), times=T5).artifact.data
        assert out.acquisition is None

    def test_exact_synthetic_rows_never_produce_an_acquisition_index(self):
        bundle = make_bundle(
            T5,
            np.arange(5, dtype=float),
            kind=np.full((5, 1), INTERPOLATED, np.uint8),
        )
        out = resample(bundle, lin(), times=T5).artifact.data
        assert out.acquisition is None


# ── three generations: support is never laundered ────────────────────────


class TestThreeGenerations:
    def _generation_one(self) -> ChannelBundle:
        source = make_bundle(T5, np.arange(5, dtype=float))
        return resample(source, lin(), times=[0.0, 0.05, 0.1, 0.15, 0.2])

    def test_the_first_interpolation_marks_the_observed_and_synthetic_cells(self):
        data = self._generation_one().artifact.data
        assert np.array_equal(
            data.support.kind[:, 0],
            [OBSERVED, INTERPOLATED, OBSERVED, INTERPOLATED, OBSERVED],
        )
        # observed ancestors: a first-generation interpolated cell carries no
        # REINTERPOLATED bit (that is added only when an ancestor is synthetic)
        synthetic = data.support.kind[:, 0] == INTERPOLATED
        assert np.array_equal(
            data.support.quality[synthetic, 0], np.zeros(2, np.uint32)
        )

    def test_no_synthetic_cell_becomes_observed_on_re_interpolation(self):
        gen1 = self._generation_one()
        gen2 = resample(gen1, lin(), times=gen1.artifact.data.time_s)
        synthetic = gen1.artifact.data.support.kind != OBSERVED
        assert not (gen2.artifact.data.support.kind[synthetic] == OBSERVED).any()
        assert np.array_equal(
            gen2.artifact.data.support.kind, gen1.artifact.data.support.kind
        )

    def test_exact_synthetic_knots_keep_their_kind_and_gain_reinterpolated(self):
        gen1 = self._generation_one()
        gen2 = resample(gen1, lin(), times=gen1.artifact.data.time_s)
        synth = gen1.artifact.data.support.kind == INTERPOLATED
        assert np.array_equal(
            gen2.artifact.data.support.quality[synth],
            np.full(int(synth.sum()), REINTERPOLATED, np.uint32),
        )
        observed = gen1.artifact.data.support.kind == OBSERVED
        # observed knots carry no REINTERPOLATED bit
        assert np.array_equal(
            gen2.artifact.data.support.quality[observed],
            np.zeros(int(observed.sum()), np.uint32),
        )

    def test_between_generation_one_knots_stays_synthetic(self):
        gen1 = self._generation_one()
        gen2 = resample(gen1, lin(), times=[0.025, 0.075, 0.125, 0.175])
        data = gen2.artifact.data
        assert np.array_equal(
            data.support.kind[:, 0], np.full(4, INTERPOLATED, np.uint8)
        )
        assert np.array_equal(
            data.support.quality[:, 0], np.full(4, REINTERPOLATED, np.uint32)
        )
        assert data.support.valid.all()

    def test_the_parent_arrays_are_unchanged_and_not_shared(self):
        gen1 = self._generation_one()
        before = {id(arr): arr.copy() for arr in _arrays(gen1.artifact.data)}
        gen2 = resample(gen1, lin(), times=gen1.artifact.data.time_s)
        for arr in _arrays(gen1.artifact.data):
            assert np.array_equal(arr, before[id(arr)], equal_nan=True)
        for parent in _arrays(gen1.artifact.data):
            for produced in _arrays(gen2.artifact.data):
                assert not np.shares_memory(parent, produced)


# ── target grid (ruling D6) ──────────────────────────────────────────────


class TestTargetGrid:
    def test_dt_s_builds_an_exactly_uniform_grid(self):
        bundle = make_bundle([0.0, 1.0], [0.0, 10.0])
        out = resample(bundle, lin(), dt_s=0.3).artifact.data
        assert np.allclose(out.time_s, [0.0, 0.3, 0.6, 0.9])

    def test_the_grid_is_t0_plus_arange_times_dt(self):
        t0, t1, dt = 0.37, 2.05, 0.13
        bundle = make_bundle([t0, t1], [0.0, 1.0])
        out = resample(bundle, lin(), dt_s=dt).artifact.data
        n = 12  # floor((2.05 - 0.37) / 0.13) == 12
        assert np.allclose(out.time_s, t0 + np.arange(n + 1) * dt)
        assert out.time_s[-1] <= t1 < out.time_s[-1] + dt

    def test_the_residual_tail_shorter_than_dt_s_is_not_represented(self):
        bundle = make_bundle([0.0, 1.0], [0.0, 1.0])
        out = resample(bundle, lin(), dt_s=0.4).artifact.data
        assert out.time_s[-1] == pytest.approx(0.8)
        assert not np.isclose(out.time_s, 1.0).any()

    def test_dt_s_equal_to_the_span_gives_two_points(self):
        bundle = make_bundle([0.0, 1.0], [0.0, 1.0])
        out = resample(bundle, lin(), dt_s=1.0).artifact.data
        assert np.allclose(out.time_s, [0.0, 1.0])

    def test_dt_s_must_be_finite_positive_and_no_larger_than_the_span(self):
        bundle = make_bundle([0.0, 1.0], [0.0, 1.0])
        for dt in (0.0, -0.1, float("nan"), float("inf"), 2.0):
            with pytest.raises(ValueError):
                resample(bundle, lin(), dt_s=dt)
        with pytest.raises(ValueError, match="exceeds the source span"):
            resample(bundle, lin(), dt_s=2.0)

    def test_a_dt_s_output_passes_a_uniformity_check(self):
        # a deliberately non-uniform source: 0.1 s cadence with two jittered intervals
        time_s = np.cumsum(np.full(8, 0.1) + np.array([0, 0, 0, 0.02, 0, 0, 0.03, 0]))
        bundle = make_bundle(time_s, np.linspace(0.0, 1.0, 8))
        out = resample(bundle, lin(), dt_s=0.1)
        # the raw source is rejected ...
        with pytest.raises(ValueError, match="not truly uniform"):
            filter(bundle, SavgolFilterSpec(window=3, polyorder=1, max_gap_s=1.0))
        # ... the uniformly resampled grid is not
        savgol = filter(out, SavgolFilterSpec(window=3, polyorder=1, max_gap_s=1.0))
        tv = filter(out, TvFilterSpec(weight=0.5, iterations=20, max_gap_s=1.0))
        assert savgol.graph.operations[-1].kind == "filter.savgol"
        assert tv.graph.operations[-1].kind == "filter.tv"
        cubic = resample(out, cub(), dt_s=0.1)
        assert cubic.graph.operations[-1].kind == "interp.cubic"

    def test_exactly_one_of_times_or_dt_s(self):
        bundle = _table_bundle()
        with pytest.raises(ValueError, match="exactly one"):
            resample(bundle, lin())
        with pytest.raises(ValueError, match="exactly one"):
            resample(bundle, lin(), times=T5, dt_s=0.1)

    def test_times_must_be_finite_strictly_increasing_and_nonempty(self):
        bundle = _table_bundle()
        for bad in (
            np.array([0.5, 0.2]),
            np.array([0.5, 0.5]),
            np.array([0.0, np.nan]),
            np.array([]),
            np.zeros((2, 2)),
        ):
            with pytest.raises(ValueError):
                resample(bundle, lin(), times=bad)

    def test_accepts_a_list_of_times(self):
        out = resample(_table_bundle(), lin(), times=[0.0, 0.2, 0.4])
        assert out.artifact.data.time_s.size == 3


# ── metadata, operation record, ownership and determinism ───────────────


class TestBundleContract:
    def test_metadata_and_acquisition_identity_are_preserved(self):
        acquisition = AcquisitionIndex(
            sample_id=np.arange(5, dtype=np.int64),
            acquisition_time_s=T5,
        )
        config = ChannelConfig(n_gates=1, sound_speed_ms=1480.0)
        bundle = make_bundle(
            T5, np.arange(5, dtype=float), config=config, acquisition=acquisition
        )
        out = resample(bundle, lin(), times=[0.05, 0.15])
        assert out.artifact.acquisition == bundle.artifact.acquisition
        assert out.artifact.descriptor == bundle.artifact.descriptor
        assert out.artifact.config == config
        assert np.array_equal(
            out.artifact.data.gate_depths_mm, bundle.artifact.data.gate_depths_mm
        )

    def test_the_operation_record_is_complete(self):
        bundle = _table_bundle()
        out = resample(bundle, lin(), times=[0.05])
        assert len(out.graph.operations) == 1
        record = out.graph.operations[0]
        assert record.kind == "interp.linear"
        assert record.schema_version == 1
        assert record.parents == (bundle.artifact.artifact_id,)
        assert record.params_json == (
            '{"extrapolation":"error","long_gap":"missing",'
            '"max_bracket_span_s":1.0,"method":"linear"}'
        )
        assert record.implementation.callable == (
            "udv_echo_process.process.sync.resample"
        )
        assert out.graph.root_artifacts == (bundle.artifact.artifact_id,)
        assert len(out.graph.derivations) == 1

    @pytest.mark.parametrize(
        ("spec", "kind", "params_json"),
        [
            (
                lin(),
                "interp.linear",
                (
                    '{"extrapolation":"error","long_gap":"missing",'
                    '"max_bracket_span_s":1.0,"method":"linear"}'
                ),
            ),
            (
                mono(),
                "interp.monotone",
                (
                    '{"extrapolation":"error","long_gap":"missing",'
                    '"max_bracket_span_s":1.0,"method":"monotone"}'
                ),
            ),
            (
                cub(),
                "interp.cubic",
                (
                    '{"extrapolation":"error","long_gap":"missing",'
                    '"max_bracket_span_s":1.0,"method":"cubic","uniform_rtol":0.01}'
                ),
            ),
            (
                bspl(order=3),
                "interp.bspline",
                (
                    '{"extrapolation":"error","long_gap":"missing",'
                    '"max_bracket_span_s":1.0,"method":"bspline","order":3,'
                    '"uniform_rtol":0.01}'
                ),
            ),
        ],
        ids=["linear", "monotone", "cubic", "bspline"],
    )
    def test_every_branch_registers_its_kind(self, spec, kind, params_json):
        out = resample(_table_bundle(), spec, times=[0.05])
        record = out.graph.operations[0]
        assert record.kind == kind
        assert record.params_json == params_json

    def test_the_parent_bundle_is_never_mutated(self):
        bundle = _table_bundle()
        before_values = bundle.artifact.data.values.copy()
        before_quality = bundle.artifact.data.support.quality.copy()
        before_graph = bundle.graph
        resample(bundle, lin(), times=[0.05])
        assert np.array_equal(
            bundle.artifact.data.values, before_values, equal_nan=True
        )
        assert np.array_equal(bundle.artifact.data.support.quality, before_quality)
        assert bundle.graph == before_graph
        assert bundle.graph.operations == ()

    def test_output_arrays_are_owned_and_share_no_memory_with_the_parent(self):
        bundle = _table_bundle()
        out = resample(bundle, lin(), times=[0.05, 0.15])
        for parent in _arrays(bundle.artifact.data):
            for produced in _arrays(out.artifact.data):
                assert not np.shares_memory(parent, produced)
        for produced in _arrays(out.artifact.data):
            assert produced.flags["OWNDATA"]
            assert produced.flags["C_CONTIGUOUS"]
            assert not produced.flags["WRITEABLE"]

    def test_equal_inputs_produce_equal_ids_and_changed_specs_do_not(self):
        bundle = _table_bundle()
        first = resample(bundle, lin(), times=[0.05])
        second = resample(bundle, lin(), times=[0.05])
        assert first.artifact.artifact_id == second.artifact.artifact_id
        assert (
            first.graph.operations[0].operation_id
            == second.graph.operations[0].operation_id
        )
        changed = resample(bundle, lin(max_bracket_span_s=0.5), times=[0.05])
        assert changed.artifact.artifact_id != first.artifact.artifact_id
        assert (
            changed.graph.operations[0].operation_id
            != first.graph.operations[0].operation_id
        )

    def test_a_derived_bundle_chains(self):
        once = resample(_table_bundle(), lin(), times=[0.05, 0.15])
        twice = resample(once, mono(), times=[0.1])
        assert len(twice.graph.operations) == 2
        assert twice.graph.operations[-1].parents == (once.artifact.artifact_id,)

    def test_reinterpolation_output_differs_from_a_single_pass(self):
        bundle = _table_bundle()
        once = resample(bundle, lin(), times=[0.05, 0.15])
        twice = resample(
            once,
            lin(),
            times=[0.05, 0.15],
        )
        # exact knots from generation one keep INTERPOLATED support and gain
        # REINTERPOLATED, so the ids cannot coincide
        assert twice.artifact.artifact_id != once.artifact.artifact_id
        assert (
            twice.artifact.data.support.quality[:, 0]
            == once.artifact.data.support.quality[:, 0] | REINTERPOLATED
        ).all()

    def test_resample_rejects_a_non_interpolation_spec(self):
        from udv_echo_process.process import MedianFilterSpec

        with pytest.raises(TypeError, match="expects an InterpSpec branch"):
            resample(
                _table_bundle(),
                MedianFilterSpec(window=3, max_gap_s=1.0),  # type: ignore[arg-type]
                times=[0.05],
            )

    def test_ids_are_deterministic_across_two_processes(self):
        local = _canonical_ids(_canonical_bundle())
        completed = subprocess.run(
            [sys.executable, "-c", _PROCESS_SCRIPT],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        remote = json.loads(completed.stdout.strip().splitlines()[-1])
        assert remote == local


def _canonical_bundle() -> ChannelBundle:
    """The deterministic bundle shared by the in-process and subprocess tests."""
    data = observed_signal([0.0, 0.1, 0.2, 0.3], [0.0], [[1.0], [2.0], [3.0], [4.0]])
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=4),
    )
    return source_bundle(source_artifact(ref, _ECHO, ChannelConfig(), data))


def _canonical_ids(bundle: ChannelBundle) -> dict[str, str]:
    out = resample(bundle, lin(), times=[0.05, 0.15, 0.25])
    return {
        "operation_id": out.graph.operations[0].operation_id,
        "artifact_id": out.artifact.artifact_id,
    }


_PROCESS_SCRIPT = """
import json

from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    SignalDescriptor,
    SignalQuantity,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import LinearInterpSpec, resample
from udv_echo_process.provenance import source_bundle

asset_id = "sha256:" + "1" * 64
ref = AcquisitionRef(
    recording_id=recording_id_for(asset_id),
    source_asset_id=asset_id,
    channel=ChannelKey(device_channel=4),
)
descriptor = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
data = observed_signal(
    [0.0, 0.1, 0.2, 0.3], [0.0], [[1.0], [2.0], [3.0], [4.0]]
)
bundle = source_bundle(source_artifact(ref, descriptor, ChannelConfig(), data))
spec = LinearInterpSpec(
    extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
)
out = resample(bundle, spec, times=[0.05, 0.15, 0.25])
print(
    json.dumps(
        {
            "operation_id": out.graph.operations[0].operation_id,
            "artifact_id": out.artifact.artifact_id,
        }
    )
)
"""


# ── real .BDD fixtures through the test adapter ──────────────────────────


def _fixture_bundle(
    path: Path, channel: int, descriptor: SignalDescriptor
) -> ChannelBundle:
    """TEST ADAPTER: ``MultiplexedMeasurement`` -> source ``ChannelBundle``.

    The ``.BDD`` reader still returns ``MultiplexedMeasurement`` until phase 6,
    so the test builds the source artifact itself. Every fixture value is finite
    and every time strictly increasing (verified), so an all-``OBSERVED``
    ``observed_signal`` is correct. No round/visit ids are invented.
    """
    measurement = load(path)
    series = measurement.by_channel()[channel]
    asset_id = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    acquisition = AcquisitionRef(
        recording_id=recording_id_for(asset_id),
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    data = observed_signal(series.time_s, series.gate_depths_mm, series.values)
    return source_bundle(source_artifact(acquisition, descriptor, series.config, data))


@pytest.fixture(scope="module")
def echo_bundle() -> ChannelBundle:
    return _fixture_bundle(ECHO_PATH, 4, _ECHO)


@pytest.fixture(scope="module")
def four_sensor_bundle() -> ChannelBundle:
    return _fixture_bundle(FOUR_SENSOR_PATH, 6, _VELOCITY)


class TestRealFixtures:
    def test_echo_exact_knots_round_trip_for_every_method(self, echo_bundle):
        source = echo_bundle.artifact.data
        for spec in (
            lin(),
            mono(),
            cub(uniform_rtol=0.05),
            bspl(order=3, uniform_rtol=0.05),
        ):
            data = resample(echo_bundle, spec, times=source.time_s).artifact.data
            assert np.allclose(data.values, source.values, rtol=1e-9, atol=1e-12)
            assert np.array_equal(data.support.kind, source.support.kind)
            assert data.support.valid.all()
            assert np.array_equal(
                data.support.kind, np.full(source.values.shape, OBSERVED, np.uint8)
            )

    def test_echo_cubic_and_bspline_reject_the_default_tolerance(self, echo_bundle):
        # the echo cadence alternates 3.1/3.2 ms (~3.1% spread), above 1%
        with pytest.raises(ValueError, match="interp.cubic"):
            resample(echo_bundle, cub(), dt_s=0.005)
        with pytest.raises(ValueError, match="interp.bspline"):
            resample(echo_bundle, bspl(order=3), dt_s=0.005)

    def test_echo_cubic_and_bspline_pass_at_the_holding_tolerance(self, echo_bundle):
        cubic = resample(echo_bundle, cub(uniform_rtol=0.05), dt_s=0.005).artifact.data
        spline = resample(
            echo_bundle, bspl(order=3, uniform_rtol=0.05), dt_s=0.005
        ).artifact.data
        assert np.isfinite(cubic.values).all()
        assert np.isfinite(spline.values).all()

    def test_echo_linear_and_monotone_run_without_a_uniformity_requirement(
        self, echo_bundle
    ):
        for spec in (lin(), mono()):
            data = resample(echo_bundle, spec, dt_s=0.005).artifact.data
            assert np.isfinite(data.values).all()

    def test_four_sensor_dt_grid_is_exactly_uniform(self, four_sensor_bundle):
        data = resample(four_sensor_bundle, lin(), dt_s=0.05).artifact.data
        assert np.array_equal(
            np.unique(np.round(np.diff(data.time_s), 12)), np.array([0.05])
        )

    def test_four_sensor_gaps_stay_missing_and_never_are_bridged(
        self, four_sensor_bundle
    ):
        # 99 inter-round gaps exceed 40 ms; max_bracket_span_s=0.040 splits the
        # channel into 100 uniform 4-row segments, so the gaps stay MISSING
        data = resample(
            four_sensor_bundle, lin(max_bracket_span_s=0.040), dt_s=0.05
        ).artifact.data
        assert np.isnan(data.values[~data.support.valid]).all()
        assert (data.support.kind[~data.support.valid] == MISSING).all()
        assert np.isfinite(data.values[data.support.valid]).all()

    def test_four_sensor_bspline_capacity_by_order(self, four_sensor_bundle):
        # a 4-row segment fits order <= 3 (order k needs k + 1 rows)
        for order in (1, 2, 3):
            data = resample(
                four_sensor_bundle,
                bspl(order=order, max_bracket_span_s=0.040),
                dt_s=0.05,
            ).artifact.data
            assert data.support.valid.any()
        for order in (4, 5):
            with pytest.raises(ValueError, match="interp.bspline") as excinfo:
                resample(
                    four_sensor_bundle,
                    bspl(order=order, max_bracket_span_s=0.040),
                    dt_s=0.05,
                )
            text = str(excinfo.value)
            assert f"at least {order + 1} samples" in text
            assert "has 4" in text
