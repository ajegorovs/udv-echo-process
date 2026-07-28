"""Inspect UDV data files: reconstruct recording setup from file composition.

Usage:
    uv run inspect_udv.py <file.ADD> [<file2.ADD> ...]
    uv run inspect_udv.py data-echo/650.ADD
    uv run inspect_udv.py data-4-sensor-velocity/200RPM.ADD
    uv run inspect_udv.py data-echo-4-sensors-2x2/300RPM.ADD
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from parse_udv import extract, MeasType


def inspect(filepath: str | Path) -> None:
    path = Path(filepath)
    d = extract(path)

    frames = d.frames
    by_ch = d.by_channel()
    by_blk = d.by_block()

    is_multi = len(by_ch) > 1 or len(by_blk) > 1
    fmt = "stat" if any(f.n_profiles is not None for f in frames) else "raw"
    n_blks = len(by_blk)

    print(f"{'=' * 60}")
    print(f"  File: {path.name}")
    print(f"  Header: {d.header}")
    print(f"  Comment: {d.comment}")
    print(f"{'=' * 60}")
    print(f"  Recording type:  {'multi-sensor' if is_multi else 'single-sensor'}")
    print(f"  Measurement:     {d.meas_type.value}")
    print(f"  File format:     {fmt}")
    print(f"  Total frames:    {len(frames)}")
    print(f"  Channels:        {sorted(by_ch.keys())}")

    if is_multi:
        n_prof = _detect_n_profiles(d, by_ch, by_blk)
        print(f"  Profiles/block:  {n_prof}")
        print(f"  Total blocks:    {n_blks}")
    else:
        print(f"  Block:           {by_blk_info(by_blk)}")

    print()
    print(f"  {'Ch':>4s}  {'Gates':>5s}  {'Depth range':>18s}  {'Frames':>6s}  {'Blocks':>7s}  {'TBD [ms]':>10s}  {'P':>3s}")
    print(f"  {'-' * 60}")
    for ch in sorted(by_ch.keys()):
        ch_frames = by_ch[ch]
        gd = ch_frames[0].gate_depths_mm
        tbds = [f.tbd_ms for f in ch_frames]
        p = ch_frames[0].n_profiles if ch_frames[0].n_profiles is not None else ""
        print(
            f"  {ch:4d}  {len(gd):5d}  "
            f"{gd[0]:6.2f}-{gd[-1]:6.2f} mm  "
            f"{len(ch_frames):6d}  "
            f"{ch_frames[0].block:3d}-{ch_frames[-1].block:3d}  "
            f"{min(tbds):6.2f}-{max(tbds):6.2f}  "
            f"{p!s:>3s}"
        )

    # Total time estimate
    all_tbds = sorted(set(f.tbd_ms for f in frames))
    if len(all_tbds) > 1 and is_multi:
        total_s = (max(all_tbds) - min(all_tbds)) / 1000
        dt_ms = float(np.mean(np.diff(sorted(set(all_tbds)))))
        print(f"\n  Duration: {total_s:.1f} s  |  Mean dT: {dt_ms:.2f} ms")

    # Recording order
    if is_multi:
        _show_recording_order(frames)

    print()


def by_blk_info(by_blk: dict) -> str:
    keys = sorted(by_blk.keys())
    if not keys:
        return "-"
    return f"{keys[0]} - {keys[-1]}"


def _detect_n_profiles(d, by_ch, by_blk) -> int:
    # Prefer explicit n_profiles from stat format
    for f in d.frames:
        if f.n_profiles is not None:
            return f.n_profiles
    # Raw format: count rows per (block, channel) group
    ch = sorted(by_ch.keys())[0]
    blk = by_ch[ch][0].block
    return sum(1 for f in d.frames if f.channel == ch and f.block == blk)


def _show_recording_order(frames) -> None:
    """Reconstruct and display the channel recording cycle."""
    seen: set[int] = set()
    cycle: list[int] = []
    for f in frames:
        if f.channel not in seen:
            seen.add(f.channel)
            cycle.append(f.channel)
        if len(seen) == len(set(f.channel for f in frames)):
            break

    if len(cycle) > 1:
        seq = " -> ".join(str(ch) for ch in cycle) + " -> ..."
        print(f"  Recording order:  Ch [{seq}]")

    by_ch: dict[int, list] = {}
    for f in frames:
        by_ch.setdefault(f.channel, []).append(f)
    first_gds = {ch: by_ch[ch][0].gate_depths_mm for ch in by_ch}
    unique_gds = set(tuple(gd) for gd in first_gds.values())
    if len(unique_gds) == 1:
        n_gates = len(first_gds[list(first_gds.keys())[0]])
        print(f"  Gate setup:       identical across all channels ({n_gates} gates)")
    else:
        print(f"  Gate setup:       CHANNEL-SPECIFIC")
        for ch, gd in first_gds.items():
            print(f"                     Ch {ch}: {len(gd)} gates  [{gd[0]:.2f}-{gd[-1]:.2f}] mm")


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["data-echo/650.ADD"]
    for t in targets:
        inspect(t)


if __name__ == "__main__":
    main()
