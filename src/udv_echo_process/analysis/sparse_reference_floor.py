"""WP2 of the sparse-pass analysis: the CR1-CR4 between-run reference floor.

**What this measures.** Four recordings — ``cr1``..``cr4``, one per *reference* job —
repeat **one** decoded condition across four distinct runs spread over the pass's
16 min 43 s: burst 10, emissions 20, 50 gates at 1.85 mm. They are the only condition
this pass observes in more than one run, so they are what says how much of any
difference between two jobs can plausibly be *time*.

**Four measurements, kept four.** The deliverable is the four runs, individually
visible and ordered in real campaign time by their own jobs' manifest windows, with
their depth-resolved window-mean profiles and the six pairwise depth-resolved
differences over the common support. **Nothing is averaged into a synthetic
reference**: a mean of the four would destroy exactly the information this slice
exists to estimate, so the module computes no such profile and a test fails if the
artefacts gain one.

**The floor is one scalar with a stated endpoint.** The compact reduction is

    the largest absolute per-depth window-mean difference over the common support,
    taken over all six ordered pairs of the four runs

published with the pair and the depth that realise it, and with the per-pair table
beside it so the reduction is checkable rather than a number to be trusted. It is an
observed difference between four recordings and four runs; it is not a confidence
interval, it does not create replication, and no count of profiles or gates changes
that.

**What it does not do.** No parameter effect, no interaction (WP3), no emissions
statement (WP4). The four runs are not compared against the anchors of WP1, whose
floors are per-job and belong to different conditions. Nothing here changes the frozen
WP0 artefacts or WP1's.
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
    REFERENCE_JOBS,
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

#: The statistic the floor is reduced from, and the statistics whose depth-resolved
#: differences are published.
FLOOR_STATISTIC = "mean"

#: The per-run statistics the table carries, mirroring WP1's set.
STATISTICS: tuple[str, ...] = ("mean", "median", "iqr", "rms", "zero_fraction")

#: The one condition the four reference runs share, as the pass declares it.
REFERENCE_CONDITION: dict[str, float] = {
    "burst_length": 10.0,
    "emissions_per_profile": 20.0,
    "resolution_mm": 1.85,
    "n_gates": 50.0,
}

CSV_NAME = "reference-floor.csv"
DOC_NAME = "reference-floor.json"
MD_NAME = "reference-floor.md"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "reference-floor.png"
FIGURE_DPI = 150
TOLERANCE = 1e-9


class ReferenceFloorError(SparseIngestError):
    """The pass cannot produce the WP2 floor, or a caller asked for a wrong one."""


# ── models ─────────────────────────────────────────────────────────────


class RunValue(ValueModel):
    """One reference run, as the floor uses it."""

    label: str
    order: int
    job: str
    step: int
    job_started_at: str
    job_finished_at: str
    gates: int
    resolution_mm: float
    supported_gates: int
    statistics: dict[str, float]


class PairDifference(ValueModel):
    """One ordered pair of reference runs, on the common support.

    ``mean_difference_mm_s`` is the unweighted mean over the supported gates of the
    per-depth difference — a descriptive summary of the pair — while
    ``max_abs_difference_mm_s`` and its depth are what the floor is reduced from.
    """

    left: str
    right: str
    job_start_separation_min: float
    mean_difference_mm_s: float
    rms_difference_mm_s: float
    max_abs_difference_mm_s: float
    max_abs_depth_mm: float


class DepthResolved(ArrayModel):
    """The four runs' window-mean profiles and their six pairwise differences."""

    depths_mm: array_field(np.float64, rank=1)
    cr1: array_field(np.float64, rank=1)
    cr2: array_field(np.float64, rank=1)
    cr3: array_field(np.float64, rank=1)
    cr4: array_field(np.float64, rank=1)
    cr1_minus_cr2: array_field(np.float64, rank=1)
    cr1_minus_cr3: array_field(np.float64, rank=1)
    cr1_minus_cr4: array_field(np.float64, rank=1)
    cr2_minus_cr3: array_field(np.float64, rank=1)
    cr2_minus_cr4: array_field(np.float64, rank=1)
    cr3_minus_cr4: array_field(np.float64, rank=1)


