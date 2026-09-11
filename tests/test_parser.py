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


# ── 93-column mux: dual velocity + amplitude column groups ──────────────
#
# The DOP3000 multiplexer export carries 45 ``mm/s`` columns followed by
# 45 ``Amp`` columns (plus TBD / No block / Channel = 93 tab-separated
# columns) and repeats its 45 unique gate depths twice on the depth row.
# The column groups must be derived from the *units row*, never from the
# depth-row length, and each group must become its own frame on the single
# 45-gate depth axis.

MUX_N_GATES = 45


def _comma(value: float) -> str:
    """Format a number the way ASCUDOPV does (comma decimal separator)."""
    return f"{value:g}".replace(".", ",")


def _mux_depths() -> list[float]:
    return [20.0 + i for i in range(MUX_N_GATES)]


def _write_mux_add(
    path: Path,
    *,
    blocks: tuple[int, ...] = (1, 2),
    channel: int = 6,
    n_profiles: int = 2,
    stat: bool = False,
    second_unit: str = "Amp",
    n_amp: int = MUX_N_GATES,
    amp_depths: list[float] | None = None,
) -> Path:
    """Write a synthetic 93-column mux file with repeated acquisition blocks."""
    vel_depths = _mux_depths()
    if amp_depths is None:
        amp_depths = list(vel_depths[:n_amp])
    assert len(amp_depths) == n_amp
    units = (
        ["mm/s"] * MUX_N_GATES
        + [second_unit] * n_amp
        + ["TBD [ms]", "No block", "Channel"]
    )
    depths = vel_depths + amp_depths

    def row(values: list[float]) -> str:
        return "\t".join(_comma(v) if isinstance(v, float) else str(v) for v in values)

    lines = ["ASCUDOPV4.03.4", "Memo_Comments", ""]
    for block in blocks:
        lines.append("Gate Depth [mm]")
        lines.append("\t".join(_comma(d) for d in depths) + "\t")
        lines.append("\t".join(units))
        if stat:
            lines.append(f"Statistical values based on :{n_profiles} values")
        numeric_rows: list[list[float]] = []
        for p in range(n_profiles):
            velocity = [-(i + 1) - 0.5 * p for i in range(MUX_N_GATES)]
            amplitude = [100.0 + i + 10.0 * p for i in range(n_amp)]
            numeric_rows.append(velocity + amplitude + [p * 3.2, block, channel])
        if stat:
            mean = numeric_rows[0]
            lines.append(row(mean))
            lines.append("standard deviation")
            lines.append(row([v + 1.0 for v in mean]))
            lines.append("minimum")
            lines.append(row([v - 1.0 for v in mean]))
            lines.append("maximum")
            lines.append(row([v + 2.0 for v in mean]))
        else:
            lines.extend(row(values) for values in numeric_rows)

    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return path


def test_mux_dual_group_splits_velocity_and_amplitude(tmp_path: Path) -> None:
    """A 93-column mux file must yield distinct velocity and amplitude frames."""
    d = extract(_write_mux_add(tmp_path / "mux93.ADD"))

    # 2 repeated sections x 2 raw profiles x 2 column groups.
    assert len(d.frames) == 8
    velocity = [f for f in d.frames if f.meas_type is MeasType.VELOCITY]
    echo = [f for f in d.frames if f.meas_type is MeasType.ECHO]
    assert len(velocity) == 4
    assert len(echo) == 4
    assert d.meas_type is None  # a mux recording is not a single measurement type

    # Every frame sits on the same single 45-gate depth axis.
    assert all(len(f.gate_depths_mm) == 45 for f in d.frames)
    assert all(f.gate_depths_mm == velocity[0].gate_depths_mm for f in d.frames)
    assert velocity[0].gate_depths_mm[0] == 20.0
    assert velocity[0].gate_depths_mm[-1] == 64.0
    assert len(velocity[0].values) == 45

    # The velocity frame carries only velocity values; the amplitude frame
    # only amplitude values. Conflation would have produced a 90-value frame.
    assert velocity[0].values == [-(i + 1) for i in range(45)]
    assert echo[0].values == [100.0 + i for i in range(45)]
    assert all(v < 0 for v in velocity[0].values)
    assert all(v >= 100.0 for v in echo[0].values)


def test_mux_dual_group_repeated_sections_parse(tmp_path: Path) -> None:
    """Repeated Gate Depth sections in a mux export all parse into frames."""
    d = extract(_write_mux_add(tmp_path / "mux93.ADD", blocks=(1, 2, 3)))

    assert sorted(d.by_block()) == [1, 2, 3]
    assert sorted(d.by_channel()) == [6]
    assert len(d.by_channel()[6]) == 12

    for block, frames in d.by_block().items():
        assert len(frames) == 4
        assert {f.meas_type for f in frames} == {MeasType.VELOCITY, MeasType.ECHO}
        assert all(f.block == block for f in frames)
        assert all(f.channel == 6 for f in frames)
        velocity = [f for f in frames if f.meas_type is MeasType.VELOCITY]
        assert [f.tbd_ms for f in velocity] == [0.0, 3.2]


def test_mux_dual_group_stat_section_splits(tmp_path: Path) -> None:
    """Statistical mux sections split mean/std/min/max per column group."""
    d = extract(
        _write_mux_add(
            tmp_path / "mux93_stat.ADD", blocks=(1,), n_profiles=4, stat=True
        )
    )

    assert len(d.frames) == 2
    velocity, echo = d.frames
    assert velocity.meas_type is MeasType.VELOCITY
    assert echo.meas_type is MeasType.ECHO
    assert velocity.n_profiles == 4
    assert velocity.gate_depths_mm == echo.gate_depths_mm
    assert len(velocity.gate_depths_mm) == 45
    assert len(velocity.values) == 45
    std_dev, min_val, max_val = velocity.std_dev, velocity.min_val, velocity.max_val
    assert std_dev is not None and min_val is not None and max_val is not None
    assert len(std_dev) == 45
    assert len(min_val) == 45
    assert len(max_val) == 45
    assert velocity.values == [-(i + 1) for i in range(45)]
    assert echo.values == [100.0 + i for i in range(45)]
    assert std_dev[0] == velocity.values[0] + 1.0
    assert min_val[0] == velocity.values[0] - 1.0
    assert max_val[0] == velocity.values[0] + 2.0


def test_mux_unknown_units_rejected_loudly(tmp_path: Path) -> None:
    """An unrecognised per-column unit must raise, not silently become echo."""
    p = _write_mux_add(tmp_path / "mux93_bad_unit.ADD", second_unit="Pa")
    with pytest.raises(ValueError, match="unit"):
        extract(p)


def test_mux_mismatched_depth_axis_rejected_loudly(tmp_path: Path) -> None:
    """Column groups that do not share one depth axis must raise."""
    shifted = [200.0 + i for i in range(MUX_N_GATES)]
    p = _write_mux_add(tmp_path / "mux93_bad_depth.ADD", amp_depths=shifted)
    with pytest.raises(ValueError, match="depth"):
        extract(p)


def test_mux_uneven_groups_rejected_loudly(tmp_path: Path) -> None:
    """Groups are derived from the units row, so uneven groups must raise."""
    p = _write_mux_add(tmp_path / "mux93_uneven.ADD", n_amp=MUX_N_GATES - 1)
    with pytest.raises(ValueError, match="group"):
        extract(p)
