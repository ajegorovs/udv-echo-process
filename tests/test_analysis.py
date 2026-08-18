"""Tests for the RPM analysis module and run_all batch helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from udv_echo_process import extract, rpm_from_echo, setpoint_rpm_from_stem
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