class ReferenceFloor(ValueModel):
    """The WP2 result: the four reference runs, their pairs, and the one reduction."""

    dataset_root: str
    plan: str
    plan_path: str
    plan_fingerprint: str
    analysis_commit: str
    window_s: float
    window_revolutions: int
    support_min_mm: float
    support_max_mm: float
    runs: tuple[RunValue, ...]
    pairs: tuple[PairDifference, ...]
    floor_statistic: str
    floor_endpoint: str
    floor_mm_s: float
    floor_pair: tuple[str, str]
    floor_depth_mm: float
    averaged_endpoint: str
    averaged_floor_mm_s: float
    averaged_floor_pair: tuple[str, str]
    depth_resolved: DepthResolved
    checks: dict[str, bool]

    @property
    def ok(self) -> bool:
        """True only when every WP2 gate check holds."""
        return all(self.checks.values())


# ── the measurement ────────────────────────────────────────────────────


def _condition_of(point: DecodedPoint) -> dict[str, float]:
    """The decoded condition a reference run must share with the other three."""
    return {
        "burst_length": float(point.config.burst_length or 0),
        "emissions_per_profile": float(point.config.emissions_per_profile or 0),
        "resolution_mm": float(point.config.resolution_mm or 0.0),
        "n_gates": float(point.config.n_gates or 0),
    }


def _job_start_separation_min(left: str, right: str, job: str) -> float:
    """The two runs' **job-start** separation in minutes, from their own manifest windows.

    This is the separation of the two *jobs*' start timestamps, not a recording-to-recording
    interval: the pass carries no per-recording clock (a file name's ``YYYYMMDDTHHMMSS``
    segment is the job's ``sweep_id``), so the recordings cannot be placed at instants. It
    orders the four runs and it is what the floor's "not a rate" statement rests on; it is
    not the elapsed recording time between two measurements.
    """
    try:
        first = datetime.fromisoformat(left)
        second = datetime.fromisoformat(right)
    except ValueError as exc:
        raise ReferenceFloorError(
            f"job {job!r}: the pass record's window ({left!r} -> {right!r}) is not a "
            "pair of ISO timestamps"
        ) from exc
    return abs((second - first).total_seconds()) / 60.0


class _Runs(NamedTuple):
    """The four reference runs, decoded and reduced to their native supported grid."""

    points: tuple[DecodedPoint, ...]
    stats: dict[str, dict[str, float]]
    blocks: dict[str, np.ndarray]
    depths: np.ndarray


def _reference_runs(decoded: PassDecoding) -> _Runs:
    """The four reference runs, or a refusal naming what disagrees."""
    runs = tuple(decoded.of_kind("common-reference"))
    if len(runs) != len(REFERENCE_JOBS):
        raise ReferenceFloorError(
            f"the pass holds {len(runs)} reference recordings, expected "
            f"{len(REFERENCE_JOBS)}: WP2 measures four runs separately, not fewer"
        )
    first = runs[0]
    for run in runs:
        observed = _condition_of(run)
        if observed != _condition_of(first):
            raise ReferenceFloorError(
                f"{run.relative_path}: decodes to {observed}, while "
                f"{first.relative_path} decodes to {_condition_of(first)}; the "
                "reference runs must share one condition"
            )
        if observed != REFERENCE_CONDITION:
            raise ReferenceFloorError(
                f"{run.relative_path}: decodes to {observed}, not the pass's declared "
                f"reference condition {REFERENCE_CONDITION}"
            )
        if not np.array_equal(np.asarray(run.depths), np.asarray(first.depths)):
            raise ReferenceFloorError(
                f"{run.relative_path}: its native depth grid is not "
                f"{first.relative_path}'s, so a per-depth difference is not defined"
            )

    stats = {
        str(run.binding.point.label): {
            statistic: supported_mean_of(
                run,
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=statistic,
            )
            for statistic in STATISTICS
        }
        for run in runs
    }
    blocks = {
        str(run.binding.point.label): gate_statistics(
            run, window_s=decoded.window_s, support_mm=decoded.support_mm
        )[FLOOR_STATISTIC]
        for run in runs
    }
    depths = supported_gates(first, decoded.support_mm)
    return _Runs(runs, stats, blocks, depths)


