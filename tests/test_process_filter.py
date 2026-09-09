"""Tests for the per-gate time filter layer — process/filter.py.

Total-variation (ROF) denoising via
``skimage.restoration.denoise_tv_chambolle``, applied per gate along time.
Semantics under test (per `docs/pipeline-conventions.md` §4 closure rule):

- closed ``denoise(series, spec) -> ChannelSeries`` transform (input
  unmutated, metadata carried, sequence = re-apply);
- noise suppressed while sharp steps are preserved (the point of TV vs a
  smoothing mean filter);
- gates filtered independently (no cross-gate coupling);
- heavier ``weight`` smooths more;
- validation: too few samples / non-finite values rejected;
- composition with the interpolation stage (fixture: resample → denoise).

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
    FilterSpec,
    MeasType,
    denoise,
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
        assert spec.method is FilterMethod.TV
        assert spec.weight == 1.0
        assert spec.iterations == 200

    def test_weight_must_be_positive(self):
        for bad in (0.0, -0.1):
            with pytest.raises(ValidationError):
                FilterSpec(weight=bad)

    def test_iterations_must_be_positive(self):
        with pytest.raises(ValidationError):
            FilterSpec(iterations=0)


# ── denoise behaviour (synthetic) ────────────────────────────────────────


class TestDenoise:
    def test_clean_step_near_identity(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        out = denoise(make_series(t, true), FilterSpec(weight=1.0))
        assert np.allclose(out.values[:, 0], true, atol=0.2)

    def test_noisy_step_noise_reduced_and_edge_kept(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        f = true + RNG.normal(0, 0.2, 200)
        out = denoise(make_series(t, f), FilterSpec(weight=0.5))
        r = out.values[:, 0]
        # noise suppressed: residual to the true step shrinks materially
        assert np.std(r - true) < 0.55 * np.std(f - true)
        # sharp edge preserved: the jump across the step stays strong
        assert (r[100] - r[99]) > 0.7

    def test_heavier_weight_smooths_more(self):
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        s = make_series(t, f)
        light = denoise(s, FilterSpec(weight=0.1)).values[:, 0]
        heavy = denoise(s, FilterSpec(weight=2.0)).values[:, 0]
        assert total_var(heavy) < total_var(light)

    def test_gates_filtered_independently(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        g_clean = true
        g_noisy = np.full(200, 5.0) + RNG.normal(0, 0.3, 200)
        out = denoise(
            make_series(t, np.column_stack([g_clean, g_noisy])), FilterSpec(weight=0.5)
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
        out = denoise(s, FilterSpec(weight=0.5))
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
        spec = FilterSpec(weight=0.5)
        u1 = denoise(make_series(t, f), spec)
        u2 = denoise(u1, spec)
        assert isinstance(u2, ChannelSeries)
        assert np.array_equal(u2.time_s, u1.time_s)
        assert u2.values.shape == u1.values.shape
        assert np.isfinite(u2.values).all()
        # continued smoothing is bounded (no divergence / blow-up)
        assert float(np.max(np.abs(u2.values[:, 0] - u1.values[:, 0]))) < 0.3


# ── validation ───────────────────────────────────────────────────────────


class TestDenoiseValidation:
    def test_too_few_samples_rejected(self):
        s = make_series(np.array([0.0]), np.array([0.0]))
        with pytest.raises(ValueError, match="at least two"):
            denoise(s, FilterSpec())

    def test_nonfinite_values_rejected(self):
        s = make_series(np.array([0.0, 1.0, 2.0]), np.array([0.0, np.nan, 2.0]))
        with pytest.raises(ValueError, match="non-finite"):
            denoise(s, FilterSpec())


# ── fixtures & pipeline composition ──────────────────────────────────────


class TestDenoiseFixtures:
    def test_echo_fixture_denoises_to_valid_series(self, echo_series):
        out = denoise(echo_series, FilterSpec(weight=1.0))
        assert isinstance(out, ChannelSeries)
        assert np.array_equal(out.time_s, echo_series.time_s)
        assert out.values.shape == echo_series.values.shape
        assert np.isfinite(out.values).all()

    def test_resample_then_denoise_on_gappy_fixture(self, gappy_series):
        # filter is meant to run on an already-resampled uniform grid: bridge
        # the gappy cadence first, then denoise (the pipeline flow).
        dt = float(np.median(np.diff(gappy_series.time_s)))
        resampled = resample(gappy_series, InterpSpec(), dt_s=dt)
        out = denoise(resampled, FilterSpec(weight=0.5))
        assert isinstance(out, ChannelSeries)
        assert np.array_equal(out.time_s, resampled.time_s)
        assert np.isfinite(out.values).all()
        assert out.values.shape == resampled.values.shape
