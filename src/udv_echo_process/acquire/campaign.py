"""The campaign layer: an explicit list of parameter permutations, run as one job.

A depth sweep asks one question — how does the window move as the resolution changes —
and :class:`~udv_echo_process.acquire.plan.SweepDefinition` expresses it as a ladder to
expand. The near-term goal this module exists for is wider, in the operator's own words:
*"a single channel parametric sweep. Same duration recording (10-15 s), but a slot of
parameter permutations. There should be a system designed for preparing parameter list
and job tracking."* So a campaign is a **file**: one channel, one window length, and an
explicit list of labelled points. It is planned and validated before the first recording
is spent, run through the runner's proven per-point cycle, tracked point by point in the
JSONL log, and summarised in a manifest beside it so an interrupted job can be resumed
instead of re-run.

What the instrument constrains, and why this module is shaped the way it is:

- **a point's write is two fields.** ``acquire.actuator.ordered_writes`` writes the
  resolution and then the gate count, and nothing else: ``sound_speed``,
  ``first_gate_depth``, ``burst_length``, ``sampling_volume`` and ``tgc`` are dialog-only
  (``actuator.DIALOG_ONLY_PARAMETERS``) and are read *once* from the application. A
  permutation that changes one of those is not a permutation a point can make, so
  :func:`plan_campaign` refuses it by name instead of planning a file whose stored words
  would contradict its own request. (This is why the campaign carries ``prf_us``,
  ``emissions_per_profile`` and ``burst_length`` as shared values and points may not
  disagree with them, and why the whole list must share one sound speed and first gate.)
- **every silent clamp is checked out loud.** The application snaps a pitch to the
  nearest rung (``(word10 + 1) × c / 12000``, docs/08 §1), clamps the gate count into
  4..1000 (docs/08 §2), and trims a window the depth budget ``P_max = c × T_prf / 2``
  cannot reach (docs/08 §3) — all without saying so. The plan applies the same laws the
  sweep plan applies, in :func:`plan_sweep`'s own words, because the alternative is
  finding out as a trimmed file after a recording has been spent.
  ``plan.assert_window_fits`` covers the block cap: past it the block is a ring and the
  stored file silently covers only its last ``cap × period`` seconds while still decoding
  as valid (docs/16 §15b).
- **the log is the campaign's memory.** One entry per point (``acquire.log``), and a
  point's identity for a resume is derived from what that record *already* holds: its
  ``name`` — ``<prefix>-<label>-<stamp>`` — minus the run's stamp (``sweep_id``). No new
  field is added to the log record, and a point that was recorded successfully is never
  recorded twice.
- **the log does not hold the intent.** It has no window length and no job name, so the
  manifest written next to it carries the job, the definition's fingerprint (which
  definition produced this job), the planned count, what a resume skipped, and how each
  point ended.

Nothing here drives an instrument. :func:`load_campaign`, :func:`plan_campaign`,
:func:`recorded_points`, the manifest readers and writers and the CLI's ``plan`` and
``report`` subcommands all work on any host — including one whose application is not
running — and only :func:`run_campaign` needs an
:class:`~udv_echo_process.acquire.actuator.Actuator`, which a fake satisfies completely.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from udv_echo_process.acquire.actuator import Actuator
from udv_echo_process.acquire.config import (
    DEFAULT_CHANNEL,
    DEFAULT_MAX_PROFILES_PER_BLOCK,
    MAX_CHANNEL,
    MIN_CHANNEL,
    AcquisitionLimits,
    ParameterSet,
    RecordSettings,
)
from udv_echo_process.acquire.log import (
    PointStatus,
    SweepPointRecord,
    point_records,
    read_entries,
)
from udv_echo_process.acquire.plan import (
    SweepPoint,
    fits_depth_budget,
    max_usable_depth_mm,
    nearest_rung_index,
    profiles_for_duration,
    resolution_for_rung,
)
from udv_echo_process.acquire.runner import (
    PERIOD_OVERHEAD_S,
    PointOutcome,
    SweepRunner,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DEFAULT_LOG_NAME",
    "HALF_DISPLAY_MM",
    "LABEL_PATTERN",
    "MANIFEST_SUFFIX",
    "MAX_POINT_DURATION_S",
    "MIN_POINT_DURATION_S",
    "RESOLUTION_DISPLAY_MM",
    "CampaignDefinition",
    "CampaignError",
    "CampaignPoint",
    "CampaignRecordSettings",
    "JobManifest",
    "ManifestPoint",
    "PlannedPoint",
    "campaign_fingerprint",
    "load_campaign",
    "manifest_path_for",
    "plan_campaign",
    "point_identity",
    "read_manifest",
    "read_manifest_if_present",
    "record_identity",
    "recorded_points",
    "run_campaign",
    "write_manifest",
]

#: A label (and the campaign's name prefix) is written into the Store dialog's *name
#: field* and becomes a file name on the instrument's disk. That dialog is modal, and a
#: name it refuses leaves the panel up with nothing able to close it (docs/16 §12b), so a
#: label is a file-name token and nothing else: letters, digits, dot, dash, underscore.
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: The sidebar displays a pitch with three decimals (docs/16 §12a), so a request within
#: half a display unit of a ladder rung *is* that rung — which is what makes the plan's
#: pitch check possible without demanding an exact float.
RESOLUTION_DISPLAY_MM = 0.001
HALF_DISPLAY_MM = RESOLUTION_DISPLAY_MM / 2

#: The sane range for a point's window. Intent, not physics: the operator's band for this
#: campaign is 10-15 s (handoff §4), a sub-second point cannot carry a profile series
#: worth comparing, and ten minutes is beyond any block the application was measured to
#: hold — the ring stopped at ~257 profiles, i.e. ~8.4 s at the measured period (handoff
#: §4), so a window that long stores only its tail whatever the cap says.
MIN_POINT_DURATION_S = 0.5
MAX_POINT_DURATION_S = 600.0

#: The log a campaign writes when the caller names none: next to the points it stores.
DEFAULT_LOG_NAME = "campaign.jsonl"

#: A manifest sits beside its log, named from it: ``campaign.jsonl`` ->
#: ``campaign.manifest.json``. Derived, so nothing has to remember a second path and a
#: report can find the manifest from the log it was given.
MANIFEST_SUFFIX = ".manifest.json"


class CampaignError(ValueError):
    """A campaign that cannot be run as written, named field by field.

    One type for the loader, the planner, the manifest reader and the run's own
    refusals, because they all mean the same thing to a caller: this definition is not
    one this layer can run, and the message names the file, the point and what to change
    rather than leaving a pydantic traceback to read. A ``ValueError``, the family the
    rest of :mod:`udv_echo_process.acquire` raises for a plan the application would not
    honour.
    """


class CampaignPoint(ValueModel):
    """A point's identity and request, as the campaign file declares it.

    ``label`` **is** the identity: it names the stored file (``<prefix>-<label>-<stamp>``,
    see :class:`CampaignRecordSettings`) and it is what a resumed run keys on, so a point
    keeps its label for the life of the job. A name built from a position in a list — as
    ``RecordSettings.point_name`` does for a sweep's rungs — would rename itself the
    moment a point is inserted, which is exactly what a job that has to survive being
    interrupted cannot afford.

    ``parameters`` is the *request*: the ladder pitch and the gate count the application
    is asked for, plus the window frame (sound speed, first gate) the stored file is
    verified against. The dialog-only fields among them are shared by the whole campaign
    — :func:`plan_campaign` refuses a point that disagrees with the list on one, because
    a point's write cannot change them (``actuator.DIALOG_ONLY_PARAMETERS``).

    ``duration_s`` overrides the campaign's window for this point alone; ``None`` takes
    the campaign's. One duration for the whole slot is what makes the comparison
    like-for-like (docs/dop3000/parameter-sweep-matrix.md §5), and the override exists for
    the point that is deliberately different.
    """

    label: str = Field(min_length=1)
    parameters: ParameterSet
    duration_s: float | None = Field(default=None, gt=0)

    @field_validator("label")
    @classmethod
    def _check_label(cls, value: str) -> str:
        if not LABEL_PATTERN.match(value):
            raise ValueError(
                f"{value!r} cannot name a stored point: a label is letters, digits, dots, "
                "dashes and underscores, and starts with a letter or a digit — it is typed "
                "into the Store dialog's name field, and a name that dialog refuses leaves "
                "it open (docs/16 §12b)"
            )
        return value


class CampaignDefinition(ValueModel):
    """What a campaign is: one channel, one window length, one explicit list of points.

    The shared fields are the ones a *point cannot write* (``actuator``'s
    :data:`~udv_echo_process.acquire.actuator.DIALOG_ONLY_PARAMETERS`): the PRF period,
    the emissions per profile and the burst length are read once from the application for
    the channel, and every point of the run records with them.

    ``prf_us`` and ``emissions_per_profile`` are required, not optional like their
    counterparts on :class:`~udv_echo_process.acquire.config.SweepDefinition`, and the
    reason is a spent recording: the runner derives the stored file's expected size from
    ``emissions × PRF + ~1 ms`` (docs/16 §15), so a point whose parameters carry neither
    is *stored and then refused* by the size guard — "no expected size can be derived".
    A plan that cannot supply them is refused here instead, before anything is recorded.
    ``burst_length`` is informational (the file's word 8 is read back and logged), and
    ``limits`` is the measured ladder and gate range, overridable for an installation
    whose optional packages are not installed.
    """

    job: str = Field(min_length=1)
    channel: int = Field(default=DEFAULT_CHANNEL, ge=MIN_CHANNEL, le=MAX_CHANNEL)
    #: The campaign's window, in seconds — what makes a slot of points comparable.
    duration_s: float = Field(gt=0)
    points: tuple[CampaignPoint, ...]
    #: First half of every stored name: ``<prefix>-<label>-<stamp>``.
    name_prefix: str = Field(min_length=1)
    #: The PRF *period* in µs as the application reports it (word 5) — the depth budget
    #: ``P_max = c × T_prf / 2`` and the profile period both need it (docs/08 §3).
    prf_us: float = Field(gt=0)
    #: Emissions per profile, word 14 — the transfer term of the period law exists for it.
    emissions_per_profile: int = Field(ge=1)
    burst_length: int | None = Field(default=None, ge=1)
    #: Where the points land. Optional here so a caller can keep it out of the file (the
    #: live commands take it from ``--store-dir`` or ``UDV_STORE_DIR``); never guessed,
    #: because the cycle *writes* the Store dialog's directory when it differs.
    store_dir: str | None = Field(default=None, min_length=1)
    #: Mirrors the application's ``Do not keep in a block more profiles than`` setting.
    #: State it explicitly and check it against the instrument: the accepted value was
    #: never established (the tested install took 1000000) and the block was measured to
    #: stop at ~257 profiles, so a window longer than the cap stores only its last
    #: ``cap × period`` seconds while still decoding as valid (docs/16 §15b, handoff §4).
    max_profiles_per_block: int = Field(
        default=DEFAULT_MAX_PROFILES_PER_BLOCK, ge=1
    )
    limits: AcquisitionLimits = Field(default_factory=AcquisitionLimits)

    @field_validator("job")
    @classmethod
    def _check_job(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(f"must not carry surrounding whitespace, got {value!r}")
        return value

    @field_validator("name_prefix")
    @classmethod
    def _check_name_prefix(cls, value: str) -> str:
        if not LABEL_PATTERN.match(value):
            raise ValueError(
                f"{value!r} cannot prefix a stored point's name: the whole stored name has "
                "to be one the Store dialog accepts, and a name that dialog refuses leaves "
                "it open (docs/16 §12b)"
            )
        return value

    @field_validator("points")
    @classmethod
    def _check_points(cls, value: tuple[CampaignPoint, ...]) -> tuple[CampaignPoint, ...]:
        if not value:
            raise ValueError(
                "points must not be empty: a campaign is at least one parameter permutation"
            )
        return value


class PlannedPoint(ValueModel):
    """One point as it will run: its key, its label, its request and its derived window.

    ``key`` is the point's 1-based *position* in the campaign — the ``key`` the log
    records and the index the runner's naming settings resolve a label with. It is a
    position, not the identity: ``identity`` is the label-based id a resume keys on, and
    inserting a point renumbers the keys without re-running anything.

    ``profiles`` is derived, and deliberately by the *same* law the runner sizes the
    stored file with (``runner.PERIOD_OVERHEAD_S`` for the transfer term), so the plan and
    the size guard cannot disagree about what a point is.
    """

    key: int = Field(ge=1)
    label: str
    identity: str
    parameters: ParameterSet
    duration_s: float = Field(gt=0)
    profiles: int = Field(ge=1)
    #: A consequence of the request, worth stating before the run and never a reason to
    #: refuse it. The one case today is a window longer than the block cap, which stores a
    #: valid file covering only its last ``cap × period`` seconds (docs/16 §15b).
    note: str | None = None

    @property
    def expected_depth_mm(self) -> float:
        """The plan's prediction of the window depth, to 3 decimals.

        ``first_gate + gates × resolution`` — the law verified twice against the app's own
        derived depth (docs/13 §1). The application's stored word 2 is the authority; a
        mismatch means the write was clamped, which the plan checks for up front.
        """
        return round(self.parameters.depth_mm, 3)


class CampaignRecordSettings(RecordSettings):
    """``RecordSettings`` that names a stored file from its campaign point's label.

    ``RecordSettings`` names a point ``<prefix>-k<key>-<stamp>``, because a depth sweep's
    points *are* its rungs. A campaign's points are its labels — ``c1460-k1-a`` is what
    the operator asked for and what a resume is keyed on — so the label takes the place
    of the rung index. The stamp stays last (a re-run must not raise the Store dialog's
    overwrite warning, docs/16 §12b) and the prefix stays first, so a directory holding
    more than one campaign's points still sorts by campaign.

    ``labels`` are the campaign's labels in run order; a key outside them is refused
    rather than named by position, because a name that silently stops matching its
    identity is a point a resumed run would record twice.
    """

    labels: tuple[str, ...] = ()

    def point_name(self, key: int, stamp: str) -> str:
        """``<prefix>-<label>-<stamp>`` for the point at 1-based position ``key``."""
        if not stamp:
            raise ValueError("stamp must not be empty")
        if not 1 <= key <= len(self.labels):
            raise ValueError(
                f"no label for key {key}: these settings carry {len(self.labels)} label(s), "
                "and a campaign's keys are its points' 1-based positions in the definition"
            )
        return f"{self.name_prefix}-{self.labels[key - 1]}-{stamp}"


class ManifestPoint(ValueModel):
    """One point's outcome, as a manifest summarises it.

    ``ok`` is the runner's own verdict (a file was stored, decoded, matched the size
    signature **and** verified against the request); ``status`` says how it ended;
    ``aborted`` says the point ended the run rather than merely failing
    (:class:`~udv_echo_process.acquire.runner.PointOutcome`). A point that is not ok may
    still carry a ``file`` — an invalid file is evidence and is kept.

    ``key`` is 0 only for an outcome the runner produced without a point; the runner does
    not do that, but a manifest keeps one row per outcome either way.
    """

    key: int = Field(ge=0)
    label: str
    identity: str
    status: PointStatus
    ok: bool
    file: str | None = None
    reason: str | None = None
    aborted: bool = False


class JobManifest(ValueModel):
    """What a campaign run was: which definition, when it ran, and how each point ended.

    Written next to the job log. The ``fingerprint`` is what ties the two together: the
    log says what happened, the definition says what was asked for, and only the manifest
    says that this log answered *this* definition. ``skipped`` names the identities a
    resume found already recorded, so a report can say why a job looks shorter than its
    plan, and ``log_errors`` carries anything the runner could not append — a run whose
    log is incomplete must not read as a clean one.
    """

    job: str
    fingerprint: str
    channel: int = Field(ge=MIN_CHANNEL, le=MAX_CHANNEL)
    planned: int = Field(ge=0)
    skipped: tuple[str, ...] = ()
    started_at: datetime
    finished_at: datetime
    outcomes: tuple[ManifestPoint, ...] = ()
    store_dir: str | None = None
    log_path: str | None = None
    definition_path: str | None = None
    log_errors: tuple[str, ...] = ()

    @property
    def points_skipped(self) -> int:
        """How many points a resume found already recorded and did not run again."""
        return len(self.skipped)

    @property
    def ok_count(self) -> int:
        """Points the run recorded and verified."""
        return sum(1 for outcome in self.outcomes if outcome.ok)

    @property
    def failed_count(self) -> int:
        """Outcomes that are not ok — a refused point is a failure worth an exit code."""
        return sum(1 for outcome in self.outcomes if not outcome.ok)

    @property
    def aborted(self) -> bool:
        """True when the run was cut short at a state the runner could not verify."""
        return any(outcome.aborted for outcome in self.outcomes)

    @property
    def summary(self) -> str:
        """One line: what the job did, in the terms an operator checks it by."""
        parts = [f"{self.ok_count}/{self.planned} point(s) ok"]
        if self.failed_count:
            parts.append(f"{self.failed_count} failed")
        if self.skipped:
            parts.append(f"{self.points_skipped} skipped as already recorded")
        if self.aborted:
            parts.append("the run was cut short: the application's state was not verified")
        if self.log_errors:
            parts.append(f"{len(self.log_errors)} log entr(ies) could not be written")
        return "; ".join(parts)


def point_identity(name_prefix: str, label: str) -> str:
    """The identity a resume keys on: ``<prefix>-<label>``, with no run stamp.

    A point's stored file is named ``<prefix>-<label>-<stamp>``
    (:class:`CampaignRecordSettings`), and the stamp is the run's own
    (``log.sweep_id_for``). Stripping it leaves the stable half — the half that says
    *this point of this campaign* rather than *this run of it*.
    """
    return f"{name_prefix}-{label}"


def record_identity(record: SweepPointRecord) -> str:
    """The identity of a logged point, read back from that record's own name and stamp.

    The record already holds both halves — ``name`` is ``<prefix>-<label>-<sweep_id>``
    and ``sweep_id`` is the stamp — so a resume needs **no new field in the log** (which
    matters: the log's shape is read by the analysis too).

    A name that does not end in its record's stamp is returned unchanged, and that is the
    safe direction: the point is then not recognised as already recorded, so a resume
    re-runs it rather than skipping a point whose identity is in doubt. (The runner's
    ``b``-suffix retry for a taken name can produce such a name if a caller reuses a
    sweep id; a fresh stamp per run is what keeps that out of the normal path.)
    """
    return record.name.removesuffix(f"-{record.sweep_id}")


def recorded_points(log_path: Path) -> set[str]:
    """The identities a job log already holds as *successful* — the resume's input.

    Only ``ok`` records count. A point that failed, or whose stored file was invalid, is
    exactly the point a resumed run has to try again — that is the difference between a
    job that was interrupted and a job that was declared bad.

    A log that is not there yet is an empty set: nothing has been recorded. A log that
    cannot be *parsed* raises instead, because a resume that silently skipped nothing
    would re-run a job the operator believes is finished (``log.read_entries`` refuses a
    malformed line on the same principle).
    """
    path = Path(log_path)
    if not path.is_file():
        return set()
    return {
        record_identity(record)
        for record in point_records(read_entries(path))
        if record.status is PointStatus.OK
    }


def campaign_fingerprint(definition: CampaignDefinition) -> str:
    """A stable hash of the definition — which definition produced which job.

    Canonical JSON (keys sorted, no whitespace, ASCII) through SHA-256: the same
    definition hashes the same on every host and every load, and any change to a point, a
    duration, a shared value or the naming prefix changes it. The manifest carries it, so
    a log and the definition it answered cannot drift apart unnoticed.
    """
    canonical = json.dumps(
        definition.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_campaign(path: Path) -> CampaignDefinition:
    """Read a campaign definition from JSON, or refuse it naming the offending field.

    JSON only, and deliberately so: this repository declares no YAML parser
    (``pyproject.toml`` has no YAML dependency), and a list of permutations needs nothing
    a JSON object cannot say. Adding a parser for the file format alone would be a
    dependency bought for cosmetics.

    Every failure is a :class:`CampaignError` naming the file and the field — an unknown
    field (``extra="forbid"``), a missing one, a point whose label cannot be a file name,
    an empty list — never a bare pydantic traceback, because the person who has to fix it
    is reading this message and not the model.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CampaignError(
            f"{source}: the campaign definition could not be read ({exc})"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CampaignError(f"{source}: not valid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise CampaignError(
            f"{source}: a campaign definition is a JSON object, got "
            f"{type(payload).__name__}"
        )
    try:
        return CampaignDefinition.model_validate(payload)
    except ValidationError as exc:
        raise CampaignError(f"{source}: {_explain_validation(exc)}") from exc


def plan_campaign(definition: CampaignDefinition) -> tuple[PlannedPoint, ...]:
    """Validate the whole list and turn it into the points the runner will run.

    Nothing here touches an instrument, and every rule the application would enforce
    *silently* is enforced *loudly* — before the first recording is spent:

    - **the window frame is shared.** Sound speed and first gate are dialog-only
      (``actuator.DIALOG_ONLY_PARAMETERS``): a point writes the pitch and the gate count,
      so all of them must be planned on one frame. A list that disagreed would record
      files contradicting their own requests;
    - **the pitch is on the ladder.** The application snaps a request to the nearest rung
      (docs/08 §1) and the sidebar shows three decimals (docs/16 §12a), so a request
      within half a display unit of a rung is that rung; further off, the stored file
      would carry a window the point did not ask for;
    - **the gate count is one the application accepts** — 4..1000 measured (docs/08 §2);
    - **the window fits the depth budget** ``P_max = c × T_prf / 2`` (docs/08 §3), in
      :func:`~udv_echo_process.acquire.plan.plan_sweep`'s own words;
    - **the window fits the block cap** (:func:`plan.assert_window_fits`): past it the
      block is a ring and the stored file covers only its last ``cap × period`` seconds
      while still decoding as valid (docs/16 §15b);
    - **the window length is in a sane range** and **the labels are unique** — a
      duplicate label would produce two points with one identity, so a resume could not
      tell which of them a file belongs to.

    Raises :class:`CampaignError` naming the point and what to change. The points come
    back in the order the file lists them: that order *is* the run order.
    """
    planned: list[PlannedPoint] = []
    labels: dict[str, int] = {}
    frame: tuple[str, float, float] | None = None

    for key, declared in enumerate(definition.points, start=1):
        label = declared.label
        if label in labels:
            raise CampaignError(
                f"duplicate label {label!r}: it is the point's identity (the stored file is "
                f"named from it and a resume is keyed on it), so point {labels[label]} and "
                f"point {key} cannot both be it — give one of them a label of its own"
            )
        labels[label] = key

        duration = definition.duration_s if declared.duration_s is None else declared.duration_s
        _check_duration(duration, label)
        parameters = _effective_parameters(definition, declared)
        frame = _check_frame(frame, label, parameters, definition)
        _check_pitch(parameters, label, definition.limits)
        _check_gates(parameters, label, definition.limits)
        _check_depth_budget(parameters, definition.prf_us, label)
        period_s = _profile_period_s(parameters)
        profiles = profiles_for_duration(duration, period_s)
        # A window longer than the block cap is *stated*, not refused, and this is where the
        # campaign parts company with the sweep (`plan.assert_window_fits` raises). What
        # differs is what the request means: a sweep's point claims a window it size-checks
        # against, while the near-term goal here is explicitly a 10-15 s recording — a
        # request the instrument honours, its block keeping only the last ``cap x period``
        # seconds of it (measured: a 12 s request stored ~257 profiles, docs/16 §15b,
        # handoff §4). Refusing would make that goal unrunnable; saying nothing would let
        # the plan pretend the stored file covers the whole window.
        note = None
        if profiles > definition.max_profiles_per_block:
            cap = definition.max_profiles_per_block
            note = (
                f"{profiles} profiles at {period_s:.6f} s/profile is above the block cap of "
                f"{cap}: the block wraps and the stored file covers only its last "
                f"{cap * period_s:.3f} s — raise the cap only if the application's own "
                '"Do not keep in a block more profiles than" setting is raised to match'
            )
        planned.append(
            PlannedPoint(
                key=key,
                label=label,
                identity=point_identity(definition.name_prefix, label),
                parameters=parameters,
                duration_s=duration,
                profiles=profiles,
                note=note,
            )
        )
    return tuple(planned)


def manifest_path_for(log_path: Path) -> Path:
    """Where a job's manifest lives: beside its log, named from it."""
    return Path(log_path).with_suffix(MANIFEST_SUFFIX)


def write_manifest(path: Path, manifest: JobManifest) -> None:
    """Write a manifest as JSON, creating the directory it lands in."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> JobManifest:
    """Read a manifest back; a malformed one is a :class:`CampaignError` naming the file."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CampaignError(f"{source}: the manifest could not be read ({exc})") from exc
    try:
        return JobManifest.model_validate_json(text)
    except ValidationError as exc:
        raise CampaignError(f"{source}: not a job manifest: {_explain_validation(exc)}") from exc


def read_manifest_if_present(path: Path) -> JobManifest | None:
    """The manifest at ``path``, or ``None`` when there is none.

    A log can outlive its manifest — a run killed before the manifest was written, or a
    log from the runner's own sweep path, which writes no manifest at all. That is not an
    error: a report says what it has, and the log alone is still a complete point-by-point
    record.
    """
    source = Path(path)
    return read_manifest(source) if source.is_file() else None


def run_campaign(
    definition: CampaignDefinition,
    actuator: Actuator,
    *,
    store_dir: Path | str | None = None,
    log_path: Path | str | None = None,
    resume: bool = False,
    channel: int | None = None,
    definition_path: Path | str | None = None,
    notes: list[str] | None = None,
    now: datetime | None = None,
) -> JobManifest:
    """Run the points that still have to run, write the manifest, and say what happened.

    The plan is validated first, and the per-point work is the **runner's**: ``SweepRunner``
    resets the block, applies the window, reads it back, records, stops, stores, decodes the
    stored file, sizes it against the signature and verifies its own words — and appends the
    log entry, valid or not. None of that cycle is re-implemented here; the seam is
    ``SweepRunner.run_points``, which takes an explicit sequence of points where ``run``
    takes a ladder to expand. A campaign's points are explicit and may each carry their own
    window, so they are handed over as a sequence and not as a definition.

    ``resume=True`` drops the points the log already holds as *successful*
    (:func:`recorded_points`) and runs the rest in the file's order, saying in the notes
    how many it skipped. Without it every point runs, and the fresh stamp in each name
    keeps the re-run from overwriting the earlier files — reusing a name raises the Store
    dialog's ``file already exists`` warning, which wedges the application when nothing
    answers it (docs/16 §12b).

    ``store_dir`` overrides the definition's and ``channel`` the definition's — the
    caller's argument wins, and the CLI takes ``--store-dir``/``UDV_STORE_DIR`` for the
    first. The channel is the one knob: a point recorded on the wrong channel decodes as a
    valid point that is not the point (docs/16 §12), so the runner verifies it once before
    the first recording, and the manifest records what it verified.

    Raises :class:`CampaignError` when the definition cannot be planned, when no store
    directory is named, or when the channel is not one the application offers. The runner
    itself never raises for a bad point: a refused point is an outcome, and the manifest
    is written either way.
    """
    planned = plan_campaign(definition)
    directory = _store_directory(definition, store_dir)
    log = Path(log_path) if log_path is not None else directory / DEFAULT_LOG_NAME
    effective_channel = definition.channel if channel is None else int(channel)
    if not MIN_CHANNEL <= effective_channel <= MAX_CHANNEL:
        raise CampaignError(
            f"channel {effective_channel} is outside the channels the application offers "
            f"({MIN_CHANNEL}..{MAX_CHANNEL})"
        )

    done = recorded_points(log) if resume else set()
    todo = tuple(point for point in planned if point.identity not in done)
    skipped = tuple(point.identity for point in planned if point.identity in done)
    if resume and notes is not None:
        notes.append(
            f"resume: {len(skipped)} of {len(planned)} point(s) are already recorded in "
            f"{log.name}; {len(todo)} to run"
        )

    started_at = _local_now(now)
    runner = SweepRunner(
        actuator,
        CampaignRecordSettings(
            capture_dir=str(directory),
            name_prefix=definition.name_prefix,
            labels=tuple(point.label for point in planned),
            max_profiles_per_block=definition.max_profiles_per_block,
        ),
        directory,
        log_path=log,
        channel=effective_channel,
    )
    outcomes = runner.run_points(
        tuple(
            SweepPoint(
                key=point.key,
                parameters=point.parameters,
                duration_s=point.duration_s,
            )
            for point in todo
        )
    )
    by_key = {point.key: point for point in planned}
    manifest = JobManifest(
        job=definition.job,
        fingerprint=campaign_fingerprint(definition),
        channel=runner.channel,
        planned=len(planned),
        skipped=skipped,
        started_at=started_at,
        finished_at=_local_now(None),
        outcomes=tuple(_manifest_point(outcome, by_key) for outcome in outcomes),
        store_dir=str(directory),
        log_path=str(log),
        definition_path=None if definition_path is None else str(definition_path),
        log_errors=tuple(runner.log_errors),
    )
    write_manifest(manifest_path_for(log), manifest)
    return manifest


def _explain_validation(exc: ValidationError) -> str:
    """A pydantic failure as "field: what is wrong", one clause per problem.

    Three cases are worth naming plainly, because they are the ones a person writing the
    file hits: an unknown field (``extra="forbid"``), a missing one, and JSON that does
    not parse. Everything else is reported with the path pydantic recorded, so the
    message points into ``points.2.parameters`` as precisely as the model knows.
    """
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ()))
        kind = str(error.get("type", ""))
        # pydantic prefixes a validator's own message; the field is already named here.
        message = str(error.get("msg", "is not valid")).removeprefix("Value error, ")
        if kind == "extra_forbidden":
            parts.append(f"unknown field {location!r}")
        elif kind == "missing":
            parts.append(f"missing field {location!r}")
        elif kind == "json_invalid":
            parts.append(f"not valid JSON ({message})")
        else:
            parts.append(f"{location or '<the definition>'}: {message}")
    return "this campaign definition is not valid: " + "; ".join(parts)


