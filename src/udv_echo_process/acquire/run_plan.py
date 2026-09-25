"""The run plan — the level above one campaign definition: a pass, its job order and its state.

A campaign definition answers *what one job records*; nothing above it answers **which jobs run,
in which order, at what run-wide values, and what has already been done** — and the WP4 schedule
needs exactly those four answers:

- ``burst-4`` → ``CR1`` → ``burst-18`` → ``CR2`` → ``emissions-8`` → ``CR3`` → ``emissions-64``
  → ``CR4`` → ``emissions-128``, with each common-reference job **between** two scientific jobs;
- every scientific job's three block-local controls placed at the **beginning, middle and end** of
  its own point order;
- the run-wide ``burst_length`` and ``emissions_per_profile`` each job records at, which
  ``campaign.CampaignDefinition`` fixes once per job and a point therefore cannot change
  (``actuator.DIALOG_ONLY_PARAMETERS``);
- and a record of which jobs finished, so a resumed pass continues rather than repeats.

**Why this is not acquisition architecture.** The batch review's stop condition
(``acquisition-campaign-compilation-plan.md`` §9.1) bound the acquisition layer: it re-opens on
evidence, not on another abstraction. This module adds **no writer, no reader and no gesture**. It
is the encoding of an already-accepted design
(:doc:`docs/dop3000/sparse-parameter-set` §3.1, §3.2, §9) plus the arithmetic that proves the
design is executable *through the existing writer surface* — every rule it applies is either a law
``campaign.plan_campaign`` already enforces, or a property of the design's own rows.

**What it deliberately does not do.** It does not switch the application's run-wide values between
jobs (that is a GUI write for convenience, and the request is explicit about resisting it), and it
does not replace the per-job compile: :func:`plan_run` is static and touches no instrument, and
:func:`next_job` hands a job to ``campaign.run_campaign`` unchanged, so the instrument-facing
checks stay where they were verified — the run-wide setup is refused by the compile's own fact
table when the operator has not set it.

**Checked statically, before anything is recorded** (:func:`plan_run`):

- one name prefix **root** for the whole pass — each job's own prefix is ``<root>-<job>``
  (:func:`job_prefix`), so a stored name names its job — and one store directory, so no two jobs
  can name one file;
- point identities unique across the pass, not merely within a job — a resumed pass keys on them;
- every point's window is one of the pass's declared windows, every declared window is acquired by
  at least one scientific row, and a job's scientific rows hold distinct windows;
- the pass's window frame (sound speed, first gate — both dialog-only) is the same in every job and
  every point;
- the block cap the plan declares cannot wrap **any** point, whatever the achieved period turns out
  to be (the floor-period bound, :func:`required_block_cap`), and no point carries a wrap note;
- the three block-local controls are the pass's reference window, at the positions the design's
  "beginning / middle / end" means (:func:`expected_point_order`);
- a common-reference job holds exactly one recording, of the **true** reference condition;
- no scientific job acquires the reference condition, because the design has no such row;
- and the blocks that carry D1 — a ``sensitivity`` other than the reference's, and an echo/energy
  channel — cannot be expressed at all: the four models here are ``extra="forbid"`` and carry no
  ``sensitivity`` field, so a file that names one is refused by name.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from enum import Enum
from itertools import pairwise
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator

from udv_echo_process.acquire.actuator import BurstWriteResult
from udv_echo_process.acquire.campaign import (
    COVARIATE_ACCEPTANCE,
    STRICTABLE_FACTS,
    CampaignDefinition,
    CampaignError,
    JobManifest,
    PlannedPoint,
    campaign_fingerprint,
    declared_fixed_fact,
    load_campaign,
    manifest_path_for,
    plan_campaign,
    reconciled_burst_history,
)
from udv_echo_process.acquire.config import MAX_CHANNEL, MIN_CHANNEL
from udv_echo_process.acquire.log import burst_mutations, read_entries
from udv_echo_process.acquire.snapshot import SUPPORTED_READ_FACTS
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ANALYSIS_ORIENTATION",
    "CONTROL_LABELS",
    "CONTROL_PREFIX",
    "MANUAL_SETTINGS",
    "REFERENCE_DOCUMENT",
    "RUN_MANIFEST_SUFFIX",
    "JobKind",
    "PairRole",
    "PlannedJob",
    "PlannedRun",
    "PlannedWindow",
    "RunCondition",
    "RunJobRecord",
    "RunJobStatus",
    "RunManifest",
    "RunPlan",
    "RunPlanError",
    "RunPlanJob",
    "expected_point_order",
    "job_log_path",
    "job_prefix",
    "job_requirements",
    "load_run_plan",
    "new_run_manifest",
    "next_job",
    "operator_setup_sheet",
    "plan_fingerprint",
    "plan_run",
    "plan_run_file",
    "read_run_manifest",
    "record_job",
    "required_block_cap",
    "run_manifest_path",
    "separates",
    "write_run_manifest",
]

#: The design document this module encodes, cited in its refusals and on the operator's sheet.
REFERENCE_DOCUMENT = "docs/dop3000/sparse-parameter-set.md"

#: A block-local control's label prefix. The prefix is the *only* thing that tells a control from a
#: scientific row, and that is deliberate: the two are otherwise identical in parameters for the
#: one-condition emissions jobs (four same-setting acquisitions inside one run, design §3.2), so a
#: positional rule would have nothing to check against.
CONTROL_PREFIX = "ctrl-"

#: The three block-local controls of a scientific job, in the order the design's run places them:
#: one at the beginning of the run, one around its middle, one at its end.
CONTROL_LABELS: tuple[str, ...] = ("ctrl-begin", "ctrl-mid", "ctrl-end")

#: ``<log>.jsonl`` -> ``<plan>.run.json``: the pass's own record, beside the store it describes.
RUN_MANIFEST_SUFFIX = ".run.json"

#: The fixed analysis orientation of a paired pass: every pair is read **E64 minus E20**, whatever
#: order it was acquired in. The design is recorded in ``docs/dop3000/stage2-run-plan.md``, which
#: ships with the pass it describes and cites the analysis that decided it. A
#: paired pass states it and the plan refuses any other value, because an orientation that could
#: differ from pair to pair is an analysis that would have to infer it — and the acquisition order
#: of a counterbalanced design is precisely what must *not* carry the comparison's sign.
ANALYSIS_ORIENTATION = "E64 - E20"

#: The settings of the pass that **no writer and no reader of this repository reaches**, stated on
#: the operator's sheet because the design fixes them (``sparse-parameter-set.md`` §1) and a pass
#: that silently changed one would be a different experiment. Values are quoted from §1; the
#: document is their authority, and the stored file's own words are the authority afterwards.
MANUAL_SETTINGS: tuple[tuple[str, str], ...] = (
    ("emitting frequency", "4 MHz"),
    ("Doppler angle", "0"),
    ("velocity scale factor", "1"),
    ("TGC", "uniform ≈20 dB (word 23 = 0, word 25 = 255, word 24 start ≈19.92 dB)"),
    ("emitting power", "medium"),
    ("sensitivity", "medium — D1's `high` is not acquired in this pass"),
    ("skipped profiles", "0 (word 84)"),
    (
        "assisted mode / filtering during acquisition / alias auto-correction",
        "OFF",
    ),
)


#: Which surface states which readable fact, from ``snapshot``'s own module docstring: the PRF
#: period and the emissions per profile come off the measurement screen's parameter column, and the
#: burst length, the sound speed and the first gate out of the ``Operating parameters`` dialog. The
#: sheet has to name the surface, because that is where the operator looks to set the value.
_FACT_SURFACE: dict[str, str] = {
    "prf_us": "the measurement screen's parameter column",
    "emissions_per_profile": "the measurement screen's parameter column",
    "burst_length": "the Operating parameters dialog",
    "sound_speed_ms": "the Operating parameters dialog",
    "first_gate_mm": "the Operating parameters dialog",
}


class RunPlanError(CampaignError):
    """A run plan that cannot be run as written, named job by job.

    A :class:`~udv_echo_process.acquire.campaign.CampaignError` — and therefore a ``ValueError`` —
    because a caller's answer to it is the same: this file is not one this layer can run, here is
    the field and the change. Keeping it in the campaign family is what lets the CLI's existing
    handler report it as one ``udv-acquire:`` line instead of a traceback.
    """


class JobKind(str, Enum):
    """What a job is for, in the design's own two terms.

    ``SCIENTIFIC``
        A job that acquires new conditions. It carries its own run-wide burst/emissions values and
        its three block-local controls (design §3.1, §3.2).
    ``COMMON_REFERENCE``
        A reference-only job: one recording of the true reference condition, intended to be
        executed **between** two scientific jobs. It acquires no new condition, which is why it has
        no controls and exactly one point (design §3.2).
    ``RUN_LEVEL``
        One run-level observation of the pass's reference window at its own emissions level, with
        no block-local controls — the unit of a **paired** pass, where two of them, counterbalanced,
        make one pair whose only difference is emissions per profile. A pass of run-level jobs has
        no scientific job at all: nothing inside it is being crossed, the *between-pair* comparison
        is the experiment (``docs/dop3000/stage2-run-plan.md``).
    """

    SCIENTIFIC = "scientific"
    COMMON_REFERENCE = "common-reference"
    RUN_LEVEL = "run-level"


class PairRole(str, Enum):
    """A run-level job's place in its pair: the one that opens the pair, or the one that closes it.

    Both roles are recorded, because the pair is counterbalanced: which level leads is a design
    fact (two pairs each way) and the later analysis must be able to read it off the record rather
    than infer it from a sequence.
    """

    LEAD = "lead"
    FOLLOW = "follow"


class RunJobStatus(str, Enum):
    """How a job of a pass ended — three states, because "some points" is its own state.

    ``PENDING``
        Not recorded yet.
    ``OK``
        Every planned point of the job was stored and verified.
    ``PARTIAL``
        Some points are ok and some are not: the job ran and did not finish clean.
    ``FAILED``
        No point is ok (nothing stored, or everything refused).
    """

    PENDING = "pending"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class PlannedWindow(ValueModel):
    """A window of the pass: the pitch the application is asked for and the gate count.

    The pair is the design's own unit — a row of §3.1 identifies a condition by its resolution and
    its gate count, and the two are not free: the committed reference windows reached ≈98.96 mm at
    three pitches (0.617 × 145, 1.850 × 50, 2.960 × 31 gates), so a window is a *pair* and never a
    pitch with a gate count derived somewhere else.
    """

    resolution_mm: float = Field(gt=0)
    gates: int = Field(ge=1)

    @property
    def as_pair(self) -> tuple[float, int]:
        """The identity of this window — the pair a comparison is made on."""
        return (self.resolution_mm, self.gates)


class RunCondition(ValueModel):
    """The run-wide values a job records at: what ``CampaignDefinition`` fixes once per job.

    ``burst_length``, ``emissions_per_profile`` and ``prf_us`` are dialog-only
    (``actuator.DIALOG_ONLY_PARAMETERS``): a point cannot write them, so a job *is* the tuple of
    values it holds them at — which is exactly what makes the design's crossing two jobs rather
    than one randomized run (design §6).
    """

    burst_length: int = Field(ge=1)
    emissions_per_profile: int = Field(ge=1)
    prf_us: float = Field(gt=0)

    @property
    def as_triple(self) -> tuple[int, int, float]:
        """The identity of this condition — the triple a comparison is made on."""
        return (self.burst_length, self.emissions_per_profile, self.prf_us)


class RunPlanJob(ValueModel):
    """One job of a pass: its position, its identity, its definition and its run-wide values.

    ``condition`` is what the *plan* requires the job to record at, and ``definition`` is the file
    that says the same thing; :func:`plan_run` refuses the pair when they disagree, which is the
    only reason the same three values appear twice. That redundancy is the point: a plan is a
    reviewable statement about the pass, and the job file is what the runner executes.
    """

    step: int = Field(ge=1)
    job: str = Field(min_length=1)
    kind: JobKind
    #: Where the job's definition lives, **relative to the run plan's own directory**.
    definition: str = Field(min_length=1)
    condition: RunCondition
    #: The pair this job belongs to, for a run-level pass: one capital letter, shared by exactly two
    #: consecutive jobs. ``None`` in a sweep pass, where pairing is not a notion.
    pair: str | None = None
    #: This job's place in that pair. Stated rather than derived, so the record carries it.
    role: PairRole | None = None

    @field_validator("pair")
    @classmethod
    def _check_pair(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 1 or not value.isupper() or not value.isalpha():
            raise ValueError(
                f"{value!r} is not a pair id: a pair is named by one capital letter (A, B, ...), "
                "so that a pair is named the same way in the plan, the sheet and the run record"
            )
        return value

    @model_validator(mode="after")
    def _check_pairing(self) -> RunPlanJob:
        """A pair id and a role are one statement: half of it names nothing."""
        if (self.pair is None) != (self.role is None):
            raise ValueError(
                f"step {self.step} ({self.job!r}) states "
                f"{'a pair' if self.pair is not None else 'a role'} without "
                f"{'a role' if self.pair is not None else 'a pair'}: a job is in a pair *as* its "
                "lead or its follow, and half of that is a job nobody can place"
            )
        return self

    @field_validator("job")
    @classmethod
    def _check_job(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(f"must not carry surrounding whitespace, got {value!r}")
        return value

    @field_validator("definition")
    @classmethod
    def _check_definition(cls, value: str) -> str:
        if Path(value).is_absolute():
            raise ValueError(
                f"{value!r} is an absolute path: a definition is named relative to the run plan "
                "that lists it, so a plan and its jobs stay one directory that can be moved, "
                "reviewed and checked as a unit"
            )
        if ".." in Path(value).parts:
            raise ValueError(
                f"{value!r} climbs out of the run plan's directory: a job definition is named "
                "inside it"
            )
        return value


class RunPlan(ValueModel):
    """A pass: one channel, one window length, one naming and store rule, and an ordered job list.

    The fields are the facts that must be **identical across every job** for the pass to be one
    experiment, and each one is checked against the job files by :func:`plan_run`:

    ``duration_s``
        The fixed window (design §4's assumption: at least 11.52 s, so every recording can be
        truncated to the common comparison window).
    ``name_prefix`` and ``store_dir``
        Where the points land and what they are called. ``name_prefix`` is the pass's **root**:
        each job stores under ``<root>-<job>`` (:func:`job_prefix`), which is what keeps a stored
        name unambiguous while the labels stay the design's own short ones.
    ``max_profiles_per_block``
        The block cap the pass requires, declared rather than defaulted. It is a *requirement*
        (:func:`required_block_cap`) and not a reading: the active cap is an application preference
        no reader in this repository reaches, so it is stated here, named on the operator's sheet,
        and carried `unproven` by the compile.
    ``sound_speed_ms`` / ``first_gate_mm``
        The window frame. Both are dialog-only: a point writes the pitch and the gate count and
        nothing else, so a pass whose jobs disagreed on the frame would record files contradicting
        their own requests.
    ``reference_window`` / ``reference_condition``
        The pass's anchor and the true reference condition. Both are needed to *check* the design's
        two control kinds rather than to assume them: a block-local control must be the reference
        window at its job's own values, and a common-reference job must be the reference window at
        the reference values.
    ``windows``
        Every window any scientific row of the pass uses, the reference window included. A job's
        window that is not in this list is a condition the design does not have, and a declared
        window no scientific row acquires is a condition the pass does not record.
    ``strict_facts``
        The fixed facts this pass **raises to refusal** over the compile's own table
        (``campaign.STRICTABLE_FACTS``): the ones that are the experiment rather than a nuisance, so
        a disagreement stops the job before the first recording *and* invalidates the point whose
        stored file disagrees (``campaign.run_campaign(strict_facts=...)``). Empty by default — the
        table's own acceptance is right for an ordinary campaign — and every job of the pass must
        declare each fact it names, or there is nothing to compare.
    """

    plan: str = Field(min_length=1)
    channel: int = Field(default=1, ge=MIN_CHANNEL, le=MAX_CHANNEL)
    duration_s: float = Field(gt=0)
    name_prefix: str = Field(min_length=1)
    store_dir: str = Field(min_length=1)
    max_profiles_per_block: int = Field(ge=1)
    sound_speed_ms: float = Field(gt=0)
    first_gate_mm: float = Field(ge=0)
    reference_window: PlannedWindow
    reference_condition: RunCondition
    windows: tuple[PlannedWindow, ...]
    #: The fixed facts this pass raises to refusal (:data:`~udv_echo_process.acquire.campaign.STRICTABLE_FACTS`).
    strict_facts: tuple[str, ...] = ()
    #: A paired pass states the orientation its pairs are *read* at (:data:`ANALYSIS_ORIENTATION`).
    #: ``None`` for a sweep pass, which has no pairs to orient.
    analysis_orientation: str | None = None
    jobs: tuple[RunPlanJob, ...]

    @field_validator("plan", "name_prefix", "store_dir")
    @classmethod
    def _check_no_surrounding_space(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(f"must not carry surrounding whitespace, got {value!r}")
        return value

    @field_validator("windows")
    @classmethod
    def _check_windows(
        cls, value: tuple[PlannedWindow, ...]
    ) -> tuple[PlannedWindow, ...]:
        if not value:
            raise ValueError(
                "windows must not be empty: a pass acquires at least one window, and this list is "
                "what a job's own windows are checked against"
            )
        pairs = [window.as_pair for window in value]
        if len(set(pairs)) != len(pairs):
            raise ValueError(
                f"windows must be unique, got {pairs}: a repeated window would let two rows claim "
                "one condition"
            )
        return value

    @field_validator("jobs")
    @classmethod
    def _check_jobs(cls, value: tuple[RunPlanJob, ...]) -> tuple[RunPlanJob, ...]:
        if not value:
            raise ValueError("jobs must not be empty: a pass is at least one job")
        steps = [job.step for job in value]
        expected = list(range(1, len(value) + 1))
        if steps != expected:
            raise ValueError(
                f"step numbers must be 1..{len(value)} in order, got {steps}: the step is the "
                "job's position in the pass and the order the run manifest reports it in"
            )
        names = [job.job for job in value]
        if len(set(names)) != len(names):
            raise ValueError(f"job names must be unique, got {names}")
        paths = [job.definition for job in value]
        if len(set(paths)) != len(paths):
            raise ValueError(
                f"two jobs share one definition file ({paths}): a job is one definition, and a "
                "pass that ran one file twice would spend recordings on one condition"
            )
        return value

    @field_validator("strict_facts")
    @classmethod
    def _check_strict_facts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """A raised fact must be one the compile *and* the stored file can be held to.

        The vocabulary is :data:`~udv_echo_process.acquire.campaign.STRICTABLE_FACTS` — the fixed
        facts a stored file carries a word for — because a plan that raised a fact only the compile
        could see would refuse a job at the screen and then accept the file's own words: the
        dataset would be weaker than the policy claims. Whether every job actually *declares* the
        fact is checked against the definitions by :func:`plan_run`.
        """
        unknown = [name for name in value if name not in STRICTABLE_FACTS]
        if unknown:
            raise ValueError(
                f"strict_facts names {unknown}, which no stored file carries a word for: a pass "
                "raises a fact to have it enforced before *and* after the recording, and the "
                f"raiseable facts are {list(STRICTABLE_FACTS)}"
            )
        return tuple(name for name in STRICTABLE_FACTS if name in value)

    @model_validator(mode="after")
    def _check_structure(self) -> RunPlan:
        """The job sequence: scientific jobs with a common-reference job between each pair.

        This is the ordering the WP4 rows cannot encode (``existing-sweep-analysis-plan.md`` §9.2:
        a single definition carries its own point order, and no definition carries a cross-job
        order), so it is enforced here, once, as a property of the plan: the pass opens and closes
        on a scientific job and every common-reference job sits **between** two of them. Two
        adjacent reference-only jobs would separate nothing and would be two recordings of one
        condition with no job between them to measure against.
        """
        if self.reference_window.as_pair not in {
            window.as_pair for window in self.windows
        }:
            raise ValueError(
                f"the reference window {self.reference_window.as_pair} is not among the pass's "
                f"windows ({[window.as_pair for window in self.windows]}): the anchor every "
                "block-local control repeats has to be a window the pass acquires"
            )
        kinds = [job.kind for job in self.jobs]
        if JobKind.SCIENTIFIC not in kinds:
            self._check_run_level_pass()
            return self
        if any(job.kind is JobKind.RUN_LEVEL for job in self.jobs):
            raise ValueError(
                "a pass holds either scientific jobs with common references between them, or "
                "run-level jobs in pairs, and this one holds both "
                f"({[kind.value for kind in kinds]}): the two are different designs, and a "
                "run-level job inside a sweep is a pair with no partner to compare against"
            )
        if any(job.pair is not None or job.role is not None for job in self.jobs):
            raise ValueError(
                "this pass names pairs where it holds scientific jobs: pairing is the run-level "
                "design's own structure, and a sweep pass reads its comparisons off its jobs' "
                "conditions instead"
            )
        if kinds[0] is not JobKind.SCIENTIFIC or kinds[-1] is not JobKind.SCIENTIFIC:
            raise ValueError(
                "the pass must open and close on a scientific job, got "
                f"{[kind.value for kind in kinds]}: a common-reference check is a *between-jobs* "
                "check ("
                + REFERENCE_DOCUMENT
                + " §3.2), so it cannot sit at either end"
            )
        for first, second in pairwise(kinds):
            if first is JobKind.COMMON_REFERENCE and second is JobKind.COMMON_REFERENCE:
                raise ValueError(
                    "two common-reference jobs are adjacent: a reference-only job separates two "
                    "scientific jobs, and two in a row separate nothing ("
                    + REFERENCE_DOCUMENT
                    + " §3.2)"
                )
        return self

    def _check_run_level_pass(self) -> None:
        """The paired design: counterbalanced pairs of run-level jobs, emissions the only variable.

        Every rule here is a property of the paired design the Stage-2 campaign states
        (``docs/dop3000/stage2-run-plan.md``) rather than a matter of taste:

        * the pass is run-level jobs only — a scientific or reference-only job belongs to the sweep
          design, and mixing the two would leave a pair with nothing to compare against;
        * jobs come in pairs: the count is even, and each pair is a *consecutive* pair of steps with
          one lead and one follow, so the pass's order is the counterbalancing it claims;
        * the two jobs of a pair differ in emissions per profile and in nothing else, and every pair
          compares the same two levels — otherwise the pass would be measuring more than one thing
          at once;
        * the level that **leads** is the lower one in exactly half the pairs. That is what makes
          the design counterbalanced: with one level always first, a short-timescale order effect
          would be confounded with the emissions contrast the pairs exist to measure;
        * the pass raises emissions per profile to a refusal, because it is the pass's only varying
          run-wide setting: without the raise, a job recorded at the wrong level would be accepted
          and the pair would compare two jobs that are not two levels;
        * the analysis orientation is stated and is :data:`ANALYSIS_ORIENTATION`.
        """
        jobs = self.jobs
        if any(job.kind is not JobKind.RUN_LEVEL for job in jobs):
            raise ValueError(
                "a pass with no scientific job is the run-level design, so every job of it is a "
                f"run-level job, got {[kind.value for kind in (job.kind for job in jobs)]}"
            )
        if len(jobs) % 2:
            raise ValueError(
                f"a run-level pass is run in pairs, so its job count is even, got {len(jobs)}: "
                "the counterbalancing *is* the pairing, and an odd job is a pair with no partner"
            )
        if self.analysis_orientation != ANALYSIS_ORIENTATION:
            raise ValueError(
                f"a run-level pass is read at {ANALYSIS_ORIENTATION!r} for every pair, whatever "
                f"order it was acquired in, and this plan states {self.analysis_orientation!r}: the "
                "orientation is a property of the design, not of the sequence the jobs happen to "
                "be listed in"
            )
        if "emissions_per_profile" not in self.strict_facts:
            raise ValueError(
                "a run-level pass varies emissions per profile and nothing else, so it has to "
                "raise that fact to a refusal (strict_facts): the pair's whole meaning is which "
                "level each job recorded at, and without the raise a job run at the wrong level "
                "would be accepted as the one the plan asked for"
            )
        reference = self.reference_condition
        for job in jobs:
            if (
                job.condition.burst_length != reference.burst_length
                or job.condition.prf_us != reference.prf_us
            ):
                raise ValueError(
                    f"step {job.step} ({job.job!r}) records at burst "
                    f"{job.condition.burst_length} / PRF {job.condition.prf_us} where a run-level "
                    f"pass fixes both at its reference condition's {reference.burst_length} / "
                    f"{reference.prf_us}: emissions per profile is the only run-wide setting a "
                    "pair varies"
                )
        pairs: dict[str, list[RunPlanJob]] = {}
        for index in range(0, len(jobs), 2):
            first, second = jobs[index], jobs[index + 1]
            assert first.pair is not None and second.pair is not None
            if first.pair != second.pair:
                raise ValueError(
                    f"steps {first.step} and {second.step} are consecutive but sit in different "
                    f"pairs ({first.pair!r} and {second.pair!r}): a pair is two consecutive jobs, "
                    "so the acquisition order is the counterbalancing the design states"
                )
            if first.role is not PairRole.LEAD or second.role is not PairRole.FOLLOW:
                raise ValueError(
                    f"pair {first.pair!r} labels {first.job!r} "
                    f"{first.role.value if first.role else None!r} and {second.job!r} "
                    f"{second.role.value if second.role else None!r}, where the job that runs first "
                    "is the pair's lead: the role *is* which job opens the pair, so a set of labels "
                    "that disagrees with the pass's own order would put an orientation on the "
                    "record that no job acquired"
                )
            levels = {
                first.condition.emissions_per_profile,
                second.condition.emissions_per_profile,
            }
            if len(levels) != 2:
                raise ValueError(
                    f"pair {first.pair!r} records both of its jobs at emissions "
                    f"{first.condition.emissions_per_profile}: a pair exists to compare two levels, "
                    "and a pair at one level compares the same job with itself"
                )
            pairs.setdefault(first.pair, []).extend((first, second))
        if any(len(members) != 2 for members in pairs.values()):
            repeated = sorted(
                name for name, members in pairs.items() if len(members) != 2
            )
            raise ValueError(
                f"pair id(s) {repeated} name more than one pair: a pair letter names one pair of "
                "the pass, so a later pair cannot reuse its letter"
            )
        ladders = {
            tuple(sorted(levels))
            for levels in (
                [m.condition.emissions_per_profile for m in members]
                for members in pairs.values()
            )
        }
        if len(ladders) != 1:
            raise ValueError(
                f"the pairs do not compare the same two levels: {sorted(ladders)}. A pass is one "
                "comparison repeated for replication, so every pair holds the same pair of levels"
            )
        ladder = next(iter(ladders))
        if len(ladder) != 2:
            raise ValueError(
                f"the pass's pairs compare {list(ladder)}, which is one level rather than two"
            )
        low = ladder[0]
        leads = [
            members[0].condition.emissions_per_profile for members in pairs.values()
        ]
        if leads.count(low) * 2 != len(pairs):
            raise ValueError(
                f"the pair order is not counterbalanced: {leads.count(low)} of {len(pairs)} pairs "
                f"lead with the lower level {low}, where half of them must ({len(pairs) // 2}). "
                "With one level always first, a short-timescale order effect — handling time, "
                "thermal or mixer evolution, settling after an emissions change — is confounded "
                "with the emissions contrast the pairs exist to measure"
            )


class PlannedJob(ValueModel):
    """One job as it will run: the plan's entry plus the points ``plan_campaign`` produced.

    ``points`` are the campaign layer's own :class:`~udv_echo_process.acquire.campaign.PlannedPoint`
    objects, unmodified — the plan does not re-implement a single planning rule. ``definition_fingerprint``
    is ``campaign.campaign_fingerprint`` of the job's file, so a run manifest written later can name
    the exact definition that produced a job's log.
    """

    step: int = Field(ge=1)
    job: str
    kind: JobKind
    definition: str
    condition: RunCondition
    definition_fingerprint: str
    points: tuple[PlannedPoint, ...]
    #: The pair this job belongs to and its place in it, carried from the plan (``None`` in a
    #: sweep pass). Copied rather than looked up, so a record built from this job names its pair
    #: even if the plan's job list is later reordered.
    pair: str | None = None
    role: PairRole | None = None

    @property
    def recordings(self) -> int:
        """How many recordings this job spends."""
        return len(self.points)

    @property
    def scientific_labels(self) -> tuple[str, ...]:
        """The job's scientific rows, in the order the definition lists them."""
        return tuple(
            point.label
            for point in self.points
            if not point.label.startswith(CONTROL_PREFIX)
        )

    @property
    def control_labels(self) -> tuple[str, ...]:
        """The job's block-local controls, in the order the definition lists them."""
        return tuple(
            point.label
            for point in self.points
            if point.label.startswith(CONTROL_PREFIX)
        )


