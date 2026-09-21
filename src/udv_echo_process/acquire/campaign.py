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
running — and only :func:`run_campaign` needs the runner's *composed* port
(:class:`~udv_echo_process.acquire.runner.SweepActuator`: the routing step, the instrument
reading, the dialog read and the record/store cycle), which a fake satisfies completely.

**What a run does, in order** (the plan's §4 step order, implemented literally): load the
definition, plan it statically, establish the target channel (``ensure_channel`` — routing,
not a scientific setting: it writes only if the channel differs), take the instrument
reading, compile the definition against that reading (a
:class:`~udv_echo_process.acquire.snapshot.CompilationIdentity` and a refusal list), validate
the resume identity against the previous manifest, compute the todo/skipped sets, then run the
*compiled* points through the runner's proven per-point cycle. The order is the safety
argument: steps 3-5 all happen before the runner exists, so a job that cannot be compiled
costs no recording, and step 6 happens before any point can leave the todo set, so a resume
cannot skip a point on an identity nothing proved.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from udv_echo_process.acquire.actuator import ChannelMode, ProcessMode
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
    profile_period_s,
    profiles_for_duration,
    resolution_for_rung,
)
from udv_echo_process.acquire.runner import (
    PointOutcome,
    SweepActuator,
    SweepRunner,
)
from udv_echo_process.acquire.snapshot import (
    FIXED_FACT_FIELDS,
    SUPPORTED_READ_FACTS,
    CompilationIdentity,
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
    Provenance,
    identity_digest,
)
from udv_echo_process.acquire.verify import (
    ADVISORY_COVARIATES,
    PRF_TOLERANCE_US,
    STRICTABLE_COVARIATES,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "COVARIATE_ACCEPTANCE",
    "DEFAULT_LOG_NAME",
    "HALF_DISPLAY_MM",
    "LABEL_PATTERN",
    "MANIFEST_SUFFIX",
    "MAX_POINT_DURATION_S",
    "MIN_POINT_DURATION_S",
    "RESOLUTION_DISPLAY_MM",
    "STRICTABLE_FACTS",
    "Acceptance",
    "CampaignDefinition",
    "CampaignError",
    "CampaignPoint",
    "CampaignRecordSettings",
    "ExecutableCampaign",
    "FactCheck",
    "JobManifest",
    "ManifestPoint",
    "PlannedPoint",
    "campaign_fingerprint",
    "compile_campaign",
    "declared_fixed_fact",
    "load_campaign",
    "manifest_path_for",
    "plan_campaign",
    "point_identity",
    "read_manifest",
    "read_manifest_if_present",
    "record_identity",
    "recorded_points",
    "refuse_process_mode",
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
#: worth comparing, and ten minutes is deliberately beyond the campaign's operating band.
#: The earlier claim that the application retained only ~8.4 s was disproved by the completed
#: sparse pass (12.4651-12.5713 s retained for a 12 s request; sparse-run-plan §5).
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
    stored file with (:func:`~udv_echo_process.acquire.plan.profile_period_s`, the manual's
    ``T_tran + T_prf · (16 + N_PRF)``), so the plan and the size guard cannot disagree
    about what a point is.
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

    The fields below ``log_errors`` are the run path's own record, and every one of them has a
    default: a manifest written before this slice carries none of them, and a manifest that a
    reader refuses is a job whose log can no longer be read at all, so nothing here is required.
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
    #: The reading this job was compiled against, projected onto what campaign compatibility
    #: depends on (:class:`~udv_echo_process.acquire.snapshot.CompilationIdentity`: each fixed
    #: fact as value+source, the channel, the mode, the layout signature) — the resume's
    #: comparison, and the only thing that says the previous job measured on *this*
    #: instrument.
    #:
    #: **Deliberately the projection and not the raw ``InstrumentSnapshot``.** The reading's
    #: volatile half — ``hwnd``, the rect, the cursor, ``is_foreground``, the geometry — is a
    #: property of a *session*: a restart hands out a new handle and a drag moves the window,
    #: so storing it as compatibility evidence would read a restart as a different instrument
    #: and re-run finished points. §3.3 exists to keep that half out of the identity, and a
    #: manifest that kept the whole reading would undo it in the one place a resume reads.
    #: ``None`` for a ``declared_only`` run (nothing was read) and for every manifest written
    #: before this slice — both of which a resume refuses on rather than assumes.
    compilation_identity: CompilationIdentity | None = None
    #: Set by a ``--no-snapshot`` run: the run record then states that **nothing** was read
    #: and nothing was compiled, so its points rest on the definition's declaration alone.
    declared_only: bool = False
    #: The point identities a resume skipped on the strength of a declaration rather than of a
    #: proven identity (``--resume-declaration-only``). Named on the record so a job that looks
    #: finished and a job that was *declared* finished are two different rows to a later reader.
    skipped_without_evidence: tuple[str, ...] = ()
    #: The process this run was **declared** to have been measured against (``--expect-mode``),
    #: and the one the instrument's own caption **stated** — persisted, both halves (plan §24.5,
    #: D3), so the execution contract outlives the shell history that produced it and a past job
    #: is reconstructable offline by someone with no instrument in front of them. ``None`` for
    #: ``observed_process_mode`` means nothing stated it (no reading was taken at all —
    #: ``declared_only`` — or the caption named no process this driver knows); ``None`` for
    #: ``expected_process_mode`` means the manifest predates this field.
    expected_process_mode: ProcessMode | None = None
    observed_process_mode: ProcessMode | None = None

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
        if self.skipped_without_evidence:
            parts.append(
                f"{len(self.skipped_without_evidence)} of those skipped without instrument "
                "evidence"
            )
        if self.declared_only:
            parts.append(
                "declared only: no instrument reading was taken and nothing was compiled"
            )
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


class Acceptance(str, Enum):
    """What a disagreement about one fixed fact does to a run — decided here, per fact.

    Each outcome is a **field of the compiled plan** rather than a rule hidden inside a
    comparison, because the operator has to be able to read, before the first recording, what
    would have stopped the job and what would not.

    ``REFUSE``
        The disagreement stops the campaign before anything is recorded. The default, because a
        definition that contradicts what the instrument states is a thrown-away job: every point
        would be stored under parameters its own file does not carry.
    ``WARN``
        The disagreement is carried onto the compiled plan and the run proceeds. Exactly one fact
        is here today — the emissions per profile, whose value *in a definition* is derived rather
        than read (:data:`~udv_echo_process.acquire.verify.ADVISORY_COVARIATES`), so a
        disagreement is as likely to be the declaration's fault as the instrument's, and W6 is
        where that ends.
    ``ACCEPT``
        Nothing was compared against this fact, so there is nothing for it to stop: the
        definition declares no value for it, or the instrument could not state one. The
        declaration stands, and the record is marked as such.
    """

    REFUSE = "refuse"
    WARN = "warn"
    ACCEPT = "accept"


#: The acceptance each fixed fact gets, **derived from the stored-file verifier's own table**
#: rather than restated: the covariates that verifier enforces refuse here too, and the one it only
#: advises on warns. Two tables of "which of these matters" would drift apart; one cannot.
#:
#: The two facts the verifier checks by *another* law are refused for reasons of their own, and the
#: reasons are the part a reader acts on:
#:
#: - **the first gate** moves the *spatial* window — ``first_gate + gates x resolution`` is the law
#:   this repository verified twice against the application's own arithmetic (docs/16 §12) — so a
#:   run compiled against one first gate and executed under another samples a different physical
#:   region than the definition asked for, whatever the stored file's own words happen to say;
#: - **the block cap** decides the *retention* semantics: how much of the requested temporal window
#:   can be kept, whether the block wraps, and therefore what ``retained_fraction`` — and any wrap
#:   inference drawn from it — means. A campaign compiled under one active cap and executed under
#:   another was compiled for different retention, so a **known** disagreement refuses.
#:
#: Neither reason is "the planner refuses those windows", and this is worth stating precisely
#: because the planner does the opposite: `plan_campaign` deliberately does **not** refuse a window
#: that breaches the declared cap. It plans it and attaches a note saying the block wraps and covers
#: only its last ``cap x period`` seconds, because the near-term goal here is a 10-15 s recording the
#: instrument honours (``tests/test_acquire_campaign.py`` pins that note). The refusal here is about
#: the *instrument* disagreeing with the definition, which is a different question from whether the
#: plan is runnable — and today it cannot fire, because the active cap is not readable (W1
#: reconnaissance, plan §14): the fact is carried unproven rather than compared.
COVARIATE_ACCEPTANCE: Mapping[str, Acceptance] = {
    name: (Acceptance.WARN if name in ADVISORY_COVARIATES else Acceptance.REFUSE)
    for name in FIXED_FACT_FIELDS
}

#: The fixed facts a run may **raise to refusal** — the ones a stored file carries a word for, so
#: the same requirement can be enforced before *and* after storage (``verify.STRICTABLE_COVARIATES``).
#: ``max_profiles_per_block`` is deliberately not here: no word in a stored file states the active
#: cap, so a fact that could be checked before a recording but never afterwards would be a policy
#: half-enforced, and a caller naming it is refused rather than quietly accommodated.
STRICTABLE_FACTS: tuple[str, ...] = STRICTABLE_COVARIATES


def _check_strict_facts(
    strict_facts: tuple[str, ...], *, where: str
) -> tuple[str, ...]:
    """Validate a run's raised facts, and return them in the vocabulary's own order.

    A raised fact must be one a stored file carries a word for (:data:`STRICTABLE_FACTS`), so the
    requirement can be enforced before *and* after a recording: a raise that only the compile could
    see would make a job refusable at the screen and acceptable in the dataset, which is the worse of
    the two halves to have. An unknown name is refused with the vocabulary, never ignored.
    """
    unknown = [name for name in strict_facts if name not in STRICTABLE_FACTS]
    if unknown:
        raise CampaignError(
            f"{where} raises {unknown}, which no stored file carries a word for: a fact that could "
            "be refused before a recording but not checked afterwards would leave the dataset "
            f"weaker than the policy claims. The raiseable facts are {list(STRICTABLE_FACTS)}"
        )
    return tuple(name for name in STRICTABLE_FACTS if name in strict_facts)


class FactCheck(ValueModel):
    """One fixed fact: what the definition declares, what the instrument was found to state, and
    what a disagreement would do to the run.

    ``agreed`` is deliberately **three**-valued. ``True`` and ``False`` mean the fact was read
    from the instrument and compared against the declaration; ``None`` means nothing was compared
    — either the definition declares no value for it (``burst_length`` is optional) or the
    instrument could not state one. A caller that read ``None`` as ``False`` would refuse a run
    over a fact nobody disputed; one that read it as ``True`` would call an unread fact verified,
    which is the claim this whole slice exists to prevent.
    """

    name: str
    #: The definition's own value **as text**, for a message that has to show both sides side by
    #: side — never a parsed measurement. ``None`` when the definition declares nothing.
    declared: str | None = None
    #: The reading: the instrument's own text and where it came from, or why it has no value.
    observed: InstrumentFact
    #: What a disagreement *would* have done (:data:`COVARIATE_ACCEPTANCE`), not what happened —
    #: what happened is ``agreed``, and a fact nothing could read has a policy and no dispute.
    acceptance: Acceptance
    agreed: bool | None = None
    #: The sentence a refusal carries and a warning is recorded as: empty when everything agreed,
    #: never empty when something did not.
    detail: str | None = None


class ExecutableCampaign(ValueModel):
    """A campaign reconciled with one reading of the instrument — what the run executes.

    Everything needed to audit the job afterwards *without the instrument* is here: the points as
    the static planner computed them (so a point cannot be recorded under parameters the plan did
    not predict), the channel the routing step established and this compile accepted, the fact
    table with each fact's provenance and acceptance, and the reading's
    :class:`~udv_echo_process.acquire.snapshot.CompilationIdentity` — which is also the answer to
    "which channel and which mode were active", and the resume's comparison.

    ``definition_fingerprint`` and the identity are carried together because they are the two
    things this plan was compiled *from*: a compiled plan found later cannot be mistaken for one
    compiled against a different definition of against a different reading.
    """

    job: str
    #: The channel the routing step established in the application and read back.
    channel: int = Field(ge=MIN_CHANNEL, le=MAX_CHANNEL)
    definition_fingerprint: str
    identity: CompilationIdentity
    facts: tuple[FactCheck, ...]
    points: tuple[PlannedPoint, ...]
    #: The facts this compilation **raised to refusal** over the table's own acceptance — what a
    #: plan supplies when one of them is the experiment. Empty for every ordinary campaign, and the
    #: empty default is what keeps a compiled plan written before this field readable.
    strict_facts: tuple[str, ...] = ()

    @property
    def identity_digest(self) -> str:
        """The resume's comparison, as one string — computed, never stored twice."""
        return identity_digest(self.identity)

    @property
    def advisories(self) -> tuple[str, ...]:
        """The disagreements the run proceeds despite — recorded rather than swallowed."""
        return tuple(
            check.detail
            for check in self.facts
            if check.acceptance is Acceptance.WARN
            and check.agreed is False
            and check.detail is not None
        )

    @property
    def unproven(self) -> tuple[str, ...]:
        """The fixed facts nothing on the instrument could state, so the declaration stands.

        Named here, on the plan, because "the instrument holds this" and "the campaign says this"
        are different claims and only the first one is evidence (criterion 4).
        """
        return tuple(
            check.name
            for check in self.facts
            if check.observed.source is FactSource.UNREADABLE
        )

    def fact(self, name: str) -> FactCheck:
        """The check for ``name`` (:data:`~udv_echo_process.acquire.snapshot.FIXED_FACT_FIELDS`)."""
        for check in self.facts:
            if check.name == name:
                return check
        raise ValueError(
            f"no check for {name!r}: this plan reconciled {[c.name for c in self.facts]}"
        )


def compile_campaign(
    definition: CampaignDefinition,
    snapshot: InstrumentSnapshot,
    *,
    strict_facts: tuple[str, ...] = (),
) -> ExecutableCampaign:
    """Reconcile a definition against one reading of the instrument, or refuse before recording.

    This is the step that turns "the campaign intends this" and "the instrument is that" into an
    explicit plan, or refuses to spend a single recording. The rule, implemented literally:

    - **the definition's own laws come first.** ``plan_campaign`` runs before anything is
      compared, so an unplannable file is refused for *that* reason and not for a screen state
      the next poll would change;
    - **the screen has to be the measurement screen** — no overlay up, a window that is showing
      its controls, and a readable mode. Each of those is a *precondition*: refusing them names
      the state that has to change instead of compiling an instrument whose configuration
      appears to differ;
    - **the channel has to have been routed**, by the step that selects it in the application and
      reads its own dialog back (``instrument_snapshot(*, routed_channel)``), and it has to be the
      campaign's channel. A reading that establishes no channel is not evidence about one;
    - **every fact the reading produced must agree with the definition**, at the acceptance its
      fact has in :data:`COVARIATE_ACCEPTANCE`: refusing, or warning and proceeding with the
      disagreement on the record. A fact nothing could read keeps the definition's declaration and
      is listed in :attr:`ExecutableCampaign.unproven` — never silently treated as verified.

    It drives nothing: no window is touched, no parameter written, no dialog opened, so it is
    safe to compile against an instrument somebody else is using, and the whole check runs on a
    captured snapshot on a host with no application at all.

    ``strict_facts`` is the **policy override**, and it is what a plan supplies when one of the
    fixed facts is the experiment rather than a nuisance: a fact named there refuses on
    disagreement whatever :data:`COVARIATE_ACCEPTANCE` says, its refusal says so in those words, and
    the compiled plan carries the tuple (:attr:`ExecutableCampaign.strict_facts`) so the policy a
    job was compiled under outlives the command line that set it. It can only **raise**: a fact the
    table already refuses is unchanged, and there is no argument that lowers one, because that would
    be a caller asking to be believed over the record.

    What it deliberately does **not** own: the strip's view. Starting a point cycle from a
    recording view is a precondition the runner refuses with its own message before anything is
    stored (``runner``'s "a running recording keeps its data"), and a second refusal here would
    give one cause two diagnoses.
    """
    strict_facts = _check_strict_facts(strict_facts, where=f"{definition.job!r}")
    points = plan_campaign(definition)
    _refuse_unusable_screen(snapshot)
    channel = _routed_channel(definition, snapshot)
    checks = tuple(
        _check_fact(definition, snapshot, name, strict_facts=strict_facts)
        for name in FIXED_FACT_FIELDS
    )
    _refuse_failed_reads(checks)
    _refuse_disagreements(checks)
    return ExecutableCampaign(
        job=definition.job,
        channel=channel,
        definition_fingerprint=campaign_fingerprint(definition),
        identity=CompilationIdentity.from_snapshot(snapshot),
        facts=checks,
        points=points,
        strict_facts=strict_facts,
    )


def _refuse_unusable_screen(snapshot: InstrumentSnapshot) -> None:
    """Refuse a screen that is not showing the measurement screen — naming the state, not a mode.

    Three states, and every one of them is a **precondition**: a modal is up; the window reports
    no visible controls in no panels, which is what a minimised window reports (the counts are
    filtered on ``IsWindowVisible``, which requires the window *and every ancestor* to be visible,
    ``driver._visible_children``); or no mode could be read at all, which is what a dialog, a menu
    popup or an unrecognised layout produces. Compiling any of them as "an instrument whose
    configuration differs" would refuse the run with the wrong diagnosis — and, worse, a
    *resume* would re-run a finished job for a window somebody minimised.
    """
    fingerprint = snapshot.fingerprint
    if fingerprint.overlay is not None:
        raise CampaignError(
            f"the application has an overlay up ({fingerprint.overlay.value!r}): a campaign is "
            "compiled against the measurement screen, so nothing was stored and nothing is "
            "stopped. Answer or dismiss it and compile again"
        )
    if fingerprint.panels == 0 and fingerprint.visible_controls == 0:
        raise CampaignError(
            "the window reports no visible controls in no panels, which is what a minimised "
            "window reports: the application is not showing its measurement screen, so there is "
            "nothing to compile against. Restore it and compile again"
        )
    mode = snapshot.mode
    if mode.source is not FactSource.READ:
        raise CampaignError(
            f"no channel mode could be read ({mode.reason}): the campaign's points write the "
            "manual parameter column, and a screen that is not the measurement screen is not "
            "evidence that the column is there. Nothing was stored — bring the measurement "
            "screen up and compile again"
        )
    if mode.value != ChannelMode.MANUAL.value:
        raise CampaignError(
            f"the channel is in {mode.value!r} mode: this campaign writes the manual parameter "
            "column — the resolution and the gate count — which that panel does not carry "
            "(measured: an assisted channel's screen is 21 visible controls in 3 panels against "
            "the manual channel's 43 in 4). Nothing was stored"
        )


def refuse_process_mode(snapshot: InstrumentSnapshot, expected: ProcessMode) -> None:
    """Refuse a reading whose caption does not state the process this run declares — by name.

    The mode rung of the compile path (plan §24.4, D3). The caption is the *only* surface that
    states which process is on the screen — every widget inside the window is caption-less, and
    the two clean layouts were measured at 43 and 44 controls, a difference *caused by* the mode
    rather than a discriminator of it — so this is the one fact a run cannot check structurally
    and the one it has to **declare** before anything is believed. Both sides are named, and so is
    the caption string itself, so the operator's next question ("which process is in front of
    me?") is answered by the refusal instead of by a second read (plan §24.5, D5).

    A caption that states nothing is a refusal too, never a default — the same argument as
    ``routed_channel`` (§12.1): an empty caption, or one naming a process this driver was not
    measured against, cannot prove the declaration that was made. There is no "no expectation"
    case to fall back to, because ``--expect-mode`` is required on every record path.

    It drives nothing and reads nothing: the reading is the argument, so the whole check runs on
    a captured snapshot on a host with no application at all.
    """
    fact = snapshot.process_mode
    stated = _stated_process_mode(fact)
    if fact.source is FactSource.READ and stated is expected:
        return
    if stated is None:
        raise CampaignError(
            f"nothing stated the process mode: {fact.reason or 'the caption names no process this driver knows'}. "
            f"This run declares it was measured against {expected.value!r}, and a reading that states no mode "
            "proves nothing about that, so nothing was stored and nothing is stopped. Bring up the process the "
            "run was measured against, or declare the one that is in front of you (--expect-mode)"
        )
    raise CampaignError(
        f"the process mode is {stated.value!r} where this run declares it was measured against "
        f"{expected.value!r} (the caption read {snapshot.fingerprint.caption!r}): a point recorded under one "
        "process and read as the other is a measurement whose conditions the record could not state, so nothing "
        "was stored and nothing is stopped. Declare the mode of the process in front of you (--expect-mode), or "
        "bring the one this job was measured against up"
    )


def _stated_process_mode(fact: InstrumentFact | Provenance | None) -> ProcessMode | None:
    """The mode a fact states, or ``None`` when it states none this driver knows.

    One place, so the compile's refusal and the manifest's ``observed_process_mode`` cannot
    disagree about what a fact said — the reading's own :class:`InstrumentFact` and the identity's
    :class:`Provenance` are read by the same rule. ``None`` also covers an identity written before
    the field existed, which states nothing by construction.
    """
    if fact is None or fact.source is not FactSource.READ or fact.value is None:
        return None
    try:
        return ProcessMode(fact.value)
    except ValueError:
        return None


def _routed_channel(
    definition: CampaignDefinition, snapshot: InstrumentSnapshot
) -> int:
    """The channel the routing step established, or a refusal carrying the reason it did not.

    The snapshot cannot read the channel itself (that costs the menubar hover the routing step
    pays), so it carries one only when the caller handed over what ``ensure_channel`` selected and
    verified. A campaign compiled against anything weaker would record its points under a channel
    nobody established — the one thing the record must never say.
    """
    fact = snapshot.channel
    if fact.source is not FactSource.ROUTED or fact.value is None:
        raise CampaignError(
            "the reading carries no routed channel "
            f"({fact.reason or 'nothing established one'}): a campaign is compiled only against "
            "the channel the routing step selected in the application and read back "
            "(ensure_channel), so the run's record can say which channel it actually used"
        )
    try:
        established = int(fact.value)
    except ValueError as exc:
        raise CampaignError(
            f"the routed channel {fact.value!r} is not a channel number: a snapshot from a "
            "written record is checked rather than trusted (docs/16)"
        ) from exc
    if established != definition.channel:
        raise CampaignError(
            f"the routing step established channel {established} but the campaign is aimed at "
            f"channel {definition.channel}: every point would be stored under another channel's "
            "window, so nothing was stored"
        )
    return established


def declared_fixed_fact(definition: CampaignDefinition, name: str) -> object | None:
    """The value the definition declares for one fixed fact — the field that has to agree.

    Four of them are the campaign's own shared fields. The two that are the window frame come
    from the points, which by the time this is called have already been planned: ``plan_campaign``
    refuses a list whose points disagree on the sound speed or the first gate, so the first
    point's frame *is* the campaign's.

    Public because it is the one answer to "what does this definition say about that fact", and a
    caller that needs to know whether a fact is **declared at all** (a run that raises a fact has
    nothing to raise it against unless every job states one) must not re-derive the answer from the
    models and drift from the comparison that uses it.
    """
    if name == "sound_speed_ms":
        return definition.points[0].parameters.sound_speed_ms
    if name == "first_gate_mm":
        return definition.points[0].parameters.first_gate_mm
    return getattr(definition, name)


def _check_fact(
    definition: CampaignDefinition,
    snapshot: InstrumentSnapshot,
    name: str,
    *,
    strict_facts: tuple[str, ...] = (),
) -> FactCheck:
    """Compare one fixed fact: the declaration against the reading, at its own acceptance.

    ``strict_facts`` raises a fact's acceptance to :attr:`Acceptance.REFUSE` for this call — the
    policy override a caller supplies when the fact is not a nuisance but the experiment
    (:func:`_check_strict_facts` validates the vocabulary). The raise never lowers anything, and the
    refusal it produces says which side of the policy it came from, so a reader of the message can
    tell the verifier's own table from a caller's requirement.

    The comparison is numeric on both sides, because both sides are numbers: the declaration is
    the campaign's own value and the reading is the application's rendering of the same setting,
    which it writes with the precision its field shows (169.0 µs for 169). The PRF keeps the
    verifier's own tolerance (:data:`~udv_echo_process.acquire.verify.PRF_TOLERANCE_US` — the
    application stores integer microseconds) and every other fact is exact, which is the same law
    the stored file is checked against after the recording: a pre-run check that were *stricter*
    would refuse jobs the post-run check would pass, and a looser one would compile a job that is
    then refused with a recording already spent.
    """
    observed = snapshot.fact(name)
    table_acceptance = COVARIATE_ACCEPTANCE[name]
    raised = name in strict_facts
    acceptance = Acceptance.REFUSE if raised else table_acceptance
    declared = declared_fixed_fact(definition, name)
    if declared is None:
        return FactCheck(
            name=name,
            observed=observed,
            acceptance=acceptance,
            detail=(
                f"{name}: the campaign declares no value for it, so there is nothing to "
                f"reconcile; the reading is carried as evidence only "
                f"(the instrument states {observed.value!r})"
                if observed.value is not None
                else f"{name}: the campaign declares no value for it and nothing on the "
                "instrument could state one"
            ),
        )
    declared_text = str(declared)
    if observed.source is not FactSource.READ or observed.value is None:
        return FactCheck(
            name=name,
            declared=declared_text,
            observed=observed,
            acceptance=acceptance,
            detail=(
                f"{name}: the definition's {declared_text} stands as a declaration — "
                f"{observed.reason or 'the instrument stated no value'}"
            ),
        )
    try:
        found = float(observed.value)
    except ValueError as exc:
        raise CampaignError(
            f"{name}: the instrument states {observed.value!r}, which is not a number to "
            "reconcile against the declaration: a value that cannot be compared is not agreement"
        ) from exc
    tolerance = PRF_TOLERANCE_US if name == "prf_us" else 0.0
    agreed = abs(float(declared) - found) <= tolerance
    return FactCheck(
        name=name,
        declared=declared_text,
        observed=observed,
        acceptance=acceptance,
        agreed=agreed,
        detail=(
            None
            if agreed
            else (
                f"{name}: the campaign declares {declared_text}, the instrument states "
                f"{observed.value!r}"
                + (f" (tolerance {tolerance:g})" if tolerance else "")
                + (
                    "; this run raises the fact to a refusal, where the stored-file verifier's "
                    f"own table calls it {table_acceptance.value!r} — a fact this run depends on "
                    "is not a nuisance to be recorded"
                    if raised
                    else ""
                )
            )
        ),
    )


def _refuse_failed_reads(checks: tuple[FactCheck, ...]) -> None:
    """Raise when a fact with a supported read path was **not read** — a failed read, not an absence.

    W1 gave the burst length, the sound speed and the first gate a real reader, which splits what a
    missing value can mean, and the two states must not be collapsed (plan §9.2):

    - nothing on this machine can state the fact (the block cap) — the reading cannot disagree with
      the definition about it, so it is carried ``declared`` and listed in
      :attr:`ExecutableCampaign.unproven`;
    - this driver *can* state it and this attempt did not — the check that exists was performed and
      failed, so a normal campaign refuses before the first recording rather than proceeding on the
      declaration alone.

    Refusing on the first case would make every campaign unrunnable on a fact no reader reaches;
    accepting the second would mean knowingly running when the instrument was not checked. Only
    facts the definition actually declares are judged: a campaign that declares nothing for a fact
    reconciles nothing (`_check_fact`), so there is nothing for a failed read to hide.

    This runs *before* :func:`_refuse_disagreements` within the facts step: a fact that was never
    read cannot be reported as agreeing or disagreeing, and the operator's first question is
    whether the check ran at all.
    """
    failed = [
        check
        for check in checks
        if check.name in SUPPORTED_READ_FACTS
        and check.declared is not None
        and check.observed.source is not FactSource.READ
    ]
    if not failed:
        return
    named = "; ".join(
        f"{check.name} (the campaign declares {check.declared}, and the reading states no value: "
        f"{check.observed.reason or 'no reason given'})"
        for check in failed
    )
    raise CampaignError(
        f"the reading did not establish {named} — each of those facts has a supported read path "
        "in this driver, so this is a read that failed rather than a fact this machine cannot "
        "state, and a campaign does not proceed on a declaration it could have checked. No "
        "recording was spent and the application is untouched"
    )


def _refuse_disagreements(checks: tuple[FactCheck, ...]) -> None:
    """Raise one refusal naming **every** fact that disagreed — not only the first one found.

    An operator with a campaign to fix should not have to fix it one run at a time: the
    comparison is cheap and the instrument is in front of them, so the whole list is reported at
    once. Warnings (:data:`Acceptance.WARN`) are not here — they travel with the plan instead.
    """
    refused = [
        check.detail
        for check in checks
        if check.agreed is False and check.acceptance is Acceptance.REFUSE
    ]
    if refused:
        raise CampaignError(
            "the instrument disagrees with the campaign before the first recording, so nothing "
            "was stored and the application is untouched: " + "; ".join(refused)
        )


def run_campaign(
    definition: CampaignDefinition,
    actuator: SweepActuator,
    *,
    store_dir: Path | str | None = None,
    log_path: Path | str | None = None,
    resume: bool = False,
    channel: int | None = None,
    definition_path: Path | str | None = None,
    notes: list[str] | None = None,
    now: datetime | None = None,
    no_snapshot: bool = False,
    resume_declaration_only: bool = False,
    expected_mode: ProcessMode,
    strict_facts: tuple[str, ...] = (),
) -> JobManifest:
    """Run the points that still have to run, write the manifest, and say what happened.

    The steps, and their order is the safety argument (plan §4):

    1. the definition is loaded by the caller and planned statically here
       (:func:`plan_campaign`) — every rule the application would enforce *silently* is
       enforced loudly, and an unplannable file is refused before anything else happens;
    2. **the channel is established** — ``actuator.ensure_channel()`` opens the dialog,
       verifies the channel and returns it. This is *routing*, not a scientific setting: it
       writes only if the channel differs from the requested one, and its own return is what
       the reading is handed;
    3. **the instrument is read** — ``instrument_snapshot(routed_channel=<from 2>,
       dialog_parameters=actuator.read_dialog_parameters())``. The dialog read is a step of
       its own because the snapshot deliberately does not open that dialog (it presses
       nothing), and the reading is what the compile is reconciled against;
    4. **the campaign is compiled** — :func:`compile_campaign`, whose :class:`CampaignError`
       **propagates untouched**: it already names the state or the fact that stopped the job,
       and re-wrapping it would give one cause two diagnoses. Nothing is stored before this
       point, which is the whole reason it exists;
    5. **the resume's identity is validated** — *before* the todo/skipped sets are computed,
       so no point can leave the todo set on an identity nothing proved
       (:func:`_validate_resume`). A previous manifest whose definition fingerprint differs
       refuses and is not bypassable; a previous manifest with no identity, or a different
       one, refuses by default;
    6. the points that still have to run are the **compiled** plan's
       (:attr:`ExecutableCampaign.points`), and they go through ``SweepRunner.run_points`` —
       the runner's own cycle, unchanged.

    The per-point work is the **runner's**: ``SweepRunner`` resets the block, applies the
    window, reads it back, records, stops, stores, decodes the stored file, sizes it against
    the signature and verifies its own words — and appends the log entry, valid or not. None
    of that cycle is re-implemented here; the seam is ``SweepRunner.run_points``, which takes
    an explicit sequence of points where ``run`` takes a ladder to expand. A campaign's points
    are explicit and may each carry their own window, so they are handed over as a sequence
    and not as a definition.

    ``resume=True`` drops the points the log already holds as *successful*
    (:func:`recorded_points`) and runs the rest in the file's order, saying in the notes
    how many it skipped. Without it every point runs, and the fresh stamp in each name
    keeps the re-run from overwriting the earlier files — reusing a name raises the Store
    dialog's ``file already exists`` warning, which wedges the application when nothing
    answers it (docs/16 §12b).

    ``no_snapshot=True`` skips steps 3 and 4 outright: no reading is taken, nothing is
    compiled, and the manifest is marked ``declared_only`` because the run's points then rest
    on the definition's declaration alone. A resume under it can never prove an identity (it
    has no reading of its own to compare), so it refuses unless ``resume_declaration_only``
    says so on purpose.

    ``resume_declaration_only=True`` turns each *identity* refusal above into a proceed, and
    only those: a changed definition is a different job and still refuses, because that flag is
    about instrument evidence and not about which job this is. What it authorises is recorded —
    every point it lets a resume skip is listed in the manifest's
    ``skipped_without_evidence``, so the run does not read like a proven resume.

    ``store_dir`` overrides the definition's and ``channel`` the definition's — the
    caller's argument wins, and the CLI takes ``--store-dir``/``UDV_STORE_DIR`` for the
    first. The channel is the one knob: a point recorded on the wrong channel decodes as a
    valid point that is not the point (docs/16 §12), so the runner verifies it once before
    the first recording, and the manifest records what it verified.

    ``expected_mode`` is **required and keyword-only** (plan §24.5, D3): the process this run was
    measured against is declared by the caller (``--expect-mode``), never inferred from what
    happens to be running. It is compared with what the caption states
    (:func:`refuse_process_mode`) *before* the compile and long before the first recording, handed
    to the runner so its per-point gate carries the same expectation, and persisted on the
    manifest as **both** halves (``expected_process_mode`` and ``observed_process_mode``) so the
    execution contract outlives the shell history that produced it. A ``no_snapshot`` run records
    the expectation and no observation — nothing was read.

    Raises :class:`CampaignError` when the definition cannot be planned, when no store
    directory is named, when the channel is not one the application offers, when the reading
    cannot be compiled against the definition, or when a resume's identity is not proven. The
    runner itself never raises for a bad point: a refused point is an outcome, and the manifest
    is written either way.

    ``strict_facts`` is the run's policy override, enforced **twice**: the compile refuses a
    disagreement before the first recording (:func:`compile_campaign`, which carries the tuple on the
    compiled plan), and the per-point verification refuses it *after* storage
    (``SweepRunner(strict_covariates=...)``), so a file whose own word disagrees invalidates its point
    instead of being logged with a note. One argument, both halves, because a fact a run depends on
    must not be enforced on one side of the recording and merely recorded on the other.
    """
    strict_facts = _check_strict_facts(strict_facts, where=f"{definition.job!r}")
    directory = _store_directory(definition, store_dir)
    log = Path(log_path) if log_path is not None else directory / DEFAULT_LOG_NAME
    effective_channel = definition.channel if channel is None else int(channel)
    if not MIN_CHANNEL <= effective_channel <= MAX_CHANNEL:
        raise CampaignError(
            f"channel {effective_channel} is outside the channels the application offers "
            f"({MIN_CHANNEL}..{MAX_CHANNEL})"
        )

    started_at = _local_now(now)

    # (2) the static plan: every rule the application would enforce *silently* is enforced
    # loudly here, and it is pure Python — so it happens before the first gesture on the
    # application, which is what makes an unplannable file cost nothing at all (not even a
    # dialog opening). The compile below plans again as part of its own refusal order
    # (compile_campaign's docstring: the definition's laws come before the screen is judged);
    # what a compiled run *executes* is the compiled plan, because that is the audited record.
    planned = plan_campaign(definition)

    # Steps 3-5: route, read, compile — all of it before the runner exists, so nothing can be
    # stored for a job that cannot be compiled. Each of the three calls is made once.
    compiled: ExecutableCampaign | None = None
    if no_snapshot:
        # Nothing is read and nothing is compiled, by definition of the flag. The points are
        # the static plan's — the same list the compile builds its identity around — and the
        # manifest states that no reading backs them.
        if notes is not None:
            notes.append(
                "no-snapshot: no instrument reading was taken and nothing was compiled; the "
                "manifest is marked declared-only and no point of this run rests on evidence"
            )
    else:
        # (3) the routing step. Its own return is the *evidence* the compile needs: the
        # reading cannot read the channel itself.
        routed = actuator.ensure_channel()
        # (4) one reading of the instrument, handed what the routing step established and
        # what the dialog reader read.
        snapshot = actuator.instrument_snapshot(
            routed_channel=routed,
            dialog_parameters=actuator.read_dialog_parameters(),
        )
        # (4a) the mode rung — the declaration against the caption, before the compile and long
        # before the first recording. It is the one fact a run cannot check structurally, and it
        # refuses by naming both sides and the caption itself (plan §24.4, §24.5 D3/D5).
        refuse_process_mode(snapshot, expected_mode)
        # (5) compiled, or refused — untouched, because the refusal already names the fact or
        # the state that stopped the job. The run's raised facts go with it, so the compiled plan
        # records the policy it was compiled under.
        compiled = compile_campaign(definition, snapshot, strict_facts=strict_facts)
        planned = compiled.points

    # (6) the resume's identity, validated *before* the todo/skipped sets are computed: no
    # point may leave the todo set on an identity nothing proved. The log is read once, here,
    # because the records are what the identity is validated *about*.
    done = recorded_points(log) if resume else set()
    unproven_resume = False
    if resume:
        unproven_resume = _validate_resume(
            definition,
            log,
            compiled=compiled,
            recorded=done,
            declaration_only=resume_declaration_only,
            notes=notes,
        )

    # (7) what is left to run, keyed on the identities the log already holds.
    todo = tuple(point for point in planned if point.identity not in done)
    skipped = tuple(point.identity for point in planned if point.identity in done)
    skipped_without_evidence = skipped if unproven_resume else ()
    if resume and notes is not None:
        notes.append(
            f"resume: {len(skipped)} of {len(planned)} point(s) are already recorded in "
            f"{log.name}; {len(todo)} to run"
        )

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
        expected_mode=expected_mode,
        # The same facts the compile refused on, enforced on the stored file's own words: a run
        # that raised a fact does not fall back to an advisory once the recording is spent.
        strict_covariates=strict_facts,
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
        compilation_identity=None if compiled is None else compiled.identity,
        declared_only=no_snapshot,
        skipped_without_evidence=skipped_without_evidence,
        # D3's durability, both halves: what this run was declared to be measured against, and
        # what the instrument's own caption stated. A no-snapshot run observed nothing, and says
        # so with a None rather than with the declaration repeated.
        expected_process_mode=expected_mode,
        observed_process_mode=(
            None if compiled is None else _stated_process_mode(compiled.identity.process_mode)
        ),
    )
    write_manifest(manifest_path_for(log), manifest)
    return manifest


