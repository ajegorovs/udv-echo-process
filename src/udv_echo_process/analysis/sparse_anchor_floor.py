"""WP1 of the sparse-pass analysis: the per-job anchor floors.

**What this measures.** Each of the pass's five scientific jobs is bracketed by three
*block-local anchor controls* — ``ctrl-begin``, ``ctrl-mid``, ``ctrl-end`` — which
record the **reference spatial window** (1.85 mm x 50 gates) at *that job's* own
condition. This module turns them into one per-job floor, and it keeps the two things
the floor is made of **apart**:

- **drift** — the three signed differences over the job's real acquisition order,
  ``M - B``, ``E - M`` and ``E - B``. A monotone shift is a different statement from
  a scatter, and only the signed pair distinguishes them;
- **spread** — ``max - min`` over ``{B, M, E}``: how far apart the three anchors sit,
  whatever their order.

Both are reported for every one of the five shared statistics (``mean``, ``median``,
``iqr``, ``rms``, ``zero_fraction``), as scalars in ``anchor-floor.csv`` and
depth-resolved in ``anchor-floor.json`` and the figures. Neither is a confidence
interval: three anchors are three recordings, and no count of profiles or gates makes
them independent replicates.

**How the scientific rows relate to the anchors.** The acquisition order is
recoverable, so the bracket is explicit — for a burst job ``B - CC1 - M - CC3 - E``
(and ``B - CC2 - M - CC4 - E``), for an emissions job ``B - E8/E64/E128 - M - E`` — so
the designated measurement sits between ``begin`` and ``mid``, and ``end`` measures the
drift that follows it rather than bracketing it symmetrically.

**The pass carries no per-recording clock, and this module does not invent one.** The
``YYYYMMDDTHHMMSS`` segment of a file name is the job's ``sweep_id`` — identical for
every point of a job, as the pass's own logs spell it — so a row cannot be placed at an
interpolated instant between its anchors. What this module reports instead is, for every
scientific row whose gates are the anchors' gates, the residual against the *left*
anchor and against the *right* one: those two are the extremes of every possible linear
interpolation, so no weighting assumption enters and the bracket is still visible. Each
job also publishes its own wall-clock window beside the summed duration of its
recordings, so the handling time between them is an observed quantity rather than an
assumption. Where the row is at another pitch (the burst jobs' ``cc1``/``cc2``/``cc3``/
``cc4``), no residual is computed at all: that comparison needs WP3's cross-pitch
alignment and is deliberately **not** taken here.

**What it does not do.** No reference-condition statement: the anchors are not
realizations of the reference condition, and the phrase is reserved for CR1-CR4
(WP2). No pooling of the five jobs' floors into one number. No claim that an anchor
difference is a parameter effect. Nothing here changes the frozen WP0 artefacts — it
adds documents beside them, and it reads the recordings through
:mod:`udv_echo_process.analysis._sparse_pass`, so it cuts the same 12 s primary
window and masks the same common support the table does.
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
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.analysis._sparse_pass import (
    SCIENTIFIC_JOBS,
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

#: The three anchors, in acquisition order, with the short names the figures and the
#: prose use. ``B``/``M``/``E`` are positions *within a job*, never a global clock.
ANCHORS: tuple[tuple[str, str], ...] = (
    ("ctrl-begin", "B"),
    ("ctrl-mid", "M"),
    ("ctrl-end", "E"),
)

#: The four derived quantities every statistic carries. The three drifts are signed;
#: the range is not. They are not interchangeable and neither is a confidence
#: interval.
QUANTITIES: tuple[tuple[str, str, str], ...] = (
    ("drift_mid_minus_begin", "signed", "M - B over the job's acquisition order"),
    ("drift_end_minus_mid", "signed", "E - M over the job's acquisition order"),
    ("drift_end_minus_begin", "signed", "E - B, the whole-job drift"),
    (
        "anchor_range",
        "non-negative",
        "max - min over {B, M, E}: the anchor spread, whatever the order",
    ),
)

#: The statistics the floors are computed for: the shared per-gate set the WP0 table
#: aggregates, recomputed here per gate and then reduced the same way.
STATISTICS: tuple[str, ...] = ("mean", "median", "iqr", "rms", "zero_fraction")

#: The residual a bracketed scientific row is measured against is the ``mean``
#: per-gate level, interpolated between its bracketing anchors in real time.
RESIDUAL_STATISTIC = "mean"

#: The statistics whose drift is published depth-resolved (the location and the
#: robust spread; the other three are in the CSV as scalars).
DEPTH_STATISTICS: tuple[str, ...] = ("mean", "iqr")

CSV_NAME = "anchor-floor.csv"
DOC_NAME = "anchor-floor.json"
MD_NAME = "anchor-floor.md"
FIGURES_DIRNAME = "figures"
FIGURE_DPI = 150

#: The reference window the anchors record, as the plan requests it.
REFERENCE_WINDOW: tuple[float, int] = (1.85, 50)

TOLERANCE = 1e-9


class AnchorFloorError(SparseIngestError):
    """The pass cannot produce the WP1 floors, or a caller asked for a wrong one."""


# ── models ─────────────────────────────────────────────────────────────


class AnchorValue(ValueModel):
    """One anchor recording, as the floor uses it.

    ``sweep_id`` is the job's own store id — the stamp every file of that job carries,
    not a per-recording time (the pass has none) — published so a reader can see that
    no time-weight is available rather than assume one is.
    """

    label: str
    short: str
    order: int
    sweep_id: str
    gates: int
    resolution_mm: float
    supported_gates: int
    statistics: dict[str, float]


class DerivedRow(ValueModel):
    """One derived quantity of one statistic of one job: a row of ``anchor-floor.csv``."""

    job: str
    step: int
    burst_length: int
    emissions_per_profile: int
    statistic: str
    quantity: str
    begin: float
    mid: float
    end: float
    value: float
    unit: str


class BracketedRow(ValueModel):
    """A scientific row inside its bracketing anchors.

    The two residuals are against the *left* and the *right* bracketing anchor, which
    are the extremes of any linear interpolation over the bracket: no time-weight is
    assumed. They are present only when the row shares the anchors' native gate grid;
    at another pitch the comparison needs WP3's alignment and is not taken here.
    """

    label: str
    order: int
    sweep_id: str
    gates: int
    between: tuple[str, str]
    grid_matches_anchors: bool
    residual_vs_left_mean_mm_s: float | None
    residual_vs_left_max_abs_mm_s: float | None
    residual_vs_left_max_abs_depth_mm: float | None
    residual_vs_right_mean_mm_s: float | None
    residual_vs_right_max_abs_mm_s: float | None
    residual_vs_right_max_abs_depth_mm: float | None
    note: str


class DepthResolved(ArrayModel):
    """One job's depth-resolved anchor levels and drifts, on the anchors' native grid."""

    depths_mm: array_field(np.float64, rank=1)
    mean_begin: array_field(np.float64, rank=1)
    mean_mid: array_field(np.float64, rank=1)
    mean_end: array_field(np.float64, rank=1)
    mean_drift_mid_minus_begin: array_field(np.float64, rank=1)
    mean_drift_end_minus_mid: array_field(np.float64, rank=1)
    iqr_drift_mid_minus_begin: array_field(np.float64, rank=1)
    iqr_drift_end_minus_mid: array_field(np.float64, rank=1)


class JobFloor(ValueModel):
    """One scientific job's anchor floor: its anchors, its drifts, its spread."""

    job: str
    step: int
    kind: str
    burst_length: int
    emissions_per_profile: int
    structure: str
    anchors: tuple[AnchorValue, ...]
    scientific_labels: tuple[str, ...]
    job_wall_seconds: float
    recorded_seconds: float
    unaccounted_seconds: float
    drift: dict[str, dict[str, float]]
    spread: dict[str, float]
    depth_resolved: DepthResolved
    bracketed: tuple[BracketedRow, ...]


