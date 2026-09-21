"""The Stage-2 paired analysis: four counterbalanced E64 - E20 contrasts from one campaign.

Section 4b of [`docs/dop3000/sparse-pass-analysis-plan.md`](../../../docs/dop3000/sparse-pass-analysis-plan.md)
names one acquisition and this is its analysis. Eight run-level jobs, four counterbalanced
pairs, emissions per profile the only varying run-wide setting, all of it inside one campaign:

```text
E20-A  E64-A      E64-B  E20-B      E20-C  E64-C      E64-D  E20-D
```

The published quantity is the **paired contrast**: for each pair, its emissions-64 recording
minus its emissions-20 recording, **oriented E64 minus E20 whatever order the pair was
acquired in**, with the pair's acquisition orientation recorded beside it. The orientation is
retained, not discarded, and it is what makes the two orders comparable: read the raw
acquisition-order difference instead, and the counterbalancing turns into a sign error on half
the pairs.

**The screening floor is this campaign's own.** The cheaper design — three new emissions-64
runs compared against the earlier pass's four emissions-20 runs — would have mixed the
emissions question with session drift, because those two sets were measured in different
campaigns. Here the variation a contrast is screened against is measured *inside* the campaign,
by the same endpoint WP2 used on the reference runs:

- a **level floor** is the largest absolute window-mean difference over the **six unique run
  pairs** of that level's four runs, taken depth-resolved (per gate, over the common support)
  and depth-averaged (the runs' own scalar reduction);
- the **screening floor** for a paired contrast is the **larger** of the two levels' floors —
  the conservative reading, since a pair's difference carries both members' run-to-run
  variation;
- the earlier pass's published floors (**4.235 mm/s** depth-averaged, **14.603 mm/s**
  depth-resolved, over `sparse-mixer-live-1`) are carried here as **context only**. They are
  never the screen and no verdict below reads them: they belong to another sitting.

**The acceptance criterion has exactly two allowed outcomes** (section 4b, stated in advance):

- a **resolved difference** — the four paired contrasts consistently larger than the
  contemporaneous variation *and* in a consistent direction; or
- an **unresolved overlap** — the separation comparable to or smaller than that variation,
  which is itself the answer and ends the question.

Inside the overlap the vocabulary keeps two different findings apart: **not detected** (the
contrasts sit inside the campaign's own variation — nothing at this design's resolving power)
and **not resolvable with this design** (the contrasts reach past the floor on some pairs but
not consistently, or disagree in direction — a separation the campaign's variation still
covers). Neither is a claim that no effect exists.

The same two rules are applied depth-resolved against the depth-resolved floor and
depth-averaged against the depth-averaged one, and the two are never mixed: a depth-averaged
verdict says nothing about a single gate, and a gate says nothing about the average.

Nothing here changes acquisition, the frozen WP0 ingest, or any earlier slice's artefacts. The
frozen decision table's E64-vs-E20 row is *reported against*, not rewritten: `pairs.md` states
what this campaign's outcome does to it and leaves the row itself where it was published.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.analysis._sparse_pass import (
    PassDecoding,
    decode_pass,
    gate_statistics,
    supported_mean_of,
)
from udv_echo_process.analysis.sparse_inventory import (
    DecodedPoint,
    SparseIngestError,
)
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.provenance.models import current_revision

# ── the pass, and what this slice insists on ───────────────────────────

DATASET_ROOT = Path("data/stage2-e20-e64")
PLAN_PATH = Path("examples/stage2-e20-e64/run-plan.json")
PLAN_NAME = "stage2-e20-e64"
REPORT_DIR = Path("reports/stage2-e20-e64")

#: Every job of this pass is one kind: the paired pass's run-level job.
RUN_KIND = "run-level"
EXPECTED_RUNS = 8
EXPECTED_PAIRS = 4
RUNS_PER_LEVEL = 4
UNIQUE_RUN_PAIRS = 6  # C(4, 2): what one level's four runs contribute

LEVEL_ORDER: tuple[str, ...] = ("E20", "E64")
LEVEL_EMISSIONS: dict[str, int] = {"E20": 20, "E64": 64}
EMISSIONS_LEVEL: dict[int, str] = {20: "E20", 64: "E64"}

#: The orientation the plan must state, and the value every pair is read at.
STATED_ORIENTATION = "E64 - E20"

ROLE_LEAD = "lead"
ROLE_FOLLOW = "follow"

#: The plan's declared reference window, and the designed exposure it is measured over.
REFERENCE_WINDOW = (1.85, 50)
DESIGNED_WINDOW_S = 12.0
DESIGNED_REVOLUTIONS = 100

FLOOR_STATISTIC = "mean"
TOLERANCE = 1e-9

#: The fields the eight runs must share, with the prose name a refusal uses. Emissions is
#: deliberately absent: it is this pass's one varying setting, and it is checked on its own.
FRAME_FIELDS: tuple[tuple[str, str], ...] = (
    ("n_gates", "gates"),
    ("resolution_mm", "resolution"),
    ("gate1_mm", "first gate"),
    ("max_depth_mm", "max depth"),
    ("sound_speed_ms", "sound speed"),
    ("pulse_repetition_freq_hz", "PRF"),
    ("burst_length", "burst length"),
    ("emit_power", "emit power"),
    ("sensitivity", "sensitivity"),
    ("tgc_mode", "TGC mode"),
    ("tgc_start_db", "TGC start"),
    ("tgc_end_db", "TGC end"),
    ("skipped_profiles", "skipped profiles"),
    ("doppler_angle_deg", "Doppler angle"),
    ("source_freq_khz", "source frequency"),
    ("velo_max_ms", "velocity scale"),
    ("module_scale", "module scale"),
    ("wall_filter", "wall filter"),
    ("sampling_volume_mm", "sampling volume"),
    ("trigger_delay_ms", "trigger delay"),
    ("trigger_state", "trigger state"),
)

# ── the outcome vocabulary ─────────────────────────────────────────────

OUTCOME_RESOLVED = "resolved difference"
OUTCOME_OVERLAP = "unresolved overlap"
OVERLAP_NOT_DETECTED = "not detected"
OVERLAP_NOT_RESOLVABLE = "not resolvable with this design"

# ── the prior context, named with its dataset and never used as a screen ─

PRIOR_DATASET = "sparse-mixer-live-1"
PRIOR_DEPTH_AVERAGED_FLOOR_MM_S = 4.235
PRIOR_DEPTH_RESOLVED_FLOOR_MM_S = 14.603

PRIOR_CONTEXT_NOTE = (
    f"quotations of the earlier pass ({PRIOR_DATASET})'s published between-run floors, carried "
    "as context only: that pass measured emissions 20 and emissions 64 in different campaigns, "
    "which is exactly the confounding this campaign was acquired to avoid, so its floors are "
    "not the screen for any contrast here"
)

# ── artefacts ──────────────────────────────────────────────────────────

CSV_NAME = "pairs.csv"
DOC_NAME = "pairs.json"
MD_NAME = "pairs.md"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "pairs.png"
FIGURE_DPI = 150

FLOOR_ENDPOINT = (
    "the largest absolute per-depth window-mean difference over the common support, taken over "
    "the six unique run pairs of one level's four runs of this campaign: one endpoint of the "
    "contemporaneous variation a depth-resolved comparison is screened against"
)

AVERAGED_ENDPOINT = (
    "the largest absolute difference between one level's four runs' depth-averaged window "
    "means, taken over the same six unique run pairs: the same reduction the earlier pass's "
    "floors used, so the depth-averaged and depth-resolved screens are compared like for like"
)

DEFINITIONS: dict[str, str] = {
    "pair": "the design's pair letter (A-D); the campaign's four pairs are its four contrasts",
    "acquisition_orientation": (
        "the order the pair was actually acquired in, retained beside its contrast: '20 -> 64' "
        "or '64 -> 20'"
    ),
    "oriented_mm_s": (
        "the published paired contrast: this pair's emissions-64 depth-averaged window mean "
        "minus its emissions-20 one, oriented E64 - E20 whatever order the pair was acquired in"
    ),
    "order_difference_mm_s": (
        "the raw acquisition-order difference (the follow-up run minus the lead run). It equals "
        "oriented_mm_s on a '20 -> 64' pair and its negative on a '64 -> 20' one: a "
        "counterbalance read without the orientation is a sign error on half the pairs"
    ),
    "max_abs_mm_s": "the largest absolute depth-resolved (per-gate) contrast of this pair",
    "run.depth_averaged_mean_mm_s": (
        "the run's unweighted mean of the per-gate window means over the supported gates: the "
        "same reduction the frozen table's supported cells use"
    ),
    "screening_floor_mm_s": (
        "the larger of the two within-level depth-averaged floors measured in this campaign's "
        "own eight runs, each the largest absolute difference over that level's six unique run "
        "pairs. It is this campaign's contemporaneous variation, not the earlier pass's floor"
    ),
    "depth_resolved_floor_mm_s": (
        "the larger of the two within-level depth-resolved floors measured in this campaign's "
        "own eight runs, taken per gate over the common support, at the depth stated"
    ),
    "outcome": (
        "one of exactly two: 'resolved difference' (the four contrasts consistently larger than "
        "the contemporaneous variation with a consistent direction) or 'unresolved overlap' "
        "(the separation comparable to or smaller than it)"
    ),
    "overlap_kind": (
        "'not detected' (every contrast inside the campaign's own variation) or 'not resolvable "
        "with this design' (the contrasts reach past the floor on some pairs but not "
        "consistently, or disagree in direction); null when the outcome is resolved"
    ),
    "depth_resolved_reading": (
        "the same two rules applied per gate against the depth-resolved floor, reduced to the "
        "strongest depth-resolved separation per pair; never mixed with the depth-averaged "
        "verdict"
    ),
}

CSV_COLUMNS: tuple[str, ...] = (
    "kind",
    "pair",
    "job",
    "step",
    "role",
    "level",
    "emissions_per_profile",
    "acquisition_orientation",
    "value_name",
    "value",
    "unit",
)

UNIT_MM_S = "mm/s"
UNIT_COUNT = "count"


class Stage2PairsError(SparseIngestError):
    """A refusal of this slice: the campaign is not the design this analysis reads."""


# ── the models ─────────────────────────────────────────────────────────


class RunValue(ValueModel):
    """One run of the campaign, kept as its own measurement."""

    label: str
    job: str
    step: int
    pair: str
    role: str
    level: str
    emissions: int
    kind: str
    relative_path: str
    gates: int
    resolution_mm: float
    supported_gates: int
    sound_speed_ms: float
    prf_us: float
    burst_length: int
    depth_mm: float
    first_gate_mm: float
    depth_averaged_mean_mm_s: float
    started_at: str
    finished_at: str


class ContrastValue(ValueModel):
    """One pair's published contrast, with the orientation it was read at."""

    pair: str
    acquisition_orientation: str
    e20_job: str
    e64_job: str
    lead_job: str
    follow_job: str
    order_difference_mm_s: float
    oriented_mm_s: float
    rms_mm_s: float
    max_abs_mm_s: float
    max_abs_depth_mm: float
    exceeds_floor: bool


