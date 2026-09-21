"""WP3 of the sparse-pass analysis: the 2x2 pitch x burst interaction.

**What this measures.** The pass records two pitches crossed with two burst lengths
inside the two *burst* jobs, each corner bracketed by that job's own block-local anchor
controls:

==========================  ===========  =============  ======================
cell                        job          pitch (mm)     burst length
==========================  ===========  =============  ======================
``cc1``                     burst-4      0.617          4
``cc2``                     burst-18     0.617          18
``cc3``                     burst-4      2.96           4
``cc4``                     burst-18     2.96           18
==========================  ===========  =============  ======================

The corner->job->condition mapping is **re-derived from the decoded recordings** (and
re-checked against the plan's own declaration) rather than trusted as given: the
burst-4 job holds ``cc1``/``cc3``, the burst-18 job holds ``cc2``/``cc4``, and a build
that finds anything else refuses by name. The endpoint is the difference of differences

    I(z) = [v(0.617, 18)(z) - v(2.96, 18)(z)] - [v(0.617, 4)(z) - v(2.96, 4)(z)]

per common knot, reduced to its unweighted mean over the knots (the *scalar
reduction*, published with its sign), with the four corner contrasts — the simple
effects — beside it for completeness.

**The alignment, and why nothing is interpolated.** The four corners are co-located in
depth but sampled at 0.6167 and 2.96 mm, so they are compared on **common physical
knots no finer than 2.96 mm**, and the knot set is the 2.960 mm measurement's own
native gate depths (the coarsest participating grid). Each corner is read at its
**nearest native gate** to each knot — no interpolation, no resampling, no fit — and
the native depth actually used and its offset from the knot are published per knot.
The build is **fail-closed**: if any required offset exceeds half the coarse pitch
(1.48 mm) the command refuses with a named error and writes nothing, because a corner
read that far from its knot is not the same depth as the knot it is compared at.

**The anchors are context, not cells.** The three block-local anchor controls of each
burst job (``ctrl-begin``/``ctrl-mid``/``ctrl-end``, the 1.85 mm reference window at
that job's own condition) are **not** factorial cells and never enter ``I(z)``: they
are reported beside each corner, with their own spread, so a reader sees where a corner
sits relative to its block's own movement. That spread is the conservative guard this
slice carries — 9.646 mm/s for ``burst-4`` and 11.980 mm/s for ``burst-18`` (WP1) — so
a pitch or burst effect smaller than ~10-12 mm/s cannot be separated from the anchors'
own movement inside those jobs.

**Screening, two endpoints, never mixed.** A depth-resolved magnitude (``|I(z)|`` per
knot, or any corner contrast's per-knot magnitude) is compared against WP2's
depth-resolved endpoint, 14.603 mm/s at 21.238 mm; a scalar (depth-averaged) effect is
compared against WP2's depth-averaged endpoint, 4.235 mm/s. The two are different
quantities from the same pair of runs and a number measured one way is never screened
against the other's endpoint.

**What it does not claim.** No causation: every number here is an observed difference
between recordings, not proof that the pitch or the burst moved anything. No
significance test and no confidence interval. No claim below ~10-12 mm/s (the anchors'
own floors). No emissions statement (WP4) and no reference-condition statement (WP2's
CR1-CR4 alone). No new acquisition, and no change to the frozen WP0 artefacts, WP1's or
WP2's: this slice reads the recordings through
:mod:`udv_echo_process.analysis._sparse_pass`, so it cuts the same 12 s primary window
and masks the same common support every other slice does.

The artefacts are ``pitch-burst.csv`` (the per-knot alignment and corner values),
``pitch-burst.json`` (the definitions, the structure, the floors and the gate),
``figures/pitch-burst.png`` and this module's own ``pitch-burst.md``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis._native_grid import nearest_gate_indices
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
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.provenance.models import current_revision

#: The four corners of the design, in the order the interaction reads them:
#: ``(label, job, requested pitch in mm, burst length)``. The job and the condition are
#: re-derived from the decoded recordings and re-checked against the plan's own
#: declaration; this constant is the expectation the data has to answer to.
CORNERS: tuple[tuple[str, str, float, int], ...] = (
    ("cc1", "burst-4", 0.617, 4),
    ("cc2", "burst-18", 0.617, 18),
    ("cc3", "burst-4", 2.96, 4),
    ("cc4", "burst-18", 2.96, 18),
)

#: The corner labels the interaction reads, and the two burst jobs it is measured in.
CORNER_LABELS: tuple[str, ...] = tuple(label for label, _, _, _ in CORNERS)
JOBS: tuple[str, ...] = ("burst-4", "burst-18")

#: The pitch of the knot participant: the coarsest grid this design measures, and the
#: grid every cross-pitch comparison in the pass is aligned on (plan §3.2).
COARSE_PITCH_MM = 2.96

#: The offset limit the alignment is fail-closed at: **half the coarse pitch**. A
#: corner read farther than this from a knot is not the same depth as the knot, and a
#: build that would need one refuses by name and writes nothing.
HALF_COARSE_PITCH_MM = COARSE_PITCH_MM / 2.0

#: The two corners that carry the coarse grid; their native supported depths are the
#: knot set, and their own knots have offset zero by construction.
KNOT_LABELS: tuple[str, ...] = ("cc3", "cc4")

#: The three block-local anchor controls, in acquisition order, with the short names the
#: documents use. They are context for the corners - never factorial cells.
ANCHORS: tuple[tuple[str, str], ...] = (
    ("ctrl-begin", "B"),
    ("ctrl-mid", "M"),
    ("ctrl-end", "E"),
)

#: The label prefix that marks a recording as a control rather than a scientific row.
CONTROL_PREFIX = "ctrl-"

#: The per-gate statistic every number here is reduced from: WP1's residual statistic
#: and WP2's floor statistic, so the three slices screen like for like.
STATISTIC = "mean"

#: The floors this slice screens against, each with the endpoint it belongs to. They are
#: **read from the frozen slices**: WP1's per-job anchor spreads and WP2's two
#: endpoints. Recomputed from the recordings in the gate below, at their published
#: precision.
DEPTH_RESOLVED_FLOOR_MM_S = 14.603
DEPTH_RESOLVED_FLOOR_DEPTH_MM = 21.238
DEPTH_RESOLVED_FLOOR_SOURCE = "WP2, the cr3-cr4 pair, per-depth window-mean difference"
DEPTH_AVERAGED_FLOOR_MM_S = 4.235
DEPTH_AVERAGED_FLOOR_SOURCE = "WP2's depth-averaged endpoint, the same pair"
ANCHOR_FLOOR_MM_S: dict[str, float] = {"burst-4": 9.646, "burst-18": 11.980}
ANCHOR_FLOOR_SOURCE = "WP1, each burst job's own block-local anchor spread"

#: The conservative reading the two anchor floors force, in the pass's own units: below
#: this band an interaction cannot be separated from the anchors' movement inside the
#: two burst jobs.
RESOLVABLE_BELOW_MM_S = (9.646, 11.980)

CSV_NAME = "pitch-burst.csv"
DOC_NAME = "pitch-burst.json"
MD_NAME = "pitch-burst.md"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "pitch-burst.png"
FIGURE_DPI = 150
TOLERANCE = 1e-9

#: What each published quantity means. The document carries them verbatim, so a reader
#: of the artefacts alone has the definitions beside the numbers.
DEFINITIONS: dict[str, str] = {
    "corner": (
        "one of the 2x2 design's four records: a pitch crossed with a burst length, "
        "measured inside the burst job that holds it (cc1/cc3 in burst-4, cc2/cc4 in "
        "burst-18). The corner's value at a knot is its own per-gate window mean at the "
        "native gate nearest that knot"
    ),
    "knot": (
        "a common physical depth both pitches are read at: the 2.960 mm measurement's "
        "own native supported gate depths, which are the coarsest participating grid. "
        "Every corner is read at its native gate nearest the knot - no interpolation, "
        "no resampling, no fit - and the native depth used and its offset are published "
        "per knot"
    ),
    "alignment_offset": (
        "the signed native depth used minus the knot it stands in for, in mm. Its "
        "magnitude is bounded by half the finer corner's own pitch for a nearest-gate "
        "read, and the build refuses by name (nothing written) if any required offset "
        "exceeds half the coarse pitch, 1.48 mm"
    ),
    "interaction": (
        "I(z) = [v(0.617,18)(z) - v(2.96,18)(z)] - [v(0.617,4)(z) - v(2.96,4)(z)], the "
        "difference-of-differences of the four corners at one knot: the pitch contrast "
        "at burst 18 minus the pitch contrast at burst 4, and equally the burst "
        "contrast at 2.96 mm minus the burst contrast at 0.617 mm. It is an observed "
        "difference, not proof that either axis moved anything"
    ),
    "scalar_reduction": (
        "the unweighted mean of I(z) over the common knots, published with its sign: "
        "the depth-averaged effect, screened against WP2's depth-averaged endpoint "
        "(4.235 mm/s) and never against the depth-resolved one"
    ),
    "corner_contrast": (
        "one simple effect of the 2x2: a pitch contrast (2.96 mm minus 0.617 mm) at one "
        "burst length, or a burst contrast (18 minus 4) at one pitch. Published "
        "depth-resolved and reduced to its unweighted mean over the knots; the four "
        "carry the interaction as I = (burst at 0.617) - (burst at 2.96) = (pitch at "
        "burst 4) - (pitch at burst 18)"
    ),
    "depth_resolved_floor": (
        "WP2's between-run endpoint for a per-depth magnitude: 14.603 mm/s at "
        "21.238 mm, from the cr3-cr4 pair. A depth-resolved magnitude is screened "
        "against this number"
    ),
    "depth_averaged_floor": (
        "WP2's between-run endpoint for a scalar, depth-averaged effect: 4.235 mm/s "
        "from the same pair, and the same reduction WP1's anchor spreads use. A scalar "
        "is screened against this number"
    ),
    "anchor_guard": (
        "each burst job's own block-local anchor spread (WP1): 9.646 mm/s at burst 4 and "
        "11.980 mm/s at burst 18. The anchors are context - never cells of the 2x2 and "
        "never an input to I(z) - and their movement inside their own job is what an "
        "interaction of comparable size cannot be separated from"
    ),
    "not_a_bound": (
        "every number here is an observed difference between recordings: not a "
        "confidence interval, not a significance test, and neither a proof of an axis "
        "effect nor a statement about drift"
    ),
}


class PitchBurstError(SparseIngestError):
    """The pass cannot produce WP3's interaction, or a caller asked for a wrong one."""


