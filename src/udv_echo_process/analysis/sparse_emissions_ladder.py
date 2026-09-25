"""WP4 of the sparse-pass analysis: the emissions ladder and its temporal cost.

**What this measures.** Four emissions-per-profile levels — E8, E20, E64 and E128 — all
at the **reference spatial window** (50 gates x 1.85 mm) and the reference support
(10.138-98.938 mm), from four *different* sources of evidence, and it measures them in
two views that are kept apart:

- **view 1, velocity-estimate stability** — the pass's designed primary window (the
  declared 12 s, cut in every recording by its own stored timestamps) on the common
  physical support: the five distributional statistics the frozen WP0 table aggregates
  (``mean``, ``median``, ``iqr``, ``rms``, ``zero_fraction``) per level and per E20 run,
  the three **consecutive-level** signed profile differences (E8->E20, E20->E64,
  E64->E128) on that support with each difference's unweighted mean, its extreme and the
  depth where the extreme sits, and — for the three levels that own a job's block-local
  controls — the residual of the one scientific row against **each** of its two
  bracketing anchors, depth-averaged and per gate;
- **view 2, the temporal cost** — the **full retained record** (not the 12 s window),
  from each file's **achieved** timestamps: the achieved profile period (the median and
  the mean of the successive differences of the stored per-profile time array), the
  profile rate, the Nyquist frequency, the frequency resolution over the record's own
  stated duration, the lag-1 autocorrelation of the stored series and the first lag at
  which ``|ACF|`` falls below 0.5 at three stated depths, and a segmentation of every
  record into equal **physical-duration** blocks — never equal profile counts, because
  the levels differ by a factor of 5.7 in profile rate — with the profiles each level
  fits into one such block.

**The evidence is unequal, and this module publishes that instead of blurring it.**

- **E20 is four runs.** It is measured from the four common-reference recordings
  ``cr1``..``cr4`` (decoded burst 10 / emissions 20, one per reference job) — the only
  condition this pass observes in more than one run — and the level's stated variation is
  the **spread of those four runs**, which is WP2's own data. Nothing here averages them
  into one profile: four runs are four, each is published individually, and no
  averaged-profile field exists for the level.
- **E8, E64 and E128 are one scientific recording each** (``e8``, ``e64``, ``e128``), each
  inside its own job's three **block-local anchor controls** (``ctrl-begin``,
  ``ctrl-mid``, ``ctrl-end``), which record *that job's own* condition. Their stated
  variation is the spread of those three anchors — a within-job bracketing context, not
  replication of the level.

**How a comparison is screened, and against which floor.** Three floors exist and they
are never mixed:

- a **depth-resolved** difference (a per-gate difference array, or extreme) is screened
  against WP2's depth-resolved endpoint, which this module **recomputes** from the four
  E20 runs: the largest absolute per-depth window-mean difference over their six ordered
  pairs;
- a **depth-averaged** difference (one unweighted mean over the supported gates) is
  screened against WP2's depth-averaged endpoint, recomputed the same way and the only
  one of the two that is like for like with WP1's per-job floors;
- a row measured **inside one job** against its own two bracketing anchors is screened
  against that job's own anchor spread from WP1, rebuilt here from that job's three
  block-local anchor controls.

**The published side of every floor is read, never pinned.** Each of the five rows carries
the number the pass's **own** WP1 and WP2 artefacts publish — ``anchor-floor.json`` and
``reference-floor.json``, beside this slice's own files in the pass's report directory —
at the three decimals those slices publish to.
The plan fingerprint both documents state is checked against the pass's own plan and their
own gate must have passed, so the two documents are this pass's own or the build refuses by
name. A second sitting therefore screens against its own campaign: the first sitting's
numbers (14.603 mm/s at 21.238 mm depth-resolved, 4.235 depth-averaged, 1.521 / 2.829 /
3.304 mm/s for the emissions-8, -64 and -128 jobs) are its own, read from its artefacts like
any other pass's, and are quoted here only because they are the readings this ladder was
first read against.

**The observation WP1 left here, and its correct reading.** ``e128`` sits **larger than**
both of its bracketing anchors in the depth-averaged mean (+3.327 against ``ctrl-begin``,
+4.696 against ``ctrl-mid``; per-gate extreme +14.642 mm/s at 76.74 mm). WP4 examines it
depth-resolved — how many knots carry the sign, over which contiguous depth region, and
how much of it is a few gates — and states plainly that it is **not** evidence that E128
caused a change: it is a difference between **one realization** and its two anchors, it is
of the same size as the floors this pass owns rather than far outside them, and the
emissions axis is not replicated at any level except E20's. A screening outcome is not a
proof of an axis effect and does not bound drift.

**What it does not do.** No causality from single realizations. No plateau, optimum,
separability or "materially better" verdict claimed from one recording per level. No
spectrum, no SNR/saturation statement (these files carry axial velocity only), no
interaction (WP3), no change to the frozen WP0 artefacts or to WP1's and WP2's — this
slice adds documents beside them, and it reads every number through
:mod:`udv_echo_process.analysis._sparse_pass`, so the window, the support, the per-gate
statistics and the recording->point binding are the table's own.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.analysis._floor_documents import (
    AuthenticatedFloor,
    FloorDocumentError,
    ReferenceEndpoints,
    read_floor_document,
    require_agrees,
)
from udv_echo_process.analysis._sparse_pass import (
    PassDecoding,
    decode_pass,
    gate_statistics,
    supported_gates,
    supported_mean_of,
)
from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    DESIGNED_WINDOW_S,
    PLAN_PATH,
    REPORT_DIR,
    DecodedPoint,
    SparseIngestError,
)
from udv_echo_process.analysis.sparse_inventory import (
    DEFINITIONS as WP0_DEFINITIONS,
)
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.provenance.models import current_revision

# ── the ladder ─────────────────────────────────────────────────────────

#: The four levels, in ladder order: the order the consecutive differences are taken in.
LEVEL_ORDER: tuple[str, ...] = ("E8", "E20", "E64", "E128")

#: The one scientific recording each single-recording level is measured from, with the
#: job whose own condition it holds and whose anchors bracket it.
SCIENTIFIC_SOURCES: dict[str, tuple[str, str]] = {
    "E8": ("e8", "emissions-8"),
    "E64": ("e64", "emissions-64"),
    "E128": ("e128", "emissions-128"),
}

#: The level measured from the four common-reference runs, one per reference job.
E20_LEVEL = "E20"
E20_RUN_SOURCES: tuple[tuple[str, str], ...] = (
    ("cr1", "common-reference-1"),
    ("cr2", "common-reference-2"),
    ("cr3", "common-reference-3"),
    ("cr4", "common-reference-4"),
)

#: The three block-local anchor controls, in acquisition order. They record the
#: reference *window* at their own job's anchor condition, and they are not realizations
#: of the reference condition (which only CR1-CR4 record).
ANCHOR_LABELS: tuple[str, ...] = ("ctrl-begin", "ctrl-mid", "ctrl-end")

#: The two anchors that bracket each emissions job's scientific row, in acquisition
#: order: the designated measurement sits between them, and ``ctrl-end`` reports the
#: drift that follows it rather than bracketing it symmetrically (WP1).
BRACKET_ANCHORS: tuple[str, ...] = ("ctrl-begin", "ctrl-mid")

#: The evidence a level is measured from, as the document publishes it.
EVIDENCE_SINGLE = (
    "one scientific recording, bracketed by its job's three block-local anchor controls"
)
EVIDENCE_FOUR_RUNS = (
    "four runs of the common-reference condition, one per reference job: the only level "
    "of this ladder observed in more than one run"
)

#: The decoded condition each level's records must hold: the same reference spatial
#: window and the same burst at the four emissions settings of the ladder. The pass's
#: PRF and sound speed are identical at every point (600 us, 1480 m/s).
#: The manual's period law carries this many PRF terms before the transfer term; the
#: fixed intercept a recording shows is ``INTERNAL_EMISSION_TERMS x PRF + transfer``.
INTERNAL_EMISSION_TERMS = 16
DECLARED_CONDITIONS: dict[str, dict[str, float]] = {
    "E8": {
        "burst_length": 10.0,
        "emissions_per_profile": 8.0,
        "prf_us": 600.0,
        "resolution_mm": 1.85,
        "n_gates": 50.0,
    },
    "E20": {
        "burst_length": 10.0,
        "emissions_per_profile": 20.0,
        "prf_us": 600.0,
        "resolution_mm": 1.85,
        "n_gates": 50.0,
    },
    "E64": {
        "burst_length": 10.0,
        "emissions_per_profile": 64.0,
        "prf_us": 600.0,
        "resolution_mm": 1.85,
        "n_gates": 50.0,
    },
    "E128": {
        "burst_length": 10.0,
        "emissions_per_profile": 128.0,
        "prf_us": 600.0,
        "resolution_mm": 1.85,
        "n_gates": 50.0,
    },
}

#: The reference window, as the plan requests it: ``(resolution_mm, gates)``.
REFERENCE_WINDOW: tuple[float, int] = (1.85, 50)

#: The statistics the frozen WP0 table aggregates and this slice reports per level.
STATISTICS: tuple[str, ...] = ("mean", "median", "iqr", "rms", "zero_fraction")

#: The statistic a residual or a depth-resolved difference is taken in (WP1's own).
RESIDUAL_STATISTIC = "mean"

#: The consecutive levels the ladder contrasts, in ladder order.
DIFFERENCE_STEPS: tuple[tuple[str, str], ...] = (
    ("E8", "E20"),
    ("E20", "E64"),
    ("E64", "E128"),
)

# ── the floors ─────────────────────────────────────────────────────────

#: The two sibling artefacts every pass's own floors are published in, beside this slice's
#: own files in the pass's report directory: WP1's per-job anchor spreads and WP2's
#: between-run reference floor's two endpoints. They are read, never pinned: what this
#: slice screens with is the number the pass's own recordings produced, not the number the
#: first sitting's did.
ANCHOR_FLOOR_DOC = "anchor-floor.json"
REFERENCE_FLOOR_DOC = "reference-floor.json"
PUBLISHED_FLOOR_DOCUMENTS: tuple[str, ...] = (ANCHOR_FLOOR_DOC, REFERENCE_FLOOR_DOC)

#: The decimals WP1 and WP2 publish a floor to, which is what ``published_mm_s`` states:
#: the artefact's own number at this precision (the committed first-pass artefact carries
#: ``14.603`` beside its document's ``14.603170079597177``).
PUBLISHED_FLOOR_DECIMALS = 3

#: The recomputation here has to reproduce the pass's own published floor within that
#: rounding and no further.
FLOOR_PUBLISHED_TOLERANCE_MM_S = 1e-3

# ── the temporal view ─────────────────────────────────────────────────

#: The block duration every record is segmented by. It is a **physical duration**, the
#: plan's requirement: a fixed profile count would compare 15 ms of one level with 87 ms
#: of another, because the levels differ by a factor of 5.7 in profile rate.
BLOCK_DURATION_S = 2.0

#: The depths the autocorrelation is measured at, and which native gate each resolves to.
#: Two of them are the depths the earlier slices named (WP2's floor depth 21.238 mm,
#: WP1's ``e128`` extreme 76.74 mm) and the third is mid-support.
ACF_DEPTHS_MM: tuple[float, ...] = (21.238, 48.988, 76.738)

#: The half level the first falling lag is reported at, and the lag span the published
#: autocorrelation curves cover, in seconds.
ACF_HALF_LEVEL = 0.5
ACF_MAX_LAG_S = 5.0

#: The reviewer's expected achieved periods and rates for the four levels, stated to
#: three significant figures in the WP4 request, with the tolerance that wording allows:
#: 0.05 ms on a period and 0.1 Hz on a rate. They are **checked, not adopted**.
EXPECTED_PERIOD_S: dict[str, float] = {
    "E8": 0.0152,
    "E20": 0.0224,
    "E64": 0.0488,
    "E128": 0.0872,
}
EXPECTED_RATE_HZ: dict[str, float] = {
    "E8": 65.8,
    "E20": 44.7,
    "E64": 20.5,
    "E128": 11.5,
}
PERIOD_EXPECTATION_TOLERANCE_S = 5e-5
RATE_EXPECTATION_TOLERANCE_HZ = 0.1

#: The retired planning expectation (``emissions x PRF + 1 ms``) the job logs still carry
#: as provenance. It is named here only so the two can be told apart: this module reads
#: every period from the stored per-profile time array and never from that field.
RETIRED_PERIOD_LAW = "emissions_per_profile x prf_us + 1 ms"
RETIRED_PERIOD_TRANSFER_S = 1e-3

CSV_NAME = "emissions-ladder.csv"
DOC_NAME = "emissions-ladder.json"
MD_NAME = "emissions-ladder.md"
FIGURES_DIRNAME = "figures"
STABILITY_FIGURE = "emissions-ladder-stability.png"
TEMPORAL_FIGURE = "emissions-ladder-temporal.png"
FIGURE_DPI = 150

TOLERANCE = 1e-9


class EmissionsLadderError(SparseIngestError):
    """The pass cannot produce the emissions ladder, or a caller asked for a wrong one."""


# ── models ─────────────────────────────────────────────────────────────


class TemporalValue(ValueModel):
    """One record's temporal view: its own achieved grid and its bandwidth price.

    Every number is measured from the record's stored per-profile time array. The
    achieved period is the **median** of the successive differences; the mean is
    published beside it, and it is what the whole retained span divided by the intervals
    gives. ``fixed_overhead_s`` is ``achieved - emissions x PRF``: the whole **fixed
    intercept** of the period, not the transfer term. It comprises the internal-emission
    term the manual's law carries (``INTERNAL_EMISSION_TERMS`` x PRF, 9.600 ms at 600 us)
    and the transfer term proper (the remainder), both published beside it, so the ladder's
    four levels can be read against one another without reading the intercept as a rate of
    anything else.
    """

    level: str
    label: str
    job: str
    profiles: int
    record_duration_s: float
    median_interval_s: float
    mean_interval_s: float
    achieved_period_s: float
    profile_rate_hz: float
    nyquist_hz: float
    frequency_resolution_hz: float
    emissions_times_prf_s: float
    fixed_overhead_s: float
    internal_emission_s: float
    transfer_term_s: float
    blocks: int
    block_duration_s: float
    block_bounds_s: tuple[float, ...]
    profiles_per_block_median: int
    profiles_per_block_min: int
    profiles_per_block_max: int
    first_block_start_s: float
    last_block_start_s: float


class AcfValue(ValueModel):
    """The autocorrelation of one record's stored series at one stated depth.

    The series is the record's **full** retained time series at that native gate (not the
    12 s window): the pass's surplus is part of the temporal view. The autocorrelation is
    the biased normalized autocovariance, the same convention
    :func:`udv_echo_process.analysis._native_grid.correlation_length` uses spatially.
    """

    level: str
    label: str
    requested_depth_mm: float
    depth_mm: float
    gate_index: int
    profiles: int
    lag1_autocorrelation: float
    first_lag_below_half: int
    first_lag_below_half_s: float
    reaches_half: bool
    series_mean_mm_s: float
    series_std_mm_s: float


class DifferenceValue(ValueModel):
    """One depth-resolved consecutive-level difference, on the common support.

    ``mean_difference_mm_s`` is the unweighted mean over the supported gates of the signed
    per-gate difference (left minus right); the extreme and its depth are the largest
    absolute per-gate value. ``knots_positive`` publishes the sign structure beside the
    mean, because a depth-averaged number hides it.
    """

    left_level: str
    right_level: str
    left_label: str
    right_label: str
    mean_difference_mm_s: float
    extreme_abs_mm_s: float
    extreme_signed_mm_s: float
    extreme_depth_mm: float
    knots_positive: int
    knots_negative: int
    gates: int


class StepValue(ValueModel):
    """One ladder step's reduction over the differences that realize it.

    For a step with E20 in it there are **four** differences, one per reference run, and
    the extreme is taken over all of them: E20 enters the ladder as four runs, never as an
    averaged profile.
    """

    left_level: str
    right_level: str
    differences: int
    extreme_abs_mm_s: float
    extreme_signed_mm_s: float
    extreme_depth_mm: float
    extreme_left_label: str
    extreme_right_label: str
    mean_difference_min_mm_s: float
    mean_difference_max_mm_s: float
    note: str


class BracketValue(ValueModel):
    """One scientific row against **one** of its two bracketing anchors.

    The two residuals of a row are the extremes of every linear interpolation over its
    bracket, because the pass carries no per-recording clock: a file name's
    ``YYYYMMDDTHHMMSS`` segment is the job's ``sweep_id``, identical for every point of
    that job, so no time-weight exists to place the row between its anchors.
    """

    level: str
    label: str
    job: str
    anchor: str
    anchor_kind: str
    residual_mean_mm_s: float
    residual_extreme_abs_mm_s: float
    residual_extreme_signed_mm_s: float
    residual_extreme_depth_mm: float
    knots_positive: int
    knots_negative: int
    gates: int
    job_anchor_floor_mm_s: float


class FloorBinding(ValueModel):
    """One floor this slice screens against, with its endpoint and where it applies.

    ``published_mm_s`` is the value the pass's own WP1/WP2 artefacts state, read from them
    for this pass; ``recomputed_mm_s`` is the same reduction rebuilt here from the
    recordings, so the screening number is checkable rather than trusted. The two
    endpoints are distinct quantities and a comparison is screened against exactly one of
    them.
    """

    name: str
    level: str | None
    statistic: str
    published_mm_s: float
    recomputed_mm_s: float
    depth_mm: float | None
    source: str
    endpoint: str
    applies_to: str
    unit: str


class PublishedFloor(ValueModel):
    """One floor as one of this pass's own WP1/WP2 artefacts states it.

    ``value_mm_s`` is the artefact's own number, read from it and never re-derived here;
    ``published_mm_s`` is that number at the ``PUBLISHED_FLOOR_DECIMALS`` the floors are
    published to, and it is the number this slice screens with. ``document`` names the
    artefact the number came from, so every floor row can be traced to the slice that
    measured it and to the pass that slice measured.
    """

    name: str
    document: str
    value_mm_s: float
    published_mm_s: float
    job: str | None = None
    pair: tuple[str, str] | None = None
    depth_mm: float | None = None


class PublishedFloors(ValueModel):
    """This pass's own published floors, read from its WP1 and WP2 artefacts.

    ``plan_fingerprint`` is the pass identity both documents state, and both are checked
    against: a document written by another sitting is refused by name rather than adopted,
    which is what keeps a second pass from being screened against the first pass's
    campaign.
    """

    plan_fingerprint: str
    directory: str
    documents: tuple[str, ...]
    depth_resolved: PublishedFloor
    depth_averaged: PublishedFloor
    job_anchors: tuple[PublishedFloor, ...]


class PredictionValue(ValueModel):
    """The WP4 request's expected achieved period for one level, beside the measurement.

    The expected numbers are the reviewer's own, stated to three significant figures; the
    measurement is this pass's, taken from the stored timestamps. They are compared within
    the stated tolerance and a disagreement would be a published difference, not a silent
    adoption.
    """

    level: str
    expected_period_s: float
    expected_rate_hz: float
    measured_period_s: float
    measured_rate_hz: float
    period_difference_s: float
    rate_difference_hz: float
    period_tolerance_s: float
    rate_tolerance_hz: float
    records_compared: int
    agrees: bool


class E128Observation(ValueModel):
    """WP1's ``e128`` finding, examined depth-resolved.

    The row sits larger than both of its bracketing anchors in the depth-averaged mean.
    This model says how much of that is a contiguous depth region and how much is a few
    gates, and it carries the floors the residual sits with, so the reading cannot be
    mistaken for an emissions effect.
    """

    label: str
    job: str
    residual_mean_vs_begin_mm_s: float
    residual_mean_vs_mid_mm_s: float
    extreme_vs_begin_abs_mm_s: float
    extreme_vs_begin_signed_mm_s: float
    extreme_vs_begin_depth_mm: float
    extreme_vs_mid_abs_mm_s: float
    extreme_vs_mid_signed_mm_s: float
    extreme_vs_mid_depth_mm: float
    gates: int
    knots_positive_vs_begin: int
    knots_positive_vs_mid: int
    longest_positive_run_knots_vs_begin: int
    longest_positive_run_span_mm_vs_begin: tuple[float, float]
    longest_positive_run_knots_vs_mid: int
    longest_positive_run_span_mm_vs_mid: tuple[float, float]
    same_sign_region_around_extreme_mm_vs_begin: tuple[float, float]
    same_sign_region_around_extreme_mm_vs_mid: tuple[float, float]
    top_three_knots_share_of_absolute_sum: float
    job_anchor_floor_mm_s: float
    ratio_to_job_anchor_floor_vs_begin: float
    ratio_to_job_anchor_floor_vs_mid: float
    ratio_to_depth_resolved_floor_vs_begin: float
    ratio_to_depth_resolved_floor_vs_mid: float
    reading: str


class DepthResolved(ArrayModel):
    """The seven records' supported mean profiles, the nine consecutive differences and
    the six bracketing residuals, on the one shared native gate grid."""

    depths_mm: array_field(np.float64, rank=1)
    e8: array_field(np.float64, rank=1)
    cr1: array_field(np.float64, rank=1)
    cr2: array_field(np.float64, rank=1)
    cr3: array_field(np.float64, rank=1)
    cr4: array_field(np.float64, rank=1)
    e64: array_field(np.float64, rank=1)
    e128: array_field(np.float64, rank=1)
    e8_minus_cr1: array_field(np.float64, rank=1)
    e8_minus_cr2: array_field(np.float64, rank=1)
    e8_minus_cr3: array_field(np.float64, rank=1)
    e8_minus_cr4: array_field(np.float64, rank=1)
    cr1_minus_e64: array_field(np.float64, rank=1)
    cr2_minus_e64: array_field(np.float64, rank=1)
    cr3_minus_e64: array_field(np.float64, rank=1)
    cr4_minus_e64: array_field(np.float64, rank=1)
    e64_minus_e128: array_field(np.float64, rank=1)
    e8_minus_ctrl_begin: array_field(np.float64, rank=1)
    e8_minus_ctrl_mid: array_field(np.float64, rank=1)
    e64_minus_ctrl_begin: array_field(np.float64, rank=1)
    e64_minus_ctrl_mid: array_field(np.float64, rank=1)
    e128_minus_ctrl_begin: array_field(np.float64, rank=1)
    e128_minus_ctrl_mid: array_field(np.float64, rank=1)


class AcfCurves(ArrayModel):
    """The autocorrelation curves the temporal figure draws, one per record.

    Each curve starts at lag 1 and runs to the lag nearest :data:`ACF_MAX_LAG_S` of that
    record's own achieved period. The lag axis is not published as an array: it is the
    curve's index times the record's own published achieved period, which is stated in the
    document and in the figure.
    """

    acf_e8: array_field(np.float64, rank=1)
    acf_cr1: array_field(np.float64, rank=1)
    acf_cr2: array_field(np.float64, rank=1)
    acf_cr3: array_field(np.float64, rank=1)
    acf_cr4: array_field(np.float64, rank=1)
    acf_e64: array_field(np.float64, rank=1)
    acf_e128: array_field(np.float64, rank=1)


class RecordValue(ValueModel):
    """One recording of the ladder, with its own statistics and its own temporal grid."""

    level: str
    label: str
    job: str
    step: int
    order: int
    relative_path: str
    evidence: str
    burst_length: int
    emissions_per_profile: int
    gates: int
    resolution_mm: float
    supported_gates: int
    profiles_full: int
    profiles_window: int
    statistics: dict[str, float]


class LevelValue(ValueModel):
    """One level of the ladder: its evidence, its records and its stated variation.

    The level carries **no** averaged profile and no averaged statistics: for E20 the four
    runs are the evidence, and its ``stated_variation_mm_s`` is the spread over those four
    runs rather than any mean of them.
    """

    level: str
    emissions_per_profile: int
    condition: dict[str, float]
    evidence: str
    records: tuple[str, ...]
    jobs: tuple[str, ...]
    anchor_labels: tuple[str, ...]
    stated_variation_mm_s: float
    stated_variation_kind: str
    stated_variation_basis: str
    note: str


class EmissionsLadder(ValueModel):
    """The WP4 result: four levels, two views, the floors and the gate that holds them."""

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    analysis_commit: str
    window_s: float
    window_revolutions: int
    support_min_mm: float
    support_max_mm: float
    reference_window_gates: int
    block_duration_s: float
    levels: tuple[LevelValue, ...]
    records: tuple[RecordValue, ...]
    temporal: tuple[TemporalValue, ...]
    acf: tuple[AcfValue, ...]
    differences: tuple[DifferenceValue, ...]
    steps: tuple[StepValue, ...]
    brackets: tuple[BracketValue, ...]
    floors: tuple[FloorBinding, ...]
    published_floors: PublishedFloors
    predictions: tuple[PredictionValue, ...]
    e128_observation: E128Observation
    depth_resolved: DepthResolved
    acf_curves: AcfCurves
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every WP4 gate check holds."""
        return all(self.checks.values())


