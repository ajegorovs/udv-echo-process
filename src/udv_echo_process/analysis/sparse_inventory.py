"""WP0 of the sparse-pass analysis: the ingest table for the mixer-enabled pass.

Reads the 26 committed ``.BDD`` recordings of ``data/sparse-mixer-live-1`` — the
mixer-enabled realization of the frozen nine-job design — through the public
reader (:func:`udv_echo_process.io.load`), binds each one to the point the pass
planned for it, and writes the two reviewer-visible WP0 artefacts into
``reports/sparse-mixer-live-1/``:

- ``points.csv`` — one row per stored recording: the point's identity (step, job,
  kind, label, position in the pass), the condition the plan holds for its job,
  the window the plan requested for that point, the settings the file's own words
  decode to, the achieved profile timing **measured from the stored timestamps**,
  the retention the file actually covers, the signal statistics of the common
  window and common physical support, and the provenance that ties the row to the
  bytes, the job log, the job manifest, the definition fingerprint and the plan
  fingerprint;
- ``qc-summary.json`` — the dataset-level assertions of the WP0 gate: 26
  recordings, the nine jobs' counts, zero decode failures, zero NaNs, strictly
  increasing timestamps, every committed recording bound to exactly one planned
  point and every planned point present, the acquisition layer's own decode
  reproduced by this reader, the declared window and condition reproduced by the
  stored words, retention of the pass's designed exposure, the achieved period
  against the planner's own law, and the signal content of every recording.

**Two provenance rules this module exists to keep.** The achieved profile period
is measured from each file's own profile timestamps, never taken from the log's
``timing.target_s`` — that field holds the *retired* ``emissions x PRF + 1 ms``
expectation the planner used on the day of the run, it is carried here under its
own column name as provenance, and the logs are never rewritten to match a later
law. And every identity in a row comes from decoding, or from the pass's own
record of what it planned: a row is bound to a planned point and the binding is
re-checked against the reader, never taken on a filename.

Nothing here measures a scientific effect. The within-job anchor controls, the
cross-run reference checks, the pitch x burst corners, the emissions ladder and
the Stage-2 decision are the later work packages of
``docs/dop3000/sparse-pass-analysis-plan.md``; this module freezes the table they
all select from.

**One pass or the next, from the same code.** The ingest takes its identity from its
inputs, not from this module's constants: the dataset root, the plan path, the plan
name (the pass record is ``<plan_name>.run.json`` inside the dataset root) and the
report directory are all parameters. The bare call still describes
``sparse-mixer-live-1`` and produces its frozen artefacts byte for byte; a second
pass whose plan names itself is ingested by pointing the same call at its own root and
plan, and it clears the *same* gate — the same nine-job design, the same common window
and support, the same content floor — because the design and the gate are properties of
the pass plan, not of one sitting. The one provenance form that moved between the two
sittings is the planner's own expectation recorded in ``timing.target_s``: the first
pass's logs predate the manual's sixteen-emission term and the second pass's record it.
The expected planning law is selected by pass identity; an old-law target in the
second sitting is a refusal, not a second acceptable spelling of its provenance.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np
from pydantic import model_validator

from udv_echo_process.acquire import run_plan
from udv_echo_process.acquire.campaign import PlannedPoint
from udv_echo_process.acquire.plan import clamp_resolution, profile_period_s
from udv_echo_process.analysis._native_grid import (
    common_support,
    in_support,
    window,
)
from udv_echo_process.analysis.reference_repeat import gate_metrics
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.provenance.models import current_revision

#: The pass's committed dataset (one flat directory of recordings plus the pass's
#: own record and per-job logs and manifests), and the frozen plan it realizes. These
#: are the *first* pass's paths and the defaults of every entry point below; a later
#: pass passes its own root, plan and name and inherits this module's schema, binding
#: and gate unchanged.
DATASET_ROOT = Path("data/sparse-mixer-live-1")
PLAN_PATH = Path("examples/sparse-mixer-live-1/run-plan.json")
PLAN_NAME = "sparse-mixer-live-1"

#: Default output directory for the WP0 artefacts.
REPORT_DIR = Path("reports/sparse-mixer-live-1")

#: Reviewer-visible artefact names.
POINTS_NAME = "points.csv"
QC_NAME = "qc-summary.json"

#: The shared design's own size and shape, as the plan states them: 26 recordings over
#: nine jobs, and the per-job counts the plan and every realization of it must match.
#: These are the design's, not one sitting's — both committed passes realize them, so
#: the WP0 gate checks each pass against the same nine-job shape.
EXPECTED_RECORDINGS = 26
EXPECTED_JOB_COUNTS: dict[str, int] = {
    "burst-4": 5,
    "common-reference-1": 1,
    "burst-18": 5,
    "common-reference-2": 1,
    "emissions-8": 4,
    "common-reference-3": 1,
    "emissions-64": 4,
    "common-reference-4": 1,
    "emissions-128": 4,
}

#: The interval each recording was asked for — the pass's **designed exposure**, and
#: the primary distributional window. The files retain more than this (12.4686-12.5888 s):
#: that overshoot is the acquisition's own stopping latency, not a longer experiment, so
#: it is reached for by the full-record view (spectra, autocorrelation) and never by the
#: primary one, which would quietly widen the exposure past the design.
REQUESTED_DURATION_S = 12.0
NOMINAL_RPM = 500.0
REVOLUTION_S = 60.0 / NOMINAL_RPM
DESIGNED_REVOLUTIONS = 100  # the declared 12 s, in nominal revolutions
DESIGNED_WINDOW_S = DESIGNED_REVOLUTIONS * REVOLUTION_S  # 12.0 s

#: The three windows the pass acquires, as the plan *requests* them —
#: ``(resolution_mm, gates)``. A point's requested window must be one of these, and
#: its decoded pitch must be the rung the application accepts for that request (the
#: ladder is quantized to ``c / 12000``, so 0.617 mm is stored as 0.616666...7 mm):
#: the two checks together are what make the pass's depth grids comparable by
#: construction rather than by convention.
PLAN_WINDOWS: tuple[tuple[float, int], ...] = ((0.617, 145), (1.85, 50), (2.96, 31))

#: The block-local anchor controls' own label prefix, as the plan spells it.
CONTROL_PREFIX = "ctrl-"

#: Tolerances. ``LOG_*`` bound the cross-check against the acquisition layer's own
#: decode (its log rounds the span to 4 decimals); ``PERIOD_MODEL_TOLERANCE_S``
#: bounds the achieved period against the planner's law, whose transfer term is only
#: known to about a millisecond; ``TOLERANCE_S`` is the slack every timestamp cut
#: uses, and ``GRID_RTOL`` the slack a decoded pitch or period is compared with.
TOLERANCE_S = 1e-9
LOG_SPAN_TOLERANCE_S = 1e-4
LOG_PERIOD_REL_TOLERANCE = 1e-9
LOG_TARGET_TOLERANCE_S = 1e-9
PERIOD_MODEL_TOLERANCE_S = 1e-3
GRID_RTOL = 1e-6

#: The retired profile-period expectation the logs record, and the fact that it is
#: provenance rather than a measurement: ``emissions x PRF + 1 ms`` is the form the
#: planner used while the first pass ran (it dropped the manual's 16-emission term), so
#: that pass's log ``timing.target_s`` reproduces *this* law and not the achieved period.
RETIRED_PERIOD_LAW = "emissions_per_profile x prf_us + 1 ms"
RETIRED_PERIOD_TRANSFER_S = 1e-3

#: The planner's *corrected* law, ``acquire/plan.py::profile_period_s`` — the manual's
#: ``T_tran + T_prf x (16 + N_PRF)``. The second pass's logs record this form, so
#: :func:`require_retired_target` accepts it too: both are planning expectations for a
#: point's own decoded emissions and PRF, and neither is the achieved period.
PLANNER_PERIOD_LAW = "T_tran + T_prf x (16 + N_PRF) (acquire/plan.py::profile_period_s)"

#: The planning law each pass's own logs record, by pass name. A pass named here is
#: screened against *that* form only, so a log rewritten to the other sitting's law —
#: or to the achieved period — is refused. A pass that is **not** named (the Stage-2
#: campaign predates the split) is screened against **both** forms instead of being
#: refused: that is what every pass was screened against before this table existed, and
#: the check's job is to catch a log rewritten to the achieved period, which both forms
#: sit far from. Naming a pass here is a tightening for that pass, never a gate on
#: whether an older pass may be analysed at all.
PERIOD_LAW_BY_PASS: dict[str, str] = {
    PLAN_NAME: RETIRED_PERIOD_LAW,
    "sparse-mixer-live-2": PLANNER_PERIOD_LAW,
}

#: The signal-content floor a live pass must clear: a recording of this pass that is
#: mostly zero would be the first pass's payload, not a usable measurement. It is a
#: floor, not a target — this pass's own non-zero fractions are ~0.99.
MIN_NON_ZERO_FRACTION = 0.5

#: Column order of ``points.csv`` — the row contract every later work package may
#: rely on. The decoded-settings cells keep the WP0 manifest's own names wherever
#: the two tables hold the same quantity, so a column means the same thing in both.
COLUMNS: tuple[str, ...] = (
    # identity: where the point sits in the pass
    "relative_path",
    "order",
    "step",
    "job",
    "kind",
    "requested_label",
    "identity",
    "point_key",
    "job_started_at",
    "job_finished_at",
    "recording_stamp",
    # the condition the plan holds for the job, and the window it requested
    "declared_burst_length",
    "declared_emissions_per_profile",
    "declared_prf_us",
    "declared_resolution_mm",
    "declared_accepted_resolution_mm",
    "declared_gates",
    "declared_first_gate_mm",
    "declared_depth_mm",
    "is_control",
    # what the stored file's own words decode to
    "quantity",
    "unit",
    "profiles",
    "gates",
    "duration_s",
    "depth_min_mm",
    "depth_max_mm",
    "resolution_mm",
    "prf_period_us",
    "prf_hz",
    "burst_length",
    "emissions_per_profile",
    "emit_freq_khz",
    "emit_power",
    "sensitivity",
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
    # timing, measured from the stored timestamps
    "requested_duration_s",
    "median_interval_s",
    "interval_iqr_s",
    "achieved_period_s",
    "retained_fraction",
    "usable_interval_s",
    "designed_window_s",
    "retains_designed_window",
    "period_expectation_s",
    "period_residual_s",
    "timestamps_monotone",
    # signal statistics: the whole record, then the common window on the common support
    "nan_count",
    "zero_fraction",
    "non_zero_fraction",
    "velocity_min_mm_s",
    "velocity_max_mm_s",
    "supported_gates",
    "window_revolutions",
    "window_s",
    "window_profiles",
    "supported_mean_mm_s",
    "supported_median_mm_s",
    "supported_iqr_mm_s",
    "supported_rms_mm_s",
    "supported_zero_fraction",
    # provenance: the bytes, the logs, the manifests and the plan this row came from
    "source_sha256",
    "file_size_bytes",
    "log_relative_path",
    "log_status",
    "log_target_s",
    "log_achieved_period_s",
    "log_median_interval_s",
    "manifest_relative_path",
    "job_definition",
    "job_definition_fingerprint",
    "plan",
    "plan_fingerprint",
    "decode_error",
)

#: Metric definitions, recorded verbatim in the QC document so a column cannot be
#: read without its meaning.
DEFINITIONS: dict[str, str] = {
    "achieved_period_s": (
        "the profile period measured from the recording's own stored timestamps, "
        "(t_last - t_first) / (profiles - 1), in seconds; never the log's "
        "timing.target_s, which records the retired planning expectation"
    ),
    "duration_s": (
        "the retained span of the recording, t_last - t_first from its stored "
        "timestamps, in seconds"
    ),
    "op_word_27": (
        "the stored sampling-volume word: the instrument's option-list INDEX, not a "
        "length. The index-to-mm relation is medium- and burst-dependent and was only "
        "ever measured at one sound speed, so this index states no acoustic averaging "
        "length and is not comparable with the historical sweep's own stored index "
        "(4). The historical value is quoted only to keep the two apart"
    ),
    "op_word_14": (
        "the stored emissions-per-profile word, which is each point's own request"
    ),
    "op_word_84": "the stored skipped-profile word (0 throughout this pass)",
    "retained_fraction": "duration_s / requested_duration_s, dimensionless",
    "retains_designed_window": (
        f"duration_s >= {DESIGNED_WINDOW_S:g} s ({DESIGNED_REVOLUTIONS} nominal "
        f"{NOMINAL_RPM:g}-RPM revolutions): whether the recording covers the "
        "pass's designed exposure in full, which is what the primary view uses"
    ),
    "period_expectation_s": (
        "the planner's own law, acquire/plan.py::profile_period_s (the manual's "
        "T_tran + T_prf x (16 + N_PRF)), for the point's decoded emissions and PRF"
    ),
    "period_residual_s": "achieved_period_s - period_expectation_s, in seconds",
    "zero_fraction": (
        "count of samples exactly equal to 0.0 divided by the record length, "
        "dimensionless (the whole record, every gate)"
    ),
    "supported_*": (
        "the same distributional metrics as reference_repeat.gate_metrics, computed "
        "over the common window (window_s, the pass's designed exposure: the "
        "declared 12 s = 100 nominal revolutions) restricted to the common physical "
        "support (support_min_mm..support_max_mm); each per-gate statistic is then "
        "aggregated across the supported gates by an unweighted mean, so one row is "
        "comparable with another whatever its gate count"
    ),
    "is_control": (
        "true for the pass's three block-local anchor controls (ctrl-begin, "
        "ctrl-mid, ctrl-end): each records its own job's anchor condition at the "
        "reference spatial window, so a burst-4 job's controls are burst 4 and not "
        "the reference condition. 'Reference' in this table means the reference "
        "condition that CR1-CR4 record; a control is not a reference realization"
    ),
    "declared_accepted_resolution_mm": (
        "the pitch the application accepts for the point's requested "
        "declared_resolution_mm: the resolution ladder is quantized to c / 12000 mm and "
        "snapping is to the nearest rung (acquire/plan.py::clamp_resolution), so a "
        "requested 0.617 mm is stored as 0.6166666666666667 mm. resolution_mm is the "
        "file's own achieved value and must equal this"
    ),
    "log_target_s": (
        "the log's own timing.target_s, carried as provenance: it reproduces the "
        f"retired law ({RETIRED_PERIOD_LAW}) the planner used on the day of the run, "
        "and it is not the achieved period. The logs are not rewritten to match a "
        "later law"
    ),
}


class SparseIngestError(ValueError):
    """The committed pass is not the dataset this ingest describes.

    Raised for a missing or unreadable pass record, a plan the record does not
    answer to, a recording the pass's own manifests do not claim, a claimed
    recording that is not committed, a decode that disagrees with the acquisition
    layer's own decode, a stored word that is not the declared setting, or a log
    whose retired target has been rewritten. The command turns it into a non-zero
    exit naming the reason, never a traceback.
    """


def _read_json(path: Path, what: str) -> dict[str, object]:
    """Read one JSON document, or refuse by name."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SparseIngestError(f"cannot read the {what} {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise SparseIngestError(f"the {what} {path} is not a JSON object")
    return document


def _read_job_log(path: Path) -> tuple[dict[str, object], ...]:
    """Read one job's JSONL log, one entry per line, refusing an unreadable line."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SparseIngestError(f"cannot read the job log {path}: {exc}") from exc
    entries: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise SparseIngestError(
                f"the job log {path} line {number} is not JSON: {exc}"
            ) from exc
        if not isinstance(entry, dict):
            raise SparseIngestError(
                f"the job log {path} line {number} is not a JSON object"
            )
        entries.append(entry)
    return tuple(entries)


def _sequence(value: object, what: str) -> tuple[object, ...]:
    """One JSON array, or a named refusal."""
    if not isinstance(value, list):
        raise SparseIngestError(f"{what} is not a JSON array")
    return tuple(value)


def _objects(value: object, what: str) -> tuple[dict[str, object], ...]:
    """One JSON array of objects, or a named refusal."""
    items = _sequence(value, what)
    for item in items:
        if not isinstance(item, dict):
            raise SparseIngestError(f"{what} holds a non-object entry")
    return tuple(item for item in items if isinstance(item, dict))


def _dataset_relative(root: Path, recorded: object, job: str, what: str) -> str:
    """The dataset-relative name of one of a job's own files, refused when absent.

    The pass record names such a file by the store path it was written to
    (``outputs/live/store/<name>``) while the committed dataset holds the same
    basename beside the recordings: the binding is by basename inside the dataset's
    own root, and a name that resolves to nothing committed is a refusal rather
    than an empty row.
    """
    name = Path(str(recorded or "")).name
    if not name:
        raise SparseIngestError(f"job {job!r}: the record names no {what} file")
    if not (root / name).is_file():
        raise SparseIngestError(
            f"job {job!r}: the record's {what} {recorded!r} is not committed as "
            f"{root / name}"
        )
    return name


# ── the pass's own record ──────────────────────────────────────────────


class PlannedJobRecord(NamedTuple):
    """One job of the pass: what the plan says, and what the run left behind.

    ``points`` are the plan's planned points, ``entries`` the job's log (one entry
    per planned point, in the order the runner wrote them) and ``outcomes`` the job
    manifest's own list. The three are checked against each other before any of them
    supplies a row.
    """

    step: int
    job: str
    kind: str
    burst_length: int
    emissions_per_profile: int
    prf_us: float
    name_prefix: str
    definition: str
    definition_fingerprint: str
    started_at: str
    finished_at: str
    log_relative_path: str
    manifest_relative_path: str
    points: tuple[PlannedPoint, ...]
    entries: tuple[dict[str, object], ...]
    outcomes: tuple[dict[str, object], ...]

    @property
    def condition(self) -> tuple[int, int, float]:
        """The job's run-wide identity: the triple its recordings share."""
        return (self.burst_length, self.emissions_per_profile, self.prf_us)


def read_run_record(
    dataset_root: Path, *, plan_name: str = PLAN_NAME
) -> dict[str, object]:
    """Read ``<plan_name>.run.json`` — the pass's own record — from the dataset root.

    ``plan_name`` defaults to this pass's own name, so every existing caller and every
    committed artefact is unchanged; a second pass whose record is named differently
    passes its own, and the record's schema and refusals are the same for both.
    """
    return _read_json(Path(dataset_root) / f"{plan_name}.run.json", "pass record")


def read_job_records(
    dataset_root: Path, plan: run_plan.PlannedRun, run: Mapping[str, object]
) -> tuple[PlannedJobRecord, ...]:
    """Bind every job of the pass to the plan and to the record the run left.

    The plan is the authority for what a job *is* (its step, kind, run-wide
    condition, definition and definition fingerprint); the pass record is the
    authority for when it ran and where its log and manifest are; the log and the
    manifest are checked against each other and against the plan's fingerprints
    before either supplies a row.
    """
    root = Path(dataset_root)
    recorded = {
        str(job.get("job")): job
        for job in _objects(run.get("jobs"), "the pass record's jobs")
    }
    records: list[PlannedJobRecord] = []
    for job in plan.jobs:
        entry = recorded.get(job.job)
        if entry is None:
            raise SparseIngestError(
                f"the pass record holds no row for job {job.job!r}; the plan has "
                f"{[item.job for item in plan.jobs]}"
            )
        if int(entry.get("step") or 0) != job.step:
            raise SparseIngestError(
                f"job {job.job!r}: the record places it at step {entry.get('step')}, "
                f"the plan at step {job.step}"
            )
        declaration = entry.get("condition")
        if not isinstance(declaration, dict) or (
            int(declaration.get("burst_length") or 0) != job.condition.burst_length
            or int(declaration.get("emissions_per_profile") or 0)
            != job.condition.emissions_per_profile
            or float(declaration.get("prf_us") or 0.0) != job.condition.prf_us
        ):
            raise SparseIngestError(
                f"job {job.job!r}: the record's condition {declaration} is not the "
                f"plan's {job.condition.as_triple}"
            )
        if str(entry.get("definition_fingerprint") or "") != job.definition_fingerprint:
            raise SparseIngestError(
                f"job {job.job!r}: the record's definition fingerprint "
                f"{entry.get('definition_fingerprint')!r} is not the plan's "
                f"{job.definition_fingerprint!r}; the plan and the pass record have to "
                "be the same nine jobs"
            )
        definition_path = Path(plan.directory) / job.definition
        definition = _read_json(definition_path, f"definition of {job.job!r}")
        prefix = str(definition.get("name_prefix") or "")
        if not prefix:
            raise SparseIngestError(
                f"job {job.job!r}: its definition states no name_prefix, so no stored "
                "file can be bound to it"
            )
        log_relative = _dataset_relative(root, entry.get("log"), job.job, "log")
        manifest_relative = _dataset_relative(
            root, entry.get("manifest"), job.job, "manifest"
        )
        entries = _read_job_log(root / log_relative)
        manifest = _read_json(root / manifest_relative, f"job manifest of {job.job!r}")
        if str(manifest.get("fingerprint") or "") != job.definition_fingerprint:
            raise SparseIngestError(
                f"job {job.job!r}: the manifest's definition fingerprint is "
                f"{manifest.get('fingerprint')!r}, the plan's is "
                f"{job.definition_fingerprint!r}"
            )
        outcomes = _objects(manifest.get("outcomes"), f"{job.job} outcomes")
        if len(entries) != len(job.points) or len(outcomes) != len(job.points):
            raise SparseIngestError(
                f"job {job.job!r}: the plan holds {len(job.points)} point(s), the log "
                f"{len(entries)}, the manifest {len(outcomes)}; the pass record must "
                "describe exactly the planned points"
            )
        records.append(
            PlannedJobRecord(
                step=job.step,
                job=job.job,
                kind=job.kind.value,
                burst_length=job.condition.burst_length,
                emissions_per_profile=job.condition.emissions_per_profile,
                prf_us=job.condition.prf_us,
                name_prefix=prefix,
                definition=job.definition,
                definition_fingerprint=job.definition_fingerprint,
                started_at=str(
                    manifest.get("started_at") or entry.get("started_at") or ""
                ),
                finished_at=str(
                    manifest.get("finished_at") or entry.get("finished_at") or ""
                ),
                log_relative_path=log_relative,
                manifest_relative_path=manifest_relative,
                points=job.points,
                entries=entries,
                outcomes=outcomes,
            )
        )
    return tuple(records)


# ── binding a committed recording to the point it was planned for ──────


class PointBinding(NamedTuple):
    """One stored recording, bound to the planned point it realizes.

    ``outcome`` is the job manifest's own row for the point (its identity, label,
    stored file and verdict), ``entry`` the job log's, ``point`` the plan's, and
    ``order`` the point's 1-based position in the whole pass — which is what makes
    the pass's acquisition order recoverable, unlike the historical sweep's.
    """

    job: PlannedJobRecord
    point: PlannedPoint
    outcome: Mapping[str, object]
    entry: Mapping[str, object]
    relative_path: str
    recording_stamp: str
    order: int

    @property
    def identity(self) -> str:
        """The point's identity as the pass's own records spell it."""
        return f"{self.job.name_prefix}-{self.point.label}"


def discover_recordings(dataset_root: Path) -> tuple[Path, ...]:
    """Every committed ``.BDD`` recording of the pass, sorted by name.

    The one declared discovery rule: the dataset root's own files. No second
    filename list is maintained anywhere in this module.
    """
    root = Path(dataset_root)
    return tuple(sorted(path for path in root.glob("*.BDD") if path.is_file()))


def _identity_of(entry: Mapping[str, object], job: str) -> str:
    """The identity a manifest outcome carries, refused when absent."""
    identity = str(entry.get("identity") or "")
    if not identity:
        raise SparseIngestError(f"job {job!r}: an outcome carries no identity")
    return identity


def bind_recordings(
    dataset_root: Path, records: Sequence[PlannedJobRecord]
) -> tuple[PointBinding, ...]:
    """Bind every committed recording to exactly one planned point.

    The binding is by identity, and both halves are checked: the job's log and its
    manifest must agree on each point's identity, label and stored file, and the
    identity must be the pass's own ``<name_prefix>-<label>`` for that point. A
    committed recording no point claims, or a point whose file is not committed, is
    a refusal — a silently dropped row is exactly the failure an audit would have to
    report.
    """
    root = Path(dataset_root)
    claimed: dict[str, PointBinding] = {}
    order = 0
    for record in records:
        for point, entry, outcome in zip(
            record.points, record.entries, record.outcomes, strict=True
        ):
            order += 1
            binding = PointBinding(
                job=record,
                point=point,
                outcome=outcome,
                entry=entry,
                relative_path="",
                recording_stamp="",
                order=order,
            )
            expected = binding.identity
            if _identity_of(outcome, record.job) != expected:
                raise SparseIngestError(
                    f"job {record.job!r}: the manifest's identity "
                    f"{_identity_of(outcome, record.job)!r} is not the plan's identity "
                    f"{expected!r} for key {point.key}"
                )
            if str(outcome.get("label") or "") != point.label:
                raise SparseIngestError(
                    f"job {record.job!r}: the manifest labels {expected!r} as "
                    f"{outcome.get('label')!r}, the plan as {point.label!r}"
                )
            if int(entry.get("key") or 0) != point.key:
                raise SparseIngestError(
                    f"job {record.job!r}: {expected!r} is key {entry.get('key')} in the "
                    f"log, key {point.key} in the plan"
                )
            name = Path(str(outcome.get("file") or "")).name
            if not name:
                raise SparseIngestError(
                    f"job {record.job!r}: the manifest claims no file for {expected!r}"
                )
            if name in claimed:
                raise SparseIngestError(
                    f"the pass record claims {name!r} twice: every stored file belongs "
                    "to exactly one point"
                )
            # The log names the same file by its stem — the identity plus the store
            # stamp — and by the path it was written to: both are checked, so the two
            # records of one point cannot describe different files or different points.
            stamp = Path(name).stem.rsplit("-", 1)[-1]
            if str(entry.get("name") or "") != f"{expected}-{stamp}":
                raise SparseIngestError(
                    f"job {record.job!r}: the log's point {entry.get('name')!r} is not "
                    f"the manifest's {expected!r} stored as {name!r}"
                )
            if Path(str(entry.get("file_path") or "")).name != name:
                raise SparseIngestError(
                    f"job {record.job!r}: the log wrote {entry.get('file_path')!r}, the "
                    f"manifest stored {name!r}"
                )
            if str(entry.get("status") or "") != "ok" or outcome.get("ok") is not True:
                raise SparseIngestError(
                    f"job {record.job!r}: {expected!r} is committed but its own "
                    f"verdicts are log status {entry.get('status')!r} and manifest ok "
                    f"{outcome.get('ok')!r}; a stored file that failed its own "
                    "verification is not a point of this pass"
                )
            claimed[name] = binding._replace(relative_path=name, recording_stamp=stamp)
    on_disk = {path.name for path in discover_recordings(root)}
    unbound = sorted(on_disk - set(claimed))
    if unbound:
        raise SparseIngestError(
            f"committed recordings no planned point claims: {unbound}"
        )
    missing = sorted(set(claimed) - on_disk)
    if missing:
        raise SparseIngestError(
            f"planned points whose stored recording is not committed: {missing}"
        )
    return tuple(claimed[path.name] for path in discover_recordings(root))


# ── decoding one bound recording ───────────────────────────────────────


class DecodedPoint(NamedTuple):
    """One bound recording, decoded: its arrays, its config and its observed cells."""

    binding: PointBinding
    values: np.ndarray
    time_s: np.ndarray
    depths: np.ndarray
    config: ChannelConfig
    quantity: str
    unit: str
    source_sha256: str
    file_size_bytes: int

    @property
    def relative_path(self) -> str:
        """The recording's dataset-relative name."""
        return self.binding.relative_path


def _prf_period_us(config: ChannelConfig) -> float | None:
    """PRF period in microseconds, inverted back from the reader's Hz field (word 5)."""
    if not config.pulse_repetition_freq_hz:
        return None
    return 1e6 / float(config.pulse_repetition_freq_hz)


def observed_cells(point: DecodedPoint) -> dict[str, object]:
    """The decoded value of every quantity a stored word or the log carries.

    One implementation for both the log cross-check and the row, so the two can
    never disagree about what the reader found.
    """
    values, time_s, depths = point.values, point.time_s, point.depths
    config = point.config
    return {
        "profiles": int(values.shape[0]),
        "gates": int(values.shape[1]),
        "duration_s": float(time_s[-1] - time_s[0]),
        "depth_min_mm": float(depths[0]),
        "depth_max_mm": float(np.max(depths)),
        "emit_freq_khz": config.source_freq_khz,
        "prf_period_us": _prf_period_us(config),
        "prf_hz": config.pulse_repetition_freq_hz,
        "burst_length": config.burst_length,
        "emissions_per_profile": config.emissions_per_profile,
        "emit_power": config.emit_power,
        "sensitivity": config.sensitivity,
        "resolution_mm": config.resolution_mm,
        "sampling_volume_index": config.sampling_volume_index,
        "sound_speed_ms": config.sound_speed_ms,
        "doppler_angle_deg": config.doppler_angle_deg,
        "velo_max_ms": config.velo_max_ms,
        "tgc_mode": config.tgc_mode,
        "tgc_start_db": config.tgc_start_db,
        "tgc_end_db": config.tgc_end_db,
        "skipped_profiles": config.skipped_profiles,
        "size_bytes": int(point.file_size_bytes),
        "median_interval_s": float(np.median(np.diff(time_s))),
        "achieved_period_s": float((time_s[-1] - time_s[0]) / (time_s.size - 1)),
    }


def decode_point(path: Path, binding: PointBinding) -> DecodedPoint | str:
    """Decode one committed recording, or return the failure that stopped it.

    Args:
        path: the committed recording.
        binding: the planned point the pass's own record claims it realizes.

    Returns:
        The decoded recording, or the ``"<Type>: <message>"`` string of the failure.
        A recording that cannot be decoded becomes a row carrying that string, so a
        crash can never remove the very point an audit has to report.
    """
    try:
        bundle = load(path)
    except Exception as exc:  # noqa: BLE001 - a row that cannot decode is a failure
        return f"{type(exc).__name__}: {exc}"
    recording = bundle.recording
    if len(recording.streams) != 1:
        return f"expected exactly one channel stream, found {len(recording.streams)}"
    stream = recording.streams[0]
    return DecodedPoint(
        binding=binding,
        values=np.asarray(stream.data.values, dtype=float),
        time_s=np.asarray(stream.data.time_s, dtype=float),
        depths=np.asarray(stream.data.gate_depths_mm, dtype=float),
        config=stream.config,
        quantity=str(stream.descriptor.quantity.value),
        unit=str(stream.descriptor.unit),
        source_sha256=recording.source_asset.content_sha256,
        file_size_bytes=Path(path).stat().st_size,
    )


# ── the checks the table has to survive ────────────────────────────────


def require_reader_agrees_with_the_log(point: DecodedPoint) -> None:
    """Refuse a recording whose decode disagrees with the acquisition layer's own.

    A job log records the settings, shape, size and timing the runner itself decoded
    from the file it had just stored — an independent decode of the same bytes, by a
    reader that never sees this one. The two must agree: a disagreement means one of
    them is wrong about the file, and no scientific number may be built on either.
    """
    decoded = point.binding.entry.get("decoded")
    if not isinstance(decoded, dict):
        raise SparseIngestError(
            f"{point.relative_path}: the job log carries no decoded block"
        )
    observed = observed_cells(point)
    cells = {
        "n_gates": ("gates", observed["gates"], None),
        "n_profiles": ("profiles", observed["profiles"], None),
        "size_bytes": ("size_bytes", observed["size_bytes"], None),
        "sound_speed_ms": ("sound_speed_ms", observed["sound_speed_ms"], None),
        "prf_us": ("prf_period_us", observed["prf_period_us"], None),
        "burst_length": ("burst_length", observed["burst_length"], None),
        "emissions_per_profile": (
            "emissions_per_profile",
            observed["emissions_per_profile"],
            None,
        ),
        "source_freq_khz": ("emit_freq_khz", observed["emit_freq_khz"], None),
        "span_s": ("duration_s", observed["duration_s"], LOG_SPAN_TOLERANCE_S),
        "median_interval_s": (
            "median_interval_s",
            observed["median_interval_s"],
            LOG_SPAN_TOLERANCE_S,
        ),
        "achieved_period_s": (
            "achieved_period_s",
            observed["achieved_period_s"],
            None,
        ),
    }
    for logged, (cell, mine, tolerance) in cells.items():
        theirs = decoded.get(logged)
        if theirs is None or mine is None:
            raise SparseIngestError(
                f"{point.relative_path}: the log's decoded {logged}={theirs!r} and this "
                f"reader's {cell}={mine!r} must both be present"
            )
        if tolerance is None:
            agree = math.isclose(
                float(theirs), float(mine), rel_tol=LOG_PERIOD_REL_TOLERANCE
            )
        else:
            agree = abs(float(theirs) - float(mine)) <= tolerance
        if not agree:
            raise SparseIngestError(
                f"{point.relative_path}: the job log decoded {logged}={theirs!r}, this "
                f"reader decodes {cell}={mine!r}; the two decodes of the stored bytes "
                "must agree before either is used"
            )


def require_declared_settings(point: DecodedPoint) -> None:
    """Refuse a file whose own words are not the condition and window it was planned at.

    The condition is the job's — burst, emissions and PRF are dialog-only values a
    point cannot write, so the stored words are the only evidence a job held them —
    and the window is the point's own. Word 14 is this pass's *raised* fact, the one
    the plan treats as mandatory, so a disagreement invalidates the point rather than
    being recorded as an advisory.
    """
    binding = point.binding
    observed = observed_cells(point)
    planned = binding.point.parameters
    for cell, wanted in (
        ("burst_length", binding.job.burst_length),
        ("emissions_per_profile", binding.job.emissions_per_profile),
        ("gates", planned.gates),
    ):
        if int(observed[cell]) != int(wanted):
            raise SparseIngestError(
                f"{binding.relative_path}: the file's own {cell} is {observed[cell]!r}, "
                f"the pass planned {wanted!r}"
            )
    for cell, wanted, tolerance in (
        ("prf_period_us", binding.job.prf_us, GRID_RTOL),
        ("sound_speed_ms", float(planned.sound_speed_ms), GRID_RTOL),
    ):
        if not math.isclose(float(observed[cell]), float(wanted), rel_tol=tolerance):
            raise SparseIngestError(
                f"{binding.relative_path}: the file's own {cell} is {observed[cell]!r}, "
                f"the pass planned {wanted!r}"
            )
    requested = (round(float(planned.resolution_mm), 6), int(planned.gates))
    if requested not in {
        (round(resolution, 6), gates) for resolution, gates in PLAN_WINDOWS
    }:
        raise SparseIngestError(
            f"{binding.relative_path}: the point requests {requested}, which is not one "
            f"of the pass's windows {PLAN_WINDOWS}"
        )
    # The request is not the setting: the application snaps the pitch to the ladder
    # rung nearest the request, and the stored file carries the achieved rung. Both
    # sides are computed by the planner's own reviewed law rather than by arithmetic
    # restated here.
    accepted = clamp_resolution(
        float(planned.resolution_mm), float(planned.sound_speed_ms)
    )
    if not math.isclose(
        float(observed["resolution_mm"]), float(accepted), rel_tol=GRID_RTOL
    ):
        raise SparseIngestError(
            f"{binding.relative_path}: the file's own pitch is "
            f"{observed['resolution_mm']!r} mm, the rung the application accepts for "
            f"the requested {planned.resolution_mm!r} mm is {accepted!r} mm"
        )


def require_retired_target(point: DecodedPoint, *, plan_name: str = PLAN_NAME) -> None:
    """Refuse a log whose ``timing.target_s`` is not a planning expectation at all.

    ``timing.target_s`` is provenance: it reproduces the planner's expectation for the
    point's own decoded emissions and PRF, never the achieved period. Two planning forms
    have planned this repository's sparse passes — the retired
    ``emissions x PRF + 1 ms`` and the manual's ``T_tran + T_prf x (16 + N_PRF)`` — and a
    pass names its own form in :data:`PERIOD_LAW_BY_PASS`. A pass that names no form is
    screened against either, so an older campaign this table does not classify keeps the
    behaviour it had before the table existed; a log rewritten to the *achieved* period
    is refused either way.
    """
    timing = point.binding.entry.get("timing")
    if not isinstance(timing, dict) or timing.get("target_s") is None:
        raise SparseIngestError(
            f"{point.relative_path}: the job log records no timing.target_s"
        )
    emissions = float(point.binding.job.emissions_per_profile)
    prf_us = float(point.binding.job.prf_us)
    recorded = float(timing["target_s"])
    retired = emissions * prf_us * 1e-6 + RETIRED_PERIOD_TRANSFER_S
    planner = profile_period_s(int(emissions), prf_us)
    pinned = PERIOD_LAW_BY_PASS.get(plan_name)
    if pinned is None:
        if (
            min(abs(recorded - retired), abs(recorded - planner))
            <= LOG_TARGET_TOLERANCE_S
        ):
            return
        raise SparseIngestError(
            f"{point.relative_path}: the log's timing.target_s is {recorded!r}, which is "
            f"neither planning form for this point's decoded emissions and PRF "
            f"({retired!r} {RETIRED_PERIOD_LAW}; {planner!r} {PLANNER_PERIOD_LAW}); the "
            "logs are provenance and are not rewritten"
        )
    expected = retired if pinned == RETIRED_PERIOD_LAW else planner
    if abs(recorded - expected) > LOG_TARGET_TOLERANCE_S:
        raise SparseIngestError(
            f"{point.relative_path}: the log's timing.target_s is {recorded!r}, the "
            f"{plan_name} planning law ({pinned}) gives {expected!r} for this point's "
            "decoded emissions and PRF; the logs are provenance and are not rewritten"
        )


# ── the row ────────────────────────────────────────────────────────────


def common_window_s(spans_s: Sequence[float]) -> float:
    """The pass's designed exposure, once every recording is shown to cover it.

    The primary distributional view is the interval the pass **asked for** — the
    declared 12 s, 100 nominal 500-RPM revolutions — and not the largest whole
    interval the stored timestamps happen to support. Every recording here retained
    more than 12 s (12.4686-12.5888 s), but that extra span is the acquisition's
    stopping latency: taking it as exposure would let the rig's overrun set the
    analysed interval, so it is left to the full-record view (spectra,
    autocorrelation) and this function *refuses* a dataset where the designed window
    does not fit rather than narrowing to a shorter one.
    """
    if not spans_s:
        raise SparseIngestError("no recording decoded, so no common window exists")
    shortest = min(spans_s)
    if shortest + TOLERANCE_S < DESIGNED_WINDOW_S:
        raise SparseIngestError(
            f"the shortest recording retains {shortest!r} s, less than the pass's "
            f"designed {DESIGNED_WINDOW_S:g} s ({DESIGNED_REVOLUTIONS} nominal "
            f"{NOMINAL_RPM:g}-RPM revolutions): the primary view would leave the design"
        )
    return DESIGNED_WINDOW_S


def build_row(
    point: DecodedPoint,
    *,
    support: tuple[float, float],
    revolutions: int,
    window_s: float,
    window_profiles: int,
    plan_fingerprint: str,
    plan_name: str = PLAN_NAME,
) -> dict[str, str]:
    """One point's row, every cell formatted for the CSV contract.

    The two views the row's numbers come from: the recording's **full record** for
    the shape, retention and whole-record counters, and the **common window**
    (``window_s``) restricted to the **common physical support** for the
    distributional metrics — the same window and the same support for every
    recording, so one row's supported numbers are comparable with another's.
    """
    binding = point.binding
    values, time_s, depths, config = (
        point.values,
        point.time_s,
        point.depths,
        point.config,
    )
    intervals = np.diff(time_s)
    span = float(time_s[-1] - time_s[0])
    achieved = float(span / (time_s.size - 1))
    expected_period = profile_period_s(
        int(config.emissions_per_profile or 0), float(_prf_period_us(config) or 0.0)
    )
    trimmed = window(values, time_s, window_s)
    mask = in_support(depths, support)
    supported = trimmed[:, mask]
    metrics = gate_metrics(supported) if supported.size else {}
    planned = binding.point.parameters
    cell = format_cell
    return {
        "relative_path": binding.relative_path,
        "order": cell(binding.order),
        "step": cell(binding.job.step),
        "job": binding.job.job,
        "kind": binding.job.kind,
        "requested_label": binding.point.label,
        "identity": binding.identity,
        "point_key": cell(binding.point.key),
        "job_started_at": binding.job.started_at,
        "job_finished_at": binding.job.finished_at,
        "recording_stamp": binding.recording_stamp,
        "declared_burst_length": cell(binding.job.burst_length),
        "declared_emissions_per_profile": cell(binding.job.emissions_per_profile),
        "declared_prf_us": cell(binding.job.prf_us),
        "declared_resolution_mm": cell(float(planned.resolution_mm)),
        "declared_accepted_resolution_mm": cell(
            clamp_resolution(
                float(planned.resolution_mm), float(planned.sound_speed_ms)
            )
        ),
        "declared_gates": cell(int(planned.gates)),
        "declared_first_gate_mm": cell(float(planned.first_gate_mm)),
        "declared_depth_mm": cell(float(planned.depth_mm)),
        "is_control": cell(binding.point.label.startswith(CONTROL_PREFIX)),
        "quantity": point.quantity,
        "unit": point.unit,
        "profiles": cell(int(values.shape[0])),
        "gates": cell(int(values.shape[1])),
        "duration_s": cell(span),
        "depth_min_mm": cell(float(depths[0])),
        "depth_max_mm": cell(float(np.max(depths))),
        "resolution_mm": cell(config.resolution_mm),
        "prf_period_us": cell(_prf_period_us(config)),
        "prf_hz": cell(config.pulse_repetition_freq_hz),
        "burst_length": cell(config.burst_length),
        "emissions_per_profile": cell(config.emissions_per_profile),
        "emit_freq_khz": cell(config.source_freq_khz),
        "emit_power": cell(config.emit_power),
        "sensitivity": cell(config.sensitivity),
        "sampling_volume_index": cell(config.sampling_volume_index),
        "sound_speed_ms": cell(config.sound_speed_ms),
        "doppler_angle_deg": cell(config.doppler_angle_deg),
        "velo_max_ms": cell(config.velo_max_ms),
        "tgc_mode": cell(config.tgc_mode),
        "tgc_start_db": cell(config.tgc_start_db),
        "tgc_end_db": cell(config.tgc_end_db),
        "skipped_profiles": cell(config.skipped_profiles),
        "op_word_14": cell(config.emissions_per_profile),
        "op_word_27": cell(config.sampling_volume_index),
        "op_word_84": cell(config.skipped_profiles),
        "requested_duration_s": cell(REQUESTED_DURATION_S),
        "median_interval_s": cell(float(np.median(intervals))),
        "interval_iqr_s": cell(
            float(np.percentile(intervals, 75.0) - np.percentile(intervals, 25.0))
        ),
        "achieved_period_s": cell(achieved),
        "retained_fraction": cell(span / REQUESTED_DURATION_S),
        "designed_window_s": cell(DESIGNED_WINDOW_S),
        "retains_designed_window": cell(span + TOLERANCE_S >= DESIGNED_WINDOW_S),
        "period_expectation_s": cell(expected_period),
        "period_residual_s": cell(achieved - expected_period),
        "timestamps_monotone": cell(bool(np.all(intervals > 0.0))),
        "nan_count": cell(int(np.count_nonzero(np.isnan(values)))),
        "zero_fraction": cell(float(np.count_nonzero(values == 0.0) / values.size)),
        "non_zero_fraction": cell(float(np.count_nonzero(values != 0.0) / values.size)),
        "velocity_min_mm_s": cell(float(np.min(values))),
        "velocity_max_mm_s": cell(float(np.max(values))),
        "supported_gates": cell(int(np.count_nonzero(mask))),
        "window_revolutions": cell(int(revolutions)),
        "window_s": cell(window_s),
        "window_profiles": cell(int(window_profiles)),
        "supported_mean_mm_s": cell(_mean_of(metrics, "mean")),
        "supported_median_mm_s": cell(_mean_of(metrics, "median")),
        "supported_iqr_mm_s": cell(_mean_of(metrics, "iqr")),
        "supported_rms_mm_s": cell(_mean_of(metrics, "rms")),
        "supported_zero_fraction": cell(_mean_of(metrics, "zero_fraction")),
        "source_sha256": point.source_sha256,
        "file_size_bytes": cell(point.file_size_bytes),
        "log_relative_path": binding.job.log_relative_path,
        "log_status": cell(binding.entry.get("status")),
        "log_target_s": cell(
            float((binding.entry.get("timing") or {}).get("target_s"))
        ),
        "log_achieved_period_s": cell(
            float((binding.entry.get("timing") or {}).get("achieved_s"))
        ),
        "log_median_interval_s": cell(
            float((binding.entry.get("decoded") or {}).get("median_interval_s"))
        ),
        "manifest_relative_path": binding.job.manifest_relative_path,
        "job_definition": binding.job.definition,
        "job_definition_fingerprint": binding.job.definition_fingerprint,
        "plan": plan_name,
        "plan_fingerprint": plan_fingerprint,
        "decode_error": "",
    }


def _mean_of(metrics: Mapping[str, np.ndarray], name: str) -> float:
    """The unweighted mean of one per-gate metric across a point's supported gates."""
    if name not in metrics or metrics[name].size == 0:
        return math.nan
    return float(np.mean(metrics[name]))


def failed_row(
    binding: PointBinding,
    error: str,
    plan_fingerprint: str,
    plan_name: str = PLAN_NAME,
) -> dict[str, str]:
    """A row for a recording that could not be decoded: its identity, and the failure.

    Every measurement cell is empty, so a failed file cannot be mistaken for a
    measurement; the ``decode_failures`` check is what reports it.
    """
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        {
            "relative_path": binding.relative_path,
            "order": format_cell(binding.order),
            "step": format_cell(binding.job.step),
            "job": binding.job.job,
            "kind": binding.job.kind,
            "requested_label": binding.point.label,
            "identity": binding.identity,
            "point_key": format_cell(binding.point.key),
            "recording_stamp": binding.recording_stamp,
            "log_relative_path": binding.job.log_relative_path,
            "manifest_relative_path": binding.job.manifest_relative_path,
            "job_definition": binding.job.definition,
            "job_definition_fingerprint": binding.job.definition_fingerprint,
            "plan": plan_name,
            "plan_fingerprint": plan_fingerprint,
            "decode_error": error,
        }
    )
    return row