def _validate_resume(
    definition: CampaignDefinition,
    log: Path,
    *,
    compiled: ExecutableCampaign | None,
    recorded: set[str],
    declaration_only: bool,
    notes: list[str] | None,
) -> bool:
    """Step 6: prove that this job is the job the log beside it already holds — or refuse.

    The log records *what* was recorded and nothing about *what it was measured on*, so a
    resume keyed on the log alone can leave a point out of the todo set on the strength of a
    fact nobody established. The proof is the previous manifest's ``compilation_identity``
    against the one this run compiled, and the refusals are:

    - **the definition changed** (``fingerprint`` differs) — a different job, so its recorded
      points are points of a job this definition never asked for. Never bypassable:
      ``--resume-declaration-only`` is about instrument evidence, not about which job this is;
    - **there is no previous manifest but the log holds successful records** — nothing carries
      an identity for them, which is the same gap as a manifest without one;
    - **the previous manifest carries no identity** — every manifest written before this slice,
      so a resume has nothing to compare;
    - **the identity differs** — compared fact by fact
      (:func:`_identity_disagreements`), so the refusal names *which* fact moved and both
      sides of the move rather than saying "a different instrument", which would send an
      operator to the window geometry that is deliberately not part of the identity;
    - **this run took no reading at all** (``no_snapshot``) — it has no identity of its own, so
      there is nothing to prove the previous job with.

    ``recorded`` is the identities the log already holds as successful
    (:func:`recorded_points`), passed in rather than re-read so that one resume reads its log
    once — and read by the caller *before* this call, because these records are what the
    identity is being validated about.

    ``declaration_only`` (the run's ``--resume-declaration-only``) turns every one of those
    *identity* refusals into a proceed and returns ``True``: the caller marks the points it let
    through as ``skipped_without_evidence``, so the record says the skip rested on a
    declaration. The definition-changed refusal is raised before that branch — deliberately, it
    is a different kind of claim.

    Nothing recorded and no manifest is not a refusal: there is nothing to skip, so there is
    nothing to prove.
    """
    fingerprint = campaign_fingerprint(definition)
    previous = read_manifest_if_present(manifest_path_for(log))

    if previous is not None and previous.fingerprint != fingerprint:
        raise CampaignError(
            f"{manifest_path_for(log).name} answers definition fingerprint "
            f"{previous.fingerprint[:12]}... while this definition's is {fingerprint[:12]}...: "
            "a changed definition is a different job, so its recorded points belong to a job "
            "this one never asked for and a resume would silently leave them out. Nothing was "
            "run. (--resume-declaration-only does not bypass this: that flag is about "
            "instrument evidence, not about which job this is)"
        )

    refusal: str | None = None
    if previous is None:
        if recorded:
            refusal = (
                f"{log.name} already holds {len(recorded)} successful point record(s) and there "
                "is no manifest beside it: nothing carries the compilation identity those "
                "records were measured under, so there is nothing a resume can compare against"
            )
    elif compiled is None:
        refusal = (
            "this run takes no instrument reading (no-snapshot), so it has no compilation "
            "identity of its own to compare with the previous job's"
        )
    elif previous.compilation_identity is None:
        refusal = (
            f"the manifest beside {log.name} carries no compilation identity: nothing says the "
            "previous job measured on this instrument (every manifest written before the "
            "identity was recorded is in this state), so its recorded points cannot be told "
            "apart from points measured somewhere else"
        )
    else:
        differences = _identity_disagreements(
            previous.compilation_identity, compiled.identity
        )
        if differences:
            refusal = (
                "the manifest beside the log was compiled against a different instrument: "
                + "; ".join(differences)
            )

    if refusal is None:
        return False
    if not declaration_only:
        raise CampaignError(
            f"a resume is refused because the identity of the previous job is not proven: "
            f"{refusal}. Nothing was run and nothing was stored. Pass "
            "--resume-declaration-only to proceed on the declaration alone — the points it "
            "skips are then recorded as skipped without instrument evidence"
        )
    if notes is not None:
        notes.append(
            f"resume-declaration-only: {refusal}; the points it skips are recorded as skipped "
            "without instrument evidence, because this run cannot prove them"
        )
    return True