def _pairs(runs: _Runs) -> tuple[PairDifference, ...]:
    """The six ordered pairs, each reduced on the common support."""
    windows = {
        str(run.binding.point.label): (
            run.binding.job.started_at,
            run.binding.job.finished_at,
        )
        for run in runs.points
    }
    differences: list[PairDifference] = []
    labels = [str(run.binding.point.label) for run in runs.points]
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            difference = runs.blocks[left] - runs.blocks[right]
            worst = int(np.argmax(np.abs(difference)))
            differences.append(
                PairDifference(
                    left=left,
                    right=right,
                    job_start_separation_min=_job_start_separation_min(
                        windows[left][0], windows[right][0], f"{left}/{right}"
                    ),
                    mean_difference_mm_s=float(np.mean(difference)),
                    rms_difference_mm_s=float(np.sqrt(np.mean(np.square(difference)))),
                    max_abs_difference_mm_s=float(abs(difference[worst])),
                    max_abs_depth_mm=float(runs.depths[worst]),
                )
            )
    return tuple(differences)


def _depth_resolved(runs: _Runs) -> DepthResolved:
    """The four profiles and their six differences, on the shared native grid."""
    block = runs.blocks
    return DepthResolved(
        depths_mm=runs.depths,
        cr1=block["cr1"],
        cr2=block["cr2"],
        cr3=block["cr3"],
        cr4=block["cr4"],
        cr1_minus_cr2=block["cr1"] - block["cr2"],
        cr1_minus_cr3=block["cr1"] - block["cr3"],
        cr1_minus_cr4=block["cr1"] - block["cr4"],
        cr2_minus_cr3=block["cr2"] - block["cr3"],
        cr2_minus_cr4=block["cr2"] - block["cr4"],
        cr3_minus_cr4=block["cr3"] - block["cr4"],
    )


FLOOR_ENDPOINT = (
    "the largest absolute per-depth window-mean difference over the common support, "
    "taken over all six ordered pairs of the four reference runs: the endpoint a "
    "depth-resolved comparison is screened against"
)

AVERAGED_ENDPOINT = (
    "the largest absolute difference between the four runs' depth-averaged window "
    "means, taken over all six ordered pairs: the same reduction WP1's anchor floors "
    "use, so the two floors are compared like for like"
)