# ── the artefact ───────────────────────────────────────────────────────


class SparseIngest(ValueModel):
    """The WP0 result: the points table plus the dataset-level QC of the pass.

    ``checks`` records each WP0 gate assertion and ``ok`` is true only when all of
    them hold — the command exits non-zero on a false ``ok``. ``rows`` is the
    ``points.csv`` table, one ``COLUMNS``-keyed string row per committed recording.
    """

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    analysis_commit: str | None = None
    points_name: str
    points_rows: int
    points_sha256: str
    recordings: int
    expected_recordings: int
    job_counts: dict[str, int]
    expected_job_counts: dict[str, int]
    decode_failures: int
    decode_failure_files: tuple[str, ...]
    nan_cells: int
    non_monotone_files: tuple[str, ...]
    not_live_files: tuple[str, ...]
    short_retention_files: tuple[str, ...]
    max_abs_period_residual_s: float
    support_mm: tuple[float, float]
    window_revolutions: int
    window_s: float
    checks: dict[str, bool]
    ok: bool
    rows: tuple[dict[str, str], ...]

    @model_validator(mode="after")
    def _check_ok_matches_checks(self) -> SparseIngest:
        if self.ok is not all(self.checks.values()):
            raise ValueError(
                f"ok must equal all(checks); ok={self.ok} for checks={self.checks}"
            )
        return self