class PlannedRun(ValueModel):
    """A checked pass: nine jobs, their points, and the counts the design's rows predict.

    Nothing here is a target the compiler enforces — the counts are **derived** from the points,
    and the test that reads them compares them with the WP4 rows through the decision-layer
    validator's own :func:`compute_counts`, so the plan and the documents cannot drift apart
    silently. ``notes`` carries the things a reader has to know and no check can refuse: what the
    pass holds fixed without a reader, and which facts of a job's run-wide setup the compile will
    refuse and which it will only record.
    """

    plan: str
    plan_fingerprint: str = Field(min_length=1)
    directory: str
    channel: int = Field(ge=MIN_CHANNEL, le=MAX_CHANNEL)
    duration_s: float = Field(gt=0)
    name_prefix: str
    store_dir: str
    max_profiles_per_block: int = Field(ge=1)
    sound_speed_ms: float
    first_gate_mm: float
    reference_window: PlannedWindow
    reference_condition: RunCondition
    #: The facts the pass raises to refusal, carried so the sheet, the record and the run all state
    #: the same policy.
    strict_facts: tuple[str, ...] = ()
    #: The orientation this pass's pairs are read at, copied from the plan
    #: (:data:`ANALYSIS_ORIENTATION` for a paired pass; ``None`` for a sweep pass).
    analysis_orientation: str | None = None
    jobs: tuple[PlannedJob, ...]

    @property
    def recordings(self) -> int:
        """Every recording the pass spends."""
        return sum(job.recordings for job in self.jobs)

    @property
    def scientific_jobs(self) -> tuple[PlannedJob, ...]:
        """The jobs that acquire new conditions."""
        return tuple(job for job in self.jobs if job.kind is JobKind.SCIENTIFIC)

    @property
    def common_reference_jobs(self) -> tuple[PlannedJob, ...]:
        """The reference-only jobs, in the order they run."""
        return tuple(job for job in self.jobs if job.kind is JobKind.COMMON_REFERENCE)

    @property
    def run_level_jobs(self) -> tuple[PlannedJob, ...]:
        """The run-level jobs of a paired pass, in the order they run."""
        return tuple(job for job in self.jobs if job.kind is JobKind.RUN_LEVEL)

    @property
    def pairs(self) -> tuple[tuple[PlannedJob, ...], ...]:
        """The pass's pairs, in acquisition order — each ``(lead, follow)`` as planned.

        Read off the compiled jobs' own pair ids, not off their steps: a pair is the unit the
        design counterbalances, and the two are the same thing only while the plan says so.
        """
        groups: list[list[PlannedJob]] = []
        for job in self.jobs:
            if job.pair is None:
                raise RunPlanError(
                    f"job {job.job!r} belongs to no pair, so this pass has no pairs: a paired pass "
                    "is the run-level design's own shape, and its jobs all carry one"
                )
            if groups and groups[-1][0].pair == job.pair:
                groups[-1].append(job)
            else:
                groups.append([job])
        return tuple(tuple(group) for group in groups)

    def acquisition_orientation(self, job: PlannedJob) -> str | None:
        """The order this job's pair records its two emissions levels in, e.g. ``'64 -> 20'``.

        ``None`` for a job of a sweep pass. This is the fact the counterbalancing is *for*: the
        analysis reads the pair at the fixed :data:`ANALYSIS_ORIENTATION` and can point at the
        acquisition order it actually ran in.
        """
        if job.pair is None:
            return None
        for group in self.pairs:
            if group[0].pair == job.pair:
                return " -> ".join(
                    str(member.condition.emissions_per_profile) for member in group
                )
        raise RunPlanError(
            f"job {job.job!r} names pair {job.pair!r}, which the pass does not hold: "
            f"{[group[0].pair for group in self.pairs]}"
        )

    @property
    def scientific_recordings(self) -> int:
        """The recordings of scientific rows — one per new condition.

        Counted over the *scientific* jobs only: a common-reference job's single recording is the
        reference condition rather than a new one, and counting it here would report eleven
        conditions where the design has seven executable ones.
        """
        return sum(len(job.scientific_labels) for job in self.scientific_jobs)

    @property
    def block_local_control_recordings(self) -> int:
        """The recordings spent on block-local controls."""
        return sum(len(job.control_labels) for job in self.jobs)

    @property
    def common_reference_recordings(self) -> int:
        """The recordings of common-reference jobs."""
        return sum(job.recordings for job in self.common_reference_jobs)

    @property
    def required_block_cap(self) -> int:
        """The smallest block cap under which no point of this pass can wrap."""
        return required_block_cap(self)

    @property
    def counts(self) -> dict[str, int]:
        """The pass's counts, in the WP4 count table's own keys — seven of them, derived.

        The same keys ``tools/validate_decision_layer.py`` derives from ``decision-table.md``, so
        the run plan and the documents are comparable field by field. Two of the seven differ from
        the documents' values, and the difference is the *point* of this module's vocabulary: the
        design's eight conditions include D1, which is blocked and which no writer can execute, so
        ``unique_new_conditions`` is 7 here and ``blocked_conditions`` is 0 — a plan cannot express
        a condition it cannot run (the models carry no ``sensitivity`` field at all). The other
        five keys are the plan's own and must equal the documents'.
        """
        return {
            "unique_new_conditions": self.scientific_recordings,
            "blocked_conditions": 0,
            "executable_scientific_recordings": self.scientific_recordings,
            "block_local_control_recordings": self.block_local_control_recordings,
            "common_reference_recordings": self.common_reference_recordings,
            "executable_jobs": len(self.jobs),
            "recordings_first_pass": self.recordings,
        }


