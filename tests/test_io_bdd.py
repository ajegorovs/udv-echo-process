"""Tests for the DOP3000 .BDD binary reader and the io load/discover layer.

Uses the committed fixtures in `data/`:
- `data/echo/*.BDD` — single-channel echo (DOP3000, `BINUDOPV4.03.4`).
- `data/4-sensor-velocity/*.BDD` — 4-channel velocity, rolling multiplex.
- `data/echo-4-sensors-2x2/20260723_143754.jpg` — a genuine .BDD misnamed
  `.jpg` (magic still matches), exercising content-based discovery.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.io import discover_data_files, load
from udv_echo_process.io.dop.bdd import read, sniff_bdd
from udv_echo_process.models import MeasType, MultiplexedMeasurement

DATA = Path("data")
ECHO = DATA / "echo"
VEL = DATA / "4-sensor-velocity"
TWOBYTWO = DATA / "echo-4-sensors-2x2"


# ── sniff ──────────────────────────────────────────────────────────────


class TestSniff:
    def test_recognizes_binudopv(self):
        assert sniff_bdd(b"BINUDOPV4.03.4\r\n...") is True

    def test_rejects_foreign_bytes(self):
        assert sniff_bdd(b"\x89PNG\r\n\x1a\n") is False

    def test_rejects_dop2000(self):
        with pytest.raises(ValueError):
            sniff_bdd(b"BINWDOPV...")


# ── single-channel echo ────────────────────────────────────────────────


class TestSingleChannel:
    def test_loads_echo_fixture(self):
        assert (ECHO / "200.BDD").is_file()
        m = read(ECHO / "200.BDD")
        assert isinstance(m, MultiplexedMeasurement)
        assert len(m.channels) == 1
        c = m.channels[0]
        assert c.meas_type == MeasType.ECHO
        assert c.values.shape == (c.time_count, c.gate_count)
        assert c.time_count == 4180  # matches DOPpy observation
        assert c.gate_count == 26
        assert c.gate_depths_mm[0] == pytest.approx(43.0, abs=0.1)
        assert c.config.module_scale == 2048
        assert c.config.sound_speed_ms == pytest.approx(2740, abs=1)

    def test_time_increasing(self):
        m = read(ECHO / "650.BDD")
        c = m.channels[0]
        assert np.all(np.diff(c.time_s) >= 0)


# ── multiplexed rolling velocity ───────────────────────────────────────


class TestMultiplexed:
    def test_four_channels_velocity(self):
        m = read(VEL / "200RPM.BDD")
        assert len(m.channels) == 4
        for c in m.channels:
            assert c.meas_type == MeasType.VELOCITY
            assert c.values.shape == (c.time_count, c.gate_count)
            assert c.gate_count == 55
        ts = [c.time_s[0] for c in m.channels]
        assert ts[0] == pytest.approx(0.0, abs=1e-3)
        for a, b in itertools.pairwise(ts):
            assert (b - a) > 0.05  # staggered start times

    def test_each_channel_has_config(self):
        m = read(VEL / "200RPM_v2.BDD")
        for c in m.channels:
            assert c.config.sound_speed_ms == pytest.approx(1460, abs=1)
            assert c.config.velo_max_ms is not None

    def test_by_channel(self):
        m = read(VEL / "200RPM.BDD")
        assert set(m.by_channel()) == {6, 7, 8, 9}


# ── content-based discovery ────────────────────────────────────────────


class TestDiscover:
    def test_finds_bdd_despite_jpg_extension(self):
        """A .BDD misnamed .jpg must still be discovered (content, not ext)."""
        files = discover_data_files(DATA)
        assert any(p.suffix.lower() == ".jpg" for p in files)

    def test_finds_many_bdd(self):
        files = discover_data_files(DATA)
        assert any(p.suffix.lower() == ".bdd" for p in files)


# ── load() dispatch ────────────────────────────────────────────────────


class TestLoad:
    def test_load_multiplexed(self):
        m = load(VEL / "200RPM.BDD")
        assert len(m.channels) == 4

    def test_load_rejects_unknown(self, tmp_path):
        bad = tmp_path / "x.bin"
        bad.write_bytes(b"not a udv file at all")
        with pytest.raises(ValueError):
            load(bad)