def _check_duration(duration_s: float, label: str) -> None:
    """Refuse a window outside :data:`MIN_POINT_DURATION_S`..:data:`MAX_POINT_DURATION_S`."""
    if duration_s < MIN_POINT_DURATION_S or duration_s > MAX_POINT_DURATION_S:
        raise CampaignError(
            f"point {label!r} asks for a {duration_s:g} s window, outside the sane range "
            f"{MIN_POINT_DURATION_S:g}..{MAX_POINT_DURATION_S:g} s: this campaign's band is "
            "10-15 s (handoff §4), a sub-second point carries too few profiles to compare, "
            "and the block was measured to stop at ~257 profiles — so a very long window "
            "stores only its tail whatever the cap says (docs/16 §15b)"
        )


def _effective_parameters(
    definition: CampaignDefinition, declared: CampaignPoint
) -> ParameterSet:
    """The point's request with the campaign's shared covariates applied.

    ``prf_us``, ``emissions_per_profile`` and ``burst_length`` are dialog-only: they are
    read once for the channel and every point of the run records with them, so the
    campaign's values are what the point runs with. A point may repeat them, but only at
    the campaign's values — one that disagreed would be planned as a file the run cannot
    produce.
    """
    for field_name, campaign_value in (
        ("prf_us", definition.prf_us),
        ("emissions_per_profile", definition.emissions_per_profile),
        ("burst_length", definition.burst_length),
    ):
        point_value = getattr(declared.parameters, field_name)
        if point_value is not None and point_value != campaign_value:
            raise CampaignError(
                f"point {declared.label!r} names {field_name}={point_value} while the "
                f"campaign names {campaign_value}: {field_name} is dialog-only "
                "(actuator.DIALOG_ONLY_PARAMETERS), read once for the channel, so every "
                "point of a run records with the campaign's value — drop it from the point, "
                "or change it on the campaign"
            )
    return ParameterSet(
        sound_speed_ms=declared.parameters.sound_speed_ms,
        first_gate_mm=declared.parameters.first_gate_mm,
        resolution_mm=declared.parameters.resolution_mm,
        gates=declared.parameters.gates,
        prf_us=definition.prf_us,
        emissions_per_profile=definition.emissions_per_profile,
        burst_length=definition.burst_length,
    )


