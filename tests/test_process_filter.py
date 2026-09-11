"""Tests for the migrated per-gate time filter layer — ``process/filter.py``.

Phase 4 coverage transfer: the still-valid numerical/behavioural assertions of
the pre-rework ``filter(series, spec) -> ChannelSeries`` suite are re-expressed
against the closed ``filter(bundle: ChannelBundle, spec: FilterSpec) ->
ChannelBundle`` API. Behaviour under test (per `docs/filter-design.md` §7 and
plan §7.2):

- closed bundle transform (input unmutated, metadata/acquisition carried, a
  fresh validated output) and ``filter_sequence`` = a plain fold;
- per-method behaviour: MEDIAN removes outliers, MEAN averages Gaussian noise,
  SAVGOL smooths without the median's stair-step, TV suppresses noise while
  preserving sharp steps;
- gates filtered independently (no cross-gate coupling);
- heavier TV ``weight`` smooths more;
- cadence rule: MEDIAN/MEAN run on the raw gappy series, TV/SAVGOL need a
  truly uniform cadence and are rejected otherwise (the old
  "ignore the final interval" rule is superseded).

Retired here (the controlled signature switch makes them obsolete): the
``ChannelSeries``-boundary validation tests (window positivity/oddness,
polyorder, non-finite values, zero gates, "too few samples") now belong to the
spec classes and the domain models and are covered in
``tests/test_artifact_filter.py``; the two ``resample`` composition tests used
the legacy ``ChannelSeries`` sync API, whose bundle migration is phase 5.

Comparisons are via ``np.allclose`` / explicit tolerances — never ``==`` on
models carrying arrays.
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
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import (
    MeanFilterSpec,
    MedianFilterSpec,
    SavgolFilterSpec,
    TvFilterSpec,
    filter,
    filter_sequence,
)
from udv_echo_process.provenance import ChannelBundle, source_bundle

DATA = Path("data")
ECHO = DATA / "echo" / "650.BDD"
FOUR_SENSOR = DATA / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ACQ = AcquisitionRef(
    recording_id=recording_id_for(_ASSET_ID),
    source_asset_id=_ASSET_ID,
    channel=ChannelKey(device_channel=4),
)
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")

RNG = np.random.default_rng(0)


def make_bundle(
    t: np.ndarray, v: np.ndarray, gates: int | None = None
) -> ChannelBundle:
    """Synthetic uniform-cadence channel; 1-D values broadcast into ``gates``."""
    if v.ndim == 1:
        n_gates = 1 if gates is None else gates
        v = np.repeat(v[:, None], n_gates, axis=1)
    data = observed_signal(t, np.arange(v.shape[1], dtype=float), v)
    return source_bundle(source_artifact(_ACQ, _ECHO, ChannelConfig(), data))


def values_of(bundle: ChannelBundle) -> np.ndarray:
    """The filtered value matrix of a bundle."""
    return bundle.artifact.data.values


def step_signal(n: int = 200, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """Clean unit step at the midpoint."""
    return np.concatenate([np.full(n // 2, lo), np.full(n - n // 2, hi)])


def total_var(x: np.ndarray) -> float:
    """Discrete 1-D total variation of a time series."""
    return float(np.sum(np.abs(np.diff(x))))


def median_spec(window: int = 5, max_gap_s: float = 1.0) -> MedianFilterSpec:
    return MedianFilterSpec(window=window, max_gap_s=max_gap_s)


def mean_spec(window: int = 5, max_gap_s: float = 1.0) -> MeanFilterSpec:
    return MeanFilterSpec(window=window, max_gap_s=max_gap_s)


def savgol_spec(
    window: int = 9, polyorder: int = 2, max_gap_s: float = 1.0
) -> SavgolFilterSpec:
    return SavgolFilterSpec(window=window, polyorder=polyorder, max_gap_s=max_gap_s)


def tv_spec(weight: float = 0.5, max_gap_s: float = 1.0) -> TvFilterSpec:
    """A TV filter spec — the only method carrying weight/iterations."""
    return TvFilterSpec(weight=weight, iterations=200, max_gap_s=max_gap_s)


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def fixture_bundle(
    path: Path,
    channel: int,
    descriptor: SignalDescriptor,
    *,
    n_channels: int | None = None,
) -> ChannelBundle:
    """TEST ADAPTER: legacy ``MultiplexedMeasurement`` -> source bundle."""
    measurement = load(path)
    if n_channels is not None:
        assert len(measurement.channels) == n_channels
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
    return fixture_bundle(ECHO, 4, _ECHO, n_channels=1)


@pytest.fixture(scope="module")
def gappy_bundle() -> ChannelBundle:
    """A staggered/multiplexed channel (raw, gappy cadence)."""
    return fixture_bundle(FOUR_SENSOR, 6, _VELOCITY, n_channels=4)


# ── per-method behaviour (synthetic) ─────────────────────────────────────


class TestFilter:
    def test_median_removes_outlier_spike_preserves_step(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        f = true.copy()
        f[30] = 5.0  # one outlier spike on the low half
        r = values_of(filter(make_bundle(t, f), median_spec(5)))[:, 0]
        # spike removed back to the (flat) baseline
        assert r[30] == pytest.approx(0.0, abs=1e-9)
        # step preserved (median of the window flips exactly at the edge)
        assert (r[100] - r[99]) > 0.9

    def test_mean_reduces_gaussian_noise(self):
        t = np.linspace(0, 10, 400)
        f = np.full(400, 1.0) + RNG.normal(0, 0.2, 400)
        r = values_of(filter(make_bundle(t, f), mean_spec(9)))[:, 0]
        # boxcar averaging cuts the noise roughly by sqrt(window)
        assert np.std(r - 1.0) < 0.5 * np.std(f - 1.0)

    def test_savgol_smooths_without_median_stair_step(self):
        n = 200
        t = np.linspace(0, 10, n)
        true = 0.5 + 2.0 * (t / t[-1]) ** 2  # smooth parabola
        f = true + RNG.normal(0, 0.15, n)
        bundle = make_bundle(t, f)
        lo, hi = 20, n - 20
        med = values_of(filter(bundle, median_spec(9)))[:, 0][lo:hi]
        sg = values_of(filter(bundle, savgol_spec(9, 2)))[:, 0][lo:hi]
        # both smooth (noise reduced vs the raw signal) …
        assert rmse(sg, true[lo:hi]) < rmse(f[lo:hi], true[lo:hi])
        # … but where the median's order-statistic selection leaves exact flat
        # plateaus (its stair-step), the savgol polynomial fit stays smooth.
        assert np.count_nonzero(np.diff(med) == 0) > 30
        assert np.count_nonzero(np.diff(sg) == 0) < 5

    def test_clean_step_near_identity(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        out = values_of(filter(make_bundle(t, true), tv_spec(1.0)))
        assert np.allclose(out[:, 0], true, atol=0.2)

    def test_noisy_step_noise_reduced_and_edge_kept(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        f = true + RNG.normal(0, 0.2, 200)
        r = values_of(filter(make_bundle(t, f), tv_spec(0.5)))[:, 0]
        # noise suppressed: residual to the true step shrinks materially
        assert np.std(r - true) < 0.55 * np.std(f - true)
        # sharp edge preserved: the jump across the step stays strong
        assert (r[100] - r[99]) > 0.7

    def test_heavier_tv_weight_smooths_more(self):
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        bundle = make_bundle(t, f)
        light = values_of(filter(bundle, tv_spec(0.1)))[:, 0]
        heavy = values_of(filter(bundle, tv_spec(2.0)))[:, 0]
        assert total_var(heavy) < total_var(light)

    def test_gates_filtered_independently(self):
        t = np.linspace(0, 10, 200)
        true = step_signal()
        g_noisy = np.full(200, 5.0) + RNG.normal(0, 0.3, 200)
        bundle = make_bundle(t, np.column_stack([true, g_noisy]))
        out = values_of(filter(bundle, tv_spec(0.5)))
        # clean gate left essentially untouched (no bleed from the noisy gate)
        assert np.allclose(out[:, 0], true, atol=0.2)
        # noisy gate denoised
        assert np.std(out[:, 1] - 5.0) < 0.5 * np.std(g_noisy - 5.0)

    def test_purity_input_unmutated_metadata_carried(self):
        t = np.linspace(0, 10, 100)
        f = step_signal(100) + RNG.normal(0, 0.2, 100)
        bundle = make_bundle(t, f)
        source = bundle.artifact.data
        vals_before = source.values.copy()
        t_before = source.time_s.copy()
        out = filter(bundle, tv_spec(0.5))
        assert out is not bundle
        assert np.array_equal(source.values, vals_before)  # input unmutated
        assert np.array_equal(source.time_s, t_before)
        # identity/metadata are carried through unchanged
        assert out.artifact.acquisition == bundle.artifact.acquisition
        assert out.artifact.descriptor == bundle.artifact.descriptor
        assert out.artifact.config == bundle.artifact.config
        assert np.array_equal(out.artifact.data.time_s, source.time_s)  # same grid
        assert out.artifact.data.values.shape == source.values.shape
        assert not np.shares_memory(out.artifact.data.values, source.values)

    def test_filter_is_reappliable_closed_transform(self):
        # A filter sequence chains: applying the filter to its own output is
        # legal and always yields a valid ChannelBundle on the same grid. TV
        # is *not* exactly idempotent (the first pass is not exactly
        # piecewise-constant, so a second pass continues to smooth a bounded
        # amount); the contract is re-applicability, not a fixed point.
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        spec = tv_spec(0.5)
        u1 = filter(make_bundle(t, f), spec)
        u2 = filter(u1, spec)
        assert isinstance(u2, ChannelBundle)
        assert np.array_equal(u2.artifact.data.time_s, u1.artifact.data.time_s)
        assert u2.artifact.data.values.shape == u1.artifact.data.values.shape
        assert np.isfinite(u2.artifact.data.values).all()
        # continued smoothing is bounded (no divergence / blow-up)
        delta = u2.artifact.data.values[:, 0] - u1.artifact.data.values[:, 0]
        assert float(np.max(np.abs(delta))) < 0.3


# ── filter_sequence (fold) ──────────────────────────────────────────────


class TestFilterSequence:
    def test_sequence_equals_fold(self):
        t = np.linspace(0, 10, 200)
        f = step_signal() + RNG.normal(0, 0.2, 200)
        bundle = make_bundle(t, f)
        specs = [median_spec(3), mean_spec(7)]
        direct = filter_sequence(bundle, specs)
        folded = filter(filter(bundle, specs[0]), specs[1])
        assert np.array_equal(direct.artifact.data.time_s, folded.artifact.data.time_s)
        assert np.allclose(direct.artifact.data.values, folded.artifact.data.values)
        assert len(direct.graph.operations) == 2

    def test_sequence_order_matters(self):
        # A lone spike: removing it first (MEDIAN) lets MEAN just average
        # noise; averaging first (MEAN) smears the spike into a plateau that
        # a small MEDIAN window cannot remove.
        t = np.linspace(0, 10, 200)
        f = step_signal()
        f[30] = 5.0
        bundle = make_bundle(t, f)
        median_first = [median_spec(3), mean_spec(9)]
        mean_first = list(reversed(median_first))
        a = values_of(filter_sequence(bundle, median_first))[:, 0]
        b = values_of(filter_sequence(bundle, mean_first))[:, 0]
        # the signal is a step (1.0 on the high half) with a lone spike on the
        # low half — compare the low half only
        lo, hi = 0, 95
        assert float(np.max(a[lo:hi])) < 0.1
        assert float(np.max(b[lo:hi])) > 0.3


# ── cadence rule + fixtures ──────────────────────────────────────────────


class TestCadenceAndFixtures:
    def test_tv_rejected_on_non_uniform_synthetic(self):
        t = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])  # gap in the middle
        bundle = make_bundle(t, np.ones(6))
        with pytest.raises(ValueError, match="not truly uniform"):
            filter(bundle, tv_spec())

    def test_savgol_rejected_on_non_uniform_synthetic(self):
        t = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])
        bundle = make_bundle(t, np.ones(6))
        with pytest.raises(ValueError, match="not truly uniform"):
            filter(bundle, savgol_spec(3, 1))

    def test_tv_rejected_on_gappy_velocity_fixture(self, gappy_bundle):
        with pytest.raises(ValueError, match="not truly uniform"):
            filter(gappy_bundle, tv_spec())

    def test_index_window_methods_run_on_raw_gappy_fixture(self, gappy_bundle):
        # MEDIAN/MEAN have no uniformity requirement, so they run on the raw
        # gappy series directly (SAVGOL/TV need a uniform cadence).
        for spec in (median_spec(5), mean_spec(5)):
            out = filter(gappy_bundle, spec)
            assert isinstance(out, ChannelBundle)
            assert np.array_equal(
                out.artifact.data.time_s, gappy_bundle.artifact.data.time_s
            )
            assert np.isfinite(out.artifact.data.values).all()

    def test_tv_passes_on_the_echo_fixture_at_the_holding_tolerance(self, echo_bundle):
        # the echo cadence alternates 3.1/3.2 ms (~3.1% spread): only the
        # plan's 5% cap accepts the whole series as truly uniform
        spec = TvFilterSpec(
            weight=1.0, iterations=200, max_gap_s=0.004, uniform_rtol=0.05
        )
        out = filter(echo_bundle, spec)
        assert isinstance(out, ChannelBundle)
        assert np.array_equal(
            out.artifact.data.time_s, echo_bundle.artifact.data.time_s
        )
        assert out.artifact.data.values.shape == echo_bundle.artifact.data.values.shape
        assert np.isfinite(out.artifact.data.values).all()

    def test_tv_passes_per_segment_on_the_gappy_fixture(self, gappy_bundle):
        # max_gap_s=0.040 splits the channel into 100 uniform 4-row segments
        # (0.4% intra-segment jitter), so TV is well defined there
        spec = tv_spec(0.5, max_gap_s=0.040)
        out = filter(gappy_bundle, spec)
        assert isinstance(out, ChannelBundle)
        assert np.array_equal(
            out.artifact.data.time_s, gappy_bundle.artifact.data.time_s
        )
        assert out.artifact.data.values.shape == gappy_bundle.artifact.data.values.shape
        assert np.isfinite(out.artifact.data.values).all()

    def test_filter_raw_then_sequence_on_the_gappy_fixture(self, gappy_bundle):
        # The settled pipeline order (filter-design.md §7.2): smooth /
        # remove outliers on the *measured* samples before interpolating.
        filtered = filter_sequence(gappy_bundle, [median_spec(5, max_gap_s=0.040)])
        assert isinstance(filtered, ChannelBundle)
        assert (
            filtered.artifact.data.values.shape
            == gappy_bundle.artifact.data.values.shape
        )
        assert np.isfinite(filtered.artifact.data.values).all()
        assert len(filtered.graph.operations) == 1