# ── the measurement ────────────────────────────────────────────────────


class _Record(NamedTuple):
    """One record of the ladder, decoded, reduced and timed."""

    level: str
    point: DecodedPoint
    depths: np.ndarray
    statistics: dict[str, float]
    block: np.ndarray
    stamps: np.ndarray
    timing: TemporalValue
    acf: tuple[AcfValue, ...]
    curve: np.ndarray


class _Segmentation(NamedTuple):
    """One record's equal-physical-duration blocks."""

    blocks: int
    block_duration_s: float
    bounds_s: tuple[float, ...]
    counts: tuple[int, ...]
    median_profiles: int
    min_profiles: int
    max_profiles: int


def _condition_of(point: DecodedPoint) -> dict[str, float]:
    """The record's decoded condition, in the terms the ladder declares it."""
    return {
        "burst_length": float(point.config.burst_length or 0),
        "emissions_per_profile": float(point.config.emissions_per_profile or 0),
        "prf_us": 1e6 / float(point.config.pulse_repetition_freq_hz or 0),
        "resolution_mm": float(point.config.resolution_mm or 0.0),
        "n_gates": float(point.config.n_gates or 0),
    }


def _unit_of(statistic: str) -> str:
    """``mm/s`` for every velocity statistic, dimensionless for the zero fraction."""
    return "dimensionless" if statistic == "zero_fraction" else "mm/s"


def _time_array(point: DecodedPoint) -> np.ndarray:
    """One record's stored per-profile timestamps, or a refusal naming what is missing.

    The achieved grid is a measurement of the file's own stored time array. A record
    without one — absent, short, non-finite or not strictly increasing — is **refused**:
    the job log's retired ``timing.target_s`` records the planning expectation of the day,
    it is provenance rather than a timestamp, and a slice that fell back to it would be
    publishing that expectation as an observation of this recording.
    """
    raw = getattr(point, "time_s", None)
    if raw is None:
        raise EmissionsLadderError(
            f"{point.relative_path}: no per-profile time array, so the achieved period "
            "cannot be measured from the stored timestamps. The retired planning "
            f"expectation ({RETIRED_PERIOD_LAW}) is not a substitute for one and is not "
            "used here"
        )
    stamps = np.asarray(raw, dtype=float).reshape(-1)
    profiles = int(np.asarray(point.values).shape[0])
    if stamps.size != profiles:
        raise EmissionsLadderError(
            f"{point.relative_path}: {stamps.size} stored profile timestamps for "
            f"{profiles} profiles; the achieved grid is the file's own and is not "
            "reconstructed from a declared period"
        )
    if stamps.size < 2:
        raise EmissionsLadderError(
            f"{point.relative_path}: its stored time array holds {stamps.size} entry(ies); "
            "a period needs at least two"
        )
    if not np.all(np.isfinite(stamps)) or not np.all(np.diff(stamps) > 0.0):
        raise EmissionsLadderError(
            f"{point.relative_path}: its stored profile timestamps are not finite and "
            "strictly increasing, so no successive difference is a period"
        )
    return stamps


