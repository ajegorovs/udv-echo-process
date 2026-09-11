"""Tests for the migrated Stage 3 resampling layer — ``process/sync.py``.

Phase 5 coverage transfer: the still-valid numerical/behavioural assertions of
the pre-rework ``resample(series, spec, *, times | dt_s) -> ChannelSeries``
suite are re-expressed against the closed ``resample(bundle: ChannelBundle,
spec: InterpSpec, *, times | dt_s) -> ChannelBundle`` API (plan §7.3 and its
ten-row propagation table, §7.4 context). Coverage kept here:

- grid-argument validation (exactly one of ``times`` / ``dt_s``; finite,
  positive ``dt_s`` no larger than the span; finite strictly-increasing
  non-empty ``times``);
- knot round-trip on the committed fixtures (``data/echo/*.BDD`` near-uniform,
  ``data/4-sensor-velocity/*.BDD`` staggered/gappy) for every interpolation
  branch, sampled at the source times so every row is an exact ancestral knot;
- the honest-method regimes: LINEAR/MONOTONE do not overshoot across gaps;
  CUBIC may overshoot a step;
- re-interpolation is legal and idempotent when the second pass reuses the
  first grid;
- the three extrapolation policies;

Retired here (the controlled break makes them obsolete):

- the ``NanPolicy`` suite — ``nan_policy`` is removed; support controls
  validity and MISSING/invalid cells are segment boundaries (§7.1, §14);
- the inclusive ``dt_s`` grid that appended a shortened final interval and the
  ``InterpMethod`` enum/``InterpParams`` bag tests — superseded by ruling D6
  (an exactly uniform grid) and the discriminated union, both covered in
  ``tests/test_artifact_resample.py``;
- the ``ChannelSeries``-boundary source validation (duplicate /
  non-monotonic / non-finite times, "too few samples") — those facts are now
  domain-model invariants of ``SignalData`` and are covered in
  ``tests/test_signal_data.py``.

Comparisons are via ``np.allclose`` — never ``==`` on models carrying arrays.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
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
    resample,
)
from udv_echo_process.provenance import ChannelBundle, source_bundle

DATA = Path("data")
ECHO = DATA / "echo" / "650.BDD"
FOUR_SENSOR = DATA / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")

ALL_SPECS = [
    LinearInterpSpec(extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"),
    MonotoneInterpSpec(
        extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
    ),
    CubicInterpSpec(extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"),
    BsplineInterpSpec(
        extrapolation="error", max_bracket_span_s=1.0, long_gap="missing", order=3
    ),
]
METHOD_IDS = ["linear", "monotone", "cubic", "bspline"]


def make_bundle(
    t: np.ndarray, v: np.ndarray, gates: int | None = None, channel: int = 4
) -> ChannelBundle:
    """Synthetic channel: 1-D values are broadcast into ``gates`` columns."""
    if v.ndim == 1:
        n_gates = 1 if gates is None else gates
        v = np.repeat(v[:, None], n_gates, axis=1)
    data = observed_signal(t, np.arange(v.shape[1], dtype=float), v)
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    return source_bundle(source_artifact(ref, _ECHO, ChannelConfig(), data))


def fixture_bundle(
    path: Path, channel: int, descriptor: SignalDescriptor, *, n_channels: int
) -> ChannelBundle:
    """TEST ADAPTER: legacy ``MultiplexedMeasurement`` -> source bundle."""
    measurement = load(path)
    assert len(measurement.channels) == n_channels
    series = measurement.by_channel()[channel]
    asset_id = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    ref = AcquisitionRef(
        recording_id=recording_id_for(asset_id),
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    data = observed_signal(series.time_s, series.gate_depths_mm, series.values)
    return source_bundle(source_artifact(ref, descriptor, series.config, data))


@pytest.fixture(scope="module")
def echo_bundle() -> ChannelBundle:
    return fixture_bundle(ECHO, 4, _ECHO, n_channels=1)


@pytest.fixture(scope="module")
def gappy_bundle() -> ChannelBundle:
    """A staggered/multiplexed channel (raw, gappy cadence)."""
    return fixture_bundle(FOUR_SENSOR, 6, _VELOCITY, n_channels=4)


# ── grid argument & input validation ─────────────────────────────────────


class TestGridValidation:
    def test_exactly_one_grid_argument(self):
        bundle = make_bundle(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        with pytest.raises(ValueError, match="exactly one"):
            resample(bundle, ALL_SPECS[0])
        with pytest.raises(ValueError, match="exactly one"):
            resample(bundle, ALL_SPECS[0], times=np.array([0.5]), dt_s=0.1)

    def test_bad_dt_s(self):
        bundle = make_bundle(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        for dt in (0.0, -0.1, np.nan, np.inf):
            with pytest.raises(ValueError):
                resample(bundle, ALL_SPECS[0], dt_s=dt)

    def test_dt_s_larger_than_span(self):
        bundle = make_bundle(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        with pytest.raises(ValueError, match="exceeds the source span"):
            resample(bundle, ALL_SPECS[0], dt_s=2.0)

    def test_times_must_be_strictly_increasing_finite_nonempty(self):
        bundle = make_bundle(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        for bad in (
            np.array([0.5, 0.2]),  # decreasing
            np.array([0.5, 0.5]),  # duplicate
            np.array([0.0, np.nan]),
            np.array([]),
        ):
            with pytest.raises(ValueError):
                resample(bundle, ALL_SPECS[0], times=bad)

    def test_accepts_list_times(self):
        bundle = make_bundle(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        out = resample(bundle, ALL_SPECS[0], times=[0.0, 0.5, 1.0])
        assert out.artifact.data.time_s.size == 3

    def test_single_sample_source_extends_by_policy(self):
        # one sample: the domain is a point, so any other target is out of
        # domain and the extrapolation policy decides (never a silent clamp)
        bundle = make_bundle(np.array([0.0]), np.array([5.0]))
        nearest = resample(
            bundle,
            LinearInterpSpec(
                extrapolation="nearest", max_bracket_span_s=1.0, long_gap="missing"
            ),
            times=np.array([-1.0, 0.0, 1.0]),
        ).artifact.data
        assert nearest.values[1, 0] == pytest.approx(5.0)
        assert nearest.values[0, 0] == pytest.approx(5.0)
        assert nearest.values[2, 0] == pytest.approx(5.0)
        assert nearest.support.kind[0, 0] == int(SupportKind.EXTRAPOLATED)


# ── knot round-trip: sampling at source times reproduces values ──────────


class TestKnotRoundTrip:
    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_echo(self, echo_bundle: ChannelBundle, spec: InterpSpec):
        source = echo_bundle.artifact.data
        out = resample(echo_bundle, spec, times=source.time_s).artifact.data
        assert out.time_s.size == source.time_s.size
        assert np.allclose(out.values, source.values, rtol=1e-6, atol=1e-6)
        assert np.array_equal(out.support.kind, source.support.kind)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_gappy_staggered(self, gappy_bundle: ChannelBundle, spec: InterpSpec):
        source = gappy_bundle.artifact.data
        out = resample(gappy_bundle, spec, times=source.time_s).artifact.data
        assert np.allclose(out.values, source.values, rtol=1e-6, atol=1e-6)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_synthetic_two_gates(self, spec: InterpSpec):
        t = np.array([0.0, 0.1, 0.2, 0.3])
        v = np.array([[0.0, 10.0], [1.0, 11.0], [4.0, 14.0], [9.0, 19.0]])
        out = resample(make_bundle(t, v), spec, times=t).artifact.data
        assert np.allclose(out.values, v, atol=1e-9)


# ── overshoot regimes (honest methods across gaps) ───────────────────────


class TestOvershootRegimes:
    def test_linear_never_overshoots_across_gaps(self, gappy_bundle: ChannelBundle):
        # dt_s spans the ~370 ms inter-visit gaps (native cadence ~25 ms); a
        # bracket wider than the worst gap is still interpolated linearly
        source = gappy_bundle.artifact.data
        out = resample(
            gappy_bundle,
            LinearInterpSpec(
                extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
            ),
            dt_s=0.05,
        ).artifact.data
        finite = out.values[np.isfinite(out.values)]
        assert finite.size > 0
        assert finite.min() >= float(source.values.min()) - 1e-9
        assert finite.max() <= float(source.values.max()) + 1e-9

    def test_monotone_stays_in_envelope_on_step(self):
        t = np.arange(6.0)
        v = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        out = resample(
            make_bundle(t, v),
            MonotoneInterpSpec(
                extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
            ),
            dt_s=0.1,
        ).artifact.data
        assert out.values.min() >= -1e-9
        assert out.values.max() <= 10.0 + 1e-9

    def test_cubic_may_overshoot_on_step(self):
        t = np.arange(6.0)
        v = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        out = resample(
            make_bundle(t, v),
            CubicInterpSpec(
                extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
            ),
            dt_s=0.1,
        ).artifact.data
        assert out.values.max() > 10.0  # not-a-knot cubic overshoots the step


# ── idempotency & re-interpolation ───────────────────────────────────────


class TestIdempotency:
    def test_echo_resample_twice_same_grid(self, echo_bundle: ChannelBundle):
        spec = LinearInterpSpec(
            extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
        )
        once = resample(echo_bundle, spec, dt_s=0.0032)
        twice = resample(once, spec, times=once.artifact.data.time_s)
        assert np.allclose(twice.artifact.data.time_s, once.artifact.data.time_s)
        assert np.allclose(
            twice.artifact.data.values, once.artifact.data.values, rtol=1e-6, atol=1e-6
        )

    def test_reinterpolation_is_legal(self, gappy_bundle: ChannelBundle):
        spec = MonotoneInterpSpec(
            extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
        )
        once = resample(gappy_bundle, spec, dt_s=0.1)
        # a resampled ChannelBundle is a valid input to resample again
        twice = resample(once, spec, times=once.artifact.data.time_s)
        assert isinstance(twice, ChannelBundle)
        assert np.allclose(
            twice.artifact.data.values, once.artifact.data.values, rtol=1e-6, atol=1e-6
        )

    def test_reinterpolation_keeps_synthetic_support(self, echo_bundle: ChannelBundle):
        # the dt_s grid reuses whichever source times it lands on exactly (rows
        # that stay OBSERVED); every other row is a synthetic INTERPOLATED knot.
        # Re-sampling at the same times keeps that split and marks the synthetic
        # knots REINTERPOLATED.
        from udv_echo_process.models import QualityFlag, SupportKind

        observed = int(SupportKind.OBSERVED)
        interpolated = int(SupportKind.INTERPOLATED)
        spec = CubicInterpSpec(
            extrapolation="error",
            max_bracket_span_s=1.0,
            long_gap="missing",
            uniform_rtol=0.05,
        )
        once = resample(echo_bundle, spec, dt_s=0.005)
        once_kinds = once.artifact.data.support.kind[:, 0]
        assert (once_kinds == observed).any()  # some grid rows are exact knots
        assert (once_kinds == interpolated).any()
        twice = resample(once, spec, times=once.artifact.data.time_s)
        kinds = twice.artifact.data.support.kind[:, 0]
        quality = twice.artifact.data.support.quality[:, 0]
        exact = once_kinds == observed
        assert np.array_equal(
            kinds[exact], np.full(int(exact.sum()), observed, np.uint8)
        )
        assert np.array_equal(
            kinds[~exact], np.full(int((~exact).sum()), interpolated, np.uint8)
        )
        assert np.array_equal(quality[exact], np.zeros(int(exact.sum()), np.uint32))
        assert (quality[~exact] & int(QualityFlag.REINTERPOLATED)).all()


# ── extrapolation policies ───────────────────────────────────────────────


class TestExtrapolation:
    # four knots so the default-style BSPLINE order 3 (needs >= 4 samples) fits
    T = np.array([0.0, 1.0, 2.0, 3.0])
    V = np.array([0.0, 5.0, 10.0, 15.0])
    OUT = np.array([-1.0, 0.5, 5.0])

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_error_raises_on_any_out_of_range(self, spec: InterpSpec):
        bundle = make_bundle(self.T, self.V)
        with pytest.raises(ValueError, match="extrapolation='error'"):
            resample(bundle, spec, times=self.OUT)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_missing_only_for_out_of_range_rows(self, spec: InterpSpec):
        spec = spec.model_copy(update={"extrapolation": "missing"})
        out = resample(make_bundle(self.T, self.V), spec, times=self.OUT).artifact.data
        assert out.values.shape == (3, 1)
        assert np.isnan(out.values[0, 0])
        assert np.isnan(out.values[2, 0])
        assert out.values[1, 0] == pytest.approx(2.5)

    @pytest.mark.parametrize("spec", ALL_SPECS, ids=METHOD_IDS)
    def test_nearest_clamps_to_edge_values(self, spec: InterpSpec):
        spec = spec.model_copy(update={"extrapolation": "nearest"})
        out = resample(make_bundle(self.T, self.V), spec, times=self.OUT).artifact.data
        assert out.values[0, 0] == pytest.approx(0.0)  # first edge value
        assert out.values[2, 0] == pytest.approx(15.0)  # last edge value
        assert out.values[1, 0] == pytest.approx(2.5)


# ── purity & identity carry-through ──────────────────────────────────────


class TestPurity:
    def test_input_never_mutated_and_output_is_new(self, gappy_bundle: ChannelBundle):
        source = gappy_bundle.artifact.data
        t_before = source.time_s.copy()
        v_before = source.values.copy()
        out = resample(
            gappy_bundle,
            MonotoneInterpSpec(
                extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
            ),
            dt_s=0.1,
        )
        assert np.array_equal(source.time_s, t_before)
        assert np.array_equal(source.values, v_before)
        assert out is not gappy_bundle
        assert out.artifact.data.values is not source.values
        assert out.artifact.data.time_s is not source.time_s

    def test_identity_and_metadata_carried_through(self, gappy_bundle: ChannelBundle):
        out = resample(
            gappy_bundle,
            LinearInterpSpec(
                extrapolation="error", max_bracket_span_s=1.0, long_gap="missing"
            ),
            dt_s=0.1,
        )
        assert out.artifact.acquisition == gappy_bundle.artifact.acquisition
        assert out.artifact.descriptor == gappy_bundle.artifact.descriptor
        assert out.artifact.config == gappy_bundle.artifact.config
        assert np.array_equal(
            out.artifact.data.gate_depths_mm,
            gappy_bundle.artifact.data.gate_depths_mm,
        )
        assert len(out.graph.operations) == 1
        assert out.graph.operations[0].parents == (gappy_bundle.artifact.artifact_id,)