class AnchorFloor(ValueModel):
    """The WP1 result: five per-job anchor floors and the gate that holds them."""

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
    rows: tuple[DerivedRow, ...]
    jobs: tuple[JobFloor, ...]
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every WP1 gate check holds."""
        return all(self.checks.values())


# ── the measurement ────────────────────────────────────────────────────


def _condition_of(point: DecodedPoint) -> tuple[int, int]:
    """The point's decoded run-wide condition: ``(burst_length, emissions_per_profile)``."""
    return (
        int(point.config.burst_length),
        int(point.config.emissions_per_profile),
    )


def _unit_of(statistic: str) -> str:
    """``mm/s`` for every velocity statistic, dimensionless for the zero fraction."""
    return "dimensionless" if statistic == "zero_fraction" else "mm/s"


def _sweep_id(point: DecodedPoint) -> str:
    """The job's own store id, the stamp every file of that job carries.

    It is *not* a per-recording time: the pass stores no such clock, and this module
    names that fact rather than dressing the id up as one.
    """
    sweep_id = str(point.binding.recording_stamp)
    if not sweep_id:
        raise AnchorFloorError(
            f"{point.relative_path}: no store id in the file name, so the row cannot "
            "even be attributed to its job's sweep"
        )
    return sweep_id


def _job_seconds(record) -> float:
    """The job's own wall-clock window, from the pass's manifest stamps."""
    try:
        started = datetime.fromisoformat(str(record.started_at))
        finished = datetime.fromisoformat(str(record.finished_at))
    except ValueError as exc:
        raise AnchorFloorError(
            f"job {record.job!r}: the pass record's window "
            f"({record.started_at!r} -> {record.finished_at!r}) is not a pair of ISO "
            "timestamps"
        ) from exc
    seconds = (finished - started).total_seconds()
    if not seconds > 0:
        raise AnchorFloorError(
            f"job {record.job!r}: its own window is not increasing "
            f"({record.started_at!r} -> {record.finished_at!r})"
        )
    return seconds


class _AnchorSet(NamedTuple):
    """The three decoded anchors of one job, with their scalars and grids."""

    points: tuple[DecodedPoint, ...]
    scalars: dict[str, dict[str, float]]
    depths: np.ndarray
    blocks: dict[str, np.ndarray]