class RunJobRecord(ValueModel):
    """One job of a pass, as the pass's own manifest reports it.

    Every field a reader needs to place a job without the instrument: what it was, at what
    run-wide values, from which definition (by fingerprint), where its log and manifest are, and
    how many of its planned recordings are ok. ``skipped`` names the identities a resumed job found
    already recorded, so a job that looks short is explained by its own row.
    """

    step: int = Field(ge=1)
    job: str
    kind: JobKind
    definition: str
    definition_fingerprint: str
    condition: RunCondition
    status: RunJobStatus = RunJobStatus.PENDING
    expected_recordings: int = Field(ge=0)
    ok_recordings: int = Field(default=0, ge=0)
    skipped: tuple[str, ...] = ()
    log: str
    manifest: str | None = None
    finished_at: datetime | None = None
    note: str | None = None
    #: The pair this job belongs to and its place in it, for a paired pass (``None`` otherwise).
    pair: str | None = None
    role: PairRole | None = None
    #: The order this job's pair recorded its two levels in, e.g. ``'20 -> 64'`` — stored on the
    #: row, so a later reader reconstructs pair membership and orientation from the run record
    #: rather than from file names or from the order the jobs happen to be listed in.
    orientation: str | None = None
    #: The burst transitions this job's boundary has performed, copied from the job's own manifest —
    #: the driver's :class:`~udv_echo_process.acquire.actuator.BurstWriteResult` (the request, the
    #: state, both dialog rows on both sides of the write and the dependent sampling-volume
    #: statement), not a boolean, and an **ordered history** (oldest first) rather than one write.
    #: An empty tuple means the job has spent no write at all (the instrument stated the job's burst
    #: on every invocation, the definition declared no burst, or the run took no reading and
    #: transitioned nothing).
    #:
    #: Copied rather than re-derived, and merged with whatever this row already carried, so a row
    #: rewritten by a resumed job keeps the earlier recording's transitions instead of reporting only
    #: the latest write. Defaulted, like every field a manifest written before a slice added: a row a
    #: reader refuses is a pass whose record can no longer be read.
    burst_transitions: tuple[BurstWriteResult, ...] = ()