def _segment(stamps: np.ndarray, block_duration_s: float) -> _Segmentation:
    """Cut one record into equal **physical-duration** blocks from its first timestamp.

    Every block is exactly ``block_duration_s`` long and half-open, so the blocks of two
    levels cover the same durations although their profile counts differ by a factor of
    5.7. The trailing part of a record shorter than one block is not a block and is not
    counted anywhere.
    """
    span = float(stamps[-1] - stamps[0])
    blocks = int(span // block_duration_s)
    if blocks < 1:
        raise EmissionsLadderError(
            f"a record of {span!r} s does not hold one whole {block_duration_s:g} s block; "
            "a physical-duration segmentation compares equal durations and would have "
            "nothing to compare"
        )
    bounds = tuple(
        float(stamps[0] + index * block_duration_s) for index in range(blocks + 1)
    )
    counts = tuple(
        int(np.count_nonzero((stamps >= bounds[index]) & (stamps < bounds[index + 1])))
        for index in range(blocks)
    )
    if min(counts) < 1:
        raise EmissionsLadderError(
            f"a {block_duration_s:g} s block of this record holds no profile at all: the "
            "block duration exceeds the level's own achieved grid"
        )
    return _Segmentation(
        blocks=blocks,
        block_duration_s=block_duration_s,
        bounds_s=bounds,
        counts=counts,
        median_profiles=int(np.median(counts)),
        min_profiles=int(min(counts)),
        max_profiles=int(max(counts)),
    )


def _timing(
    level: str,
    point: DecodedPoint,
    stamps: np.ndarray,
    segmentation: _Segmentation,
) -> TemporalValue:
    """One record's temporal view, every number measured from ``stamps``."""
    intervals = np.diff(stamps)
    span = float(stamps[-1] - stamps[0])
    emissions = float(point.config.emissions_per_profile or 0)
    prf_us = 1e6 / float(point.config.pulse_repetition_freq_hz or 0)
    period = float(np.median(intervals))
    if not math.isfinite(period) or period <= 0.0:
        raise EmissionsLadderError(
            f"{point.relative_path}: the achieved profile period is {period!r}; a level "
            "with no positive period has no grid to compare"
        )
    rate = 1.0 / period
    emissions_times_prf = emissions * prf_us * 1e-6
    return TemporalValue(
        level=level,
        label=str(point.binding.point.label),
        job=str(point.binding.job.job),
        profiles=int(stamps.size),
        record_duration_s=span,
        median_interval_s=period,
        mean_interval_s=float(np.mean(intervals)),
        achieved_period_s=period,
        profile_rate_hz=rate,
        nyquist_hz=0.5 * rate,
        frequency_resolution_hz=1.0 / span,
        emissions_times_prf_s=emissions_times_prf,
        fixed_overhead_s=period - emissions_times_prf,
        internal_emission_s=INTERNAL_EMISSION_TERMS * prf_us * 1e-6,
        transfer_term_s=period
        - emissions_times_prf
        - INTERNAL_EMISSION_TERMS * prf_us * 1e-6,
        blocks=segmentation.blocks,
        block_duration_s=segmentation.block_duration_s,
        block_bounds_s=segmentation.bounds_s,
        profiles_per_block_median=segmentation.median_profiles,
        profiles_per_block_min=segmentation.min_profiles,
        profiles_per_block_max=segmentation.max_profiles,
        first_block_start_s=segmentation.bounds_s[0],
        last_block_start_s=segmentation.bounds_s[-2],
    )


def _autocorrelation(series: np.ndarray) -> np.ndarray:
    """The biased normalized autocovariance of one series, from lag 0 to the last lag.

    ``acf[0]`` is 1 by construction and ``acf[k]`` is the correlation of the series with
    itself shifted by ``k`` profiles, each product carried over the overlapping samples
    and divided by the whole series' length and variance — the same convention the
    spatial correlation length uses on a gate profile.
    """
    values = np.asarray(series, dtype=float).reshape(-1)
    if values.size < 2:
        raise EmissionsLadderError(
            f"a series of {values.size} profile(s) has no lag: the autocorrelation needs "
            "at least two"
        )
    centred = values - float(np.mean(values))
    variance = float(np.mean(np.square(centred)))
    if variance == 0.0:
        raise EmissionsLadderError(
            "a constant series has no autocorrelation: this gate resolves no variation"
        )
    return np.correlate(centred, centred, mode="full")[values.size - 1 :] / (
        values.size * variance
    )


def _first_lag_below(acf: np.ndarray, level: float) -> tuple[int, bool]:
    """The first lag at or after 1 whose ``|acf|`` falls below ``level``, and whether one exists."""
    below = np.flatnonzero(np.abs(acf[1:]) < level)
    if below.size == 0:
        return int(acf.size - 1), False
    return int(below[0] + 1), True


def _acf_rows(
    record_level: str, point: DecodedPoint, depths: np.ndarray, period_s: float
) -> tuple[AcfValue, ...]:
    """One record's autocorrelation at each of the three stated depths, on the full record."""
    values = np.asarray(point.values, dtype=float)
    rows: list[AcfValue] = []
    for requested in ACF_DEPTHS_MM:
        gate = int(np.argmin(np.abs(depths - requested)))
        series = values[:, gate]
        acf = _autocorrelation(series)
        lag, reached = _first_lag_below(acf, ACF_HALF_LEVEL)
        rows.append(
            AcfValue(
                level=record_level,
                label=str(point.binding.point.label),
                requested_depth_mm=float(requested),
                depth_mm=float(depths[gate]),
                gate_index=gate,
                profiles=int(series.size),
                lag1_autocorrelation=float(acf[1]),
                first_lag_below_half=lag,
                first_lag_below_half_s=float(lag * period_s),
                reaches_half=reached,
                series_mean_mm_s=float(np.mean(series)),
                series_std_mm_s=float(np.std(series)),
            )
        )
    return tuple(rows)


def _curve(series: np.ndarray, period_s: float) -> np.ndarray:
    """The autocorrelation curve the figure draws: lags 1..nearest ``ACF_MAX_LAG_S``."""
    acf = _autocorrelation(series)
    lags = max(1, round(ACF_MAX_LAG_S / period_s))
    return acf[1 : min(lags, acf.size - 1) + 1]


def _condition_matches(
    observed: Mapping[str, float], declared: Mapping[str, float]
) -> bool:
    """Whether a decoded condition is the declared one, in every declared cell."""
    if set(observed) != set(declared):
        return False
    return all(
        math.isclose(
            float(observed[key]), float(declared[key]), rel_tol=1e-9, abs_tol=1e-9
        )
        for key in declared
    )


def _require_record(
    level: str, label: str, job: str, point: DecodedPoint, decoded: PassDecoding
) -> np.ndarray:
    """Refuse a record that is not the level's own, and return its supported depths."""
    if str(point.binding.point.label) != label:
        raise EmissionsLadderError(
            f"level {level}: asked for {label!r}, the pass returned "
            f"{point.binding.point.label!r}"
        )
    if str(point.binding.job.job) != job:
        raise EmissionsLadderError(
            f"level {level}: {label!r} decodes to job {point.binding.job.job!r}, the "
            f"level's source is {job!r}"
        )
    observed = _condition_of(point)
    declared = DECLARED_CONDITIONS[level]
    if not _condition_matches(observed, declared):
        raise EmissionsLadderError(
            f"level {level}: {label!r} decodes to {observed}, the level's declared "
            f"condition is {declared}"
        )
    gates, resolution = (
        int(point.values.shape[1]),
        float(point.config.resolution_mm or 0.0),
    )
    if gates != REFERENCE_WINDOW[1] or not math.isclose(
        resolution, REFERENCE_WINDOW[0], rel_tol=1e-9
    ):
        raise EmissionsLadderError(
            f"level {level}: {label!r} records {gates} gates at {resolution} mm, the "
            f"reference window is {REFERENCE_WINDOW[1]} gates at {REFERENCE_WINDOW[0]} mm"
        )
    return supported_gates(point, decoded.support_mm)


def _records(decoded: PassDecoding) -> dict[str, tuple[_Record, ...]]:
    """Every level's records, decoded, reduced and timed — or a refusal by name.

    Raises:
        EmissionsLadderError: for a level whose recording is not the one the ladder
            declares, a record at another condition or window than its level's, a record
            without a usable stored time array, or two records that do not share one
            native gate grid.
    """
    grid: np.ndarray | None = None
    out: dict[str, tuple[_Record, ...]] = {}
    for level in LEVEL_ORDER:
        sources = (
            E20_RUN_SOURCES
            if level == E20_LEVEL
            else ((SCIENTIFIC_SOURCES[level][0], SCIENTIFIC_SOURCES[level][1]),)
        )
        rows: list[_Record] = []
        for label, job in sources:
            point = decoded.by_label(label)
            depths = _require_record(level, label, job, point, decoded)
            if grid is None:
                grid = depths
            elif (
                depths.shape != grid.shape
                or float(np.abs(depths - grid).max()) > TOLERANCE
            ):
                raise EmissionsLadderError(
                    f"level {level}: {label!r} keeps its own native gate grid, which is "
                    "not the ladder's; every level is measured on the shared reference "
                    "window's own gates and this slice resamples nothing"
                )
            stamps = _time_array(point)
            period = float(np.median(np.diff(stamps)))
            segmentation = _segment(stamps, BLOCK_DURATION_S)
            statistics = {
                name: supported_mean_of(
                    point,
                    window_s=decoded.window_s,
                    support_mm=decoded.support_mm,
                    name=name,
                )
                for name in STATISTICS
            }
            block = gate_statistics(
                point, window_s=decoded.window_s, support_mm=decoded.support_mm
            )[RESIDUAL_STATISTIC]
            gate = int(np.argmin(np.abs(depths - ACF_DEPTHS_MM[0])))
            rows.append(
                _Record(
                    level=level,
                    point=point,
                    depths=depths,
                    statistics=statistics,
                    block=block,
                    stamps=stamps,
                    timing=_timing(level, point, stamps, segmentation),
                    acf=_acf_rows(level, point, depths, period),
                    curve=_curve(
                        np.asarray(point.values, dtype=float)[:, gate], period
                    ),
                )
            )
        out[level] = tuple(rows)
    return out


def _anchors(
    decoded: PassDecoding, job: str, reference: _Record
) -> dict[str, np.ndarray]:
    """The three block-local anchors of one job, as per-gate ``mean`` profiles.

    Their own recovered acquisition order must bracket the scientific row:
    ``ctrl-begin`` before it and ``ctrl-mid`` after it, which is what places a measurement
    inside its job when the pass carries no per-recording clock.
    """
    points = decoded.of_job(job)
    grids: dict[str, np.ndarray] = {}
    order = int(reference.point.binding.order)
    for label in ANCHOR_LABELS:
        matches = [point for point in points if str(point.binding.point.label) == label]
        if len(matches) != 1:
            raise EmissionsLadderError(
                f"job {job!r}: {len(matches)} recordings are labelled {label!r}, expected "
                "exactly one block-local anchor"
            )
        anchor = matches[0]
        if int(anchor.values.shape[1]) != int(
            reference.point.values.shape[1]
        ) or not np.array_equal(
            np.asarray(anchor.depths), np.asarray(reference.point.depths)
        ):
            raise EmissionsLadderError(
                f"job {job!r}: anchor {label!r} does not record the scientific row's "
                "native gate grid, so no same-grid residual exists"
            )
        grids[label] = gate_statistics(
            anchor, window_s=decoded.window_s, support_mm=decoded.support_mm
        )[RESIDUAL_STATISTIC]
    left = int(
        next(
            point
            for point in points
            if str(point.binding.point.label) == BRACKET_ANCHORS[0]
        ).binding.order
    )
    right = int(
        next(
            point
            for point in points
            if str(point.binding.point.label) == BRACKET_ANCHORS[1]
        ).binding.order
    )
    if not left < order < right:
        raise EmissionsLadderError(
            f"job {job!r}: the scientific row at order {order} is not bracketed by "
            f"{BRACKET_ANCHORS[0]!r} (order {left}) and {BRACKET_ANCHORS[1]!r} (order "
            f"{right}); the pass's controls are what place a measurement inside its job"
        )
    return grids


def _anchor_spreads(
    decoded: PassDecoding, records: Mapping[str, tuple[_Record, ...]]
) -> dict[str, float]:
    """Each single-recording job's own anchor spread of the depth-averaged window mean.

    It is the same reduction WP1 published as that job's floor: ``max - min`` over the
    job's three block-local anchors of the unweighted mean over the supported gates.
    """
    spreads: dict[str, float] = {}
    for level in LEVEL_ORDER:
        if level == E20_LEVEL:
            continue
        record = records[level][0]
        job = str(record.point.binding.job.job)
        grids = _anchors(decoded, job, record)
        by_label = {
            str(point.binding.point.label): point for point in decoded.of_job(job)
        }
        means = [
            supported_mean_of(
                by_label[label],
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=RESIDUAL_STATISTIC,
            )
            for label in ANCHOR_LABELS
        ]
        spreads[level] = float(max(means) - min(means))
        if len(grids) != len(ANCHOR_LABELS):
            raise EmissionsLadderError(
                f"job {job!r}: {len(grids)} anchors were reduced, expected "
                f"{len(ANCHOR_LABELS)}"
            )
    return spreads


# ── this pass's own published floors ───────────────────────────────────


def _published_number(value: object, *, where: str) -> float:
    """One number from a sibling artefact, refused by name when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EmissionsLadderError(f"{where} is not a number: {value!r}")
    if not math.isfinite(float(value)):
        raise EmissionsLadderError(f"{where} is not finite: {value!r}")
    return float(value)


def _published_pair(value: object, *, where: str) -> tuple[str, str] | None:
    """The run pair a reference endpoint is realized by, as the artefact names it."""
    if value is None:
        return None
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        return (str(value[0]), str(value[1]))
    raise EmissionsLadderError(f"{where} is not a pair of run labels: {value!r}")


def _published_block(value: object, *, where: str) -> Mapping[str, object]:
    """One nested block of a sibling artefact, refused by name when it is not one."""
    if not isinstance(value, dict):
        raise EmissionsLadderError(f"{where} is not a block: {value!r}")
    return value


def _published_floor(
    name: str,
    document: str,
    *,
    value_mm_s: float,
    job: str | None = None,
    pair: tuple[str, str] | None = None,
    depth_mm: float | None = None,
) -> PublishedFloor:
    """One floor at the artefact's own precision and at the published one."""
    return PublishedFloor(
        name=name,
        document=document,
        value_mm_s=value_mm_s,
        published_mm_s=round(value_mm_s, PUBLISHED_FLOOR_DECIMALS),
        job=job,
        pair=pair,
        depth_mm=depth_mm,
    )


def _published_floor_directory(report_dir: Path, plan_name: str) -> Path:
    """The directory this pass's WP1 and WP2 documents are read from: the report directory.

    One rule, the same one WP3 applies: the floors a slice screens with are the ones
    published beside the artefacts it is writing, read from the directory the caller named
    and nowhere else. A run into a scratch directory is therefore *not* silently screened
    against this pass's committed ``reports/<plan>`` copy — a substitution that would leave
    the published floors of one directory deciding the outcome recorded in another — it
    refuses and names the document that has to be there, which is exactly what a caller
    who wants the committed numbers gets by naming that directory instead.

    Neither copy could contribute another pass's numbers: the plan fingerprint is what makes
    the documents the pass's own, and the shared reader in
    :mod:`udv_echo_process.analysis._floor_documents` is what makes the *numbers* the ones
    those documents were reduced from — the document's ``table_sha256`` is checked against the
    table beside it, and every floor this slice screens with against that table's own row.
    """
    directory = Path(report_dir)
    for name in PUBLISHED_FLOOR_DOCUMENTS:
        if not (directory / name).is_file():
            raise EmissionsLadderError(
                f"{plan_name}'s {name} is missing under {directory.as_posix()!r}: this "
                "slice screens each pass against that pass's own published floors, so it "
                "reads WP1's and WP2's documents beside this run's artefacts and never "
                "substitutes a number of its own"
            )
    return directory


def _load_published_document(
    path: Path, plan_fingerprint: str, *, slice_name: str
) -> AuthenticatedFloor:
    """One sibling artefact, authenticated as this pass's own before anything is read from it.

    The checks live in :mod:`udv_echo_process.analysis._floor_documents`, which WP3 reads the
    same two documents through, so the two readers cannot drift apart: the document exists, is
    a JSON object, states a named gate that passed, names this pass's plan fingerprint, and
    publishes a ``table_sha256`` that is the digest of the table beside it.
    """
    try:
        return read_floor_document(
            path.parent,
            path.name,
            slice_name=slice_name,
            plan_fingerprint=plan_fingerprint,
        )
    except FloorDocumentError as exc:
        raise EmissionsLadderError(str(exc)) from None


def _require_agrees(
    stated: float, tabulated: float, *, where: str, quantity: str
) -> None:
    """Refuse unless the document's floor is the number its authenticated table carries."""
    try:
        require_agrees(stated, tabulated, where=where, quantity=quantity)
    except FloorDocumentError as exc:
        raise EmissionsLadderError(str(exc)) from None


def _tabulated_spread(anchors: AuthenticatedFloor, job: str) -> float:
    """The spread the authenticated anchor table carries for one job, or a refusal."""
    try:
        return anchors.anchor_spread_mm_s(job, statistic=RESIDUAL_STATISTIC)
    except FloorDocumentError as exc:
        raise EmissionsLadderError(str(exc)) from None


def _tabulated_endpoints(reference: AuthenticatedFloor) -> ReferenceEndpoints:
    """Both reference endpoints, as the authenticated reference table carries them."""
    try:
        return reference.reference_endpoints()
    except FloorDocumentError as exc:
        raise EmissionsLadderError(str(exc)) from None


def _require_same_pair(
    document: AuthenticatedFloor,
    path: str,
    stated: tuple[str, str],
    tabulated: tuple[str, str],
) -> None:
    """Refuse unless the pair a document says an endpoint came from is its table's pair."""
    if stated != tabulated:
        raise EmissionsLadderError(
            f"{document.slice_name}'s {document.name} publishes {path} as the pair "
            f"{stated!r}, but the authenticated table carries that endpoint from "
            f"{tabulated!r}: the endpoint and the pair it was reduced from have to be the "
            "same measurement"
        )


def read_published_floors(
    report_dir: Path = REPORT_DIR,
    *,
    plan_name: str,
    plan_fingerprint: str,
) -> PublishedFloors:
    """This pass's own WP1 and WP2 floors, read from the pass's committed artefacts.

    ``plan_name`` and ``plan_fingerprint`` are the pass being measured, as the frozen WP0
    ingest decodes them. The fingerprint is what both documents must state, so a document
    written by another sitting is refused by name instead of adopted.

    Raises:
        EmissionsLadderError: when neither candidate directory holds both documents, when
            either cannot be read, when either was written by another pass or states that
            its own gate did not pass, when it does not state the floor in the statistic
            this slice screens in, or when a floor it must carry is not there.
    """
    directory = _published_floor_directory(report_dir, plan_name)
    anchors_path = directory / ANCHOR_FLOOR_DOC
    reference_path = directory / REFERENCE_FLOOR_DOC
    anchors = _load_published_document(anchors_path, plan_fingerprint, slice_name="WP1")
    reference = _load_published_document(
        reference_path, plan_fingerprint, slice_name="WP2"
    )

    entries = anchors.document.get("jobs")
    if not isinstance(entries, list):
        raise EmissionsLadderError(
            f"{anchors_path.as_posix()} states no jobs list: the per-job anchor spreads "
            "this slice screens with are read from it"
        )
    job_anchors: list[PublishedFloor] = []
    for index, entry in enumerate(entries):
        where = f"{anchors_path.as_posix()}: jobs[{index}]"
        block = _published_block(entry, where=where)
        job = str(block.get("job") or "")
        if not job:
            raise EmissionsLadderError(f"{where} states no job name")
        spread = _published_block(block.get("spread"), where=f"{where} 'spread'")
        value_mm_s = _published_number(
            spread.get(RESIDUAL_STATISTIC),
            where=f"{where}: spread[{RESIDUAL_STATISTIC!r}]",
        )
        _require_agrees(
            value_mm_s,
            _tabulated_spread(anchors, job),
            where=f"WP1's {ANCHOR_FLOOR_DOC}",
            quantity=f"job {job!r}'s anchor spread",
        )
        job_anchors.append(
            _published_floor(
                f"job_anchors_{job}",
                ANCHOR_FLOOR_DOC,
                value_mm_s=value_mm_s,
                job=job,
            )
        )

    floor = _published_block(
        reference.document.get("floor"), where=f"{reference_path}: 'floor'"
    )
    statistic = str(floor.get("statistic") or "")
    if statistic != RESIDUAL_STATISTIC:
        raise EmissionsLadderError(
            f"{reference_path.as_posix()} states its reference floors in {statistic!r}, "
            f"this slice screens in {RESIDUAL_STATISTIC!r}: the two numbers would not be "
            "like for like"
        )
    resolved = _published_block(
        floor.get("depth_resolved"), where=f"{reference_path}: floor.depth_resolved"
    )
    averaged = _published_block(
        floor.get("depth_averaged"), where=f"{reference_path}: floor.depth_averaged"
    )
    resolved_value = _published_number(
        resolved.get("value_mm_s"),
        where=f"{reference_path}: floor.depth_resolved.value_mm_s",
    )
    resolved_depth = _published_number(
        resolved.get("depth_mm"),
        where=f"{reference_path}: floor.depth_resolved.depth_mm",
    )
    resolved_pair = _published_pair(
        resolved.get("pair"),
        where=f"{reference_path}: floor.depth_resolved.pair",
    )
    averaged_value = _published_number(
        averaged.get("value_mm_s"),
        where=f"{reference_path}: floor.depth_averaged.value_mm_s",
    )
    averaged_pair = _published_pair(
        averaged.get("pair"),
        where=f"{reference_path}: floor.depth_averaged.pair",
    )
    endpoints = _tabulated_endpoints(reference)
    _require_agrees(
        resolved_value,
        endpoints.depth_resolved_value_mm_s,
        where=f"WP2's {REFERENCE_FLOOR_DOC}",
        quantity="the depth-resolved endpoint",
    )
    _require_agrees(
        resolved_depth,
        endpoints.depth_resolved_depth_mm,
        where=f"WP2's {REFERENCE_FLOOR_DOC}",
        quantity="the depth-resolved endpoint's depth",
    )
    _require_same_pair(
        reference,
        "floor.depth_resolved.pair",
        resolved_pair,
        endpoints.depth_resolved_pair,
    )
    _require_agrees(
        averaged_value,
        endpoints.depth_averaged_value_mm_s,
        where=f"WP2's {REFERENCE_FLOOR_DOC}",
        quantity="the depth-averaged endpoint",
    )
    _require_same_pair(
        reference,
        "floor.depth_averaged.pair",
        averaged_pair,
        endpoints.depth_averaged_pair,
    )
    return PublishedFloors(
        plan_fingerprint=plan_fingerprint,
        directory=directory.as_posix(),
        documents=PUBLISHED_FLOOR_DOCUMENTS,
        depth_resolved=_published_floor(
            "reference_depth_resolved",
            REFERENCE_FLOOR_DOC,
            value_mm_s=resolved_value,
            depth_mm=resolved_depth,
            pair=resolved_pair,
        ),
        depth_averaged=_published_floor(
            "reference_depth_averaged",
            REFERENCE_FLOOR_DOC,
            value_mm_s=averaged_value,
            pair=averaged_pair,
        ),
        job_anchors=tuple(job_anchors),
    )


def published_job_floor(published: PublishedFloors, job: str) -> PublishedFloor:
    """This pass's own anchor spread for one job, by the job's name."""
    for floor in published.job_anchors:
        if floor.job == job:
            return floor
    raise EmissionsLadderError(
        f"the pass's own {ANCHOR_FLOOR_DOC} carries no anchor spread for job {job!r}: it "
        f"carries {sorted(str(floor.job) for floor in published.job_anchors)}"
    )


def science_jobs() -> tuple[str, ...]:
    """The three jobs that hold this ladder's single-recording levels, in ladder order."""
    return tuple(
        SCIENTIFIC_SOURCES[level][1] for level in LEVEL_ORDER if level != E20_LEVEL
    )


def published_floor_for(
    published: PublishedFloors, row: FloorBinding
) -> PublishedFloor:
    """This pass's own copy of one floor row, by the name the row carries."""
    if row.name == "reference_depth_resolved":
        return published.depth_resolved
    if row.name == "reference_depth_averaged":
        return published.depth_averaged
    source = SCIENTIFIC_SOURCES.get(row.level or "")
    if source is None:
        raise EmissionsLadderError(
            f"floor row {row.name!r} names no level of this ladder"
        )
    return published_job_floor(published, source[1])


def _brackets(
    decoded: PassDecoding,
    records: Mapping[str, tuple[_Record, ...]],
    published: PublishedFloors,
) -> tuple[BracketValue, ...]:
    """Every single-recording level against each of its two bracketing anchors."""
    rows: list[BracketValue] = []
    for level in LEVEL_ORDER:
        if level == E20_LEVEL:
            continue
        record = records[level][0]
        job = str(record.point.binding.job.job)
        grids = _anchors(decoded, job, record)
        for anchor in BRACKET_ANCHORS:
            residual = record.block - grids[anchor]
            worst = int(np.argmax(np.abs(residual)))
            rows.append(
                BracketValue(
                    level=level,
                    label=str(record.point.binding.point.label),
                    job=job,
                    anchor=anchor,
                    anchor_kind=(
                        "block-local anchor control: the reference window at this job's "
                        "own condition, not a realization of the reference condition"
                    ),
                    residual_mean_mm_s=float(np.mean(residual)),
                    residual_extreme_abs_mm_s=float(abs(residual[worst])),
                    residual_extreme_signed_mm_s=float(residual[worst]),
                    residual_extreme_depth_mm=float(record.depths[worst]),
                    knots_positive=int(np.count_nonzero(residual > 0.0)),
                    knots_negative=int(np.count_nonzero(residual < 0.0)),
                    gates=int(residual.size),
                    job_anchor_floor_mm_s=published_job_floor(
                        published, job
                    ).published_mm_s,
                )
            )
    return tuple(rows)


def _differences(
    records: Mapping[str, tuple[_Record, ...]], depths: np.ndarray
) -> tuple[DifferenceValue, ...]:
    """The consecutive levels' signed per-gate differences, one per pair of records.

    A step with E20 in it contributes one difference per reference run: the four runs are
    the level's evidence, and pooling them into one profile would destroy exactly the
    variation this slice has to state.
    """
    rows: list[DifferenceValue] = []
    for left_level, right_level in DIFFERENCE_STEPS:
        for left in records[left_level]:
            for right in records[right_level]:
                difference = left.block - right.block
                worst = int(np.argmax(np.abs(difference)))
                rows.append(
                    DifferenceValue(
                        left_level=left_level,
                        right_level=right_level,
                        left_label=str(left.point.binding.point.label),
                        right_label=str(right.point.binding.point.label),
                        mean_difference_mm_s=float(np.mean(difference)),
                        extreme_abs_mm_s=float(abs(difference[worst])),
                        extreme_signed_mm_s=float(difference[worst]),
                        extreme_depth_mm=float(depths[worst]),
                        knots_positive=int(np.count_nonzero(difference > 0.0)),
                        knots_negative=int(np.count_nonzero(difference < 0.0)),
                        gates=int(difference.size),
                    )
                )
    return tuple(rows)


def _steps(differences: Sequence[DifferenceValue]) -> tuple[StepValue, ...]:
    """One reduction per ladder step, taken over every difference that realizes it."""
    rows: list[StepValue] = []
    for left_level, right_level in DIFFERENCE_STEPS:
        pairs = [
            row
            for row in differences
            if (row.left_level, row.right_level) == (left_level, right_level)
        ]
        if not pairs:
            raise EmissionsLadderError(
                f"step {left_level}->{right_level} holds no difference; every ladder step "
                "must be realized by the records the ladder names"
            )
        worst = max(pairs, key=lambda row: row.extreme_abs_mm_s)
        means = [row.mean_difference_mm_s for row in pairs]
        rows.append(
            StepValue(
                left_level=left_level,
                right_level=right_level,
                differences=len(pairs),
                extreme_abs_mm_s=worst.extreme_abs_mm_s,
                extreme_signed_mm_s=worst.extreme_signed_mm_s,
                extreme_depth_mm=worst.extreme_depth_mm,
                extreme_left_label=worst.left_label,
                extreme_right_label=worst.right_label,
                mean_difference_min_mm_s=min(means),
                mean_difference_max_mm_s=max(means),
                note=(
                    f"{len(pairs)} difference(s), one per pair of records: "
                    + (
                        "E20 enters this step as its four runs, so the step's extreme is "
                        "taken over four run-resolved differences and no averaged E20 "
                        "profile exists to take it from"
                        if E20_LEVEL in (left_level, right_level)
                        else "each level of this step has one recording"
                    )
                ),
            )
        )
    return tuple(rows)


def _depth_resolved(
    decoded: PassDecoding,
    records: Mapping[str, tuple[_Record, ...]],
    brackets: Sequence[BracketValue],
    depths: np.ndarray,
) -> DepthResolved:
    """The seven profiles, nine consecutive differences and six bracketing residuals."""
    store: dict[str, np.ndarray] = {"depths_mm": depths}
    for level in LEVEL_ORDER:
        for record in records[level]:
            store[str(record.point.binding.point.label)] = record.block
    for left_level, right_level in DIFFERENCE_STEPS:
        for left in records[left_level]:
            for right in records[right_level]:
                store[
                    f"{left.point.binding.point.label}_minus_"
                    f"{right.point.binding.point.label}"
                ] = left.block - right.block
    for row in brackets:
        record = records[row.level][0]
        store[f"{row.label}_minus_{row.anchor.replace('-', '_')}"] = (
            record.block - _anchors(decoded, row.job, record)[row.anchor]
        )
    missing = sorted(set(DepthResolved.model_fields) - set(store))
    if missing:
        raise EmissionsLadderError(
            f"the depth-resolved block is incomplete: {missing} have no array"
        )
    return DepthResolved(**{name: store[name] for name in DepthResolved.model_fields})


def _floors(
    records: Mapping[str, tuple[_Record, ...]],
    spreads: Mapping[str, float],
    published: PublishedFloors,
) -> tuple[FloorBinding, ...]:
    """The five floors this slice screens against, recomputed from the recordings.

    The two reference endpoints are rebuilt from the four E20 runs: the largest absolute
    per-depth difference over their six ordered pairs (depth-resolved) and the largest
    absolute difference between their depth-averaged means (depth-averaged). The three
    per-job anchor floors are rebuilt from each emissions job's own three block-local
    anchor controls, whose own per-gate ``mean`` profiles this slice reads. Beside each
    recomputation sits the number **this pass's own** WP1/WP2 artefacts publish for it,
    read from those documents: the first sitting's numbers are not adopted here, and a
    disagreement between the two sides is what the gate above reports.
    """
    runs = records[E20_LEVEL]
    blocks = [record.block for record in runs]
    worst_abs, worst_depth = 0.0, float(runs[0].depths[0])
    for index, left in enumerate(blocks):
        for right in blocks[index + 1 :]:
            difference = left - right
            worst = int(np.argmax(np.abs(difference)))
            if float(abs(difference[worst])) > worst_abs:
                worst_abs = float(abs(difference[worst]))
                worst_depth = float(runs[0].depths[worst])
    means = [record.statistics["mean"] for record in runs]
    averaged = float(max(means) - min(means))

    rows = [
        FloorBinding(
            name="reference_depth_resolved",
            level=None,
            statistic=RESIDUAL_STATISTIC,
            published_mm_s=published.depth_resolved.published_mm_s,
            recomputed_mm_s=worst_abs,
            depth_mm=worst_depth,
            source=(
                "WP2's between-run reference floor, rebuilt here from the four E20 runs: "
                "the largest absolute per-depth window-mean difference over their six "
                "ordered pairs"
            ),
            endpoint="depth-resolved: one per-gate difference array, or its extreme",
            applies_to=(
                "every depth-resolved comparison on the common support - each per-gate "
                "difference and each per-gate extreme of this slice"
            ),
            unit="mm/s",
        ),
        FloorBinding(
            name="reference_depth_averaged",
            level=None,
            statistic=RESIDUAL_STATISTIC,
            published_mm_s=published.depth_averaged.published_mm_s,
            recomputed_mm_s=averaged,
            depth_mm=None,
            source=(
                "WP2's between-run reference floor's depth-averaged endpoint, rebuilt here "
                "from the four E20 runs: the largest absolute difference between their "
                "depth-averaged window means"
            ),
            endpoint=(
                "depth-averaged: one unweighted mean over the supported gates - the same "
                "reduction WP1's per-job floors use"
            ),
            applies_to=(
                "every depth-averaged comparison between two levels - the three ladder "
                "steps' mean differences - and the only endpoint like for like with WP1's "
                "per-job anchor floors"
            ),
            unit="mm/s",
        ),
    ]
    for level in LEVEL_ORDER:
        if level == E20_LEVEL:
            continue
        record = records[level][0]
        job = str(record.point.binding.job.job)
        rows.append(
            FloorBinding(
                name=f"job_anchors_{level.lower()}",
                level=level,
                statistic=RESIDUAL_STATISTIC,
                published_mm_s=published_job_floor(published, job).published_mm_s,
                recomputed_mm_s=spreads[level],
                depth_mm=None,
                source=(
                    f"WP1's per-job anchor floor for job {job!r}, rebuilt here from that "
                    "job's three block-local anchor controls"
                ),
                endpoint=(
                    "depth-averaged spread: max - min over the job's three block-local "
                    "anchors of the unweighted mean over the supported gates"
                ),
                applies_to=(
                    f"the residual of {record.point.binding.point.label!r} against each of "
                    "its two bracketing anchors, which is a comparison inside one job"
                ),
                unit="mm/s",
            )
        )
    return tuple(rows)


def _longest_positive_run(
    residual: np.ndarray, depths: np.ndarray
) -> tuple[int, float, float]:
    """The longest contiguous run of positive knots: its length and its depth span."""
    best = (0, 0, 0)
    start: int | None = None
    for index, value in enumerate(residual > 0.0):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start > best[0]:
                best = (index - start, start, index - 1)
            start = None
    if start is not None and residual.size - start > best[0]:
        best = (residual.size - start, start, residual.size - 1)
    if best[0] == 0:
        return 0, float(depths[0]), float(depths[0])
    return int(best[0]), float(depths[best[1]]), float(depths[best[2]])


def _same_sign_region(residual: np.ndarray, depths: np.ndarray) -> tuple[float, float]:
    """The contiguous same-sign region around the extreme, as a depth span."""
    worst = int(np.argmax(np.abs(residual)))
    sign = math.copysign(1.0, residual[worst])
    low = worst
    while low - 1 >= 0 and math.copysign(1.0, residual[low - 1]) == sign:
        low -= 1
    high = worst
    while high + 1 < residual.size and math.copysign(1.0, residual[high + 1]) == sign:
        high += 1
    return float(depths[low]), float(depths[high])


E128_READING = (
    "one realization larger than its two block-local anchors in the depth-averaged mean, "
    "of the same size as the floors this pass owns rather than far outside them, and "
    "carried mostly by a contiguous depth region on one side of the support. It is a "
    "difference between one recording and two recordings: it is not evidence that E128 "
    "caused a change, no screening outcome proves an axis effect, and the emissions axis "
    "stays one realization per level apart from E20's four runs"
)


def _e128_observation(
    decoded: PassDecoding,
    records: Mapping[str, tuple[_Record, ...]],
    brackets: Sequence[BracketValue],
    published: PublishedFloors,
) -> E128Observation:
    """WP1's ``e128`` finding, recomputed depth-resolved against both anchors."""
    record = records["E128"][0]
    rows = {row.anchor: row for row in brackets if row.level == "E128"}
    begin, mid = rows[BRACKET_ANCHORS[0]], rows[BRACKET_ANCHORS[1]]
    depths = record.depths
    curves = _bracketing_curves(decoded, record)
    begin_curve = curves[BRACKET_ANCHORS[0]]
    mid_curve = curves[BRACKET_ANCHORS[1]]
    run_begin = _longest_positive_run(begin_curve, depths)
    run_mid = _longest_positive_run(mid_curve, depths)
    ordered = np.sort(np.abs(begin_curve))[::-1]
    share = float(np.sum(ordered[:3]) / np.sum(ordered))
    floor = published_job_floor(
        published, str(record.point.binding.job.job)
    ).published_mm_s
    depth_floor = published.depth_resolved.published_mm_s
    return E128Observation(
        label=str(record.point.binding.point.label),
        job=str(record.point.binding.job.job),
        residual_mean_vs_begin_mm_s=begin.residual_mean_mm_s,
        residual_mean_vs_mid_mm_s=mid.residual_mean_mm_s,
        extreme_vs_begin_abs_mm_s=begin.residual_extreme_abs_mm_s,
        extreme_vs_begin_signed_mm_s=begin.residual_extreme_signed_mm_s,
        extreme_vs_begin_depth_mm=begin.residual_extreme_depth_mm,
        extreme_vs_mid_abs_mm_s=mid.residual_extreme_abs_mm_s,
        extreme_vs_mid_signed_mm_s=mid.residual_extreme_signed_mm_s,
        extreme_vs_mid_depth_mm=mid.residual_extreme_depth_mm,
        gates=begin.gates,
        knots_positive_vs_begin=begin.knots_positive,
        knots_positive_vs_mid=mid.knots_positive,
        longest_positive_run_knots_vs_begin=run_begin[0],
        longest_positive_run_span_mm_vs_begin=(run_begin[1], run_begin[2]),
        longest_positive_run_knots_vs_mid=run_mid[0],
        longest_positive_run_span_mm_vs_mid=(run_mid[1], run_mid[2]),
        same_sign_region_around_extreme_mm_vs_begin=_same_sign_region(
            begin_curve, depths
        ),
        same_sign_region_around_extreme_mm_vs_mid=_same_sign_region(mid_curve, depths),
        top_three_knots_share_of_absolute_sum=share,
        job_anchor_floor_mm_s=floor,
        ratio_to_job_anchor_floor_vs_begin=abs(begin.residual_mean_mm_s) / floor,
        ratio_to_job_anchor_floor_vs_mid=abs(mid.residual_mean_mm_s) / floor,
        ratio_to_depth_resolved_floor_vs_begin=(
            begin.residual_extreme_abs_mm_s / depth_floor
        ),
        ratio_to_depth_resolved_floor_vs_mid=(
            mid.residual_extreme_abs_mm_s / depth_floor
        ),
        reading=E128_READING,
    )


def _bracketing_curves(decoded: PassDecoding, record: _Record) -> dict[str, np.ndarray]:
    """One record's per-gate residual against each of its two bracketing anchors."""
    grids = _anchors(decoded, str(record.point.binding.job.job), record)
    return {anchor: record.block - grids[anchor] for anchor in BRACKET_ANCHORS}


# ── the build ──────────────────────────────────────────────────────────


def build_emissions_ladder(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    report_dir: Path = REPORT_DIR,
    analysis_commit: str | None = None,
) -> EmissionsLadder:
    """The emissions ladder of the committed pass, or a refusal by name.

    Raises:
        EmissionsLadderError: for anything the frozen WP0 ingest refuses — including the
            two sibling artefacts this pass's own floors are published in, which must be
            this pass's own and must have passed their own gate — and for a level whose
            recording is not the one the ladder declares, a record at another condition,
            window or native grid than its level's, a record without a usable stored
            per-profile time array, a job whose anchors do not bracket its scientific row,
            or a recomputed floor that does not reproduce the published one.
    """
    decoded = decode_pass(dataset_root, plan_path=plan_path)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise EmissionsLadderError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )
    published = read_published_floors(
        report_dir,
        plan_name=str(decoded.plan.plan),
        plan_fingerprint=decoded.plan_fingerprint,
    )
    records = _records(decoded)
    depths = records[LEVEL_ORDER[0]][0].depths
    spreads = _anchor_spreads(decoded, records)

    brackets = _brackets(decoded, records, published)
    differences = _differences(records, depths)
    steps = _steps(differences)
    floors = _floors(records, spreads, published)
    e128 = _e128_observation(decoded, records, brackets, published)
    predictions = _predictions(records)
    levels = _level_values(records, spreads)

    checks = _checks(
        decoded,
        commit,
        records,
        levels,
        differences,
        steps,
        brackets,
        floors,
        predictions,
        published,
    )
    return EmissionsLadder(
        dataset_root=decoded.dataset_root.as_posix(),
        plan=str(decoded.plan.plan),
        plan_path=Path(plan_path).as_posix(),
        plan_fingerprint=decoded.plan_fingerprint,
        analysis_commit=commit,
        window_s=decoded.window_s,
        window_revolutions=decoded.window_revolutions,
        support_min_mm=decoded.support_mm[0],
        support_max_mm=decoded.support_mm[1],
        reference_window_gates=REFERENCE_WINDOW[1],
        block_duration_s=BLOCK_DURATION_S,
        levels=levels,
        records=tuple(
            RecordValue(
                level=record.level,
                label=str(record.point.binding.point.label),
                job=str(record.point.binding.job.job),
                step=int(record.point.binding.job.step),
                order=int(record.point.binding.order),
                relative_path=record.point.relative_path,
                evidence=(
                    EVIDENCE_FOUR_RUNS if record.level == E20_LEVEL else EVIDENCE_SINGLE
                ),
                burst_length=int(record.point.config.burst_length or 0),
                emissions_per_profile=int(
                    record.point.config.emissions_per_profile or 0
                ),
                gates=int(record.point.values.shape[1]),
                resolution_mm=float(record.point.config.resolution_mm or 0.0),
                supported_gates=int(record.depths.size),
                profiles_full=int(record.point.values.shape[0]),
                profiles_window=_window_profiles(record.point, decoded.window_s),
                statistics=record.statistics,
            )
            for level in LEVEL_ORDER
            for record in records[level]
        ),
        temporal=tuple(
            record.timing for level in LEVEL_ORDER for record in records[level]
        ),
        acf=tuple(
            row
            for level in LEVEL_ORDER
            for record in records[level]
            for row in record.acf
        ),
        differences=differences,
        steps=steps,
        brackets=brackets,
        floors=floors,
        published_floors=published,
        predictions=predictions,
        e128_observation=e128,
        depth_resolved=_depth_resolved(decoded, records, brackets, depths),
        acf_curves=AcfCurves(
            **{
                f"acf_{record.point.binding.point.label}": record.curve
                for level in LEVEL_ORDER
                for record in records[level]
            }
        ),
        checks=checks,
    )


