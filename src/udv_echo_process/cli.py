"""Command-line entry points for the ``udv_echo_process`` package.

Console scripts (defined in ``[project.scripts]``):

    udv-inspect   — describe a recording setup
    udv-viz       — per-channel heatmaps + gate profiles
    udv-run-all   — batch RPM analysis + visualizations
    udv-acquire   — drive the running UDOP application (live path; see tools/live/README.md)

The module-invoked verbs (``python -m udv_echo_process.cli <name> ...``, the
form the analysis plan's verification section names) carry the report-writing
commands alongside ``acquire``: ``sweep-inventory`` writes the WP0 mixer-sweep
manifest and QC summary from the committed BDD files, ``reference-repeat``
writes the WP1 reference-repeatability table, provenance document and figure
from that manifest, ``resolution-ladder`` writes the WP2 resolution axis,
``burst-ladder`` the WP2 burst-length axis, ``prf-ladder`` the WP2
pulse-repetition-frequency axis and ``gain-power-screen`` the velocity-only
TGC and emitting-power screening — levels, pairs and figure — all against the WP1
envelope, and none of them touches an instrument.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from udv_echo_process import run_all
from udv_echo_process.acquire import campaign, driver, live
from udv_echo_process.acquire.actuator import ProcessMode
from udv_echo_process.acquire.config import ChannelSetting
from udv_echo_process.acquire.log import PointStatus, point_records, read_entries
from udv_echo_process.analysis import (
    burst_ladder,
    gain_power_screen,
    prf_ladder,
    reference_repeat,
    resolution_ladder,
    sweep_inventory,
)
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


def sweep_inventory_main(argv: list[str] | None = None) -> None:
    """``sweep-inventory`` — write the WP0 mixer-sweep manifest and QC summary.

    Reads the committed ``.BDD`` points through the public reader and writes
    ``manifest.csv`` and ``qc-summary.json`` into the report directory, then
    exits 0 when every WP0 gate check holds and 1 otherwise, naming the failed
    checks on stderr. It touches nothing but those two files: no instrument, no
    cache, no analysis beyond the inventory.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sweep-inventory",
        description=(
            "Inventory the committed mixer sensitivity sweep: one manifest row "
            "per BDD file plus the WP0 QC summary"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=sweep_inventory.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=sweep_inventory.REPORT_DIR.as_posix(),
        help="directory to write manifest.csv and qc-summary.json into",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record in the QC summary (default: the checkout's "
            "short git SHA)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    inventory = sweep_inventory.write_sweep_inventory(
        Path(args.dataset_root),
        report_dir,
        analysis_commit=args.analysis_commit,
    )
    print(
        f"{inventory.files} / {inventory.expected_files} files, axes "
        f"{dict(sorted(inventory.axis_counts.items()))}"
    )
    print(f"manifest : {report_dir / sweep_inventory.MANIFEST_NAME}")
    print(f"summary  : {report_dir / sweep_inventory.QC_NAME}")
    print(f"commit   : {inventory.analysis_commit}")
    failed = [name for name, ok in sorted(inventory.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sweep-inventory: check failed: {name}", file=sys.stderr)
    raise SystemExit(0 if inventory.ok else 1)


def reference_repeat_main(argv: list[str] | None = None) -> None:
    """``reference-repeat`` — write the WP1 repeatability artefacts.

    Selects the only same-settings repeat from the WP0 manifest, re-checks both
    source hashes and the decoded settings, and writes ``reference-repeat.csv``,
    ``reference-repeat.provenance.json`` and ``figures/reference-repeat.png``
    into the report directory. Exits 0 on success and 1 with the named reason on
    stderr when the selection, the bytes or the comparison itself cannot be
    trusted (never a traceback, and never a half-written artefact). It touches
    nothing but those three files: no instrument, no cache.
    """
    parser = argparse.ArgumentParser(
        prog="udv-reference-repeat",
        description=(
            "Quantify the reference-repeatability bound of the committed mixer "
            "sweep: the prf/600 vs res/1-8 repeat, depth-resolved"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=reference_repeat.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=reference_repeat.REPORT_DIR.as_posix(),
        help="directory to write the WP1 artefacts into",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "WP0 manifest the repeat pair is selected from (default: "
            "<report-dir>/manifest.csv)"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record (default: the checkout's short git SHA; pass the "
            "recorded commit to reproduce the committed artefacts byte for byte)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    try:
        model = reference_repeat.write_reference_repeat(
            Path(args.dataset_root),
            report_dir,
            manifest_path=None if args.manifest is None else Path(args.manifest),
            analysis_commit=args.analysis_commit,
        )
    except reference_repeat.ReferenceRepeatError as exc:
        print(f"udv-reference-repeat: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    envelope = model.envelope
    print(
        f"{reference_repeat.DIFFERENCE_DEFINITION} "
        f"({model.input_a.profiles} / {model.input_b.profiles} profiles, "
        f"{model.common.gates} gates)"
    )
    print(
        f"common view : {model.common.revolutions} rev = "
        f"{model.common.window_s:.4g} s "
        f"({model.common.profiles_a} / {model.common.profiles_b} profiles)"
    )
    print(
        f"envelope    : {envelope.value_mm_s:.4g} mm/s "
        f"({envelope.metric}, gate {envelope.gate_index} at "
        f"{envelope.depth_mm:.4g} mm); median |per-gate mean| "
        f"{envelope.median_abs_mean_difference_mm_s:.4g} mm/s"
    )
    print(f"table       : {report_dir / reference_repeat.CSV_NAME}")
    print(f"provenance  : {report_dir / reference_repeat.PROVENANCE_NAME}")
    print(
        f"figure      : {report_dir / reference_repeat.FIGURES_DIRNAME / reference_repeat.FIGURE_NAME}"
    )
    print(f"commit      : {model.analysis_commit}")
    raise SystemExit(0)


def resolution_ladder_main(argv: list[str] | None = None) -> None:
    """``resolution-ladder`` — write the WP2 resolution-axis artefacts.

    Selects every ``res`` recording from the WP0 manifest, re-checks each source
    hash and decoded setting, and writes ``resolution-levels.csv``,
    ``resolution-pairs.csv``, ``resolution-ladder.provenance.json`` and
    ``figures/resolution-ladder.png`` into the report directory, comparing every
    pair to the committed WP1 repeatability envelope. Exits 0 on success and 1
    with the named reason on stderr when the selection, the bytes, the envelope or
    the alignment cannot be trusted (never a traceback, and never a half-written
    artefact). It touches nothing but those four files: no instrument, no cache.
    """
    parser = argparse.ArgumentParser(
        prog="udv-resolution-ladder",
        description=(
            "Analyse the committed mixer sweep's resolution ladder: depth-resolved "
            "metrics per decoded pitch, every level pair on common knots, and the "
            "effect against the WP1 repeatability envelope"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=resolution_ladder.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=resolution_ladder.REPORT_DIR.as_posix(),
        help="directory to write the WP2 artefacts into",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "WP0 manifest the ladder is selected from (default: "
            "<report-dir>/manifest.csv)"
        ),
    )
    parser.add_argument(
        "--envelope",
        default=None,
        help=(
            "WP1 provenance the repeatability envelope is read from (default: "
            "<report-dir>/reference-repeat.provenance.json)"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record (default: the checkout's short git SHA; pass the "
            "recorded commit to reproduce the committed artefacts byte for byte)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    try:
        model = resolution_ladder.write_resolution_ladder(
            Path(args.dataset_root),
            report_dir,
            manifest_path=None if args.manifest is None else Path(args.manifest),
            envelope_path=None if args.envelope is None else Path(args.envelope),
            analysis_commit=args.analysis_commit,
        )
    except resolution_ladder.ResolutionLadderError as exc:
        print(f"udv-resolution-ladder: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    findings = resolution_ladder.provenance_document(model)["findings"]
    gate = findings["envelope_gate"]
    information = findings["information"]
    coarsest = findings["coarsest_pitch"]
    print(
        f"levels      : {model.common.levels} decoded pitches "
        f"{model.levels[0].pitch_mm:.4g}-{model.levels[-1].pitch_mm:.4g} mm, "
        f"{len(model.pairs)} pairs"
    )
    print(
        f"common view : {model.common.revolutions} rev = "
        f"{model.common.window_s:.4g} s; support "
        f"{model.common.support_min_mm:.6g}-{model.common.support_max_mm:.6g} mm"
    )
    print(
        f"envelope    : {model.envelope.value_mm_s:.4g} mm/s "
        f"({model.envelope.metric}, {model.envelope.path}); "
        f"{gate['pairs_above_envelope']} / {gate['pairs']} pairs above it, worst "
        f"{gate['max_ratio_to_envelope']:.3g} x"
    )
    print(
        f"focus pair  : {information['fine_path']} ({information['fine_pitch_mm']:.4g} mm) "
        f"vs {information['coarse_path']} "
        f"({information['coarse_pitch_mm']:.4g} mm): max |diff| "
        f"{information['max_abs_difference_mm_s']:.4g} mm/s at "
        f"{information['max_abs_difference_depth_mm']:.4g} mm = "
        f"{information['max_abs_difference_mm_s'] / model.envelope.value_mm_s:.3g} x "
        f"envelope; sub-knot detail peak "
        f"{information['detail_max_abs_mm_s']:.4g} mm/s"
    )
    print(
        f"coarsest    : {coarsest['label']} at {coarsest['pitch_mm']:.4g} mm, "
        f"correlation length {coarsest['correlation_length_mm']:.4g} mm = "
        f"{coarsest['correlation_length_over_pitch']:.3g} pitches"
    )
    print(f"levels table: {report_dir / resolution_ladder.LEVELS_NAME}")
    print(f"pairs table : {report_dir / resolution_ladder.PAIRS_NAME}")
    print(f"provenance  : {report_dir / resolution_ladder.PROVENANCE_NAME}")
    print(
        f"figure      : {report_dir / resolution_ladder.FIGURES_DIRNAME / resolution_ladder.FIGURE_NAME}"
    )
    print(f"commit      : {model.analysis_commit}")
    raise SystemExit(0)


def burst_ladder_main(argv: list[str] | None = None) -> None:
    """``burst-ladder`` — write the WP2 burst-length-axis artefacts.

    Selects every ``burst_len`` recording from the WP0 manifest, re-checks each source hash
    and decoded setting, refuses a ladder where a setting other than the burst length moved,
    and writes ``burst-levels.csv``, ``burst-pairs.csv``, ``burst-ladder.provenance.json``
    and ``figures/burst-ladder.png`` into the report directory, comparing every level pair to
    the committed WP1 repeatability envelope and the matched temporal view to the temporal
    repeat floor the committed WP1 curves imply. Exits 0 on success and 1 with the named
    reason on stderr when the selection, the bytes, the envelope or the temporal floor cannot
    be trusted (never a traceback, never a half-written artefact). It touches nothing but
    those four files: no instrument, no cache.
    """
    parser = argparse.ArgumentParser(
        prog="udv-burst-ladder",
        description=(
            "Analyse the committed mixer sweep's burst-length ladder: depth-resolved metrics "
            "and matched full-record temporal metrics per decoded cycle count, every level "
            "pair on the shared knots, and every effect against the WP1 repeatability envelope"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=burst_ladder.inventory.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=burst_ladder.inventory.REPORT_DIR.as_posix(),
        help="directory to write the WP2 burst artefacts into",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="WP0 manifest the ladder is selected from (default: <report-dir>/manifest.csv)",
    )
    parser.add_argument(
        "--envelope",
        default=None,
        help=(
            "WP1 provenance the repeatability envelope and temporal floor are read from "
            "(default: <report-dir>/reference-repeat.provenance.json)"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record (default: the checkout's short git SHA; pass the recorded "
            "commit to reproduce the committed artefacts byte for byte)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    try:
        model = burst_ladder.write_burst_ladder(
            Path(args.dataset_root),
            report_dir,
            manifest_path=None if args.manifest is None else Path(args.manifest),
            envelope_path=None if args.envelope is None else Path(args.envelope),
            analysis_commit=args.analysis_commit,
        )
    except burst_ladder.BurstLadderError as exc:
        print(f"udv-burst-ladder: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    findings = burst_ladder.provenance_document(model)["findings"]
    gate = findings["envelope_gate"]
    focus = findings["focus_18_vs_20"]
    window = findings["focus_window_16_20"]
    temporal = findings["temporal_bandwidth"]
    cycles = [row["cycles"] for row in model.levels]
    print(
        f"levels      : {len(model.levels)} decoded burst lengths {cycles[0]}-{cycles[-1]} "
        f"cycles, {len(model.pairs)} pairs, clean OFAT ladder"
    )
    print(
        f"common view : {model.common['revolutions']} rev = {model.common['window_s']:.4g} s; "
        f"support {model.common['support_min_mm']:.6g}-{model.common['support_max_mm']:.6g} mm; "
        f"temporal {model.temporal['segment_profiles']}-profile segments at "
        f"{model.temporal['profile_period_s']:.6g} s "
        f"({model.temporal['frequency_resolution_hz']:.4g} Hz resolution)"
    )
    print(
        f"envelope    : {model.envelope.value_mm_s:.4g} mm/s ({model.envelope.metric}); "
        f"{gate['pairs_above_envelope']} / {gate['pairs']} pairs above it, worst "
        f"{gate['max_ratio_to_envelope']:.3g} x, "
        f"{gate['clearances_involving_the_longest_bursts']} of them at the longest bursts"
    )
    print(
        f"focus 18/20 : max |diff| {focus['max_abs_difference_mm_s']:.4g} mm/s at "
        f"{focus['max_abs_difference_depth_mm']:.4g} mm = {focus['ratio_to_envelope']:.3g} x "
        f"envelope, {focus['knots_above_envelope']} of {focus['knots']} knots above it; "
        f"16-20-cycle region {window['pairs']} pairs, "
        f"{window['pairs_above_envelope']} clearing it"
    )
    print(
        f"bandwidth   : in-band power above 10 Hz {temporal['hf_share_min']:.4g}-"
        f"{temporal['hf_share_max']:.4g}, against a same-settings floor of "
        f"{temporal['floor_hf_share_difference']:.4g} in the same share"
    )
    print(f"levels table: {report_dir / burst_ladder.LEVELS_NAME}")
    print(f"pairs table : {report_dir / burst_ladder.PAIRS_NAME}")
    print(f"provenance  : {report_dir / burst_ladder.PROVENANCE_NAME}")
    print(
        f"figure      : {report_dir / burst_ladder.FIGURES_DIRNAME / burst_ladder.FIGURE_NAME}"
    )
    print(f"commit      : {model.analysis_commit}")
    raise SystemExit(0)


def prf_ladder_main(argv: list[str] | None = None) -> None:
    """``prf-ladder`` — write the WP2 PRF-axis artefacts.

    Selects every ``prf`` recording from the WP0 manifest, orders the ladder by decoded
    pulse-repetition period, re-checks each source hash, every shared decoded cell and the two
    cells the key derives (the PRF in Hz and the ±Nyquist velocity scale), refuses a ladder where
    anything other than the key moved, and writes ``prf-levels.csv``, ``prf-pairs.csv``,
    ``prf-ladder.provenance.json`` and ``figures/prf-ladder.png`` into the report directory:
    per-level velocity metrics, the actual profile rate from the timestamps, the ``|v| / Vmax``
    load fractions, the wrap-like discontinuities, the matched-physical-duration temporal view
    with its repeat floor, every level pair against the committed WP1 envelope, and the plan's
    400-us versus 250-us decision. Exits 0 on success and 1 with the named reason on stderr when
    the selection, the bytes, the envelope, the temporal floor or the key's scaling cannot be
    trusted (never a traceback, never a half-written artefact). It touches nothing but those four
    files: no instrument, no cache.
    """
    parser = argparse.ArgumentParser(
        prog="udv-prf-ladder",
        description=(
            "Analyse the committed mixer sweep's PRF ladder: velocity headroom and usable "
            "temporal bandwidth per decoded pulse-repetition period, every level pair on the "
            "shared knots and bands, and every effect against the WP1 repeatability envelope"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=prf_ladder.inventory.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=prf_ladder.inventory.REPORT_DIR.as_posix(),
        help="directory to write the WP2 PRF artefacts into",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="WP0 manifest the ladder is selected from (default: <report-dir>/manifest.csv)",
    )
    parser.add_argument(
        "--envelope",
        default=None,
        help=(
            "WP1 provenance the repeatability envelope and temporal floor are read from "
            "(default: <report-dir>/reference-repeat.provenance.json)"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record (default: the checkout's short git SHA; pass the recorded commit "
            "to reproduce the committed artefacts byte for byte)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    try:
        model = prf_ladder.write_prf_ladder(
            Path(args.dataset_root),
            report_dir,
            manifest_path=None if args.manifest is None else Path(args.manifest),
            envelope_path=None if args.envelope is None else Path(args.envelope),
            analysis_commit=args.analysis_commit,
        )
    except prf_ladder.PrfLadderError as exc:
        print(f"udv-prf-ladder: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    findings = prf_ladder.provenance_document(model)["findings"]
    gate = findings["effect_gate"]
    headroom = findings["velocity_headroom"]
    bandwidth = findings["temporal_bandwidth"]
    decision = findings["focus_decision"]
    periods = [row["prf_period_us"] for row in model.levels]
    print(
        f"levels      : {len(model.levels)} decoded PRF periods {periods[0]:g}-{periods[-1]:g} "
        f"us, {len(model.pairs)} pairs, clean OFAT ladder with a scaled velocity range"
    )
    print(
        f"common view : {model.common['revolutions']} rev = {model.common['window_s']:.4g} s; "
        f"support {model.common['support_min_mm']:.6g}-{model.common['support_max_mm']:.6g} mm; "
        f"matched {model.common['segment_target_s']:g} s segments, nominal resolution "
        f"{model.temporal['nominal_resolution_hz']:.4g} Hz"
    )
    print(
        f"rate/band   : profile rate {min(bandwidth['profile_rate_hz'].values()):.4g}-"
        f"{max(bandwidth['profile_rate_hz'].values()):.4g} Hz; usable bandwidth "
        f"{min(bandwidth['usable_bandwidth_hz']):.4g}-{max(bandwidth['usable_bandwidth_hz']):.4g} "
        f"Hz; spectra compared in {bandwidth['band_hz'][0]:.4g}-{bandwidth['band_hz'][1]:.4g} Hz, "
        f"mixer marker {bandwidth['mixer_marker_hz']:.4g} Hz (a marker, not a phase reference)"
    )
    print(
        f"envelope    : {model.envelope.value_mm_s:.4g} mm/s ({model.envelope.metric}); "
        f"{gate['pairs_above_envelope']} / {gate['pairs']} pairs above it, worst "
        f"{gate['max_ratio_to_envelope']:.3g} x at {gate['max_abs_difference_mm_s']:.4g} mm/s"
    )
    print(
        f"headroom    : at {headroom['focus_prf_period_us']:g} us the peak load is "
        f"{headroom['focus_load_max_over_velo_max']:.4g} of "
        f"{headroom['focus_velo_max_mm_s']:.4g} mm/s, "
        f"{headroom['focus_samples_beyond_limit']} sample(s) beyond it, "
        f"{headroom['focus_wrap_like_events']} wrap-like step(s)"
    )
    print(
        f"decision    : {decision['focus_setting_us']:g} vs {decision['candidate_setting_us']:g} "
        f"us - headroom adequate {decision['velocity_headroom_adequate']}, bandwidth adequate "
        f"{decision['temporal_bandwidth_adequate']}"
    )
    print(f"levels table: {report_dir / prf_ladder.LEVELS_NAME}")
    print(f"pairs table : {report_dir / prf_ladder.PAIRS_NAME}")
    print(f"provenance  : {report_dir / prf_ladder.PROVENANCE_NAME}")
    print(f"figure      : {report_dir / prf_ladder.FIGURES_DIRNAME / prf_ladder.FIGURE_NAME}")
    print(f"commit      : {model.analysis_commit}")
    raise SystemExit(0)


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


def _campaign_point_payload(point: campaign.PlannedPoint) -> dict[str, object]:
    """One planned point as a machine reads it: the scalars, and the window they make.

    Flat on purpose — a machine wants the numbers it compares points by, not this layer's
    model shape — and ``parameters`` are the four the point actually writes plus the two
    the campaign fixes for every point of the run.
    """
    parameters = point.parameters
    return {
        "key": point.key,
        "label": point.label,
        "identity": point.identity,
        "duration_s": point.duration_s,
        "note": point.note,
        "sound_speed_ms": parameters.sound_speed_ms,
        "first_gate_mm": parameters.first_gate_mm,
        "resolution_mm": parameters.resolution_mm,
        "resolution_text": parameters.resolution_text,
        "gates": parameters.gates,
        "expected_depth_mm": point.expected_depth_mm,
        "profiles": point.profiles,
    }


def _campaign_plan(args: argparse.Namespace, as_json: bool) -> int:
    """``plan``: load a definition, validate every point, print the plan — touch nothing.

    The half of the campaign feature that has to work anywhere: it reads one file and
    applies the planning math, so it runs on a machine whose application is not running,
    and on a machine that has no application at all. Exit 0 when the plan is valid, 2 when
    the file or a point is invalid, with the reason on stderr.
    """
    try:
        definition = campaign.load_campaign(Path(args.definition))
        points = campaign.plan_campaign(definition)
    # CampaignError is a ValueError; a driver refusal is named here because it is not (§16.2).
    except (driver.AcquisitionError, ValueError, OSError) as exc:
        print(f"udv-acquire: {exc}", file=sys.stderr)
        return 2

    fingerprint = campaign.campaign_fingerprint(definition)
    if as_json:
        print(
            json.dumps(
                {
                    "definition": str(args.definition),
                    "job": definition.job,
                    "channel": definition.channel,
                    "duration_s": definition.duration_s,
                    "store_dir": definition.store_dir,
                    "fingerprint": fingerprint,
                    "points": [_campaign_point_payload(point) for point in points],
                },
                indent=2,
                default=str,
            )
        )
        return 0

    print(
        f"{definition.job}: channel {definition.channel}, {definition.duration_s:g} s per "
        f"point, {len(points)} point(s), definition {fingerprint[:12]}"
    )
    if definition.store_dir:
        print(f"points would land in: {definition.store_dir}")
    print(
        f"{'point':<20} {'c m/s':>6} {'res mm':>8} {'gates':>6} {'depth mm':>9} "
        f"{'profiles':>8} {'window s':>8}"
    )
    for point in points:
        parameters = point.parameters
        print(
            f"{point.label:<20} {parameters.sound_speed_ms:>6.0f} "
            f"{parameters.resolution_mm:>8.3f} {parameters.gates:>6} "
            f"{point.expected_depth_mm:>9.3f} {point.profiles:>8} "
            f"{point.duration_s:>8.1f}"
        )
    for point in points:
        if point.note:
            print(f"note: {point.label}: {point.note}")
    return 0


def _campaign_compile(args: argparse.Namespace, notes: list[str], as_json: bool) -> int:
    """``compile``: one live reading, reconciled against the definition, and stop there.

    The run path's steps 3-5 and nothing after them: route the channel, take one reading of
    the instrument, compile the campaign against it, and print what came out. It is the only
    way to see the *compiled* plan — the static ``plan`` cannot know what the instrument
    states — and it is what an operator checks before spending a job's recordings, which is
    why it must record nothing: ``compile_campaign`` takes no actuator, so nothing on this
    path can store, and no store directory, log or manifest is named here.

    Unlike ``plan`` it drives the instrument, and step 3 is a *write* whenever the dialog is
    not already on the channel — so the note names the channel that it routed. It also takes the
    declaration the record paths take (``--expect-mode``) and checks the reading's own process
    mode against it (:func:`campaign.refuse_process_mode`, step 4a): a compile against the wrong
    process would reconcile a definition with another machine's instrument, so it refuses by
    naming the caption it read — §24.7's third live step, and it still records nothing.
    Exit 0 when the definition and the instrument agree, 2 when the file or the compile refuses,
    with the refusal's own words on stderr: it already names the fact or the state that stopped the
    job, and re-wrapping it would give one cause two diagnoses.
    """
    try:
        definition = campaign.load_campaign(Path(args.definition))
        actuator = live.live_actuator(args.channel, notes)
        # (3) the routing step, whose own return is the evidence the reading needs — the
        # reading cannot read the channel itself. Worth a note, because this is the one of
        # the three steps that can change the instrument.
        routed = actuator.ensure_channel()
        notes.append(
            f"compile: routed channel {routed} (step 3 writes the channel only when the "
            "dialog is not already on it)"
        )
        # (4) one reading, handed what the routing step established and what the dialog
        # reader read. (5) reconciled, or refused by name.
        snapshot = actuator.instrument_snapshot(
            routed_channel=routed,
            dialog_parameters=actuator.read_dialog_parameters(),
        )
        # (4a) the mode rung, before the compile: the declared process is compared with what the
        # caption states, and a mismatch is exit 2 naming the caption — records nothing (plan
        # §24.7 step 3 is the live check of exactly this).
        campaign.refuse_process_mode(snapshot, ProcessMode(args.expect_mode))
        compiled = campaign.compile_campaign(definition, snapshot)
    # CampaignError is a ValueError; a driver refusal is named here because it is not (§16.2).
    except (driver.AcquisitionError, ValueError, OSError) as exc:
        print(f"udv-acquire: {exc}", file=sys.stderr)
        return 2

    if as_json:
        # One document, like `plan`'s, plus the two things the compile states as properties
        # rather than fields: the facts nothing on the instrument could state, and the
        # disagreements the run would proceed despite.
        payload = compiled.model_dump(mode="json")
        payload["unproven"] = list(compiled.unproven)
        payload["advisories"] = list(compiled.advisories)
        print(json.dumps(payload, indent=2, default=str))
        return 0

    _acquire_report(compiled, as_json)
    return 0


def _campaign_run(
    args: argparse.Namespace, notes: list[str], as_json: bool
) -> int:
    """``campaign``: run a definition point by point through the runner, and write its manifest.

    The store directory is the flag's, else the definition's, else the live commands' own
    rule (``UDV_STORE_DIR`` or a usage error) — never a guess, because the cycle *writes*
    the Store dialog's directory when it differs. Exit 0 when every point ran, 1 when any
    point was refused or failed, 2 when the definition or the directory cannot be used.
    """
    try:
        definition = campaign.load_campaign(Path(args.definition))
        if args.store_dir is not None:
            directory = Path(args.store_dir)
        elif definition.store_dir is not None:
            directory = Path(definition.store_dir)
        else:
            directory = _acquire_store_directory(None)
        channel = definition.channel if args.channel is None else args.channel
        log_path = Path(args.log) if args.log else directory / campaign.DEFAULT_LOG_NAME
        manifest = campaign.run_campaign(
            definition,
            live.live_actuator(channel, notes),
            store_dir=directory,
            log_path=log_path,
            resume=args.resume,
            no_snapshot=args.no_snapshot,
            resume_declaration_only=args.resume_declaration_only,
            channel=channel,
            definition_path=Path(args.definition),
            notes=notes,
            expected_mode=ProcessMode(args.expect_mode),
        )
    # Includes campaign.CampaignError, and the driver's own refusals, which are not ValueErrors
    # (§16.2): a refusal from the driver is still a refusal — one line and exit 2.
    except (driver.AcquisitionError, ValueError, OSError) as exc:
        print(f"udv-acquire: {exc}", file=sys.stderr)
        return 2

    if as_json:
        # The manifest is the whole report: what the job was and how every point ended.
        print(json.dumps(manifest.model_dump(mode="json"), indent=2, default=str))
    else:
        for outcome in manifest.outcomes:
            # A refused or failed point says why; the stored file stays visible either way.
            detail = outcome.file or ""
            if not outcome.ok and outcome.reason:
                detail = f"{detail}  {outcome.reason}".strip()
            elif not detail:
                detail = outcome.reason or ""
            print(f"{outcome.label:<20} {outcome.status.value:<8} {detail}")
        print(f"log      : {manifest.log_path}")
        print(f"manifest : {campaign.manifest_path_for(log_path)}")
        print(manifest.summary)
    return 0 if manifest.failed_count == 0 and not manifest.aborted else 1


def _campaign_report(args: argparse.Namespace, as_json: bool) -> int:
    """``report``: a job log's per-point status and its summary — no instrument needed.

    Reads the log (the authority for what happened) and the manifest beside it when there
    is one (the only place the job's name, the definition's fingerprint and the window
    length are written down). A log whose manifest is missing is still a complete
    point-by-point record, so that is not an error. Exit 0, or 2 when the log cannot be
    read — an unreadable log is a usage problem, not a failed job.
    """
    log_path = Path(args.log)
    try:
        records = point_records(read_entries(log_path))
        manifest = campaign.read_manifest_if_present(campaign.manifest_path_for(log_path))
    # Includes campaign.CampaignError, and the driver's own refusals, which are not ValueErrors
    # (§16.2): a refusal from the driver is still a refusal — one line and exit 2.
    except (driver.AcquisitionError, ValueError, OSError) as exc:
        print(f"udv-acquire: {exc}", file=sys.stderr)
        return 2

    rows = [
        {
            "identity": campaign.record_identity(record),
            "key": record.key,
            "name": record.name,
            "status": record.status.value,
            "gates": record.requested.gates,
            "readback_gates": record.readback_gates,
            "file": record.file_path,
            "failure": record.failure,
        }
        for record in records
    ]
    summary = {
        "points": len(records),
        "ok": sum(1 for record in records if record.status is PointStatus.OK),
        "failed": sum(1 for record in records if record.status is PointStatus.FAILED),
        "invalid": sum(1 for record in records if record.status is PointStatus.INVALID),
        "recorded": sorted(
            campaign.record_identity(record)
            for record in records
            if record.status is PointStatus.OK
        ),
    }

    if as_json:
        print(
            json.dumps(
                {
                    "log": str(log_path),
                    "manifest": None
                    if manifest is None
                    else manifest.model_dump(mode="json"),
                    "summary": summary,
                    "points": rows,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    if manifest is None:
        print("job        : unknown (no manifest beside this log)")
    else:
        print(f"job        : {manifest.job} (fingerprint {manifest.fingerprint[:12]})")
        print(f"started    : {manifest.started_at.isoformat()}")
        print(f"finished   : {manifest.finished_at.isoformat()}")
        print(
            f"planned    : {manifest.planned} point(s), {manifest.points_skipped} skipped, "
            f"{manifest.failed_count} not ok"
        )
        for note in manifest.log_errors:
            print(f"log error  : {note}")
    print(f"log        : {log_path}")
    print(f"{'point':<24} {'status':<8} {'gates':>6} {'read':>6}  file / reason")
    for row in rows:
        readback = "" if row["readback_gates"] is None else f"{row['readback_gates']}"
        # The file is evidence and stays visible; the reason is why a bad point is bad, so a
        # point that is not ok says both.
        detail = row["file"] or ""
        if row["failure"]:
            detail = f"{detail}  {row['failure']}".strip()
        print(
            f"{row['identity']:<24} {row['status']:<8} {row['gates']:>6} "
            f"{readback:>6}  {detail}"
        )
    print(
        f"summary    : {summary['ok']}/{summary['points']} ok, {summary['failed']} failed, "
        f"{summary['invalid']} invalid"
    )
    return 0


def acquire_main(argv: list[str] | None = None) -> None:
    """``udv-acquire`` — the live path: read the screen, exercise a cycle, store a point, sweep.

    These commands drive the *running* application, so they only work from the session that owns
    its screen (``tools/live/README.md``); everything they report is a model from
    :mod:`udv_echo_process.acquire.actuator`, and ``--json`` prints it for a machine. Exit codes:
    0 ok, 1 a refused point or a failed verification, 2 usage, configuration, or a refusal from
    the driver itself (the foreground precondition, a dialog that will not open, a control that
    is not there) — reported as one ``udv-acquire:`` line and never as a traceback, because the
    run did not happen and nothing was written.

    ``plan`` and ``report`` are the campaign layer's two halves that touch no instrument at all:
    ``plan`` validates a definition and prints the points it would run, ``report`` reads a job
    log (and the manifest beside it) and prints how the job went. Both work on a machine whose
    application is not running — including one that has no application — which is what makes a
    campaign reviewable before anything is recorded. ``compile`` adds one live reading to what
    ``plan`` does and reconciles the definition against it, so it drives the instrument — the
    routing step writes the channel when the dialog differs — but still records nothing: no
    store, no log, no manifest, which is what makes a compiled plan checkable before a job is
    spent. Only ``campaign`` records: it compiles, then runs the points through the same live
    actuator the other subcommands use.
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

    def expect_mode_argument(target: argparse.ArgumentParser) -> None:
        """``--expect-mode``: the process one of the **record** paths declares.

        Required, with a fixed vocabulary of two (plan §24.5 D1/D3): the process is a property of
        the machine the operator stands at, so it is declared at the command line and never
        inferred from whatever happens to be running. Only the commands that record take it —
        ``status``, ``plan``, ``report`` and ``decode`` refuse nothing, and a diagnostic that
        refused would be useless.
        """
        # DEVIATION: §24.4's own list names only the record path and the runner's gate, and this
        # flag is on `compile` too — which records nothing. §24.7 step 3 is why: the live check of
        # this slice is "compile twice on the instrument: the declared mode exits 0, the other mode
        # exits 2 naming the caption", and a compile that could not hear the declaration could not
        # run that check. `plan`/`report`/`status`/`decode` still refuse nothing.
        target.add_argument(
            "--expect-mode",
            required=True,
            choices=[mode.value for mode in ProcessMode],
            help=(
                "the process this run was measured against; the top-level window's caption is "
                "compared with it before anything is recorded"
            ),
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
    expect_mode_argument(point_parser)
    point_parser.add_argument("--store-dir", default=None)
    point_parser.add_argument("--json", action="store_true")

    sweep_parser = subcommands.add_parser(
        "sweep", help="a multi-point sweep, one JSONL entry per point"
    )
    sweep_parser.add_argument("--seconds", type=float, required=True)
    sweep_parser.add_argument("--rungs", required=True, help="1-based ladder indices, e.g. 1,2")
    channel_argument(sweep_parser)
    expect_mode_argument(sweep_parser)
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

    plan_parser = subcommands.add_parser(
        "plan",
        help="validate a campaign definition and print its points (touches no instrument)",
    )
    plan_parser.add_argument("--definition", required=True)
    plan_parser.add_argument("--json", action="store_true")

    compile_parser = subcommands.add_parser(
        "compile",
        help=(
            "add one live reading to a definition and print the reconciled plan "
            "(touches the instrument; records nothing)"
        ),
    )
    compile_parser.add_argument("--definition", required=True)
    channel_argument(compile_parser)
    expect_mode_argument(compile_parser)
    compile_parser.add_argument("--json", action="store_true")

    campaign_parser = subcommands.add_parser(
        "campaign", help="run a campaign definition, one JSONL entry per point"
    )
    campaign_parser.add_argument("--definition", required=True)
    campaign_parser.add_argument("--store-dir", default=None)
    campaign_parser.add_argument(
        "--log", default=None, help="JSONL job log (default: <store-dir>/campaign.jsonl)"
    )
    campaign_parser.add_argument(
        "--resume",
        action="store_true",
        help="skip the points the log already holds as ok, and say how many",
    )
    campaign_parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help=(
            "take no instrument reading and compile nothing: the manifest, and every point "
            "from it, are marked 'declared only'"
        ),
    )
    campaign_parser.add_argument(
        "--resume-declaration-only",
        action="store_true",
        help=(
            "let a resume proceed without a proven compilation identity, marking every point "
            "it skipped that way as decided without instrument evidence"
        ),
    )
    channel_argument(campaign_parser)
    expect_mode_argument(campaign_parser)
    campaign_parser.add_argument("--json", action="store_true")

    report_parser = subcommands.add_parser(
        "report", help="a job log's per-point status and summary (touches no instrument)"
    )
    report_parser.add_argument("--log", required=True)
    report_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    notes: list[str] = []
    as_json = bool(getattr(args, "json", False))
    # With --json the report is the only thing on stdout; the notes go to stderr.
    note_stream = sys.stderr if as_json else sys.stdout
    code = 0
    try:
        if args.command == "status":
            _acquire_report(live.status(args.channel, notes), as_json)
        elif args.command == "plan":
            code = _campaign_plan(args, as_json)
        elif args.command == "compile":
            code = _campaign_compile(args, notes, as_json)
        elif args.command == "campaign":
            code = _campaign_run(args, notes, as_json)
        elif args.command == "report":
            code = _campaign_report(args, as_json)
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
                expected_mode=ProcessMode(args.expect_mode),
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
                expected_mode=ProcessMode(args.expect_mode),
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
    except driver.AcquisitionError as exc:
        # The live verbs drive the instrument through the same driver and have no handler of
        # their own, so a refusal from one of them arrives here (§16.2). The answer is the one
        # the campaign handlers give above — the driver's own words on one line, exit 2 —
        # because a refused step is a refusal (nothing ran, nothing was written), not a crash.
        print(f"udv-acquire: {exc}", file=sys.stderr)
        code = 2
    finally:
        for note in notes:
            print(f"note: {note}", file=note_stream)
    raise SystemExit(code)


def gain_power_screen_main(argv: list[str] | None = None) -> None:
    """``gain-power-screen`` — write the WP2 TGC/emitting-power screening artefacts.

    Selects every ``tgc`` and ``em_pow`` recording from the WP0 manifest, orders each axis by its
    decoded key (the TGC start in dB, the instrument's own power steps), re-checks each source hash,
    every shared decoded cell *and* the two TGC cells (op words 24 and 25), refuses any axis where a
    setting other than its own key moved or the committed TGC representation (word 23 = 0, word 25 =
    255) no longer holds, and writes ``gain-power-levels.csv``, ``gain-power-pairs.csv``,
    ``gain-power-depths.csv``, ``gain-power-screen.provenance.json`` and
    ``figures/gain-power-screen.png`` into the report directory: depth-resolved dropout, bias and
    spread per level, every within-axis pair against the committed WP1 envelope with the depth ranges
    where it clears, and the sensitivity/echo-energy statement. Exits 0 on success and 1 with the
    named reason on stderr when the selection, the bytes, the envelope or an invariant cannot be
    trusted (never a traceback, never a half-written artefact). It touches nothing but those files.
    """
    parser = argparse.ArgumentParser(
        prog="udv-gain-power-screen",
        description=(
            "Screen the committed mixer sweep's TGC and emitting-power axes on velocity alone: "
            "depth-resolved dropout, bias and spread per decoded level, every within-axis pair "
            "against the committed WP1 repeatability envelope, and what still needs echo/energy"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=gain_power_screen.inventory.DATASET_ROOT.as_posix(),
        help="directory of <axis>/<label>.BDD points",
    )
    parser.add_argument(
        "--report-dir",
        default=gain_power_screen.inventory.REPORT_DIR.as_posix(),
        help="directory to write the screening artefacts into",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="WP0 manifest both axes are selected from (default: <report-dir>/manifest.csv)",
    )
    parser.add_argument(
        "--envelope",
        default=None,
        help=(
            "WP1 provenance the repeatability envelope is read from (default: "
            "<report-dir>/reference-repeat.provenance.json)"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help=(
            "revision to record (default: the checkout's short git SHA; pass the recorded commit to "
            "reproduce the committed artefacts byte for byte)"
        ),
    )
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    try:
        model = gain_power_screen.write_gain_power_screen(
            Path(args.dataset_root),
            report_dir,
            manifest_path=None if args.manifest is None else Path(args.manifest),
            envelope_path=None if args.envelope is None else Path(args.envelope),
            analysis_commit=args.analysis_commit,
        )
    except gain_power_screen.GainPowerScreenError as exc:
        print(f"udv-gain-power-screen: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    findings = gain_power_screen.provenance_document(model)["findings"]
    screen, diagnostic = findings["screen_summary"], findings["diagnostic"]
    for axis in model.axes:
        gate = findings["axes"][axis.axis]["effect_gate"]
        print(
            f"{axis.axis:<8}: {len(axis.levels)} levels, {len(axis.pairs)} pairs, "
            f"{len(axis.depths)} depth rows; window {axis.common['revolutions']} rev = "
            f"{axis.common['window_s']:.4g} s; support {axis.common['support_min_mm']:.6g}-"
            f"{axis.common['support_max_mm']:.6g} mm; flagged "
            f"{axis.screen['flagged_paths'] or 'none'}; worst pair "
            f"{gate['max_abs_difference_mm_s']:.4g} mm/s = {gate['max_ratio_to_envelope']:.3g} "
            f"envelope over {gate['knots_above_envelope']} of {gate['pairs']} pair(s) clearing"
        )
    print(
        f"screen  : {screen['levels']} levels, {screen['levels_flagged']} flagged, "
        f"{screen['pairs_above_envelope']} of {screen['pairs']} pairs clear the "
        f"{model.envelope.value_mm_s:.6g} mm/s envelope"
    )
    print(f"diagnostic: justified={diagnostic['justified']} "
          f"wider_ladder_justified={diagnostic['wider_ladder_justified']} "
          f"outcome_claimed={diagnostic['outcome_claimed']}")
    print(f"levels      : {report_dir / gain_power_screen.LEVELS_NAME}")
    print(f"pairs       : {report_dir / gain_power_screen.PAIRS_NAME}")
    print(f"depths      : {report_dir / gain_power_screen.DEPTHS_NAME}")
    print(f"provenance  : {report_dir / gain_power_screen.PROVENANCE_NAME}")
    print(
        f"figure      : {report_dir / gain_power_screen.FIGURES_DIRNAME / gain_power_screen.FIGURE_NAME}"
    )
    print(f"commit      : {model.analysis_commit}")
    raise SystemExit(0)


#: The command a module-level invocation names first: `python -m udv_echo_process.cli <name> ...`
#: — the form the live path uses, because a command that drives the GUI has to be started in the
#: session that owns the screen and a dispatcher can only name a module (`tools/live/README.md`).
_COMMANDS = {
    "acquire": acquire_main,
    "burst-ladder": burst_ladder_main,
    "gain-power-screen": gain_power_screen_main,
    "inspect": inspect_main,
    "prf-ladder": prf_ladder_main,
    "reference-repeat": reference_repeat_main,
    "resolution-ladder": resolution_ladder_main,
    "run-all": run_all_main,
    "sweep-inventory": sweep_inventory_main,
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