def _check_frame(
    frame: tuple[str, float, float] | None,
    label: str,
    parameters: ParameterSet,
    definition: CampaignDefinition,
) -> tuple[str, float, float]:
    """Every point on one window frame: the same sound speed and the same first gate.

    Both are dialog-only (``actuator.DIALOG_ONLY_PARAMETERS``) and neither is written by a
    point's cycle, so a list planned on two sound speeds, or two first gates, would record
    every point on the channel's own values and read back files that contradict their
    requests. The refusal names the two points and says which of the three ways out to
    take: one frame per campaign.
    """
    current = (label, parameters.sound_speed_ms, parameters.first_gate_mm)
    if frame is None:
        return current
    first_label, first_sound_speed, first_gate = frame
    if parameters.sound_speed_ms != first_sound_speed:
        raise CampaignError(
            f"point {label!r} asks for sound_speed_ms={parameters.sound_speed_ms:g} while "
            f"point {first_label!r} asks for {first_sound_speed:g}: sound speed is a "
            "dialog-only setting, read once for the channel (actuator."
            "DIALOG_ONLY_PARAMETERS), and a point's write cannot change it — a list "
            "planned on two sound speeds would record every point at the channel's own c, "
            "so split it into one campaign per sound speed"
        )
    if parameters.first_gate_mm != first_gate:
        raise CampaignError(
            f"point {label!r} asks for first_gate_mm={parameters.first_gate_mm:g} while "
            f"point {first_label!r} asks for {first_gate:g}: the first gate is "
            "dialog-only too, and it decides the near end of every window in the campaign "
            "(docs/08's window law) — one first gate per campaign"
        )
    return frame


