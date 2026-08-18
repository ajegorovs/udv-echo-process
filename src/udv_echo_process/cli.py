"""Command-line entry points for the ``udv_echo_process`` package.

Console scripts (defined in ``[project.scripts]``):

    udv-inspect   — describe a recording setup
    udv-viz       — per-channel heatmaps + gate profiles
    udv-run-all   — batch RPM analysis + visualizations
    udv-project   — temporal projections over an image sequence
    udv-mixvel    — optical mixer particle pipeline
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from udv_echo_process import run_all
from udv_echo_process.analysis.feature_track import plot_flow, track_grid_flow
from udv_echo_process.analysis.image_projection import (
    frame_paths,
    project_images,
    save_projections,
    select_frames,
)
from udv_echo_process.analysis.mixer import (
    crop_to_box,
    deflicker,
    largest_component_box,
    normalize,
    particle_mask,
    scale_box,
    top_hat_enhanced,
)
from udv_echo_process.analysis.temporal_projection import temporal_projections
from udv_echo_process.parser import extract
from udv_echo_process.viz import DEFAULT_OUTPUT_DIR, _discover_data_files, plot_all

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
    targets = [Path(t) for t in args.files] or _discover_data_files()
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


def project_main(argv: list[str] | None = None) -> None:
    """``udv-project`` — temporal Min/Max/Mean/Std projection of an image sequence."""
    parser = argparse.ArgumentParser(
        prog="udv-project",
        description="Temporal Min/Max/Mean/Std projection over an image sequence",
    )
    parser.add_argument("images", help="image file (a sequence is inferred from siblings) or folder")
    parser.add_argument("--step", type=int, default=1, help="use every Nth frame (default: 1)")
    parser.add_argument("--max-frames", type=int, default=None, help="max frames to use")
    parser.add_argument("--chunk-size", type=int, default=32, help="frames loaded at once (default: 32)")
    parser.add_argument("--output-dir", default="outputs", help="output directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    result = project_images(
        args.images,
        step=args.step,
        max_frames=args.max_frames,
        chunk_size=args.chunk_size,
    )
    logger.info("projected %d frames", result.count)
    written = save_projections(result, args.output_dir)
    logger.info("wrote %s", ", ".join(str(p) for p in written.values()))


def mixvel_main(argv: list[str] | None = None) -> None:
    """``udv-mixvel`` — optical mixer particle pipeline (Mixer_velocimetry.nb port)."""
    parser = argparse.ArgumentParser(
        prog="udv-mixvel",
        description="Optical mixer particle pipeline (port of Mixer_velocimetry.nb)",
    )
    parser.add_argument("images", help="image file or folder; a sequence is inferred")
    parser.add_argument("--step", type=int, default=1, help="use every Nth frame (default: 1)")
    parser.add_argument("--max-frames", type=int, default=None, help="max frames to use")
    parser.add_argument("--grid", type=int, default=20, help="feature-track seed spacing (px)")
    parser.add_argument("--convention", default="sample", choices=["sample", "population"])
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--output-dir", default="outputs", help="output directory")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    paths = frame_paths(args.images) if Path(args.images).is_dir() else [Path(args.images)]
    if not paths:
        raise SystemExit(f"no images found at {args.images}")
    selected = select_frames(paths, step=args.step, max_frames=args.max_frames)
    if len(selected) < 2:
        raise SystemExit("need at least 2 frames")
    logger.info("loaded %d frames from %s", len(selected), selected[0].parent)

    from PIL import Image

    def load(i: int) -> np.ndarray:
        im = Image.open(selected[i])
        if im.mode != "L":
            im = im.convert("L")
        return np.asarray(im)

    first = load(0)
    mask = particle_mask(top_hat_enhanced(first))  # top-hat -> binarize -> clean
    pbox = scale_box(largest_component_box(mask), first.shape, scale=1.0)
    mask_b = crop_to_box([mask], pbox)[0]
    logger.info("particle ROI box=%s", pbox)

    enhanced = [
        normalize(
            mask_b
            * top_hat_enhanced(crop_to_box([load(i)], pbox)[0])
        )
        for i in range(len(selected))
    ]

    corrected = deflicker(enhanced)

    flow = track_grid_flow(enhanced[0], enhanced[1], grid=args.grid)
    flow_path = Path(args.output_dir) / "flow.png"
    plot_flow(flow, enhanced[0].shape, flow_path, dpi=args.dpi)
    logger.info("tracked %d points -> %s", len(flow), flow_path)

    projections = temporal_projections(
        [corrected[i] for i in range(len(corrected))], convention=args.convention
    )
    written = save_projections(
        projections, Path(args.output_dir), prefix="particles_"
    )
    logger.info(
        "wrote %s",
        ", ".join(str(p) for p in [flow_path, *written.values()]),
    )
