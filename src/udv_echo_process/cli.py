"""Command-line entry points for the ``udv_echo_process`` package.

Console scripts (defined in ``[project.scripts]``):

    udv-inspect   — describe a recording setup
    udv-viz       — per-channel heatmaps + gate profiles
    udv-run-all   — batch RPM analysis + visualizations
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from udv_echo_process import run_all
from udv_echo_process.io import load
from udv_echo_process.io.dop.bdd import sniff_bdd
from udv_echo_process.parser import MAGIC_PREFIX, extract
from udv_echo_process.provenance import ArtifactBundle
from udv_echo_process.viz import DEFAULT_OUTPUT_DIR, discover_data_files, plot_all

logger = logging.getLogger(__name__)

DEFAULT_TARGET = "data/echo/650.ADD"


def _describe_bundle(bundle: ArtifactBundle) -> str:
    """Typed summary of a decoded ``.BDD`` :class:`ArtifactBundle`."""
    recording = bundle.recording
    asset = recording.source_asset
    lines = [
        "=" * 58,
        f"  File: {asset.file_name}",
        f"  Format: BDD (binary, {asset.source.device})",
        f"  Content SHA-256: {asset.content_sha256[:16]}…  ({asset.byte_size} bytes)",
        f"  Acquisition mode: {recording.acquisition_mode.value}",
        "=" * 58,
    ]
    for stream in recording.streams:
        cfg = stream.config
        data = stream.data
        channel = stream.acquisition.channel.device_channel
        descriptor = stream.descriptor
        lines.append(
            f"  Channel {channel}  ({descriptor.quantity.value}, {descriptor.unit}):"
        )
        lines.append(
            f"    Samples x gates:  {data.values.shape[0]} x {data.values.shape[1]}"
        )
        lines.append(
            f"    Gate depths:      {data.gate_depths_mm[0]:.2f} - "
            f"{data.gate_depths_mm[-1]:.2f} mm"
        )
        lines.append(f"    Duration:         {data.time_s[-1] - data.time_s[0]:.2f} s")
        if cfg.source_freq_khz is not None:
            lines.append(f"    Emit frequency:   {cfg.source_freq_khz:.0f} kHz")
        if cfg.pulse_repetition_freq_hz is not None:
            lines.append(f"    PRF:              {cfg.pulse_repetition_freq_hz:.0f} Hz")
        if cfg.sound_speed_ms is not None:
            lines.append(f"    Sound speed:      {cfg.sound_speed_ms:.0f} m/s")
        if cfg.resolution_mm is not None:
            lines.append(f"    Resolution:       {cfg.resolution_mm:.4f} mm")
        if cfg.velo_max_ms is not None:
            lines.append(f"    Max velocity:     ±{cfg.velo_max_ms:.2f} mm/s")
        lines.append("")
    return "\n".join(lines)


def _inspect_target(path: Path) -> str:
    """Describe one recording, dispatching on its *bytes*.

    ``ASCUDOPV`` text stays on the ``.ADD`` path (:func:`parser.extract`);
    recognized ``BINUDOPV`` bytes go through :func:`io.load` into a typed
    :class:`ArtifactBundle` summary. There is no adapter between the two.
    """
    head = path.read_bytes()[:128]
    if head.lstrip().split(b"\n", 1)[0].startswith(MAGIC_PREFIX.encode()):
        return extract(path).describe()
    if sniff_bdd(head):
        return _describe_bundle(load(path))
    raise ValueError(
        f"not a UDV recording (no '{MAGIC_PREFIX}' header and no DOP3000 "
        f".BDD magic): {path}"
    )


def inspect_main(argv: list[str] | None = None) -> None:
    """``udv-inspect`` — print the recording setup description.

    Dispatches by content: ``.ADD`` text via :func:`extract`, recognized
    ``.BDD`` bytes via :func:`io.load`. Unrecognised files (misnamed images,
    unknown bytes) are reported per file; any failure makes the process exit
    non-zero.
    """
    parser = argparse.ArgumentParser(
        prog="udv-inspect",
        description="Inspect a UDV recording (.ADD or .BDD), dispatching by content",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help=f"recordings to inspect (default: {DEFAULT_TARGET})",
    )
    args = parser.parse_args(argv)

    targets = [Path(t) for t in args.files] or [Path(DEFAULT_TARGET)]
    failures = 0
    for target in targets:
        try:
            print(_inspect_target(target))
        except (ValueError, OSError) as exc:
            failures += 1
            print(f"udv-inspect: {exc}", file=sys.stderr)
    if failures:
        raise SystemExit(1)


def viz_main(argv: list[str] | None = None) -> None:
    """``udv-viz`` — render heatmaps + gate profiles for one or many files."""
    parser = argparse.ArgumentParser(
        prog="udv-viz",
        description="Render per-channel heatmaps + gate profiles",
    )
    parser.add_argument(
        "files", nargs="*", help=".ADD files to plot (default: all in data/)"
    )
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
    parser.add_argument(
        "--data-dir", default="data/echo", help="directory of raw .ADD files"
    )
    parser.add_argument("--output-dir", default="outputs", help="output directory")
    args = parser.parse_args(argv)

    run_all.main(data_dir=args.data_dir, output_dir=args.output_dir)