def _window_profiles(point: DecodedPoint, window_s: float) -> int:
    """How many profiles of a record fall inside the primary window."""
    stamps = np.asarray(point.time_s, dtype=float)
    return int(np.count_nonzero(stamps <= stamps[0] + window_s + TOLERANCE))


def _level_values(
    records: Mapping[str, tuple[_Record, ...]], spreads: Mapping[str, float]
) -> tuple[LevelValue, ...]:
    """The four levels, each with the evidence and the variation its evidence supports."""
    values: list[LevelValue] = []
    for level in LEVEL_ORDER:
        rows = records[level]
        labels = tuple(str(row.point.binding.point.label) for row in rows)
        jobs = tuple(str(row.point.binding.job.job) for row in rows)
        if level == E20_LEVEL:
            means = [row.statistics["mean"] for row in rows]
            variation = float(max(means) - min(means))
            kind = "between-run spread over the level's four runs"
            basis = (
                "max - min over the four reference runs' depth-averaged window means: the "
                "between-run variation this pass observes, which is WP2's own data. The "
                "four runs are published individually and no averaged profile stands for "
                "the level"
            )
            anchors: tuple[str, ...] = ()
            note = (
                "the reference level: four runs of one decoded condition, one per "
                "reference job, so its stated variation is a spread over runs rather "
                "than a within-job bracketing context"
            )
        else:
            variation = float(spreads[level])
            kind = "within-job anchor spread over the job's three block-local anchors"
            basis = (
                "max - min over the job's three block-local anchor controls of the "
                "depth-averaged window mean, this job's own floor: the bracketing context "
                "of the level's single scientific recording, not replication of the level"
            )
            anchors = ANCHOR_LABELS
            note = (
                "one scientific recording inside its own job's three block-local anchors: "
                "the anchors record this job's condition at the reference window, they are "
                "not realizations of the reference condition, and the level is one "
                "realization"
            )
        values.append(
            LevelValue(
                level=level,
                emissions_per_profile=int(
                    DECLARED_CONDITIONS[level]["emissions_per_profile"]
                ),
                condition=dict(DECLARED_CONDITIONS[level]),
                evidence=(
                    EVIDENCE_FOUR_RUNS if level == E20_LEVEL else EVIDENCE_SINGLE
                ),
                records=labels,
                jobs=jobs,
                anchor_labels=anchors,
                stated_variation_mm_s=variation,
                stated_variation_kind=kind,
                stated_variation_basis=basis,
                note=note,
            )
        )
    return tuple(values)