#: The identity's facts for a resume comparison, in the order a refusal reports them: the three
#: that say *which surface* the previous job measured on — the channel, the channel's mode and the
#: **process** the caption stated (plan §24.5, D2) — then the six a definition declares
#: (:data:`~udv_echo_process.acquire.snapshot.FIXED_FACT_FIELDS`). Spelled out here rather than
#: read off the model, because the message's order is part of the answer an operator reads.
_IDENTITY_FACT_FIELDS: tuple[str, ...] = ("channel", "mode", "process_mode", *FIXED_FACT_FIELDS)

#: The identity's layout half: the window class, the panel count and the strip's view. Not
#: :class:`Provenance` — nothing declared them, so a disagreement here is the *screen* having
#: moved (a press is bound to a button's position in a view), never a setting.
#:
#: All four are **optional at parse time with a default** (the ``process_mode`` precedent, and
#: for the same reason): a manifest written before a later UI slice added one of them carries no
#: such field, and a *required* one would make ``read_manifest`` call that valid file "not a job
#: manifest" instead of refusing it by name at the comparison below. ``None`` on either side
#: means the field was never recorded, which is exactly what the refusal says — a field tolerated
#: at parse time and then silently ignored would instead skip points on evidence the previous job
#: never carried.
#:
#: ``visible_controls`` is deliberately **out** (plan §24.5, D6): the reference install's clean
#: screen is 43 in 4 and the instrument's own is 44 in 4, and whether that row is session state is
#: still open, so two runs on one instrument in one mode could differ by that single control and
#: be refused as a different instrument. It is the same ruling that took ``strip_button_count``
#: out, applied to the same class of number; the count stays in the reading, in its note and in
#: the record, where a reader sees the drift.
_IDENTITY_LAYOUT_FIELDS: tuple[str, ...] = (
    "class_name",
    "panels",
    "strip_view",
    "strip_has_slider",
)