class RunManifest(ValueModel):
    """What a pass has done: one row per job, in plan order, and the pass it belongs to.

    The run-level counterpart of :class:`~udv_echo_process.acquire.campaign.JobManifest`, and it
    exists for the one thing a job manifest cannot say: **where the pass stands**. A job manifest
    answers "how did this job go"; this answers "which job is next", which is the only question a
    resumed pass has to answer, and it answers it only for a pass whose earlier jobs are ok —
    :func:`record_job` refuses a job that is not next, because the cross-job order is a property of
    the pass rather than of any job.
    """

    plan: str
    plan_fingerprint: str
    channel: int = Field(ge=MIN_CHANNEL, le=MAX_CHANNEL)
    duration_s: float = Field(gt=0)
    store_dir: str
    created_at: datetime
    updated_at: datetime
    #: The orientation this pass's pairs are read at (:data:`ANALYSIS_ORIENTATION`), copied from
    #: the plan so the record states the design's own rule beside the jobs it applies to.
    analysis_orientation: str | None = None
    jobs: tuple[RunJobRecord, ...] = ()

    @property
    def next_step(self) -> int | None:
        """The step of the first job that is not ok, or ``None`` when the pass is complete."""
        for record in self.jobs:
            if record.status is not RunJobStatus.OK:
                return record.step
        return None

    @property
    def next_record(self) -> RunJobRecord | None:
        """The first job that is not ok, or ``None`` when the pass is complete."""
        for record in self.jobs:
            if record.status is not RunJobStatus.OK:
                return record
        return None

    @property
    def complete(self) -> bool:
        """True when every job of the pass is ok."""
        return bool(self.jobs) and self.next_step is None

    @property
    def ok_steps(self) -> tuple[int, ...]:
        """The steps that are ok — what a later job's predecessor check reads."""
        return tuple(
            record.step for record in self.jobs if record.status is RunJobStatus.OK
        )

    @property
    def summary(self) -> str:
        """One line: where the pass stands, in the terms an operator checks it by."""
        if not self.jobs:
            return "no job of this pass has run"
        done = len(self.ok_steps)
        parts = [f"{done}/{len(self.jobs)} job(s) ok"]
        if self.next_record is not None:
            parts.append(
                f"next: step {self.next_record.step} {self.next_record.job!r} "
                f"({self.next_record.status.value})"
            )
        else:
            parts.append("the pass is complete")
        return "; ".join(parts)


def job_prefix(plan: RunPlan, job: str) -> str:
    """The name prefix one job of a pass stores under: ``<plan root>-<job>``.

    Derived, and derived *here* rather than declared in nine files, because it is the thing that
    keeps a stored name unambiguous: the pass declares one root (``sparse1``), each job's prefix is
    ``<root>-<job>`` (``sparse1-burst-4``), and a stored name is therefore
    ``<root>-<job>-<label>-<stamp>`` — which names the job it belongs to as well as the point, even
    though the labels stay the design's own short ones (``ctrl-begin``, ``cc1``, ``cr1``) and repeat
    from job to job. Under one flat prefix those labels would collide across jobs, and a renamed
    point is a point a resumed pass cannot find.
    """
    return f"{plan.name_prefix}-{job}"


def expected_point_order(scientific_labels: tuple[str, ...]) -> tuple[str, ...]:
    """The design's within-job order: control, scientific rows, control, control.

    "a block-local control at the beginning of the run, the block's scientific points, a
    block-local control around the middle and one at the end" (``sparse-parameter-set.md`` §3.1).
    For ``n`` scientific rows the middle control follows the first ``ceil(n / 2)`` of them, which
    is the position that splits the sequence where the design says the middle is:

    - ``n = 1`` → ``[ctrl-begin, row, ctrl-mid, ctrl-end]`` (E8, E64, E128);
    - ``n = 2`` → ``[ctrl-begin, row1, ctrl-mid, row2, ctrl-end]`` (``burst-4``, ``burst-18``).

    A job with a single scientific row therefore ends with two adjacent controls, and that is the
    design's own arithmetic rather than a choice made here: three controls at beginning / middle /
    end of a one-condition run have no further position to occupy.
    """
    if not scientific_labels:
        raise ValueError(
            "a scientific job has at least one scientific row: this order is what a job's "
            "block-local controls are placed around"
        )
    split = math.ceil(len(scientific_labels) / 2)
    return (
        CONTROL_LABELS[0],
        *scientific_labels[:split],
        CONTROL_LABELS[1],
        *scientific_labels[split:],
        CONTROL_LABELS[2],
    )


def required_block_cap(run: PlannedRun) -> int:
    """The smallest cap under which no point of this pass can wrap, whatever the period is.

    The achieved profile period is **never shorter** than the sum of the programmed PRF periods of
    one profile — ``emissions_per_profile × prf_us`` — because that is the time the instrument
    spends emitting them; the rest of the manual's law — the instrument's own 16 emissions and
    the transfer term (``acquire/plan.profile_period_s``) — can only make it longer. So the most profiles a point can
    possibly store in the pass's window is ``ceil(T / (emissions × T_prf))``, and a cap at least
    that large cannot wrap it: the block keeps everything the point records.

    This is why the cap is *declared* on the plan rather than defaulted. The active cap is an
    application preference with no reader in this repository (``sparse-parameter-set.md`` §9), so
    the honest declaration is the plan's own requirement — and with it stated, a wrap becomes a
    thing the record can contradict rather than a silent loss of the window's tail. It is the
    largest value over the *jobs* rather than the points, because the whole pass declares one cap
    and every point of a job shares that job's condition.
    """
    if not run.jobs:
        raise RunPlanError("a pass with no jobs has no block-cap requirement")
    largest = 0
    for job in run.jobs:
        floor_period_s = (
            job.condition.emissions_per_profile * job.condition.prf_us * 1e-6
        )
        if floor_period_s <= 0:
            raise RunPlanError(
                f"job {job.job!r} declares no profile period: emissions "
                f"{job.condition.emissions_per_profile} x PRF {job.condition.prf_us} us is not "
                "positive, so the window cannot be sized against the block cap"
            )
        largest = max(largest, math.ceil(run.duration_s / floor_period_s))
    return largest