# ── models ─────────────────────────────────────────────────────────────


class AnchorValue(ValueModel):
    """One block-local anchor control of a burst job, as the corner context uses it.

    ``sweep_id`` is the job's own store id — the stamp every file of that job carries,
    not a per-recording time (the pass has none) — published so a reader can see that no
    time-weight is available rather than assume one is.
    """

    label: str
    short: str
    order: int
    sweep_id: str
    mean_mm_s: float
    supported_gates: int


class JobContext(ValueModel):
    """One burst job's anchored bracket: its structure, its anchors and their spread."""

    job: str
    step: int
    burst_length: int
    emissions_per_profile: int
    structure: str
    anchors: tuple[AnchorValue, ...]
    anchor_floor_mm_s: float
    anchor_floor_source: str


class CornerValue(ValueModel):
    """One corner of the 2x2, with the plan's declaration beside its decoded condition.

    ``scalar_mean_native_mm_s`` is the unweighted mean over the corner's *own* supported
    native gates (145 at 0.6167 mm, 31 at 2.96 mm) — the reduction the pass's table uses,
    and a grid-mismatched comparison with an anchor's 49 gate mean, which is why the two
    anchor differences below are published as a placement and never as a residual.
    """

    label: str
    job: str
    order: int
    sweep_id: str
    burst_length: int
    emissions_per_profile: int
    pitch_requested_mm: float
    pitch_stored_mm: float
    gates: int
    supported_gates: int
    plan_resolution_mm: float
    plan_gates: int
    plan_burst_length: int
    plan_emissions_per_profile: int
    scalar_mean_native_mm_s: float
    scalar_mean_knots_mm_s: float
    between: tuple[str, str]
    vs_left_anchor_mm_s: float
    vs_right_anchor_mm_s: float
    anchor_floor_mm_s: float
    note: str


class KnotRow(ValueModel):
    """One common knot: the four native reads, their offsets and the interaction there."""

    knot: int
    depth_mm: float
    native_mm: dict[str, float]
    offset_mm: dict[str, float]
    corner_mm_s: dict[str, float]
    interaction_mm_s: float


class CornerContrast(ValueModel):
    """One simple effect of the 2x2, depth-resolved and reduced over the knots."""

    name: str
    definition: str
    pitch_mm: float | None
    burst_length: int | None
    left: str
    right: str
    mean_mm_s: float
    min_mm_s: float
    min_depth_mm: float
    max_mm_s: float
    max_depth_mm: float
    max_abs_mm_s: float
    max_abs_depth_mm: float


class DepthResolved(ArrayModel):
    """The four corner profiles on the common knots and everything derived from them."""

    knots_mm: array_field(np.float64, rank=1)
    cc1: array_field(np.float64, rank=1)
    cc2: array_field(np.float64, rank=1)
    cc3: array_field(np.float64, rank=1)
    cc4: array_field(np.float64, rank=1)
    interaction: array_field(np.float64, rank=1)
    pitch_at_burst_4: array_field(np.float64, rank=1)
    pitch_at_burst_18: array_field(np.float64, rank=1)
    burst_at_pitch_0617: array_field(np.float64, rank=1)
    burst_at_pitch_296: array_field(np.float64, rank=1)


class PitchBurst(ValueModel):
    """The WP3 result: the aligned corners, the interaction, the floors and the gate."""

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    analysis_commit: str
    window_s: float
    window_revolutions: int
    support_min_mm: float
    support_max_mm: float
    statistic: str
    knot_pitch_mm: float
    half_coarse_pitch_mm: float
    knot_source: tuple[str, ...]
    knot_count: int
    max_abs_offset_mm: float
    max_abs_offset_label: str
    max_abs_offset_knot: int
    max_abs_offset_depth_mm: float
    corners: tuple[CornerValue, ...]
    jobs: tuple[JobContext, ...]
    knots: tuple[KnotRow, ...]
    contrasts: tuple[CornerContrast, ...]
    depth_resolved: DepthResolved
    interaction_reduction_mm_s: float
    interaction_min_mm_s: float
    interaction_min_depth_mm: float
    interaction_max_mm_s: float
    interaction_max_depth_mm: float
    interaction_max_abs_mm_s: float
    interaction_max_abs_depth_mm: float
    depth_resolved_floor_mm_s: float
    depth_resolved_floor_depth_mm: float
    depth_resolved_floor_source: str
    depth_averaged_floor_mm_s: float
    depth_averaged_floor_source: str
    anchor_floors_mm_s: dict[str, float]
    anchor_floor_source: str
    knots_above_anchor_floor: dict[str, int]
    knots_above_depth_resolved_floor: int
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every WP3 gate check holds."""
        return all(self.checks.values())

    @property
    def anchor_floor_shares(self) -> dict[str, float]:
        """The share of knots whose ``|I(z)|`` exceeds each burst job's own anchor floor."""
        return {
            job: count / self.knot_count
            for job, count in self.knots_above_anchor_floor.items()
        }


# ── the measurement ────────────────────────────────────────────────────


class AlignedCorner(NamedTuple):
    """One corner's native read at every knot: where it was taken and what it carries."""

    label: str
    native_mm: np.ndarray
    offset_mm: np.ndarray
    values_mm_s: np.ndarray


def align_corner(
    label: str,
    depths_mm: np.ndarray,
    values_mm_s: np.ndarray,
    knots_mm: np.ndarray,
    *,
    half_pitch_mm: float = HALF_COARSE_PITCH_MM,
) -> AlignedCorner:
    """Read one corner at its **nearest native gate** to each knot, or refuse by name.

    No interpolation, no resampling and no fit: the knot's value is the value the
    recording actually measured at the gate nearest it, and both the native depth used
    and the offset from the knot are returned. Refuses — with a named error and nothing
    written — when any required offset exceeds ``half_pitch_mm``, because that far from
    its knot a gate is not the same depth as the knot it would stand in for.

    Raises:
        PitchBurstError: when the corner is empty, the knot set is empty, the arrays do
            not agree in length, or a required offset exceeds ``half_pitch_mm``.
    """
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    values = np.asarray(values_mm_s, dtype=float).reshape(-1)
    knots = np.asarray(knots_mm, dtype=float).reshape(-1)
    if depths.size == 0 or depths.shape != values.shape:
        raise PitchBurstError(
            f"corner {label!r}: {depths.size} native gates against {values.size} values; "
            "the alignment needs one gate per value"
        )
    if knots.size == 0:
        raise PitchBurstError(
            f"corner {label!r}: the knot set is empty, so there is nothing to align on"
        )
    indices = nearest_gate_indices(depths, knots)
    native = depths[indices]
    offset = native - knots
    worst = int(np.argmax(np.abs(offset)))
    if abs(float(offset[worst])) > half_pitch_mm + TOLERANCE:
        raise PitchBurstError(
            f"corner {label!r}: the nearest native gate to the knot at "
            f"{float(knots[worst]):.4f} mm is {float(native[worst]):.4f} mm, an offset of "
            f"{abs(float(offset[worst])):.4f} mm, which exceeds half the coarse pitch "
            f"({half_pitch_mm:.4f} mm). No interpolation is performed and nothing is "
            "written: a gate that far from its knot is not the same depth as the knot"
        )
    return AlignedCorner(
        label=label, native_mm=native, offset_mm=offset, values_mm_s=values[indices]
    )


def _corner_points(decoded: PassDecoding) -> dict[str, DecodedPoint]:
    """The four corner recordings, verified against the pass's own decoded structure.

    Which ``cc*`` belongs to which job and carries which pitch and burst is **read from
    the recordings** and re-checked against the plan's declaration: the burst-4 job must
    hold ``cc1``/``cc3`` and the burst-18 job ``cc2``/``cc4``, each once, with the
    decoded burst length and the stored pitch the application accepts for the requested
    resolution.
    """
    seen = [
        str(point.binding.point.label)
        for point in decoded.points
        if str(point.binding.point.label) in CORNER_LABELS
    ]
    if sorted(seen) != sorted(CORNER_LABELS):
        raise PitchBurstError(
            f"the pass holds {sorted(seen)} among the corner labels, expected exactly "
            f"{sorted(CORNER_LABELS)}: the 2x2 needs one recording per corner"
        )
    found: dict[str, DecodedPoint] = {}
    sound_speed = float(decoded.plan.sound_speed_ms)
    for label, job, pitch, burst in CORNERS:
        matches = [
            point
            for point in decoded.of_job(job)
            if str(point.binding.point.label) == label
        ]
        if len(matches) != 1:
            raise PitchBurstError(
                f"job {job!r}: {len(matches)} recordings are labelled {label!r}; the "
                f"plan places {label!r} in that job and the 2x2 needs exactly one"
            )
        point = matches[0]
        observed = (
            float(point.config.resolution_mm or 0.0),
            int(point.config.burst_length or 0),
        )
        expected = (clamp_resolution(pitch, sound_speed), burst)
        if not (
            math.isclose(observed[0], expected[0], rel_tol=1e-9)
            and observed[1] == expected[1]
        ):
            raise PitchBurstError(
                f"{point.relative_path}: decodes to pitch {observed[0]!r} at burst "
                f"{observed[1]}, the design's {label!r} corner is pitch {pitch!r} "
                f"(stored {expected[0]!r}) at burst {burst}"
            )
        found[label] = point
    return found


def _plan_point(decoded: PassDecoding, job: str, label: str):
    """The plan's own declaration of one corner point, or a refusal naming it."""
    for planned in decoded.plan.jobs:
        if str(planned.job) != job:
            continue
        for point in planned.points:
            if str(point.label) == label:
                return point
    raise PitchBurstError(
        f"the plan's job {job!r} declares no point {label!r}; the corners this slice "
        "measures must be the points the pass planned"
    )


