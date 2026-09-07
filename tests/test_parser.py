"""Tests locking in parser behavior across the three data families.

These tests use the committed data files as fixtures so they exercise the
real-world file formats end to end. The ``data/`` directory is checked in,
so all fixtures are expected to be present.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process import (
    MeasType,
    extract,
    list_add_files,
    list_stat_add_files,
    parse_comma_decimal,
)

ROOT = Path(__file__).resolve().parent.parent

SINGLE_RAW = ROOT / "data/echo/650.ADD"
SINGLE_STAT = ROOT / "data/echo/650_Stat.ADD"
MULTI_STAT = ROOT / "data/echo-4-sensors-2x2/300RPM.ADD"
MULTI_RAW_VEL = ROOT / "data/4-sensor-velocity/200RPM_v2.ADD"
MULTI_STAT_VEL = ROOT / "data/4-sensor-velocity/200RPM_v2_Stat.ADD"


@pytest.fixture(autouse=True)
def _require_data() -> None:
    if not SINGLE_RAW.exists():
        pytest.skip("committed data/ fixtures not present")


# ── low-level helpers ───────────────────────────────────────────────────


def test_parse_comma_decimal() -> None:
    assert parse_comma_decimal("42,97") == 42.97
    assert parse_comma_decimal("0,00") == 0.0
    assert parse_comma_decimal("-22,571") == -22.571


# ── single-sensor raw echo ──────────────────────────────────────────────


def test_single_sensor_raw_echo() -> None:
    d = extract(SINGLE_RAW)
    assert d.header == "ASCUDOPV4.03.4"
    assert d.comment == "Memo_Comments"
    assert len(d.frames) == 4630
    assert sorted(d.by_channel().keys()) == [4]
    assert d.meas_type is MeasType.ECHO

    f0 = d.frames[0]
    assert f0.channel == 4
    assert f0.block == 1
    assert f0.tbd_ms == 0.0
    assert f0.n_profiles is None
    assert f0.std_dev is None
    assert len(f0.gate_depths_mm) == 26
    assert len(f0.values) == 26
    assert f0.gate_depths_mm[0] == 42.97
    assert f0.gate_depths_mm[-1] == 54.39
    np.testing.assert_allclose(f0.values[:3], [24.0, 8.0, 16.0])


def test_single_sensor_raw_tbd_increases() -> None:
    d = extract(SINGLE_RAW)
    tbds = [f.tbd_ms for f in d.frames]
    assert all(b > a for a, b in itertools.pairwise(tbds))


# ── single-sensor statistical echo ──────────────────────────────────────


def test_single_sensor_stat_echo() -> None:
    d = extract(SINGLE_STAT)
    assert len(d.frames) == 1
    f0 = d.frames[0]
    assert f0.n_profiles == 4630
    assert f0.channel == 4
    assert f0.tbd_ms == 3.18
    assert len(f0.std_dev) == 26
    assert len(f0.min_val) == 26
    assert len(f0.max_val) == 26
    assert f0.values[0] != 0.0


# ── multi-sensor statistical echo ───────────────────────────────────────


def test_multi_sensor_stat_echo() -> None:
    d = extract(MULTI_STAT)
    assert len(d.frames) == 400
    assert sorted(d.by_channel().keys()) == [6, 7, 8, 9]
    assert d.meas_type is MeasType.ECHO
    assert len(d.by_block()) == 100

    for frames in d.by_channel().values():
        assert len(frames) == 100
        assert all(f.block == i + 1 for i, f in enumerate(frames))
        assert frames[0].n_profiles == 10
        assert len(frames[0].std_dev) == 35


# ── multi-sensor raw velocity ───────────────────────────────────────────


def test_multi_sensor_raw_velocity() -> None:
    d = extract(MULTI_RAW_VEL)
    assert len(d.frames) == 1600
    assert sorted(d.by_channel().keys()) == [6, 7, 8, 9]
    assert d.meas_type is MeasType.VELOCITY

    f0 = d.frames[0]
    assert f0.n_profiles is None
    assert len(f0.gate_depths_mm) == 55
    assert len(f0.values) == 55
    assert f0.gate_depths_mm[0] == 20.0
    assert f0.gate_depths_mm[-1] == 79.13


def test_multi_sensor_stat_velocity() -> None:
    d = extract(MULTI_STAT_VEL)
    assert len(d.frames) == 400
    assert sorted(d.by_channel().keys()) == [6, 7, 8, 9]
    assert d.frames[0].n_profiles == 4
    assert len(d.frames[0].values) == 55


# ── grouping & describe ─────────────────────────────────────────────────


def test_by_channel_by_block_grouping() -> None:
    d = extract(MULTI_STAT)
    total_ch = sum(len(f) for f in d.by_channel().values())
    total_blk = sum(len(f) for f in d.by_block().values())
    assert total_ch == len(d.frames)
    assert total_blk == len(d.frames)


def test_describe_reports_setup() -> None:
    text = extract(MULTI_STAT).describe()
    assert "multi-sensor" in text
    assert "stat" in text
    assert "Profiles/block:  10" in text
    assert "Channels:        [6, 7, 8, 9]" in text


def test_mixed_meas_type_returns_none() -> None:
    d = extract(MULTI_RAW_VEL)
    d.frames[0].meas_type = MeasType.ECHO
    assert d.meas_type is None


# ── listing helpers ─────────────────────────────────────────────────────


def test_list_add_files_excludes_stat() -> None:
    names = [p.name for p in list_add_files(ROOT / "data/echo")]
    assert "650.ADD" in names
    assert all("_Stat" not in n for n in names)


def test_list_stat_add_files() -> None:
    names = [p.name for p in list_stat_add_files(ROOT / "data/echo")]
    assert "650_Stat.ADD" in names
    assert all(n.endswith("_Stat.ADD") for n in names)


# ── content sniffing guard ──────────────────────────────────────────────


def test_extract_rejects_non_udv_content(tmp_path: Path) -> None:
    """A magic-less file (e.g. a misnamed image) must raise a clear error."""
    png = tmp_path / "fake.BDD"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    with pytest.raises(ValueError, match="ASCUDOPV"):
        extract(png)

    jpg = tmp_path / "fake.ADD"
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    with pytest.raises(ValueError, match="ASCUDOPV"):
        extract(jpg)

    empty = tmp_path / "empty.ADD"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="ASCUDOPV"):
        extract(empty)


def test_extract_rejects_misnamed_tracked_images() -> None:
    """The two known-bad tracked files now carry true extensions; if they ever
    come back under a .ADD/.BDD name with image content, extract() must refuse."""
    for name in ("300RPM.BDD", "300RPM_Stat.ADD"):
        p = ROOT / "data/echo-4-sensors-2x2" / name
        if p.exists():
            with pytest.raises(ValueError, match="ASCUDOPV"):
                extract(p)


# ── empty-data degradation ──────────────────────────────────────────────


def test_describe_on_header_only_file(tmp_path: Path) -> None:
    """A magic-bearing file with no data rows must describe gracefully."""
    f = tmp_path / "header_only.ADD"
    f.write_text("ASCUDOPV4.03.4\nMemo_Comments\n", encoding="latin-1")
    d = extract(f)
    assert d.frames == []
    assert d.meas_type is None
    text = d.describe()
    assert "No frames parsed" in text
    assert d.file_path.name in text