def _predictions(
    records: Mapping[str, tuple[_Record, ...]],
) -> tuple[PredictionValue, ...]:
    """The expected achieved periods beside this pass's own measurements."""
    rows: list[PredictionValue] = []
    for level in LEVEL_ORDER:
        measured = float(
            np.median([record.timing.achieved_period_s for record in records[level]])
        )
        rate = 1.0 / measured
        period_gap = measured - EXPECTED_PERIOD_S[level]
        rate_gap = rate - EXPECTED_RATE_HZ[level]
        rows.append(
            PredictionValue(
                level=level,
                expected_period_s=EXPECTED_PERIOD_S[level],
                expected_rate_hz=EXPECTED_RATE_HZ[level],
                measured_period_s=measured,
                measured_rate_hz=rate,
                period_difference_s=period_gap,
                rate_difference_hz=rate_gap,
                period_tolerance_s=PERIOD_EXPECTATION_TOLERANCE_S,
                rate_tolerance_hz=RATE_EXPECTATION_TOLERANCE_HZ,
                records_compared=len(records[level]),
                agrees=(
                    abs(period_gap) <= PERIOD_EXPECTATION_TOLERANCE_S
                    and abs(rate_gap) <= RATE_EXPECTATION_TOLERANCE_HZ
                ),
            )
        )
    return tuple(rows)


def _brackets_reproduce(
    decoded: PassDecoding,
    records: Mapping[str, tuple[_Record, ...]],
    brackets: Sequence[BracketValue],
) -> bool:
    """Whether every published bracketing residual equals a fresh recomputation.

    The bracket is rebuilt from the job's own two anchors and compared with what the
    slice published, including ``e128``'s two residuals and their sign structure: a
    published number that no longer follows from the recordings fails the gate rather
    than travelling.
    """
    published = {(row.level, row.anchor): row for row in brackets}
    for level in LEVEL_ORDER:
        if level == E20_LEVEL:
            continue
        record = records[level][0]
        grids = _anchors(decoded, str(record.point.binding.job.job), record)
        for anchor in BRACKET_ANCHORS:
            row = published.get((level, anchor))
            if row is None:
                return False
            residual = record.block - grids[anchor]
            worst = int(np.argmax(np.abs(residual)))
            if not (
                math.isclose(
                    float(np.mean(residual)), row.residual_mean_mm_s, abs_tol=1e-12
                )
                and math.isclose(
                    float(residual[worst]),
                    row.residual_extreme_signed_mm_s,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    float(record.depths[worst]),
                    row.residual_extreme_depth_mm,
                    abs_tol=1e-12,
                )
                and int(np.count_nonzero(residual > 0.0)) == row.knots_positive
            ):
                return False
    return True