def points_csv_text(rows: Sequence[Mapping[str, str]]) -> str:
    """Render ``points.csv`` (LF endings, one trailing newline, POSIX paths)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(COLUMNS), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def regeneration_command(
    commit: str | None,
    *,
    plan_name: str = PLAN_NAME,
    dataset_root: Path | None = None,
    plan_path: Path | None = None,
    report_dir: Path | None = None,
) -> str:
    """The exact command that reproduces a pass's committed artefacts byte for byte.

    The first pass's bare form is emitted unchanged: a flag is added only for an input
    that differs from this module's own default, so a pass whose inputs are the first
    pass's is described by exactly the command the committed artefacts carry. A second
    pass names its own dataset, plan, plan name and report directory, by the
    repository's convention (``data/<plan>``, ``examples/<plan>/run-plan.json``,
    ``reports/<plan>``) unless a caller passes explicit paths.
    """
    root = Path(dataset_root) if dataset_root is not None else Path("data") / plan_name
    plan = (
        Path(plan_path)
        if plan_path is not None
        else Path("examples") / plan_name / "run-plan.json"
    )
    report = Path(report_dir) if report_dir is not None else Path("reports") / plan_name
    parts = [
        ".venv/Scripts/python.exe",
        "-m",
        "udv_echo_process.cli",
        "sparse-inventory",
    ]
    if root.as_posix() != DATASET_ROOT.as_posix():
        parts += ["--dataset-root", root.as_posix()]
    if plan.as_posix() != PLAN_PATH.as_posix():
        parts += ["--plan", plan.as_posix()]
    if report.as_posix() != REPORT_DIR.as_posix():
        parts += ["--report-dir", report.as_posix()]
    if plan_name != PLAN_NAME:
        parts += ["--plan-name", plan_name]
    parts += ["--analysis-commit", commit or "<generator commit>"]
    return " ".join(parts)


def _word_summary(rows: Sequence[Mapping[str, str]], column: str) -> dict[str, object]:
    """The distinct stored values of one op word across the table, with their counts."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[column]] = counts.get(row[column], 0) + 1
    return {"values": sorted(counts), "counts": dict(sorted(counts.items()))}