def _anchor_set(
    decoded: PassDecoding, job: str, points: Sequence[DecodedPoint]
) -> _AnchorSet:
    """The job's three anchors, or a refusal naming what is missing or inconsistent."""
    anchors: list[DecodedPoint] = []
    for label, _ in ANCHORS:
        matches = [point for point in points if point.binding.point.label == label]
        if len(matches) != 1:
            raise AnchorFloorError(
                f"job {job!r}: {len(matches)} recordings are labelled {label!r}, "
                "expected exactly one anchor"
            )
        anchors.append(matches[0])

    reference = anchors[0]
    for anchor in anchors[1:]:
        if not np.array_equal(np.asarray(anchor.depths), np.asarray(reference.depths)):
            raise AnchorFloorError(
                f"job {job!r}: anchor {anchor.binding.point.label!r} has a different "
                "native depth grid from "
                f"{reference.binding.point.label!r}; the anchors of one job must "
                "record the same window"
            )

    scalars: dict[str, dict[str, float]] = {}
    for anchor in anchors:
        label = str(anchor.binding.point.label)
        scalars[label] = {
            statistic: supported_mean_of(
                anchor,
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=statistic,
            )
            for statistic in STATISTICS
        }

    blocks = {
        str(anchor.binding.point.label): gate_statistics(
            anchor, window_s=decoded.window_s, support_mm=decoded.support_mm
        )
        for anchor in anchors
    }
    depths = supported_gates(reference, decoded.support_mm)
    return _AnchorSet(tuple(anchors), scalars, depths, blocks)