class LevelFloorValue(ValueModel):
    """One level's within-campaign run-to-run variation, as two named endpoints."""

    level: str
    emissions: int
    jobs: tuple[str, ...]
    runs_pooled: int
    unique_pairs: int
    depth_averaged_mm_s: float
    depth_averaged_pair: tuple[str, str]
    depth_resolved_mm_s: float
    depth_resolved_depth_mm: float
    depth_resolved_pair: tuple[str, str]


class Verdict(ValueModel):
    """The two-outcome judgement of one screening, with the numbers that produced it."""

    outcome: str
    overlap_kind: str | None
    consistent_direction: bool
    all_contrasts_exceed_floor: bool
    exceeding: int
    count: int
    min_abs_mm_s: float
    max_abs_mm_s: float
    mean_mm_s: float
    range_mm_s: float
    floor_mm_s: float

    @property
    def resolved(self) -> bool:
        """True only for a resolved difference."""
        return self.outcome == OUTCOME_RESOLVED


class ContrastProfiles(ArrayModel):
    """The eight runs' window-mean profiles and the four contrasts, on the common support."""

    depths_mm: array_field(np.float64, rank=1)
    e20_a: array_field(np.float64, rank=1)
    e64_a: array_field(np.float64, rank=1)
    e64_b: array_field(np.float64, rank=1)
    e20_b: array_field(np.float64, rank=1)
    e20_c: array_field(np.float64, rank=1)
    e64_c: array_field(np.float64, rank=1)
    e64_d: array_field(np.float64, rank=1)
    e20_d: array_field(np.float64, rank=1)
    contrast_a: array_field(np.float64, rank=1)
    contrast_b: array_field(np.float64, rank=1)
    contrast_c: array_field(np.float64, rank=1)
    contrast_d: array_field(np.float64, rank=1)

    def run(self, job: str) -> np.ndarray:
        """One run's profile by job name."""
        name = job.replace("-", "_")
        if not hasattr(self, name):
            raise Stage2PairsError(f"no profile is published for job {job!r}")
        return getattr(self, name)

    def contrast(self, pair: str) -> np.ndarray:
        """One pair's contrast profile by pair letter."""
        name = f"contrast_{pair.lower()}"
        if not hasattr(self, name):
            raise Stage2PairsError(f"no contrast profile is published for pair {pair!r}")
        return getattr(self, name)