def _check_pitch(
    parameters: ParameterSet, label: str, limits: AcquisitionLimits
) -> None:
    """Refuse a pitch that is not a ladder rung the application would keep.

    Snapping is *nearest rung* and it is silent (docs/08 §1), and the sidebar displays
    three decimals (docs/16 §12a) — so a request within half a display unit of a rung is
    that rung, and further off the file is written at a pitch the point never asked for.
    The ladder's top rung (``c / 100`` mm) comes out of the same check: a request above it
    clamps to the top, which is more than half a display unit away.
    """
    index = nearest_rung_index(
        parameters.resolution_mm, parameters.sound_speed_ms, limits=limits
    )
    rung = resolution_for_rung(index, parameters.sound_speed_ms, limits=limits)
    if abs(parameters.resolution_mm - rung) > HALF_DISPLAY_MM:
        raise CampaignError(
            f"point {label!r} asks for a {parameters.resolution_mm:g} mm pitch, which is "
            f"not a ladder rung: at c = {parameters.sound_speed_ms:g} m/s the nearest rung "
            f"is {rung:.3f} mm (word 10 = {index}, resolution = (word10 + 1) × c / 12000, "
            "docs/08 §1) and the application snaps a request to it without saying so — "
            "write the rung's own value, or the stored file carries a window this point "
            "did not ask for"
        )