def build_reference_floor(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> ReferenceFloor:
    """The four-run reference floor of the committed pass, or a refusal by name.

    Raises:
        ReferenceFloorError: for anything the frozen WP0 ingest refuses, and for a
            reference set that is not four runs sharing one condition on one native
            grid.
    """
    decoded = decode_pass(dataset_root, plan_path=plan_path)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise ReferenceFloorError(
            "no generator revision: pass --analysis-commit or run from a checkout"
        )
    runs = _reference_runs(decoded)
    pairs = _pairs(runs)
    depth_resolved = _depth_resolved(runs)

    ordered = sorted(runs.points, key=lambda run: int(run.binding.order))
    values: list[RunValue] = []
    for run in ordered:
        label = str(run.binding.point.label)
        values.append(
            RunValue(
                label=label,
                order=int(run.binding.order),
                job=str(run.binding.job.job),
                step=int(run.binding.job.step),
                job_started_at=str(run.binding.job.started_at),
                job_finished_at=str(run.binding.job.finished_at),
                gates=int(run.values.shape[1]),
                resolution_mm=float(run.config.resolution_mm or 0.0),
                supported_gates=int(runs.depths.size),
                statistics=runs.stats[label],
            )
        )

    worst = max(pairs, key=lambda pair: pair.max_abs_difference_mm_s)
    worst_averaged = max(pairs, key=lambda pair: abs(pair.mean_difference_mm_s))
    checks = _checks(decoded, values, pairs, worst, worst_averaged)
    return ReferenceFloor(
        dataset_root=decoded.dataset_root.as_posix(),
        plan=str(decoded.plan.plan),
        plan_path=Path(plan_path).as_posix(),
        plan_fingerprint=decoded.plan_fingerprint,
        analysis_commit=commit,
        window_s=decoded.window_s,
        window_revolutions=decoded.window_revolutions,
        support_min_mm=decoded.support_mm[0],
        support_max_mm=decoded.support_mm[1],
        runs=tuple(values),
        pairs=pairs,
        floor_statistic=FLOOR_STATISTIC,
        floor_endpoint=FLOOR_ENDPOINT,
        floor_mm_s=worst.max_abs_difference_mm_s,
        floor_pair=(worst.left, worst.right),
        floor_depth_mm=worst.max_abs_depth_mm,
        averaged_endpoint=AVERAGED_ENDPOINT,
        averaged_floor_mm_s=abs(worst_averaged.mean_difference_mm_s),
        averaged_floor_pair=(worst_averaged.left, worst_averaged.right),
        depth_resolved=depth_resolved,
        checks=checks,
    )


def _checks(
    decoded: PassDecoding,
    runs: Sequence[RunValue],
    pairs: Sequence[PairDifference],
    worst: PairDifference,
    worst_averaged: PairDifference,
) -> dict[str, bool]:
    """The WP2 gate: the structural facts that must hold before the floor is published."""
    return {
        "four_runs": len(runs) == len(REFERENCE_JOBS)
        and sorted(run.job for run in runs) == sorted(REFERENCE_JOBS)
        and len({run.label for run in runs}) == 4,
        "one_condition": len({(run.gates, round(run.resolution_mm, 6)) for run in runs})
        == 1,
        "campaign_order_is_increasing": [run.job_started_at for run in runs]
        == sorted(run.job_started_at for run in runs),
        "supported_gate_count_is_shared": len({run.supported_gates for run in runs})
        == 1,
        "six_ordered_pairs": len(pairs) == 6
        and len({(pair.left, pair.right) for pair in pairs}) == 6,
        "pairs_are_separated_by_their_job_starts": all(
            pair.job_start_separation_min > 0 for pair in pairs
        ),
        "floor_is_the_worst_pair": worst.max_abs_difference_mm_s
        == max(pair.max_abs_difference_mm_s for pair in pairs),
        "the_two_endpoints_are_distinct_quantities": (
            worst_averaged.mean_difference_mm_s
            == max((pair.mean_difference_mm_s for pair in pairs), key=abs)
            and worst_averaged.max_abs_difference_mm_s <= worst.max_abs_difference_mm_s
            and len(pairs) == 6
        ),
        "no_synthetic_reference": not hasattr(decoded, "mean_profile"),
        "window_and_support_are_the_wp0_ones": (
            math.isclose(
                decoded.window_s, DESIGNED_WINDOW_S, rel_tol=0.0, abs_tol=1e-12
            )
            and decoded.support_mm[1] > decoded.support_mm[0]
        ),
    }


# ── artefacts ──────────────────────────────────────────────────────────


CSV_COLUMNS: tuple[str, ...] = (
    "label",
    "order",
    "job",
    "step",
    "job_started_at",
    "gates",
    "resolution_mm",
    "supported_gates",
    "statistic",
    "value",
    "unit",
)

PAIR_COLUMNS: tuple[str, ...] = (
    "left",
    "right",
    "job_start_separation_min",
    "mean_difference_mm_s",
    "rms_difference_mm_s",
    "max_abs_difference_mm_s",
    "max_abs_depth_mm",
)

#: What each pair column means, published in the document's ``pair_columns``. The first
#: entry is the review's correction: the separation is of the two *job starts*, because a
#: recording-to-recording interval is not available from this pass at all.
PAIR_COLUMNS_DEFINITIONS: dict[str, str] = {
    "job_start_separation_min": (
        "the difference between the two runs' jobs' *manifest start timestamps*, in "
        "minutes - the separation of the two job starts, and NOT a recording-to-recording "
        "interval or an elapsed time between two measurements. The pass carries no "
        "per-recording clock (a file name's YYYYMMDDTHHMMSS segment is the job's "
        "sweep_id, identical for every point of that job), so the recordings cannot be "
        "placed at instants. This quantity orders the four runs and it is what the floor's "
        "'not a rate' statement rests on."
    ),
    "mean_difference_mm_s": (
        "the unweighted mean over the supported gates of the per-depth window-mean "
        "difference (left minus right), in mm/s: a descriptive summary of the pair"
    ),
    "rms_difference_mm_s": (
        "the root mean square over the supported gates of the same difference, in mm/s"
    ),
    "max_abs_difference_mm_s": (
        "the largest absolute per-depth window-mean difference over the supported gates, "
        "in mm/s - the reduction the depth-resolved floor endpoint is taken from"
    ),
    "max_abs_depth_mm": (
        "the depth, in mm, at which that largest absolute difference occurs"
    ),
}


def _unit_of(statistic: str) -> str:
    """``mm/s`` for every velocity statistic, dimensionless for the zero fraction."""
    return "dimensionless" if statistic == "zero_fraction" else "mm/s"


def csv_text(model: ReferenceFloor) -> str:
    """Render ``reference-floor.csv``: the runs, then the pairs (LF, trailing newline).

    One table, two blocks, told apart by the first column: a run row carries its own
    statistics, a pair row carries the two labels in the same two first cells.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(CSV_COLUMNS))
    for run in model.runs:
        for statistic in STATISTICS:
            writer.writerow(
                [
                    "run",
                    run.label,
                    run.job,
                    format_cell(run.step),
                    run.job_started_at,
                    format_cell(run.gates),
                    format_cell(run.resolution_mm),
                    format_cell(run.supported_gates),
                    statistic,
                    format_cell(run.statistics[statistic]),
                    _unit_of(statistic),
                ]
            )
    writer.writerow([])
    writer.writerow(list(PAIR_COLUMNS))
    for pair in model.pairs:
        writer.writerow(
            [
                pair.left,
                pair.right,
                format_cell(pair.job_start_separation_min),
                format_cell(pair.mean_difference_mm_s),
                format_cell(pair.rms_difference_mm_s),
                format_cell(pair.max_abs_difference_mm_s),
                format_cell(pair.max_abs_depth_mm),
            ]
        )
    return buffer.getvalue()


def def_document(model: ReferenceFloor) -> dict[str, object]:
    """The WP2 document: the four runs, their pairs, the floor and the gate."""
    return {
        "dataset_root": model.dataset_root,
        "plan": model.plan,
        "plan_path": model.plan_path,
        "plan_fingerprint": model.plan_fingerprint,
        "analysis_commit": model.analysis_commit,
        "table": CSV_NAME,
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
                    "per-depth statistic is computed on the recording's own native gate "
                    "grid inside it, and no interpolation or resampling is applied"
                ),
            },
        },
        "reference_condition": {
            "declared": REFERENCE_CONDITION,
            "note": (
                "the one condition this pass observes in more than one run: burst 10, "
                "emissions 20, 50 gates at 1.85 mm. The four recordings are four repeated "
                "observations of that condition across four distinct runs - four runs, not "
                "four replicates of one run - and they are the only reference realizations "
                "in the pass: the WP1 anchors are block-local and belong to other "
                "conditions. What they do not provide is independent replication of the "
                "pitch, burst or emissions treatment levels, each of which stays a single "
                "realization per level."
            ),
        },
        "floor": {
            "statistic": model.floor_statistic,
            "depth_resolved": {
                "endpoint": model.floor_endpoint,
                "value_mm_s": model.floor_mm_s,
                "pair": list(model.floor_pair),
                "depth_mm": model.floor_depth_mm,
            },
            "depth_averaged": {
                "endpoint": model.averaged_endpoint,
                "value_mm_s": model.averaged_floor_mm_s,
                "pair": list(model.averaged_floor_pair),
            },
            "pairs_reduced": len(model.pairs),
            "note": (
                "two endpoints, because a depth-resolved comparison and a "
                "depth-averaged one are screened against different numbers and only "
                "the second is like for like with WP1's anchor floors. Both are "
                "observed differences between four recordings and four runs, not a "
                "confidence interval and not a separability criterion; neither proves "
                "an axis effect nor bound drift"
            ),
        },
        "no_synthetic_reference": (
            "the four runs are published individually and their six pairwise "
            "differences are published individually; nothing in this slice averages "
            "the four into one reference profile, because that average is exactly the "
            "information this floor exists to estimate"
        ),
        "runs": [
            {
                "label": run.label,
                "order": run.order,
                "job": run.job,
                "step": run.step,
                "job_started_at": run.job_started_at,
                "job_finished_at": run.job_finished_at,
                "gates": run.gates,
                "resolution_mm": run.resolution_mm,
                "supported_gates": run.supported_gates,
                "statistics": dict(run.statistics),
            }
            for run in model.runs
        ],
        "pairs": [
            {
                "left": pair.left,
                "right": pair.right,
                "job_start_separation_min": pair.job_start_separation_min,
                "mean_difference_mm_s": pair.mean_difference_mm_s,
                "rms_difference_mm_s": pair.rms_difference_mm_s,
                "max_abs_difference_mm_s": pair.max_abs_difference_mm_s,
                "max_abs_depth_mm": pair.max_abs_depth_mm,
            }
            for pair in model.pairs
        ],
        "depth_resolved": {
            key: [float(value) for value in getattr(model.depth_resolved, key)]
            for key in (
                "depths_mm",
                "cr1",
                "cr2",
                "cr3",
                "cr4",
                "cr1_minus_cr2",
                "cr1_minus_cr3",
                "cr1_minus_cr4",
                "cr2_minus_cr3",
                "cr2_minus_cr4",
                "cr3_minus_cr4",
            )
        },
        "definitions": {
            statistic: WP0_DEFINITIONS.get(f"supported_{statistic}", statistic)
            if statistic != "zero_fraction"
            else WP0_DEFINITIONS["zero_fraction"]
            for statistic in STATISTICS
        },
        "pair_columns": PAIR_COLUMNS_DEFINITIONS,
        "checks": dict(sorted(model.checks.items())),
        "ok": model.ok,
    }


def render_figure(model: ReferenceFloor, path: Path) -> Path:
    """Draw the four reference runs and their pairwise differences against depth.

    Two panels. The upper one keeps the four runs individually visible — no averaged
    profile is drawn, on purpose — and the lower one draws all six differences with
    the floor's own pair marked. The caption carries the floor, its endpoint and the
    caveats, so the image alone cannot be read as a confidence interval.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    depths = np.asarray(model.depth_resolved.depths_mm, dtype=float)
    figure, (levels, differences) = plt.subplots(
        2, 1, figsize=(7.4, 8.2), sharex=True, dpi=FIGURE_DPI
    )
    colors = {
        "cr1": "#1f77b4",
        "cr2": "#ff7f0e",
        "cr3": "#2ca02c",
        "cr4": "#d62728",
    }
    for label, color in colors.items():
        levels.plot(
            getattr(model.depth_resolved, label),
            depths,
            color=color,
            linewidth=1.5,
            label=f"{label}  ({next(run for run in model.runs if run.label == label).job})",
        )
    levels.set_ylabel("depth [mm]")
    levels.invert_yaxis()
    levels.set_xlabel("window mean velocity [mm/s]")
    levels.set_title(
        "the four reference runs, individually — no averaged profile is drawn\n"
        f"one condition: burst 10 / emissions 20 / {int(model.runs[0].gates)} gates at "
        f"{model.runs[0].resolution_mm:.2f} mm",
        fontsize=10,
    )
    levels.grid(alpha=0.2)
    levels.legend(loc="lower right", fontsize=7.5, framealpha=0.9)

    for pair in model.pairs:
        key = f"{pair.left}_minus_{pair.right}"
        is_floor = (pair.left, pair.right) == model.floor_pair
        differences.plot(
            getattr(model.depth_resolved, key),
            depths,
            color="#d62728" if is_floor else "#999999",
            linewidth=1.8 if is_floor else 0.9,
            label=f"{pair.left} - {pair.right}",
        )
    differences.axvline(0.0, color="#444444", linewidth=0.8)
    differences.set_ylabel("depth [mm]")
    differences.set_xlabel("per-depth window-mean difference [mm/s]")
    differences.set_title(
        f"all six pairwise differences; the floor is {model.floor_mm_s:.3f} mm/s at "
        f"{model.floor_depth_mm:.2f} mm, pair {model.floor_pair[0]}-{model.floor_pair[1]}",
        fontsize=9,
    )
    differences.grid(alpha=0.2)
    differences.legend(loc="lower right", fontsize=6.5, ncol=3, framealpha=0.9)

    figure.text(
        0.01,
        0.012,
        _wrap(
            f"depth-resolved endpoint: {model.floor_endpoint} = "
            f"{model.floor_mm_s:.4f} mm/s at {model.floor_depth_mm:.3f} mm "
            f"({model.floor_pair[0]} - {model.floor_pair[1]}); depth-averaged "
            f"endpoint: {model.averaged_endpoint} = "
            f"{model.averaged_floor_mm_s:.4f} mm/s ({model.averaged_floor_pair[0]} - "
            f"{model.averaged_floor_pair[1]}). Four runs over four reference jobs, "
            f"separated by their job starts: {model.pairs[0].job_start_separation_min:.1f} "
            f"min at the closest and "
            f"{max(pair.job_start_separation_min for pair in model.pairs):.1f} at the widest "
            "(job-start separation, not a recording interval - the pass carries no "
            "per-recording clock). "
            f"Primary window {model.window_s:g} s ({model.window_revolutions} nominal "
            f"revolutions), common support {model.support_min_mm:.3f}-"
            f"{model.support_max_mm:.3f} mm, {int(depths.size)} supported gates. An "
            "observed difference between four recordings and four runs - not a "
            "confidence interval, not a separability criterion, no proof of an axis "
            "effect. Per-pair: "
            + " | ".join(
                f"{pair.left}-{pair.right} mean {pair.mean_difference_mm_s:+.3f} "
                f"max |.| {pair.max_abs_difference_mm_s:.3f}"
                for pair in model.pairs
            )
        ),
        fontsize=5.4,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.90, bottom=0.21, hspace=0.18)
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


def write_reference_floor(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    plan_path: Path = PLAN_PATH,
    analysis_commit: str | None = None,
) -> ReferenceFloor:
    """Build the floor and write the table, the document and the figure.

    Every file is UTF-8 with LF endings and one trailing newline, so two runs on the
    same inputs and revision produce identical bytes. Nothing is written when the
    build refuses.
    """
    model = build_reference_floor(
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
    render_figure(model, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model


def reference_floor_main(argv: list[str] | None = None) -> None:
    """``sparse-reference-floor`` — write WP2's between-run reference floor.

    Reads the four reference recordings through the frozen WP0 ingest's own binding and
    decoding, keeps them as four individually visible runs ordered in campaign time,
    computes their six pairwise depth-resolved differences on the common support, and
    publishes the compact reduction the later packages screen against. It exits 0 when
    every WP2 gate check holds and 1 otherwise, naming the failure; a pass the ingest
    refuses exits 1 with the ingest's own reason and writes nothing.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-reference-floor",
        description=(
            "WP2: the sparse pass's between-run reference floor from CR1-CR4, kept as "
            "four runs"
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
        help="directory to write reference-floor.csv and reference-floor.json into",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    try:
        model = write_reference_floor(
            Path(args.dataset_root),
            Path(args.report_dir),
            plan_path=Path(args.plan),
            analysis_commit=args.analysis_commit,
        )
    except SparseIngestError as exc:
        print(f"udv-sparse-reference-floor: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    for run in model.runs:
        print(
            f"{run.label:4s} {run.job:20s} started {run.job_started_at} "
            f"mean {run.statistics['mean']:9.4f} mm/s"
        )
    for pair in model.pairs:
        print(
            f"{pair.left}-{pair.right}: job starts {pair.job_start_separation_min:5.1f} min "
            "apart, "
            f"mean {pair.mean_difference_mm_s:+8.3f}, "
            f"max |.| {pair.max_abs_difference_mm_s:7.3f} at "
            f"{pair.max_abs_depth_mm:6.2f} mm"
        )
    print(
        f"floor   : depth-resolved {model.floor_mm_s:.4f} mm/s at "
        f"{model.floor_depth_mm:.3f} mm ({model.floor_pair[0]} - "
        f"{model.floor_pair[1]}); depth-averaged "
        f"{model.averaged_floor_mm_s:.4f} mm/s ({model.averaged_floor_pair[0]} - "
        f"{model.averaged_floor_pair[1]})"
    )
    print(f"table   : {Path(args.report_dir) / CSV_NAME}")
    print(f"document: {Path(args.report_dir) / DOC_NAME}")
    failed = [name for name, ok in sorted(model.checks.items()) if not ok]
    for name in failed:
        print(f"udv-sparse-reference-floor: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