class Stage2Pairs(ValueModel):
    """The campaign's paired contrasts and the contemporaneous variation they read."""

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    analysis_commit: str
    channel: int
    duration_s: float
    window_s: float
    window_revolutions: int
    support_min_mm: float
    support_max_mm: float
    reference_resolution_mm: float
    reference_gates: int
    runs: tuple[RunValue, ...]
    contrasts: tuple[ContrastValue, ...]
    floors: tuple[LevelFloorValue, ...]
    screening_floor_mm_s: float
    screening_floor_level: str
    screening_floor_source: str
    depth_resolved_floor_mm_s: float
    depth_resolved_floor_depth_mm: float
    depth_resolved_floor_level: str
    depth_resolved_floor_source: str
    stated_orientation: str
    scalar: Verdict
    depth_resolved: Verdict
    depth_resolved_resolved_share: float
    prior_context: dict[str, dict[str, float]]
    prior_context_note: str
    floor_statistic: str
    floor_endpoint: str
    averaged_endpoint: str
    profiles: ContrastProfiles
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every gate check of this slice holds."""
        return all(self.checks.values())

    @property
    def outcome(self) -> str:
        """The depth-averaged outcome — one of exactly two."""
        return self.scalar.outcome

    @property
    def depth_resolved_outcome(self) -> str:
        """The depth-resolved outcome — the same two, read per gate."""
        return self.depth_resolved.outcome

    @property
    def overlap_kind(self) -> str | None:
        """The finding inside an unresolved overlap, or ``None`` when resolved."""
        return self.scalar.overlap_kind

    @property
    def consistent_direction(self) -> bool:
        """True when the four contrasts share one sign."""
        return self.scalar.consistent_direction

    @property
    def all_contrasts_exceed_floor(self) -> bool:
        """True when every one of the four contrasts is larger than the screening floor."""
        return self.scalar.all_contrasts_exceed_floor

    @property
    def frame_fields_checked(self) -> int:
        """How many decoded settings the frame gate compared across the eight runs."""
        return len(FRAME_FIELDS)


# ── the two-outcome rule, implemented once ─────────────────────────────


def decide(oriented: np.ndarray, floor_mm_s: float, tolerance: float) -> Verdict:
    """Judge ``oriented`` against one floor: a resolved difference, or an unresolved overlap.

    The rule is stated in advance by the design and is the whole of the decision:

    - **consistent direction** — every contrast that is not zero to ``tolerance`` carries the
      same sign;
    - **all above the floor** — every contrast is larger in absolute value than the floor;
    - a **resolved difference** requires both. Anything else is an **unresolved overlap**, and
      its kind keeps two findings apart: ``not detected`` when the largest contrast is still
      inside the floor, ``not resolvable with this design`` when it is not.
    """
    values = np.asarray(oriented, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise Stage2PairsError(
            f"decide() reads a 1-D vector of contrasts, got shape {values.shape}"
        )
    if not bool(np.all(np.isfinite(values))):
        raise Stage2PairsError(f"decide() refuses a non-finite contrast: {values.tolist()}")
    if not floor_mm_s > 0.0:
        raise Stage2PairsError(f"the screening floor must be positive, got {floor_mm_s!r}")
    signs = {float(np.sign(value)) for value in values if abs(value) > tolerance}
    consistent = len(signs) <= 1
    exceeding = int(np.sum(np.abs(values) > floor_mm_s))
    all_exceed = exceeding == values.size
    if consistent and all_exceed:
        outcome: str = OUTCOME_RESOLVED
        kind: str | None = None
    else:
        outcome = OUTCOME_OVERLAP
        kind = (
            OVERLAP_NOT_DETECTED
            if float(np.max(np.abs(values))) <= floor_mm_s
            else OVERLAP_NOT_RESOLVABLE
        )
    return Verdict(
        outcome=outcome,
        overlap_kind=kind,
        consistent_direction=consistent,
        all_contrasts_exceed_floor=all_exceed,
        exceeding=exceeding,
        count=int(values.size),
        min_abs_mm_s=float(np.min(np.abs(values))),
        max_abs_mm_s=float(np.max(np.abs(values))),
        mean_mm_s=float(np.mean(values)),
        range_mm_s=float(np.max(values) - np.min(values)),
        floor_mm_s=float(floor_mm_s),
    )


def oriented_contrast(*, e20_block: np.ndarray, e64_block: np.ndarray) -> np.ndarray:
    """The published contrast: E64 minus E20, whatever order the pair was acquired in."""
    return np.asarray(e64_block, dtype=float) - np.asarray(e20_block, dtype=float)


def order_difference(*, lead: np.ndarray, follow: np.ndarray) -> np.ndarray:
    """The raw acquisition-order difference: the follow-up run minus the lead run."""
    return np.asarray(follow, dtype=float) - np.asarray(lead, dtype=float)


# ── reading the campaign ───────────────────────────────────────────────


class _Run(NamedTuple):
    """One decoded run, reduced to the two views the contrasts are taken on."""

    point: DecodedPoint
    job: str
    step: int
    pair: str
    role: str
    level: str
    label: str
    emissions: int
    started_at: str
    finished_at: str
    scalar: float
    block: np.ndarray


class _Campaign(NamedTuple):
    """The eight runs and the shared views, or the refusal that stopped the reading."""

    decoded: PassDecoding
    runs: tuple[_Run, ...]
    native_depths: np.ndarray
    depths: np.ndarray
    support_mm: tuple[float, float]
    window_s: float


def _plan_jobs(decoded: PassDecoding) -> dict[str, object]:
    """The plan's own job objects by name — the authority for what a job *is*."""
    return {str(job.job): job for job in decoded.plan.jobs}  # type: ignore[attr-defined]


def _recorded_jobs(decoded: PassDecoding) -> dict[str, dict[str, object]]:
    """The pass record's own rows by job name — the provenance of each job."""
    rows = decoded.run.get("jobs")
    if not isinstance(rows, list):
        raise Stage2PairsError(
            "the pass record holds no jobs list, so pair membership has no provenance"
        )
    return {str(row.get("job")): dict(row) for row in rows if isinstance(row, dict)}


def _level_of(job: str, emissions: object) -> str:
    """The level a job's declared emissions names, or a refusal naming the job."""
    try:
        value = int(emissions)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise Stage2PairsError(
            f"job {job!r}: its declared emissions_per_profile is {emissions!r}, not a number"
        ) from exc
    level = EMISSIONS_LEVEL.get(value)
    if level is None:
        raise Stage2PairsError(
            f"job {job!r}: its declared emissions_per_profile is {value}, which is not a level "
            f"of this pass ({sorted(EMISSIONS_LEVEL.values())})"
        )
    return level


def _support_mask(depths: np.ndarray, support_mm: tuple[float, float]) -> np.ndarray:
    """The native gates inside the common physical support."""
    low, high = support_mm
    return (np.asarray(depths, dtype=float) >= low) & (np.asarray(depths, dtype=float) <= high)


def _campaign(decoded: PassDecoding) -> _Campaign:
    """The campaign's eight runs, or a refusal naming what disagrees.

    Every gate here is about *what the campaign is*, never about what it shows: the plan's
    stated orientation, eight run-level recordings, four pairs of one run of each level whose
    lead ran first, the stored emissions word against its own declaration, the shared frame,
    and one native gate grid on the common support.
    """
    orientation = str(getattr(decoded.plan, "analysis_orientation", "") or "")
    if orientation != STATED_ORIENTATION:
        raise Stage2PairsError(
            f"the plan states analysis orientation {orientation or None!r}, not "
            f"{STATED_ORIENTATION!r}: every pair of this pass is read E64 minus E20, and an "
            "orientation that disagreed would silently reverse half the contrasts"
        )
    if (
        abs(decoded.window_s - DESIGNED_WINDOW_S) > TOLERANCE
        or decoded.window_revolutions != DESIGNED_REVOLUTIONS
    ):
        raise Stage2PairsError(
            f"the shared primary window is {decoded.window_s} s "
            f"({decoded.window_revolutions} revolutions), not the designed "
            f"{DESIGNED_WINDOW_S} s / {DESIGNED_REVOLUTIONS} revolutions: the contrasts are "
            "only comparable with the campaign's own floors if they cut the same interval"
        )

    points = tuple(point for point in decoded.points if point.binding.job.kind == RUN_KIND)
    if len(points) != EXPECTED_RUNS:
        raise Stage2PairsError(
            f"the campaign holds {len(points)} {RUN_KIND} recordings, expected "
            f"{EXPECTED_RUNS}: this analysis reads eight runs in four pairs, not fewer"
        )
    steps = [int(point.binding.order) for point in points]
    if sorted(steps) != list(range(1, EXPECTED_RUNS + 1)):
        raise Stage2PairsError(
            f"the campaign's acquisition order is {steps}, not 1..{EXPECTED_RUNS}"
        )

    plan_jobs = _plan_jobs(decoded)
    recorded = _recorded_jobs(decoded)
    runs: list[_Run] = []
    for point in points:
        job = str(point.binding.job.job)
        planned = plan_jobs.get(job)
        if planned is None:
            raise Stage2PairsError(f"job {job!r}: the plan holds no such job")
        pair = str(getattr(planned, "pair", "") or "")
        role_field = getattr(planned, "role", "")
        role = str(getattr(role_field, "value", role_field) or "")
        if not pair or not role:
            raise Stage2PairsError(
                f"job {job!r}: the plan states pair {pair!r} and role {role!r}, so its pair "
                "membership is not part of the design"
            )
        row = recorded.get(job)
        if row is None:
            raise Stage2PairsError(
                f"job {job!r}: the pass record holds no row for it, so no provenance"
            )
        if str(row.get("pair") or "") != pair or str(row.get("role") or "") != role:
            raise Stage2PairsError(
                f"job {job!r}: the plan places it in pair {pair!r}/{role!r}, the pass record in "
                f"pair {row.get('pair')!r}/{row.get('role')!r}; the pair provenance in the run "
                "record must agree with the design"
            )

        declared = int(point.binding.job.emissions_per_profile)
        level = _level_of(job, declared)
        stored = point.config.emissions_per_profile
        runs.append(
            _Run(
                point=point,
                job=job,
                step=int(point.binding.order),
                pair=pair,
                role=role,
                level=level,
                label=str(point.binding.point.label),
                emissions=int(stored or 0),
                started_at=str(point.binding.job.started_at),
                finished_at=str(point.binding.job.finished_at),
                scalar=supported_mean_of(
                    point,
                    window_s=decoded.window_s,
                    support_mm=decoded.support_mm,
                    name=FLOOR_STATISTIC,
                ),
                block=gate_statistics(
                    point, window_s=decoded.window_s, support_mm=decoded.support_mm
                )[FLOOR_STATISTIC],
            )
        )
    runs.sort(key=lambda run: run.step)

    by_pair: dict[str, list[_Run]] = {}
    for run in runs:
        by_pair.setdefault(run.pair, []).append(run)
    if len(by_pair) != EXPECTED_PAIRS:
        raise Stage2PairsError(
            f"the campaign holds {len(by_pair)} pair(s) ({sorted(by_pair)}), expected "
            f"{EXPECTED_PAIRS}"
        )
    for pair in sorted(by_pair):
        members = by_pair[pair]
        levels = sorted(run.level for run in members)
        if len(members) != 2 or levels != sorted(LEVEL_ORDER):
            raise Stage2PairsError(
                f"pair {pair!r} holds {[(run.job, run.level) for run in members]}, not one run "
                f"of each level ({', '.join(LEVEL_ORDER)}); a pair that does not bracket the "
                "two levels is not a contrast"
            )
        if {run.role for run in members} != {ROLE_LEAD, ROLE_FOLLOW}:
            raise Stage2PairsError(
                f"pair {pair!r}: its roles are {sorted(run.role for run in members)}, not one "
                "lead and one follow"
            )
        lead = next(run for run in members if run.role == ROLE_LEAD)
        first = min(members, key=lambda run: run.step)
        if lead.step != first.step:
            raise Stage2PairsError(
                f"pair {pair!r}: the plan calls {lead.job!r} its lead, but {first.job!r} ran "
                "first; the job that opens a pair is that pair's lead, and the counterbalance "
                "is read off the order, not off the labels"
            )

    # ── the artefact, once the design holds: each run's stored word is its own level ──
    for run in runs:
        declared = int(run.point.binding.job.emissions_per_profile)
        stored = run.point.config.emissions_per_profile
        if stored != declared:
            raise Stage2PairsError(
                f"job {run.job!r}: the stored word emissions_per_profile is {stored}, so the "
                f"recording is not the {run.level} run its pair declares "
                f"(emissions_per_profile {declared})"
            )

    reference = runs[0]
    for run in runs:
        for field_name, prose in FRAME_FIELDS:
            mine = getattr(run.point.config, field_name)
            theirs = getattr(reference.point.config, field_name)
            if mine != theirs:
                raise Stage2PairsError(
                    f"job {run.job!r}: its {prose} is {mine!r}, while job "
                    f"{reference.job!r} states {theirs!r}; emissions per profile is this pass's "
                    "one varying setting, so every other fact of the frame has to be identical "
                    "across the eight runs"
                )

    native = np.asarray(reference.point.depths, dtype=float)
    for run in runs:
        if not np.array_equal(np.asarray(run.point.depths, dtype=float), native):
            raise Stage2PairsError(
                f"job {run.job!r}: its native depth grid is not job {reference.job!r}'s, so a "
                "per-depth contrast is not defined"
            )
    mask = _support_mask(native, decoded.support_mm)
    supported = int(np.count_nonzero(mask))
    if supported < REFERENCE_WINDOW[1] - 1:
        raise Stage2PairsError(
            f"the common support covers {supported} gates of the declared "
            f"{REFERENCE_WINDOW[1]}-gate reference window at {REFERENCE_WINDOW[0]} mm, which is "
            "narrower than the pass's own window allows"
        )
    return _Campaign(
        decoded=decoded,
        runs=tuple(runs),
        native_depths=native,
        depths=native[mask],
        support_mm=decoded.support_mm,
        window_s=decoded.window_s,
    )