def qc_document(ingest: SparseIngest) -> dict[str, object]:
    """The QC summary document: the pass-level assertions, never the table rows.

    Keys are inserted in a fixed order so a regeneration from the same commit is
    byte-identical.
    """
    return {
        "dataset_root": ingest.dataset_root,
        "plan": ingest.plan,
        "plan_path": ingest.plan_path,
        "plan_fingerprint": ingest.plan_fingerprint,
        "analysis_commit": ingest.analysis_commit,
        "points": ingest.points_name,
        "points_rows": ingest.points_rows,
        "points_sha256": ingest.points_sha256,
        "recordings": ingest.recordings,
        "expected_recordings": ingest.expected_recordings,
        "job_counts": ingest.job_counts,
        "expected_job_counts": ingest.expected_job_counts,
        "decode_failures": ingest.decode_failures,
        "decode_failure_files": list(ingest.decode_failure_files),
        "nan_cells": ingest.nan_cells,
        "non_monotone_files": list(ingest.non_monotone_files),
        "not_live_files": list(ingest.not_live_files),
        "short_retention_files": list(ingest.short_retention_files),
        "max_abs_period_residual_s": ingest.max_abs_period_residual_s,
        "observed_words": {
            "op_word_14": _word_summary(ingest.rows, "op_word_14"),
            "op_word_27": _word_summary(ingest.rows, "op_word_27"),
            "op_word_84": _word_summary(ingest.rows, "op_word_84"),
            "note": (
                "the stored op words of the 26 recordings, decoded independently by this "
                "reader and re-published here so the prose that cites them has one "
                "machine-readable authority. Word 14 is each point's own emissions "
                "request; word 84 is the stored skipped-profile count. Word 27 is the "
                "instrument's option-list INDEX, not a length: the index-to-mm relation "
                "is medium- and burst-dependent and was only ever measured at one sound "
                "speed, so the historical sweep's stored index (4) and this pass's (1) "
                "are not the same measurement of a shared setting, and neither states an "
                "acoustic averaging length. No analysis may read the two as one setting"
            ),
        },
        "views": {
            "point_table": (
                "one row per committed recording; the full record for the shape, the "
                "retention and the whole-record counters"
            ),
            "common_window": {
                "revolutions": ingest.window_revolutions,
                "nominal_rpm": NOMINAL_RPM,
                "revolution_s": REVOLUTION_S,
                "window_s": ingest.window_s,
                "rule": (
                    "the interval the pass asked every recording for, 100 nominal "
                    f"{NOMINAL_RPM:g}-RPM revolutions = {DESIGNED_WINDOW_S:g} s, cut in each "
                    "recording by that recording's own stored timestamps. It is NOT "
                    "widened to the largest interval the files happen to support: the "
                    "surplus span (12.4686-12.5888 s retained) is the acquisition's "
                    "stopping latency, so it belongs to the full-record view "
                    "(spectra, autocorrelation) and not to the primary exposure"
                ),
            },
            "common_support": {
                "support_min_mm": ingest.support_mm[0],
                "support_max_mm": ingest.support_mm[1],
                "rule": (
                    "the intersection of every recording's decoded depth range; the "
                    "supported metrics are computed on each recording's own native "
                    "gate grid inside it, and no interpolation or resampling is "
                    "applied anywhere in this report"
                ),
            },
            "achieved_timing": (
                "the profile period is measured from each recording's own stored "
                "timestamps; the logs' timing.target_s is carried as provenance "
                f"({RETIRED_PERIOD_LAW}) and is never used as a measurement"
            ),
        },
        "definitions": dict(DEFINITIONS),
        "checks": dict(sorted(ingest.checks.items())),
        "ok": ingest.ok,
        "regeneration": {
            "command": regeneration_command(
                ingest.analysis_commit, plan_name=ingest.plan
            ),
            "note": (
                "pass the recorded analysis_commit to reproduce these artefacts byte "
                "for byte; the bare command records the current HEAD"
            ),
        },
    }