def _checks(
    decoded: PassDecoding,
    commit: str,
    records: Mapping[str, tuple[_Record, ...]],
    levels: Sequence[LevelValue],
    differences: Sequence[DifferenceValue],
    steps: Sequence[StepValue],
    brackets: Sequence[BracketValue],
    floors: Sequence[FloorBinding],
    predictions: Sequence[PredictionValue],
    published: PublishedFloors,
) -> dict[str, bool]:
    """The WP4 gate: the structural facts that must hold before a level is published."""
    every = [row for level in LEVEL_ORDER for row in records[level]]
    counts = {level: len(records[level]) for level in LEVEL_ORDER}
    periods_from_stamps = all(
        math.isclose(
            record.timing.achieved_period_s,
            float(np.median(np.diff(_time_array(record.point)))),
            rel_tol=0.0,
            abs_tol=TOLERANCE,
        )
        and math.isclose(
            record.timing.median_interval_s,
            float(np.median(np.diff(record.stamps))),
            rel_tol=0.0,
            abs_tol=TOLERANCE,
        )
        for record in every
    )
    return {
        "four_levels_with_their_declared_conditions": (
            tuple(level.level for level in levels) == LEVEL_ORDER
            and all(
                _condition_matches(
                    _condition_of(record.point), DECLARED_CONDITIONS[level]
                )
                for level in LEVEL_ORDER
                for record in records[level]
            )
        ),
        "evidence_counts_are_the_declared_ones": counts
        == {"E8": 1, "E20": 4, "E64": 1, "E128": 1},
        "e20_is_four_runs_and_the_others_one_each": (
            len({str(row.point.binding.job.job) for row in records[E20_LEVEL]}) == 4
            and len({str(row.point.binding.point.label) for row in records[E20_LEVEL]})
            == 4
            and all(counts[level] == 1 for level in LEVEL_ORDER if level != E20_LEVEL)
        ),
        "e20_kept_as_four_runs_with_no_averaged_profile": (
            len({str(row.point.binding.point.label) for row in records[E20_LEVEL]}) == 4
            and all(
                name not in DepthResolved.model_fields
                for name in ("e20", "e20_mean_profile", "mean_profile")
            )
            and len({record.block.tobytes() for record in records[E20_LEVEL]}) == 4
            and len(
                [
                    row
                    for row in differences
                    if E20_LEVEL in (row.left_level, row.right_level)
                ]
            )
            == 8
        ),
        "the_levels_state_the_variation_their_evidence_supports": (
            all(
                level.stated_variation_mm_s > 0.0
                and (
                    level.stated_variation_kind.startswith("between-run")
                    if level.level == E20_LEVEL
                    else level.stated_variation_kind.startswith("within-job")
                )
                for level in levels
            )
            and math.isclose(
                next(
                    level.stated_variation_mm_s
                    for level in levels
                    if level.level == E20_LEVEL
                ),
                max(row.statistics["mean"] for row in records[E20_LEVEL])
                - min(row.statistics["mean"] for row in records[E20_LEVEL]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ),
        "achieved_periods_are_measured_from_the_stored_timestamps": periods_from_stamps,
        "periods_are_not_the_retired_planning_law": all(
            not math.isclose(
                record.timing.achieved_period_s,
                record.timing.emissions_times_prf_s + RETIRED_PERIOD_TRANSFER_S,
                rel_tol=0.0,
                abs_tol=TOLERANCE,
            )
            for record in every
        ),
        "segmentation_is_by_physical_duration": all(
            record.timing.block_duration_s == BLOCK_DURATION_S
            and record.timing.blocks >= 1
            and len(record.timing.block_bounds_s) == record.timing.blocks + 1
            and all(
                math.isclose(
                    record.timing.block_bounds_s[index + 1]
                    - record.timing.block_bounds_s[index],
                    BLOCK_DURATION_S,
                    rel_tol=0.0,
                    abs_tol=TOLERANCE,
                )
                for index in range(record.timing.blocks)
            )
            and record.timing.profiles_per_block_median
            == int(np.median(_segment(record.stamps, BLOCK_DURATION_S).counts))
            for record in every
        ),
        "profiles_per_block_fall_with_emissions": (
            len(
                {
                    level: records[level][0].timing.profiles_per_block_median
                    for level in LEVEL_ORDER
                }
            )
            == 4
            and records["E8"][0].timing.profiles_per_block_median
            > records[E20_LEVEL][0].timing.profiles_per_block_median
            > records["E64"][0].timing.profiles_per_block_median
            > records["E128"][0].timing.profiles_per_block_median
        ),
        "spectral_arithmetic_holds": all(
            math.isclose(
                record.timing.profile_rate_hz,
                1.0 / record.timing.achieved_period_s,
                rel_tol=1e-12,
            )
            and math.isclose(
                record.timing.nyquist_hz,
                0.5 * record.timing.profile_rate_hz,
                rel_tol=1e-12,
            )
            and math.isclose(
                record.timing.frequency_resolution_hz,
                1.0 / record.timing.record_duration_s,
                rel_tol=1e-12,
            )
            for record in every
        ),
        "the_renderer_expected_periods_are_checked": all(
            row.agrees for row in predictions
        ),
        "one_shared_native_grid": len({int(record.depths.size) for record in every})
        == 1
        and all(
            record.depths.shape == records[LEVEL_ORDER[0]][0].depths.shape
            and float(np.abs(record.depths - records[LEVEL_ORDER[0]][0].depths).max())
            <= TOLERANCE
            for record in every
        ),
        "differences_are_complete": len(differences)
        == sum(
            len(records[left]) * len(records[right]) for left, right in DIFFERENCE_STEPS
        ),
        "steps_are_the_three_consecutive_levels": tuple(
            (step.left_level, step.right_level) for step in steps
        )
        == DIFFERENCE_STEPS
        and all(
            step.differences
            == len(records[step.left_level]) * len(records[step.right_level])
            for step in steps
        ),
        "bracketing_is_recomputed_for_every_single_level": (
            len(brackets) == 2 * (len(LEVEL_ORDER) - 1)
            and all(
                row.job_anchor_floor_mm_s
                == published_job_floor(published, row.job).published_mm_s
                for row in brackets
            )
        ),
        "e128_bracketing_recomputed": _brackets_reproduce(decoded, records, brackets),
        "floors_are_stated_with_both_endpoints_and_reproduce": (
            len(floors) == 5
            and sum(floor.depth_mm is not None for floor in floors) == 1
            and all(
                math.isfinite(floor.recomputed_mm_s)
                and abs(floor.published_mm_s - floor.recomputed_mm_s)
                <= FLOOR_PUBLISHED_TOLERANCE_MM_S
                and floor.published_mm_s
                == round(
                    published_floor_for(published, floor).value_mm_s,
                    PUBLISHED_FLOOR_DECIMALS,
                )
                for floor in floors
            )
        ),
        "window_and_support_are_the_wp0_ones": (
            math.isclose(
                decoded.window_s, DESIGNED_WINDOW_S, rel_tol=0.0, abs_tol=1e-12
            )
            and decoded.support_mm[1] > decoded.support_mm[0]
        ),
        "analysis_commit": bool(commit),
    }


# ── artefacts ──────────────────────────────────────────────────────────


LEVEL_COLUMNS: tuple[str, ...] = (
    "level",
    "label",
    "job",
    "evidence",
    "burst_length",
    "emissions_per_profile",
    "gates",
    "resolution_mm",
    "supported_gates",
    "profiles_full",
    "profiles_window",
    "statistic",
    "value",
    "unit",
)

DIFFERENCE_COLUMNS: tuple[str, ...] = (
    "left_level",
    "right_level",
    "left_label",
    "right_label",
    "mean_difference_mm_s",
    "extreme_abs_mm_s",
    "extreme_signed_mm_s",
    "extreme_depth_mm",
    "knots_positive",
    "knots_negative",
    "gates",
    "unit",
)

BRACKET_COLUMNS: tuple[str, ...] = (
    "level",
    "label",
    "job",
    "anchor",
    "residual_mean_mm_s",
    "residual_extreme_abs_mm_s",
    "residual_extreme_signed_mm_s",
    "residual_extreme_depth_mm",
    "knots_positive",
    "knots_negative",
    "gates",
    "job_anchor_floor_mm_s",
    "unit",
)

TEMPORAL_COLUMNS: tuple[str, ...] = (
    "level",
    "label",
    "job",
    "profiles",
    "record_duration_s",
    "median_interval_s",
    "mean_interval_s",
    "achieved_period_s",
    "profile_rate_hz",
    "nyquist_hz",
    "frequency_resolution_hz",
    "emissions_times_prf_s",
    "fixed_overhead_s",
    "internal_emission_s",
    "transfer_term_s",
    "blocks",
    "block_duration_s",
    "profiles_per_block_median",
    "profiles_per_block_min",
    "profiles_per_block_max",
)

ACF_COLUMNS: tuple[str, ...] = (
    "level",
    "label",
    "requested_depth_mm",
    "depth_mm",
    "gate_index",
    "profiles",
    "lag1_autocorrelation",
    "first_lag_below_half",
    "first_lag_below_half_s",
    "reaches_half",
    "series_mean_mm_s",
    "series_std_mm_s",
)


def csv_text(model: EmissionsLadder) -> str:
    """Render ``emissions-ladder.csv``: five blocks, LF endings, one trailing newline.

    The blocks are told apart by their own header row and by their first column: the
    level statistics, the consecutive-level differences, the bracketing residuals, the
    temporal view and the autocorrelation at the stated depths.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(LEVEL_COLUMNS))
    for row in model.records:
        for statistic in STATISTICS:
            writer.writerow(
                [
                    row.level,
                    row.label,
                    row.job,
                    row.evidence,
                    format_cell(row.burst_length),
                    format_cell(row.emissions_per_profile),
                    format_cell(row.gates),
                    format_cell(row.resolution_mm),
                    format_cell(row.supported_gates),
                    format_cell(row.profiles_full),
                    format_cell(row.profiles_window),
                    statistic,
                    format_cell(row.statistics[statistic]),
                    _unit_of(statistic),
                ]
            )
    writer.writerow([])
    writer.writerow(list(DIFFERENCE_COLUMNS))
    for row in model.differences:
        writer.writerow(
            [
                row.left_level,
                row.right_level,
                row.left_label,
                row.right_label,
                format_cell(row.mean_difference_mm_s),
                format_cell(row.extreme_abs_mm_s),
                format_cell(row.extreme_signed_mm_s),
                format_cell(row.extreme_depth_mm),
                format_cell(row.knots_positive),
                format_cell(row.knots_negative),
                format_cell(row.gates),
                "mm/s",
            ]
        )
    writer.writerow([])
    writer.writerow(list(BRACKET_COLUMNS))
    for row in model.brackets:
        writer.writerow(
            [
                row.level,
                row.label,
                row.job,
                row.anchor,
                format_cell(row.residual_mean_mm_s),
                format_cell(row.residual_extreme_abs_mm_s),
                format_cell(row.residual_extreme_signed_mm_s),
                format_cell(row.residual_extreme_depth_mm),
                format_cell(row.knots_positive),
                format_cell(row.knots_negative),
                format_cell(row.gates),
                format_cell(row.job_anchor_floor_mm_s),
                "mm/s",
            ]
        )
    writer.writerow([])
    writer.writerow(list(TEMPORAL_COLUMNS))
    for row in model.temporal:
        writer.writerow(
            [
                row.level,
                row.label,
                row.job,
                format_cell(row.profiles),
                format_cell(row.record_duration_s),
                format_cell(row.median_interval_s),
                format_cell(row.mean_interval_s),
                format_cell(row.achieved_period_s),
                format_cell(row.profile_rate_hz),
                format_cell(row.nyquist_hz),
                format_cell(row.frequency_resolution_hz),
                format_cell(row.emissions_times_prf_s),
                format_cell(row.fixed_overhead_s),
                format_cell(row.internal_emission_s),
                format_cell(row.transfer_term_s),
                format_cell(row.blocks),
                format_cell(row.block_duration_s),
                format_cell(row.profiles_per_block_median),
                format_cell(row.profiles_per_block_min),
                format_cell(row.profiles_per_block_max),
            ]
        )
    writer.writerow([])
    writer.writerow(list(ACF_COLUMNS))
    for row in model.acf:
        writer.writerow(
            [
                row.level,
                row.label,
                format_cell(row.requested_depth_mm),
                format_cell(row.depth_mm),
                format_cell(row.gate_index),
                format_cell(row.profiles),
                format_cell(row.lag1_autocorrelation),
                format_cell(row.first_lag_below_half),
                format_cell(row.first_lag_below_half_s),
                format_cell(row.reaches_half),
                format_cell(row.series_mean_mm_s),
                format_cell(row.series_std_mm_s),
            ]
        )
    return buffer.getvalue()


#: The WP4-specific definitions the document records beside the shared WP0 ones.
DEFINITIONS: dict[str, str] = {
    "achieved_period_s": (
        "the profile period measured from the recording's own stored per-profile time "
        "array: the median of the successive differences of that array over the full "
        "retained record. It is never the job log's timing.target_s, which records the "
        f"retired planning expectation ({RETIRED_PERIOD_LAW}) and is not a measurement of "
        "this recording"
    ),
    "mean_interval_s": (
        "the mean of the same successive differences, equal to the retained span divided "
        "by one less than the profile count"
    ),
    "profile_rate_hz": "1 / achieved_period_s, the profiles the level records per second",
    "nyquist_hz": (
        "profile_rate_hz / 2: the highest fluctuation frequency the level's own grid can "
        "represent, since the profile series is sampled at the achieved period"
    ),
    "frequency_resolution_hz": (
        "1 / record_duration_s: the bin spacing of a spectrum taken over this record's own "
        "retained duration, which is the only duration the levels are compared at"
    ),
    "fixed_overhead_s": (
        "achieved_period_s minus emissions x prf: the whole fixed intercept of the achieved "
        "period - the part that is not the emissions block - and NOT the transfer term. It "
        "comprises internal_emission_s (the manual's law carries 16 PRF terms: 9.600 ms at "
        "600 us) and transfer_term_s (the remainder), both published beside it. It is a "
        "measurement of this pass's files, not a change to the planner's law and not an "
        "acquisition result"
    ),
    "internal_emission_s": (
        "16 x prf: the internal-emission term of the manual's period law, 9.600 ms at 600 us, "
        "identical at every level"
    ),
    "transfer_term_s": (
        "fixed_overhead_s minus internal_emission_s: the transfer term proper, the part of "
        "the fixed intercept the manual's 16 PRF terms do not account for"
    ),
    "block_duration_s": (
        "the physical duration every record is segmented by. The blocks are equal in "
        "duration and not in profile count, because the levels differ by a factor of 5.7 "
        "in profile rate: a fixed profile count would compare 15 ms of one level with "
        "87 ms of another"
    ),
    "profiles_per_block_median": (
        "the median across the record's own complete physical-duration blocks of how many "
        "of its profiles fall in one block; min and max are published beside it, because "
        "the counts jitter by one profile between blocks"
    ),
    "lag1_autocorrelation": (
        "the biased normalized autocovariance of the record's full stored series at one "
        "native gate, at lag 1 profile: the same convention the spatial correlation length "
        "uses on a gate profile. It is descriptive of that one series on that one record"
    ),
    "first_lag_below_half": (
        "the first lag, in profiles, at which the absolute autocorrelation falls below "
        "0.5, searched over the whole record; when it does not fall below 0.5 the field "
        "reports the last available lag and reaches_half is false"
    ),
    "stated_variation_mm_s": (
        "the level's own variation, from the evidence it has: for E20 the spread of its "
        "four runs' depth-averaged window means (between-run variation, WP2's own data), "
        "for E8/E64/E128 the spread of that job's three block-local anchors "
        "(within-job bracketing context). Neither is a confidence interval, and three "
        "anchors are three recordings rather than replicates"
    ),
    "depth_resolved_difference": (
        "the signed per-gate difference of two window-mean profiles on the common support, "
        "each profile computed on its own native gate grid with no interpolation or "
        "resampling. The extreme is the largest absolute per-gate value and its depth is "
        "reported with it"
    ),
    "residual_vs_anchor": (
        "a scientific row's per-gate window mean minus one bracketing anchor's, on the "
        "same grid. The pass carries no per-recording clock (a file name's "
        "YYYYMMDDTHHMMSS segment is the job's sweep_id, identical for every point of that "
        "job), so the row is reported against each bracketing anchor rather than at an "
        "invented instant between them"
    ),
}

#: The statements the document makes about what this slice does not claim.
NOT_HERE: tuple[str, ...] = (
    (
        "No causality from single realizations: E8, E64 and E128 are one recording each, so "
        "any difference they show from E20 or from their own anchors is an observed "
        "difference between recordings, not evidence that the emissions setting caused it"
    ),
    (
        "No plateau, optimum, threshold or separability claim: nothing here establishes that "
        "the velocity estimate stops improving at some level, and no comparison is a "
        "statistical distinguishability test"
    ),
    (
        "No pooled E20 profile: the four reference runs are published individually and the "
        "level's variation is their spread. They are four runs of one condition, not a "
        "synthetic reference profile, and a mean of the four would destroy exactly the "
        "variation this slice exists to state, so the module computes none"
    ),
    (
        "No new acquisition, no change to the run plan, and no change to the frozen WP0 "
        "artefacts, WP1's or WP2's: this slice adds documents beside them and reads every "
        "number through the shared loader"
    ),
    (
        "No spectrum, no SNR and no saturation statement: these files carry one "
        "axial-velocity channel, so the power spectrum, the noise floor and the receiver "
        "gain are outside what this dataset can measure"
    ),
    (
        "No interaction: the pitch x burst corner is WP3's, and its floors are not used here"
    ),
    (
        "No rate of anything: the achieved periods are grid properties of the four levels, "
        "and no drift or change is expressed per unit time"
    ),
)


def _temporal_document(row: TemporalValue) -> dict[str, object]:
    """One temporal row's JSON view, with the published block boundaries."""
    return {
        "level": row.level,
        "label": row.label,
        "job": row.job,
        "profiles": row.profiles,
        "record_duration_s": row.record_duration_s,
        "median_interval_s": row.median_interval_s,
        "mean_interval_s": row.mean_interval_s,
        "achieved_period_s": row.achieved_period_s,
        "profile_rate_hz": row.profile_rate_hz,
        "nyquist_hz": row.nyquist_hz,
        "frequency_resolution_hz": row.frequency_resolution_hz,
        "emissions_times_prf_s": row.emissions_times_prf_s,
        "fixed_overhead_s": row.fixed_overhead_s,
        "internal_emission_s": row.internal_emission_s,
        "transfer_term_s": row.transfer_term_s,
        "blocks": row.blocks,
        "block_duration_s": row.block_duration_s,
        "block_bounds_s": [float(value) for value in row.block_bounds_s],
        "profiles_per_block_median": row.profiles_per_block_median,
        "profiles_per_block_min": row.profiles_per_block_min,
        "profiles_per_block_max": row.profiles_per_block_max,
        "first_block_start_s": row.first_block_start_s,
        "last_block_start_s": row.last_block_start_s,
    }


def def_document(model: EmissionsLadder) -> dict[str, object]:
    """The WP4 document: both views, the floors, the observation and the gate.

    Keys are dumped with ``sort_keys=True``, so a regeneration from the same commit is
    byte-identical.
    """
    curves = {
        label: {
            "lag_step_s": next(
                row.achieved_period_s for row in model.temporal if row.label == label
            ),
            "curve_from_lag_1": [
                float(value) for value in getattr(model.acf_curves, f"acf_{label}")
            ],
        }
        for label in (row.label for row in model.records)
    }
    return {
        "dataset_root": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "analysis_commit": model.analysis_commit,
        "table": CSV_NAME,
        "table_rows": sum(
            (
                len(model.records) * len(STATISTICS),
                len(model.differences),
                len(model.brackets),
                len(model.temporal),
                len(model.acf),
            )
        ),
        "view_1_velocity_stability": {
            "window_s": model.window_s,
            "revolutions": model.window_revolutions,
            "rule": (
                "the pass's designed exposure, the declared 12 s = 100 nominal 500-RPM "
                "revolutions, cut in each recording by its own stored timestamps (WP0); the "
                "retained surplus belongs to view 2 and is not part of this exposure"
            ),
            "common_support": {
                "support_min_mm": model.support_min_mm,
                "support_max_mm": model.support_max_mm,
                "rule": (
                    "the intersection of every recording's decoded depth range; each "
                    "per-gate statistic is computed on the recording's own native gate grid "
                    "inside it, and no interpolation or resampling is applied"
                ),
            },
            "ladder_steps": [
                {"left": step.left_level, "right": step.right_level}
                for step in model.steps
            ],
        },
        "view_2_temporal_cost": {
            "rule": (
                "the full retained record, not the 12 s window: the achieved period, rate, "
                "Nyquist frequency, frequency resolution, autocorrelation and the "
                "physical-duration segmentation are all measured on each file's own stored "
                "per-profile time array"
            ),
            "segment_duration_s": model.block_duration_s,
            "autocorrelation_depths_mm": list(ACF_DEPTHS_MM),
            "autocorrelation_half_level": ACF_HALF_LEVEL,
            "autocorrelation_curve_span_s": ACF_MAX_LAG_S,
            "retired_planning_law": (
                f"{RETIRED_PERIOD_LAW}: the expectation the job logs record as provenance. "
                "No number in this slice is taken from it, and a record without a stored "
                "per-profile time array is refused rather than measured with it"
            ),
        },
        "evidence": {
            "levels": [
                {
                    "level": level.level,
                    "emissions_per_profile": level.emissions_per_profile,
                    "condition": dict(level.condition),
                    "records": list(level.records),
                    "jobs": list(level.jobs),
                    "evidence": level.evidence,
                    "anchor_labels": list(level.anchor_labels),
                    "stated_variation_mm_s": level.stated_variation_mm_s,
                    "stated_variation_kind": level.stated_variation_kind,
                    "stated_variation_basis": level.stated_variation_basis,
                    "note": level.note,
                }
                for level in model.levels
            ],
            "caveat": (
                "the four levels rest on unequal evidence and this slice never blurs it: "
                "E20 is four runs and its variation is their spread, while E8, E64 and E128 "
                "are one scientific recording each inside its own job's three block-local "
                "anchors"
            ),
        },
        "floors": {
            "bindings": [
                {
                    "name": floor.name,
                    "level": floor.level,
                    "statistic": floor.statistic,
                    "published_mm_s": floor.published_mm_s,
                    "recomputed_mm_s": floor.recomputed_mm_s,
                    "depth_mm": floor.depth_mm,
                    "source": floor.source,
                    "endpoint": floor.endpoint,
                    "applies_to": floor.applies_to,
                    "unit": floor.unit,
                }
                for floor in model.floors
            ],
            "rule": (
                "three floors, never mixed: a per-gate difference or extreme is screened "
                "against the depth-resolved endpoint, a depth-averaged difference against "
                "the depth-averaged endpoint, and a residual inside one job against that "
                "job's own anchor spread. All are observed differences over a few "
                "recordings: they screen, they do not bound drift, and they are not "
                "confidence intervals"
            ),
        },
        "predictions": [
            {
                "level": row.level,
                "expected_period_s": row.expected_period_s,
                "expected_rate_hz": row.expected_rate_hz,
                "measured_period_s": row.measured_period_s,
                "measured_rate_hz": row.measured_rate_hz,
                "period_difference_s": row.period_difference_s,
                "rate_difference_hz": row.rate_difference_hz,
                "period_tolerance_s": row.period_tolerance_s,
                "rate_tolerance_hz": row.rate_tolerance_hz,
                "records_compared": row.records_compared,
                "agrees": row.agrees,
            }
            for row in model.predictions
        ],
        "e128_observation": {
            "label": model.e128_observation.label,
            "job": model.e128_observation.job,
            "residual_mean_vs_begin_mm_s": (
                model.e128_observation.residual_mean_vs_begin_mm_s
            ),
            "residual_mean_vs_mid_mm_s": model.e128_observation.residual_mean_vs_mid_mm_s,
            "extreme_vs_begin_abs_mm_s": model.e128_observation.extreme_vs_begin_abs_mm_s,
            "extreme_vs_begin_signed_mm_s": (
                model.e128_observation.extreme_vs_begin_signed_mm_s
            ),
            "extreme_vs_begin_depth_mm": model.e128_observation.extreme_vs_begin_depth_mm,
            "extreme_vs_mid_abs_mm_s": model.e128_observation.extreme_vs_mid_abs_mm_s,
            "extreme_vs_mid_signed_mm_s": (
                model.e128_observation.extreme_vs_mid_signed_mm_s
            ),
            "extreme_vs_mid_depth_mm": model.e128_observation.extreme_vs_mid_depth_mm,
            "gates": model.e128_observation.gates,
            "knots_positive_vs_begin": model.e128_observation.knots_positive_vs_begin,
            "knots_positive_vs_mid": model.e128_observation.knots_positive_vs_mid,
            "longest_positive_run_knots_vs_begin": (
                model.e128_observation.longest_positive_run_knots_vs_begin
            ),
            "longest_positive_run_span_mm_vs_begin": list(
                model.e128_observation.longest_positive_run_span_mm_vs_begin
            ),
            "longest_positive_run_knots_vs_mid": (
                model.e128_observation.longest_positive_run_knots_vs_mid
            ),
            "longest_positive_run_span_mm_vs_mid": list(
                model.e128_observation.longest_positive_run_span_mm_vs_mid
            ),
            "same_sign_region_around_extreme_mm_vs_begin": list(
                model.e128_observation.same_sign_region_around_extreme_mm_vs_begin
            ),
            "same_sign_region_around_extreme_mm_vs_mid": list(
                model.e128_observation.same_sign_region_around_extreme_mm_vs_mid
            ),
            "top_three_knots_share_of_absolute_sum": (
                model.e128_observation.top_three_knots_share_of_absolute_sum
            ),
            "job_anchor_floor_mm_s": model.e128_observation.job_anchor_floor_mm_s,
            "ratio_to_job_anchor_floor_vs_begin": (
                model.e128_observation.ratio_to_job_anchor_floor_vs_begin
            ),
            "ratio_to_job_anchor_floor_vs_mid": (
                model.e128_observation.ratio_to_job_anchor_floor_vs_mid
            ),
            "ratio_to_depth_resolved_floor_vs_begin": (
                model.e128_observation.ratio_to_depth_resolved_floor_vs_begin
            ),
            "ratio_to_depth_resolved_floor_vs_mid": (
                model.e128_observation.ratio_to_depth_resolved_floor_vs_mid
            ),
            "reading": model.e128_observation.reading,
        },
        "levels": [
            {
                "level": level.level,
                "emissions_per_profile": level.emissions_per_profile,
                "evidence": level.evidence,
                "records": list(level.records),
                "stated_variation_mm_s": level.stated_variation_mm_s,
                "stated_variation_kind": level.stated_variation_kind,
            }
            for level in model.levels
        ],
        "records": [
            {
                "level": row.level,
                "label": row.label,
                "job": row.job,
                "step": row.step,
                "order": row.order,
                "relative_path": row.relative_path,
                "evidence": row.evidence,
                "burst_length": row.burst_length,
                "emissions_per_profile": row.emissions_per_profile,
                "gates": row.gates,
                "resolution_mm": row.resolution_mm,
                "supported_gates": row.supported_gates,
                "profiles_full": row.profiles_full,
                "profiles_window": row.profiles_window,
                "statistics": dict(row.statistics),
            }
            for row in model.records
        ],
        "temporal": [_temporal_document(row) for row in model.temporal],
        "autocorrelation": [
            {
                "level": row.level,
                "label": row.label,
                "requested_depth_mm": row.requested_depth_mm,
                "depth_mm": row.depth_mm,
                "gate_index": row.gate_index,
                "profiles": row.profiles,
                "lag1_autocorrelation": row.lag1_autocorrelation,
                "first_lag_below_half": row.first_lag_below_half,
                "first_lag_below_half_s": row.first_lag_below_half_s,
                "reaches_half": row.reaches_half,
                "series_mean_mm_s": row.series_mean_mm_s,
                "series_std_mm_s": row.series_std_mm_s,
            }
            for row in model.acf
        ],
        "autocorrelation_curves": curves,
        "differences": [
            {
                "left_level": row.left_level,
                "right_level": row.right_level,
                "left_label": row.left_label,
                "right_label": row.right_label,
                "mean_difference_mm_s": row.mean_difference_mm_s,
                "extreme_abs_mm_s": row.extreme_abs_mm_s,
                "extreme_signed_mm_s": row.extreme_signed_mm_s,
                "extreme_depth_mm": row.extreme_depth_mm,
                "knots_positive": row.knots_positive,
                "knots_negative": row.knots_negative,
                "gates": row.gates,
            }
            for row in model.differences
        ],
        "steps": [
            {
                "left_level": row.left_level,
                "right_level": row.right_level,
                "differences": row.differences,
                "extreme_abs_mm_s": row.extreme_abs_mm_s,
                "extreme_signed_mm_s": row.extreme_signed_mm_s,
                "extreme_depth_mm": row.extreme_depth_mm,
                "extreme_left_label": row.extreme_left_label,
                "extreme_right_label": row.extreme_right_label,
                "mean_difference_min_mm_s": row.mean_difference_min_mm_s,
                "mean_difference_max_mm_s": row.mean_difference_max_mm_s,
                "note": row.note,
            }
            for row in model.steps
        ],
        "brackets": [
            {
                "level": row.level,
                "label": row.label,
                "job": row.job,
                "anchor": row.anchor,
                "anchor_kind": row.anchor_kind,
                "residual_mean_mm_s": row.residual_mean_mm_s,
                "residual_extreme_abs_mm_s": row.residual_extreme_abs_mm_s,
                "residual_extreme_signed_mm_s": row.residual_extreme_signed_mm_s,
                "residual_extreme_depth_mm": row.residual_extreme_depth_mm,
                "knots_positive": row.knots_positive,
                "knots_negative": row.knots_negative,
                "gates": row.gates,
                "job_anchor_floor_mm_s": row.job_anchor_floor_mm_s,
            }
            for row in model.brackets
        ],
        "depth_resolved": {
            key: [float(value) for value in getattr(model.depth_resolved, key)]
            for key in DepthResolved.model_fields
        },
        "definitions": {
            **{
                statistic: WP0_DEFINITIONS.get(f"supported_{statistic}", statistic)
                if statistic != "zero_fraction"
                else WP0_DEFINITIONS["zero_fraction"]
                for statistic in STATISTICS
            },
            **DEFINITIONS,
        },
        "not_here": list(NOT_HERE),
        "checks": dict(sorted(model.checks.items())),
        "ok": model.ok,
    }


def _wrap(text: str, width: int = 150) -> str:
    """Wrap a caption to fixed width, so the figure's own text is readable."""
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def _floors_caption(model: EmissionsLadder) -> str:
    """The floors, with the endpoint each one applies to, for a figure caption."""
    return " | ".join(
        f"{floor.name} {floor.published_mm_s:.3f} mm/s"
        + (f" at {floor.depth_mm:.3f} mm" if floor.depth_mm is not None else "")
        for floor in model.floors
    )


def render_stability_figure(model: EmissionsLadder, path: Path) -> Path:
    """Draw the velocity-stability view: the profiles, then the ladder's differences.

    The upper panel keeps every record visible — the four E20 runs individually, on
    purpose, with no averaged profile — and the lower one draws every consecutive-level
    difference with each step's own extreme marked and the two reference endpoints beside
    them, at the values this pass's own artefacts publish. The caption carries the
    statistics, the floors and the evidence caveat, so the image alone cannot be read as a
    level effect.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    depths = np.asarray(model.depth_resolved.depths_mm, dtype=float)
    published = model.published_floors
    published_jobs = " / ".join(
        f"{published_job_floor(published, job).published_mm_s:.3f}"
        for job in science_jobs()
    )
    figure, (levels, differences) = plt.subplots(
        2, 1, figsize=(7.6, 8.8), sharex=True, dpi=FIGURE_DPI
    )
    style = {
        "e8": ("#1f77b4", 1.7, "-", "e8  (E8)"),
        "cr1": ("#e6550d", 1.2, "-", "cr1  (E20)"),
        "cr2": ("#fd8d3c", 1.2, "--", "cr2  (E20)"),
        "cr3": ("#fdd0a2", 1.4, "-.", "cr3  (E20)"),
        "cr4": ("#a63603", 1.2, ":", "cr4  (E20)"),
        "e64": ("#2ca02c", 1.7, "-", "e64  (E64)"),
        "e128": ("#d62728", 1.7, "-", "e128  (E128)"),
    }
    for row in model.records:
        colour, width, dash, label = style[row.label]
        levels.plot(
            getattr(model.depth_resolved, row.label),
            depths,
            color=colour,
            linewidth=width,
            linestyle=dash,
            label=f"{label}  {row.statistics['mean']:.2f} mm/s",
        )
    levels.set_ylabel("depth [mm]")
    levels.invert_yaxis()
    levels.set_xlabel("window mean velocity [mm/s]")
    levels.set_title(
        "the ladder's records, individually - no averaged E20 profile is drawn\n"
        f"reference window {model.reference_window_gates} gates x "
        f"{REFERENCE_WINDOW[0]:g} mm, primary window {model.window_s:g} s, "
        f"{int(depths.size)} supported gates of "
        f"{model.support_min_mm:.3f}-{model.support_max_mm:.3f} mm",
        fontsize=9,
    )
    levels.grid(alpha=0.2)
    levels.legend(loc="lower right", fontsize=6.5, framealpha=0.9)

    step_style = {
        ("E8", "E20"): "#1f77b4",
        ("E20", "E64"): "#2ca02c",
        ("E64", "E128"): "#d62728",
    }
    for step in model.steps:
        colour = step_style[(step.left_level, step.right_level)]
        widest = (step.extreme_left_label, step.extreme_right_label)
        for row in model.differences:
            if (row.left_level, row.right_level) != (
                step.left_level,
                step.right_level,
            ):
                continue
            is_worst = (row.left_label, row.right_label) == widest
            differences.plot(
                getattr(
                    model.depth_resolved,
                    f"{row.left_label}_minus_{row.right_label}",
                ),
                depths,
                color=colour,
                linewidth=1.9 if is_worst else 0.8,
                alpha=1.0 if is_worst else 0.5,
                label=(
                    f"{row.left_label} - {row.right_label} "
                    f"({step.left_level}->{step.right_level})"
                ),
            )
        differences.scatter(
            [step.extreme_signed_mm_s],
            [step.extreme_depth_mm],
            color=colour,
            s=22,
            zorder=5,
        )
    for value, name in (
        (published.depth_resolved.published_mm_s, "WP2 depth-resolved floor"),
        (published.depth_averaged.published_mm_s, "WP2 depth-averaged floor"),
    ):
        for sign in (-1.0, 1.0):
            differences.axvline(
                sign * value,
                color="#555555",
                linewidth=0.9,
                linestyle=(0, (4, 3)),
                label=f"{name} {value:.3f} mm/s" if sign > 0 else None,
            )
    differences.axvline(0.0, color="#444444", linewidth=0.8)
    differences.set_ylabel("depth [mm]")
    differences.invert_yaxis()
    differences.set_xlabel("per-gate window-mean difference [mm/s]")
    differences.set_title(
        "every consecutive-level difference, run-resolved; the marked point is each "
        "step's own extreme",
        fontsize=9,
    )
    differences.grid(alpha=0.2)
    differences.legend(loc="lower right", fontsize=5.6, ncol=2, framealpha=0.9)

    statistics_line = " | ".join(
        f"{row.label}: mean {row.statistics['mean']:.3f} median "
        f"{row.statistics['median']:.3f} iqr {row.statistics['iqr']:.3f} rms "
        f"{row.statistics['rms']:.3f} zero_fraction {row.statistics['zero_fraction']:.4f}"
        for row in model.records
    )
    steps_line = " | ".join(
        f"{step.left_level}->{step.right_level}: mean {step.mean_difference_min_mm_s:+.3f}.."
        f"{step.mean_difference_max_mm_s:+.3f}, extreme {step.extreme_signed_mm_s:+.3f} "
        f"at {step.extreme_depth_mm:.2f} mm ({step.extreme_left_label} - "
        f"{step.extreme_right_label})"
        for step in model.steps
    )
    figure.text(
        0.01,
        0.012,
        _wrap(
            f"floors: {_floors_caption(model)}. {statistics_line}. Depth-resolved steps: "
            f"{steps_line}. Evidence: E20 is four runs (cr1..cr4, spread "
            f"{next(level.stated_variation_mm_s for level in model.levels if level.level == 'E20'):.3f} "
            f"mm/s between them), while e8, e64 and e128 are one scientific recording each "
            f"inside their own job's three block-local anchors (spreads {published_jobs} "
            "mm/s). One realization per level: an observed difference is not "
            "evidence that the emissions setting caused it, and a screening outcome "
            "neither proves an axis effect nor bounds drift."
        ),
        fontsize=5.3,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.90, bottom=0.19, hspace=0.16)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=FIGURE_DPI)
    plt.close(figure)
    return target


def render_temporal_figure(model: EmissionsLadder, path: Path) -> Path:
    """Draw the temporal-cost view: the achieved grid per level, then its autocorrelation.

    The bars are each level's achieved period from its stored timestamps, with the
    reviewer's expected period marked, and the panels beside them are the records'
    autocorrelation curves at the first stated depth. The caption carries the rates, the
    Nyquist frequencies, the profiles per fixed-duration block and the floors caveat.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    figure, (grid, acf) = plt.subplots(2, 1, figsize=(7.6, 8.6), dpi=FIGURE_DPI)
    labels = [row.label for row in model.temporal]
    colours = {
        "e8": "#1f77b4",
        "cr1": "#e6550d",
        "cr2": "#fd8d3c",
        "cr3": "#fdd0a2",
        "cr4": "#a63603",
        "e64": "#2ca02c",
        "e128": "#d62728",
    }
    positions = np.arange(len(labels), dtype=float)
    periods_ms = [row.achieved_period_s * 1e3 for row in model.temporal]
    grid.bar(
        positions,
        periods_ms,
        color=[colours[label] for label in labels],
        width=0.6,
    )
    for position, row in zip(positions, model.temporal, strict=True):
        grid.annotate(
            f"{row.profile_rate_hz:.2f} Hz\nNyq {row.nyquist_hz:.2f} Hz",
            xy=(position, row.achieved_period_s * 1e3),
            xytext=(0.0, 3.0),
            textcoords="offset points",
            ha="center",
            fontsize=5.6,
            family="monospace",
        )
    expected = {row.level: row.expected_period_s * 1e3 for row in model.predictions}
    grid.scatter(
        positions,
        [expected[row.level] for row in model.temporal],
        marker="x",
        color="#111111",
        s=26,
        zorder=5,
        label="the request's expected period (three significant figures)",
    )
    grid.set_xticks(positions)
    grid.set_xticklabels(
        [f"{row.label}\n{row.level}" for row in model.temporal], fontsize=7
    )
    grid.set_ylabel("achieved profile period [ms]")
    grid.set_title(
        "the achieved grid per record, measured from the stored timestamps\n"
        "the bars are the median of the successive differences, the crosses the "
        "expected periods",
        fontsize=9,
    )
    grid.grid(alpha=0.2, axis="y")
    grid.legend(loc="upper left", fontsize=7, framealpha=0.9)

    for row in model.temporal:
        period = row.achieved_period_s
        curve = np.asarray(getattr(model.acf_curves, f"acf_{row.label}"), dtype=float)
        acf.plot(
            np.arange(1, curve.size + 1) * period,
            curve,
            color=colours[row.label],
            linewidth=1.4,
            label=f"{row.label} ({row.level})",
        )
    acf.axhline(ACF_HALF_LEVEL, color="#555555", linewidth=0.9, linestyle=(0, (4, 3)))
    acf.axhline(0.0, color="#444444", linewidth=0.8)
    acf.set_xlabel("lag [s], from the record's own achieved period")
    acf.set_ylabel(f"autocorrelation at {model.acf[0].depth_mm:.3f} mm")
    acf.set_ylim(-0.4, 1.05)
    acf.set_title(
        f"the full record's autocorrelation at {model.acf[0].depth_mm:.3f} mm "
        f"(the first stated depth); |ACF| = {ACF_HALF_LEVEL:g} marked",
        fontsize=9,
    )
    acf.grid(alpha=0.2)
    acf.legend(loc="upper right", fontsize=6, ncol=2, framealpha=0.9)

    grid_line = " | ".join(
        f"{row.label}: {row.achieved_period_s * 1e3:.3f} ms (mean "
        f"{row.mean_interval_s * 1e3:.3f}), {row.profile_rate_hz:.3f} Hz, Nyq "
        f"{row.nyquist_hz:.3f} Hz, df {row.frequency_resolution_hz:.4f} Hz over "
        f"{row.record_duration_s:.3f} s, {row.profiles_per_block_median} profiles per "
        f"{row.block_duration_s:g} s block"
        for row in model.temporal
    )
    prediction_line = " | ".join(
        f"{row.level}: expected {row.expected_period_s * 1e3:.1f} ms "
        f"({row.expected_rate_hz:.1f} Hz) vs measured "
        f"{row.measured_period_s * 1e3:.3f} ms ({row.measured_rate_hz:.3f} Hz)"
        for row in model.predictions
    )
    acf_line = " | ".join(
        f"{row.label}@{row.depth_mm:.3f} mm lag1 {row.lag1_autocorrelation:.3f}, "
        f"|ACF|<0.5 at lag {row.first_lag_below_half} ({row.first_lag_below_half_s:.3f} s)"
        for row in model.acf
        if math.isclose(
            row.requested_depth_mm, ACF_DEPTHS_MM[0], rel_tol=0.0, abs_tol=1e-9
        )
    )
    figure.text(
        0.01,
        0.012,
        _wrap(
            f"full retained record, each level's own achieved grid. {grid_line}. "
            f"Expected periods from the WP4 request, checked within "
            f"{PERIOD_EXPECTATION_TOLERANCE_S * 1e3:.2f} ms and "
            f"{RATE_EXPECTATION_TOLERANCE_HZ:.1f} Hz: {prediction_line}. Autocorrelation "
            f"(biased normalized autocovariance of the stored series): {acf_line}. "
            f"Floors: {_floors_caption(model)}. Evidence: E20 is four runs, while e8, e64 "
            "and e128 are one scientific recording each inside their own job's three "
            "block-local anchors - the temporal cost is a grid property, not proof that "
            "an emissions setting caused a change, and the four levels rest on unequal "
            "evidence."
        ),
        fontsize=5.3,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.91, bottom=0.21, hspace=0.30)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=FIGURE_DPI)
    plt.close(figure)
    return target


def _md_table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> str:
    """Render one markdown table."""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def markdown_text(model: EmissionsLadder) -> str:
    """Render ``emissions-ladder.md``: the two views, the floors and the reading."""
    records = {row.label: row for row in model.records}
    levels = {level.level: level for level in model.levels}
    e128 = model.e128_observation
    published = model.published_floors
    rows = [
        [
            level.level,
            f"{level.emissions_per_profile:d}",
            ", ".join(level.records),
            ", ".join(level.jobs),
            str(len(level.records)),
            f"{level.stated_variation_mm_s:.3f}",
            level.stated_variation_kind,
        ]
        for level in model.levels
    ]
    statistics_rows = []
    for level in model.levels:
        for label in level.records:
            record = records[label]
            statistics_rows.append(
                [
                    level.level,
                    label,
                    f"{record.statistics['mean']:.3f}",
                    f"{record.statistics['median']:.3f}",
                    f"{record.statistics['iqr']:.3f}",
                    f"{record.statistics['rms']:.3f}",
                    f"{record.statistics['zero_fraction']:.4f}",
                ]
            )
    difference_rows = [
        [
            f"{row.left_level}->{row.right_level}",
            row.left_label,
            row.right_label,
            f"{row.mean_difference_mm_s:+.3f}",
            f"{row.extreme_signed_mm_s:+.3f}",
            f"{row.extreme_abs_mm_s:.3f}",
            f"{row.extreme_depth_mm:.3f}",
            f"{row.knots_positive}/{row.gates}",
        ]
        for row in model.differences
    ]
    step_rows = [
        [
            f"{row.left_level}->{row.right_level}",
            str(row.differences),
            f"{row.mean_difference_min_mm_s:+.3f} .. {row.mean_difference_max_mm_s:+.3f}",
            f"{row.extreme_signed_mm_s:+.3f}",
            f"{row.extreme_abs_mm_s:.3f}",
            f"{row.extreme_depth_mm:.3f}",
            f"{row.extreme_left_label} - {row.extreme_right_label}",
        ]
        for row in model.steps
    ]
    bracket_rows = [
        [
            row.level,
            row.label,
            row.anchor,
            f"{row.residual_mean_mm_s:+.3f}",
            f"{row.residual_extreme_signed_mm_s:+.3f}",
            f"{row.residual_extreme_abs_mm_s:.3f}",
            f"{row.residual_extreme_depth_mm:.3f}",
            f"{row.job_anchor_floor_mm_s:.3f}",
        ]
        for row in model.brackets
    ]
    temporal_rows = [
        [
            row.level,
            row.label,
            str(row.profiles),
            f"{row.record_duration_s:.4f}",
            f"{row.median_interval_s * 1e3:.3f}",
            f"{row.mean_interval_s * 1e3:.3f}",
            f"{row.profile_rate_hz:.3f}",
            f"{row.nyquist_hz:.3f}",
            f"{row.frequency_resolution_hz:.4f}",
            f"{row.fixed_overhead_s * 1e3:.3f}",
            f"{row.internal_emission_s * 1e3:.3f}",
            f"{row.transfer_term_s * 1e3:.3f}",
            str(row.blocks),
            str(row.profiles_per_block_median),
            f"{row.profiles_per_block_min}-{row.profiles_per_block_max}",
        ]
        for row in model.temporal
    ]
    prediction_rows = [
        [
            row.level,
            f"{row.expected_period_s * 1e3:.1f}",
            f"{row.expected_rate_hz:.1f}",
            f"{row.measured_period_s * 1e3:.3f}",
            f"{row.measured_rate_hz:.3f}",
            f"{row.period_difference_s * 1e3:+.4f}",
            f"{row.rate_difference_hz:+.3f}",
            "yes" if row.agrees else "no",
        ]
        for row in model.predictions
    ]
    acf_rows = [
        [
            row.label,
            row.level,
            f"{row.depth_mm:.3f}",
            f"{row.lag1_autocorrelation:.3f}",
            str(row.first_lag_below_half),
            f"{row.first_lag_below_half_s:.3f}",
            f"{row.series_mean_mm_s:.3f}",
            f"{row.series_std_mm_s:.3f}",
        ]
        for row in model.acf
    ]
    floor_rows = [
        [
            floor.name,
            f"{floor.published_mm_s:.3f}",
            f"{floor.recomputed_mm_s:.3f}",
            "-" if floor.depth_mm is None else f"{floor.depth_mm:.3f}",
            floor.endpoint,
            floor.applies_to,
        ]
        for floor in model.floors
    ]
    ladder_line = " -> ".join(
        f"{level.level} ({level.stated_variation_mm_s:.3f} mm/s "
        f"{level.stated_variation_kind.split(' over')[0]})"
        for level in model.levels
    )
    return f"""# WP4 — the emissions ladder, and its temporal cost

**Status:** WP4 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
§4. Generated against the revision `{model.analysis_commit}`, the revision
`emissions-ladder.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-emissions-ladder \\
    --analysis-commit {model.analysis_commit}
```

**What it measures.** Four emissions-per-profile levels — E8, E20, E64 and E128 — at the
**reference spatial window** ({model.reference_window_gates} gates x {REFERENCE_WINDOW[0]:g} mm),
on the common physical support {model.support_min_mm:.3f}-{model.support_max_mm:.3f} mm, in two
views that are kept apart: the **velocity-estimate stability** on the pass's designed
primary window ({model.window_s:g} s), and the **temporal cost** on the full retained record
from each file's achieved timestamps. The levels differ by a factor of 5.7 in profile rate,
so every temporal statement is drawn on each file's own grid, and every segment compared
between levels has one shared physical *duration*.

**The evidence is unequal, and the table below is that fact rather than a summary of it.**

{_md_table(rows, ["level", "emissions", "records", "jobs", "records", "stated variation [mm/s]", "variation from"])}

E20 is the only level this pass observes in **more than one run**: it is the four
common-reference recordings (`cr1`..`cr4`, decoded burst 10 / emissions 20, one per reference
job), and its stated variation is the **spread of those four runs** — between-run variation,
which is WP2's own data. E8, E64 and E128 are **one scientific recording each** (`e8`, `e64`,
`e128`) inside their own job's three **block-local anchor controls**, and their stated
variation is that job's own anchor spread: a within-job bracketing context, not replication
of the level. No averaged E20 profile exists anywhere in this slice: four runs are four, and
pooling them would destroy exactly the variation this slice has to state.

The ladder reads, in the reduction the floors are stated in
(depth-averaged window mean, then each level's own variation): {ladder_line}.

## View 1 — the velocity estimate on the primary window

Depth-averaged statistics of the {model.window_s:g} s primary window on the common support,
in mm/s except `zero_fraction` (dimensionless), one row per record:

{_md_table(statistics_rows, ["level", "record", "mean", "median", "iqr", "rms", "zero_fraction"])}

The within-window width (`iqr`) and the payload's liveness (`zero_fraction`) move far less
than the level does, and the robust width is smallest at E64 and E128
({records["e64"].statistics["iqr"]:.3f} and {records["e128"].statistics["iqr"]:.3f} mm/s) against
E20's {min(records[label].statistics["iqr"] for label in ("cr1", "cr2", "cr3", "cr4")):.3f}-
{max(records[label].statistics["iqr"] for label in ("cr1", "cr2", "cr3", "cr4")):.3f} mm/s: a
5-10 % narrower per-gate spread at the two highest levels, beside a depth-averaged level that
moved by {records["e64"].statistics["mean"] - records["cr1"].statistics["mean"]:+.3f} to
{records["e64"].statistics["mean"] - records["cr4"].statistics["mean"]:+.3f} mm/s (E64 against the
four E20 runs). One recording per level is one realization: the narrowing is an observed
difference between these recordings and is not resolved as an emissions effect.

### The consecutive-level differences, depth-resolved

Every difference is a signed per-gate difference of window-mean profiles on the common
support, one row per pair of records — so a step with E20 in it carries **four** rows, one
per reference run, and no averaged E20 profile:

{_md_table(difference_rows, ["step", "left", "right", "mean [mm/s]", "extreme signed", "extreme abs", "at depth [mm]", "knots positive"])}

Each step's own reduction, its extreme taken over every difference that realizes it:

{_md_table(step_rows, ["step", "differences", "mean range [mm/s]", "extreme signed", "extreme abs", "at depth [mm]", "realized by"])}

Two readings follow, and they are the ones the numbers support:

1. **The depth-averaged steps, each read against the campaign's own between-run endpoint.**
   The reference endpoint is {published.depth_averaged.published_mm_s:.3f} mm/s, and the three steps do
   not sit with it in the same way:
   - *E8->E20*: the step's means span {model.steps[0].mean_difference_min_mm_s:+.3f} to
     {model.steps[0].mean_difference_max_mm_s:+.3f} mm/s (spread
     {model.steps[0].mean_difference_max_mm_s - model.steps[0].mean_difference_min_mm_s:.3f} mm/s, which is
     the E20 level's own run-to-run spread, because a constant offset cannot change a spread),
     so **E8 sits inside the spread the four E20 runs show between themselves**.
   - *E20->E64*: the step's means span {model.steps[1].mean_difference_min_mm_s:+.3f} to
     {model.steps[1].mean_difference_max_mm_s:+.3f} mm/s. That span straddles the
     {published.depth_averaged.published_mm_s:.3f} mm/s reference floor, so **some of the four E20
     realizations put the difference above it and some below it**: which realization E20 is taken
     as decides the answer. E64 therefore reads as *suggestive against E20 and unresolved by this
     pass*, not as sitting inside the pass's baseline variation.
   - *E64->E128*: {model.steps[2].mean_difference_min_mm_s:+.3f} mm/s, which lies **within** the
     {published.depth_averaged.published_mm_s:.3f} mm/s reference floor.
   Screening outcomes, not proofs of an axis effect.
2. **The per-gate extremes are the larger numbers, and they are what the depth-resolved
   endpoint screens.** The depth-resolved endpoint is
   {published.depth_resolved.published_mm_s:.3f} mm/s at {published.depth_resolved.depth_mm:.3f} mm; the
   step extremes reach {model.steps[0].extreme_abs_mm_s:.3f},
   {model.steps[1].extreme_abs_mm_s:.3f} and {model.steps[2].extreme_abs_mm_s:.3f} mm/s. A
   depth-averaged comparison hides local structure, which is why both views are published.

### The scientific rows inside their anchors

Each single-recording level against **each** of its two bracketing anchors
(`ctrl-begin`, `ctrl-mid`; `ctrl-end` reports the drift that follows the row and does not
bracket it symmetrically). The pass carries no per-recording clock, so a row is reported
against each bracketing anchor rather than at an invented instant — those two residuals
span every linear interpolation over the bracket:

{_md_table(bracket_rows, ["level", "record", "anchor", "residual mean [mm/s]", "extreme signed", "extreme abs", "at depth [mm]", "job's own anchor floor"])}

## The `e128` observation, examined depth-resolved

WP1 reported that `e128` sits larger than both of its bracketing anchors in the
depth-averaged mean. Recomputed here: {e128.residual_mean_vs_begin_mm_s:+.3f} mm/s against
`ctrl-begin` and {e128.residual_mean_vs_mid_mm_s:+.3f} mm/s against `ctrl-mid`, with the
largest per-gate residual {e128.extreme_vs_begin_signed_mm_s:+.3f} mm/s at
{e128.extreme_vs_begin_depth_mm:.3f} mm (against `ctrl-begin`) and
{e128.extreme_vs_mid_signed_mm_s:+.3f} mm/s at {e128.extreme_vs_mid_depth_mm:.3f} mm (against
`ctrl-mid`). Depth-resolved, it is {e128.knots_positive_vs_begin} of {e128.gates} knots with
the same sign against `ctrl-begin` and {e128.knots_positive_vs_mid} of {e128.gates} against
`ctrl-mid`; the longest contiguous same-sign run is
{e128.longest_positive_run_knots_vs_begin} knots spanning
{e128.longest_positive_run_span_mm_vs_begin[0]:.3f}-{e128.longest_positive_run_span_mm_vs_begin[1]:.3f} mm
against `ctrl-begin` and {e128.longest_positive_run_knots_vs_mid} knots spanning
{e128.longest_positive_run_span_mm_vs_mid[0]:.3f}-{e128.longest_positive_run_span_mm_vs_mid[1]:.3f} mm
against `ctrl-mid`; the same-sign region around the extreme is
{e128.same_sign_region_around_extreme_mm_vs_begin[0]:.3f}-
{e128.same_sign_region_around_extreme_mm_vs_begin[1]:.3f} mm, and the three largest knots carry
{e128.top_three_knots_share_of_absolute_sum * 100:.1f} % of the summed absolute residual. So
the sign is carried over a substantial contiguous depth region rather than by one gate, and
it is that region - not a single knot - that raises the depth-averaged mean.

**It is not evidence that E128 caused a change.** The residual is a difference between
**one** realization and **two** anchors; it is of the same size as the floors this pass owns
rather than far outside them ({e128.ratio_to_job_anchor_floor_vs_begin:.3f} and
{e128.ratio_to_job_anchor_floor_vs_mid:.3f} of the emissions-128 job's own anchor spread of
{e128.job_anchor_floor_mm_s:.3f} mm/s, and {e128.ratio_to_depth_resolved_floor_vs_begin:.3f} and
{e128.ratio_to_depth_resolved_floor_vs_mid:.3f} of WP2's depth-resolved endpoint of
{published.depth_resolved.published_mm_s:.3f} mm/s); and the emissions axis is one realization per
level except at E20, so no count of profiles or gates makes the comparison replicated. It is
an observation to carry forward, not a level effect.

## View 2 — the temporal cost of each level

Every number below is measured on the **full retained record** from that file's own stored
per-profile time array. The achieved period is the median of the successive differences of
that array; the mean is published beside it:

{_md_table(temporal_rows, ["level", "record", "profiles", "record [s]", "median period [ms]", "mean period [ms]", "rate [Hz]", "Nyquist [Hz]", "resolution [Hz]", "fixed overhead [ms]", "internal emission [ms]", "transfer [ms]", "blocks", "profiles/block", "range"])}

The four levels' achieved grids fall by a factor of 5.7 in rate from E8 to E128
({model.predictions[0].measured_rate_hz:.3f} Hz against
{model.predictions[3].measured_rate_hz:.3f} Hz), so the Nyquist frequency falls with them
({model.predictions[0].measured_rate_hz / 2:.3f} Hz against
{model.predictions[3].measured_rate_hz / 2:.3f} Hz) and the profiles in one
{model.block_duration_s:g} s block fall with them too
({model.temporal[0].profiles_per_block_median} at e8 against
{model.temporal[-1].profiles_per_block_median} at e128): that is the bandwidth price of higher
emissions, and it is a grid property rather than a change in the estimate. The frequency
resolution is essentially the same at every level
({model.temporal[0].frequency_resolution_hz:.4f} to
{max(row.frequency_resolution_hz for row in model.temporal):.4f} Hz), because every record retains
about 12.5 s: the ladder's temporal cost lies in the *rate*, not in the resolution. The
**fixed profile overhead** (`achieved - emissions x PRF`, the *intercept* of the period and
not the transfer term) is {model.temporal[0].fixed_overhead_s * 1e3:.3f} ms at every level,
composed of {model.temporal[0].internal_emission_s * 1e3:.3f} ms of internal emission - the 16
PRF terms the manual's law carries, 16 x
{model.temporal[0].internal_emission_s / 16 * 1e6:.0f} us - and
{model.temporal[0].transfer_term_s * 1e3:.3f} ms of transfer term proper.

### The request's expected periods, beside this pass's measurements

| level | expected period [ms] | expected rate [Hz] | measured period [ms] | measured rate [Hz] | difference [ms] | difference [Hz] | agrees |
|---|---|---|---|---|---|---|---|
{chr(10).join("| " + " | ".join(row) + " |" for row in prediction_rows)}

The expected numbers are the WP4 request's own, stated to three significant figures and
checked here within {PERIOD_EXPECTATION_TOLERANCE_S * 1e3:.2f} ms and
{RATE_EXPECTATION_TOLERANCE_HZ:.1f} Hz. They are checked rather than adopted: the measurement is
this pass's, taken from the stored timestamps, and a disagreement would be published as a
difference.

### The autocorrelation at the three stated depths

The biased normalized autocovariance of the **full** stored series at one native gate, the
same convention the spatial correlation length uses on a gate profile. The three depths are
two the earlier slices named (WP2's endpoint depth 21.238 mm, WP1's `e128` extreme 76.74 mm)
and one mid-support:

{_md_table(acf_rows, ["record", "level", "depth [mm]", "lag-1", "first lag below half", "at [s]", "series mean [mm/s]", "series std [mm/s]"])}

Two readings, reported independently because they answer different questions. *In physical
time*, the correlation at these gates survives **longer** at the higher levels than at the
lowest: the first lag below half is
{next(row for row in model.acf if row.label == "e8" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half_s:.3f} s at e8
against
{next(row for row in model.acf if row.label == "e128" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half_s:.3f} s at e128, i.e. **slower**
decorrelation in seconds at the higher emissions level - which is what a longer per-profile
acoustic averaging interval predicts, since each E128 profile spans {model.temporal[-1].achieved_period_s * 1e3:.1f} ms
against {model.temporal[0].achieved_period_s * 1e3:.1f} ms at E8, so the recorded series is the
smoother and lower-bandwidth one. It is not monotone across the ladder: at this gate E64's
first lag below half is
{next(row for row in model.acf if row.label == "e64" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half_s:.3f} s,
**longer** in physical time than E128's
{next(row for row in model.acf if row.label == "e128" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half_s:.3f} s, so the readings are
"longer at higher emissions than at the lowest" and not "longer at every step". *In profile lags*, the ordering runs the other way: 
{next(row for row in model.acf if row.label == "e8" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half} profiles at
e8 against
{next(row for row in model.acf if row.label == "e128" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half} at e128, i.e. fewer
profiles when each profile covers more time. The two are consequences of the same grid
difference read in two different units, and are published as two readings rather than as one
ordering that "reverses". Both are one record per series (E20's four runs are the only level
with repeats) at the three stated gates, so neither is a replication statement.

## The floors, and which endpoint applies where

{_md_table(floor_rows, ["floor", "published [mm/s]", "recomputed [mm/s]", "at depth [mm]", "endpoint", "applies to"])}

The published values are WP1's and WP2's; the recomputed ones are the same reductions
rebuilt here from the recordings, and the two agree within the three decimals the earlier
slices published
(tolerance {FLOOR_PUBLISHED_TOLERANCE_MM_S:g} mm/s). Three rules, never mixed:

- a **per-gate difference array or its extreme** is screened against the depth-resolved
  endpoint, {published.depth_resolved.published_mm_s:.3f} mm/s at
  {published.depth_resolved.depth_mm:.3f} mm;
- a **depth-averaged difference** (one unweighted mean over the supported gates) is screened
  against the depth-averaged endpoint, {published.depth_averaged.published_mm_s:.3f} mm/s, which is
  the only endpoint like for like with WP1's per-job floors;
- a **residual inside one job** is screened against that job's own anchor spread:
  {" / ".join(f"{published_job_floor(published, job).published_mm_s:.3f} mm/s ({job})" for job in sorted(science_jobs()))}.

All five are observed differences over a handful of recordings: they screen, they do not
bound drift, and they are not confidence intervals.

## What the WP4 gate asks, and what the evidence answers

1. **Do E64/E128 materially improve the velocity estimate over E20?** The depth-averaged
   differences are {model.steps[1].mean_difference_min_mm_s:+.3f} to
   {model.steps[1].mean_difference_max_mm_s:+.3f} mm/s across the four E20 runs, and the E64->E128
   difference is {model.steps[2].mean_difference_min_mm_s:+.3f} mm/s; the per-gate iqr is 5-10 %
   narrower at E64/E128. Both are of the order of the campaign's own four-run spread, and
   each level is one recording: the pass does not resolve a material improvement, and this
   slice says so rather than naming a winner.
2. **Does E8 lose useful estimator stability?** It has the smallest within-job anchor spread
   of the ladder ({levels["E8"].stated_variation_mm_s:.3f} mm/s), the highest profile rate
   ({model.predictions[0].measured_rate_hz:.3f} Hz) and, at the gates measured, the shortest
   physical correlation time of the four levels
   ({next(row for row in model.acf if row.label == "e8" and row.requested_depth_mm == ACF_DEPTHS_MM[0]).first_lag_below_half_s:.3f} s, i.e. its series decorrelates fastest in seconds and slowest in profiles); nothing measured here shows E8's estimate degrading against E20's.
3. **What is the bandwidth cost of each level?** The achieved period and profile rate above,
   with the profiles per {model.block_duration_s:g} s block as the concrete price:
   {", ".join(f"{row.level} {row.profiles_per_block_median}" for row in model.temporal if row.label in ("e8", "cr1", "e64", "e128"))}
   profiles per block (taking one record per level), and the Nyquist frequency falling from
   {model.predictions[0].measured_rate_hz / 2:.3f} Hz at E8 to {model.predictions[3].measured_rate_hz / 2:.3f} Hz at E128.

## Artefacts

| file | what it is |
|---|---|
| [`emissions-ladder.csv`](emissions-ladder.csv) | five blocks: the level statistics, the consecutive-level differences, the bracketing residuals, the temporal view, the autocorrelation at the stated depths |
| [`emissions-ladder.json`](emissions-ladder.json) | the levels and their evidence, both views depth-resolved, the floors with their endpoints, the request's expected periods beside the measurements, the `e128` observation, the definitions, the gate |
| `figures/{STABILITY_FIGURE}` | the stability view: every record's window-mean profile, and every consecutive-level difference with each step's extreme marked and both reference endpoints drawn |
| `figures/{TEMPORAL_FIGURE}` | the temporal view: the achieved period per record with the expected periods marked, and the autocorrelation at the first stated depth |
| this document | the reading of the numbers, the floors and their endpoints, and the `e128` observation |

## What is checked before a level is published

The command refuses (non-zero exit, named reason, nothing written) when the frozen WP0
ingest refuses, when a level's recording is not the one the ladder declares or decodes to
another condition, window or native grid than its level's, when a record carries no usable
stored per-profile time array (the retired `timing.target_s` is never a substitute for one),
when a job's anchors do not bracket its scientific row, or when a recomputed floor does not
reproduce the published one. The gate then holds only when all {len(model.checks)}
structural checks pass, including: four levels at their declared conditions, the declared
evidence counts
(4/1/1/1), E20 kept as four runs with no averaged profile, periods measured from the stored
timestamps and distinguishable from the retired planning law, the physical-duration
segmentation with its block boundaries, the spectral arithmetic, the request's expected
periods reproduced within tolerance, one shared native grid, complete differences and steps,
the bracketing recomputed per single level, and the floors stated with both endpoints. The
`ok` flag is the conjunction of the checks.

## What is deliberately not here

{chr(10).join("- " + text for text in NOT_HERE)}
"""


def write_emissions_ladder(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> EmissionsLadder:
    """Build the ladder and write the table, the document, the markdown and two figures.

    The pass's own WP1 and WP2 artefacts are read from ``report_dir`` for the published
    side of every floor; when they are not there the build refuses and names the missing
    document, because a floor read from another directory would let one directory's
    published numbers decide the outcome recorded in another. Every file is UTF-8 with LF endings and one trailing newline, so two runs on the
    same inputs and revision produce identical bytes. Nothing is written when the build
    refuses: a refused level, or a report directory without this pass's own published
    floors, leaves no half-artefact behind.
    """
    model = build_emissions_ladder(
        dataset_root,
        plan_path=plan_path,
        report_dir=Path(report_dir),
        analysis_commit=analysis_commit,
    )
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CSV_NAME).write_text(csv_text(model), encoding="utf-8", newline="")
    document = def_document(model)
    document["table_sha256"] = (
        "sha256:" + hashlib.sha256((directory / CSV_NAME).read_bytes()).hexdigest()
    )
    (directory / DOC_NAME).write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    (directory / MD_NAME).write_text(markdown_text(model), encoding="utf-8", newline="")
    render_stability_figure(model, directory / FIGURES_DIRNAME / STABILITY_FIGURE)
    render_temporal_figure(model, directory / FIGURES_DIRNAME / TEMPORAL_FIGURE)
    return model


def emissions_ladder_main(argv: list[str] | None = None) -> int:
    """``udv-sparse-emissions-ladder`` — write WP4's emissions ladder, both views.

    Reads the committed recordings through the frozen WP0 ingest's own binding and
    decoding, measures the four levels' velocity-estimate stability on the pass's designed
    primary window and their temporal cost on the full retained record from each file's
    achieved timestamps, and writes ``emissions-ladder.csv``, ``emissions-ladder.json``,
    ``emissions-ladder.md`` and the two figures into the report directory. The published
    side of every floor is read from the pass's own ``anchor-floor.json`` and
    ``reference-floor.json`` in the report directory, and never from a pinned copy of
    another sitting's numbers. It
    exits 0 when every WP4 gate check holds and 1 otherwise, naming the failure; a pass the
    ingest refuses exits 1 with the ingest's own reason and writes nothing.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-emissions-ladder",
        description=(
            "WP4: the sparse pass's emissions ladder (E8/E20/E64/E128), its stability view "
            "and its temporal bandwidth cost"
        ),
    )
    parser.add_argument(
        "--dataset-root",
        default=DATASET_ROOT.as_posix(),
        help="directory of committed .BDD recordings plus the pass's own record",
    )
    parser.add_argument(
        "--plan-path",
        default=PLAN_PATH.as_posix(),
        help="the frozen plan the pass is a realization of",
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR.as_posix(),
        help=(
            "directory to write emissions-ladder.{csv,json,md} into, and to read this "
            "pass's own anchor-floor.json and reference-floor.json from: both must be "
            "there, because the floors this slice screens with are the ones published "
            "beside its own artefacts"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default="",
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    try:
        model = write_emissions_ladder(
            Path(args.dataset_root),
            Path(args.report_dir),
            plan_path=Path(args.plan_path),
            analysis_commit=args.analysis_commit or None,
        )
    except SparseIngestError as exc:
        print(f"udv-sparse-emissions-ladder: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    for level in model.levels:
        print(
            f"{level.level:5s} emissions {level.emissions_per_profile:3d}  "
            f"records {len(level.records):d}  "
            f"variation {level.stated_variation_mm_s:7.3f} mm/s  "
            f"({level.stated_variation_kind})"
        )
    for row in model.temporal:
        print(
            f"  {row.label:5s} period {row.achieved_period_s * 1e3:8.3f} ms  "
            f"rate {row.profile_rate_hz:7.3f} Hz  Nyq {row.nyquist_hz:7.3f} Hz  "
            f"{row.profiles:d} profiles  {row.profiles_per_block_median:d} per "
            f"{row.block_duration_s:g} s block"
        )
    for row in model.differences:
        print(
            f"  {row.left_label:5s} - {row.right_label:5s} mean "
            f"{row.mean_difference_mm_s:+8.3f}  extreme {row.extreme_signed_mm_s:+8.3f} "
            f"({row.extreme_abs_mm_s:7.3f}) at {row.extreme_depth_mm:6.3f} mm"
        )
    print(
        f"e128 vs anchors: mean {model.e128_observation.residual_mean_vs_begin_mm_s:+.3f} / "
        f"{model.e128_observation.residual_mean_vs_mid_mm_s:+.3f} mm/s, extreme "
        f"{model.e128_observation.extreme_vs_begin_abs_mm_s:.3f} mm/s at "
        f"{model.e128_observation.extreme_vs_begin_depth_mm:.3f} mm, "
        f"{model.e128_observation.knots_positive_vs_begin}/"
        f"{model.e128_observation.gates} knots of one sign"
    )
    print(f"table   : {Path(args.report_dir) / CSV_NAME}")
    print(f"document: {Path(args.report_dir) / DOC_NAME}")
    failed = [name for name, ok in sorted(model.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sparse-emissions-ladder: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