def _drift_and_spread(
    job: str, scalars: dict[str, dict[str, float]]
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """The signed B/M/E differences and the anchor range, per statistic."""
    begin = scalars["ctrl-begin"]
    mid = scalars["ctrl-mid"]
    end = scalars["ctrl-end"]
    drift: dict[str, dict[str, float]] = {}
    spread: dict[str, float] = {}
    for statistic in STATISTICS:
        three = (begin[statistic], mid[statistic], end[statistic])
        drift[statistic] = {
            "drift_mid_minus_begin": three[1] - three[0],
            "drift_end_minus_mid": three[2] - three[1],
            "drift_end_minus_begin": three[2] - three[0],
        }
        spread[statistic] = max(three) - min(three)
        for name, value in drift[statistic].items():
            if not math.isfinite(value):
                raise AnchorFloorError(
                    f"job {job!r}: the {name} of {statistic!r} is not finite "
                    f"({value!r}); a non-finite floor must not be published"
                )
    return drift, spread


def _bracket(
    decoded: PassDecoding,
    job: str,
    point: DecodedPoint,
    anchors: Sequence[DecodedPoint],
    blocks: dict[str, np.ndarray],
    depths: np.ndarray,
) -> BracketedRow:
    """One scientific row's bracketing pair and its residuals against each of them.

    The bracket is the acquisition order, which the pass's own record makes
    recoverable. There is no per-recording clock to place the row between the two
    anchors any more precisely (the file name's stamp is the job's ``sweep_id``), so
    the comparison is made against the left anchor and against the right one: those
    two are the extremes of every linear interpolation, and no weight is assumed.
    """
    order = int(point.binding.order)
    before = [anchor for anchor in anchors if int(anchor.binding.order) < order]
    after = [anchor for anchor in anchors if int(anchor.binding.order) > order]
    if not before or not after:
        raise AnchorFloorError(
            f"job {job!r}: the row {point.binding.point.label!r} at order {order} is "
            "not bracketed by an anchor on each side; the pass's controls are what "
            "place a measurement in time inside its job"
        )
    left = max(before, key=lambda anchor: int(anchor.binding.order))
    right = min(after, key=lambda anchor: int(anchor.binding.order))
    sweep_id = _sweep_id(point)
    if _sweep_id(left) != sweep_id or _sweep_id(right) != sweep_id:
        raise AnchorFloorError(
            f"job {job!r}: the row {point.binding.point.label!r} and its bracketing "
            f"anchors do not share one store id ({sweep_id}, {_sweep_id(left)}, "
            f"{_sweep_id(right)}): they are not one sweep"
        )

    matches = bool(
        np.array_equal(np.asarray(point.depths), np.asarray(left.depths))
        and int(point.config.n_gates or 0) == int(left.config.n_gates or 0)
    )
    if not matches:
        return BracketedRow(
            label=str(point.binding.point.label),
            order=order,
            sweep_id=sweep_id,
            gates=int(point.values.shape[1]),
            between=(
                str(left.binding.point.label),
                str(right.binding.point.label),
            ),
            grid_matches_anchors=False,
            residual_vs_left_mean_mm_s=None,
            residual_vs_left_max_abs_mm_s=None,
            residual_vs_left_max_abs_depth_mm=None,
            residual_vs_right_mean_mm_s=None,
            residual_vs_right_max_abs_mm_s=None,
            residual_vs_right_max_abs_depth_mm=None,
            note=(
                "recorded at another pitch, so its gates are not the anchors' gates: "
                "no knot-wise residual is computed here. The cross-pitch comparison is "
                "WP3's, which aligns on common knots no finer than 2.96 mm"
            ),
        )

    row_block = gate_statistics(
        point, window_s=decoded.window_s, support_mm=decoded.support_mm
    )[RESIDUAL_STATISTIC]
    left_block = blocks[str(left.binding.point.label)][RESIDUAL_STATISTIC]
    right_block = blocks[str(right.binding.point.label)][RESIDUAL_STATISTIC]
    vs_left = row_block - left_block
    vs_right = row_block - right_block
    worst_left = int(np.argmax(np.abs(vs_left)))
    worst_right = int(np.argmax(np.abs(vs_right)))
    return BracketedRow(
        label=str(point.binding.point.label),
        order=order,
        sweep_id=sweep_id,
        gates=int(point.values.shape[1]),
        between=(
            str(left.binding.point.label),
            str(right.binding.point.label),
        ),
        grid_matches_anchors=True,
        residual_vs_left_mean_mm_s=float(np.mean(vs_left)),
        residual_vs_left_max_abs_mm_s=float(abs(vs_left[worst_left])),
        residual_vs_left_max_abs_depth_mm=float(depths[worst_left]),
        residual_vs_right_mean_mm_s=float(np.mean(vs_right)),
        residual_vs_right_max_abs_mm_s=float(abs(vs_right[worst_right])),
        residual_vs_right_max_abs_depth_mm=float(depths[worst_right]),
        note=(
            "same gate grid as the anchors: the two residuals are the row's own "
            f"per-gate {RESIDUAL_STATISTIC} minus each bracketing anchor's level, and "
            "they span every linear interpolation over the bracket. Reported as "
            "observed differences, not as regime effects"
        ),
    )


def _depth_resolved(blocks: dict[str, np.ndarray], depths: np.ndarray) -> DepthResolved:
    """The depth-resolved anchor levels and drifts of one job, on its native grid."""
    begin = blocks["ctrl-begin"]
    mid = blocks["ctrl-mid"]
    end = blocks["ctrl-end"]
    return DepthResolved(
        depths_mm=depths,
        mean_begin=begin["mean"],
        mean_mid=mid["mean"],
        mean_end=end["mean"],
        mean_drift_mid_minus_begin=mid["mean"] - begin["mean"],
        mean_drift_end_minus_mid=end["mean"] - mid["mean"],
        iqr_drift_mid_minus_begin=mid["iqr"] - begin["iqr"],
        iqr_drift_end_minus_mid=end["iqr"] - mid["iqr"],
    )


def build_anchor_floor(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> AnchorFloor:
    """The five per-job anchor floors of the committed pass, or a refusal by name.

    Raises:
        AnchorFloorError: for anything the frozen WP0 ingest refuses, and for a job
            that does not carry exactly three anchors on one grid, a scientific row
            that no anchor pair brackets, or a bracket whose stamps do not increase.
    """
    decoded = decode_pass(dataset_root, plan_path=plan_path)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise AnchorFloorError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )

    jobs: list[JobFloor] = []
    rows: list[DerivedRow] = []
    for job in SCIENTIFIC_JOBS:
        points = decoded.of_job(job)
        if not points:
            raise AnchorFloorError(f"job {job!r} has no committed recording")
        anchors = _anchor_set(decoded, job, points)
        condition = _condition_of(anchors.points[0])
        burst, emissions = condition
        for anchor in anchors.points:
            if _condition_of(anchor) != condition:
                raise AnchorFloorError(
                    f"job {job!r}: the anchor {anchor.binding.point.label!r} decodes "
                    f"to condition {_condition_of(anchor)}, the job's is {condition}"
                )
            if (
                int(anchor.config.n_gates or 0),
                float(anchor.config.resolution_mm or 0.0),
            ) != (REFERENCE_WINDOW[1], REFERENCE_WINDOW[0]):
                raise AnchorFloorError(
                    f"job {job!r}: the anchor {anchor.binding.point.label!r} decodes "
                    f"to {anchor.config.n_gates} gates at "
                    f"{anchor.config.resolution_mm} mm, the reference window is "
                    f"{REFERENCE_WINDOW[1]} gates at {REFERENCE_WINDOW[0]} mm"
                )

        drift, spread = _drift_and_spread(job, anchors.scalars)
        scientific = tuple(
            point
            for point in points
            if not str(point.binding.point.label).startswith("ctrl-")
        )
        bracketed = tuple(
            _bracket(
                decoded, job, point, anchors.points, anchors.blocks, anchors.depths
            )
            for point in scientific
        )
        structure = _structure(anchors.points, scientific)
        wall_seconds = _job_seconds(points[0].binding.job)
        recorded_seconds = float(
            sum(float(point.time_s[-1] - point.time_s[0]) for point in points)
        )
        jobs.append(
            JobFloor(
                job=job,
                step=int(points[0].binding.job.step),
                kind=str(points[0].binding.job.kind),
                burst_length=burst,
                emissions_per_profile=emissions,
                structure=structure,
                anchors=tuple(
                    AnchorValue(
                        label=str(anchor.binding.point.label),
                        short=short,
                        order=int(anchor.binding.order),
                        sweep_id=_sweep_id(anchor),
                        gates=int(anchor.values.shape[1]),
                        resolution_mm=float(anchor.config.resolution_mm or 0.0),
                        supported_gates=int(anchors.depths.size),
                        statistics=anchors.scalars[str(anchor.binding.point.label)],
                    )
                    for anchor, (_, short) in zip(anchors.points, ANCHORS, strict=True)
                ),
                scientific_labels=tuple(
                    str(point.binding.point.label) for point in scientific
                ),
                job_wall_seconds=wall_seconds,
                recorded_seconds=recorded_seconds,
                unaccounted_seconds=wall_seconds - recorded_seconds,
                drift=drift,
                spread=spread,
                depth_resolved=_depth_resolved(anchors.blocks, anchors.depths),
                bracketed=bracketed,
            )
        )
        for statistic in STATISTICS:
            for name, _, _ in QUANTITIES:
                value = (
                    drift[statistic][name]
                    if name != "anchor_range"
                    else spread[statistic]
                )
                rows.append(
                    DerivedRow(
                        job=job,
                        step=int(points[0].binding.job.step),
                        burst_length=burst,
                        emissions_per_profile=emissions,
                        statistic=statistic,
                        quantity=name,
                        begin=anchors.scalars["ctrl-begin"][statistic],
                        mid=anchors.scalars["ctrl-mid"][statistic],
                        end=anchors.scalars["ctrl-end"][statistic],
                        value=value,
                        unit=_unit_of(statistic),
                    )
                )

    checks = _checks(decoded, jobs, rows)
    return AnchorFloor(
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
        rows=tuple(rows),
        jobs=tuple(jobs),
        checks=checks,
    )


def _structure(
    anchors: Sequence[DecodedPoint], scientific: Sequence[DecodedPoint]
) -> str:
    """The job's acquisition order with the anchors marked, e.g. ``B - CC1 - M - CC3 - E``."""
    names = {
        str(point.binding.point.label): short
        for point, (_, short) in zip(anchors, ANCHORS, strict=True)
    }
    ordered = sorted(
        list(anchors) + list(scientific), key=lambda point: int(point.binding.order)
    )
    return " - ".join(
        names.get(
            str(point.binding.point.label), str(point.binding.point.label).upper()
        )
        for point in ordered
    )


def _checks(
    decoded: PassDecoding, jobs: Sequence[JobFloor], rows: Sequence[DerivedRow]
) -> dict[str, bool]:
    """The WP1 gate: the structural facts that must hold before a floor is published."""
    anchors = [anchor for job in jobs for anchor in job.anchors]
    return {
        "jobs": len(jobs) == len(SCIENTIFIC_JOBS),
        "three_anchors_per_job": all(len(job.anchors) == 3 for job in jobs),
        "anchors_at_the_reference_window": all(
            anchor.gates == REFERENCE_WINDOW[1]
            and math.isclose(
                anchor.resolution_mm, REFERENCE_WINDOW[0], rel_tol=0.0, abs_tol=1e-6
            )
            for anchor in anchors
        ),
        "anchors_bracket_the_job": all(
            job.structure.startswith("B") and job.structure.endswith("E")
            for job in jobs
        ),
        "one_sweep_per_job": all(
            len({anchor.sweep_id for anchor in job.anchors}) == 1
            and all(anchor.sweep_id for anchor in job.anchors)
            for job in jobs
        ),
        "anchor_grids_agree_within_the_job": all(
            len({anchor.supported_gates for anchor in job.anchors}) == 1
            and job.depth_resolved.depths_mm.size == job.anchors[0].supported_gates
            for job in jobs
        ),
        "supported_gate_count_is_shared": len(
            {int(job.depth_resolved.depths_mm.size) for job in jobs}
        )
        == 1,
        "job_time_is_accounted": all(
            job.job_wall_seconds > 0
            and job.recorded_seconds > 0
            and job.unaccounted_seconds >= -TOLERANCE
            for job in jobs
        ),
        "drift_and_spread_are_distinct_quantities": all(
            set(job.drift[statistic])
            == {name for name, _, _ in QUANTITIES if name != "anchor_range"}
            and math.isclose(
                job.spread[statistic],
                max(
                    [
                        job.anchors[0].statistics[statistic],
                        job.anchors[1].statistics[statistic],
                        job.anchors[2].statistics[statistic],
                    ]
                )
                - min(
                    [
                        job.anchors[0].statistics[statistic],
                        job.anchors[1].statistics[statistic],
                        job.anchors[2].statistics[statistic],
                    ]
                ),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for job in jobs
            for statistic in STATISTICS
        ),
        "derived_rows_are_complete": len(rows)
        == len(jobs) * len(STATISTICS) * len(QUANTITIES),
        "brackets_are_complete": all(
            len(job.bracketed) == len(job.scientific_labels) for job in jobs
        ),
        "cross_pitch_rows_carry_no_residual": all(
            row.residual_vs_left_mean_mm_s is None
            and row.residual_vs_right_mean_mm_s is None
            for job in jobs
            for row in job.bracketed
            if not row.grid_matches_anchors
        ),
        "bracketed_rows_carry_both_extremes": all(
            row.residual_vs_left_mean_mm_s is not None
            and row.residual_vs_right_mean_mm_s is not None
            for job in jobs
            for row in job.bracketed
            if row.grid_matches_anchors
        ),
        "window_and_support_are_the_wp0_ones": (
            math.isclose(
                decoded.window_s, DESIGNED_WINDOW_S, rel_tol=0.0, abs_tol=1e-12
            )
            and decoded.support_mm[1] > decoded.support_mm[0]
        ),
    }


# ── artefacts ──────────────────────────────────────────────────────────


CSV_COLUMNS: tuple[str, ...] = (
    "job",
    "step",
    "burst_length",
    "emissions_per_profile",
    "statistic",
    "quantity",
    "begin",
    "mid",
    "end",
    "value",
    "unit",
)


def csv_text(model: AnchorFloor) -> str:
    """Render ``anchor-floor.csv`` (LF endings, one trailing newline)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(CSV_COLUMNS), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    for row in model.rows:
        writer.writerow(
            {
                "job": row.job,
                "step": format_cell(row.step),
                "burst_length": format_cell(row.burst_length),
                "emissions_per_profile": format_cell(row.emissions_per_profile),
                "statistic": row.statistic,
                "quantity": row.quantity,
                "begin": format_cell(row.begin),
                "mid": format_cell(row.mid),
                "end": format_cell(row.end),
                "value": format_cell(row.value),
                "unit": row.unit,
            }
        )
    return buffer.getvalue()


def _row_document(row: BracketedRow) -> dict[str, object]:
    """One bracketed row's JSON view, with the absent residual spelled as null."""
    return {
        "label": row.label,
        "order": row.order,
        "sweep_id": row.sweep_id,
        "gates": row.gates,
        "between": list(row.between),
        "grid_matches_anchors": row.grid_matches_anchors,
        "residual_vs_left_mean_mm_s": row.residual_vs_left_mean_mm_s,
        "residual_vs_left_max_abs_mm_s": row.residual_vs_left_max_abs_mm_s,
        "residual_vs_left_max_abs_depth_mm": row.residual_vs_left_max_abs_depth_mm,
        "residual_vs_right_mean_mm_s": row.residual_vs_right_mean_mm_s,
        "residual_vs_right_max_abs_mm_s": row.residual_vs_right_max_abs_mm_s,
        "residual_vs_right_max_abs_depth_mm": row.residual_vs_right_max_abs_depth_mm,
        "note": row.note,
    }


def def_document(model: AnchorFloor) -> dict[str, object]:
    """The WP1 document: the floors, their definitions and the gate, keys in order."""
    return {
        "dataset_root": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "analysis_commit": model.analysis_commit,
        "table": CSV_NAME,
        "table_rows": len(model.rows),
        "views": {
            "primary_window": {
                "window_s": model.window_s,
                "revolutions": model.window_revolutions,
                "rule": (
                    "the pass's designed exposure, the declared 12 s = 100 nominal "
                    "500-RPM revolutions, cut in each recording by its own stored "
                    "timestamps (WP0); the retained surplus is not part of it"
                ),
            },
            "common_support": {
                "support_min_mm": model.support_min_mm,
                "support_max_mm": model.support_max_mm,
                "rule": (
                    "the intersection of every recording's decoded depth range; each "
                    "per-gate statistic is computed on the recording's own native gate "
                    "grid inside it, and no interpolation or resampling is applied"
                ),
            },
        },
        "statistics": {
            statistic: WP0_DEFINITIONS.get(f"supported_{statistic}", statistic)
            if statistic != "zero_fraction"
            else WP0_DEFINITIONS["zero_fraction"]
            for statistic in STATISTICS
        },
        "quantities": {
            name: {"kind": kind, "definition": definition}
            for name, kind, definition in QUANTITIES
        },
        "anchors": {
            "labels": [label for label, _ in ANCHORS],
            "short": {label: short for label, short in ANCHORS},
            "condition": (
                "each anchor records the reference spatial window at its own job's "
                "anchor condition: a burst-4 job's anchors are burst 4, an "
                "emissions-128 job's are emissions 128. They are NOT realizations of "
                "the reference condition - that one is observed across runs by "
                "CR1-CR4 alone (WP2) - and no anchor floor is pooled across jobs"
            ),
            "sweep_id": (
                "the YYYYMMDDTHHMMSS segment of a recording's file name is its job's "
                "sweep_id - the same string for every point of that job, as the job's "
                "own log entries spell it - and it is not a per-recording timestamp. "
                "The pass stores no such clock, so no row can be placed at an "
                "interpolated instant between its anchors; the brackets are reported "
                "in acquisition order, and the residuals are taken against each "
                "bracketing anchor, which spans every linear interpolation"
            ),
        },
        "scope": {
            "residual": (
                "computed only for a scientific row that shares the anchors' native "
                "gate grid, and taken against each of the two bracketing anchors "
                "separately: the left one and the right one are the extremes of every "
                "linear interpolation over the bracket, so the pair spans the bracket "
                "without assuming a time-weight the pass cannot supply"
            ),
            "cross_pitch_rows": (
                "a scientific row at another pitch carries no residual: the "
                "cross-pitch comparison belongs to WP3, which aligns on common knots "
                "no finer than 2.96 mm"
            ),
            "not_a_bound": (
                "drift and spread are observed differences over three recordings. "
                "They are not a confidence interval and they neither prove an axis "
                "effect nor bound drift"
            ),
        },
        "jobs": [
            {
                "job": job.job,
                "step": job.step,
                "kind": job.kind,
                "condition": {
                    "burst_length": job.burst_length,
                    "emissions_per_profile": job.emissions_per_profile,
                },
                "structure": job.structure,
                "scientific_labels": list(job.scientific_labels),
                "job_time": {
                    "job_wall_seconds": job.job_wall_seconds,
                    "recorded_seconds": job.recorded_seconds,
                    "unaccounted_seconds": job.unaccounted_seconds,
                    "note": (
                        "the job's own manifest window beside the summed duration of "
                        "every one of its recordings: the difference is the pass's own "
                        "handling and store time between recordings, an observed "
                        "quantity, and it is why a per-recording instant is not "
                        "reconstructible from the files"
                    ),
                },
                "anchors": [
                    {
                        "label": anchor.label,
                        "short": anchor.short,
                        "order": anchor.order,
                        "sweep_id": anchor.sweep_id,
                        "gates": anchor.gates,
                        "resolution_mm": anchor.resolution_mm,
                        "supported_gates": anchor.supported_gates,
                        "statistics": dict(anchor.statistics),
                    }
                    for anchor in job.anchors
                ],
                "drift": {key: dict(value) for key, value in job.drift.items()},
                "spread": dict(job.spread),
                "depth_resolved": {
                    "depths_mm": [
                        float(value) for value in job.depth_resolved.depths_mm
                    ],
                    "mean_begin": [
                        float(value) for value in job.depth_resolved.mean_begin
                    ],
                    "mean_mid": [float(value) for value in job.depth_resolved.mean_mid],
                    "mean_end": [float(value) for value in job.depth_resolved.mean_end],
                    "mean_drift_mid_minus_begin": [
                        float(value)
                        for value in job.depth_resolved.mean_drift_mid_minus_begin
                    ],
                    "mean_drift_end_minus_mid": [
                        float(value)
                        for value in job.depth_resolved.mean_drift_end_minus_mid
                    ],
                    "iqr_drift_mid_minus_begin": [
                        float(value)
                        for value in job.depth_resolved.iqr_drift_mid_minus_begin
                    ],
                    "iqr_drift_end_minus_mid": [
                        float(value)
                        for value in job.depth_resolved.iqr_drift_end_minus_mid
                    ],
                },
                "bracketed": [_row_document(row) for row in job.bracketed],
            }
            for job in model.jobs
        ],
        "checks": dict(sorted(model.checks.items())),
        "ok": model.ok,
    }


def figure_name(job: str) -> str:
    """The figure a job's floor is drawn in."""
    return f"anchor-{job}.png"


def render_figure(model: AnchorFloor, job: str, path: Path) -> Path:
    """Draw one job's anchor levels and their drifts against depth.

    Two panels: the three anchor ``mean`` profiles on the native supported grid, and
    the two signed drifts with the spread they are not. The caption carries the
    scalars, the job's own condition, its structure and the caveats, so a reviewer
    reading the image alone sees what was measured and what it is not.
    """
    floor = next((item for item in model.jobs if item.job == job), None)
    if floor is None:
        raise AnchorFloorError(
            f"no job {job!r} in this floor; jobs are "
            f"{[item.job for item in model.jobs]}"
        )
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    depths = np.asarray(floor.depth_resolved.depths_mm, dtype=float)
    figure, (levels, drifts) = plt.subplots(
        2, 1, figsize=(7.2, 8.0), sharex=True, dpi=FIGURE_DPI
    )
    colors = {"mean_begin": "#1f77b4", "mean_mid": "#ff7f0e", "mean_end": "#2ca02c"}
    labels = {
        "mean_begin": "B  ctrl-begin",
        "mean_mid": "M  ctrl-mid",
        "mean_end": "E  ctrl-end",
    }
    for key, color in colors.items():
        levels.plot(
            getattr(floor.depth_resolved, key),
            depths,
            color=color,
            linewidth=1.5,
            label=labels[key],
        )
    levels.set_ylabel("depth [mm]")
    levels.invert_yaxis()
    levels.set_xlabel("window mean velocity [mm/s]")
    levels.set_title(
        f"{job} - anchor levels at the reference window "
        f"({REFERENCE_WINDOW[1]} gates x {REFERENCE_WINDOW[0]} mm), "
        f"job condition burst {floor.burst_length} / emissions "
        f"{floor.emissions_per_profile}\n{floor.structure}",
        fontsize=10,
    )
    levels.grid(alpha=0.2)
    levels.legend(loc="lower right", fontsize=8, framealpha=0.9)

    spread_band = np.maximum.reduce(
        [
            np.asarray(floor.depth_resolved.mean_begin, dtype=float),
            np.asarray(floor.depth_resolved.mean_mid, dtype=float),
            np.asarray(floor.depth_resolved.mean_end, dtype=float),
        ]
    ) - np.minimum.reduce(
        [
            np.asarray(floor.depth_resolved.mean_begin, dtype=float),
            np.asarray(floor.depth_resolved.mean_mid, dtype=float),
            np.asarray(floor.depth_resolved.mean_end, dtype=float),
        ]
    )
    drifts.plot(
        floor.depth_resolved.mean_drift_mid_minus_begin,
        depths,
        color="#ff7f0e",
        linewidth=1.5,
        label="drift M - B",
    )
    drifts.plot(
        floor.depth_resolved.mean_drift_end_minus_mid,
        depths,
        color="#2ca02c",
        linewidth=1.5,
        label="drift E - M",
    )
    drifts.plot(
        spread_band,
        depths,
        color="#7f7f7f",
        linewidth=1.2,
        linestyle=":",
        label="anchor spread (max - min over B,M,E)",
    )
    drifts.axvline(0.0, color="#444444", linewidth=0.8)
    drifts.set_ylabel("depth [mm]")
    drifts.set_xlabel("difference [mm/s]")
    drifts.set_title(
        "drift is signed and ordered; spread is neither "
        f"(job means: drift M-B {floor.drift['mean']['drift_mid_minus_begin']:+.3f}, "
        f"E-M {floor.drift['mean']['drift_end_minus_mid']:+.3f}, "
        f"spread {floor.spread['mean']:.3f} mm/s)",
        fontsize=9,
    )
    drifts.grid(alpha=0.2)
    drifts.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

    residual_lines = [
        f"{row.label}: bracketed by {row.between[0]}..{row.between[1]} in order; "
        + (
            f"residual vs {row.between[0]} {row.residual_vs_left_mean_mm_s:+.3f} "
            f"(max |.| {row.residual_vs_left_max_abs_mm_s:.3f} at "
            f"{row.residual_vs_left_max_abs_depth_mm:.2f} mm), vs "
            f"{row.between[1]} {row.residual_vs_right_mean_mm_s:+.3f} "
            f"(max |.| {row.residual_vs_right_max_abs_mm_s:.3f} at "
            f"{row.residual_vs_right_max_abs_depth_mm:.2f} mm)"
            if row.residual_vs_left_mean_mm_s is not None
            else "cross-pitch: no residual (WP3 aligns)"
        )
        for row in floor.bracketed
    ]
    caption = _wrap(
        f"{job}: {REFERENCE_WINDOW[1]} gates x {REFERENCE_WINDOW[0]} mm reference window, "
        f"primary window {model.window_s:g} s ({model.window_revolutions} nominal "
        f"revolutions), common support {model.support_min_mm:.3f}-"
        f"{model.support_max_mm:.3f} mm, {int(depths.size)} supported gates. "
        "Anchors are block-local: they record this job's condition, not the reference "
        "condition (CR1-CR4 only, WP2). The file-name stamp is the job's sweep id, not "
        "a per-recording time, so a row is bracketed by order and its residual is taken "
        "against each bracketing anchor. Drift and spread are observed differences over "
        "three recordings - not a confidence interval, no proof of an axis effect. "
        + " | ".join(residual_lines)
    )
    figure.text(
        0.01,
        0.012,
        caption,
        fontsize=5.6,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.90, bottom=0.20, hspace=0.18)
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


def write_anchor_floor(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> AnchorFloor:
    """Build the floors and write the table, the document and one figure per job.

    Every file is UTF-8 with LF endings and one trailing newline, so two runs on the
    same inputs and revision produce identical bytes. Nothing is written when the
    build refuses.
    """
    model = build_anchor_floor(
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
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline=""
    )
    for job in model.jobs:
        render_figure(
            model, job.job, directory / FIGURES_DIRNAME / figure_name(job.job)
        )
    return model


def anchor_floor_main(argv: list[str] | None = None) -> None:
    """``sparse-anchor-floor`` — write WP1's per-job anchor floors.

    Reads the committed recordings through the frozen WP0 ingest's own binding and
    decoding, computes each scientific job's drift (B->M->E, signed) and spread
    (max-min over the three anchors) for the five shared statistics, and writes
    ``anchor-floor.csv``, ``anchor-floor.json`` and one figure per job into the report
    directory. It exits 0 when every WP1 gate check holds and 1 otherwise, naming the
    failure; a pass the ingest refuses exits 1 with the ingest's own reason and writes
    nothing.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-anchor-floor",
        description=(
            "WP1: the sparse pass's per-job anchor floors (drift and spread at the "
            "reference window, each job's own condition)"
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
        help="the frozen plan the pass is a realization of",
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR.as_posix(),
        help="directory to write anchor-floor.csv and anchor-floor.json into",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    try:
        model = write_anchor_floor(
            Path(args.dataset_root),
            Path(args.report_dir),
            plan_path=Path(args.plan),
            analysis_commit=args.analysis_commit,
        )
    except SparseIngestError as exc:
        print(f"udv-sparse-anchor-floor: {exc}")
        raise SystemExit(1) from exc
    for job in model.jobs:
        print(
            f"{job.job:14s} {job.structure:26s} "
            f"drift M-B {job.drift['mean']['drift_mid_minus_begin']:+8.3f} "
            f"E-M {job.drift['mean']['drift_end_minus_mid']:+8.3f} "
            f"spread {job.spread['mean']:7.3f} mm/s"
        )
    print(f"table   : {Path(args.report_dir) / CSV_NAME}")
    print(f"document: {Path(args.report_dir) / DOC_NAME}")
    failed = [name for name, ok in sorted(model.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sparse-anchor-floor: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