def _identity_disagreements(
    previous: CompilationIdentity, current: CompilationIdentity
) -> tuple[str, ...]:
    """Every field two identities disagree about, each with both sides — never just the first.

    Fact by fact and through each fact's :class:`Provenance`, for two reasons. The operator's
    next question is *which* fact moved and what it moved between, and a refusal that said only
    "a different instrument" would send them to the window geometry — which is deliberately not
    in the identity. And the provenance is half the answer: a fact that moved from ``read`` to
    ``unreadable`` is a weaker claim about the *same* instrument, which a comparison on values
    alone would report as a change of instrument.

    Every disagreement is collected rather than raised on the first, the same way
    :func:`_refuse_disagreements` reports the whole list: the instrument is in front of the
    operator and one round trip should be enough to see all of it.

    One field may be **absent** rather than different, and it gets its own clause: an identity
    written before ``process_mode`` existed carries none, and an identity written before a later
    UI slice's field carries none of *those* — and a comparison that read either as "a different
    instrument" would send the operator looking at the instrument instead of at the manifest. The
    refusal says which side carries no reading and what that means — the previous job's mode or
    layout is not proven — because that is the state every manifest written before the field was
    recorded is in, and ``--resume-declaration-only`` is the documented way past it (plan §24.5,
    D2; the same rule for the identity's UI half).
    """
    differences: list[str] = []
    for name in _IDENTITY_FACT_FIELDS:
        was = getattr(previous, name)
        now = getattr(current, name)
        if was == now:
            continue
        if was is None or now is None:
            side = "the previous identity" if was is None else "this identity"
            differences.append(
                f"{name}: {side} carries no process mode, so the previous job's mode is not "
                "proven — nothing says which process it was measured against (every manifest "
                "written before the mode was recorded is in this state), and a point measured "
                "under one process and read as the other is a measurement whose conditions the "
                "record cannot state. A fresh run states one"
            )
            continue
        differences.append(
            f"{name}: the previous job was compiled against {_provenance_text(was)}, this one "
            f"against {_provenance_text(now)}"
        )
    for name in _IDENTITY_LAYOUT_FIELDS:
        was = getattr(previous, name)
        now = getattr(current, name)
        if was == now:
            continue
        if was is None or now is None:
            side = "the previous identity" if was is None else "this identity"
            differences.append(
                f"{name}: {side} carries no reading for this part of the layout, so the screen "
                "the previous job's presses were bound to is not proven — nothing recorded it "
                "(every manifest written before the field was recorded is in this state), and a "
                "point measured on one layout and resumed against another is a measurement "
                "whose conditions the record cannot state. A fresh run states one"
            )
            continue
        differences.append(
            f"{name}: the previous job's screen was {was!r} where this one's is {now!r} (the "
            "layout a run's presses were bound to, which is not a setting)"
        )
    return tuple(differences)


def _provenance_text(fact: Provenance) -> str:
    """One side of a fact comparison: its value and how strong the evidence behind it is.

    ``'1460' (read)`` says the application itself stated it; ``'1460' (declared)`` says it is a
    campaign's own claim, and ``no value (unreadable)`` says nothing could state it — three
    different claims that must not read alike in a refusal.
    """
    if fact.value is None:
        return f"no value ({fact.source.value})"
    return f"{fact.value!r} ({fact.source.value})"


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

    The manual's ``T_profile ≈ T_tran + T_prf · (16 + N_PRF)``
    (:func:`~udv_echo_process.acquire.plan.profile_period_s`), so the profile count in the
    plan is the profile count the size guard derives.
    """
    emissions = parameters.emissions_per_profile or 0
    period = parameters.prf_us or 0.0
    return profile_period_s(emissions, period)


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