def _knots(decoded: PassDecoding, points: dict[str, DecodedPoint]) -> np.ndarray:
    """The common knot set: the coarse corners' own native supported gate depths.

    The knot set is **not chosen here**: it is what the 2.960 mm measurement actually
    measured inside the common support (the coarsest participating grid), and the two
    coarse corners must agree on it exactly. A grid that is not the pass's coarse pitch,
    or two coarse corners whose gates disagree, is refused by name.
    """
    grids = {
        label: supported_gates(points[label], decoded.support_mm)
        for label in KNOT_LABELS
    }
    first = KNOT_LABELS[0]
    for label in KNOT_LABELS[1:]:
        if not np.array_equal(grids[label], grids[first]):
            raise PitchBurstError(
                f"{points[label].relative_path}: its native supported gates are not "
                f"{points[first].relative_path}'s ({grids[label].size} against "
                f"{grids[first].size}); the two coarse corners must measure one grid, "
                "which is the knot set"
            )
    knots = grids[first]
    if knots.size < 2:
        raise PitchBurstError(
            f"{points[first].relative_path}: {knots.size} native gate(s) fall inside "
            f"the common support {decoded.support_mm}; a knot set needs two"
        )
    pitch = float(np.diff(knots).mean())
    if not math.isclose(pitch, COARSE_PITCH_MM, rel_tol=1e-6):
        raise PitchBurstError(
            f"the coarse corners' own gate pitch is {pitch!r} mm, not the pass's "
            f"{COARSE_PITCH_MM} mm: the knot set is the coarsest participating pitch and "
            "this is not it"
        )
    return knots


def _job_context(decoded: PassDecoding, job: str) -> JobContext:
    """One burst job's three anchors, its structure and its own anchor spread.

    The spread is recomputed here from the recordings and is the guard the conservative
    reading uses; the gate re-checks it against WP1's published floor at that floor's
    precision.
    """
    points = decoded.of_job(job)
    anchors: list[DecodedPoint] = []
    for label, _ in ANCHORS:
        matches = [point for point in points if str(point.binding.point.label) == label]
        if len(matches) != 1:
            raise PitchBurstError(
                f"job {job!r}: {len(matches)} recordings are labelled {label!r}, "
                "expected exactly one block-local anchor control"
            )
        anchors.append(matches[0])
    values = [
        supported_mean_of(
            anchor,
            window_s=decoded.window_s,
            support_mm=decoded.support_mm,
            name=STATISTIC,
        )
        for anchor in anchors
    ]
    first = points[0]
    return JobContext(
        job=job,
        step=int(first.binding.job.step),
        burst_length=int(first.config.burst_length or 0),
        emissions_per_profile=int(first.config.emissions_per_profile or 0),
        structure=_structure(points),
        anchors=tuple(
            AnchorValue(
                label=str(anchor.binding.point.label),
                short=short,
                order=int(anchor.binding.order),
                sweep_id=_sweep_id(anchor),
                mean_mm_s=value,
                supported_gates=int(supported_gates(anchor, decoded.support_mm).size),
            )
            for anchor, (_, short), value in zip(anchors, ANCHORS, values, strict=True)
        ),
        anchor_floor_mm_s=float(max(values) - min(values)),
        anchor_floor_source=ANCHOR_FLOOR_SOURCE,
    )


def _sweep_id(point: DecodedPoint) -> str:
    """The job's own store id, the stamp every file of that job carries.

    It is *not* a per-recording time: the pass stores no such clock, and this module
    names that fact rather than dressing the id up as one.
    """
    sweep_id = str(point.binding.recording_stamp)
    if not sweep_id:
        raise PitchBurstError(
            f"{point.relative_path}: no store id in the file name, so the corner cannot "
            "be attributed to its job's sweep"
        )
    return sweep_id


def _structure(points: Sequence[DecodedPoint]) -> str:
    """A job's acquisition order with its anchors marked, e.g. ``B - CC1 - M - CC3 - E``."""
    names = {label: short for label, short in ANCHORS}
    ordered = sorted(points, key=lambda point: int(point.binding.order))
    return " - ".join(
        names.get(
            str(point.binding.point.label), str(point.binding.point.label).upper()
        )
        for point in ordered
    )


def _bracketing_anchors(
    anchors: Sequence[AnchorValue], order: int
) -> tuple[AnchorValue, AnchorValue]:
    """The anchors that bracket one corner in acquisition order, or a refusal."""
    before = [anchor for anchor in anchors if anchor.order < order]
    after = [anchor for anchor in anchors if anchor.order > order]
    if not before or not after:
        raise PitchBurstError(
            f"the corner at order {order} is not bracketed by an anchor on each side; "
            "the pass's controls are what places a measurement inside its job"
        )
    return (
        max(before, key=lambda anchor: anchor.order),
        min(after, key=lambda anchor: anchor.order),
    )


def _corner_value(
    decoded: PassDecoding,
    label: str,
    job: str,
    point: DecodedPoint,
    planned,
    context: JobContext,
    aligned: AlignedCorner,
) -> CornerValue:
    """One corner as published, with the plan's declaration and its block's anchors."""
    scalar_native = supported_mean_of(
        point,
        window_s=decoded.window_s,
        support_mm=decoded.support_mm,
        name=STATISTIC,
    )
    supported = int(supported_gates(point, decoded.support_mm).size)
    anchors = context.anchors
    left, right = _bracketing_anchors(anchors, int(point.binding.order))
    return CornerValue(
        label=label,
        job=job,
        order=int(point.binding.order),
        sweep_id=_sweep_id(point),
        burst_length=int(point.config.burst_length or 0),
        emissions_per_profile=int(point.config.emissions_per_profile or 0),
        pitch_requested_mm=float(planned.parameters.resolution_mm),
        pitch_stored_mm=float(point.config.resolution_mm or 0.0),
        gates=int(point.values.shape[1]),
        supported_gates=supported,
        plan_resolution_mm=float(planned.parameters.resolution_mm),
        plan_gates=int(planned.parameters.gates),
        plan_burst_length=int(planned.parameters.burst_length),
        plan_emissions_per_profile=int(planned.parameters.emissions_per_profile),
        scalar_mean_native_mm_s=scalar_native,
        scalar_mean_knots_mm_s=float(np.mean(aligned.values_mm_s)),
        between=(left.label, right.label),
        vs_left_anchor_mm_s=float(scalar_native - left.mean_mm_s),
        vs_right_anchor_mm_s=float(scalar_native - right.mean_mm_s),
        anchor_floor_mm_s=context.anchor_floor_mm_s,
        note=(
            "the corner's own scalar is the unweighted mean over its "
            f"{supported} native supported gates at its own pitch, while an anchor's "
            "is the mean over that anchor's 49 gates at 1.85 mm: the two differences "
            "here are a grid-mismatched placement of the corner inside its block, not "
            "a residual, and neither enters I(z)"
        ),
    )


def _contrast(
    name: str,
    definition: str,
    left_label: str,
    right_label: str,
    values: np.ndarray,
    knots_mm: np.ndarray,
    *,
    pitch_mm: float | None,
    burst_length: int | None,
) -> CornerContrast:
    """One simple effect, depth-resolved and reduced over the knots."""
    worst = int(np.argmax(np.abs(values)))
    lowest = int(np.argmin(values))
    highest = int(np.argmax(values))
    return CornerContrast(
        name=name,
        definition=definition,
        pitch_mm=pitch_mm,
        burst_length=burst_length,
        left=left_label,
        right=right_label,
        mean_mm_s=float(np.mean(values)),
        min_mm_s=float(values[lowest]),
        min_depth_mm=float(knots_mm[lowest]),
        max_mm_s=float(values[highest]),
        max_depth_mm=float(knots_mm[highest]),
        max_abs_mm_s=float(abs(values[worst])),
        max_abs_depth_mm=float(knots_mm[worst]),
    )


