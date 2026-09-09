"""Tests for the per-gate time filter layer — process/filter.py.

Sequence-capable smoothing/outlier platform (settled 2026-09-09,
`docs/filter-design.md` §7): MEDIAN / MEAN / SAVGOL on scipy + TV (ROF) on
skimage, applied per gate along time. Semantics under test (per
`docs/pipeline-conventions.md` §4 closure rule):

- closed ``filter(series, spec) -> ChannelSeries`` transform (input
  unmutated, metadata carried) and ``filter_sequence`` = a plain fold;
- per-method behaviour: MEDIAN removes outliers, MEAN averages Gaussian
  noise, SAVGOL smooths without the median's stair-step, TV suppresses noise
  while preserving sharp steps;
- gates filtered independently (no cross-gate coupling);
- heavier TV ``weight`` smooths more;
- cadence rule: index-window methods run on the raw gappy series, TV needs
  uniform cadence (post-``resample``) and is rejected otherwise;
- validation: too few samples / no gates / non-finite values rejected,
  SAVGOL window must be odd and exceed polyorder;
- composition with the interpolation stage, in the settled order
  (filter raw → resample) on the 4-sensor fixture.

Comparisons are via ``np.allclose`` / explicit tolerances — never ``==`` on
models carrying arrays (interpolation-design.md §6.2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process import (
    ChannelSeries,
    FilterMethod,
    FilterParams,
    FilterSpec,
    MeasType,
    filter,
    filter_sequence,
)
from udv_echo_process.io import load
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.process import InterpSpec, resample

DATA = Path("data")
ECHO = DATA / "echo" / "650.BDD"
FOUR_SENSOR = DATA / "4-sensor-velocity" / "200RPM.BDD"

RNG = np.random.default_rng(0)


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


def step_signal(n: int = 200, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """Clean unit step at the midpoint."""
    return np.concatenate([np.full(n // 2, lo), np.full(n - n // 2, hi)])


def total_var(x: np.ndarray) -> float:
    """Discrete 1-D total variation of a time series."""
    return float(np.sum(np.abs(np.diff(x))))


def tv_spec(weight: float = 0.5) -> FilterSpec:
    """A TV filter spec — the only method carrying weight/iterations."""
    return FilterSpec(method=FilterMethod.TV, params=FilterParams(weight=weight))


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


@pytest.fixture(scope="module")
def echo_series() -> ChannelSeries:
    m = load(ECHO)
    assert len(m.channels) == 1
    return m.channels[0]


@pytest.fixture(scope="module")
def gappy_series() -> ChannelSeries:
    """A staggered/multiplexed channel (raw, gappy cadence)."""
    m = load(FOUR_SENSOR)
    assert len(m.channels) == 4
    return m.channels[0]


# ── spec validation ─────────────────────────────────────────────────────


class TestFilterSpecValidation:
    def test_defaults(self):
        spec = FilterSpec()
        assert spec.method is FilterMethod.MEDIAN
        assert spec.params.window == 5
        assert spec.params.polyorder == 2
        assert spec.params.weight == 1.0
        assert spec.params.iterations == 200

    def test_window_must_be_positive(self):
        for bad in (0, -3):
            with pytest.raises(ValidationError):
                FilterParams(window=bad)

    def test_polyorder_must_be_nonnegative(self):
        with pytest.raises(ValidationError):
            FilterParams(polyorder=-1)

    def test_weight_must_be_positive(self):
        for bad in (0.0, -0.1):
            with pytest.raises(ValidationError):
                FilterParams(weight=bad)

    def test_iterations_must_be_positive(self):
        with pytest.raises(ValidationError):
            FilterParams(iterations=0)


# ── per-method behaviour (synthetic) ─────────────────────────────────────


class TestFilter:
    def test_median_removes_outlier_spike_preserves_step(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        f = true.copy()
        f[30] = 5.0  # one outlier spike on the low half
        out = filter(
            make_series(t, f),
            FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=5)),
        )
        r = out.values[:, 0]
        # spike removed back to the (flat) baseline
        assert r[30] == pytest.approx(0.0, abs=1e-9)
        # step preserved (median of the window flips exactly at the edge)
        assert (r[100] - r[99]) > 0.9

    def test_mean_reduces_gaussian_noise(self):
        t = np.linspace(0, 10, 400)
        f = np.full(400, 1.0) + RNG.normal(0, 0.2, 400)
        out = filter(
            make_series(t, f),
            FilterSpec(method=FilterMethod.MEAN, params=FilterParams(window=9)),
        )
        r = out.values[:, 0]
        # boxcar averaging cuts the noise roughly by sqrt(window)
        assert np.std(r - 1.0) < 0.5 * np.std(f - 1.0)

    def test_savgol_smooths_without_median_stair_step(self):
        n = 200
        t = np.linspace(0, 10, n)
        true = 0.5 + 2.0 * (t / t[-1]) ** 2  # smooth parabola
        f = true + RNG.normal(0, 0.15, n)
        s = make_series(t, f)
        lo, hi = 20, n - 20
        med = filter(
            s, FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=9))
        ).values[:, 0][lo:hi]
        sg = filter(
            s,
            FilterSpec(
                method=FilterMethod.SAVGOL,
                params=FilterParams(window=9, polyorder=2),
            ),
        ).values[:, 0][lo:hi]
        # both smooth (noise reduced vs the raw signal) …
        assert rmse(sg, true[lo:hi]) < rmse(f[lo:hi], true[lo:hi])
        # … but where the median's order-statistic selection leaves exact flat
        # plateaus (its stair-step), the savgol polynomial fit stays smooth.
        assert np.count_nonzero(np.diff(med) == 0) > 30
        assert np.count_nonzero(np.diff(sg) == 0) < 5

    def test_clean_step_near_identity(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        out = filter(make_series(t, true), tv_spec(weight=1.0))
        assert np.allclose(out.values[:, 0], true, atol=0.2)

    def test_noisy_step_noise_reduced_and_edge_kept(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        f = true + RNG.normal(0, 0.2, 200)
        out = filter(make_series(t, f), tv_spec(weight=0.5))
        r = out.values[:, 0]
        # noise suppressed: residual to the true step shrinks materially
        assert np.std(r - true) < 0.55 * np.std(f - true)
        # sharp edge preserved: the jump across the step stays strong
        assert (r[100] - r[99]) > 0.7

    def test_heavier_tv_weight_smooths_more(self):
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        s = make_series(t, f)
        light = filter(s, tv_spec(weight=0.1)).values[:, 0]
        heavy = filter(s, tv_spec(weight=2.0)).values[:, 0]
        assert total_var(heavy) < total_var(light)

    def test_gates_filtered_independently(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        g_clean = true
        g_noisy = np.full(200, 5.0) + RNG.normal(0, 0.3, 200)
        out = filter(
            make_series(t, np.column_stack([g_clean, g_noisy])), tv_spec(weight=0.5)
        )
        # clean gate left essentially untouched (no bleed from the noisy gate)
        assert np.allclose(out.values[:, 0], true, atol=0.2)
        # noisy gate denoised
        assert np.std(out.values[:, 1] - 5.0) < 0.5 * np.std(g_noisy - 5.0)

    def test_purity_input_unmutated_metadata_carried(self):
        t = np.linspace(0, 10, 100)
        f = step_signal(100) + RNG.normal(0, 0.2, 100)
        s = make_series(t, f)
        s.config = ChannelConfig()
        vals_before = s.values.copy()
        t_before = s.time_s.copy()
        out = filter(s, tv_spec(weight=0.5))
        assert out is not s
        assert np.array_equal(s.values, vals_before)  # input unmutated
        assert np.array_equal(s.time_s, t_before)
        assert out.channel == s.channel
        assert out.meas_type == s.meas_type
        assert out.gate_depths_mm == s.gate_depths_mm
        assert not np.shares_memory(out.config, s.config)  # deep-copied config
        assert np.array_equal(out.time_s, s.time_s)  # same grid
        assert out.values.shape == s.values.shape

    def test_filter_is_reappliable_closed_transform(self):
        # Closure rule (`pipeline-conventions.md` §4): a filter sequence
        # chains — applying the filter to its own output is legal and always
        # yields a valid ChannelSeries on the same grid. TV is *not* exactly
        # idempotent (the first pass is not exactly piecewise-constant, so a
        # second pass continues to smooth a bounded amount); the contract is
        # re-applicability, not a fixed point.
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        spec = tv_spec(weight=0.5)
        u1 = filter(make_series(t, f), spec)
        u2 = filter(u1, spec)
        assert isinstance(u2, ChannelSeries)
        assert np.array_equal(u2.time_s, u1.time_s)
        assert u2.values.shape == u1.values.shape
        assert np.isfinite(u2.values).all()
        # continued smoothing is bounded (no divergence / blow-up)
        assert float(np.max(np.abs(u2.values[:, 0] - u1.values[:, 0]))) < 0.3


# ── filter_sequence (fold) ──────────────────────────────────────────────


class TestFilterSequence:
    def test_sequence_equals_fold(self):
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        s = make_series(t, f)
        specs = [
            FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=3)),
            FilterSpec(method=FilterMethod.MEAN, params=FilterParams(window=7)),
        ]
        direct = filter_sequence(s, specs)
        folded = filter(filter(s, specs[0]), specs[1])
        assert np.array_equal(direct.time_s, folded.time_s)
        assert np.allclose(direct.values, folded.values)

    def test_sequence_order_matters(self):
        # A lone spike: removing it first (MEDIAN) lets MEAN just average
        # noise; averaging first (MEAN) smears the spike into a plateau that
        # a small MEDIAN window cannot remove.
        t = np.linspace(0, 10, 200)
        f = step_signal()
        f[30] = 5.0
        s = make_series(t, f)
        median_first = [
            FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=3)),
            FilterSpec(method=FilterMethod.MEAN, params=FilterParams(window=9)),
        ]
        mean_first = list(reversed(median_first))
        a = filter_sequence(s, median_first).values[:, 0]
        b = filter_sequence(s, mean_first).values[:, 0]
        # the signal is a step (1.0 on the high half) with a lone spike on the
        # low half — compare the low half only
        lo, hi = 0, 95
        assert float(np.max(a[lo:hi])) < 0.1
        assert float(np.max(b[lo:hi])) > 0.3


# ── validation ───────────────────────────────────────────────────────────


class TestFilterValidation:
    def test_too_few_samples_rejected(self):
        s = make_series(np.array([0.0]), np.array([0.0]))
        with pytest.raises(ValueError, match="at least two"):
            filter(s, FilterSpec())

    def test_nonfinite_values_rejected(self):
        s = make_series(np.array([0.0, 1.0, 2.0]), np.array([0.0, np.nan, 2.0]))
        with pytest.raises(ValueError, match="non-finite"):
            filter(s, FilterSpec())

    def test_no_gates_rejected(self):
        s = ChannelSeries(
            channel=4,
            meas_type=MeasType.ECHO,
            gate_depths_mm=[],
            time_s=np.array([0.0, 1.0, 2.0]),
            values=np.empty((3, 0)),
        )
        with pytest.raises(ValueError, match="no gates"):
            filter(s, FilterSpec())

    def test_savgol_window_must_exceed_polyorder(self):
        s = make_series(np.linspace(0, 1, 50), np.ones(50))
        spec = FilterSpec(
            method=FilterMethod.SAVGOL,
            params=FilterParams(window=3, polyorder=3),
        )
        with pytest.raises(ValueError, match="must exceed polyorder"):
            filter(s, spec)

    def test_savgol_window_must_be_odd(self):
        s = make_series(np.linspace(0, 1, 50), np.ones(50))
        spec = FilterSpec(
            method=FilterMethod.SAVGOL,
            params=FilterParams(window=4, polyorder=2),
        )
        with pytest.raises(ValueError, match="must be odd"):
            filter(s, spec)

    def test_tv_rejected_on_non_uniform_synthetic(self):
        t = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])  # gap in the middle
        s = make_series(t, np.ones(6))
        with pytest.raises(ValueError, match="uniform cadence"):
            filter(s, tv_spec())


# ── cadence rule + fixtures ──────────────────────────────────────────────


class TestCadenceAndFixtures:
    def test_tv_rejected_on_gappy_velocity_fixture(self, gappy_series):
        with pytest.raises(ValueError, match="uniform cadence"):
            filter(gappy_series, tv_spec())

    def test_index_window_methods_run_on_raw_gappy_fixture(self, gappy_series):
        specs = [
            FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=5)),
            FilterSpec(method=FilterMethod.MEAN, params=FilterParams(window=5)),
            FilterSpec(method=FilterMethod.SAVGOL, params=FilterParams(window=5)),
        ]
        for spec in specs:
            out = filter(gappy_series, spec)
            assert isinstance(out, ChannelSeries)
            assert np.array_equal(out.time_s, gappy_series.time_s)
            assert np.isfinite(out.values).all()

    def test_tv_passes_on_uniform_echo_fixture(self, echo_series):
        out = filter(echo_series, tv_spec(weight=1.0))
        assert isinstance(out, ChannelSeries)
        assert np.array_equal(out.time_s, echo_series.time_s)
        assert out.values.shape == echo_series.values.shape
        assert np.isfinite(out.values).all()

    def test_tv_passes_after_resample_on_gappy_fixture(self, gappy_series):
        dt = float(np.median(np.diff(gappy_series.time_s)))
        resampled = resample(gappy_series, InterpSpec(), dt_s=dt)
        out = filter(resampled, tv_spec(weight=0.5))
        assert isinstance(out, ChannelSeries)
        assert np.array_equal(out.time_s, resampled.time_s)
        assert np.isfinite(out.values).all()
        assert out.values.shape == resampled.values.shape

    def test_filter_raw_then_resample_on_gappy_fixture(self, gappy_series):
        # The settled pipeline order (filter-design.md §7.2): smooth /
        # remove outliers on the *measured* samples, then interpolate.
        filtered = filter_sequence(
            gappy_series,
            [FilterSpec(method=FilterMethod.MEDIAN, params=FilterParams(window=5))],
        )
        dt = float(np.median(np.diff(gappy_series.time_s)))
        resampled = resample(filtered, InterpSpec(), dt_s=dt)
        assert isinstance(resampled, ChannelSeries)
        assert resampled.time_s[0] == filtered.time_s[0]
        assert resampled.time_s[-1] == filtered.time_s[-1]
        assert np.isfinite(resampled.values).all()
        # resample fills the span at the intra-visit cadence, so the uniform
        # grid holds more rows than the gappy source — the gate axis is what
        # must be preserved through filter → resample
        assert resampled.values.shape[1] == filtered.values.shape[1]
        assert resampled.time_count > filtered.time_count
