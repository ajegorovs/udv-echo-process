"""Tests for the RPM analysis module and run_all batch helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from udv_echo_process import extract, rpm_from_echo, setpoint_rpm_from_stem
from udv_echo_process.analysis.temporal_projection import temporal_projections
from udv_echo_process.run_all import collect_results

ROOT = Path(__file__).resolve().parent.parent
SINGLE_RAW = ROOT / "data/echo/650.ADD"


def test_rpm_from_echo_returns_plausible_estimate() -> None:
    d = extract(SINGLE_RAW)
    rpm, peak_freq, n = rpm_from_echo(d, dt_s=0.0032)
    assert n == len(d.frames) == 4630
    assert np.isfinite(rpm)
    assert 0.0 < rpm < 2000.0
    assert peak_freq > 0.0


def test_setpoint_rpm_from_stem() -> None:
    assert setpoint_rpm_from_stem("650") == 650
    assert setpoint_rpm_from_stem("650.ADD") == 650
    assert setpoint_rpm_from_stem("200RPM") == 200
    assert setpoint_rpm_from_stem("200RPM_v2") == 200


def test_setpoint_rpm_from_stem_no_digits() -> None:
    with pytest.raises(ValueError):
        setpoint_rpm_from_stem("RPM")


def test_collect_results_sorted_by_setpoint() -> None:
    paths = [
        ROOT / "data/echo/200.ADD",
        ROOT / "data/echo/650.ADD",
        ROOT / "data/echo/300.ADD",
    ]
    datasets = {p.stem: extract(p) for p in paths}
    results = collect_results(datasets, dt_s=0.0032)
    setpoints = [r.setpoint_rpm for r in results]
    assert setpoints == [200, 300, 650]
    assert all(r.n_samples > 0 for r in results)
    assert all(np.isfinite(r.measured_rpm) for r in results)


def _synthetic_stack(n, h=4, w=5, seed=0):
    rng = np.random.default_rng(seed)
    return rng.random((n, h, w))


def test_temporal_projections_matches_brute_force() -> None:
    stack = _synthetic_stack(n=37)
    res = temporal_projections(list(stack), chunk_size=10)
    expected_min = stack.min(axis=0)
    expected_max = stack.max(axis=0)
    expected_mean = stack.mean(axis=0)
    expected_std = stack.std(axis=0, ddof=1)
    assert res.count == 37
    np.testing.assert_allclose(res.min_array, expected_min, atol=1e-12)
    np.testing.assert_allclose(res.max_array, expected_max, atol=1e-12)
    np.testing.assert_allclose(res.mean_array, expected_mean, atol=1e-12)
    np.testing.assert_allclose(res.std_array, expected_std, atol=1e-12)


def test_temporal_projections_chunk_size_invariant() -> None:
    stack = _synthetic_stack(n=50)
    a = temporal_projections(list(stack), chunk_size=1)
    b = temporal_projections(list(stack), chunk_size=13)
    c = temporal_projections(list(stack), chunk_size=123)
    for res in (a, b, c):
        np.testing.assert_allclose(res.mean_array, a.mean_array, atol=1e-12)
        np.testing.assert_allclose(res.std_array, a.std_array, atol=1e-12)
        np.testing.assert_allclose(res.min_array, a.min_array, atol=1e-12)
        np.testing.assert_allclose(res.max_array, a.max_array, atol=1e-12)


def test_temporal_projections_population_convention() -> None:
    stack = _synthetic_stack(n=8)
    res = temporal_projections(list(stack), convention="population")
    np.testing.assert_allclose(res.std_array, stack.std(axis=0, ddof=0), atol=1e-12)


def test_temporal_projections_get_chunk_loader() -> None:
    stack = _synthetic_stack(n=20)
    def get_chunk(ids):
        return [stack[i] for i in ids]
    res = temporal_projections((get_chunk, 20), chunk_size=6)
    np.testing.assert_allclose(res.mean_array, stack.mean(axis=0), atol=1e-12)
    np.testing.assert_allclose(res.std_array, stack.std(axis=0, ddof=1), atol=1e-12)


def test_temporal_projections_errors() -> None:
    stack = _synthetic_stack(n=5)
    with pytest.raises(ValueError):
        temporal_projections(list(stack), convention="bogus")
    with pytest.raises(ValueError):
        temporal_projections(list(stack), chunk_size=0)
    with pytest.raises(ValueError):
        temporal_projections([])
    with pytest.raises(ValueError):
        temporal_projections((lambda ids: [], 3))
    bad_shapes = [np.zeros((2, 2)), np.zeros((3, 3))]
    with pytest.raises(ValueError):
        temporal_projections(bad_shapes)