def plan_fingerprint(plan: RunPlan) -> str:
    """A stable hash of the plan's content — which plan a pass belongs to.

    Canonical JSON through SHA-256, exactly as ``campaign.campaign_fingerprint`` hashes a
    definition, so a stored plan hashes the same on every host and any change to a job, a
    condition or a window changes it. The run manifest carries it beside the per-job fingerprints,
    which is what ties a pass's record to the plan it answered.

    Absent optionals are not part of the identity: ``exclude_none`` drops them, so a plan that does
    not state an optional field and one that states it as null hash alike, and an *additive*
    optional field cannot move the fingerprint of a plan already recorded. Every value a plan does
    carry is still covered — including the Stage-2 pass's pair, role and analysis orientation, which
    it states. The alternative breaks provenance rather than tests: without this, adding a field
    would move the fingerprint a stored pass record answers, and the record of a recording that
    already happened could only be reconciled by rewriting it.
    """
    canonical = json.dumps(
        plan.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_run_plan(path: Path) -> RunPlan:
    """Read a run plan from JSON, or refuse it naming the offending field.

    JSON only, for the campaign loader's own reason: no YAML parser is declared and this file needs
    nothing a JSON object cannot say. Failures are :class:`RunPlanError` naming the file and the
    field — never a bare pydantic traceback, because the person fixing it is reading this message.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunPlanError(f"{source}: the run plan could not be read ({exc})") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunPlanError(f"{source}: not valid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise RunPlanError(
            f"{source}: a run plan is a JSON object, got {type(payload).__name__}"
        )
    try:
        return RunPlan.model_validate(payload)
    except ValidationError as exc:
        raise RunPlanError(f"{source}: {_explain(exc)}") from exc


def plan_run(plan: RunPlan, *, directory: Path | str) -> PlannedRun:
    """Plan every job of a pass and check the whole thing, without touching an instrument.

    ``directory`` is the directory the plan was read from: a job's ``definition`` is relative to it,
    so this is the one argument that cannot be guessed from the plan itself
    (:func:`plan_run_file` is the form that reads both from one path).

    Everything here is either a law the campaign layer already enforces — every job goes through
    :func:`~udv_echo_process.acquire.campaign.plan_campaign`, so the ladder, the gate range, the
    depth budget and the label grammar are checked exactly once and in one place — or a property of
    the *design's own rows*, which is what this function exists for:

    - the plan's run-wide facts hold in every job file (channel, window length, name prefix, store
      directory, block cap, window frame);
    - a job records at the values the plan states for it, and **no** job moves the PRF period;
    - every point's window is one of the pass's declared windows, a scientific job's rows hold
      distinct windows, and every declared window is acquired by some scientific row;
    - the three block-local controls are the pass's reference window at the positions
      :func:`expected_point_order` derives, and a common-reference job is exactly one recording of
      the true reference condition;
    - no scientific job acquires the reference condition, because the design has no such row;
    - point identities are unique across the whole pass, not merely inside a job;
    - the declared block cap cannot wrap any point, and no point carries a wrap note;
    - and a file that names a ``sensitivity`` is already refused by the models (``extra="forbid"``),
      which is how D1 — the one condition no writer can execute
      (``sparse-parameter-set.md`` §3.1, §6) — cannot be compiled into an executable plan.

    Raises :class:`RunPlanError` naming the step, the job and the point. The jobs come back in the
    plan's order: that order *is* the run order.
    """
    base = Path(directory)
    planned: list[PlannedJob] = []
    identities: dict[str, str] = {}
    used_windows: set[tuple[float, int]] = set()

    for entry in plan.jobs:
        definition = _load_job_definition(base, entry)
        _check_job_declaration(plan, entry, definition)
        _check_raised_facts(plan, entry, definition)
        points = plan_campaign(definition)
        _check_job_points(plan, entry, points, identities, used_windows)
        planned.append(
            PlannedJob(
                step=entry.step,
                job=entry.job,
                kind=entry.kind,
                definition=entry.definition,
                condition=entry.condition,
                definition_fingerprint=campaign_fingerprint(definition),
                points=points,
                pair=entry.pair,
                role=entry.role,
            )
        )

    _check_every_window_is_acquired(plan, used_windows)
    run = PlannedRun(
        plan=plan.plan,
        plan_fingerprint=plan_fingerprint(plan),
        directory=str(base),
        channel=plan.channel,
        duration_s=plan.duration_s,
        name_prefix=plan.name_prefix,
        store_dir=plan.store_dir,
        max_profiles_per_block=plan.max_profiles_per_block,
        sound_speed_ms=plan.sound_speed_ms,
        first_gate_mm=plan.first_gate_mm,
        reference_window=plan.reference_window,
        reference_condition=plan.reference_condition,
        strict_facts=plan.strict_facts,
        analysis_orientation=plan.analysis_orientation,
        jobs=tuple(planned),
    )
    _check_block_cap(run)
    return run


def plan_run_file(path: Path) -> PlannedRun:
    """Load a run plan from ``path`` and plan it — the form that cannot get ``directory`` wrong."""
    source = Path(path)
    return plan_run(load_run_plan(source), directory=source.parent)


def _load_job_definition(base: Path, entry: RunPlanJob) -> CampaignDefinition:
    """Read one job's definition, refusing a file that cannot be the job the plan lists."""
    path = base / entry.definition
    definition = load_campaign(path)
    if definition.job != entry.job:
        raise RunPlanError(
            f"step {entry.step}: {path} declares job {definition.job!r} while the run plan lists "
            f"{entry.job!r} at this step — a job's name is how its log, its manifest and its row "
            "in the pass's record are found, so the two cannot differ"
        )
    return definition


def _check_job_declaration(
    plan: RunPlan, entry: RunPlanJob, definition: CampaignDefinition
) -> None:
    """Refuse a job file that disagrees with the pass on any run-wide fact."""
    where = f"step {entry.step} ({entry.job!r}, {entry.definition})"
    for name, declared, expected in (
        ("channel", definition.channel, plan.channel),
        ("duration_s", definition.duration_s, plan.duration_s),
        (
            "name_prefix",
            definition.name_prefix,
            job_prefix(plan, entry.job),
        ),
        (
            "max_profiles_per_block",
            definition.max_profiles_per_block,
            plan.max_profiles_per_block,
        ),
        ("prf_us", definition.prf_us, entry.condition.prf_us),
        (
            "emissions_per_profile",
            definition.emissions_per_profile,
            entry.condition.emissions_per_profile,
        ),
        ("burst_length", definition.burst_length, entry.condition.burst_length),
    ):
        if declared != expected:
            raise RunPlanError(
                f"{where} declares {name}={declared!r} while the run plan states "
                f"{expected!r} for it: {name} is a run-wide fact of the pass "
                "(a point cannot write it), so a job that disagreed would record files the plan "
                "does not describe"
            )
    if definition.store_dir is not None and definition.store_dir != plan.store_dir:
        raise RunPlanError(
            f"{where} declares store_dir={definition.store_dir!r} while the run plan stores the "
            f"pass in {plan.store_dir!r}: one pass writes one directory, because the run manifest "
            "and every job's log and manifest live beside the points they describe"
        )
    for point in definition.points:
        parameters = point.parameters
        if parameters.sound_speed_ms != plan.sound_speed_ms:
            raise RunPlanError(
                f"{where} point {point.label!r} asks for sound_speed_ms="
                f"{parameters.sound_speed_ms:g} while the pass's frame is "
                f"{plan.sound_speed_ms:g}: the sound speed is dialog-only, so every recording of "
                "the pass is measured at the channel's own c whatever a point says"
            )
        if parameters.first_gate_mm != plan.first_gate_mm:
            raise RunPlanError(
                f"{where} point {point.label!r} asks for first_gate_mm="
                f"{parameters.first_gate_mm:g} while the pass's frame is {plan.first_gate_mm:g}: "
                "the first gate is dialog-only too, and it decides the near end of every window of "
                "the pass"
            )


def _check_raised_facts(
    plan: RunPlan, entry: RunPlanJob, definition: CampaignDefinition
) -> None:
    """Every fact the pass raises must be **declared** by every job, or the raise compares nothing.

    A raise is a comparison at a stricter acceptance, and a job that declares no value for the fact
    falls through to "there is nothing to reconcile" (:func:`campaign.declared_fixed_fact` returns
    ``None``, and :func:`campaign._check_fact` carries the declaration instead of comparing). The
    pass would then read as stricter than it is.

    **For today's vocabulary this cannot fire**, and that is worth stating rather than implying it
    guards something live: every fact in :data:`~udv_echo_process.acquire.campaign.STRICTABLE_FACTS`
    is required by :class:`~udv_echo_process.acquire.campaign.CampaignDefinition` or by its points,
    so a raise is always declared. It is here because the vocabulary is a table, not a law: the day
    an *optional* fixed fact is added to it, a raise would silently compare nothing, and this is the
    line that refuses that instead.
    """
    for name in plan.strict_facts:
        if declared_fixed_fact(definition, name) is not None:
            continue
        raise RunPlanError(
            f"step {entry.step} ({entry.job!r}, {entry.definition}) declares no value for {name}, "
            "which this run plan raises to a refusal: a fact the pass depends on has to be stated "
            "by every job, or the raise has nothing to compare and the pass would look stricter "
            "than it is"
        )


def _check_job_points(
    plan: RunPlan,
    entry: RunPlanJob,
    points: tuple[PlannedPoint, ...],
    identities: dict[str, str],
    used_windows: set[tuple[float, int]],
) -> None:
    """Check one job's points against the design's own rules, and take its windows and identities."""
    where = f"step {entry.step} ({entry.job!r}, {entry.definition})"
    for point in points:
        window = (point.parameters.resolution_mm, point.parameters.gates)
        if window not in {candidate.as_pair for candidate in plan.windows}:
            raise RunPlanError(
                f"{where} point {point.label!r} asks for {window[0]:g} mm x {window[1]} gates, "
                "which is not one of the pass's windows "
                f"({[candidate.as_pair for candidate in plan.windows]}): a window the design does "
                "not name is a condition the pass was not designed to acquire — add it to the "
                "plan's windows, or fix the point"
            )
        owner = identities.get(point.identity)
        if owner is not None:
            raise RunPlanError(
                f"{where} point {point.label!r} has identity {point.identity!r}, which is already "
                f"{owner}: every job of the pass stores into one directory under one name prefix, "
                "so an identity shared across jobs would make a resumed pass unable to tell which "
                "job a stored file belongs to"
            )
        identities[point.identity] = (
            f"{where} point {point.label!r} (step {entry.step})"
        )
        if point.note is not None:
            raise RunPlanError(
                f"{where} point {point.label!r} wraps the pass's own declared block cap of "
                f"{plan.max_profiles_per_block} profiles: {point.note}. A run plan states a cap at "
                "least its own requirement (required_block_cap), because the pass's window is only "
                "comparable if every point keeps all of it"
            )
        if point.label.startswith(CONTROL_PREFIX):
            _check_control_window(plan, entry, point)
            continue
        used_windows.add(window)

    if entry.kind is JobKind.COMMON_REFERENCE:
        _check_common_reference_job(plan, entry, points)
        return

    if entry.kind is JobKind.RUN_LEVEL:
        _check_run_level_job(plan, entry, points)
        return

    if entry.condition.as_triple == plan.reference_condition.as_triple:
        raise RunPlanError(
            f"{where} is a scientific job recording at the reference condition "
            f"(burst {plan.reference_condition.burst_length}, emissions "
            f"{plan.reference_condition.emissions_per_profile}, PRF "
            f"{plan.reference_condition.prf_us:g} us): the design acquires no new condition there — "
            "the reference is already committed and is repeated only by the common-reference jobs "
            f"({REFERENCE_DOCUMENT} §3.1, §3.2) — so this job would spend recordings on a "
            "condition the pass does not claim"
        )
    if entry.condition.prf_us != plan.reference_condition.prf_us:
        raise RunPlanError(
            f"{where} records at PRF {entry.condition.prf_us:g} us while the pass holds "
            f"{plan.reference_condition.prf_us:g} us: the PRF period is fixed for the whole "
            f"augmentation ({REFERENCE_DOCUMENT} §1), and 250 us is deferred rather than acquired"
        )

    labels = tuple(point.label for point in points)
    expected = expected_point_order(
        tuple(label for label in labels if not label.startswith(CONTROL_PREFIX))
    )
    if labels != expected:
        raise RunPlanError(
            f"{where} lists its points as {list(labels)} where the design's within-job order is "
            f"{list(expected)} ({REFERENCE_DOCUMENT} §3.1: a block-local control at the beginning, "
            "the block's scientific points, one around the middle and one at the end). Within-job "
            "order is exactly what a definition does encode — the runner runs a definition's order "
            "literally — so it has to be the design's order here"
        )

    seen: dict[tuple[float, int], str] = {}
    for point in points:
        if point.label.startswith(CONTROL_PREFIX):
            continue
        window = (point.parameters.resolution_mm, point.parameters.gates)
        if window in seen:
            raise RunPlanError(
                f"{where} acquires {window[0]:g} mm x {window[1]} gates twice "
                f"({seen[window]!r} and {point.label!r}): a job acquires each of its conditions "
                f"once — the design's rows carry one recording per condition ({REFERENCE_DOCUMENT} "
                "§3.3)"
            )
        seen[window] = point.label


