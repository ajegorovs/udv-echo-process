"""Tests for the Stage 3 interpolation layer — process/sync.py.

Covers `docs/interpolation-design.md` §7/§8 semantics: the closed
``resample(series, spec, *, times | dt_s) -> ChannelSeries`` transform,
knot round-trip on the committed fixtures (`data/echo/*.BDD` uniform,
`data/4-sensor-velocity/*.BDD` staggered/gappy), the LINEAR no-overshoot
contract, extrapolation policies, NaN policy, grid semantics and
non-mutation.

Comparisons are via ``np.allclose`` — never ``==`` on models carrying arrays
(interpolation-design.md §6.2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process import ChannelSeries, MeasType
from udv_echo_process.io import load
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.process import InterpMethod, InterpParams, InterpSpec, resample

DATA = Path("data")
ECHO = DATA / "echo" / "650.BDD"
FOUR_SENSOR = DATA / "4-sensor-velocity" / "200RPM.BDD"

ALL_METHODS = [
    InterpMethod.LINEAR,
    InterpMethod.MONOTONE,
    InterpMethod.CUBIC,
    InterpMethod.BSPLINE,
]


def make_series(
    t: np.ndarray, v: np.ndarray, gates: int | None = None, channel: int = 4
) -> ChannelSeries:
    """Synthetic channel: 1-D values are broadcast into `gates` columns."""
    if v.ndim == 1:
        n_gates = 1 if gates is None else gates
        v = np.repeat(v[:, None], n_gates, axis=1)
    return ChannelSeries(
        channel=channel,
        meas_type=MeasType.ECHO,
        gate_depths_mm=[float(g) for g in range(v.shape[1])],
        time_s=np.asarray(t, dtype=float),
        values=np.asarray(v, dtype=float),
    )


@pytest.fixture(scope="module")
def echo_series() -> ChannelSeries:
    m = load(ECHO)
    assert len(m.channels) == 1
    return m.channels[0]


@pytest.fixture(scope="module")
def gappy_series() -> ChannelSeries:
    """A staggered/multiplexed channel: bursts of ~25 ms at ~448 ms revisit."""
    m = load(FOUR_SENSOR)
    assert len(m.channels) == 4
    return m.channels[0]


# ── grid argument & input validation ────────────────────────────────────


class TestGridValidation:
    def test_neither_nor_both_grid_args(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        with pytest.raises(ValueError, match="exactly one"):
            resample(s, InterpSpec())
        with pytest.raises(ValueError, match="exactly one"):
            resample(s, InterpSpec(), times=np.array([0.5]), dt_s=0.1)

    def test_bad_dt_s(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        for dt in (0.0, -0.1, np.nan, np.inf):
            with pytest.raises(ValueError):
                resample(s, InterpSpec(), dt_s=dt)

    def test_dt_s_larger_than_span(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        with pytest.raises(ValueError, match="exceeds the series span"):
            resample(s, InterpSpec(), dt_s=2.0)

    def test_times_must_be_strictly_increasing_finite_nonempty(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        for bad in (
            np.array([0.5, 0.2]),  # decreasing
            np.array([0.5, 0.5]),  # duplicate
            np.array([0.0, np.nan]),
            np.array([]),
        ):
            with pytest.raises(ValueError):
                resample(s, InterpSpec(), times=bad)

    def test_accepts_list_times(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        out = resample(s, InterpSpec(), times=[0.0, 0.5, 1.0])
        assert out.time_count == 3

    def test_source_duplicate_knots_rejected_every_method(self):
        s = make_series(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 2.0]))
        for m in ALL_METHODS:
            with pytest.raises(ValueError, match="strictly increasing"):
                resample(s, InterpSpec(method=m), dt_s=0.1)

    def test_source_nonfinite_time_rejected(self):
        s = make_series(np.array([0.0, np.nan, 1.0]), np.array([0.0, 1.0, 2.0]))
        with pytest.raises(ValueError, match="not finite"):
            resample(s, InterpSpec(), dt_s=0.1)

    def test_too_few_samples_rejected(self):
        s = make_series(np.array([0.0]), np.array([0.0]))
        with pytest.raises(ValueError, match="at least two"):
            resample(s, InterpSpec(), dt_s=0.1)

    def test_bspline_order_capacity(self):
        s = make_series(np.array([0.0, 1.0, 2.0]), np.array([0.0, 1.0, 2.0]))
        with pytest.raises(ValueError, match="needs at least 4 samples"):
            resample(s, InterpSpec(method=InterpMethod.BSPLINE), dt_s=0.5)

    def test_spline_order_must_be_positive(self):
        with pytest.raises(ValidationError):
            InterpSpec(method=InterpMethod.BSPLINE, params=InterpParams(spline_order=0))

    def test_method_is_constrained_enum(self):
        assert InterpMethod.LINEAR.value == "linear"
        assert InterpMethod.MONOTONE.value == "monotone"
        assert InterpSpec().method is InterpMethod.LINEAR  # default


# ── knot round-trip: sampling at the source times reproduces values ─────


class TestKnotRoundTrip:
    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_echo_uniform(self, echo_series: ChannelSeries, method: InterpMethod):
        out = resample(echo_series, InterpSpec(method=method), times=echo_series.time_s)
        assert out.time_count == echo_series.time_count
        assert np.allclose(out.values, echo_series.values, rtol=1e-6, atol=1e-6)

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_gappy_staggered(self, gappy_series: ChannelSeries, method: InterpMethod):
        out = resample(
            gappy_series, InterpSpec(method=method), times=gappy_series.time_s
        )
        assert np.allclose(out.values, gappy_series.values, rtol=1e-6, atol=1e-6)

    def test_synthetic_two_gates(self):
        t = np.array([0.0, 0.1, 0.2, 0.3])
        v = np.array([[0.0, 10.0], [1.0, 11.0], [4.0, 14.0], [9.0, 19.0]])
        for m in ALL_METHODS:
            out = resample(make_series(t, v), InterpSpec(method=m), times=t)
            assert np.allclose(out.values, v, atol=1e-9)


# ── overshoot regimes (honest methods across gaps) ──────────────────────


class TestOvershootRegimes:
    def test_linear_never_overshoots_across_gaps(self, gappy_series: ChannelSeries):
        # dt_s spans the ~370 ms inter-visit gaps (native cadence ~25 ms)
        out = resample(gappy_series, InterpSpec(method=InterpMethod.LINEAR), dt_s=0.05)
        env_min = float(gappy_series.values.min())
        env_max = float(gappy_series.values.max())
        assert out.values.min() >= env_min - 1e-9
        assert out.values.max() <= env_max + 1e-9

    def test_monotone_stays_in_envelope_on_step(self):
        t = np.arange(6.0)
        v = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        out = resample(
            make_series(t, v), InterpSpec(method=InterpMethod.MONOTONE), dt_s=0.1
        )
        assert out.values.min() >= -1e-9
        assert out.values.max() <= 10.0 + 1e-9

    def test_cubic_may_overshoot_on_step(self):
        t = np.arange(6.0)
        v = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        out = resample(
            make_series(t, v), InterpSpec(method=InterpMethod.CUBIC), dt_s=0.1
        )
        assert out.values.max() > 10.0  # not-a-knot cubic overshoots the step


# ── uniform-echo idempotency & re-interpolation ─────────────────────────


class TestIdempotency:
    def test_echo_resample_twice_same_grid(self, echo_series: ChannelSeries):
        spec = InterpSpec(method=InterpMethod.LINEAR)
        once = resample(echo_series, spec, dt_s=0.0032)
        twice = resample(once, spec, dt_s=0.0032)
        assert np.allclose(twice.time_s, once.time_s)
        assert np.allclose(twice.values, once.values, rtol=1e-6, atol=1e-6)

    def test_dt_grid_inclusive_span_short_final_interval(self):
        s = make_series(np.array([0.0, 1.0]), np.array([0.0, 10.0]))
        out = resample(s, InterpSpec(), dt_s=0.3)
        assert out.time_s[0] == 0.0
        assert out.time_s[-1] == pytest.approx(1.0)
        # shortened final interval keeps the last sample at the series end
        assert np.allclose(out.values[:, 0], [0.0, 3.0, 6.0, 9.0, 10.0])

    def test_reinterpolation_is_legal(self, gappy_series: ChannelSeries):
        spec = InterpSpec(method=InterpMethod.MONOTONE)
        once = resample(gappy_series, spec, dt_s=0.1)
        # a resampled ChannelSeries is a valid input to resample again
        twice = resample(once, spec, dt_s=0.1)
        assert isinstance(twice, ChannelSeries)
        assert np.allclose(twice.values, once.values, rtol=1e-6, atol=1e-6)


# ── extrapolation policies ───────────────────────────────────────────────


class TestExtrapolation:
    # 4 knots so the default BSPLINE order 3 (needs >= 4 samples) is usable
    S = make_series(np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.0, 5.0, 10.0, 15.0]))

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_error_raises_on_any_out_of_range(self, method: InterpMethod):
        with pytest.raises(ValueError, match="outside the source span"):
            resample(self.S, InterpSpec(method=method), times=np.array([-1.0, 1.0]))

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_nan_only_for_out_of_range_rows(self, method: InterpMethod):
        out = resample(
            self.S,
            InterpSpec(method=method, extrapolation="nan"),
            times=np.array([-1.0, 0.5, 5.0]),
        )
        assert out.values.shape == (3, 1)
        assert np.isnan(out.values[0, 0])
        assert np.isnan(out.values[2, 0])
        assert out.values[1, 0] == pytest.approx(2.5)

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_nearest_clamps_to_edge_values(self, method: InterpMethod):
        out = resample(
            self.S,
            InterpSpec(method=method, extrapolation="nearest"),
            times=np.array([-1.0, 0.5, 5.0]),
        )
        assert out.values[0, 0] == pytest.approx(0.0)  # first edge value
        assert out.values[2, 0] == pytest.approx(15.0)  # last edge value
        assert out.values[1, 0] == pytest.approx(2.5)


# ── NaN policy ───────────────────────────────────────────────────────────


class TestNanPolicy:
    TN = np.array([0.0, 1.0, 2.0])
    VN = np.array([0.0, np.nan, 2.0])

    def test_error_policy_rejects_nan_source(self):
        s = make_series(self.TN, self.VN)
        with pytest.raises(ValueError, match="nan_policy='error'"):
            resample(s, InterpSpec(), times=self.TN)

    def test_propagate_carries_nan_through_linear(self):
        s = make_series(self.TN, self.VN)
        out = resample(s, InterpSpec(nan_policy="propagate"), times=self.TN)
        assert out.values[0, 0] == pytest.approx(0.0)
        assert np.isnan(out.values[1, 0])
        assert out.values[2, 0] == pytest.approx(2.0)

    def test_propagate_with_spline_raises_clear_error(self):
        s = make_series(self.TN, self.VN)
        for method in (InterpMethod.MONOTONE, InterpMethod.CUBIC, InterpMethod.BSPLINE):
            with pytest.raises(ValueError, match="only defined for LINEAR"):
                resample(
                    s, InterpSpec(method=method, nan_policy="propagate"), times=self.TN
                )

    def test_propagate_with_spline_finite_data_is_fine(self):
        s = make_series(self.TN, np.array([0.0, 5.0, 10.0]))
        out = resample(
            s,
            InterpSpec(method=InterpMethod.MONOTONE, nan_policy="propagate"),
            times=np.array([0.5, 1.5]),
        )
        assert np.allclose(out.values[:, 0], [2.5, 7.5], atol=1e-6)


# ── non-mutation & identity carry-through ───────────────────────────────


class TestPurity:
    def test_input_never_mutated_and_output_is_new(self, gappy_series: ChannelSeries):
        t_before = gappy_series.time_s.copy()
        v_before = gappy_series.values.copy()
        out = resample(gappy_series, InterpSpec(method=InterpMethod.MONOTONE), dt_s=0.1)
        assert np.array_equal(gappy_series.time_s, t_before)
        assert np.array_equal(gappy_series.values, v_before)
        assert out is not gappy_series
        assert out.values is not gappy_series.values
        assert out.time_s is not gappy_series.time_s

    def test_identity_carried_through(self, gappy_series: ChannelSeries):
        cfg = ChannelConfig(sound_speed_ms=2740.0, n_gates=gappy_series.gate_count)
        s = gappy_series.model_copy(update={"config": cfg})
        out = resample(s, InterpSpec(), dt_s=0.1)
        assert out.channel == s.channel
        assert out.meas_type is s.meas_type
        assert out.gate_depths_mm == s.gate_depths_mm
        assert out.config == cfg

    def test_output_revalidates_as_channel_series(self, echo_series: ChannelSeries):
        out = resample(echo_series, InterpSpec(method=InterpMethod.CUBIC), dt_s=0.005)
        # re-construction with the T2 checks would raise if shapes were off
        ChannelSeries.model_validate(out)
        assert out.values.shape == (out.time_count, out.gate_count)
