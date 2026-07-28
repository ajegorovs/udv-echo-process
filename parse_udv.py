"""Parse UDV (Ultrasonic Doppler Velocimetry) .ADD data files.

File format variants detected automatically:

**Single-sensor continuous** (data-echo/*.ADD):
  One "Gate Depth [mm]" section followed by continuous data rows.
  Unit: "Amp" (echo) or "mm/s" (velocity).

**Multi-sensor block-channel** (data-4-sensor-*/):
  Repeated "Gate Depth [mm]" sections, one per (Block, Channel) group.
  Sub-types:
    - Raw format: P data rows per section
    - Statistical summary: mean/stddev/min/max over P profiles per section
  Unit: "Amp" (echo) or "mm/s" (velocity).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel


class UDVData(NamedTuple):
    """Parsed UDV measurement data."""

    header: str
    comment: str
    gate_depths_mm: list[float]
    data: list[list[float]]  # shape (n_timesteps, n_gates) - amp values
    tbd_ms: list[float]  # time between data
    block: list[int]
    channel: list[int]
    file_path: Path


@dataclass
class UDVStats:
    """Statistical summary from _Stat.ADD files."""

    header: str
    comment: str
    gate_depths_mm: list[float]
    n_values: int
    mean: list[float]
    std_dev: list[float]
    median: list[float] | None = None
    first_quartile: list[float] | None = None
    third_quartile: list[float] | None = None
    min_val: list[float] | None = None
    max_val: list[float] | None = None
    file_path: Path = field(default_factory=Path)


def parse_comma_decimal(value: str) -> float:
    """Parse a comma-decimal string like '42,97' -> 42.97."""
    return float(value.replace(",", "."))


def parse_add_file(filepath: str | Path) -> UDVData:
    """Parse a raw .ADD data file, returning structured data."""
    path = Path(filepath)
    lines = path.read_text(encoding="latin-1").splitlines()

    header = lines[0].strip()
    comment = lines[1].strip()

    gate_depth_strs = lines[4].strip().split("\t")
    gate_depths = [parse_comma_decimal(g) for g in gate_depth_strs if g]

    data: list[list[float]] = []
    tbd_ms: list[float] = []
    block: list[int] = []
    channel: list[int] = []

    n_gates = len(gate_depths)

    for line in lines[6:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        amp_vals = [parse_comma_decimal(p) for p in parts[:n_gates]]
        tbd = parse_comma_decimal(parts[n_gates]) if len(parts) > n_gates else 0.0
        blk = int(parts[n_gates + 1]) if len(parts) > n_gates + 1 else 0
        ch = int(parts[n_gates + 2]) if len(parts) > n_gates + 2 else 0

        data.append(amp_vals)
        tbd_ms.append(tbd)
        block.append(blk)
        channel.append(ch)

    return UDVData(
        header=header,
        comment=comment,
        gate_depths_mm=gate_depths,
        data=data,
        tbd_ms=tbd_ms,
        block=block,
        channel=channel,
        file_path=path,
    )


def parse_stat_add_file(filepath: str | Path) -> UDVStats:
    """Parse a _Stat.ADD statistical summary file."""
    path = Path(filepath)
    lines = path.read_text(encoding="latin-1").splitlines()

    header = lines[0].strip()
    comment = lines[1].strip()

    gate_depth_strs = lines[4].strip().split("\t")
    gate_depths = [parse_comma_decimal(g) for g in gate_depth_strs if g]
    n_gates = len(gate_depths)

    n_values = 0
    nv_match = re.search(r"(\d+)", lines[6])
    if nv_match:
        n_values = int(nv_match.group(1))

    def parse_row(idx: int) -> list[float] | None:
        if idx >= len(lines):
            return None
        parts = lines[idx].strip().split("\t")
        if not parts or len(parts) < n_gates:
            return None
        return [parse_comma_decimal(p) for p in parts[:n_gates]]

    # Row 7: mean (line index 6)
    # Row 9: std dev (line index 8)
    # Row 11: min (line index 10)
    # Row 13: first quartile (line index 12)
    # Row 15: median (line index 14)
    # Row 17: third quartile (line index 16)
    # Row 19: max (line index 18)
    # The ordering varies by file version; we scan by label.

    label_map: dict[str, str] = {}
    for i in range(6, len(lines) - 1, 2):
        label = lines[i + 1].strip().lower() if i + 1 < len(lines) else ""
        if label == "standart deviation":
            label_map["std_dev"] = lines[i]
        elif label in ("mean", "average"):
            label_map["mean"] = lines[i]
        elif label in ("median",):
            label_map["median"] = lines[i]
        elif label in ("first quartile", "q1", "25%"):
            label_map["first_quartile"] = lines[i]
        elif label in ("third quartile", "q3", "75%"):
            label_map["third_quartile"] = lines[i]
        elif label in ("minimum", "min"):
            label_map["min"] = lines[i]
        elif label in ("maximum", "max"):
            label_map["max"] = lines[i]
        elif label in ("count", "n"):
            pass  # already captured from line 6

    return UDVStats(
        header=header,
        comment=comment,
        gate_depths_mm=gate_depths,
        n_values=n_values,
        mean=parse_row(6),
        std_dev=parse_row(8),
        file_path=path,
    )


def list_add_files(data_dir: str | Path = "data-echo") -> list[Path]:
    """List all raw .ADD files (excluding _Stat.ADD) in the data directory."""
    return sorted(
        p for p in Path(data_dir).glob("*.ADD") if "_Stat" not in p.stem
    )


def list_stat_add_files(data_dir: str | Path = "data-echo") -> list[Path]:
    """List all _Stat.ADD files in the data directory."""
    return sorted(Path(data_dir).glob("*_Stat.ADD"))


def load_all_data(
    data_dir: str | Path = "data-echo",
) -> dict[str, UDVData]:
    """Load all raw .ADD files into a dict keyed by setpoint RPM."""
    result: dict[str, UDVData] = {}
    for fp in list_add_files(data_dir):
        key = fp.stem  # e.g. "650"
        result[key] = parse_add_file(fp)
    return result


# ── Unified parser (Pydantic models + auto-detect) ──────────────────────


class MeasType(str, Enum):
    """Type of measurement: echo (amplitude) or velocity (mm/s)."""

    ECHO = "echo"
    VELOCITY = "velocity"


class ChannelFrame(BaseModel):
    """One measurement at one time point for one channel.

    In multi-sensor rolling data, each (block, channel) pair produces
    one frame. In single-sensor data, each data row is one frame.
    """

    channel: int
    block: int
    tbd_ms: float
    gate_depths_mm: list[float]
    values: list[float]

    # Optional fields for statistical-summary format
    n_profiles: int | None = None
    std_dev: list[float] | None = None
    min_val: list[float] | None = None
    max_val: list[float] | None = None


class ExtractedData(BaseModel):
    """Unified result from parsing any UDV file."""

    file_path: Path
    header: str = ""
    comment: str = ""
    meas_type: MeasType = MeasType.ECHO
    frames: list[ChannelFrame] = []

    def by_channel(self) -> dict[int, list[ChannelFrame]]:
        result: dict[int, list[ChannelFrame]] = {}
        for f in self.frames:
            result.setdefault(f.channel, []).append(f)
        return result

    def by_block(self) -> dict[int, list[ChannelFrame]]:
        result: dict[int, list[ChannelFrame]] = {}
        for f in self.frames:
            result.setdefault(f.block, []).append(f)
        return result


# ── Internal helpers ────────────────────────────────────────────────────


def _detect_meas_type(header_row: str) -> MeasType:
    if "mm/s" in header_row:
        return MeasType.VELOCITY
    return MeasType.ECHO


def _parse_gate_depths(line: str) -> list[float]:
    parts = line.strip().split("\t")
    return [parse_comma_decimal(p) for p in parts if p]


def _parse_num(line: str) -> int | None:
    m = re.search(r"(\d+)", line)
    return int(m.group(1)) if m else None


def extract(
    filepath: str | Path,
) -> ExtractedData:
    """Parse any UDV file, auto-detecting format."""
    path = Path(filepath)
    lines = path.read_text(encoding="latin-1").splitlines()
    stripped = [l for l in lines if l.strip()]

    result = ExtractedData(file_path=path)

    # Global header / comment
    if stripped:
        result.header = stripped[0].strip()
    if len(stripped) > 1:
        result.comment = stripped[1].strip()

    # Find all "Gate Depth [mm]" markers
    gd_indices = [i for i, l in enumerate(stripped) if l.strip() == "Gate Depth [mm]"]

    if len(gd_indices) <= 1:
        _parse_single_sensor(stripped, result, gd_indices)
    else:
        _parse_multi_sensor(stripped, result, gd_indices)

    return result


def _parse_single_sensor(
    lines: list[str], result: ExtractedData, gd_indices: list[int],
) -> None:
    """Single continuous recording — one channel, one block."""
    idx = gd_indices[0] if gd_indices else 0
    gate_depths = _parse_gate_depths(lines[idx + 1])
    n_gates = len(gate_depths)
    result.meas_type = _detect_meas_type(lines[idx + 2])

    data_start = idx + 3

    # Check if this is a stat file
    if data_start < len(lines) and lines[data_start].strip().startswith("Statistical"):
        _parse_stat_section(lines, data_start, n_gates, gate_depths, result)
        return

    for line in lines[data_start:]:
        _add_frame(line, n_gates, gate_depths, result)


def _parse_multi_sensor(
    lines: list[str], result: ExtractedData, gd_indices: list[int],
) -> None:
    """Repeating sections — one per (block, channel)."""
    for sec_idx, gd_idx in enumerate(gd_indices):
        gate_depths = _parse_gate_depths(lines[gd_idx + 1])
        n_gates = len(gate_depths)
        result.meas_type = _detect_meas_type(lines[gd_idx + 2])

        # Determine section extent
        end_idx = gd_indices[sec_idx + 1] if sec_idx + 1 < len(gd_indices) else len(lines)
        section_lines = lines[gd_idx + 3 : end_idx]

        # Check if statistical format
        if section_lines and section_lines[0].strip().startswith("Statistical"):
            _parse_stat_section(section_lines, 0, n_gates, gate_depths, result)
        else:
            for line in section_lines:
                _add_frame(line, n_gates, gate_depths, result)


def _add_frame(
    line: str, n_gates: int, gate_depths: list[float], result: ExtractedData,
) -> None:
    """Parse one data row and add a ChannelFrame."""
    parts = line.strip().split("\t")
    if len(parts) < n_gates + 1:
        return
    try:
        vals = [parse_comma_decimal(p) for p in parts[:n_gates]]
        tbd = parse_comma_decimal(parts[n_gates])
        block = int(parts[n_gates + 1]) if len(parts) > n_gates + 1 else 0
        channel = int(parts[n_gates + 2]) if len(parts) > n_gates + 2 else 0
    except ValueError:
        return

    result.frames.append(ChannelFrame(
        channel=channel,
        block=block,
        tbd_ms=tbd,
        gate_depths_mm=list(gate_depths),
        values=vals,
    ))


def _parse_stat_section(
    lines: list[str], start: int, n_gates: int,
    gate_depths: list[float], result: ExtractedData,
) -> None:
    """Parse a statistical summary block (mean / stddev / min / max)."""
    # Line 0 (relative): "Statistical values based on :N values"
    n_prof = _parse_num(lines[start]) if start < len(lines) else None

    # Line 1: mean row
    mean_row = _parse_stat_row(lines, start + 1, n_gates)
    # Labels and values alternate every 2 lines
    labels = {}
    for i in range(start + 2, len(lines) - 1, 2):
        label = lines[i].strip().lower() if i < len(lines) else ""
        val_row = _parse_stat_row(lines, i + 1, n_gates) if i + 1 < len(lines) else None
        if label in ("standart deviation", "standard deviation"):
            labels["std_dev"] = val_row
        elif label in ("minimum", "min"):
            labels["min"] = val_row
        elif label in ("maximum", "max"):
            labels["max"] = val_row

    if mean_row is None:
        return

    # Extract block/channel from the mean row's last columns
    parts = lines[start + 1].strip().split("\t") if start + 1 < len(lines) else []
    block = int(parts[n_gates + 1]) if len(parts) > n_gates + 1 else 0
    channel = int(parts[n_gates + 2]) if len(parts) > n_gates + 2 else 0
    tbd = parse_comma_decimal(parts[n_gates]) if len(parts) > n_gates else 0.0

    result.frames.append(ChannelFrame(
        channel=channel,
        block=block,
        tbd_ms=tbd,
        gate_depths_mm=list(gate_depths),
        values=mean_row,
        n_profiles=n_prof,
        std_dev=labels.get("std_dev"),
        min_val=labels.get("min"),
        max_val=labels.get("max"),
    ))


def _parse_stat_row(lines: list[str], idx: int, n_gates: int) -> list[float] | None:
    if idx >= len(lines):
        return None
    parts = lines[idx].strip().split("\t")
    if len(parts) < n_gates:
        return None
    try:
        return [parse_comma_decimal(p) for p in parts[:n_gates]]
    except ValueError:
        return None


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "data-echo/650.ADD"
    data = parse_add_file(target)
    print(f"File: {data.file_path.name}")
    print(f"Header: {data.header}")
    print(f"Gate depths ({len(data.gate_depths_mm)}): {data.gate_depths_mm}")
    print(f"Data shape: {len(data.data)} timesteps x {len(data.data[0])} gates")
    print(f"TBD range: {min(data.tbd_ms):.2f} - {max(data.tbd_ms):.2f} ms")
    print(f"Block: {set(data.block)}, Channel: {set(data.channel)}")
    print(f"\nFirst 3 data rows (first 5 gates):")
    for i, row in enumerate(data.data[:3]):
        print(f"  [{i}] {row[:5]}...")
