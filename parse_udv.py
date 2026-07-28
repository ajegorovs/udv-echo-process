"""Parse UDV (Ultrasonic Doppler Velocimetry) .ADD data files.

File format (TSV with comma as decimal separator):
  Row 1: Instrument header        e.g. "ASCUDOPV4.03.4"
  Row 2: Comment                  e.g. "Memo_Comments"
  Row 3: (empty)
  Row 4: Section header           "Gate Depth [mm]"
  Row 5: Gate depth values        26 comma-decimal values (tab-separated)
  Row 6: Column headers           26x "Amp" + "TBD [ms]" + "No block" + "Channel"
  Row 7+: Data rows               26 Amp values + TBD + block + channel

  _Stat.ADD files: same header, then statistical summary rows
  (mean, std deviation, count, etc.)
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple


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