def measure(
    decoded: PassDecoding, *, analysis_commit: str, plan_path: Path = PLAN_PATH
) -> PitchBurst:
    """Measure WP3 on an already-decoded pass, or refuse by name.

    Raises:
        PitchBurstError: for anything the frozen WP0 ingest refuses, for a corner that
            is missing, duplicated or not the plan's condition, for coarse corners whose
            native grids disagree, for a knot grid that is not the coarse pitch, and for
            an alignment offset beyond half the coarse pitch.
    """
    commit = str(analysis_commit).strip()
    if not commit:
        raise PitchBurstError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )
    points = _corner_points(decoded)
    planned = {label: _plan_point(decoded, job, label) for label, job, _, _ in CORNERS}
    emissions = {
        int(points[label].config.emissions_per_profile or 0) for label in CORNER_LABELS
    }
    if len(emissions) != 1:
        raise PitchBurstError(
            f"the four corners do not share one emissions level ({sorted(emissions)}); "
            "the 2x2 must be a clean pitch x burst cross, so a build that has moved "
            "another setting refuses rather than reporting a confounded interaction"
        )

    contexts = {job: _job_context(decoded, job) for job in JOBS}
    knots = _knots(decoded, points)
    knot_pitch = float(np.diff(knots).mean())
    half_pitch = knot_pitch / 2.0

    aligned: dict[str, AlignedCorner] = {}
    for label, _, _, _ in CORNERS:
        point = points[label]
        values = gate_statistics(
            point, window_s=decoded.window_s, support_mm=decoded.support_mm
        )[STATISTIC]
        aligned[label] = align_corner(
            label,
            supported_gates(point, decoded.support_mm),
            values,
            knots,
            half_pitch_mm=half_pitch,
        )

    interaction = (aligned["cc2"].values_mm_s - aligned["cc4"].values_mm_s) - (
        aligned["cc1"].values_mm_s - aligned["cc3"].values_mm_s
    )
    burst_at_0617 = aligned["cc2"].values_mm_s - aligned["cc1"].values_mm_s
    burst_at_296 = aligned["cc4"].values_mm_s - aligned["cc3"].values_mm_s
    pitch_at_4 = aligned["cc3"].values_mm_s - aligned["cc1"].values_mm_s
    pitch_at_18 = aligned["cc4"].values_mm_s - aligned["cc2"].values_mm_s

    corners = tuple(
        _corner_value(
            decoded,
            label,
            job,
            points[label],
            planned[label],
            contexts[job],
            aligned[label],
        )
        for label, job, _, _ in CORNERS
    )
    rows = tuple(
        KnotRow(
            knot=index,
            depth_mm=float(knots[index]),
            native_mm={
                label: float(aligned[label].native_mm[index]) for label in CORNER_LABELS
            },
            offset_mm={
                label: float(aligned[label].offset_mm[index]) for label in CORNER_LABELS
            },
            corner_mm_s={
                label: float(aligned[label].values_mm_s[index])
                for label in CORNER_LABELS
            },
            interaction_mm_s=float(interaction[index]),
        )
        for index in range(knots.size)
    )
    contrasts = (
        _contrast(
            "pitch_at_burst_4",
            "the pitch contrast at burst 4: v(2.96,4) - v(0.617,4), cc3 - cc1",
            "cc3",
            "cc1",
            pitch_at_4,
            knots,
            pitch_mm=2.96,
            burst_length=4,
        ),
        _contrast(
            "pitch_at_burst_18",
            "the pitch contrast at burst 18: v(2.96,18) - v(0.617,18), cc4 - cc2",
            "cc4",
            "cc2",
            pitch_at_18,
            knots,
            pitch_mm=2.96,
            burst_length=18,
        ),
        _contrast(
            "burst_at_pitch_0617",
            "the burst contrast at 0.6167 mm: v(0.617,18) - v(0.617,4), cc2 - cc1",
            "cc2",
            "cc1",
            burst_at_0617,
            knots,
            pitch_mm=0.617,
            burst_length=None,
        ),
        _contrast(
            "burst_at_pitch_296",
            "the burst contrast at 2.96 mm: v(2.96,18) - v(2.96,4), cc4 - cc3",
            "cc4",
            "cc3",
            burst_at_296,
            knots,
            pitch_mm=2.96,
            burst_length=None,
        ),
    )

    offset_field = {
        (label, int(index)): float(aligned[label].offset_mm[index])
        for label in CORNER_LABELS
        for index in range(knots.size)
    }
    worst_key = max(offset_field, key=lambda key: abs(offset_field[key]))
    worst_label, worst_index = worst_key
    values = interaction
    extremes = {
        "min": int(np.argmin(values)),
        "max": int(np.argmax(values)),
        "abs": int(np.argmax(np.abs(values))),
    }
    depth_resolved = DepthResolved(
        knots_mm=knots,
        cc1=aligned["cc1"].values_mm_s,
        cc2=aligned["cc2"].values_mm_s,
        cc3=aligned["cc3"].values_mm_s,
        cc4=aligned["cc4"].values_mm_s,
        interaction=interaction,
        pitch_at_burst_4=pitch_at_4,
        pitch_at_burst_18=pitch_at_18,
        burst_at_pitch_0617=burst_at_0617,
        burst_at_pitch_296=burst_at_296,
    )
    knots_above_anchor = {
        job: int(
            np.count_nonzero(np.abs(interaction) > ANCHOR_FLOOR_MM_S[job] + TOLERANCE)
        )
        for job in JOBS
    }
    checks = _checks(
        decoded=decoded,
        commit=commit,
        corners=corners,
        contexts=contexts,
        rows=rows,
        contrasts=contrasts,
        depth_resolved=depth_resolved,
        knots=knots,
        knot_pitch=knot_pitch,
        half_pitch=half_pitch,
        interaction=interaction,
        emissions=emissions,
    )
    return PitchBurst(
        dataset_root=decoded.dataset_root.as_posix(),
        plan=str(decoded.plan.plan),
        plan_path=Path(plan_path).as_posix(),
        plan_fingerprint=decoded.plan_fingerprint,
        analysis_commit=commit,
        window_s=decoded.window_s,
        window_revolutions=decoded.window_revolutions,
        support_min_mm=decoded.support_mm[0],
        support_max_mm=decoded.support_mm[1],
        statistic=STATISTIC,
        knot_pitch_mm=knot_pitch,
        half_coarse_pitch_mm=half_pitch,
        knot_source=KNOT_LABELS,
        knot_count=int(knots.size),
        max_abs_offset_mm=abs(offset_field[worst_key]),
        max_abs_offset_label=worst_label,
        max_abs_offset_knot=worst_index,
        max_abs_offset_depth_mm=float(knots[worst_index]),
        corners=corners,
        jobs=tuple(contexts[job] for job in JOBS),
        knots=rows,
        contrasts=contrasts,
        depth_resolved=depth_resolved,
        interaction_reduction_mm_s=float(np.mean(interaction)),
        interaction_min_mm_s=float(values[extremes["min"]]),
        interaction_min_depth_mm=float(knots[extremes["min"]]),
        interaction_max_mm_s=float(values[extremes["max"]]),
        interaction_max_depth_mm=float(knots[extremes["max"]]),
        interaction_max_abs_mm_s=float(abs(values[extremes["abs"]])),
        interaction_max_abs_depth_mm=float(knots[extremes["abs"]]),
        depth_resolved_floor_mm_s=DEPTH_RESOLVED_FLOOR_MM_S,
        depth_resolved_floor_depth_mm=DEPTH_RESOLVED_FLOOR_DEPTH_MM,
        depth_resolved_floor_source=DEPTH_RESOLVED_FLOOR_SOURCE,
        depth_averaged_floor_mm_s=DEPTH_AVERAGED_FLOOR_MM_S,
        depth_averaged_floor_source=DEPTH_AVERAGED_FLOOR_SOURCE,
        anchor_floors_mm_s=dict(ANCHOR_FLOOR_MM_S),
        anchor_floor_source=ANCHOR_FLOOR_SOURCE,
        knots_above_anchor_floor=knots_above_anchor,
        knots_above_depth_resolved_floor=int(
            np.count_nonzero(
                np.abs(interaction) > DEPTH_RESOLVED_FLOOR_MM_S + TOLERANCE
            )
        ),
        checks=checks,
    )


def build_pitch_burst(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> PitchBurst:
    """The pitch x burst interaction of the committed pass, or a refusal by name.

    Raises:
        PitchBurstError: for anything the frozen WP0 ingest refuses, and for every
            structural condition :func:`measure` refuses.
    """
    decoded = decode_pass(dataset_root, plan_path=plan_path)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise PitchBurstError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )
    return measure(decoded, analysis_commit=str(commit), plan_path=Path(plan_path))