def _check_control_window(
    plan: RunPlan, entry: RunPlanJob, point: PlannedPoint
) -> None:
    """A block-local control is the pass's reference window, at its job's own run-wide values."""
    window = (point.parameters.resolution_mm, point.parameters.gates)
    if window != plan.reference_window.as_pair:
        raise RunPlanError(
            f"step {entry.step} ({entry.job!r}) control {point.label!r} asks for "
            f"{window[0]:g} mm x {window[1]} gates where a block-local control is the pass's "
            f"reference window {plan.reference_window.as_pair} "
            f"({REFERENCE_DOCUMENT} §3.2: it repeats the job's own anchor, so it is the reference "
            "spatial window at that job's run-wide burst and emissions values)"
        )


def _check_run_level_job(
    plan: RunPlan, entry: RunPlanJob, points: tuple[PlannedPoint, ...]
) -> None:
    """One run-level observation: the reference window, no controls, and its own emissions level.

    The run-level job is the paired design's unit, so what it must be is narrow: exactly one
    recording, at the window every job of the pass shares, carrying no block-local control (there
    is no within-job comparison for a control to anchor). Its burst and PRF are held to the
    reference's by the plan's own structure check, which is where "emissions only" belongs; this
    function refuses a job that is not an observation of the pass's own reference window, or one
    that is dressed as a scientific job's block.
    """
    where = f"step {entry.step} ({entry.job!r}, {entry.definition})"
    if len(points) != 1:
        raise RunPlanError(
            f"{where} holds {len(points)} point(s) where a run-level job is one observation of "
            "the reference window: a pair compares two levels, and a job that records two windows "
            "would have its pair comparing something else as well"
        )
    point = points[0]
    if point.label.startswith(CONTROL_PREFIX):
        raise RunPlanError(
            f"{where} labels its only point {point.label!r}: a run-level job carries no "
            "block-local control — it *is* the observation, not an anchor for one"
        )
    if (point.parameters.resolution_mm, point.parameters.gates) != (
        plan.reference_window.as_pair
    ):
        raise RunPlanError(
            f"{where} records at {point.parameters.resolution_mm} mm x "
            f"{point.parameters.gates} gates where a run-level job records the pass's reference "
            f"window {plan.reference_window.as_pair}: every pair is a comparison at one window, so "
            "the pass's jobs cannot sit at different ones"
        )


def _check_common_reference_job(
    plan: RunPlan, entry: RunPlanJob, points: tuple[PlannedPoint, ...]
) -> None:
    """A common-reference job is exactly one recording, of the true reference condition."""
    where = f"step {entry.step} ({entry.job!r}, {entry.definition})"
    if entry.condition.as_triple != plan.reference_condition.as_triple:
        raise RunPlanError(
            f"{where} records at burst {entry.condition.burst_length}, emissions "
            f"{entry.condition.emissions_per_profile}, PRF {entry.condition.prf_us:g} us while the "
            "reference condition is "
            f"(burst {plan.reference_condition.burst_length}, emissions "
            f"{plan.reference_condition.emissions_per_profile}, PRF "
            f"{plan.reference_condition.prf_us:g} us): a reference-only job exists to record the "
            "one condition the whole pass is read against, and a run-wide value it cannot write "
            f"makes any other set of values a different condition ({REFERENCE_DOCUMENT} §3.2)"
        )
    if len(points) != 1:
        raise RunPlanError(
            f"{where} holds {len(points)} point(s) where a common-reference job carries one "
            "recording ("
            + REFERENCE_DOCUMENT
            + " §3.2): the four reference-only jobs are four "
            "separate between-job checks, not a block of repeats"
        )
    point = points[0]
    if point.label.startswith(CONTROL_PREFIX):
        raise RunPlanError(
            f"{where} labels its single recording {point.label!r}: a common-reference recording is "
            "not a block-local control — the two are different problems ("
            + REFERENCE_DOCUMENT
            + " §3.2), and they have to stay different in names as well as in rows"
        )
    if (point.parameters.resolution_mm, point.parameters.gates) != (
        plan.reference_window.as_pair
    ):
        raise RunPlanError(
            f"{where} records {point.parameters.resolution_mm:g} mm x "
            f"{point.parameters.gates} gates where the reference condition is "
            f"{plan.reference_window.as_pair}: the reference is the pass's anchor, spatial window "
            "included"
        )


def _check_every_window_is_acquired(
    plan: RunPlan, used: set[tuple[float, int]]
) -> None:
    """Every window the plan declares is a window some scientific row actually acquires."""
    missing = [window.as_pair for window in plan.windows if window.as_pair not in used]
    if missing:
        raise RunPlanError(
            f"the run plan declares windows nothing acquires: {missing}. A declared window is a "
            "condition of the pass, and one no scientific row asks for is a design the encoded "
            "pass does not have — drop it from the plan, or add the row that acquires it"
        )


def _check_block_cap(run: PlannedRun) -> None:
    """The declared cap cannot wrap any point, whatever the achieved period turns out to be."""
    required = run.required_block_cap
    if run.max_profiles_per_block < required:
        raise RunPlanError(
            f"the run plan declares a block cap of {run.max_profiles_per_block} profiles where "
            f"this pass needs at least {required}: the achieved profile period is never shorter "
            "than the programmed emissions x PRF of one profile, so a point can store up to "
            f"ceil({run.duration_s:g} s / (emissions x PRF)) profiles — past the cap the block is a "
            "ring and the stored file silently covers only its last cap x period seconds while "
            f"still decoding as valid ({REFERENCE_DOCUMENT} §4)"
        )


def separates(run: PlannedRun, job: str) -> tuple[str | None, str | None]:
    """The scientific jobs a common-reference job is intended to separate: the ones either side.

    Derived from the plan's order rather than stored, because the order *is* the placement — the
    WP4 rows answer membership, run-wide compatibility, control type and count and deliberately do
    not encode sequence (``existing-sweep-analysis-plan.md`` §10.2), so the placement lives here
    and is read off the sequence that carries it. A scientific job returns ``(None, None)``.
    """
    for index, entry in enumerate(run.jobs):
        if entry.job != job:
            continue
        if entry.kind is not JobKind.COMMON_REFERENCE:
            return (None, None)
        before = next(
            (
                candidate.job
                for candidate in reversed(run.jobs[:index])
                if candidate.kind is JobKind.SCIENTIFIC
            ),
            None,
        )
        after = next(
            (
                candidate.job
                for candidate in run.jobs[index + 1 :]
                if candidate.kind is JobKind.SCIENTIFIC
            ),
            None,
        )
        return (before, after)
    raise RunPlanError(
        f"no job {job!r} in the run plan: it holds {[entry.job for entry in run.jobs]}"
    )


def job_log_path(
    plan: RunPlan | PlannedRun,
    job: RunPlanJob | PlannedJob,
    *,
    store_dir: Path | str | None = None,
) -> Path:
    """Where a job's log lives: ``<store_dir>/<plan>-<job>.jsonl``.

    Derived, never declared, and one log per job on purpose: ``campaign.run_campaign`` proves a
    resume against the manifest beside the log it was given, and a pass whose nine jobs shared one
    log and one manifest could not be resumed at all — the second job's resume would read the first
    job's definition fingerprint and refuse.

    It takes either the plan as written or the pass as checked, because a log's path has to be one
    answer before and during a run: an operator who has read the sheet and the pass that runs it
    must not be looking at two different paths.
    """
    directory = Path(plan.store_dir if store_dir is None else store_dir)
    return directory / f"{plan.plan}-{job.job}.jsonl"


def run_manifest_path(
    plan: RunPlan | PlannedRun, *, store_dir: Path | str | None = None
) -> Path:
    """Where the pass's own record lives: ``<store_dir>/<plan>.run.json``."""
    directory = Path(plan.store_dir if store_dir is None else store_dir)
    return directory / f"{plan.plan}{RUN_MANIFEST_SUFFIX}"


def new_run_manifest(
    run: PlannedRun, *, store_dir: Path | str | None = None, now: datetime | None = None
) -> RunManifest:
    """A pass's record before any of it has run: every job pending, in plan order.

    Written before the first job, not after it: a job that ends the process early then leaves a
    record naming the pass it belonged to, which is what a later session reads to answer "where
    does this stand" without reading nine logs.
    """
    directory = Path(run.store_dir if store_dir is None else store_dir)
    moment = _local_now(now)
    return RunManifest(
        plan=run.plan,
        plan_fingerprint=run.plan_fingerprint,
        channel=run.channel,
        duration_s=run.duration_s,
        analysis_orientation=run.analysis_orientation,
        store_dir=str(directory),
        created_at=moment,
        updated_at=moment,
        jobs=tuple(
            RunJobRecord(
                step=job.step,
                job=job.job,
                kind=job.kind,
                definition=job.definition,
                definition_fingerprint=job.definition_fingerprint,
                condition=job.condition,
                pair=job.pair,
                role=job.role,
                orientation=run.acquisition_orientation(job),
                expected_recordings=job.recordings,
                log=str(job_log_path(run, job, store_dir=directory)),
            )
            for job in run.jobs
        ),
    )


def next_job(run: PlannedRun, manifest: RunManifest) -> PlannedJob | None:
    """The next job the pass has to run, or ``None`` when it is complete.

    The pass's order is the plan's order, and a job is next when every job before it is ok — which
    is the same thing :func:`record_job` enforces from the other side, and the reason a pass cannot
    be run out of order by accident: the runner takes one job at a time and this is what names it.

    The record must answer **this** plan (:func:`_check_record_answers_plan`): a pass's record and
    the plan it was run from are one thing, so an edited point, value or policy is a different run
    whose finished jobs are not this one's.
    """
    _check_record_answers_plan(run, manifest)
    record = manifest.next_record
    if record is None:
        return None
    for job in run.jobs:
        if job.step == record.step:
            return job
    raise RunPlanError(
        f"the run manifest names step {record.step} ({record.job!r}), which is not a step of this "
        f"plan ({[entry.step for entry in run.jobs]}): the record and the plan are not the same "
        "pass"
    )


