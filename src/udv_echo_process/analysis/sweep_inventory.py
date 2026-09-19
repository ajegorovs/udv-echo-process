"""WP0 inventory of the committed mixer sensitivity sweep (plan ``WP0``).

Reads the 40 committed ``.BDD`` recordings under
``data/mixer-sensitivity-analysis/4MHz/0500RPM/001`` through the public reader
(:func:`udv_echo_process.io.load`) and writes the two reviewer-visible WP0
artefacts into ``reports/mixer-sensitivity-analysis/``:

- ``manifest.csv`` — one row per file: the dataset-relative path, the axis and
  requested label its filename carries, the source content SHA-256, the decoded
  quantity/unit, shape, timing, depth support and the decoded acquisition
  settings, the stored operation words 14/27/84 (published by the reader as
  ``ChannelConfig.emissions_per_profile`` / ``sampling_volume_index`` /
  ``skipped_profiles`` — the reader's private ``_Buffer``/``_read_op`` are never
  touched here), plus the data-quality counters;
- ``qc-summary.json`` — the dataset-level assertions of the WP0 gate: exactly
  40 files, the axis counts ``13/12/8/5/2``, zero decode failures, zero NaNs,
  monotone timestamps in every file, the invariant words ``14 = 20``,
  ``27 = 4``, ``84 = 0``, and the analysis git commit the artefacts were
  generated against.

Determinism is part of the contract: rows are ordered by ``(axis, label)``,
paths are dataset-relative POSIX strings (never absolute), floats are
serialized with a fixed 12-significant-digit format, both documents use LF
endings with one trailing newline, and ``manifest_sha256`` binds the QC summary
to the exact manifest bytes. Regenerating on another machine from the same
commit therefore reproduces both files byte for byte.

This module produces the inventory only. No axis analysis, no repeatability
bound and no interpolation choice belongs to WP0 (plan §3–§4).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.provenance.models import current_revision

#: Default dataset root, relative to the repository root (the CLI's default and
#: the spelling the report README documents).
DATASET_ROOT = Path("data/mixer-sensitivity-analysis/4MHz/0500RPM/001")

#: Default output directory for the WP0 artefacts.
REPORT_DIR = Path("reports/mixer-sensitivity-analysis")

#: Reviewer-visible artefact names.
MANIFEST_NAME = "manifest.csv"
QC_NAME = "qc-summary.json"

#: Expected archive size and per-axis file counts (plan §4 WP0).
EXPECTED_FILES = 40
EXPECTED_AXIS_COUNTS: dict[str, int] = {
    "burst_len": 12,
    "em_pow": 2,
    "prf": 5,
    "res": 13,
    "tgc": 8,
}

#: Operation words that are constant across the whole committed sweep, with the
#: value the payload carries (plan §2). Published by the reader as
#: ``emissions_per_profile`` (14), ``sampling_volume_index`` (27) and
#: ``skipped_profiles`` (84).
EXPECTED_INVARIANT_WORDS: dict[str, int] = {"14": 20, "27": 4, "84": 0}

#: Manifest column order — the row contract every consumer may rely on.
COLUMNS: tuple[str, ...] = (
    "relative_path",
    "axis",
    "requested_label",
    "source_sha256",
    "quantity",
    "unit",
    "profiles",
    "gates",
    "duration_s",
    "median_dt_s",
    "depth_min_mm",
    "depth_max_mm",
    "velocity_min_mm_s",
    "velocity_max_mm_s",
    "emit_freq_khz",
    "prf_period_us",
    "prf_hz",
    "burst_length",
    "emissions_per_profile",
    "emit_power",
    "sensitivity",
    "resolution_mm",
    "sampling_volume_index",
    "sound_speed_ms",
    "doppler_angle_deg",
    "velo_max_ms",
    "tgc_mode",
    "tgc_start_db",
    "tgc_end_db",
    "skipped_profiles",
    "op_word_14",
    "op_word_27",
    "op_word_84",
    "zero_fraction",
    "nan_count",
    "timestamps_monotone",
    "decode_error",
)

#: Significant digits used for every float column. Fixed so a regeneration is
#: byte-identical; the exact values stay recoverable from the source BDD file
#: identified by ``source_sha256``.
_SIGNIFICANT_DIGITS = 12


class SweepInventory(ValueModel):
    """The WP0 inventory: the manifest rows plus the dataset-level QC result.

    ``rows`` is the manifest (one :data:`COLUMNS`-keyed string row per file, in
    the emitted order); every other field is the QC summary. Values are all
    JSON scalars, so :func:`model_dump` is the QC document itself apart from
    ``rows``, which :func:`qc_document` deliberately omits (the manifest is the
    row-level artefact).

    ``checks`` records each WP0 gate assertion and ``ok`` is true only when all
    of them hold — the CLI exits non-zero on a false ``ok``.
    """

    dataset_root: str
    analysis_commit: str | None = None
    manifest_rows: int
    manifest_sha256: str
    files: int
    expected_files: int
    axis_counts: dict[str, int]
    expected_axis_counts: dict[str, int]
    decode_failures: int
    decode_failure_files: tuple[str, ...]
    nan_cells: int
    non_monotone_files: tuple[str, ...]
    invariant_words: dict[str, int | None]
    expected_invariant_words: dict[str, int]
    checks: dict[str, bool]
    ok: bool
    rows: tuple[dict[str, str], ...]

    @model_validator(mode="after")
    def _check_ok_matches_checks(self) -> SweepInventory:
        if self.ok is not all(self.checks.values()):
            raise ValueError(
                f"ok must equal all(checks); ok={self.ok} for checks={self.checks}"
            )
        return self


# ── serialization ──────────────────────────────────────────────────────


def format_cell(value: object) -> str:
    """Serialize one manifest cell deterministically.

    ``None`` becomes the empty string, booleans become ``true``/``false``,
    integers keep their exact form, floats use a fixed 12-significant-digit
    format (platform-independent and locale-independent), and strings pass
    through unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float | np.floating):
        return format(float(value), f".{_SIGNIFICANT_DIGITS}g")
    return str(value)