def _floors(campaign: _Campaign) -> tuple[LevelFloorValue, ...]:
    """Each level's within-campaign variation, from the six unique pairs its four runs make."""
    floors: list[LevelFloorValue] = []
    for level in LEVEL_ORDER:
        members = [run for run in campaign.runs if run.level == level]
        if len(members) != RUNS_PER_LEVEL:
            raise Stage2PairsError(
                f"level {level} holds {len(members)} run(s), expected {RUNS_PER_LEVEL}"
            )
        averaged, averaged_pair = -1.0, ("", "")
        resolved, resolved_depth, resolved_pair = -1.0, 0.0, ("", "")
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                difference = left.scalar - right.scalar
                if abs(difference) > averaged:
                    averaged, averaged_pair = abs(difference), (left.job, right.job)
                profile = left.block - right.block
                worst = int(np.argmax(np.abs(profile)))
                magnitude = float(abs(profile[worst]))
                if magnitude > resolved:
                    resolved = magnitude
                    resolved_depth = float(campaign.depths[worst])
                    resolved_pair = (left.job, right.job)
        floors.append(
            LevelFloorValue(
                level=level,
                emissions=LEVEL_EMISSIONS[level],
                jobs=tuple(run.job for run in members),
                runs_pooled=len(members),
                unique_pairs=UNIQUE_RUN_PAIRS,
                depth_averaged_mm_s=averaged,
                depth_averaged_pair=averaged_pair,
                depth_resolved_mm_s=resolved,
                depth_resolved_depth_mm=resolved_depth,
                depth_resolved_pair=resolved_pair,
            )
        )
    return tuple(floors)


def _contrasts(
    campaign: _Campaign, screening_floor_mm_s: float
) -> tuple[tuple[ContrastValue, ...], np.ndarray]:
    """The four published contrasts, E64 minus E20, with the raw order kept beside them."""
    by_pair: dict[str, list[_Run]] = {}
    for run in campaign.runs:
        by_pair.setdefault(run.pair, []).append(run)
    contrasts: list[ContrastValue] = []
    profiles: list[np.ndarray] = []
    for pair in sorted(by_pair):
        members = sorted(by_pair[pair], key=lambda run: run.step)
        lead, follow = members[0], members[1]
        e20 = next(run for run in members if run.level == "E20")
        e64 = next(run for run in members if run.level == "E64")
        profile = oriented_contrast(e20_block=e20.block, e64_block=e64.block)
        oriented = float(e64.scalar - e20.scalar)
        worst = int(np.argmax(np.abs(profile)))
        contrasts.append(
            ContrastValue(
                pair=pair,
                acquisition_orientation=f"{lead.emissions} -> {follow.emissions}",
                e20_job=e20.job,
                e64_job=e64.job,
                lead_job=lead.job,
                follow_job=follow.job,
                order_difference_mm_s=float(follow.scalar - lead.scalar),
                oriented_mm_s=oriented,
                rms_mm_s=float(np.sqrt(np.mean(np.square(profile)))),
                max_abs_mm_s=float(abs(profile[worst])),
                max_abs_depth_mm=float(campaign.depths[worst]),
                exceeds_floor=bool(abs(oriented) > screening_floor_mm_s),
            )
        )
        profiles.append(profile)
    return tuple(contrasts), np.asarray(profiles, dtype=float)


def _checks(
    campaign: _Campaign,
    contrasts: tuple[ContrastValue, ...],
    floors: tuple[LevelFloorValue, ...],
    scalar: Verdict,
    depth_resolved: Verdict,
) -> dict[str, bool]:
    """The slice's own gate: every statement the report makes must be true of the campaign."""
    runs = campaign.runs
    by_job = {run.job: run for run in runs}
    return {
        "eight_runs": len(runs) == EXPECTED_RUNS,
        "four_pairs": len({run.pair for run in runs}) == EXPECTED_PAIRS,
        "one_run_of_each_level_per_pair": all(
            sorted(run.level for run in runs if run.pair == contrast.pair)
            == sorted(LEVEL_ORDER)
            for contrast in contrasts
        ),
        "stored_word_is_the_declared_level": all(
            run.point.config.emissions_per_profile == run.emissions
            == LEVEL_EMISSIONS[run.level]
            for run in runs
        ),
        "frame_identical": True,  # _campaign refuses a moving frame; recorded for the report
        "orientation_stated": campaign.decoded.plan.analysis_orientation == STATED_ORIENTATION,
        "orientation_matches_order": all(
            contrast.acquisition_orientation
            == (
                f"{by_job[contrast.lead_job].emissions} -> "
                f"{by_job[contrast.follow_job].emissions}"
            )
            for contrast in contrasts
        ),
        "window_is_the_designed_one": abs(campaign.window_s - DESIGNED_WINDOW_S) <= TOLERANCE,
        "one_native_grid": True,  # _campaign refuses otherwise; recorded for the report
        "floors_are_this_campaigns": all(
            floor.runs_pooled == RUNS_PER_LEVEL
            and floor.unique_pairs == UNIQUE_RUN_PAIRS
            and set(floor.jobs) <= set(by_job)
            for floor in floors
        ),
        "floor_is_the_larger_level_floor": abs(
            max(floor.depth_averaged_mm_s for floor in floors) - scalar.floor_mm_s
        )
        <= TOLERANCE,
        "outcome_is_one_of_two": scalar.outcome in (OUTCOME_RESOLVED, OUTCOME_OVERLAP)
        and depth_resolved.outcome in (OUTCOME_RESOLVED, OUTCOME_OVERLAP),
        "overlap_kind_is_consistent": (
            scalar.overlap_kind is None
            if scalar.outcome == OUTCOME_RESOLVED
            else scalar.overlap_kind in (OVERLAP_NOT_DETECTED, OVERLAP_NOT_RESOLVABLE)
        ),
        "prior_floors_are_context_only": scalar.floor_mm_s
        != PRIOR_DEPTH_AVERAGED_FLOOR_MM_S
        and depth_resolved.floor_mm_s != PRIOR_DEPTH_RESOLVED_FLOOR_MM_S,
    }


