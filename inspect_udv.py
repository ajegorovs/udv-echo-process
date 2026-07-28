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

from parse_udv import extract


def inspect(filepath: str | Path) -> None:
    d = extract(filepath)
    print(d.describe())


def main() -> None:
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["data-echo/650.ADD"]
    for t in targets:
        inspect(t)


if __name__ == "__main__":
    main()