def _check_record_answers_plan(run: PlannedRun, manifest: RunManifest) -> None:
    """Refuse a record that answers a different plan — by hash, naming both sides.

    The per-job resume already refuses a changed *definition* (``campaign._validate_resume``), and
    this is the run-level half of the same rule: a plan whose job order, windows, values or raised
    facts moved is not the pass whose record stands beside it, and its finished jobs must not read
    as this plan's finished jobs.
    """
    if manifest.plan_fingerprint == run.plan_fingerprint:
        return
    raise RunPlanError(
        f"the run manifest answers plan fingerprint {manifest.plan_fingerprint[:12]}... while this "
        f"plan hashes to {run.plan_fingerprint[:12]}...: a pass and its record have to be the same "
        "pass, and a point, a value or a raised fact that moved makes this a different run. Either "
        "run the plan the record was started from, or start a new pass (a new store directory or a "
        "new plan name) rather than folding two runs into one record"
    )


def record_job(
    manifest: RunManifest,
    run: PlannedRun,
    job: PlannedJob,
    job_manifest: JobManifest,
    *,
    now: datetime | None = None,
) -> RunManifest:
    """Fold one finished job into the pass's record — or refuse a job that is not the next one.

    The refusal is the point. A pass is read as one experiment: its common-reference checks mean
    something only if the jobs between them ran in the planned order, so a job whose predecessors
    are not ok is not recorded as done and is not skipped either — it is refused, by name, with the
    step that stands in front of it. ``--resume`` inside a job is unaffected: this is the
    *cross-job* order, and the two are different problems (``existing-sweep-analysis-plan.md``
    §10.2).

    The row is built from the job's own :class:`~udv_echo_process.acquire.campaign.JobManifest`
    rather than from what the caller says happened, and the manifest's own job name and definition
    fingerprint are checked against the plan's entry, so a row cannot describe a different job's
    log.
    """
    if job_manifest.job != job.job:
        raise RunPlanError(
            f"the manifest reports job {job_manifest.job!r} where the plan's step {job.step} is "
            f"{job.job!r}: a job's manifest is what a row of the pass's record is built from, so "
            "the two cannot differ"
        )
    if job_manifest.fingerprint != job.definition_fingerprint:
        raise RunPlanError(
            f"job {job.job!r}: the manifest's definition fingerprint is "
            f"{job_manifest.fingerprint} where the plan's definition hashes to "
            f"{job.definition_fingerprint} — the manifest beside this log answers a different "
            "definition, so its outcome cannot be recorded as this plan's step"
        )
    _check_record_answers_plan(run, manifest)
    record = manifest.next_record
    if record is None:
        raise RunPlanError(
            f"job {job.job!r} cannot be recorded: the pass is complete "
            f"({manifest.summary})"
        )
    if record.step != job.step:
        raise RunPlanError(
            f"job {job.job!r} is not the next job of this pass: step {record.step} "
            f"({record.job!r}) comes first and is {record.status.value}. The pass's jobs are run "
            "in the plan's order — a common-reference job is a check *between* two scientific jobs "
            f"and means nothing if the job it follows never ran ({REFERENCE_DOCUMENT} §3.2)"
        )

    status = _status_of(job_manifest)
    updated = RunJobRecord(
        step=record.step,
        job=record.job,
        kind=record.kind,
        definition=record.definition,
        definition_fingerprint=record.definition_fingerprint,
        condition=record.condition,
        pair=record.pair,
        role=record.role,
        orientation=record.orientation,
        status=status,
        expected_recordings=record.expected_recordings,
        ok_recordings=job_manifest.ok_count,
        skipped=job_manifest.skipped,
        log=record.log,
        manifest=str(manifest_path_for(Path(record.log))),
        finished_at=job_manifest.finished_at,
        note=_job_note(
            job_manifest,
            status,
            carried_transitions=record.burst_transitions,
            recovered_from_log=_recovered_from_log(
                job_manifest, record.burst_transitions, log_path=record.log
            ),
        ),
        # The boundary's own evidence, carried onto the pass's row so reconstructing the pass
        # offline says which job moved the dialog — and what the application answered. The job
        # manifest's history is authoritative, and whatever this row already carried is merged in
        # rather than dropped: a row rewritten by a resumed job keeps the earlier recording's
        # transitions, oldest first, instead of reporting only the latest write.
        burst_transitions=_accumulated_transitions(
            record.burst_transitions, job_manifest.burst_transitions
        ),
    )
    return manifest.model_copy(
        update={
            "jobs": tuple(
                updated if row.step == record.step else row for row in manifest.jobs
            ),
            "updated_at": _local_now(now),
        }
    )


def _status_of(job_manifest: JobManifest) -> RunJobStatus:
    """How a job ended, from its own manifest: ok only when every planned point is ok."""
    if job_manifest.aborted:
        return (
            RunJobStatus.FAILED if job_manifest.ok_count == 0 else RunJobStatus.PARTIAL
        )
    if job_manifest.failed_count:
        return RunJobStatus.PARTIAL if job_manifest.ok_count else RunJobStatus.FAILED
    if job_manifest.ok_count == job_manifest.planned and job_manifest.planned:
        return RunJobStatus.OK
    return RunJobStatus.FAILED


def _accumulated_transitions(
    carried: tuple[BurstWriteResult, ...], recorded: tuple[BurstWriteResult, ...]
) -> tuple[BurstWriteResult, ...]:
    """A row's burst history: what it already carried, then what the job's own manifest records.

    The two are normally the same list with the newer recording's entries appended, and then the
    manifest's own (the authority) is the answer. They can also arrive as *disjoint* lists — a row
    recorded once and then rewritten by a job whose manifest was produced by a fresh invocation that
    did not accumulate — and neither may be dropped, because both are verified transitions this job's
    boundary spent. Merging keeps the earlier entries first (the order is the record) and never
    duplicates: a manifest that already extends what the row carried is returned unchanged.

    **The manifest's list may now hold entries recovered from the job's own log.** A job manifest is
    written at the end of an invocation, so one refused after its verified write records the
    transition only in the log; the next invocation folds it in
    (``campaign.reconciled_burst_history``, ``docs/dop3000/failed-invocation-provenance.md`` §5.3),
    and the manifest this row is built from then carries an occurrence no invocation that wrote
    *this* row performed. Nothing here has to change for that: the prefix test compares full
    results **in sequence**, one occurrence per entry, so a recovered entry is kept as its own
    entry and never collapsed into an identical one — which is the property that matters, because
    two identical ``10 -> 18`` transitions are two events.
    """
    if recorded[: len(carried)] == carried:
        return recorded
    return (*carried, *recorded)


def _precedes(moment: datetime, other: datetime | None) -> bool:
    """True only when ``moment`` is *known* to precede ``other``.

    A moment the manifest does not carry, or a pair that cannot be compared at all (a naive
    timestamp beside an aware one — a manifest written by something other than this module), answers
    ``False``: the caller's sentence then keeps its narrower claim instead of a guess.
    """
    if other is None:
        return False
    try:
        return moment < other
    except TypeError:
        return False


def _recovered_from_log(
    job_manifest: JobManifest,
    carried: tuple[BurstWriteResult, ...],
    *,
    log_path: str | None,
) -> int:
    """How many of the manifest's entries beyond the row's own history the job's log records.

    Almost every entry the manifest carries beyond what this row already carried was this
    recording's own verified write — but not all of them. An entry the job's boundary appended to
    the log in an *earlier* invocation that was then refused wrote no manifest of its own, so it
    reaches this manifest only through the log (``campaign.reconciled_burst_history``), and the
    sentence in :func:`_job_note` must not call it "added by this recording".

    The count is by **occurrence**, using the same rule the accumulation uses: the row's own history
    is consumed against the log first, then the entries beyond it, one log entry per manifest entry,
    in sequence, by full result equality — never by a key derived from a transition's content, so a
    repeated identical transition is not collapsed. An occurrence counts only when the log records
    it as having happened **before this invocation** (``occurred_at`` earlier than the manifest's own
    ``started_at``): an entry the log holds with a later stamp is this recording's own write, and the
    timestamp is the only thing that tells the two apart. ``0`` when the manifest names no readable
    log — a missing one, or a manifest that predates the log — so the older, narrower sentence is
    kept rather than a claim nothing supports.
    """
    history = job_manifest.burst_transitions
    if history[: len(carried)] != carried:
        return 0
    beyond = history[len(carried) :]
    source = job_manifest.log_path or log_path
    if not beyond or source is None:
        return 0
    path = Path(source)
    if not path.is_file():
        return 0
    earlier = [
        mutation.transition
        for mutation in burst_mutations(read_entries(path))
        if _precedes(mutation.occurred_at, job_manifest.started_at)
    ]
    # What the row's own history does not account for, in the log's order — the same leftovers the
    # accumulation keeps, so the two agree on which occurrences are still unclaimed.
    leftover = reconciled_burst_history(carried, tuple(earlier))[len(carried) :]
    recovered = 0
    position = 0
    for transition in beyond:
        scan = position
        while scan < len(leftover) and leftover[scan] != transition:
            scan += 1
        if scan < len(leftover):
            position = scan + 1
            recovered += 1
    return recovered


def _transition_text(transition: BurstWriteResult) -> str:
    """One transition as ``before -> requested (state)``, ``?`` for an unread starting row.

    The state travels with the entry for the same reason it does on the job manifest: a reader must
    see that the write was a *verified* one (only verified transitions reach a manifest) rather than
    take the note's word for it.
    """
    before = "?" if transition.before_burst is None else transition.before_burst.text
    return f"{before} → {transition.requested_burst} ({transition.state.value})"