def _check_gates(
    parameters: ParameterSet, label: str, limits: AcquisitionLimits
) -> None:
    """Refuse a gate count outside the range the application accepts (4..1000, docs/08 §2)."""
    if not limits.min_gates <= parameters.gates <= limits.max_gates:
        raise CampaignError(
            f"point {label!r} asks for {parameters.gates} gates, outside the accepted "
            f"{limits.min_gates}..{limits.max_gates} (measured, docs/08 §2): the "
            "application clamps the count silently, so the point would not be the one "
            "planned"
        )


def _check_depth_budget(
    parameters: ParameterSet, prf_us: float, label: str
) -> None:
    """Refuse a window the unambiguous reach cannot hold, naming the point.

    The same check, and the same wording, as
    :func:`~udv_echo_process.acquire.plan.plan_sweep`: ``P_max = c × T_prf / 2`` (docs/08
    §3), beyond which the application reduces the gate count without saying so. The file
    would still be a valid point, just not the planned one.
    """
    if fits_depth_budget(parameters):
        return
    p_max = max_usable_depth_mm(parameters.sound_speed_ms, prf_us)
    raise CampaignError(
        f"point {label!r} wants {parameters.depth_mm:.3f} mm but the depth budget at PRF "
        f"{prf_us} us is {p_max:.3f} mm: the app would silently reduce the gate count "
        "(lower the target depth, raise the PRF period, or raise the first gate)"
    )


