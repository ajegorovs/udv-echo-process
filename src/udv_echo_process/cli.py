"""Command-line entry points for the ``udv_echo_process`` package.

Console scripts (defined in ``[project.scripts]``):

    udv-inspect   — describe a recording setup
    udv-viz       — per-channel heatmaps + gate profiles
    udv-run-all   — batch RPM analysis + visualizations
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from udv_echo_process import run_all
from udv_echo_process.parser import extract
from udv_echo_process.viz import DEFAULT_OUTPUT_DIR, discover_data_files, plot_all

logger = logging.getLogger(__name__)

DEFAULT_TARGET = "data/echo/650.ADD"


def inspect_main(argv: list[str] | None = None) -> None:
    """``udv-inspect`` — print the recording setup description."""
    parser = argparse.ArgumentParser(
        prog="udv-inspect",
        description="Inspect a UDV .ADD recording setup",
    )
    parser.add_argument(
        "files", nargs="*",
        help=f".ADD files to inspect (default: {DEFAULT_TARGET})",
    )
    args = parser.parse_args(argv)

    targets = [Path(t) for t in args.files] or [Path(DEFAULT_TARGET)]
    for t in targets:
        print(extract(t).describe())


def viz_main(argv: list[str] | None = None) -> None:
    """``udv-viz`` — render heatmaps + gate profiles for one or many files."""
    parser = argparse.ArgumentParser(
        prog="udv-viz",
        description="Render per-channel heatmaps + gate profiles",
    )
    parser.add_argument("files", nargs="*", help=".ADD files to plot (default: all in data/)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dpi", type=int, default=150)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    targets = [Path(t) for t in args.files] or discover_data_files()
    for t in targets:
        logger.info("processing %s", t)
        plot_all(extract(t), output_dir=args.output_dir, dpi=args.dpi)


def run_all_main(argv: list[str] | None = None) -> None:
    """``udv-run-all`` — batch RPM analysis + visualizations."""
    parser = argparse.ArgumentParser(
        prog="udv-run-all",
        description="Batch UDV RPM analysis + visualizations",
    )
    parser.add_argument("--data-dir", default="data/echo", help="directory of raw .ADD files")
    parser.add_argument("--output-dir", default="outputs", help="output directory")
    args = parser.parse_args(argv)

    run_all.main(data_dir=args.data_dir, output_dir=args.output_dir)