# ── the build ──────────────────────────────────────────────────────────


def build_stage2_pairs(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    plan_name: str = PLAN_NAME,
    analysis_commit: str | None = None,
) -> Stage2Pairs:
    """The campaign's four paired contrasts and their contemporaneous floor, or a refusal.

    Raises:
        Stage2PairsError: for anything the frozen ingest refuses, and for a campaign that is
            not this design — a plan that does not state the analysis orientation, recordings
            that are not eight run-level jobs forming four pairs of one run of each level, a
            stored emissions word that is not its job's declared level, a frame that moves
            between runs, or a native depth grid that differs between them.
    """
    decoded = decode_pass(Path(dataset_root), plan_path=Path(plan_path), plan_name=plan_name)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise Stage2PairsError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )
    campaign = _campaign(decoded)
    floors = _floors(campaign)
    screening = max(floors, key=lambda floor: floor.depth_averaged_mm_s)
    depth_floor = max(floors, key=lambda floor: floor.depth_resolved_mm_s)
    screening_source = (
        "the larger of this campaign's two within-level depth-averaged floors ("
        + "; ".join(f"{floor.level} {floor.depth_averaged_mm_s:.4f} mm/s" for floor in floors)
        + "), each measured on that level's own four runs of this campaign"
    )
    depth_source = (
        "the larger of this campaign's two within-level depth-resolved floors ("
        + "; ".join(
            f"{floor.level} {floor.depth_resolved_mm_s:.4f} mm/s at "
            f"{floor.depth_resolved_depth_mm:.3f} mm"
            for floor in floors
        )
        + "), each measured on that level's own four runs of this campaign"
    )

    contrasts, profiles = _contrasts(campaign, screening.depth_averaged_mm_s)
    scalar = decide(
        np.asarray([contrast.oriented_mm_s for contrast in contrasts], dtype=float),
        screening.depth_averaged_mm_s,
        TOLERANCE,
    )
    strongest = np.asarray(
        [profile[int(np.argmax(np.abs(profile)))] for profile in profiles], dtype=float
    )
    depth_resolved = decide(strongest, depth_floor.depth_resolved_mm_s, TOLERANCE)
    share = _resolved_share(profiles, depth_floor.depth_resolved_mm_s)

    reference = campaign.runs[0].point.config
    checks = _checks(campaign, contrasts, floors, scalar, depth_resolved)
    return Stage2Pairs(
        dataset_root=Path(dataset_root).as_posix(),
        plan=str(getattr(decoded.plan, "plan", "") or PLAN_NAME),
        plan_path=Path(plan_path).as_posix(),
        plan_fingerprint=str(decoded.plan_fingerprint),
        analysis_commit=commit,
        channel=int(getattr(decoded.plan, "channel", 0) or 0),
        duration_s=float(getattr(decoded.plan, "duration_s", 0.0) or 0.0),
        window_s=campaign.window_s,
        window_revolutions=round(campaign.window_s / (60.0 / 500.0)),
        support_min_mm=float(campaign.support_mm[0]),
        support_max_mm=float(campaign.support_mm[1]),
        reference_resolution_mm=float(REFERENCE_WINDOW[0]),
        reference_gates=int(REFERENCE_WINDOW[1]),
        runs=tuple(
            RunValue(
                label=run.label,
                job=run.job,
                step=run.step,
                pair=run.pair,
                role=run.role,
                level=run.level,
                emissions=run.emissions,
                kind=str(run.point.binding.job.kind),
                relative_path=run.point.relative_path,
                gates=int(reference.n_gates or 0),
                resolution_mm=float(reference.resolution_mm or 0.0),
                supported_gates=int(np.count_nonzero(_support_mask(campaign.native_depths, campaign.support_mm))),
                sound_speed_ms=float(reference.sound_speed_ms or 0.0),
                prf_us=(
                    float(1e6 / reference.pulse_repetition_freq_hz)
                    if reference.pulse_repetition_freq_hz
                    else 0.0
                ),
                burst_length=int(reference.burst_length or 0),
                depth_mm=float(reference.max_depth_mm or 0.0),
                first_gate_mm=float(reference.gate1_mm or 0.0),
                depth_averaged_mean_mm_s=run.scalar,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            for run in campaign.runs
        ),
        contrasts=contrasts,
        floors=floors,
        screening_floor_mm_s=screening.depth_averaged_mm_s,
        screening_floor_level=screening.level,
        screening_floor_source=screening_source,
        depth_resolved_floor_mm_s=depth_floor.depth_resolved_mm_s,
        depth_resolved_floor_depth_mm=depth_floor.depth_resolved_depth_mm,
        depth_resolved_floor_level=depth_floor.level,
        depth_resolved_floor_source=depth_source,
        stated_orientation=STATED_ORIENTATION,
        scalar=scalar,
        depth_resolved=depth_resolved,
        depth_resolved_resolved_share=share,
        prior_context={
            PRIOR_DATASET: {
                "depth_averaged_mm_s": PRIOR_DEPTH_AVERAGED_FLOOR_MM_S,
                "depth_resolved_mm_s": PRIOR_DEPTH_RESOLVED_FLOOR_MM_S,
            }
        },
        prior_context_note=PRIOR_CONTEXT_NOTE,
        floor_statistic=FLOOR_STATISTIC,
        floor_endpoint=FLOOR_ENDPOINT,
        averaged_endpoint=AVERAGED_ENDPOINT,
        profiles=_profiles_model(campaign, contrasts, profiles),
        checks=checks,
    )


def _resolved_share(profiles: np.ndarray, floor_mm_s: float) -> float:
    """The share of supported gates that are individually resolved, all four pairs agreeing.

    A gate counts only when **every** pair's contrast there exceeds the depth-resolved floor
    *and* all four share a sign: the depth-resolved reading of the same two-outcome rule.
    """
    if profiles.size == 0:
        return 0.0
    signs = np.sign(profiles)
    resolved = np.ones(profiles.shape[1], dtype=bool)
    for index, profile in enumerate(profiles):
        resolved &= np.abs(profile) > floor_mm_s
        resolved &= signs[index] == signs[0]
    return float(np.count_nonzero(resolved) / resolved.size)


def _profiles_model(
    campaign: _Campaign, contrasts: tuple[ContrastValue, ...], profiles: np.ndarray
) -> ContrastProfiles:
    """The eight run profiles and the four contrasts, on the shared supported grid."""
    by_job = {run.job: run for run in campaign.runs}
    by_pair = {
        contrast.pair: profile
        for contrast, profile in zip(contrasts, profiles, strict=True)
    }
    return ContrastProfiles(
        depths_mm=campaign.depths,
        e20_a=by_job["e20-a"].block,
        e64_a=by_job["e64-a"].block,
        e64_b=by_job["e64-b"].block,
        e20_b=by_job["e20-b"].block,
        e20_c=by_job["e20-c"].block,
        e64_c=by_job["e64-c"].block,
        e64_d=by_job["e64-d"].block,
        e20_d=by_job["e20-d"].block,
        contrast_a=by_pair["A"],
        contrast_b=by_pair["B"],
        contrast_c=by_pair["C"],
        contrast_d=by_pair["D"],
    )


# ── the artefacts ──────────────────────────────────────────────────────


def csv_text(model: Stage2Pairs) -> str:
    """Render ``pairs.csv``: the eight runs, the four contrasts, then the two level floors."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(CSV_COLUMNS))

    def row(*cells: object) -> None:
        writer.writerow([format_cell(cell) if not isinstance(cell, str) else cell for cell in cells])

    for run in model.runs:
        row(
            "run", run.pair, run.job, run.step, run.role, run.level, run.emissions, "",
            "depth_averaged_mean_mm_s", run.depth_averaged_mean_mm_s, UNIT_MM_S,
        )
    for contrast in model.contrasts:
        for name, value in (
            ("oriented_mm_s", contrast.oriented_mm_s),
            ("order_difference_mm_s", contrast.order_difference_mm_s),
            ("rms_mm_s", contrast.rms_mm_s),
            ("max_abs_mm_s", contrast.max_abs_mm_s),
        ):
            row(
                "contrast", contrast.pair, "", "", "", "", "", contrast.acquisition_orientation,
                name, value, UNIT_MM_S,
            )
        row(
            "contrast", contrast.pair, "", "", "", "", "", contrast.acquisition_orientation,
            "exceeds_floor", "true" if contrast.exceeds_floor else "false", UNIT_COUNT,
        )
    for floor in model.floors:
        row(
            "floor", "", ", ".join(floor.jobs), "", "", floor.level, floor.emissions, "",
            "depth_averaged_mm_s", floor.depth_averaged_mm_s, UNIT_MM_S,
        )
        row(
            "floor", "", ", ".join(floor.jobs), "", "", floor.level, floor.emissions, "",
            "depth_resolved_mm_s", floor.depth_resolved_mm_s, UNIT_MM_S,
        )
    row(
        "floor", "", model.screening_floor_level, "", "", model.screening_floor_level, "", "",
        "screening_floor_mm_s", model.screening_floor_mm_s, UNIT_MM_S,
    )
    row(
        "floor", "", model.depth_resolved_floor_level, "", "", model.depth_resolved_floor_level,
        "", "", "depth_resolved_floor_mm_s", model.depth_resolved_floor_mm_s, UNIT_MM_S,
    )
    return buffer.getvalue()


def def_document(model: Stage2Pairs) -> dict[str, object]:
    """The definition document: every published number, its definition, and the gate."""
    return {
        "artefact": "reports/stage2-e20-e64/pairs",
        "stage": "the Stage-2 paired analysis (section 4b of docs/dop3000/sparse-pass-analysis-plan.md)",
        "dataset": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "analysis_commit": model.analysis_commit,
        "channel": model.channel,
        "duration_s": model.duration_s,
        "window_s": model.window_s,
        "window_revolutions": model.window_revolutions,
        "support": {
            "min_mm": model.support_min_mm,
            "max_mm": model.support_max_mm,
            "supported_gates": model.runs[0].supported_gates,
            "gates": model.runs[0].gates,
        },
        "reference_window": {
            "resolution_mm": model.reference_resolution_mm,
            "gates": model.reference_gates,
        },
        "frame_fields_checked": model.frame_fields_checked,
        "runs": [
            {
                "job": run.job,
                "step": run.step,
                "pair": run.pair,
                "role": run.role,
                "level": run.level,
                "emissions_per_profile": run.emissions,
                "label": run.label,
                "relative_path": run.relative_path,
                "depth_averaged_mean_mm_s": run.depth_averaged_mean_mm_s,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for run in model.runs
        ],
        "contrasts": [
            {
                "pair": contrast.pair,
                "acquisition_orientation": contrast.acquisition_orientation,
                "e20_job": contrast.e20_job,
                "e64_job": contrast.e64_job,
                "lead_job": contrast.lead_job,
                "follow_job": contrast.follow_job,
                "order_difference_mm_s": contrast.order_difference_mm_s,
                "oriented_mm_s": contrast.oriented_mm_s,
                "rms_mm_s": contrast.rms_mm_s,
                "max_abs_mm_s": contrast.max_abs_mm_s,
                "max_abs_depth_mm": contrast.max_abs_depth_mm,
                "exceeds_floor": contrast.exceeds_floor,
            }
            for contrast in model.contrasts
        ],
        "floors": [
            {
                "level": floor.level,
                "emissions_per_profile": floor.emissions,
                "jobs": list(floor.jobs),
                "runs_pooled": floor.runs_pooled,
                "unique_pairs": floor.unique_pairs,
                "depth_averaged_mm_s": floor.depth_averaged_mm_s,
                "depth_averaged_pair": list(floor.depth_averaged_pair),
                "depth_resolved_mm_s": floor.depth_resolved_mm_s,
                "depth_resolved_depth_mm": floor.depth_resolved_depth_mm,
                "depth_resolved_pair": list(floor.depth_resolved_pair),
            }
            for floor in model.floors
        ],
        "floor_statistic": model.floor_statistic,
        "floor_endpoint": model.floor_endpoint,
        "averaged_endpoint": model.averaged_endpoint,
        "screening_floor_mm_s": model.screening_floor_mm_s,
        "screening_floor_level": model.screening_floor_level,
        "screening_floor_source": model.screening_floor_source,
        "depth_resolved_floor_mm_s": model.depth_resolved_floor_mm_s,
        "depth_resolved_floor_depth_mm": model.depth_resolved_floor_depth_mm,
        "depth_resolved_floor_level": model.depth_resolved_floor_level,
        "depth_resolved_floor_source": model.depth_resolved_floor_source,
        "stated_orientation": model.stated_orientation,
        "outcome": model.outcome,
        "overlap_kind": model.overlap_kind,
        "scalar_verdict": model.scalar.model_dump(mode="json"),
        "depth_resolved_outcome": model.depth_resolved_outcome,
        "depth_resolved_verdict": model.depth_resolved.model_dump(mode="json"),
        "depth_resolved_resolved_share": model.depth_resolved_resolved_share,
        "prior_context": model.prior_context,
        "prior_context_note": model.prior_context_note,
        "definitions": DEFINITIONS,
        "checks": model.checks,
        "figure": f"{FIGURES_DIRNAME}/{FIGURE_NAME}",
    }


def render_markdown(model: Stage2Pairs) -> str:
    """Render ``pairs.md``: the design, the four contrasts, the floor, and the verdict."""
    lines: list[str] = []
    lines.append("# The Stage-2 paired analysis — four E64 - E20 contrasts in one campaign")
    lines.append("")
    lines.append(
        f"The eight run-level jobs of `{model.plan}` (plan fingerprint "
        f"`{model.plan_fingerprint[:12]}`), acquired in the frozen **counterbalanced** order:"
    )
    lines.append("")
    lines.append("```text")
    lines.append("E20-A   E64-A      E64-B   E20-B      E20-C   E64-C      E64-D   E20-D")
    lines.append("```")
    lines.append("")
    lines.append(
        "One **campaign block**, not two interleaved campaigns: one run plan, one manifest, one "
        "ordered sequence. Emissions per profile is the only run-wide setting that differs, and "
        f"the frame is otherwise identical across all eight runs in {model.frame_fields_checked} "
        "decoded settings."
    )
    lines.append("")
    lines.append(
        f"The two shared views are the pass's own: the designed exposure "
        f"**{model.window_s:g} s = {model.window_revolutions} nominal 500-RPM revolutions**, cut "
        f"by each recording's stored timestamps, and the common physical support "
        f"{model.support_min_mm:.3f} - {model.support_max_mm:.3f} mm — which covers "
        f"**all {model.runs[0].supported_gates} gates** of the declared "
        f"{model.reference_resolution_mm:.3f} mm x {model.reference_gates}-gate reference window, "
        "so every contrast below is published on the full window the campaign was planned around."
    )
    lines.append("")
    lines.append("## The four paired contrasts")
    lines.append("")
    lines.append(
        "Each pair is read **E64 - E20**, whatever order it was acquired in. The orientation is "
        "**recorded beside** each contrast rather than folded away, and the raw "
        "acquisition-order difference is published next to it: on a `64 -> 20` pair the two "
        "differ by sign, and a counterbalance read without the orientation would be a sign "
        "error on half the contrasts."
    )
    lines.append("")
    lines.append(
        "| pair | acquired | lead | follow | order difference | **oriented (E64 - E20)** | "
        "screening floor | above it |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---|")
    for contrast in model.contrasts:
        lines.append(
            f"| {contrast.pair} | {contrast.acquisition_orientation} | {contrast.lead_job} | "
            f"{contrast.follow_job} | {contrast.order_difference_mm_s:+.4f} | "
            f"**{contrast.oriented_mm_s:+.4f}** | {model.screening_floor_mm_s:.4f} | "
            f"{'yes' if contrast.exceeds_floor else 'no'} |"
        )
    lines.append("")
    lines.append(
        "Depth-resolved, the strongest per-gate separation of each pair is "
        + ", ".join(
            f"{contrast.pair} {contrast.max_abs_mm_s:.4f} mm/s at "
            f"{contrast.max_abs_depth_mm:.3f} mm"
            for contrast in model.contrasts
        )
        + f" — screened against the depth-resolved floor {model.depth_resolved_floor_mm_s:.4f} "
        f"mm/s at {model.depth_resolved_floor_depth_mm:.3f} mm, never against the depth-averaged one."
    )
    lines.append("")
    lines.append("| pair | depth-averaged (E64 - E20) | rms | max abs | at depth |")
    lines.append("|---|---:|---:|---:|---:|")
    for contrast in model.contrasts:
        lines.append(
            f"| {contrast.pair} | {contrast.oriented_mm_s:+.4f} | {contrast.rms_mm_s:.4f} | "
            f"{contrast.max_abs_mm_s:.4f} | {contrast.max_abs_depth_mm:.3f} mm |"
        )
    lines.append("")
    lines.append("## The eight runs, individually")
    lines.append("")
    lines.append(
        "The four emissions-20 observations and the four emissions-64 observations are reported "
        "separately, each run as its own measurement — nothing is averaged into a per-level "
        "reference, because a synthetic reference would hide exactly the run-to-run spread the "
        "screen is built from."
    )
    lines.append("")
    lines.append("| step | job | pair | role | level | emissions | window mean | recording |")
    lines.append("|---:|---|---|---|---|---:|---:|---|")
    for run in model.runs:
        lines.append(
            f"| {run.step} | {run.job} | {run.pair} | {run.role} | {run.level} | {run.emissions} "
            f"| {run.depth_averaged_mean_mm_s:+.4f} mm/s | `{run.relative_path}` |"
        )
    lines.append("")
    by_level = {level: [run for run in model.runs if run.level == level] for level in LEVEL_ORDER}
    for level in LEVEL_ORDER:
        means = ", ".join(f"{run.depth_averaged_mean_mm_s:+.4f}" for run in by_level[level])
        spread = max(run.depth_averaged_mean_mm_s for run in by_level[level]) - min(
            run.depth_averaged_mean_mm_s for run in by_level[level]
        )
        lines.append(
            f"- **{level}** (emissions {LEVEL_EMISSIONS[level]}) — {len(by_level[level])} runs, "
            f"window means {means} mm/s, spread {spread:.4f} mm/s"
        )
    lines.append("")
    lines.append("")
    lines.append("## The contemporaneous variation")
    lines.append("")
    lines.append(
        "The screen is **this campaign's own** run-to-run variation, measured on its eight runs "
        "by the endpoint WP2 used on the reference runs — the largest absolute window-mean "
        "difference over each level's six unique run pairs:"
    )
    lines.append("")
    lines.append("| level | runs | depth-averaged floor | at | depth-resolved floor | at depth |")
    lines.append("|---|---|---:|---|---:|---:|")
    for floor in model.floors:
        lines.append(
            f"| {floor.level} (emissions {floor.emissions}) | {', '.join(floor.jobs)} | "
            f"{floor.depth_averaged_mm_s:.4f} mm/s | {floor.depth_averaged_pair[0]}-"
            f"{floor.depth_averaged_pair[1]} | {floor.depth_resolved_mm_s:.4f} mm/s | "
            f"{floor.depth_resolved_depth_mm:.3f} mm |"
        )
    lines.append("")
    lines.append(f"- screening floor (depth-averaged): **{model.screening_floor_mm_s:.4f} mm/s** "
                 f"from {model.screening_floor_level}; {model.screening_floor_source}")
    lines.append(f"- depth-resolved floor: **{model.depth_resolved_floor_mm_s:.4f} mm/s** at "
                 f"{model.depth_resolved_floor_depth_mm:.3f} mm from "
                 f"{model.depth_resolved_floor_level}; {model.depth_resolved_floor_source}")
    lines.append("")
    lines.append(
        "**How the screen is composed matters as much as its value.** Both floors are maxima over "
        "the six unique run pairs of one level, so a single run that departs from the other three "
        "of its own level sets the screen for the whole campaign. That is the endpoint WP2 used on "
        "the reference runs and it is deliberately conservative: it is not an average of the "
        "campaign's noise, it is the campaign's worst same-level disagreement, and reading a "
        "contrast against it asks whether the emissions change is larger than the largest thing "
        "this campaign did on its own. The runs that set each floor are named in the table above, "
        "and the per-level spreads above that are the same numbers that build it."
    )
    lines.append("")
    first = min(model.runs, key=lambda run: run.step)
    involving_first = [
        f"{floor.level} ({pair[0]}-{pair[1]})"
        for floor in model.floors
        for pair in [floor.depth_averaged_pair]
        if first.job in pair
    ]
    if involving_first:
        lines.append(
            f"The campaign's first run, `{first.job}` (step {first.step}, "
            f"{first.depth_averaged_mean_mm_s:+.4f} mm/s), is one of the two runs in "
            f"{', '.join(involving_first)}: the screen this campaign measures for itself includes "
            "whatever settled during the sitting, and the campaign's own first job is reported "
            "here rather than excluded or smoothed — pre-filtering a run out of the floor would "
            "be a choice made after seeing the contrasts."
        )
        lines.append("")
    lines.append("## The outcome")
    lines.append("")
    scalar = model.scalar
    kind = f" — {scalar.overlap_kind}" if scalar.overlap_kind is not None else ""
    lines.append(f"**{model.outcome}** (depth-averaged){kind}.")
    lines.append("")
    article = "a" if scalar.consistent_direction else "an"
    lines.append(
        f"The four contrasts span {scalar.min_abs_mm_s:.4f} to {scalar.max_abs_mm_s:.4f} mm/s in "
        f"absolute value (mean {scalar.mean_mm_s:+.4f}, range {scalar.range_mm_s:.4f}), with "
        f"{scalar.exceeding} of {scalar.count} above the {scalar.floor_mm_s:.4f} mm/s floor and "
        f"{article} {'consistent' if scalar.consistent_direction else 'inconsistent'} direction."
    )
    lines.append("")
    depth_kind = (
        f" — {model.depth_resolved.overlap_kind}"
        if model.depth_resolved.overlap_kind is not None
        else ""
    )
    lines.append(f"**{model.depth_resolved_outcome}** (depth-resolved){depth_kind}.")
    lines.append("")
    lines.append(
        f"{model.depth_resolved_resolved_share:.1%} of the "
        f"{model.runs[0].supported_gates} supported gates are individually resolved — every pair "
        "above the depth-resolved floor there *and* all four agreeing in direction."
    )
    lines.append("")
    lines.append(
        "The criterion has exactly two allowed outcomes and this is one of them: a **resolved "
        "difference** or an **unresolved overlap**. Inside an overlap the vocabulary keeps two "
        "findings apart — **not detected** (the contrasts sit inside the campaign's own "
        "variation) and **not resolvable with this design** (they reach past the floor on some "
        "pairs but not consistently, or disagree in direction). Neither is a claim that no "
        "effect exists, and a depth-averaged verdict says nothing about a single gate."
    )
    lines.append("")
    lines.append("## The earlier pass, as context only")
    lines.append("")
    lines.append(
        f"{model.prior_context_note}. `{PRIOR_DATASET}`'s published floors were "
        f"**{PRIOR_DEPTH_AVERAGED_FLOOR_MM_S} mm/s** depth-averaged and "
        f"**{PRIOR_DEPTH_RESOLVED_FLOOR_MM_S} mm/s** depth-resolved; they appear here so the two "
        "campaigns can be read side by side, and no number above was screened against them."
    )
    lines.append("")
    lines.append("## What this does to the frozen decision table")
    lines.append("")
    lines.append(
        "Nothing in `reports/sparse-mixer-live-1/decision-table.md` is rewritten: its "
        "E64-vs-E20 row was published as `defer` / not resolvable **with that pass's design**, "
        "and this campaign was the measurement that row named as the one that would overturn "
        "it. Folding this outcome into that table is a one-row change to a pinned artefact, so "
        "it belongs in its own reviewed slice rather than in this one."
    )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "uv run python -m udv_echo_process.cli sparse-stage2-pairs "
        f"--analysis-commit {model.analysis_commit}"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "The table is `pairs.csv`, the definition document `pairs.json` (it carries the "
        "definitions, the gate checks and the table's SHA-256), and the figure "
        f"`{FIGURES_DIRNAME}/{FIGURE_NAME}`."
    )
    lines.append("")
    lines.append("## Every published number, defined")
    lines.append("")
    for name, text in DEFINITIONS.items():
        lines.append(f"- `{name}` — {text}")
    lines.append("")
    lines.append("## The gate")
    lines.append("")
    for name, ok in model.checks.items():
        lines.append(f"- `{name}` — {'ok' if ok else 'FAILED'}")
    lines.append("")
    return "\n".join(lines) + "\n"


def render_figure(model: Stage2Pairs, path: Path) -> Path:
    """Draw the four contrasts and the contemporaneous floor band, against depth.

    One panel per reading: the left keeps all eight runs individually visible (no averaged
    profile is drawn, on purpose) and the right draws the four E64-E20 contrasts with the
    depth-resolved floor as a band, so the figure cannot be read as a significance test.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    depths = np.asarray(model.profiles.depths_mm, dtype=float)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (runs, contrasts) = plt.subplots(1, 2, figsize=(11.6, 4.6), dpi=FIGURE_DPI)
    e20_color, e64_color = "#1f77b4", "#d62728"
    for run in model.runs:
        color = e20_color if run.level == "E20" else e64_color
        style = "-" if run.level == "E20" else "--"
        runs.plot(model.profiles.run(run.job), depths, color=color, linestyle=style,
                  linewidth=1.1, alpha=0.9)
    runs.set_xlabel("window mean velocity [mm/s]")
    runs.set_ylabel("depth [mm]")
    runs.invert_yaxis()
    runs.set_title(
        "the eight runs, individually\nsolid: emissions 20, dashed: emissions 64", fontsize=9
    )
    for contrast in model.contrasts:
        contrasts.plot(
            model.profiles.contrast(contrast.pair),
            depths,
            linewidth=1.2,
            label=f"{contrast.pair}: {contrast.acquisition_orientation}",
        )
    contrasts.axvline(0.0, color="#555555", linewidth=0.8)
    for value in (model.depth_resolved_floor_mm_s, -model.depth_resolved_floor_mm_s):
        contrasts.axvline(value, color="#888888", linewidth=0.9, linestyle=":")
    contrasts.set_xlabel("E64 - E20 window mean [mm/s]")
    contrasts.set_ylabel("depth [mm]")
    contrasts.invert_yaxis()
    contrasts.legend(fontsize=7, loc="best")
    contrasts.set_title(
        "the four paired contrasts, E64 - E20\ndotted: the depth-resolved floor "
        f"{model.depth_resolved_floor_mm_s:.3f} mm/s at {model.depth_resolved_floor_depth_mm:.2f} mm",
        fontsize=9,
    )
    figure.suptitle(
        f"{model.outcome} / {model.depth_resolved_outcome}; screening floor "
        f"{model.screening_floor_mm_s:.3f} mm/s measured in this campaign",
        fontsize=9,
    )
    figure.tight_layout()
    figure.savefig(path, dpi=FIGURE_DPI)
    plt.close(figure)
    return path


def write_stage2_pairs(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    plan_name: str = PLAN_NAME,
    analysis_commit: str | None = None,
) -> Stage2Pairs:
    """Build the analysis and write the table, the document, the report and the figure.

    Every file is UTF-8 with LF endings and one trailing newline, so two runs on the same
    inputs and revision produce identical bytes. Nothing is written when the build refuses.
    """
    model = build_stage2_pairs(
        dataset_root, plan_path=plan_path, plan_name=plan_name, analysis_commit=analysis_commit
    )
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CSV_NAME).write_text(csv_text(model), encoding="utf-8", newline="")
    document = def_document(model)
    document["table_sha256"] = (
        "sha256:" + hashlib.sha256((directory / CSV_NAME).read_bytes()).hexdigest()
    )
    (directory / DOC_NAME).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline=""
    )
    (directory / MD_NAME).write_text(render_markdown(model), encoding="utf-8", newline="")
    render_figure(model, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model


def stage2_pairs_main(argv: list[str] | None = None) -> None:
    """``sparse-stage2-pairs`` — write this slice's table, document, report and figure.

    Reads the campaign's eight committed recordings through the frozen ingest's own binding
    and decoding, keeps them as eight individually visible runs in four pairs, publishes the
    four paired contrasts oriented E64 minus E20 with each pair's acquisition orientation, and
    screens them against the variation the campaign itself measured. It exits 0 when every gate
    check holds and 1 otherwise, naming the failure; a campaign the ingest refuses exits 1 with
    its own reason and writes nothing.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-stage2-pairs",
        description=(
            "the Stage-2 paired analysis: four counterbalanced E64 - E20 contrasts and the "
            "contemporaneous floor of one campaign"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=DATASET_ROOT.as_posix(),
        help="directory of committed .BDD recordings plus the pass's own record",
    )
    parser.add_argument(
        "--plan",
        default=PLAN_PATH.as_posix(),
        help="the compiled campaign the pass is a realization of",
    )
    parser.add_argument(
        "--plan-name",
        default=PLAN_NAME,
        help="the pass record's name inside the dataset root",
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR.as_posix(),
        help="directory to write pairs.csv, pairs.json and pairs.md into",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    try:
        model = write_stage2_pairs(
            Path(args.dataset_root),
            Path(args.report_dir),
            plan_path=Path(args.plan),
            plan_name=args.plan_name,
            analysis_commit=args.analysis_commit,
        )
    except SparseIngestError as exc:
        print(f"udv-sparse-stage2-pairs: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    for run in model.runs:
        print(
            f"{run.job:6s} step {run.step}  pair {run.pair}  {run.role:6s}  "
            f"{run.level}  mean {run.depth_averaged_mean_mm_s:+9.4f} mm/s  "
            f"({run.relative_path})"
        )
    for contrast in model.contrasts:
        print(
            f"pair {contrast.pair}: acquired {contrast.acquisition_orientation:8s} "
            f"order difference {contrast.order_difference_mm_s:+8.4f}, "
            f"oriented E64 - E20 {contrast.oriented_mm_s:+8.4f} mm/s "
            f"({'above' if contrast.exceeds_floor else 'inside'} the floor)"
        )
    print(
        f"floor : depth-averaged {model.screening_floor_mm_s:.4f} mm/s "
        f"(from {model.screening_floor_level}); depth-resolved "
        f"{model.depth_resolved_floor_mm_s:.4f} mm/s at "
        f"{model.depth_resolved_floor_depth_mm:.3f} mm (from {model.depth_resolved_floor_level})"
    )
    print(
        f"verdict: {model.outcome} (depth-averaged)"
        + (f" — {model.overlap_kind}" if model.overlap_kind else "")
        + f"; {model.depth_resolved_outcome} (depth-resolved), "
        f"{model.depth_resolved_resolved_share:.1%} of gates resolved"
    )
    print(f"table   : {Path(args.report_dir) / CSV_NAME}")
    print(f"document: {Path(args.report_dir) / DOC_NAME}")
    failed = [name for name, ok in sorted(model.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sparse-stage2-pairs: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