def _profile_period_s(parameters: ParameterSet) -> float:
    """The profile period a point's own covariates imply — the runner's own law.

    ``T_profile ≈ T_prf × (16 + N_PRF)`` from the manual, used here as its measured
    equivalent ``emissions × PRF + ~1 ms`` (docs/16 §15) with the runner's own constant,
    so the profile count in the plan is the profile count the size guard derives.
    """
    emissions = parameters.emissions_per_profile or 0
    period = parameters.prf_us or 0.0
    return emissions * period * 1e-6 + PERIOD_OVERHEAD_S


def _store_directory(
    definition: CampaignDefinition, override: Path | str | None
) -> Path:
    """Where the points land: the caller's directory, else the definition's, else refused.

    Never a guess. The cycle *asserts* the Store dialog's working directory against this
    and writes it when they differ, so a default would point the instrument's store
    somewhere nobody chose — the same rule the live commands follow for ``--store-dir``.
    """
    if override is not None:
        return Path(override)
    if definition.store_dir:
        return Path(definition.store_dir)
    raise CampaignError(
        "no store directory: name one with --store-dir (or UDV_STORE_DIR), or put "
        "store_dir in the campaign definition — a guessed path would point the "
        "application's store where nobody asked for it"
    )


def _manifest_point(
    outcome: PointOutcome, planned: Mapping[int, PlannedPoint]
) -> ManifestPoint:
    """One runner outcome as a manifest row, keyed back to the point that produced it.

    The outcome carries the ``SweepPoint`` (its key and its request) but not the campaign's
    label — a label is the naming settings' business, as it is for the stored file name —
    so the row is completed from the plan by key. One row per outcome, always: a manifest
    that dropped an outcome it could not name would hide a point.
    """
    key = 0 if outcome.point is None else outcome.point.key
    point = planned.get(key)
    return ManifestPoint(
        key=key,
        label="" if point is None else point.label,
        identity="" if point is None else point.identity,
        status=outcome.status,
        ok=outcome.ok,
        file=None if outcome.file is None else str(outcome.file),
        reason=outcome.reason,
        aborted=outcome.aborted,
    )


def _local_now(moment: datetime | None) -> datetime:
    """Now in local time; a supplied moment wins, so a manifest is reproducible in tests.

    Local time on purpose: a stamp in a name and a run's start in a manifest are read by
    an operator against a wall clock, and ``log.sweep_id_for`` is local for the same
    reason.
    """
    return datetime.now(tz=UTC).astimezone() if moment is None else moment