def manifest_csv(rows: tuple[dict[str, str], ...]) -> str:
    """Render the manifest rows as CSV text (LF endings, one trailing newline)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(COLUMNS), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def qc_document(inventory: SweepInventory) -> dict[str, object]:
    """Return the QC JSON document: the summary fields, never the manifest rows.

    Keys are inserted in a fixed order so the serialized document is stable.
    """
    return {
        "dataset_root": inventory.dataset_root,
        "analysis_commit": inventory.analysis_commit,
        "manifest": MANIFEST_NAME,
        "manifest_rows": inventory.manifest_rows,
        "manifest_sha256": inventory.manifest_sha256,
        "files": inventory.files,
        "expected_files": inventory.expected_files,
        "axis_counts": dict(sorted(inventory.axis_counts.items())),
        "expected_axis_counts": dict(sorted(inventory.expected_axis_counts.items())),
        "decode_failures": inventory.decode_failures,
        "decode_failure_files": list(inventory.decode_failure_files),
        "nan_cells": inventory.nan_cells,
        "non_monotone_files": list(inventory.non_monotone_files),
        "invariant_words": dict(sorted(inventory.invariant_words.items())),
        "expected_invariant_words": dict(
            sorted(inventory.expected_invariant_words.items())
        ),
        "checks": dict(sorted(inventory.checks.items())),
        "ok": inventory.ok,
    }


# ── row building ───────────────────────────────────────────────────────


def discover_sweep_files(dataset_root: Path) -> tuple[Path, ...]:
    """Return the dataset's ``<axis>/<label>.BDD`` files, sorted.

    Sorted so the walk order is deterministic; the axis is the directory name
    and the requested label is the file stem (the dataset's own naming). An
    empty (or absent) dataset root yields no files rather than an error: the
    gate — ``file_count`` — is what reports a missing or incomplete dataset,
    and a caller needs the header-only manifest to see which files were found.
    """
    root = Path(dataset_root)
    files = sorted(path for path in root.glob("*/*.BDD") if path.is_file())
    return tuple(files)


def _prf_period_us(config: ChannelConfig) -> float | None:
    """PRF period in microseconds, inverted back from the reader's Hz field (word 5)."""
    prf_hz = config.pulse_repetition_freq_hz
    if not prf_hz:
        return None
    return 1e6 / float(prf_hz)


def read_manifest_row(path: Path, dataset_root: Path) -> dict[str, str]:
    """Decode one ``.BDD`` file into its manifest row.

    A file that cannot be decoded still gets a row — the relative path, axis,
    label and content SHA-256 are read from the file itself — with every
    remaining column empty and ``decode_error`` naming the failure, so the
    manifest always has one row per committed file and the QC's decode-failure
    count is the number of rows that failed. "Cannot be decoded" includes any
    ordinary decoder exception (a truncated payload raises ``struct.error``
    inside the binary reader), not just ``OSError``/``ValueError``.
    """
    relative = path.relative_to(dataset_root).as_posix()
    row = dict.fromkeys(COLUMNS, "")
    row["relative_path"] = relative
    row["axis"] = path.parent.name
    row["requested_label"] = path.stem

    try:
        recording = load(path).recording
    except Exception as exc:  # noqa: BLE001 - a row that cannot decode is a failure, not an abort
        # A truncated or malformed payload can raise ``struct.error`` (or another
        # non-``OSError``/``ValueError`` exception) from inside the binary reader;
        # catching ``Exception`` still lets ``KeyboardInterrupt`` and
        # ``SystemExit`` (``BaseException``) propagate.
        row["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        row["decode_error"] = f"{type(exc).__name__}: {exc}"
        return row

    row["source_sha256"] = recording.source_asset.content_sha256
    streams = recording.streams
    if len(streams) != 1:
        row["decode_error"] = (
            f"expected exactly one channel stream, found {len(streams)}"
        )
        return row

    stream = streams[0]
    data = stream.data
    config = stream.config
    values = data.values
    monotone = bool(np.all(np.diff(data.time_s) > 0))
    row.update(
        {
            "quantity": stream.descriptor.quantity.value,
            "unit": stream.descriptor.unit,
            "profiles": format_cell(int(values.shape[0])),
            "gates": format_cell(int(values.shape[1])),
            "duration_s": format_cell(float(data.time_s[-1] - data.time_s[0])),
            "median_dt_s": format_cell(float(np.median(np.diff(data.time_s)))),
            "depth_min_mm": format_cell(float(data.gate_depths_mm[0])),
            "depth_max_mm": format_cell(float(np.max(data.gate_depths_mm))),
            "velocity_min_mm_s": format_cell(float(np.min(values))),
            "velocity_max_mm_s": format_cell(float(np.max(values))),
            "emit_freq_khz": format_cell(config.source_freq_khz),
            "prf_period_us": format_cell(_prf_period_us(config)),
            "prf_hz": format_cell(config.pulse_repetition_freq_hz),
            "burst_length": format_cell(config.burst_length),
            "emissions_per_profile": format_cell(config.emissions_per_profile),
            "emit_power": format_cell(config.emit_power),
            "sensitivity": format_cell(config.sensitivity),
            "resolution_mm": format_cell(config.resolution_mm),
            "sampling_volume_index": format_cell(config.sampling_volume_index),
            "sound_speed_ms": format_cell(config.sound_speed_ms),
            "doppler_angle_deg": format_cell(config.doppler_angle_deg),
            "velo_max_ms": format_cell(config.velo_max_ms),
            "tgc_mode": format_cell(config.tgc_mode),
            "tgc_start_db": format_cell(config.tgc_start_db),
            "tgc_end_db": format_cell(config.tgc_end_db),
            "skipped_profiles": format_cell(config.skipped_profiles),
            # Words 14/27/84 as the reader publishes them (stored integers).
            "op_word_14": format_cell(config.emissions_per_profile),
            "op_word_27": format_cell(config.sampling_volume_index),
            "op_word_84": format_cell(config.skipped_profiles),
            "zero_fraction": format_cell(
                float(np.count_nonzero(values == 0) / values.size)
            ),
            "nan_count": format_cell(int(np.count_nonzero(np.isnan(values)))),
            "timestamps_monotone": format_cell(monotone),
        }
    )
    return row


def _axis_counts(rows: tuple[dict[str, str], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        axis = row["axis"]
        counts[axis] = counts.get(axis, 0) + 1
    return dict(sorted(counts.items()))


def _observed_invariant_words(
    rows: tuple[dict[str, str], ...],
) -> dict[str, int | None]:
    """The single value each of words 14/27/84 carries, or ``None`` if it varies."""
    observed: dict[str, int | None] = {}
    for word in EXPECTED_INVARIANT_WORDS:
        column = f"op_word_{word}"
        values = {row[column] for row in rows}
        text = next(iter(values)) if len(values) == 1 else ""
        try:
            observed[word] = int(text)
        except ValueError:
            observed[word] = None
    return observed


def build_sweep_inventory(
    dataset_root: Path = DATASET_ROOT, *, analysis_commit: str | None = None
) -> SweepInventory:
    """Decode every committed ``.BDD`` file and build the WP0 inventory.

    Args:
        dataset_root: directory holding ``<axis>/<label>.BDD`` points.
        analysis_commit: revision to record. ``None`` probes the checkout's
            short git SHA once (never blocking); pass it explicitly to keep a
            caller in control or to reproduce a committed artefact.

    Returns:
        The manifest rows plus the QC summary and gate checks. The artefacts are
        *not* written here — see :func:`write_sweep_inventory`.

    Raises:
        Nothing for an undecodable file or an empty dataset root: a file that
        cannot be decoded becomes a ``decode_error`` row and an empty discovery
        yields no rows, so the checks — ``decode_failures``, ``file_count`` —
        report the failure instead of an exception escaping the command.
    """
    root = Path(dataset_root)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    rows = tuple(read_manifest_row(path, root) for path in discover_sweep_files(root))

    axis_counts = _axis_counts(rows)
    invariant_words = _observed_invariant_words(rows)
    failures = tuple(row["relative_path"] for row in rows if row["decode_error"])
    # A decode-error row carries an empty ``timestamps_monotone`` because it has
    # no timestamps at all — that is not evidence of a non-monotone series, so
    # the timestamp gate judges only rows that actually decoded.
    non_monotone = tuple(
        row["relative_path"]
        for row in rows
        if not row["decode_error"] and row["timestamps_monotone"] != "true"
    )
    nan_cells = sum(int(row["nan_count"] or 0) for row in rows)
    invariant_ok = invariant_words == EXPECTED_INVARIANT_WORDS and all(
        row[f"op_word_{word}"] == str(value)
        for row in rows
        for word, value in EXPECTED_INVARIANT_WORDS.items()
    )
    checks = {
        "file_count": len(rows) == EXPECTED_FILES,
        "axis_counts": axis_counts == dict(sorted(EXPECTED_AXIS_COUNTS.items())),
        "decode_failures": not failures,
        "nan_cells": nan_cells == 0,
        "timestamps_monotone": not non_monotone,
        "invariant_words": invariant_ok,
        "analysis_commit": bool(commit),
    }
    csv_text = manifest_csv(rows)
    return SweepInventory(
        dataset_root=root.as_posix(),
        analysis_commit=commit,
        manifest_rows=len(rows),
        manifest_sha256=f"sha256:{hashlib.sha256(csv_text.encode('utf-8')).hexdigest()}",
        files=len(rows),
        expected_files=EXPECTED_FILES,
        axis_counts=axis_counts,
        expected_axis_counts=dict(sorted(EXPECTED_AXIS_COUNTS.items())),
        decode_failures=len(failures),
        decode_failure_files=failures,
        nan_cells=nan_cells,
        non_monotone_files=non_monotone,
        invariant_words=invariant_words,
        expected_invariant_words=dict(sorted(EXPECTED_INVARIANT_WORDS.items())),
        checks=checks,
        ok=all(checks.values()),
        rows=rows,
    )


def write_sweep_inventory(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    analysis_commit: str | None = None,
) -> SweepInventory:
    """Build the inventory and write ``manifest.csv`` + ``qc-summary.json``.

    Both files are written as UTF-8 with LF endings and one trailing newline, so
    two runs with the same inputs and commit produce identical bytes. The report
    directory is created when missing. The returned inventory is the QC result;
    a caller that needs the gate verdict reads ``ok``.
    """
    inventory = build_sweep_inventory(dataset_root, analysis_commit=analysis_commit)
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / MANIFEST_NAME).write_text(
        manifest_csv(inventory.rows), encoding="utf-8", newline=""
    )
    document = json.dumps(qc_document(inventory), indent=2) + "\n"
    (directory / QC_NAME).write_text(document, encoding="utf-8", newline="")
    return inventory
