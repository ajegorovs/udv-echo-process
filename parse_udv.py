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

import re
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import BaseModel


def parse_comma_decimal(value: str) -> float:
    """Parse a comma-decimal string like '42,97' -> 42.97."""
    return float(value.replace(",", "."))


# ── Unified parser (Pydantic models + auto-detect) ──────────────────────


class MeasType(str, Enum):
    """Type of measurement: echo (amplitude) or velocity (mm/s)."""

    ECHO = "echo"
    VELOCITY = "velocity"


class ChannelFrame(BaseModel):
    """One measurement at one time point for one channel.

    In multi-sensor rolling data, each (block, channel) pair produces
    one frame. In single-sensor data, each data row is one frame.

    ``tbd_ms``: "Time Between Data" — cumulative from recording start
    for raw format; per-block acquisition interval (constant) for stat.
    """

    channel: int
    block: int
    tbd_ms: float
    meas_type: MeasType
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
    frames: list[ChannelFrame] = []

    @property
    def meas_type(self) -> MeasType | None:
        """Measurement type if all frames agree, None if mixed."""
        types = {f.meas_type for f in self.frames}
        return types.pop() if len(types) == 1 else None

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

    def describe(self) -> str:
        """Return a formatted description of the recording setup."""
        by_ch = self.by_channel()
        by_blk = self.by_block()
        is_multi = len(by_ch) > 1 or len(by_blk) > 1
        fmt = "stat" if any(f.n_profiles is not None for f in self.frames) else "raw"

        lines: list[str] = []
        sep = "=" * 58
        lines.append(sep)
        lines.append(f"  File: {self.file_path.name}")
        lines.append(f"  Header: {self.header}")
        lines.append(f"  Comment: {self.comment}")
        lines.append(sep)
        lines.append(f"  Recording type:  {'multi-sensor' if is_multi else 'single-sensor'}")
        lines.append(f"  File format:     {fmt}")
        lines.append(f"  Total frames:    {len(self.frames)}")
        lines.append(f"  Channels:        {sorted(by_ch.keys())}")

        if is_multi:
            n_prof = _detect_n_profiles(self, by_ch, by_blk)
            lines.append(f"  Profiles/block:  {n_prof}")
            lines.append(f"  Total blocks:    {len(by_blk)}")

            # Detect recording order
            seen: set[int] = set()
            cycle: list[int] = []
            for f in self.frames:
                if f.channel not in seen:
                    seen.add(f.channel)
                    cycle.append(f.channel)
                    if len(seen) == len(by_ch):
                        break
            if len(cycle) > 1:
                seq = " -> ".join(str(ch) for ch in cycle) + " -> ..."
                lines.append(f"  Recording order:  Ch [{seq}]")

            # Timing overview
            all_tbds = [f.tbd_ms for f in self.frames]
            tbd_range_ms = max(all_tbds) - min(all_tbds)
            if tbd_range_ms > 1.0:
                total_s = tbd_range_ms / 1000
                tbds_unique = sorted(set(all_tbds))
                dt_ms = float(np.mean(np.diff(tbds_unique))) if len(tbds_unique) > 1 else 0.0
                lines.append(f"  Duration:        {total_s:.1f} s  (mean dT: {dt_ms:.2f} ms)")
            else:
                mean_tbd = float(np.mean(all_tbds))
                lines.append(f"  Per-block DT:    {mean_tbd:.2f} ms  (constant TBD)")

        lines.append("")
        lines.append("  TBD = Time Between Data (cumulative in raw, per-block constant in stat)")
        lines.append("")

        # Detect P for raw format (same across channels)
        raw_p = _detect_n_profiles(self, by_ch, by_blk) if is_multi else None

        for ch in sorted(by_ch.keys()):
            ch_frames = by_ch[ch]
            gd = ch_frames[0].gate_depths_mm
            tbds = [f.tbd_ms for f in ch_frames]
            p = ch_frames[0].n_profiles or raw_p

            mt = ch_frames[0].meas_type.value
            lines.append(f"  Channel {ch}  ({mt}):")
            lines.append(f"    Gate depths:     {len(gd)} gates  ({gd[0]:.2f} - {gd[-1]:.2f} mm)")
            lines.append(f"    Frames:          {len(ch_frames)}")
            lines.append(f"    Blocks:          {ch_frames[0].block} - {ch_frames[-1].block}")
            lines.append(f"    TBD range:       {min(tbds):.2f} - {max(tbds):.2f} ms")
            lines.append(f"    Profiles/block:  {p if p is not None else '-'}")

            # Check if channels share identical gate setup
            first_gds = {c: by_ch[c][0].gate_depths_mm for c in by_ch}
            unique_gds = set(tuple(g) for g in first_gds.values())
            if len(unique_gds) > 1:
                lines.append(f"    ** Gate setup differs from other channels **")
            lines.append("")

        return "\n".join(lines)


