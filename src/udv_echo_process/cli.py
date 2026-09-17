"""Command-line entry points for the ``udv_echo_process`` package.

Console scripts (defined in ``[project.scripts]``):

    udv-inspect   — describe a recording setup
    udv-viz       — per-channel heatmaps + gate profiles
    udv-run-all   — batch RPM analysis + visualizations
    udv-acquire   — drive the running UDOP application (live path; see tools/live/README.md)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from udv_echo_process import run_all
from udv_echo_process.acquire import live
from udv_echo_process.acquire.config import ChannelSetting
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


def _acquire_report(value: object, as_json: bool) -> None:
    """Print a report: JSON for a machine, one ``field: value`` line each for a person."""
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")  # type: ignore[attr-defined]
    else:
        dumped = value
    if as_json:
        print(json.dumps(dumped, indent=2, default=str))
        return
    if isinstance(dumped, dict):
        for field, item in dumped.items():
            print(f"{field:<26}: {item}")
        return
    print(dumped)


def _acquire_store_directory(explicit: str | None) -> Path:
    """``--store-dir``, else ``UDV_STORE_DIR``, else a usage error naming both.

    Never a default: the cycle *asserts* the Store dialog's working directory against this and
    writes it when they differ, so a guessed path would point the instrument's store somewhere
    nobody asked for.
    """
    if explicit:
        return Path(explicit)
    from_environment = os.environ.get("UDV_STORE_DIR")
    if from_environment:
        return Path(from_environment)
    print(
        "no store directory: pass --store-dir, or set UDV_STORE_DIR to the directory the "
        "application's Store dialog shows",
        file=sys.stderr,
    )
    raise SystemExit(2)


def acquire_main(argv: list[str] | None = None) -> None:
    """``udv-acquire`` — the live path: read the screen, exercise a cycle, store a point, sweep.

    These commands drive the *running* application, so they only work from the session that owns
    its screen (``tools/live/README.md``); everything they report is a model from
    :mod:`udv_echo_process.acquire.actuator`, and ``--json`` prints it for a machine. Exit codes:
    0 ok, 1 a refused point or a failed verification, 2 usage or configuration.
    """
    parser = argparse.ArgumentParser(
        prog="udv-acquire",
        description="Drive the running UDOP application (live path)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def channel_argument(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--channel",
            type=int,
            default=None,
            help="measurement channel (default: the UDV_CHANNEL setting)",
        )

    status_parser = subcommands.add_parser("status", help="read the screen, pressing nothing")
    channel_argument(status_parser)
    status_parser.add_argument("--json", action="store_true")

    channel_parser = subcommands.add_parser(
        "channel", help="verify the measurement channel (writes it only if it differs)"
    )
    channel_parser.add_argument("number", type=int)

    preflight_parser = subcommands.add_parser(
        "preflight", help="one whole cycle with nothing stored"
    )
    channel_argument(preflight_parser)
    preflight_parser.add_argument("--seconds", type=float, default=2.0)
    preflight_parser.add_argument("--store-dir", default=None)
    preflight_parser.add_argument("--json", action="store_true")

    point_parser = subcommands.add_parser("point", help="one stored point")
    point_parser.add_argument("name")
    point_parser.add_argument("--seconds", type=float, required=True)
    channel_argument(point_parser)
    point_parser.add_argument("--store-dir", default=None)
    point_parser.add_argument("--json", action="store_true")

    sweep_parser = subcommands.add_parser(
        "sweep", help="a multi-point sweep, one JSONL entry per point"
    )
    sweep_parser.add_argument("--seconds", type=float, required=True)
    sweep_parser.add_argument("--rungs", required=True, help="1-based ladder indices, e.g. 1,2")
    channel_argument(sweep_parser)
    sweep_parser.add_argument("--store-dir", default=None)
    sweep_parser.add_argument("--name-prefix", default="sweep")
    sweep_parser.add_argument("--log", default=None, help="JSONL log (default: <store-dir>/sweep.jsonl)")
    sweep_parser.add_argument(
        "--sound-speed", type=float, default=live.DEFAULT_MEASUREMENT["sound_speed_ms"]
    )
    sweep_parser.add_argument(
        "--first-gate", type=float, default=live.DEFAULT_MEASUREMENT["first_gate_mm"]
    )
    sweep_parser.add_argument(
        "--depth", type=float, default=live.DEFAULT_MEASUREMENT["target_depth_mm"]
    )
    sweep_parser.add_argument("--prf", type=float, default=live.DEFAULT_MEASUREMENT["prf_us"])
    sweep_parser.add_argument(
        "--emissions", type=int, default=int(live.DEFAULT_MEASUREMENT["emissions_per_profile"])
    )
    sweep_parser.add_argument(
        "--burst", type=int, default=int(live.DEFAULT_MEASUREMENT["burst_length"])
    )

    decode_parser = subcommands.add_parser("decode", help="a stored file's own operation words")
    decode_parser.add_argument("path")
    channel_argument(decode_parser)
    decode_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    notes: list[str] = []
    as_json = bool(getattr(args, "json", False))
    # With --json the report is the only thing on stdout; the notes go to stderr.
    note_stream = sys.stderr if as_json else sys.stdout
    code = 0
    try:
        if args.command == "status":
            _acquire_report(live.status(args.channel, notes), as_json)
        elif args.command == "channel":
            verified, fingerprint = live.select_channel(args.number, notes)
            print(f"verified channel: {verified}")
            _acquire_report(fingerprint, as_json)
        elif args.command == "preflight":
            expected = None if args.store_dir is None else Path(args.store_dir)
            report = live.preflight(
                args.seconds, args.channel, expect_directory=expected, notes=notes
            )
            _acquire_report(report, as_json)
        elif args.command == "point":
            ok, result = live.point(
                args.name,
                args.seconds,
                _acquire_store_directory(args.store_dir),
                args.channel,
                notes,
            )
            print(f"stored: {result}" if ok else f"refused: {result}")
            code = 0 if ok else 1
        elif args.command == "sweep":
            directory = _acquire_store_directory(args.store_dir)
            outcomes = live.sweep(
                args.seconds,
                directory,
                [int(key) for key in args.rungs.split(",")],
                args.channel,
                name_prefix=args.name_prefix,
                log_path=Path(args.log) if args.log else directory / "sweep.jsonl",
                notes=notes,
                sound_speed_ms=args.sound_speed,
                first_gate_mm=args.first_gate,
                target_depth_mm=args.depth,
                prf_us=args.prf,
                emissions_per_profile=args.emissions,
                burst_length=args.burst,
            )
            for outcome in outcomes:
                key = getattr(outcome.point, "key", "?")
                reason = "" if outcome.reason is None else f" reason={outcome.reason}"
                print(f"k={key} ok={outcome.ok} status={outcome.status} file={outcome.file}{reason}")
            if as_json:
                _acquire_report([outcome.__dict__ for outcome in outcomes], True)
            code = 0 if outcomes and all(outcome.ok for outcome in outcomes) else 1
        else:  # decode
            measured = args.channel if args.channel is not None else ChannelSetting().channel
            _acquire_report(live.decode(Path(args.path), measured), as_json)
    finally:
        for note in notes:
            print(f"note: {note}", file=note_stream)
    raise SystemExit(code)


#: The command a module-level invocation names first: `python -m udv_echo_process.cli <name> ...`
#: — the form the live path uses, because a command that drives the GUI has to be started in the
#: session that owns the screen and a dispatcher can only name a module (`tools/live/README.md`).
_COMMANDS = {
    "acquire": acquire_main,
    "inspect": inspect_main,
    "run-all": run_all_main,
    "viz": viz_main,
}


if __name__ == "__main__":
    _named = sys.argv[1] if len(sys.argv) > 1 else ""
    if _named not in _COMMANDS:
        print(
            f"usage: python -m udv_echo_process.cli {{{','.join(sorted(_COMMANDS))}}} ...",
            file=sys.stderr,
        )
        raise SystemExit(2)
    _COMMANDS[_named](sys.argv[2:])