def _job_note(
    job_manifest: JobManifest,
    status: RunJobStatus,
    *,
    carried_transitions: tuple[BurstWriteResult, ...] = (),
    recovered_from_log: int = 0,
) -> str | None:
    """The job's own summary on the pass's row, plus what a reader must not have to derive."""
    parts = [job_manifest.summary]
    if job_manifest.declared_only:
        parts.append(
            "declared only: no instrument reading was taken and nothing was compiled for this job"
        )
    transitions = job_manifest.burst_transitions
    if transitions:
        # The phrase matters: the row carries a **history** the job has accumulated across its
        # invocations, not a report of the one that wrote this row. The entries this recording added
        # are named separately, so a resume that inherited the earlier transitions and wrote nothing
        # new cannot read as if it had transitioned anything.
        added = max(len(transitions) - len(carried_transitions), 0)
        if added and recovered_from_log:
            # The third case (§5.3): a transition an *earlier* invocation appended to the job's log
            # and was then refused on reaches this manifest through the log alone, so "added by this
            # recording" would be false for it. The sentence names the source instead of the writer.
            parts.append(
                f"burst transitions (accumulated history, oldest first): "
                f"{', '.join(_transition_text(transition) for transition in transitions)}"
                f"; {added} beyond this row's own history, of which {recovered_from_log} recorded "
                "by the job's log alone (an invocation refused after its verified write records "
                "the transition there, and no manifest of its own)"
            )
        else:
            parts.append(
                f"burst transitions (accumulated history, oldest first): "
                f"{', '.join(_transition_text(transition) for transition in transitions)}"
                + (
                    f"; {added} added by this recording"
                    if added
                    else "; none added by this recording (carried from earlier invocations)"
                )
            )
    if status is not RunJobStatus.OK:
        failed = [
            outcome.label or outcome.identity
            for outcome in job_manifest.outcomes
            if not outcome.ok
        ]
        if failed:
            parts.append("not ok: " + ", ".join(failed))
    return "; ".join(part for part in parts if part)


def read_run_manifest(path: Path) -> RunManifest:
    """Read a pass's record back; a malformed one is a :class:`RunPlanError` naming the file."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunPlanError(
            f"{source}: the run manifest could not be read ({exc})"
        ) from exc
    try:
        return RunManifest.model_validate_json(text)
    except ValidationError as exc:
        raise RunPlanError(f"{source}: not a run manifest: {_explain(exc)}") from exc


def write_run_manifest(path: Path, manifest: RunManifest) -> None:
    """Write a pass's record as JSON, creating the directory it lands in."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def job_requirements(run: PlannedRun, job: PlannedJob) -> tuple[str, ...]:
    """The run-wide setup one job needs, as lines an operator acts on — the sheet's per-job block.

    One function for the sheet and for the live path (``udv-acquire run-plan --next``), because a
    hint printed before a run and a hint written on a sheet have to be the same text: two copies
    would drift, and the one that drifted would be the one the operator read.
    """
    before, after = separates(run, job.job)
    lines = [
        (
            f"run-wide   : burst_length {job.condition.burst_length}, emissions_per_profile "
            f"{job.condition.emissions_per_profile}, prf_us {job.condition.prf_us:g}"
        )
    ]
    for fact in ("burst_length", "emissions_per_profile", "prf_us"):
        lines.append(
            f"                {fact}: "
            f"{_readability(fact, strict=fact in run.strict_facts)}"
        )
    if before or after:
        lines.append(
            f"placement  : the reference check between {before!r} and {after!r}"
        )
    if job.pair is not None:
        partner = next(
            (
                candidate
                for candidate in run.jobs
                if candidate.pair == job.pair and candidate.step != job.step
            ),
            None,
        )
        lines.append(
            f"pair       : {job.pair}, "
            f"{job.role.value if job.role else 'unstated'} of 2 — set emissions_per_profile "
            f"{job.condition.emissions_per_profile} for this job"
            + (
                ""
                if partner is None
                else f"; its partner is {partner.job!r} at "
                f"{partner.condition.emissions_per_profile}"
            )
        )
        lines.append(
            f"                acquisition orientation {run.acquisition_orientation(job)}; "
            f"analysis orientation {ANALYSIS_ORIENTATION} for every pair, whatever its order"
        )
    return tuple(lines)


def operator_setup_sheet(run: PlannedRun) -> str:
    """The sheet an operator works from — one block per job, in the pass's order.

    It exists because the two facts that define each job — its burst length and its emissions per
    profile — are **run-wide** and cannot be written by a point (``actuator.DIALOG_ONLY_PARAMETERS``),
    so a pass of nine jobs is nine manual setups between which the automation must not move
    anything. The sheet states, per job, exactly what to set, what the compile will read back, and
    what it will do when the two disagree; and it names the settings of the pass that **no reader
    in this repository reaches**, so the operator's checklist is complete rather than merely
    convenient.

    It is text, and deliberately so: it is read at the machine, it is copied into a session record,
    and a sheet that were a data structure would need a reader for the person it is written for.
    """
    lines: list[str] = []
    lines.append(f"run plan    : {run.plan}")
    #: The plan's own directory, rendered repo-style: the sheet is copied into session records and
    #: compared as an artefact, so a backslash on Windows and a slash elsewhere would be two sheets
    #: for one pass.
    directory = Path(run.directory).as_posix()
    lines.append(f"directory   : {directory}")
    counted = [
        (len(run.scientific_jobs), "scientific"),
        (len(run.common_reference_jobs), "common-reference"),
        (len(run.run_level_jobs), "run-level"),
    ]
    lines.append(
        f"jobs        : {len(run.jobs)} "
        f"({', '.join(f'{count} {name}' for count, name in counted if count)}), "
        f"{run.recordings} recording(s)"
    )
    lines.append(
        f"fixed frame : sound speed {run.sound_speed_ms} m/s, first gate "
        f"{run.first_gate_mm} mm (both dialog-only — set by hand; a disagreement refuses)"
    )
    lines.append(
        f"window      : {run.duration_s:g} s per recording; "
        f"store {Path(run.store_dir).as_posix()}; names "
        f"{run.name_prefix}-<job>-<label>-<stamp>"
    )
    lines.append(
        f"block cap   : at least {run.max_profiles_per_block} profiles — the pass's own "
        "requirement (the active cap is an application preference no reader here reaches; "
        "confirm it by hand and record what it says)"
    )
    if run.strict_facts:
        lines.append(
            f"raised facts: {list(run.strict_facts)} — a disagreement on any of them refuses "
            "before the first recording, and the stored file's own word must agree as well"
        )
    else:
        lines.append(
            "raised facts: none — every fixed fact of this pass keeps the acceptance of the "
            "stored-file verifier's own table"
        )
    if run.run_level_jobs:
        lines.append(
            f"pairs       : {len(run.pairs)} counterbalanced pairs — "
            + ", ".join(
                f"{group[0].pair}: {run.acquisition_orientation(group[0])}"
                for group in run.pairs
            )
        )
        lines.append(
            f"              each pair is read {ANALYSIS_ORIENTATION} whatever order it was "
            "recorded in; the order is the counterbalancing, not the comparison's sign"
        )
    lines.append("")
    for job in run.jobs:
        lines.append(
            f"--- step {job.step} of {len(run.jobs)}: {job.job} [{job.kind.value}] ---"
        )
        lines.append(f"    definition : {directory}/{job.definition}")
        # Displayed, not used: the sheet is committed to a repository and read on other machines,
        # so it renders separators repo-style, while the path the recorder opens stays the native
        # one (the record's own ``log`` field, and ``job_log_path`` itself).
        lines.append(f"    log        : {job_log_path(run, job).as_posix()}")
        for line in job_requirements(run, job):
            lines.append(f"    {line}")
        lines.append("    points     :")
        for point in job.points:
            note = "" if point.note is None else f"  NOTE {point.note}"
            lines.append(
                f"        {point.key:>2}. {point.label:<12} {point.identity:<32} "
                f"{point.parameters.resolution_text} mm x {point.parameters.gates} gates  "
                f"({point.profiles} profiles){note}"
            )
        lines.append("")
    lines.append(
        f"the pass holds fixed, with no reader here ({REFERENCE_DOCUMENT} §1):"
    )
    for name, value in MANUAL_SETTINGS:
        lines.append(f"    {name}: {value}")
    lines.append(
        "                none of these is machine-verifiable: no reader in this repository reaches "
        "them, so the pass is enforced by the compile only where a reader exists (the run-wide "
        "burst, emissions and PRF above) and by the operator everywhere else"
    )
    lines.append(
        "                confirm every one of them ONCE at the start of the campaign, record what "
        'the application says, and do not touch any of them between jobs: "the same settings '
        'except emissions" is a property of the sitting, not of the files'
    )
    return "\n".join(lines)


def _readability(fact: str, *, strict: bool = False) -> str:
    """What the compile does with one run-wide fact — read or not, refused or advised.

    Read from the two tables that decide it rather than restated: the facts a reader reaches are
    ``snapshot.SUPPORTED_READ_FACTS``, what a disagreement does is
    ``campaign.COVARIATE_ACCEPTANCE``, and which *surface* states a readable fact is the third
    table, ``snapshot``'s own module docstring (the PRF period and the emissions per profile come
    off the measurement screen's column; the burst length, the sound speed and the first gate out of
    the ``Operating parameters`` dialog).

    ``strict`` is the pass's own policy (:attr:`RunPlan.strict_facts`): a fact the pass raises is
    refused before the first recording **and** enforced in the stored file's own word, and the
    sentence says both halves. A sheet that read an advisory fact as one the run will stop for, or a
    raised fact as one it will merely note, would be wrong in the direction that costs a job.

    ``burst_length`` is the one **written** fact and gets its own sentence: since B5 the run
    transitions it through the ``Operating parameters`` dialog at the job boundary
    (``campaign._transit_burst_length``), so a sheet that still told the operator to prepare it by
    hand — or that read a disagreement as a refusal — would be describing a run this repository no
    longer performs. The transition is *not* the whole check: the compile still reconciles the
    definition against the state the write established, and the sentence names both halves. The
    raise, where a pass declares one, is unchanged: it lands on the stored file's own word. The
    surface lookup sits *after* the reader check, so a fact no reader reaches is described as one no
    reader reaches whatever its name.
    """
    if fact not in SUPPORTED_READ_FACTS:
        return (
            "no reader in this repository reaches it — confirm it on the screen by hand"
        )
    if fact == "burst_length":
        surface = _FACT_SURFACE.get(fact, "the Operating parameters dialog")
        written = (
            f"read from {surface}; the run transitions it at the job boundary when the job's "
            "burst differs from the instrument's — written, read back from a re-opened dialog "
            "and then compiled against (write → verify → compile); a transition that does not "
            "verify refuses before the first recording, and the compile that follows refuses on "
            "any disagreement it finds"
        )
        if strict:
            return (
                written
                + ", and this pass raises it to a refusal: the stored file's own word has to "
                "agree as well"
            )
        return written
    surface = _FACT_SURFACE.get(fact, "the measurement screen")
    acceptance = COVARIATE_ACCEPTANCE[fact].value
    if strict:
        return (
            f"read from {surface}; this pass raises it to a refusal, so a disagreement stops the "
            "job before the first recording and the stored file's own word has to agree as well "
            f"(the verifier's own default for it is {acceptance!r})"
        )
    if acceptance == "refuse":
        return f"read from {surface}; a disagreement refuses before the first recording"
    return (
        f"read from {surface}; a disagreement is recorded as an advisory and the run proceeds "
        f"({fact} is advisory to the stored-file verifier — confirm it on the screen by hand "
        "before recording)"
    )


def _local_now(moment: datetime | None) -> datetime:
    """Now in local time; a supplied moment wins, so a record is reproducible in tests."""
    return datetime.now(tz=UTC).astimezone() if moment is None else moment


def _explain(exc: ValidationError) -> str:
    """One line per invalid field, in the campaign loader's own voice."""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