def build_sparse_ingest(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    plan_name: str | None = None,
    analysis_commit: str | None = None,
) -> SparseIngest:
    """Decode every committed recording and build the WP0 ingest.

    Args:
        dataset_root: the directory holding the pass's ``.BDD`` recordings and its own
            record, logs and manifests.
        plan_path: the frozen plan the pass is a realization of.
        plan_name: the pass name, which names the record ``<plan_name>.run.json`` inside
            the dataset root. ``None`` — the default — takes the plan's own name, so a
            pass whose plan names itself needs no second declaration; passing a name
            that is not the plan's is refused.
        analysis_commit: the revision to record in the QC summary.

    Raises:
        SparseIngestError: for a pass record or a plan the dataset does not answer
            to, a recording no planned point claims (or the reverse), two decodes of
            the same bytes that disagree, a stored word that is not the declared
            setting, or a log whose planning target has been rewritten.
    """
    root = Path(dataset_root)
    plan = run_plan.plan_run_file(Path(plan_path))
    name = plan.plan if plan_name is None else plan_name
    if plan.plan != name:
        raise SparseIngestError(
            f"the plan at {plan_path} is {plan.plan!r}, this ingest describes {name!r}"
        )
    run = read_run_record(root, plan_name=name)
    if str(run.get("plan") or "") != plan.plan:
        raise SparseIngestError(
            f"the pass record is for plan {run.get('plan')!r}, the plan file is "
            f"{plan.plan!r}"
        )
    if str(run.get("plan_fingerprint") or "") != plan.plan_fingerprint:
        raise SparseIngestError(
            f"the pass record answers plan fingerprint "
            f"{str(run.get('plan_fingerprint'))[:12]}..., the plan hashes to "
            f"{plan.plan_fingerprint[:12]}...: the record and the plan must be the "
            "same design"
        )
    records = read_job_records(root, plan, run)
    bindings = bind_recordings(root, records)

    decoded: list[DecodedPoint] = []
    failed: list[str] = []
    rows: list[dict[str, str]] = []
    for binding in bindings:
        result = decode_point(root / binding.relative_path, binding)
        if isinstance(result, str):
            failed.append(binding.relative_path)
            rows.append(
                failed_row(binding, result, plan.plan_fingerprint, plan_name=name)
            )
            continue
        require_reader_agrees_with_the_log(result)
        require_declared_settings(result)
        require_retired_target(result, plan_name=name)
        decoded.append(result)

    # The two shared views are read off the decoded set, never declared: the window is
    # the designed exposure, refused rather than narrowed if a recording is short, and
    # support is the intersection of their decoded depth ranges.
    spans = [float(point.time_s[-1] - point.time_s[0]) for point in decoded]
    window_s = common_window_s(spans)
    revolutions = round(window_s / REVOLUTION_S)
    support = common_support(
        [(float(point.depths[0]), float(np.max(point.depths))) for point in decoded]
    )
    for point in decoded:
        rows.append(
            build_row(
                point,
                support=support,
                revolutions=revolutions,
                window_s=window_s,
                window_profiles=int(
                    window(point.values, point.time_s, window_s).shape[0]
                ),
                plan_fingerprint=plan.plan_fingerprint,
                plan_name=name,
            )
        )
    rows.sort(key=lambda row: (int(row["order"]), row["relative_path"]))

    job_counts: dict[str, int] = {}
    for row in rows:
        job_counts[row["job"]] = job_counts.get(row["job"], 0) + 1
    nan_cells = sum(int(row["nan_count"] or 0) for row in rows)
    non_monotone = tuple(
        row["relative_path"]
        for row in rows
        if not row["decode_error"] and row["timestamps_monotone"] != "true"
    )
    not_live = tuple(
        row["relative_path"]
        for row in rows
        if not row["decode_error"]
        and float(row["non_zero_fraction"] or 0.0) < MIN_NON_ZERO_FRACTION
    )
    short = tuple(
        row["relative_path"]
        for row in rows
        if not row["decode_error"] and row["retains_designed_window"] != "true"
    )
    residuals = [
        abs(float(row["period_residual_s"])) for row in rows if not row["decode_error"]
    ]
    worst_residual = float(max(residuals)) if residuals else math.nan
    commit = analysis_commit if analysis_commit is not None else current_revision()
    checks = {
        "recordings": len(rows) == EXPECTED_RECORDINGS,
        "job_counts": dict(sorted(job_counts.items()))
        == dict(sorted(EXPECTED_JOB_COUNTS.items())),
        "decode_failures": not failed,
        "nan_cells": nan_cells == 0,
        "timestamps_monotone": not non_monotone,
        "signal_content": not not_live,
        "retention": not short,
        "common_window": min(spans) + TOLERANCE_S >= DESIGNED_WINDOW_S,
        "common_support": support[1] > support[0],
        "achieved_period_within_the_planners_law": worst_residual
        <= PERIOD_MODEL_TOLERANCE_S,
        "retired_target_recorded": bool(residuals)
        and all(row["log_target_s"] for row in rows if not row["decode_error"]),
        "analysis_commit": bool(commit),
    }
    text = points_csv_text(rows)
    return SparseIngest(
        dataset_root=root.as_posix(),
        plan=plan.plan,
        plan_path=Path(plan_path).as_posix(),
        plan_fingerprint=plan.plan_fingerprint,
        analysis_commit=commit,
        points_name=POINTS_NAME,
        points_rows=len(rows),
        points_sha256=f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
        recordings=len(rows),
        expected_recordings=EXPECTED_RECORDINGS,
        job_counts=dict(sorted(job_counts.items())),
        expected_job_counts=dict(sorted(EXPECTED_JOB_COUNTS.items())),
        decode_failures=len(failed),
        decode_failure_files=tuple(failed),
        nan_cells=nan_cells,
        non_monotone_files=non_monotone,
        not_live_files=not_live,
        short_retention_files=short,
        max_abs_period_residual_s=worst_residual,
        support_mm=(float(support[0]), float(support[1])),
        window_revolutions=revolutions,
        window_s=window_s,
        checks=checks,
        ok=all(checks.values()),
        rows=tuple(rows),
    )


def write_sparse_ingest(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    plan_name: str | None = None,
    analysis_commit: str | None = None,
) -> SparseIngest:
    """Build the ingest and write ``points.csv`` + ``qc-summary.json``.

    Both files are written as UTF-8 with LF endings and one trailing newline, so two
    runs on the same inputs and commit produce identical bytes. Nothing is written
    when the build refuses: a failed binding leaves no half-artefact behind.

    ``plan_name`` names the pass record inside ``dataset_root`` and defaults to the
    plan's own name, so the first pass's call is unchanged and a second pass writes its
    own artifacts by naming its own root, plan and report directory.
    """
    ingest = build_sparse_ingest(
        dataset_root,
        plan_path=plan_path,
        plan_name=plan_name,
        analysis_commit=analysis_commit,
    )
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / POINTS_NAME).write_text(
        points_csv_text(ingest.rows), encoding="utf-8", newline=""
    )
    document = json.dumps(qc_document(ingest), indent=2) + "\n"
    (directory / QC_NAME).write_text(document, encoding="utf-8", newline="")
    return ingest