# ── Backward-compat convenience functions ───────────────────────────────


def list_add_files(data_dir: str | Path = "data-echo") -> list[Path]:
    """List all raw .ADD files (excluding _Stat.ADD) in a directory."""
    return sorted(p for p in Path(data_dir).glob("*.ADD") if "_Stat" not in p.stem)


def list_stat_add_files(data_dir: str | Path = "data-echo") -> list[Path]:
    """List all _Stat.ADD files in a directory."""
    return sorted(Path(data_dir).glob("*_Stat.ADD"))


def parse_add_file(filepath: str | Path) -> ExtractedData:
    """Parse a .ADD data file (backward-compat name)."""
    return extract(filepath)


def parse_stat_add_file(filepath: str | Path) -> ExtractedData:
    """Parse a _Stat.ADD file (backward-compat name)."""
    return extract(filepath)


def load_all_data(
    data_dir: str | Path = "data-echo",
) -> dict[str, ExtractedData]:
    """Load all raw .ADD files into a dict keyed by setpoint RPM."""
    return {fp.stem: extract(fp) for fp in list_add_files(data_dir)}


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
    meas_type = _detect_meas_type(lines[idx + 2])

    data_start = idx + 3

    # Check if this is a stat file
    if data_start < len(lines) and lines[data_start].strip().startswith("Statistical"):
        _parse_stat_section(lines, data_start, n_gates, gate_depths, meas_type, result)
        return

    for line in lines[data_start:]:
        _add_frame(line, n_gates, gate_depths, meas_type, result)


def _parse_multi_sensor(
    lines: list[str], result: ExtractedData, gd_indices: list[int],
) -> None:
    """Repeating sections — one per (block, channel)."""
    for sec_idx, gd_idx in enumerate(gd_indices):
        gate_depths = _parse_gate_depths(lines[gd_idx + 1])
        n_gates = len(gate_depths)
        meas_type = _detect_meas_type(lines[gd_idx + 2])

        # Determine section extent
        end_idx = gd_indices[sec_idx + 1] if sec_idx + 1 < len(gd_indices) else len(lines)
        section_lines = lines[gd_idx + 3 : end_idx]

        # Check if statistical format
        if section_lines and section_lines[0].strip().startswith("Statistical"):
            _parse_stat_section(section_lines, 0, n_gates, gate_depths, meas_type, result)
        else:
            for line in section_lines:
                _add_frame(line, n_gates, gate_depths, meas_type, result)


def _add_frame(
    line: str, n_gates: int, gate_depths: list[float],
    meas_type: MeasType, result: ExtractedData,
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
        meas_type=meas_type,
        gate_depths_mm=list(gate_depths),
        values=vals,
    ))


def _parse_stat_section(
    lines: list[str], start: int, n_gates: int,
    gate_depths: list[float], meas_type: MeasType, result: ExtractedData,
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
        meas_type=meas_type,
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


def _detect_n_profiles(d: ExtractedData, by_ch, by_blk) -> int:
    for f in d.frames:
        if f.n_profiles is not None:
            return f.n_profiles
    ch = sorted(by_ch.keys())[0]
    blk = by_ch[ch][0].block
    return sum(1 for f in d.frames if f.channel == ch and f.block == blk)


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "data-echo/650.ADD"
    print(extract(target).describe())
