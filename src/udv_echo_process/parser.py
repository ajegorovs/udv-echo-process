"""Parse UDV (Ultrasonic Doppler Velocimetry) .ADD data files.

File format variants detected automatically:

**Single-sensor continuous** (data/echo/*.ADD):
  One "Gate Depth [mm]" section followed by continuous data rows.
  Unit: "Amp" (echo) or "mm/s" (velocity).

**Multi-sensor block-channel** (data/4-sensor-*/):
  Repeated "Gate Depth [mm]" sections, one per (Block, Channel) group.
  Sub-types:
    - Raw format: P data rows per section
    - Statistical summary: mean/stddev/min/max over P profiles per section
  Unit: "Amp" (echo) or "mm/s" (velocity).

  A multiplexer export may interleave both unit types in one section: 45
  ``mm/s`` columns followed by 45 ``Amp`` columns (93 tab-separated columns
  including TBD / No block / Channel), with the 45 unique gate depths listed
  once per column group. The **units row** defines the column groups — never
  the depth-row length — and each group becomes its own ``ChannelFrame`` on
  the single shared 45-gate depth axis.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import BaseModel

GATE_DEPTH_HEADER = "Gate Depth [mm]"
STAT_PREFIX = "Statistical"
MAGIC_PREFIX = "ASCUDOPV"

__all__ = [
    "ChannelFrame",
    "ExtractedData",
    "MeasType",
    "extract",
    "list_add_files",
    "list_stat_add_files",
    "load_all_data",
    "parse_add_file",
    "parse_comma_decimal",
    "parse_stat_add_file",
]

_STAT_LABELS: dict[str, tuple[str, ...]] = {
    "std_dev": ("standart deviation", "standard deviation"),
    "min": ("minimum", "min"),
    "max": ("maximum", "max"),
}


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
        if not self.frames:
            return (
                f"{'=' * 58}\n"
                f"  File: {self.file_path.name}\n"
                f"  Header: {self.header}\n"
                f"  No frames parsed — the file contains no recognisable "
                f"UDV data rows.\n"
                f"{'=' * 58}"
            )
        by_ch = self.by_channel()
        by_blk = self.by_block()
        is_multi = len(by_ch) > 1 or len(by_blk) > 1
        fmt = "stat" if any(f.n_profiles is not None for f in self.frames) else "raw"
        n_prof = _detect_n_profiles(self, by_ch) if is_multi else None
        gate_setup_differs = (
            len({tuple(c[0].gate_depths_mm) for c in by_ch.values()}) > 1
        )

        lines: list[str] = []
        sep = "=" * 58
        lines.append(sep)
        lines.append(f"  File: {self.file_path.name}")
        lines.append(f"  Header: {self.header}")
        lines.append(f"  Comment: {self.comment}")
        lines.append(sep)
        lines.append(
            f"  Recording type:  {'multi-sensor' if is_multi else 'single-sensor'}"
        )
        lines.append(f"  File format:     {fmt}")
        lines.append(f"  Total frames:    {len(self.frames)}")
        lines.append(f"  Channels:        {sorted(by_ch.keys())}")

        if is_multi:
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

            # Timing overview (raw only — TBD is cumulative from recording start)
            if fmt == "raw":
                all_tbds = [f.tbd_ms for f in self.frames]
                tbd_range_ms = max(all_tbds) - min(all_tbds)
                if tbd_range_ms > 1.0:
                    total_s = tbd_range_ms / 1000
                    tbds_unique = sorted(set(all_tbds))
                    dt_ms = (
                        float(np.mean(np.diff(tbds_unique)))
                        if len(tbds_unique) > 1
                        else 0.0
                    )
                    lines.append(
                        f"  Duration:        {total_s:.1f} s  (mean dT: {dt_ms:.2f} ms)"
                    )

        lines.append("")
        lines.append("  TBD = Time Between Data")
        lines.append("")

        for ch in sorted(by_ch.keys()):
            ch_frames = by_ch[ch]
            gd = ch_frames[0].gate_depths_mm
            tbds = [f.tbd_ms for f in ch_frames]
            p = ch_frames[0].n_profiles or n_prof

            mt = "+".join(sorted({f.meas_type.value for f in ch_frames}))
            lines.append(f"  Channel {ch}  ({mt}):")
            lines.append(
                f"    Gate depths:     {len(gd)} gates  ({gd[0]:.2f} - {gd[-1]:.2f} mm)"
            )
            lines.append(f"    Frames:          {len(ch_frames)}")
            lines.append(
                f"    Blocks:          {ch_frames[0].block} - {ch_frames[-1].block}"
            )
            lines.append(f"    TBD range:       {min(tbds):.2f} - {max(tbds):.2f} ms")
            lines.append(f"    Profiles/block:  {p if p is not None else '-'}")

            if gate_setup_differs:
                lines.append("    ** Gate setup differs from other channels **")
            lines.append("")

        return "\n".join(lines)


# ── Backward-compat convenience functions ───────────────────────────────


def list_add_files(data_dir: str | Path = "data/echo") -> list[Path]:
    """List all raw .ADD files (excluding _Stat.ADD) in a directory."""
    return sorted(p for p in Path(data_dir).glob("*.ADD") if "_Stat" not in p.stem)


def list_stat_add_files(data_dir: str | Path = "data/echo") -> list[Path]:
    """List all _Stat.ADD files in a directory."""
    return sorted(Path(data_dir).glob("*_Stat.ADD"))


def parse_add_file(filepath: str | Path) -> ExtractedData:
    """Parse a .ADD data file (backward-compat name)."""
    return extract(filepath)


def parse_stat_add_file(filepath: str | Path) -> ExtractedData:
    """Parse a _Stat.ADD file (backward-compat name)."""
    return extract(filepath)


def load_all_data(
    data_dir: str | Path = "data/echo",
) -> dict[str, ExtractedData]:
    """Load all raw .ADD files into a dict keyed by setpoint RPM."""
    return {fp.stem: extract(fp) for fp in list_add_files(data_dir)}


# ── Internal helpers ────────────────────────────────────────────────────


def _classify_unit(label: str) -> MeasType | None:
    """Map one units-row label to a measurement type, or None if unknown."""
    low = label.strip().lower()
    if "mm/s" in low:
        return MeasType.VELOCITY
    if low.startswith("amp"):
        return MeasType.ECHO
    return None


def _parse_gate_depths(line: str) -> list[float]:
    parts = line.strip().split("\t")
    return [parse_comma_decimal(p) for p in parts if p]


# One column group: (measurement type, start, stop) into a row's value columns.
_ColumnGroup = tuple[MeasType, int, int]


def _resolve_column_groups(
    depths: list[float], units_row: str
) -> tuple[list[float], list[_ColumnGroup]]:
    """Derive per-column measurement groups from a section's units row.

    One units-row label corresponds to one data column, so the ``mm/s`` /
    ``Amp`` runs in that row define the column groups — *not* the depth row,
    whose length is the total column count and may repeat the gate axis once
    per group (a 93-column mux export lists its 45 depths twice).

    Returns ``(gate_depths, groups)`` where ``gate_depths`` is the single
    depth axis shared by every group and each group is a
    ``(meas_type, start, stop)`` slice into the row's value columns.

    Raises ``ValueError`` for layouts that cannot be interpreted: a units row
    shorter than the depth row, unknown unit labels, groups of unequal width,
    or groups that do not repeat one identical depth axis.
    """
    if not depths:
        raise ValueError("empty gate-depth row")
    labels = [p.strip() for p in units_row.strip().split("\t")]
    if len(labels) < len(depths):
        raise ValueError(
            f"units row has {len(labels)} labels for {len(depths)} gate "
            f"depths; expected one unit label per gate"
        )

    value_types: list[MeasType] = []
    unknown: list[str] = []
    for label in labels[: len(depths)]:
        meas_type = _classify_unit(label)
        if meas_type is None:
            unknown.append(label)
        else:
            value_types.append(meas_type)
    if unknown:
        raise ValueError(
            f"unrecognised units row label(s) {sorted(set(unknown))}; "
            f"expected mm/s or Amp"
        )

    groups: list[_ColumnGroup] = []
    start = 0
    for i in range(1, len(value_types) + 1):
        if i == len(value_types) or value_types[i] != value_types[start]:
            groups.append((value_types[start], start, i))
            start = i

    n_groups = len(groups)
    span, remainder = divmod(len(depths), n_groups)
    if remainder or any(stop - lo != span for _, lo, stop in groups):
        raise ValueError(
            f"gate-depth row with {len(depths)} entries does not divide "
            f"evenly into {n_groups} unit group(s)"
        )
    gate_depths = depths[:span]
    for _, lo, stop in groups[1:]:
        if depths[lo:stop] != gate_depths:
            raise ValueError(
                "column unit groups do not repeat a single gate-depth axis"
            )
    return gate_depths, groups


def _parse_num(line: str) -> int | None:
    m = re.search(r"(\d+)", line)
    return int(m.group(1)) if m else None


def extract(
    filepath: str | Path,
) -> ExtractedData:
    """Parse any UDV file, auto-detecting format.

    Raises ``ValueError`` when the file does not carry the ``ASCUDOPV``
    magic header line (e.g. a misnamed image, or a binary/empty file),
    and ``FileNotFoundError`` when it does not exist.
    """
    path = Path(filepath)
    lines = path.read_text(encoding="latin-1", errors="replace").splitlines()
    stripped = [l for l in lines if l.strip()]

    if not stripped or not stripped[0].lstrip().startswith(MAGIC_PREFIX):
        raise ValueError(
            f"not a UDV recording (missing '{MAGIC_PREFIX}' header): {path}"
        )

    result = ExtractedData(file_path=path)

    # Global header / comment
    if stripped:
        result.header = stripped[0].strip()
    if len(stripped) > 1:
        result.comment = stripped[1].strip()

    # Every "Gate Depth [mm]" marker starts a new section; a file without
    # any marker is treated as a single section starting at the first line.
    gd_indices = [i for i, l in enumerate(stripped) if l.strip() == GATE_DEPTH_HEADER]
    for gd_idx in gd_indices or [0]:
        _parse_section(stripped, gd_idx, result)

    return result


def _parse_section(
    lines: list[str],
    gd_idx: int,
    result: ExtractedData,
) -> None:
    """Parse one gate-depth section (single- or multi-sensor alike).

    The section's column groups come from its units row (see
    :func:`_resolve_column_groups`); an uninterpretable units row raises
    ``ValueError``. Truncated or non-numeric depth rows are skipped silently
    (they add no frames), so a magic-bearing file with no real data rows
    still yields a usable empty :class:`ExtractedData` instead of raising.
    """
    if gd_idx + 2 >= len(lines):
        return
    try:
        depths = _parse_gate_depths(lines[gd_idx + 1])
    except ValueError:
        return
    if not depths:
        return
    gate_depths, groups = _resolve_column_groups(depths, lines[gd_idx + 2])
    n_cols = sum(stop - start for _, start, stop in groups)

    data_start = gd_idx + 3
    end = next(
        (
            i
            for i in range(data_start, len(lines))
            if lines[i].strip() == GATE_DEPTH_HEADER
        ),
        len(lines),
    )
    data_lines = lines[data_start:end]

    if data_lines and data_lines[0].strip().startswith(STAT_PREFIX):
        _parse_stat_section(data_lines, gate_depths, groups, result)
    else:
        for line in data_lines:
            _add_frames(line, gate_depths, groups, n_cols, result)


def _add_frames(
    line: str,
    gate_depths: list[float],
    groups: list[_ColumnGroup],
    n_cols: int,
    result: ExtractedData,
) -> None:
    """Parse one data row into one frame per column group.

    All groups of a row share the row's TBD / block / channel columns and the
    single gate-depth axis; a malformed row adds nothing.
    """
    parts = line.strip().split("\t")
    if len(parts) < n_cols + 1:
        return
    try:
        tbd = parse_comma_decimal(parts[n_cols])
        block = int(parts[n_cols + 1]) if len(parts) > n_cols + 1 else 0
        channel = int(parts[n_cols + 2]) if len(parts) > n_cols + 2 else 0
        values_by_group = [
            [parse_comma_decimal(p) for p in parts[start:stop]]
            for _, start, stop in groups
        ]
    except ValueError:
        return

    for (meas_type, _start, _stop), vals in zip(groups, values_by_group):
        result.frames.append(
            ChannelFrame(
                channel=channel,
                block=block,
                tbd_ms=tbd,
                meas_type=meas_type,
                gate_depths_mm=list(gate_depths),
                values=vals,
            )
        )


def _slice_group(row: list[float] | None, start: int, stop: int) -> list[float] | None:
    """Slice one per-group view out of a full-width stat row."""
    return None if row is None else row[start:stop]


def _parse_stat_section(
    lines: list[str],
    gate_depths: list[float],
    groups: list[_ColumnGroup],
    result: ExtractedData,
) -> None:
    """Parse a statistical summary block (mean / stddev / min / max).

    ``lines`` holds the section's data rows: index 0 is the
    "Statistical values based on :N values" line, index 1 the mean row,
    followed by alternating label/value pairs. Every row spans all column
    groups; each group is sliced out into its own frame on the shared axis.
    """
    if not lines:
        return
    n_prof = _parse_num(lines[0])
    n_cols = sum(stop - start for _, start, stop in groups)

    mean_row = _parse_stat_row(lines, 1, n_cols)

    labels: dict[str, list[float] | None] = {}
    for i in range(2, len(lines) - 1, 2):
        label = lines[i].strip().lower()
        val_row = _parse_stat_row(lines, i + 1, n_cols)
        if label in _STAT_LABELS["std_dev"]:
            labels["std_dev"] = val_row
        elif label in _STAT_LABELS["min"]:
            labels["min"] = val_row
        elif label in _STAT_LABELS["max"]:
            labels["max"] = val_row

    if mean_row is None:
        return

    # Trailing columns of the mean row: TBD, block, channel.
    parts = lines[1].strip().split("\t")
    block = int(parts[n_cols + 1]) if len(parts) > n_cols + 1 else 0
    channel = int(parts[n_cols + 2]) if len(parts) > n_cols + 2 else 0
    tbd = parse_comma_decimal(parts[n_cols]) if len(parts) > n_cols else 0.0

    for meas_type, start, stop in groups:
        result.frames.append(
            ChannelFrame(
                channel=channel,
                block=block,
                tbd_ms=tbd,
                meas_type=meas_type,
                gate_depths_mm=list(gate_depths),
                values=mean_row[start:stop],
                n_profiles=n_prof,
                std_dev=_slice_group(labels.get("std_dev"), start, stop),
                min_val=_slice_group(labels.get("min"), start, stop),
                max_val=_slice_group(labels.get("max"), start, stop),
            )
        )


def _parse_stat_row(lines: list[str], idx: int, n_cols: int) -> list[float] | None:
    if idx >= len(lines):
        return None
    parts = lines[idx].strip().split("\t")
    if len(parts) < n_cols:
        return None
    try:
        return [parse_comma_decimal(p) for p in parts[:n_cols]]
    except ValueError:
        return None


def _detect_n_profiles(d: ExtractedData, by_ch: dict[int, list[ChannelFrame]]) -> int:
    for f in d.frames:
        if f.n_profiles is not None:
            return f.n_profiles
    ch = min(by_ch.keys())
    first = by_ch[ch][0]
    return sum(
        1
        for f in d.frames
        if f.channel == ch and f.block == first.block and f.meas_type is first.meas_type
    )


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "data/echo/650.ADD"
    print(extract(target).describe())