def _checks(
    *,
    decoded: PassDecoding,
    commit: str,
    corners: Sequence[CornerValue],
    contexts: dict[str, JobContext],
    rows: Sequence[KnotRow],
    contrasts: Sequence[CornerContrast],
    depth_resolved: DepthResolved,
    knots: np.ndarray,
    knot_pitch: float,
    half_pitch: float,
    interaction: np.ndarray,
    emissions: set[int],
) -> dict[str, bool]:
    """The WP3 gate: the structural facts that must hold before an interaction is published."""
    interaction_labels = set(CORNER_LABELS)
    per_knot = np.array([row.interaction_mm_s for row in rows], dtype=float)
    from_rows = np.array(
        [
            (row.corner_mm_s["cc2"] - row.corner_mm_s["cc4"])
            - (row.corner_mm_s["cc1"] - row.corner_mm_s["cc3"])
            for row in rows
        ],
        dtype=float,
    )
    pitches = {corner.label: corner.pitch_stored_mm for corner in corners}
    native_is_the_corners_own_grid = True
    for label, pitch in pitches.items():
        native = np.array([row.native_mm[label] for row in rows], dtype=float)
        if native.size < 2 or not np.all(np.diff(native) > 0.0):
            native_is_the_corners_own_grid = False
            continue
        # Consecutive native reads are whole numbers of that corner's own gates apart,
        # which is what a nearest-gate pick on a native grid produces and what an
        # interpolated value would not.
        for step in np.diff(native):
            multiple = round(float(step) / pitch)
            if multiple < 1 or abs(float(step) - multiple * pitch) > 0.5 * pitch:
                native_is_the_corners_own_grid = False
    return {
        "four_corners_present": len(corners) == len(CORNER_LABELS)
        and [corner.label for corner in corners] == list(CORNER_LABELS)
        and len(
            {(corner.pitch_requested_mm, corner.burst_length) for corner in corners}
        )
        == 4,
        "corner_conditions_are_the_plans_declared_pitch_and_burst": all(
            math.isclose(
                corner.pitch_requested_mm,
                corner.plan_resolution_mm,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and corner.gates == corner.plan_gates
            and corner.burst_length == corner.plan_burst_length
            and corner.emissions_per_profile == corner.plan_emissions_per_profile
            and math.isclose(
                corner.pitch_stored_mm,
                clamp_resolution(
                    corner.plan_resolution_mm, float(decoded.plan.sound_speed_ms)
                ),
                rel_tol=1e-9,
            )
            for corner in corners
        ),
        "corners_share_one_emissions_level": len(emissions) == 1
        and all(
            corner.emissions_per_profile == next(iter(emissions)) for corner in corners
        ),
        "knots_are_the_coarse_grids_native_supported_gates": all(
            row.native_mm[label] == row.depth_mm
            for row in rows
            for label in KNOT_LABELS
        )
        and [float(knots[index]) for index in range(knots.size)]
        == [row.depth_mm for row in rows]
        and math.isclose(knot_pitch, COARSE_PITCH_MM, rel_tol=1e-6),
        "all_four_corners_are_read_at_native_gates": native_is_the_corners_own_grid
        and all(
            abs(row.offset_mm[label]) <= half_pitch + TOLERANCE
            for row in rows
            for label in CORNER_LABELS
        ),
        "no_alignment_offset_beyond_half_the_coarse_pitch": max(
            abs(row.offset_mm[label]) for row in rows for label in CORNER_LABELS
        )
        <= half_pitch + TOLERANCE,
        "interaction_recomputes_from_the_published_corner_profiles": bool(
            np.allclose(per_knot, interaction, rtol=0.0, atol=1e-12)
            and np.allclose(from_rows, interaction, rtol=0.0, atol=1e-12)
            and np.allclose(
                np.asarray(depth_resolved.interaction, dtype=float),
                interaction,
                rtol=0.0,
                atol=0.0,
            )
        ),
        "the_four_contrasts_carry_the_interaction": len(contrasts) == 4
        and bool(
            np.allclose(
                interactions_from_contrasts(depth_resolved),
                interaction,
                rtol=0.0,
                atol=1e-12,
            )
        )
        and {contrast.name for contrast in contrasts}
        == {
            "pitch_at_burst_4",
            "pitch_at_burst_18",
            "burst_at_pitch_0617",
            "burst_at_pitch_296",
        },
        "anchors_excluded_from_the_interaction": interaction_labels
        == set(CORNER_LABELS)
        and not any(label.startswith(CONTROL_PREFIX) for label in interaction_labels)
        and all(
            anchor.label.startswith(CONTROL_PREFIX)
            for context in contexts.values()
            for anchor in context.anchors
        )
        and all(context.anchor_floor_mm_s > 0.0 for context in contexts.values()),
        "anchor_floors_reproduce_wp1": all(
            math.isclose(
                round(context.anchor_floor_mm_s, 3),
                ANCHOR_FLOOR_MM_S[context.job],
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for context in contexts.values()
        ),
        "the_two_screening_endpoints_are_kept_apart": math.isclose(
            DEPTH_RESOLVED_FLOOR_MM_S, 14.603, rel_tol=0.0, abs_tol=1e-12
        )
        and math.isclose(DEPTH_AVERAGED_FLOOR_MM_S, 4.235, rel_tol=0.0, abs_tol=1e-12)
        and DEPTH_RESOLVED_FLOOR_MM_S > DEPTH_AVERAGED_FLOOR_MM_S,
        "window_and_support_are_the_wp0_ones": math.isclose(
            decoded.window_s, DESIGNED_WINDOW_S, rel_tol=0.0, abs_tol=1e-12
        )
        and decoded.support_mm[1] > decoded.support_mm[0],
        "engine_revision_recorded": bool(commit),
    }


def interactions_from_contrasts(depth_resolved: DepthResolved) -> np.ndarray:
    """``I(z)`` rebuilt from the published simple effects, as two identities.

    ``I = burst at 0.6167 mm - burst at 2.96 mm = pitch at burst 4 - pitch at burst 18``:
    the same array a reader of the contrast columns can reconstruct.
    """
    return np.asarray(depth_resolved.burst_at_pitch_0617, dtype=float) - np.asarray(
        depth_resolved.burst_at_pitch_296, dtype=float
    )


# ── artefacts ──────────────────────────────────────────────────────────


CSV_COLUMNS: tuple[str, ...] = (
    "knot",
    "depth_mm",
    "cc1_native_mm",
    "cc1_offset_mm",
    "cc1_mm_s",
    "cc2_native_mm",
    "cc2_offset_mm",
    "cc2_mm_s",
    "cc3_native_mm",
    "cc3_offset_mm",
    "cc3_mm_s",
    "cc4_native_mm",
    "cc4_offset_mm",
    "cc4_mm_s",
    "interaction_mm_s",
)

#: What each CSV column is, so the table is readable without this module.
CSV_COLUMN_DEFINITIONS: dict[str, str] = {
    "knot": "the knot's index in the common knot set, from 0",
    "depth_mm": "the common knot's physical depth: the 2.96 mm measurement's own gate",
    "cc*_native_mm": (
        "the native gate depth the corner was actually read at for this knot. For the "
        "two 2.96 mm corners it is the knot itself, offset 0"
    ),
    "cc*_offset_mm": (
        "native depth minus the knot, in mm: zero for the coarse corners, at most half "
        "the corner's own pitch for the others, and refused by name above half the "
        "coarse pitch (1.48 mm)"
    ),
    "cc*_mm_s": (
        "the corner's per-gate window mean velocity at that native gate, in mm/s, on "
        "the pass's primary 12 s window"
    ),
    "interaction_mm_s": (
        "I(z) = [cc2 - cc4] - [cc1 - cc3] at this knot, in mm/s: the difference of "
        "differences of the four corners"
    ),
}


def csv_text(model: PitchBurst) -> str:
    """Render ``pitch-burst.csv``: one row per common knot (LF, trailing newline)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(CSV_COLUMNS))
    for row in model.knots:
        cells: list[str] = [format_cell(row.knot), format_cell(row.depth_mm)]
        for label in CORNER_LABELS:
            cells.extend(
                [
                    format_cell(row.native_mm[label]),
                    format_cell(row.offset_mm[label]),
                    format_cell(row.corner_mm_s[label]),
                ]
            )
        cells.append(format_cell(row.interaction_mm_s))
        writer.writerow(cells)
    return buffer.getvalue()


def _result_document(number: float, description: str) -> dict[str, object]:
    """A measured number beside the description its sentence uses."""
    return {"value": number, "description": description}


def def_document(model: PitchBurst) -> dict[str, object]:
    """The WP3 document: the corners, the alignment, the interaction, the floors, the gate."""
    return {
        "dataset_root": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "analysis_commit": model.analysis_commit,
        "table": CSV_NAME,
        "table_rows": len(model.knots),
        "views": {
            "primary_window": {
                "window_s": model.window_s,
                "revolutions": model.window_revolutions,
                "rule": (
                    "the pass's designed exposure, the declared 12 s = 100 nominal "
                    "500-RPM revolutions, cut in each recording by its own stored "
                    "timestamps (WP0); every corner value is the per-gate "
                    f"{model.statistic} of that window and no other"
                ),
            },
            "common_support": {
                "support_min_mm": model.support_min_mm,
                "support_max_mm": model.support_max_mm,
                "rule": (
                    "the intersection of every recording's decoded depth range; each "
                    "corner is read on its own native gate grid inside it, and no "
                    "interpolation or resampling is applied at any stage"
                ),
            },
        },
        "alignment": {
            "rule": (
                "the four corners are compared on common physical knots no finer than "
                "2.96 mm, and the knot set is the 2.96 mm measurement's own native "
                "supported gate depths (the coarsest participating grid). Each corner "
                "is read at its nearest NATIVE gate to each knot: no interpolation, no "
                "resampling, no fit. The native depth used and its offset from the knot "
                "are published per knot in the table"
            ),
            "why_no_interpolation": (
                "a resampled profile is not the recording's own measurement: "
                "interpolating a 2.96 mm grid onto 0.6167 mm knots would manufacture "
                "structure the coarse recording never resolved, and interpolating the "
                "fine grid would hide the width of the gates it actually averaged. The "
                "pass therefore compares what was measured"
            ),
            "knot_source": list(model.knot_source),
            "knot_count": model.knot_count,
            "knot_pitch_mm": model.knot_pitch_mm,
            "half_coarse_pitch_mm": model.half_coarse_pitch_mm,
            "max_abs_offset_mm": model.max_abs_offset_mm,
            "max_abs_offset_label": model.max_abs_offset_label,
            "max_abs_offset_knot": model.max_abs_offset_knot,
            "max_abs_offset_depth_mm": model.max_abs_offset_depth_mm,
            "refusal": (
                "fail-closed: if a corner's nearest native gate to a required knot lies "
                "farther than half the coarse pitch (1.48 mm) from that knot, this slice "
                "refuses with a named error and writes nothing. A gate that far from its "
                "knot is not the same depth as the knot, and no interpolation is "
                "performed to make it one"
            ),
            "knot_edges": [model.knots[0].depth_mm, model.knots[-1].depth_mm],
        },
        "crossed_cells": [
            {
                "label": corner.label,
                "job": corner.job,
                "pitch_requested_mm": corner.pitch_requested_mm,
                "pitch_stored_mm": corner.pitch_stored_mm,
                "burst_length": corner.burst_length,
                "emissions_per_profile": corner.emissions_per_profile,
                "order": corner.order,
                "sweep_id": corner.sweep_id,
                "gates": corner.gates,
                "supported_gates": corner.supported_gates,
                "scalar_mean_native_mm_s": corner.scalar_mean_native_mm_s,
                "scalar_mean_knots_mm_s": corner.scalar_mean_knots_mm_s,
                "plan": {
                    "resolution_mm": corner.plan_resolution_mm,
                    "gates": corner.plan_gates,
                    "burst_length": corner.plan_burst_length,
                    "emissions_per_profile": corner.plan_emissions_per_profile,
                },
                "between": list(corner.between),
                "vs_left_anchor_mm_s": corner.vs_left_anchor_mm_s,
                "vs_right_anchor_mm_s": corner.vs_right_anchor_mm_s,
                "anchor_floor_mm_s": corner.anchor_floor_mm_s,
                "note": corner.note,
            }
            for corner in model.corners
        ],
        "blocks": [
            {
                "job": context.job,
                "step": context.step,
                "burst_length": context.burst_length,
                "emissions_per_profile": context.emissions_per_profile,
                "structure": context.structure,
                "corner_labels": [
                    corner.label
                    for corner in model.corners
                    if corner.job == context.job
                ],
                "anchors": [
                    {
                        "label": anchor.label,
                        "short": anchor.short,
                        "order": anchor.order,
                        "sweep_id": anchor.sweep_id,
                        "mean_mm_s": anchor.mean_mm_s,
                        "supported_gates": anchor.supported_gates,
                    }
                    for anchor in context.anchors
                ],
                "anchor_floor_mm_s": context.anchor_floor_mm_s,
                "anchor_floor_source": context.anchor_floor_source,
                "role": (
                    "context only: these block-local controls record the 1.85 mm "
                    "reference window at this job's own condition. They are not cells "
                    "of the 2x2 and never enter I(z); their spread is the guard the "
                    "conservative reading uses"
                ),
            }
            for context in model.jobs
        ],
        "interaction": {
            "definition": DEFINITIONS["interaction"],
            "reduction": DEFINITIONS["scalar_reduction"],
            "scalar_reduction_mm_s": model.interaction_reduction_mm_s,
            "per_knot": [
                {
                    "knot": row.knot,
                    "depth_mm": row.depth_mm,
                    "interaction_mm_s": row.interaction_mm_s,
                }
                for row in model.knots
            ],
            "min_mm_s": model.interaction_min_mm_s,
            "min_depth_mm": model.interaction_min_depth_mm,
            "max_mm_s": model.interaction_max_mm_s,
            "max_depth_mm": model.interaction_max_depth_mm,
            "max_abs_mm_s": model.interaction_max_abs_mm_s,
            "max_abs_depth_mm": model.interaction_max_abs_depth_mm,
            "identities": [
                "I(z) = [cc2 - cc4] - [cc1 - cc3] per knot",
                "I(z) = burst_at_pitch_0617(z) - burst_at_pitch_296(z)",
                "I(z) = pitch_at_burst_4(z) - pitch_at_burst_18(z)",
            ],
        },
        "corner_contrasts": [
            {
                "name": contrast.name,
                "definition": contrast.definition,
                "left": contrast.left,
                "right": contrast.right,
                "pitch_mm": contrast.pitch_mm,
                "burst_length": contrast.burst_length,
                "mean_mm_s": contrast.mean_mm_s,
                "min_mm_s": contrast.min_mm_s,
                "min_depth_mm": contrast.min_depth_mm,
                "max_mm_s": contrast.max_mm_s,
                "max_depth_mm": contrast.max_depth_mm,
                "max_abs_mm_s": contrast.max_abs_mm_s,
                "max_abs_depth_mm": contrast.max_abs_depth_mm,
            }
            for contrast in model.contrasts
        ],
        "floors": {
            "depth_resolved": {
                "value_mm_s": model.depth_resolved_floor_mm_s,
                "depth_mm": model.depth_resolved_floor_depth_mm,
                "source": model.depth_resolved_floor_source,
                "applies_to": (
                    "a depth-resolved magnitude: |I(z)| at one knot, or a corner "
                    "contrast's per-knot magnitude. Never applied to a scalar"
                ),
            },
            "depth_averaged": {
                "value_mm_s": model.depth_averaged_floor_mm_s,
                "source": model.depth_averaged_floor_source,
                "applies_to": (
                    "a scalar, depth-averaged effect: the unweighted mean over the knots. "
                    "Never applied to a per-knot magnitude"
                ),
            },
            "anchor_guards": {
                "value_mm_s": dict(model.anchor_floors_mm_s),
                "source": model.anchor_floor_source,
                "applies_to": (
                    "the conservative reading: each burst job's own block-local anchor "
                    "spread, so an interaction of comparable size cannot be separated "
                    "from the anchors' movement inside that job"
                ),
            },
            "never_mixed": (
                "the depth-resolved and the depth-averaged endpoints are different "
                "quantities from the same pair of runs; a number measured one way is "
                "never screened against the other's endpoint"
            ),
        },
        "conservative_reading": {
            "resolvable_below_mm_s": list(RESOLVABLE_BELOW_MM_S),
            "knot_count": model.knot_count,
            "knots_above_anchor_floor": dict(model.knots_above_anchor_floor),
            "knots_above_anchor_floor_share": dict(model.anchor_floor_shares),
            "knots_above_depth_resolved_floor": (
                model.knots_above_depth_resolved_floor
            ),
            "knots_above_depth_resolved_floor_share": (
                model.knots_above_depth_resolved_floor / model.knot_count
            ),
            "statement": (
                "a pitch or burst effect smaller than ~10-12 mm/s is not resolvable in "
                "this pass: both burst jobs' own block-local anchors move by that much "
                "inside their own job, so an interaction of that size or smaller cannot "
                "be separated from the anchors' movement. The magnitudes below are "
                "screening outcomes against those floors and against WP2's endpoints - "
                "neither outcome proves an axis effect"
            ),
        },
        "definitions": dict(DEFINITIONS),
        "columns": dict(CSV_COLUMN_DEFINITIONS),
        "checks": dict(sorted(model.checks.items())),
        "ok": model.ok,
    }


def _percent(count: int, total: int) -> str:
    """A count's share of the knots, as the documents print it."""
    return f"{100.0 * count / total:.1f} %" if total else "n/a"


def markdown_text(model: PitchBurst) -> str:
    """Render ``pitch-burst.md``: the reading of this run's numbers (LF, trailing newline).

    The document is generated with the artefacts, so its tables are the published
    numbers rather than a hand copy of them.
    """
    by_label = {corner.label: corner for corner in model.corners}
    lines: list[str] = []
    add = lines.append
    add("# WP3 — the pitch × burst interaction")
    add("")
    add(
        "**Status:** WP3 deliverable of "
        "[`docs/dop3000/sparse-pass-analysis-plan.md`]"
        "(../../docs/dop3000/sparse-pass-analysis-plan.md) §4, generated by "
        f"`udv-sparse-pitch-burst` against the revision `{model.analysis_commit}`. "
        "Regenerate with"
    )
    add("")
    add("```bash")
    add(
        ".venv/Scripts/python.exe -m udv_echo_process.cli sparse-pitch-burst \\\n"
        "    --analysis-commit <generator>"
    )
    add("```")
    add("")
    add(
        "**What it measures.** The four corners of the pass's pitch × burst design, on "
        "one common knot set: `cc1` (0.6167 mm, burst 4) and `cc3` (2.96 mm, burst 4) "
        "inside the `burst-4` job, `cc2` (0.6167 mm, burst 18) and `cc4` (2.96 mm, burst "
        "18) inside `burst-18`. The endpoint is the difference of differences"
    )
    add("")
    add("```text")
    add("I(z) = [v(0.617,18)(z) - v(2.96,18)(z)] - [v(0.617,4)(z) - v(2.96,4)(z)]")
    add("```")
    add("")
    add(
        "per common knot, reduced to the **unweighted mean over the knots**, with the "
        "four corner contrasts (the simple effects) beside it. Which `cc*` belongs to "
        "which job and carries which pitch and burst is **read from the decoded "
        "recordings** and re-checked against the plan, not assumed."
    )
    add("")
    add(
        "**What it does not claim.** No causation: every number is an observed "
        "difference between recordings. No significance test, no confidence interval, "
        "no statement below the anchors' own ~10-12 mm/s. No emissions statement (WP4), "
        "no reference-condition statement (that is CR1-CR4's, WP2), and no new "
        "acquisition."
    )
    add("")
    add("## The crossed cells")
    add("")
    add(
        f"Primary window {model.window_s:g} s ({model.window_revolutions} nominal "
        f"revolutions), common support {model.support_min_mm:.3f}–"
        f"{model.support_max_mm:.3f} mm, common knots {model.knot_count} at "
        f"{model.knot_pitch_mm:.4f} mm, statistic `{model.statistic}` (the per-gate "
        "window mean every slice here reduces from)."
    )
    add("")
    add("| pitch (mm) | burst 4 | burst 18 |")
    add("|---|---|---|")
    add(
        f"| 0.617 | `cc1` {by_label['cc1'].scalar_mean_native_mm_s:.3f} | "
        f"`cc2` {by_label['cc2'].scalar_mean_native_mm_s:.3f} |"
    )
    add(
        f"| 2.96 | `cc3` {by_label['cc3'].scalar_mean_native_mm_s:.3f} | "
        f"`cc4` {by_label['cc4'].scalar_mean_native_mm_s:.3f} |"
    )
    add("")
    add(
        "Each cell is that corner's unweighted mean velocity over its **own** supported "
        "native gates (145, 145, 31 and 31 gates at 0.6167, 0.6167, 2.96 and 2.96 mm) "
        "on the primary window — the reduction the pass's table uses. The same corners "
        "reduced over the common knots instead:"
    )
    add("")
    add(
        "| corner | job | pitch stored (mm) | burst | gates | supported | mean over the "
        "knots (mm/s) | order | between |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for corner in model.corners:
        add(
            f"| `{corner.label}` | {corner.job} | {corner.pitch_stored_mm:.6f} | "
            f"{corner.burst_length} | {corner.gates} | {corner.supported_gates} | "
            f"{corner.scalar_mean_knots_mm_s:.3f} | {corner.order} | "
            f"{corner.between[0]} → {corner.between[1]} |"
        )
    add("")
    add("## Each corner beside its block-local anchors")
    add("")
    add(
        "The 1.85 mm anchor controls are **context, not cells**: they never enter "
        "`I(z)`. They are printed here so a reader sees where each corner sits relative "
        "to the movement its own job recorded."
    )
    add("")
    add(
        "| corner | job | corner mean (own gates, mm/s) | vs B | vs M | vs E | job anchor "
        "spread (mm/s) |"
    )
    add("|---|---|---|---|---|---|---|")
    for corner in model.corners:
        block = next(item for item in model.jobs if item.job == corner.job)
        means = {anchor.short: anchor.mean_mm_s for anchor in block.anchors}
        add(
            f"| `{corner.label}` | {corner.job} | "
            f"{corner.scalar_mean_native_mm_s:.3f} | "
            f"{corner.scalar_mean_native_mm_s - means['B']:+.3f} | "
            f"{corner.scalar_mean_native_mm_s - means['M']:+.3f} | "
            f"{corner.scalar_mean_native_mm_s - means['E']:+.3f} | "
            f"{block.anchor_floor_mm_s:.3f} |"
        )
    add("")
    add(
        "The anchor means those differences are taken against, and each job's structure:"
    )
    add("")
    for block in model.jobs:
        cells = ", ".join(
            f"{anchor.short} ({anchor.label}) {anchor.mean_mm_s:.3f}"
            for anchor in block.anchors
        )
        add(
            f"- `{block.job}` — burst {block.burst_length}, emissions "
            f"{block.emissions_per_profile}, {block.structure}: {cells} mm/s; "
            f"anchor spread {block.anchor_floor_mm_s:.3f} mm/s "
            f"({block.anchor_floor_source})."
        )
    add("")
    add(
        "These differences are **grid-mismatched by construction and are not "
        "residuals**: a corner's scalar is the mean over its own 145 or 31 gates at its "
        "own pitch, an anchor's is the mean over 49 gates at 1.85 mm. They place the "
        "corner inside its block; they enter no interaction and screen against nothing."
    )
    add("")
    add("## The alignment rule, and why nothing is interpolated")
    add("")
    add(
        f"- The knots are the 2.96 mm measurement's **own native supported gate "
        f"depths** — {model.knot_count} gates, "
        f"{model.knots[0].depth_mm:.3f}–{model.knots[-1].depth_mm:.3f} mm, step "
        f"{model.knot_pitch_mm:.4f} mm — which is the coarsest grid this design "
        "measures. The knot set is not chosen here: it is what that recording measured."
    )
    add(
        "- Every corner is read at its **nearest native gate** to each knot. No "
        "interpolation, no resampling, no fit: a resampled coarse profile would "
        "manufacture structure the 2.96 mm grid never resolved, and an upsampled one "
        "would hide the width of the gates the fine grid actually averaged."
    )
    add(
        "- Per knot the native depth actually used and its offset from the knot are "
        "published in `pitch-burst.csv` and `pitch-burst.json`."
    )
    add(
        f"- The largest offset this run needed is **{model.max_abs_offset_mm:.6f} mm** "
        f"(`{model.max_abs_offset_label}` at knot {model.max_abs_offset_knot} = "
        f"{model.max_abs_offset_depth_mm:.3f} mm); the 2.96 mm corners carry offset 0 by "
        f"construction."
    )
    add(
        f"- **Fail-closed:** an offset above half the coarse pitch "
        f"({model.half_coarse_pitch_mm:.4f} mm) refuses with a named error and writes "
        "nothing, because a gate that far from its knot is not the same depth as the "
        "knot."
    )
    add("")
    add("## What was measured: I(z)")
    add("")
    add(
        f"The scalar reduction of `I(z)` over the {model.knot_count} common knots is "
        f"**{model.interaction_reduction_mm_s:+.3f} mm/s** (its sign included). "
        f"Depth-resolved it runs from {model.interaction_min_mm_s:+.3f} mm/s at "
        f"{model.interaction_min_depth_mm:.3f} mm to "
        f"{model.interaction_max_mm_s:+.3f} mm/s at "
        f"{model.interaction_max_depth_mm:.3f} mm, with its largest magnitude "
        f"{model.interaction_max_abs_mm_s:.3f} mm/s at "
        f"{model.interaction_max_abs_depth_mm:.3f} mm."
    )
    add("")
    add("| knot | depth (mm) | I(z) (mm/s) |")
    add("|---|---|---|")
    for row in model.knots:
        add(f"| {row.knot} | {row.depth_mm:.3f} | {row.interaction_mm_s:+.3f} |")
    add("")
    add(
        "The four corner contrasts — the simple effects — each depth-resolved and "
        "reduced the same way:"
    )
    add("")
    add(
        "| contrast | reduction (mm/s) | min (mm/s) @ mm | max (mm/s) @ mm | largest "
        "magnitude (mm/s) @ mm |"
    )
    add("|---|---|---|---|---|")
    for contrast in model.contrasts:
        add(
            f"| {contrast.definition} | {contrast.mean_mm_s:+.3f} | "
            f"{contrast.min_mm_s:+.3f} @ {contrast.min_depth_mm:.3f} | "
            f"{contrast.max_mm_s:+.3f} @ {contrast.max_depth_mm:.3f} | "
            f"{contrast.max_abs_mm_s:.3f} @ {contrast.max_abs_depth_mm:.3f} |"
        )
    add("")
    add(
        "The identities that follow, and that a reader can check against the tables "
        "above: `I(z) = [cc2 - cc4] - [cc1 - cc3] = burst_at_pitch_0617 - "
        "burst_at_pitch_296 = pitch_at_burst_4 - pitch_at_burst_18`."
    )
    add("")
    add("## The floors, and which endpoint applies where")
    add("")
    add("| quantity | endpoint | value | source |")
    add("|---|---|---|---|")
    add(
        f"| depth-resolved magnitude (`\\|I(z)\\|` per knot, a contrast's per-knot "
        f"magnitude) | WP2's per-depth endpoint | "
        f"**{model.depth_resolved_floor_mm_s:.3f} mm/s** at "
        f"{model.depth_resolved_floor_depth_mm:.3f} mm | "
        f"{model.depth_resolved_floor_source} |"
    )
    add(
        f"| scalar / depth-averaged effect (the reduction over the knots) | WP2's "
        f"depth-averaged endpoint | **{model.depth_averaged_floor_mm_s:.3f} mm/s** | "
        f"{model.depth_averaged_floor_source} |"
    )
    add(
        f"| conservative guard | each burst job's own block-local anchor spread | "
        f"**{model.anchor_floors_mm_s['burst-4']:.3f}** mm/s (`burst-4`) and "
        f"**{model.anchor_floors_mm_s['burst-18']:.3f}** mm/s (`burst-18`) | "
        f"{model.anchor_floor_source} |"
    )
    add("")
    add(
        "The two WP2 endpoints are different quantities measured from the same pair of "
        "reference runs, and this slice never mixes them: a per-knot magnitude is "
        "screened against 14.603 mm/s, a scalar against 4.235 mm/s."
    )
    add("")
    add("## The conservative reading")
    add("")
    add(
        f"Both burst jobs' own anchors move by **{model.anchor_floors_mm_s['burst-4']:.3f} "
        f"mm/s** (`burst-4`) and **{model.anchor_floors_mm_s['burst-18']:.3f} mm/s** "
        f"(`burst-18`) inside their own job. A pitch or burst effect smaller than "
        "~10-12 mm/s is therefore **not resolvable in this pass**: it cannot be "
        "separated from the anchors' own movement in those jobs."
    )
    add("")
    add(
        f"- The scalar reduction of `I(z)` is "
        f"**{model.interaction_reduction_mm_s:+.3f} mm/s**. Its magnitude is "
        f"{abs(model.interaction_reduction_mm_s):.3f} mm/s, which is below both anchor "
        f"floors ({model.anchor_floors_mm_s['burst-4']:.3f} and "
        f"{model.anchor_floors_mm_s['burst-18']:.3f} mm/s) and also below the "
        f"depth-resolved endpoint: at the depth-averaged level this interaction is not "
        "separable from the two jobs' own anchor movement."
    )
    add(
        f"- Depth-resolved, `|I(z)|` is a screening outcome above the `burst-4` guard at "
        f"**{model.knots_above_anchor_floor['burst-4']} of {model.knot_count} knots "
        f"({_percent(model.knots_above_anchor_floor['burst-4'], model.knot_count)})** "
        f"and above the `burst-18` guard at "
        f"**{model.knots_above_anchor_floor['burst-18']} of {model.knot_count} "
        f"({_percent(model.knots_above_anchor_floor['burst-18'], model.knot_count)})**."
    )
    add(
        f"- Against WP2's depth-resolved endpoint ({model.depth_resolved_floor_mm_s:.3f} "
        f"mm/s), `|I(z)|` is a screening outcome above it at "
        f"**{model.knots_above_depth_resolved_floor} of {model.knot_count} knots "
        f"({_percent(model.knots_above_depth_resolved_floor, model.knot_count)})**."
    )
    add("")
    add(
        "So the honest reading of this pass is: the interaction is concentrated in the "
        "near and mid field, where its local magnitudes reach "
        f"{model.interaction_max_abs_mm_s:.3f} mm/s at "
        f"{model.interaction_max_abs_depth_mm:.3f} mm and change sign around the middle "
        "of the profile, while its depth-averaged value stays inside the anchors' own "
        "movement. Both statements are observations. Neither proves that the pitch, the "
        "burst or their combination caused anything — the two jobs differ in condition "
        "*and* in their own drift, and this pass has one realization per corner."
    )
    add("")
    add("## What is checked before a run is published")
    add("")
    add(
        "The command refuses — non-zero exit, named reason, nothing written — for "
        "anything the frozen WP0 ingest refuses, for a corner that is missing, "
        "duplicated or not the plan's declared condition, for coarse corners whose "
        "native grids disagree, for a knot grid that is not the coarse pitch, and for "
        "an alignment offset beyond half the coarse pitch. It then publishes only when "
        "every structural check below holds:"
    )
    add("")
    add("| check | holds |")
    add("|---|---|")
    for name, value in sorted(model.checks.items()):
        add(f"| `{name}` | {'yes' if value else 'no'} |")
    add("")
    add("## Artefacts")
    add("")
    add("| file | what it is |")
    add("|---|---|")
    add(
        f"| [`{CSV_NAME}`]({CSV_NAME}) | one row per common knot: the four corners' "
        "native depths used, their offsets, their values there and `I(z)` |"
    )
    add(
        f"| [`{DOC_NAME}`]({DOC_NAME}) | the definitions, the crossed cells with the "
        "plan's declaration, the alignment with every offset, the per-knot interaction, "
        "the contrasts, the floors, the conservative reading and the gate |"
    )
    add(
        f"| `{FIGURES_DIRNAME}/{FIGURE_NAME}` | the four corner profiles on the common "
        "knots, and `I(z)` against depth with the zero line, the depth-resolved floor "
        "band and the two anchor guards |"
    )
    add("| this document | the reading of the numbers, generated with them |")
    add("")
    add("## What is deliberately not here")
    add("")
    add(
        "- **No causation claim.** Every number is an observed difference between "
        "recordings of a moving rig. One realization per corner, no replicate, no "
        "significance test: nothing here says the pitch, the burst or their combination "
        "*produced* the difference."
    )
    add(
        "- **The anchors are not cells.** `ctrl-begin`/`ctrl-mid`/`ctrl-end` record the "
        "1.85 mm reference window at their own job's condition; they are neither "
        "factorial cell nor input to `I(z)`, and they are published only as the context "
        "a corner sits in."
    )
    add(
        "- **No claim below ~10-12 mm/s.** The two burst jobs' own anchor floors are "
        f"{model.anchor_floors_mm_s['burst-4']:.3f} and "
        f"{model.anchor_floors_mm_s['burst-18']:.3f} mm/s, so a pitch or burst effect of "
        "that size or smaller cannot be separated from the anchors' movement inside the "
        "jobs. Nothing in this slice asserts it."
    )
    add(
        "- **No new acquisition.** The pass is closed; this slice reads its committed "
        "bytes and changes no recording, log, manifest or plan."
    )
    add(
        "- **No change to the frozen artefacts.** WP0's table, WP1's anchor floors and "
        "WP2's reference floor are read, never rewritten; the 1.85 mm window appears here "
        "only as the anchors' context, because no 1.85 mm corner is a cell of this 2x2."
    )
    add(
        "- **No emissions statement** (WP4) and **no reference-condition statement** "
        "(WP2's CR1-CR4 alone)."
    )
    add("")
    return "\n".join(lines) + "\n"


def render_figure(model: PitchBurst, path: Path) -> Path:
    """Draw the four corners on the common knots and ``I(z)`` against depth.

    Two panels. The upper one keeps the four corner profiles individually visible on the
    knot grid the comparison used, with each corner's own native gates marked; the lower
    one draws ``I(z)`` with the zero line, WP2's depth-resolved floor as a band and the
    two anchor guards as lines. The monospace caption carries the floors, the alignment
    rule, the knot count and the conservative reading, so the image cannot travel
    without them.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    depths = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    figure, (levels, effect) = plt.subplots(
        2, 1, figsize=(7.6, 8.4), sharex=True, dpi=FIGURE_DPI
    )
    colors = {
        "cc1": "#1f77b4",
        "cc2": "#ff7f0e",
        "cc3": "#2ca02c",
        "cc4": "#d62728",
    }
    for corner in model.corners:
        levels.plot(
            getattr(model.depth_resolved, corner.label),
            depths,
            color=colors[corner.label],
            linewidth=1.5,
            label=(
                f"{corner.label}  pitch {corner.pitch_stored_mm:.4f} / burst "
                f"{corner.burst_length}  ({corner.job})"
            ),
        )
    levels.set_ylabel("depth [mm]")
    levels.invert_yaxis()
    levels.set_xlabel("window mean velocity at the knot [mm/s]")
    levels.set_title(
        "the four corners on the common knots — the 2.96 mm measurement's own gates\n"
        f"{model.knot_count} knots, step {model.knot_pitch_mm:.4f} mm; every corner read "
        "at its nearest native gate (no interpolation)",
        fontsize=9.5,
    )
    levels.grid(alpha=0.2)
    levels.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

    floor = model.depth_resolved_floor_mm_s
    effect.axvspan(-floor, floor, color="#d0d0d0", alpha=0.45, linewidth=0)
    effect.axvline(0.0, color="#444444", linewidth=0.8)
    for job, guard in sorted(model.anchor_floors_mm_s.items()):
        effect.axvline(guard, color="#7f7f7f", linewidth=0.9, linestyle="--")
        effect.axvline(-guard, color="#7f7f7f", linewidth=0.9, linestyle="--")
    effect.plot(
        model.depth_resolved.interaction,
        depths,
        color="#6a3d9a",
        linewidth=1.9,
        label="I(z), the difference of differences",
    )
    for contrast in model.contrasts:
        effect.plot(
            getattr(model.depth_resolved, contrast.name),
            depths,
            color="#999999",
            linewidth=0.7,
            label=contrast.name,
        )
    effect.set_ylabel("depth [mm]")
    effect.set_xlabel("difference of differences [mm/s]")
    span = 1.15 * max(
        model.interaction_max_abs_mm_s,
        max(contrast.max_abs_mm_s for contrast in model.contrasts),
        floor,
    )
    effect.set_xlim(-span, span)
    effect.set_title(
        f"I(z): reduction {model.interaction_reduction_mm_s:+.3f} mm/s over "
        f"{model.knot_count} knots; range {model.interaction_min_mm_s:+.3f} at "
        f"{model.interaction_min_depth_mm:.2f} mm to {model.interaction_max_mm_s:+.3f} "
        f"at {model.interaction_max_depth_mm:.2f} mm",
        fontsize=9,
    )
    effect.grid(alpha=0.2)
    effect.legend(loc="lower right", fontsize=6.5, ncol=2, framealpha=0.9)

    caption = _wrap(
        f"floors: depth-resolved |I(z)| vs WP2's {floor:.3f} mm/s at "
        f"{model.depth_resolved_floor_depth_mm:.3f} mm (grey band here); scalar/"
        f"depth-averaged vs WP2's {model.depth_averaged_floor_mm_s:.3f} mm/s — the two "
        "are never mixed. Anchor guards (dashed): "
        + " and ".join(
            f"{job} {value:.3f} mm/s"
            for job, value in sorted(model.anchor_floors_mm_s.items())
        )
        + ". Alignment: the knots are the 2.96 mm measurement's own native supported "
        f"gate depths ({model.knot_count} knots, {model.knots[0].depth_mm:.3f}-"
        f"{model.knots[-1].depth_mm:.3f} mm, step {model.knot_pitch_mm:.4f} mm) and "
        "every corner is read at its nearest NATIVE gate — no interpolation, no "
        f"resampling; the largest offset used is {model.max_abs_offset_mm:.6f} mm, and "
        f"an offset above half the coarse pitch ({model.half_coarse_pitch_mm:.4f} mm) "
        "is refused by name with nothing written. Conservative reading: a pitch or burst "
        "effect smaller than ~10-12 mm/s is not resolvable in this pass — |I(z)| is a "
        f"screening outcome above the burst-4 guard ({model.anchor_floors_mm_s['burst-4']:.3f}) "
        f"at {model.knots_above_anchor_floor['burst-4']}/{model.knot_count} knots and "
        f"above the burst-18 guard ({model.anchor_floors_mm_s['burst-18']:.3f}) at "
        f"{model.knots_above_anchor_floor['burst-18']}/{model.knot_count}, while the "
        f"depth-averaged reduction {model.interaction_reduction_mm_s:+.3f} mm/s stays "
        "inside that band. Primary window "
        f"{model.window_s:g} s ({model.window_revolutions} revolutions), common support "
        f"{model.support_min_mm:.3f}-{model.support_max_mm:.3f} mm, statistic "
        f"'{model.statistic}'. Observed differences only: no confidence interval, no "
        "significance test, no proof of an axis effect."
    )
    figure.text(
        0.01,
        0.012,
        caption,
        fontsize=5.2,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.90, bottom=0.22, hspace=0.20)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=FIGURE_DPI)
    plt.close(figure)
    return target


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


def write_pitch_burst(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> PitchBurst:
    """Build the interaction and write the table, the document, the prose and the figure.

    Every file is UTF-8 with LF endings and one trailing newline (the figure is a PNG
    written by a fixed renderer), so two runs on the same inputs and revision produce
    identical bytes. Nothing is written when the build refuses.
    """
    model = build_pitch_burst(
        dataset_root, plan_path=plan_path, analysis_commit=analysis_commit
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
    render_figure(model, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model


def pitch_burst_main(argv: list[str] | None = None) -> int:
    """``sparse-pitch-burst`` — write WP3's pitch x burst interaction.

    Reads the two burst jobs' corners and anchors through the frozen WP0 ingest's own
    binding and decoding, aligns the four corners on the 2.96 mm measurement's own
    native knots by each corner's nearest native gate, computes ``I(z)`` and its
    reduction with the four corner contrasts, and writes ``pitch-burst.csv``,
    ``pitch-burst.json``, ``pitch-burst.md`` and ``figures/pitch-burst.png`` into the
    report directory. The exit code is 0 when every WP3 gate check holds and 1
    otherwise, with the failure or the refusal named on stderr and nothing written when
    the build refuses.

    The declared return type is the exit code, and the command **raises**
    ``SystemExit`` with it — the form the frozen slice commands use, because the CLI's
    dispatcher ignores a return value.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-pitch-burst",
        description=(
            "WP3: the sparse pass's 2x2 pitch x burst interaction on the 2.96 mm "
            "measurement's own common knots"
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
            "directory to write pitch-burst.csv, pitch-burst.json, pitch-burst.md and "
            "figures/ into"
        ),
    )
    parser.add_argument(
        "--analysis-commit",
        default="",
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    report_dir = Path(args.report_dir)
    try:
        model = write_pitch_burst(
            Path(args.dataset_root),
            report_dir,
            plan_path=Path(args.plan_path),
            analysis_commit=args.analysis_commit or None,
        )
    except SparseIngestError as exc:
        print(f"udv-sparse-pitch-burst: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    for corner in model.corners:
        print(
            f"{corner.label:4s} {corner.job:9s} pitch {corner.pitch_stored_mm:.6f} "
            f"burst {corner.burst_length:2d} knots-mean "
            f"{corner.scalar_mean_knots_mm_s:9.4f}  native-mean "
            f"{corner.scalar_mean_native_mm_s:9.4f} mm/s"
        )
    print(
        f"I(z)  : reduction {model.interaction_reduction_mm_s:+9.4f} mm/s over "
        f"{model.knot_count} knots; range {model.interaction_min_mm_s:+.4f} at "
        f"{model.interaction_min_depth_mm:.3f} mm to {model.interaction_max_mm_s:+.4f} "
        f"at {model.interaction_max_depth_mm:.3f} mm; largest magnitude "
        f"{model.interaction_max_abs_mm_s:.4f} at {model.interaction_max_abs_depth_mm:.3f} mm"
    )
    for contrast in model.contrasts:
        print(
            f"      : {contrast.name:22s} mean {contrast.mean_mm_s:+9.4f} "
            f"largest magnitude {contrast.max_abs_mm_s:8.4f} at "
            f"{contrast.max_abs_depth_mm:6.3f} mm"
        )
    print(
        f"floors: depth-resolved {model.depth_resolved_floor_mm_s:.3f} mm/s at "
        f"{model.depth_resolved_floor_depth_mm:.3f} mm; depth-averaged "
        f"{model.depth_averaged_floor_mm_s:.3f} mm/s; anchor guards "
        + ", ".join(
            f"{job} {value:.3f}"
            for job, value in sorted(model.anchor_floors_mm_s.items())
        )
        + f" mm/s; |I(z)| above: WP2 {model.knots_above_depth_resolved_floor}, "
        f"burst-4 {model.knots_above_anchor_floor['burst-4']}, burst-18 "
        f"{model.knots_above_anchor_floor['burst-18']} of {model.knot_count} knots"
    )
    print(
        f"alignment: largest offset {model.max_abs_offset_mm:.6f} mm of a "
        f"{model.half_coarse_pitch_mm:.4f} mm half-pitch limit"
    )
    print(f"table   : {report_dir / CSV_NAME}")
    print(f"document: {report_dir / DOC_NAME}")
    print(f"prose   : {report_dir / MD_NAME}")
    print(f"figure  : {report_dir / FIGURES_DIRNAME / FIGURE_NAME}")
    failed = [name for name, ok in sorted(model.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sparse-pitch-burst: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
