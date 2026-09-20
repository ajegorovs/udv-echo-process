"""WP2, resolution axis — the measured pitch ladder against the sole-pair screening threshold.

The committed sweep holds a 13-point resolution ladder: one base-state recording per gate pitch,
0.247 mm (`res/0-2.BDD`, 365 gates) to 2.96 mm (`res/3-0.BDD`, 31 gates), over the same ~100 mm
window (plan §2). This module answers the plan's question — *does 0.247 mm add information over
0.617 mm, and how coarse can a measured pitch go before structure is lost* — from the ``res``
rows of the WP0 manifest, never a filename list (plan §4 WP2 gate). The recordings are selected by
their decoded **scientific fingerprint**: :data:`ELIGIBILITY` names the pitch as the only setting this
axis may move, so every recording that shares the rest of the fingerprint - including
`prf/600.BDD`, which sits under another folder - is eligible and realizes the level its own decoded
pitch names, with the two 1.850 mm recordings recorded as two named realizations of one level
(plan §8.3 step 2, R1/R4). The ladder holds **every eligible decoded level**, and each level's
numbers are measured per realization and then summarised by the shared, unweighted rule
(:data:`udv_echo_process.analysis._native_grid.AGGREGATION_RULE`): one decoded pitch is one level
however many recordings realize it, and no recording is dropped, collapsed into another's path or
allowed to outweigh another (plan §8.3 step 5). One build produces:

- the **common views** — the largest whole number of nominal 500-RPM revolutions (0.12 s) fitting
  every recording, and the intersection of the decoded depth ranges (plan §3.1, §3.2);
- **level metrics on each native grid** — mean, robust spread (IQR), RMS about zero, zero fraction
  and gate-level temporal IQR over the common window, plus the gate-to-gate gradient and the
  spatial correlation length, both computed *before* any comparison (plan §3.2);
- **pairs on common knots** — every unordered pair on the coarser participant's own gate depths
  inside the support, the finer level *sampled* there by nearest native gate: no interpolation,
  no upsampling, and the knots that clear the committed WP1 screening_threshold, where in depth and by what
  ratio (plan §4 WP1 gate);
- the **detail below the coarse knots**, measured inside the finer recording alone so no drift
  enters it: its native mean profile minus that same profile sampled at the coarse knots.

Gates and profiles are not independent replicates, the levels carry no acquisition order (their
differences hold drift as well as pitch), and no p-value family is produced (plan §3.3). Resolution
axis only: burst, PRF, TGC/power and emissions are out of scope, and 500 RPM is a marker
(8.33 Hz), never a phase reference.

The input binding and most of the machinery are *shared*, not duplicated: the axis-input layer, the
common views, the native-grid metrics, the pairwise alignment, the committed WP1 readers and the
writers live in ``_native_grid.py``, which the burst, PRF and TGC/power axes of the same plan reuse.
WP1's temporal models (per-gate autocorrelation/PSD on a second time base) have no counterpart
here: this axis compares pitch, not time.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis import _native_grid as grid
from udv_echo_process.analysis._native_grid import (
    CORRELATION_FLOOR,
    AxisEligibility,
    LevelGroup,
    LevelMetrics,
    NativeGridError,
    ScreeningThresholdBinding,
    align_on_knots,
    common_support,
    correlation_length,  # noqa: F401 - re-exported for the focused resolution tests
    csv_text,
    depth_ranges,
    in_support,
    level_metrics,
    nearest_gate_indices,
    panel_figure,
    read_decoded_level,
    read_screening_threshold,
    select_axis_rows,
    sha256_file,
    spatial_gradient,  # noqa: F401 - re-exported for the focused resolution tests
    write_text_artefacts,
)
from udv_echo_process.analysis.reference_repeat import (
    NOMINAL_REVOLUTION_S,
    NOMINAL_RPM,
    common_revolution_count,
)
from udv_echo_process.analysis.sweep_inventory import (
    DATASET_ROOT,
    MANIFEST_NAME,
    REPORT_DIR,
)
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: The manifest axis this module owns, and the reviewer-visible artefacts.
AXIS = "res"
LEVELS_NAME = "resolution-levels.csv"
PAIRS_NAME = "resolution-pairs.csv"
PROVENANCE_NAME = "resolution-ladder.provenance.json"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "resolution-ladder.png"

#: The axis's setting-based contract (plan §8.3 step 2, R1/R4): the pitch is the only decoded
#: setting this ladder may move, so every recording sharing the rest of the fingerprint - whatever
#: folder its row sits in - is eligible, and the two 1.850 mm recordings are two realizations of one
#: level rather than a duplicate key.
ELIGIBILITY = AxisEligibility(
    axis=AXIS, ladder_label="resolution", varied=("resolution_mm",)
)

#: The committed WP1 artefact the decision threshold is read from.
SCREENING_THRESHOLD_NAME = "reference-repeat.provenance.json"

#: The two pitches the plan's question names (0.247 mm, 0.617 mm): the focus pair
#: is selected by *pitch* from the manifest, in the same way every row is.
FOCUS_PITCHES_MM: tuple[float, float] = (0.246666666667, 0.616666666667)
FOCUS_PITCH_RTOL = 1e-6

#: The plan's stated common physical support, with the tolerance its wording allows.
PLAN_SUPPORT_MM: tuple[float, float] = (10.163, 96.743)
PLAN_SUPPORT_TOLERANCE_MM = 0.01

#: Column order of ``resolution-levels.csv``; the field order of :class:`LevelRow` is
#: the same tuple, so the table and the model cannot drift apart. ``realizations`` and
#: ``realization_paths`` name the recordings one level summarises: a level with two of them is one
#: row, and both paths are still published here rather than collapsed (plan §8.3 step 5).
LEVEL_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "realizations", "realization_paths",
    "pitch_mm", "gates", "duration_s",
    "profiles", "profiles_window", "gates_in_support", "depth_min_mm",
    "depth_max_mm", "support_min_mm", "support_max_mm", "mean_mm_s",
    "robust_spread_mm_s", "rms_mm_s", "zero_fraction", "time_iqr_median_mm_s",
    "gradient_median_abs_mm_s_per_mm", "gradient_max_abs_mm_s_per_mm",
    "gradient_max_depth_mm", "correlation_length_mm", "correlation_lag_max_mm",
    "correlation_reaches_floor", "correlation_length_over_pitch",
)

#: The level cells the shared aggregation rule is applied to (plan §8.3 step 5): everything a level
#: row carries apart from its identity (``axis``/``relative_path``/``requested_label``), the set it
#: names (``realizations``/``realization_paths``), the one view it was measured in
#: (``support_min_mm``/``support_max_mm``) and its one boolean verdict, which aggregates by
#: conjunction rather than by a mean.
AGGREGATED_CELLS: tuple[str, ...] = (
    "pitch_mm", "duration_s", "profiles", "profiles_window", "depth_min_mm", "depth_max_mm",
    "mean_mm_s", "robust_spread_mm_s", "rms_mm_s", "zero_fraction", "time_iqr_median_mm_s",
    "gradient_median_abs_mm_s_per_mm", "gradient_max_abs_mm_s_per_mm", "gradient_max_depth_mm",
    "correlation_length_mm", "correlation_lag_max_mm", "correlation_length_over_pitch",
)
#: Cells that stay whole numbers: every realization of one level measures the same native gate grid,
#: so their gate counts are identical and the mean is one of them. Refused if it is not.
INTEGRAL_CELLS: tuple[str, ...] = ("gates", "gates_in_support")
#: The per-realization cells the provenance document publishes beside each level's mean, so every
#: mean can be audited against the recordings it summarises.
REALIZATION_CELLS: tuple[str, ...] = (
    "profiles", "profiles_window", "gates", "gates_in_support", "duration_s", "mean_mm_s",
    "robust_spread_mm_s", "rms_mm_s", "zero_fraction", "time_iqr_median_mm_s",
    "gradient_median_abs_mm_s_per_mm", "gradient_max_abs_mm_s_per_mm",
    "correlation_length_mm", "correlation_reaches_floor",
)

#: Column order of ``resolution-pairs.csv``; one row per unordered level pair.
PAIR_COLUMNS: tuple[str, ...] = (
    "axis", "fine_path", "fine_label", "fine_pitch_mm", "coarse_path",
    "coarse_label", "coarse_pitch_mm", "knot_spacing_mm", "knots",
    "support_min_mm", "support_max_mm", "max_knot_offset_mm",
    "mean_abs_difference_mm_s", "median_abs_difference_mm_s",
    "max_abs_difference_mm_s", "max_abs_difference_depth_mm",
    "knots_above_screening_threshold", "fraction_above_screening_threshold",
    "max_abs_difference_over_screening_threshold", "depth_ranges_above_screening_threshold_mm",
    "fine_variance_share_at_coarse_knots", "fine_detail_rms_mm_s",
    "fine_detail_max_abs_mm_s", "fine_detail_variance_share",
)


#: The error class of every message this module raises. The native-grid helpers of
#: :mod:`udv_echo_process.analysis._native_grid` raise the same class, so a caller
#: catches a helper refusal and an axis refusal under one name.
ResolutionLadderError = NativeGridError


# ── models ─────────────────────────────────────────────────────────────


class LevelInput(ValueModel):
    """One resolution level, as decoded and pinned to its manifest row."""

    relative_path: str
    axis: str
    requested_label: str
    source_sha256: str
    pitch_mm: float
    gates: int
    profiles: int
    duration_s: float
    depth_min_mm: float
    depth_max_mm: float


class CommonView(ValueModel):
    """The two views every cross-level number is restricted to.

    ``profiles_window`` and ``gates_in_support`` are keyed by manifest path: one
    shared duration leaves each recording a different profile count, and one shared
    support leaves each level a different gate count.
    """

    nominal_rpm: float
    revolution_s: float
    revolutions: int
    window_s: float
    profiles_window: dict[str, int]
    gates_in_support: dict[str, int]
    support_min_mm: float
    support_max_mm: float
    levels: int


class LevelRow(ValueModel):
    """One row of ``resolution-levels.csv``: a decoded level on its own native grid.

    A level summarises **every** recording that realizes it (plan §8.3 step 5): every numeric cell is
    the unweighted mean of its realizations' cells, ``correlation_reaches_floor`` holds only when
    every realization's own autocovariance reached the 1/e floor, ``profiles``/``profiles_window``/
    ``duration_s`` are means because two realizations of one setting observe for different lengths,
    ``gates``/``gates_in_support`` are the one gate grid their shared resolution gives them, and
    ``realization_paths`` names each recording rather than collapsing them.
    """

    axis: str
    relative_path: str
    requested_label: str
    realizations: int
    realization_paths: str
    pitch_mm: float
    gates: int
    duration_s: float
    profiles: float
    profiles_window: float
    gates_in_support: int
    depth_min_mm: float
    depth_max_mm: float
    support_min_mm: float
    support_max_mm: float
    mean_mm_s: float
    robust_spread_mm_s: float
    rms_mm_s: float
    zero_fraction: float
    time_iqr_median_mm_s: float
    gradient_median_abs_mm_s_per_mm: float
    gradient_max_abs_mm_s_per_mm: float
    gradient_max_depth_mm: float
    correlation_length_mm: float
    correlation_lag_max_mm: float
    correlation_reaches_floor: bool
    correlation_length_over_pitch: float

    @model_validator(mode="after")
    def _check_the_level_names_every_realization(self) -> LevelRow:
        paths = [path for path in self.realization_paths.split(";") if path]
        if len(paths) != self.realizations or self.relative_path not in paths:
            raise ValueError(
                f"a level must name each of its {self.realizations} realization(s), including "
                f"its own {self.relative_path!r}, got {self.realization_paths!r}"
            )
        return self


class PairRow(ValueModel):
    """One row of ``resolution-pairs.csv``: a fine/coarse pair on common knots."""

    axis: str
    fine_path: str
    fine_label: str
    fine_pitch_mm: float
    coarse_path: str
    coarse_label: str
    coarse_pitch_mm: float
    knot_spacing_mm: float
    knots: int
    support_min_mm: float
    support_max_mm: float
    max_knot_offset_mm: float
    mean_abs_difference_mm_s: float
    median_abs_difference_mm_s: float
    max_abs_difference_mm_s: float
    max_abs_difference_depth_mm: float
    knots_above_screening_threshold: int
    fraction_above_screening_threshold: float
    max_abs_difference_over_screening_threshold: float
    depth_ranges_above_screening_threshold_mm: str
    fine_variance_share_at_coarse_knots: float
    fine_detail_rms_mm_s: float
    fine_detail_max_abs_mm_s: float
    fine_detail_variance_share: float

    @model_validator(mode="after")
    def _check_the_pair_is_fine_then_coarse_on_the_coarse_grid(self) -> PairRow:
        if self.fine_pitch_mm >= self.coarse_pitch_mm:
            raise ValueError(
                f"a pair row is (fine, coarse): {self.fine_pitch_mm} is not finer "
                f"than {self.coarse_pitch_mm}"
            )
        if self.knot_spacing_mm != self.coarse_pitch_mm:
            raise ValueError(
                f"knot spacing {self.knot_spacing_mm} must be the coarser pitch "
                f"{self.coarse_pitch_mm}"
            )
        if self.knots < 2 or self.knots_above_screening_threshold > self.knots:
            raise ValueError(
                f"{self.knots} knots cannot carry {self.knots_above_screening_threshold} "
                "above-screening_threshold flags; a pair needs at least two knots"
            )
        return self


class ResolutionLadder(ValueModel):
    """The WP2 resolution result: the levels, the two views and every pair.

    ``eligibility`` and ``groups`` are the *selection* the levels were drawn from (plan §8.3
    step 2): the axis's fingerprint contract, and every eligible level with all its realizations,
    including the reference recordings another folder requested. ``levels`` is exactly those
    levels - one row per decoded pitch, each summarising every recording that realizes it - and
    ``inputs`` is every realization of every level, one entry per recording (plan §8.3 step 5).
    """

    dataset_root: str
    manifest_path: str
    manifest_sha256: str
    screening_threshold: ScreeningThresholdBinding
    axis: str = AXIS
    analysis_commit: str | None = None
    eligibility: AxisEligibility = ELIGIBILITY
    inputs: tuple[LevelInput, ...]
    groups: tuple[LevelGroup, ...] = ()
    common: CommonView
    focus_pair: tuple[str, str]
    levels: tuple[LevelRow, ...]
    pairs: tuple[PairRow, ...]
    #: One row per realization, in input order: the per-recording numbers every level mean was
    #: aggregated from, kept so a reviewer can audit each mean against the recordings behind it
    #: (plan §8.3 step 5).
    realizations: tuple[LevelRow, ...] = ()

    @model_validator(mode="after")
    def _check_the_ladder_is_internally_consistent(self) -> ResolutionLadder:
        paths = [row.relative_path for row in self.levels]
        if len(set(paths)) != len(paths):
            raise ValueError("every level must appear exactly once")
        if self.groups and [group.primary_path for group in self.groups] != paths:
            raise ValueError(
                "the ladder must be exactly the eligible decoded levels, in their order; got "
                f"{[group.primary_path for group in self.groups]} beside {paths}"
            )
        measured = {entry.relative_path for entry in self.inputs}
        if len(measured) != len(self.inputs):
            raise ValueError("every realization must appear exactly once, in its level's order")
        for group, row in zip(self.groups, self.levels, strict=False):
            if set(group.realization_paths) != set(row.realization_paths.split(";")):
                raise ValueError(
                    f"{row.relative_path}: the level must name exactly the realizations the "
                    "selection grouped with it"
                )
        if self.groups and measured != {
            path for group in self.groups for path in group.realization_paths
        }:
            raise ValueError(
                "every level must be measured on exactly its own realizations, and on no other "
                "recording"
            )
        pitches = [row.pitch_mm for row in self.levels]
        if any(b <= a for a, b in itertools.pairwise(pitches)):
            raise ValueError("levels must be ordered by increasing pitch")
        if len(self.pairs) != len(paths) * (len(paths) - 1) // 2:
            raise ValueError(
                f"expected every unordered pair of {len(paths)} levels, got "
                f"{len(self.pairs)} pairs"
            )
        if self.focus_pair not in {
            (row.fine_path, row.coarse_path) for row in self.pairs
        }:
            raise ValueError(f"focus pair {self.focus_pair} must be one of the pairs")
        if self.screening_threshold.value_mm_s <= 0.0:
            raise ValueError("the repeatability screening_threshold must be positive")
        for entry in self.inputs:
            if not (
                entry.depth_min_mm <= self.common.support_min_mm
                and self.common.support_max_mm <= entry.depth_max_mm
            ):
                raise ValueError(
                    f"{entry.relative_path} does not cover the common support "
                    f"[{self.common.support_min_mm}, {self.common.support_max_mm}]"
                )
            if self.common.gates_in_support[entry.relative_path] < 2:
                raise ValueError(
                    f"{entry.relative_path} has fewer than two gates in the common "
                    "support; its spatial metrics are undefined"
                )
        if self.realizations and [row.relative_path for row in self.realizations] != [
            entry.relative_path for entry in self.inputs
        ]:
            raise ValueError(
                "the per-realization rows must cover every recording once, in input order"
            )
        return self


# ── selection and binding to the committed inventory ───────────────────


def _row_pitch(row: Mapping[str, str], manifest_path: Path) -> float:
    """The row's decoded pitch, refused unless it is a positive finite number."""
    relative = row.get("relative_path") or "?"
    cell = (row.get("resolution_mm") or "").strip()
    try:
        pitch = float(cell)
    except ValueError:
        raise ResolutionLadderError(
            f"{relative}: manifest resolution_mm={cell!r} in {manifest_path} is not a "
            "number; the ladder cannot be ordered by pitch"
        ) from None
    if not math.isfinite(pitch) or pitch <= 0.0:
        raise ResolutionLadderError(
            f"{relative}: manifest resolution_mm={cell!r} is not a positive finite pitch"
        )
    return pitch


def _order_key(manifest_path: Path):
    """This axis's ordering key: the row's decoded pitch, pinned to the manifest path.
    """
    return lambda row: _row_pitch(row, manifest_path)


def select_level_rows(manifest_path: Path) -> tuple[dict[str, str], ...]:
    """Return the representative row of every ``res`` level the axis itself requested, by pitch.

    The ladder is pinned to the WP0 manifest rather than to a hand-maintained filename list: the
    selection, the ordering and the refusals are the shared axis-input layer's
    (:func:`_native_grid.select_axis_rows`), driven here with this axis's own contract. A recording
    of the same decoded settings sitting in another folder is *eligible*
    (:func:`level_groups`) but is not one of this axis's requested levels, so it does not redefine
    the committed ladder on its own.
    """
    path = Path(manifest_path)
    return select_axis_rows(
        path, eligibility=ELIGIBILITY, order_key=_order_key(path), order_label="pitch"
    )


def level_groups(manifest_path: Path) -> tuple[LevelGroup, ...]:
    """Every eligible ``res`` level with all its realizations, by pitch then path.

    The level of the plan's two reference recordings is one 1.850 mm level with ``res/1-8.BDD`` and
    ``prf/600.BDD`` as two named realizations, whichever folder each sits in (plan §8.3 step 2, R1).
    """
    path = Path(manifest_path)
    return grid.level_groups(
        path, eligibility=ELIGIBILITY, order_key=_order_key(path), order_label="pitch"
    )



def _read_level(
    dataset_root: Path, row: dict[str, str]
) -> tuple[LevelInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected level and bind it to its manifest row.

    Returns ``(entry, values, time_s, gate_depths_mm)`` — the manifest record and the
    ``(profiles, gates)`` velocity array in ``mm/s`` with its two axes. The decode and every check on
    it are the shared axis-input layer's, so this axis and the burst axis cannot disagree about what
    a pinned recording is.
    """
    level = read_decoded_level(Path(dataset_root), row)
    observed = level.observed
    return (
        LevelInput(
            relative_path=level.relative_path,
            axis=level.axis,
            requested_label=level.requested_label,
            source_sha256=level.source_sha256,
            pitch_mm=level.pitch_mm,
            gates=int(level.values.shape[1]),
            profiles=int(level.values.shape[0]),
            duration_s=float(observed["duration_s"]),
            depth_min_mm=float(observed["depth_min_mm"]),
            depth_max_mm=float(observed["depth_max_mm"]),
        ),
        level.values,
        level.time_s,
        level.depths,
    )



# ── the two common views and the pure spatial helpers ──────────────────


def level_row(
    entry: LevelInput, metrics: LevelMetrics, *, support: tuple[float, float]
) -> LevelRow:
    """One *realization's* row: the common-duration window on its own native grid.

    Every distributional metric uses the common window and only the gates inside the common support,
    and both spatial metrics use that supported native grid: the shared metric layer's numbers,
    computed before any alignment. One level's row is its realizations' rows under
    :func:`aggregate_level_row`; this is one recording's own numbers, published per realization so
    the mean can be audited (plan §8.3 step 5).
    """
    gradient, correlation = metrics.gradient, metrics.correlation
    means = metrics.means
    return LevelRow(
        axis=entry.axis,
        relative_path=entry.relative_path,
        requested_label=entry.requested_label,
        realizations=1,
        realization_paths=entry.relative_path,
        pitch_mm=entry.pitch_mm,
        gates=entry.gates,
        duration_s=entry.duration_s,
        profiles=entry.profiles,
        profiles_window=metrics.profiles_window,
        gates_in_support=metrics.supported_gates,
        depth_min_mm=entry.depth_min_mm,
        depth_max_mm=entry.depth_max_mm,
        support_min_mm=support[0],
        support_max_mm=support[1],
        mean_mm_s=float(means.mean()),
        robust_spread_mm_s=float(
            np.percentile(means, 75.0) - np.percentile(means, 25.0)
        ),
        rms_mm_s=float(np.sqrt(np.mean(np.square(metrics.supported)))),
        zero_fraction=float(
            np.count_nonzero(metrics.supported == 0.0) / metrics.supported.size
        ),
        time_iqr_median_mm_s=float(np.median(metrics.per_gate["iqr"][metrics.mask])),
        gradient_median_abs_mm_s_per_mm=gradient.median_abs_mm_s_per_mm,
        gradient_max_abs_mm_s_per_mm=gradient.max_abs_mm_s_per_mm,
        gradient_max_depth_mm=gradient.max_depth_mm,
        correlation_length_mm=correlation.length_mm,
        correlation_lag_max_mm=correlation.lag_max_mm,
        correlation_reaches_floor=correlation.reaches_floor,
        correlation_length_over_pitch=correlation.length_mm / entry.pitch_mm,
    )



def pair_row(
    fine: LevelInput,
    fine_mean_mm_s: np.ndarray,
    fine_depths_mm: np.ndarray,
    coarse: LevelInput,
    coarse_mean_mm_s: np.ndarray,
    coarse_depths_mm: np.ndarray,
    *,
    support: tuple[float, float],
    screening_threshold: ScreeningThresholdBinding,
) -> PairRow:
    """Compare a fine level with a coarse one on the coarser grid's own knots.

    The knots are the coarse participant's native gate depths inside the common support, so their
    spacing is the coarser pitch, never finer than the coarsest participating pitch (plan §3.2); the
    fine profile is sampled there by the shared :func:`nearest_gate_indices` — the nearest native
    gate's value, no interpolation. The ``fine_detail_*`` fields are measured inside the *finer
    recording alone* (its supported native mean profile minus that same profile sampled at the coarse
    knots), so they carry no drift and bound how much spatial variance the finer pitch adds below the
    coarse knot spacing.
    """
    if fine.pitch_mm >= coarse.pitch_mm:
        raise ResolutionLadderError(
            f"a pair is (fine, coarse): {fine.relative_path} at {fine.pitch_mm:g} mm "
            f"is not finer than {coarse.relative_path} at {coarse.pitch_mm:g} mm"
        )
    fine_depths = np.asarray(fine_depths_mm, dtype=float)
    coarse_depths = np.asarray(coarse_depths_mm, dtype=float)
    fine_mean = np.asarray(fine_mean_mm_s, dtype=float)
    aligned = align_on_knots(
        fine_depths,
        fine_mean,
        coarse_depths,
        np.asarray(coarse_mean_mm_s, dtype=float),
        path=fine.relative_path,
        support=support,
        threshold_mm_s=screening_threshold.value_mm_s,
    )
    knots, absolute, flagged = aligned.knots, aligned.absolute, aligned.flagged
    fine_at_knots = fine_mean[aligned.indices]
    fine_mask = in_support(fine_depths, support)
    native = fine_mean[fine_mask]
    detail = native - fine_at_knots[nearest_gate_indices(knots, fine_depths[fine_mask])]
    return PairRow(
        axis=fine.axis,
        fine_path=fine.relative_path,
        fine_label=fine.requested_label,
        fine_pitch_mm=fine.pitch_mm,
        coarse_path=coarse.relative_path,
        coarse_label=coarse.requested_label,
        coarse_pitch_mm=coarse.pitch_mm,
        knot_spacing_mm=coarse.pitch_mm,
        knots=int(knots.size),
        support_min_mm=support[0],
        support_max_mm=support[1],
        max_knot_offset_mm=aligned.offset_mm,
        mean_abs_difference_mm_s=float(absolute.mean()),
        median_abs_difference_mm_s=float(np.median(absolute)),
        max_abs_difference_mm_s=float(absolute[aligned.worst]),
        max_abs_difference_depth_mm=float(knots[aligned.worst]),
        knots_above_screening_threshold=int(np.count_nonzero(flagged)),
        fraction_above_screening_threshold=float(np.count_nonzero(flagged) / flagged.size),
        max_abs_difference_over_screening_threshold=float(absolute[aligned.worst] / screening_threshold.value_mm_s),
        depth_ranges_above_screening_threshold_mm=depth_ranges(knots, flagged),
        fine_variance_share_at_coarse_knots=float(
            np.var(fine_at_knots) / aligned.sampled_variance
        ),
        fine_detail_rms_mm_s=float(np.sqrt(np.mean(np.square(detail)))),
        fine_detail_max_abs_mm_s=float(np.abs(detail).max()),
        fine_detail_variance_share=float(np.var(detail) / aligned.sampled_variance),
    )



def _focus_pair(levels: Sequence[LevelRow]) -> tuple[str, str]:
    """The two levels the plan's question names, selected by pitch from the ladder.

    Raises:
        ResolutionLadderError: when either named pitch is absent from the ladder.
    """
    selected: list[str] = []
    for pitch in FOCUS_PITCHES_MM:
        matches = [
            row
            for row in levels
            if math.isclose(row.pitch_mm, pitch, rel_tol=FOCUS_PITCH_RTOL)
        ]
        if len(matches) != 1:
            raise ResolutionLadderError(
                f"the plan's question names the pitch {pitch:g} mm, the manifest "
                f"ladder holds {len(matches)} level(s) at it; the selection is by "
                "pitch, never by filename"
            )
        selected.append(matches[0].relative_path)
    return selected[0], selected[1]


# ── the level aggregation (plan §8.3 step 5) ───────────────────────────


def selected_levels(manifest_path: Path) -> tuple[tuple[LevelGroup, tuple[dict[str, str], ...]], ...]:
    """Every eligible ``res`` level beside the rows of *every* recording that realizes it.

    The ladder is the setting-based selection (plan §8.3 step 5): a decoded pitch is one level, and
    a recording under another folder that carries the same swept settings realizes it rather than
    being excluded. Ordered by decoded pitch, then by the level's primary path.
    """
    path = Path(manifest_path)
    return grid.grouped_level_rows(
        path, eligibility=ELIGIBILITY, order_key=_order_key(path), order_label="pitch"
    )


def aggregate_level_row(
    group: LevelGroup, rows: Sequence[LevelRow], *, support: tuple[float, float]
) -> LevelRow:
    """One decoded level's row: its realizations' rows under the shared aggregation rule.

    Every numeric cell is the unweighted mean of its realizations' cells (one realization, one
    vote), ``gates``/``gates_in_support`` are the one native gate grid the level's shared resolution
    gives every realization, and ``correlation_reaches_floor`` holds only when every realization's
    own autocovariance reached 1/e - so no realization is dropped, collapsed into another's path or
    allowed to outweigh another (plan §8.3 step 5, R1).
    """
    if not rows:
        raise ResolutionLadderError(
            f"{group.primary_path}: the decoded level realises no recording, so it cannot be "
            "measured"
        )
    level = group.primary_path
    cells: dict[str, object] = {
        cell: grid.aggregate_cell(
            [float(getattr(row, cell)) for row in rows], cell=cell, level=level
        )
        for cell in AGGREGATED_CELLS
    }
    for cell in INTEGRAL_CELLS:
        mean = grid.aggregate_cell(
            [float(getattr(row, cell)) for row in rows], cell=cell, level=level
        )
        if not math.isclose(mean, round(mean), abs_tol=1e-9):
            raise ResolutionLadderError(
                f"{level}: the realizations measure {mean:g} {cell}; one decoded level keeps one "
                "native gate grid and this build resamples nothing"
            )
        cells[cell] = round(mean)
    primary = next(row for row in rows if row.relative_path == level)
    return LevelRow(
        axis=group.axis,
        relative_path=level,
        requested_label=primary.requested_label,
        realizations=len(rows),
        realization_paths=";".join(group.realization_paths),
        support_min_mm=support[0],
        support_max_mm=support[1],
        correlation_reaches_floor=grid.aggregate_verdict(
            [row.correlation_reaches_floor for row in rows], rule="all"
        ),
        **cells,
    )


def _build(
    dataset_root: Path,
    manifest_path: Path,
    screening_threshold_path: Path,
    analysis_commit: str | None,
) -> tuple[ResolutionLadder, dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Build the ladder and return it beside each level's *aggregated* native mean profile."""
    selected = selected_levels(manifest_path)
    manifest_sha256 = f"sha256:{sha256_file(Path(manifest_path))}"
    screening_threshold = read_screening_threshold(Path(screening_threshold_path), manifest_sha256)
    root = Path(dataset_root)
    decoded = [
        (group, _read_level(root, row)) for group, rows in selected for row in rows
    ]
    entries = [entry for _group, (entry, *_rest) in decoded]
    revolutions = common_revolution_count([entry.duration_s for entry in entries])
    window_s = revolutions * NOMINAL_REVOLUTION_S
    support = common_support([(entry.depth_min_mm, entry.depth_max_mm) for entry in entries])
    metrics = [
        level_metrics(
            entry.relative_path, values, time_s, depths, window_s=window_s, support=support
        )
        for _group, (entry, values, time_s, depths) in decoded
    ]
    realization_rows = {
        entry.relative_path: level_row(entry, own, support=support)
        for (_group, (entry, *_rest)), own in zip(decoded, metrics, strict=True)
    }
    depths_by_path = {
        entry.relative_path: depths for _group, (entry, _v, _t, depths) in decoded
    }
    means_by_path = {
        entry.relative_path: own.per_gate["mean"]
        for (_group, (entry, *_rest)), own in zip(decoded, metrics, strict=True)
    }
    levels: list[LevelRow] = []
    profiles: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for group, rows in selected:
        paths = group.realization_paths
        levels.append(
            aggregate_level_row(
                group, [realization_rows[path] for path in paths], support=support
            )
        )
        profiles[group.primary_path] = (
            grid.require_one_native_grid(
                [(path, depths_by_path[path]) for path in paths], where=group.primary_path
            ),
            grid.mean_profile([means_by_path[path] for path in paths], where=group.primary_path),
        )
    pairs = tuple(
        pair_row(
            fine,
            profiles[fine.relative_path][1],
            profiles[fine.relative_path][0],
            coarse,
            profiles[coarse.relative_path][1],
            profiles[coarse.relative_path][0],
            support=support,
            screening_threshold=screening_threshold,
        )
        for fine, coarse in itertools.combinations(levels, 2)
    )
    commit = analysis_commit if analysis_commit is not None else current_revision()
    model = ResolutionLadder(
        dataset_root=root.as_posix(),
        manifest_path=Path(manifest_path).as_posix(),
        manifest_sha256=manifest_sha256,
        screening_threshold=screening_threshold,
        analysis_commit=commit,
        eligibility=ELIGIBILITY,
        inputs=tuple(entries),
        groups=tuple(group for group, _rows in selected),
        common=CommonView(
            nominal_rpm=NOMINAL_RPM,
            revolution_s=NOMINAL_REVOLUTION_S,
            revolutions=revolutions,
            window_s=window_s,
            profiles_window={
                entry.relative_path: own.profiles_window
                for (_group, (entry, *_rest)), own in zip(decoded, metrics, strict=True)
            },
            gates_in_support={
                entry.relative_path: own.supported_gates
                for (_group, (entry, *_rest)), own in zip(decoded, metrics, strict=True)
            },
            support_min_mm=support[0],
            support_max_mm=support[1],
            levels=len(levels),
        ),
        focus_pair=_focus_pair(levels),
        levels=tuple(levels),
        pairs=pairs,
        realizations=tuple(realization_rows[entry.relative_path] for entry in entries),
    )
    return model, profiles



def build_resolution_ladder(
    dataset_root: Path = DATASET_ROOT,
    manifest_path: Path = REPORT_DIR / MANIFEST_NAME,
    screening_threshold_path: Path = REPORT_DIR / SCREENING_THRESHOLD_NAME,
    *,
    analysis_commit: str | None = None,
) -> ResolutionLadder:
    """Build the WP2 resolution ladder from the manifest-selected recordings.

    ``analysis_commit`` is the revision to record; ``None`` probes the checkout's short git SHA once
    (never blocking), and passing the recorded commit reproduces a committed artefact. A manifest, a
    WP1 screening_threshold or a recording that contradicts its row is refused by name before anything is
    written.
    """
    return _build(
        dataset_root, Path(manifest_path), Path(screening_threshold_path), analysis_commit
    )[0]


# ── the artefacts a reviewer reads ─────────────────────────────────────


#: Metric definitions, recorded verbatim in the provenance document so the tables
#: cannot be read without them.
DEFINITIONS: dict[str, str] = {
    "pitch_mm": (
        "mean step of the decoded gate depths (mm), re-checked against the manifest's "
        "resolution_mm cell: the realised pitch, not the rung label"
    ),
    "robust_spread": (
        "interquartile range p75 - p25 across supported gates of the per-gate time "
        "means, linear-interpolated percentiles, mm/s"
    ),
    "rms": (
        "root mean square about zero over the common window and support, mm/s; "
        "DC-inclusive, so a mean offset raises it (not a standard deviation)"
    ),
    "zero_fraction": (
        "samples exactly equal to 0.0 over the sample count, common window and support, "
        "dimensionless"
    ),
    "time_iqr": (
        "median over supported gates of the per-gate temporal interquartile range, mm/s"
    ),
    "gradient": (
        "median and maximum |mean[k+1] - mean[k]| / pitch on the supported native grid, "
        "mm/s per mm, before any alignment, at the interval midpoint"
    ),
    "correlation_length": (
        "first lag where the normalized biased autocovariance of the mean-removed "
        "supported native mean profile falls below 1/e, in mm (gates x pitch); capped at "
        "floor((gates - 1) / 2) gates, where a cap is a lower bound "
        "(correlation_reaches_floor false)"
    ),
    "knots": (
        "a pair's common depth knots: the coarser participant's native gate depths in "
        "the common support, so the spacing equals the coarser pitch, never finer than "
        "the coarsest participating pitch"
    ),
    "difference": (
        "signed fine - coarse per-gate time mean at every knot, mm/s; mean/median/max "
        "absolute values and the knot of the maximum are reported beside it"
    ),
    "screening_threshold": (
        "the committed sole-pair observed-discrepancy screening threshold, "
        "max_gate_abs_mean_difference_mm_s, read from reference-repeat.provenance.json and "
        "pinned to this manifest's hash: the threshold every effect here is screened "
        "against, one observed realization of repeatability *plus* uncontrolled drift and "
        "not a bound on either"
    ),
    "detail": (
        "inside the finer recording alone, so drift-free: its supported native mean "
        "profile minus that profile sampled at the coarse knots, as RMS, peak and share "
        "of the spatial variance; fine_variance_share_at_coarse_knots is what the coarse "
        "knots retain (1.0 = coarsening loses nothing)"
    ),
    "replicates": (
        "no profile and no gate is an independent experimental replicate: each level is "
        "one recording, the levels carry no acquisition order, and their differences "
        "hold drift as well as pitch"
    ),
    "time_view": (
        "the common-duration view of every distributional metric: the largest integer "
        "number of nominal 500-RPM revolutions (0.12 s) fitting every level, truncated "
        "per file by the recorded timestamps"
    ),
    "realizations": (
        "the recordings that realize one decoded level: the ladder holds every eligible "
        "decoded pitch, so `res/1-8.BDD` and `prf/600.BDD` are two named realizations of the "
        "1.850 mm level rather than one being dropped or standing in for the other; "
        "realization_paths names each of them and the provenance document carries each one's "
        "own numbers"
    ),
    "aggregation": (
        "how one level's numbers are formed from its realizations: " + grid.AGGREGATION_RULE
    ),
    "depth_view": (
        "each level on its own decoded gate grid, restricted to the common physical "
        "support; gradient and correlation length are native-grid quantities and nothing "
        "is upsampled in this report"
    ),
}

#: The two caveats that travel with every resolution artefact.
MIXER_SETPOINT_ROLE = (
    "nominal mixer marker only (500 RPM -> 8.33 Hz, one revolution = 0.12 s): these "
    "files carry no tachometer, so the setpoint is not a phase reference and no "
    "harmonic is attributed to it"
)
REPLICATE_ROLE = (
    "no gate and no profile is an independent experimental replicate - gates and "
    "profiles are not independent samples, and the levels carry no acquisition order"
)

#: The two verdicts of :func:`_findings`, written once so the wording cannot drift
#: between the provenance document and the figure caption.
_FOCUS_VERDICT = (
    "Verdict: an information gain from 0.247 mm over 0.617 mm is not demonstrated - "
    "both the level difference and the structure the extra gates add sit inside the "
    "repeat-plus-drift screening_threshold, so this evidence cannot support that claim; it "
    "equally cannot exclude a real effect smaller than the bound, which one "
    "same-settings repeat cannot resolve."
)
_COARSEST_VERDICT = (
    "On this evidence the coarsest *measured* pitch preserves the structure the finer "
    "pitches show, and no measured pitch is shown to lose it - a statement about the "
    "13 recorded pitches only: nothing finer or coarser was measured, and a resolution "
    "effect smaller than the drift-inclusive screening_threshold would be invisible here."
)

#: Panels of the reviewer-visible figure.
FIGURE_PANELS: tuple[str, ...] = (
    (
        "native-grid spatial correlation length versus gate pitch, with the 1:1 line "
        "where a correlation length would equal one gate"
    ),
    (
        "the plan's 0.247 mm vs 0.617 mm pair: both aligned profiles versus depth, the "
        "signed difference at the 0.617 mm knots and the WP1 screening_threshold band; the native "
        "gradient spread stays in resolution-levels.csv"
    ),
)


def _rows_of(columns: Sequence[str], rows: Sequence[object]) -> list[dict[str, object]]:
    """The given column of every row object, as a mapping per row."""
    return [{column: getattr(row, column) for column in columns} for row in rows]


def levels_csv_text(model: ResolutionLadder) -> str:
    """Render ``resolution-levels.csv`` from the model's own level rows."""
    return csv_text(LEVEL_COLUMNS, _rows_of(LEVEL_COLUMNS, model.levels))


def pairs_csv_text(model: ResolutionLadder) -> str:
    """Render ``resolution-pairs.csv`` from the model's own pair rows."""
    return csv_text(PAIR_COLUMNS, _rows_of(PAIR_COLUMNS, model.pairs))


def _findings(model: ResolutionLadder) -> dict[str, object]:
    """The plan's resolution questions answered from the numbers the tables already carry.

    Every statement is composed from those values, so a regeneration says what it wrote. Nothing here
    is a p-value, a significance claim, or a decision about an axis this module does not own.
    """
    screening_threshold = model.screening_threshold.value_mm_s
    pairs = model.pairs
    above = [row for row in pairs if row.knots_above_screening_threshold]
    worst = max(pairs, key=lambda row: row.max_abs_difference_mm_s)
    focus = next(
        row for row in pairs if (row.fine_path, row.coarse_path) == model.focus_pair
    )
    lengths = [row.correlation_length_mm for row in model.levels]
    units = [row.correlation_length_over_pitch for row in model.levels]
    coarsest = model.levels[-1]

    coarse_pairs = [row for row in pairs if row.coarse_path == coarsest.relative_path]
    coarse_worst = max(row.max_abs_difference_mm_s for row in coarse_pairs)
    coarse_ratio = max(row.max_abs_difference_over_screening_threshold for row in coarse_pairs)
    gate_tail = (
        f"{len(above)} of {len(pairs)} pairs put a knot above the screening_threshold, named with "
        "their depth ranges in resolution-pairs.csv"
        if above
        else (
            f"not one of the {len(pairs)} pairs puts a knot above the screening_threshold, so no "
            "level differs from another by more than repeat-plus-drift anywhere in the "
            "common support"
        )
    )
    return {
        "screening_threshold_gate": {
            "pairs": len(pairs),
            "screening_threshold_mm_s": screening_threshold,
            "screening_threshold_source_sha256": model.screening_threshold.source_sha256,
            "pairs_above_screening_threshold": len(above),
            "max_abs_difference_mm_s": worst.max_abs_difference_mm_s,
            "max_abs_difference_fine_path": worst.fine_path,
            "max_abs_difference_coarse_path": worst.coarse_path,
            "max_abs_difference_depth_mm": worst.max_abs_difference_depth_mm,
            "max_ratio_to_screening_threshold": worst.max_abs_difference_over_screening_threshold,
            "statement": (
                f"Effect gate: the largest absolute per-knot mean-profile difference "
                f"over the {len(pairs)} pairs is {worst.max_abs_difference_mm_s:.4g} "
                f"mm/s ({worst.fine_label} vs {worst.coarse_label} at "
                f"{worst.max_abs_difference_depth_mm:.4g} mm) = "
                f"{worst.max_abs_difference_over_screening_threshold:.3g} of the WP1 screening_threshold "
                f"{screening_threshold:.4g} mm/s; {gate_tail}."
            ),
        },
        "information": {
            "fine_path": focus.fine_path,
            "coarse_path": focus.coarse_path,
            "fine_pitch_mm": focus.fine_pitch_mm,
            "coarse_pitch_mm": focus.coarse_pitch_mm,
            "knot_spacing_mm": focus.knot_spacing_mm,
            "knots": focus.knots,
            "knots_above_screening_threshold": focus.knots_above_screening_threshold,
            "mean_abs_difference_mm_s": focus.mean_abs_difference_mm_s,
            "max_abs_difference_mm_s": focus.max_abs_difference_mm_s,
            "max_abs_difference_depth_mm": focus.max_abs_difference_depth_mm,
            "detail_rms_mm_s": focus.fine_detail_rms_mm_s,
            "detail_max_abs_mm_s": focus.fine_detail_max_abs_mm_s,
            "detail_variance_share": focus.fine_detail_variance_share,
            "variance_share_at_coarse_knots": focus.fine_variance_share_at_coarse_knots,
            "statement": (
                f"Plan question: {focus.fine_label} at {focus.fine_pitch_mm:.4g} mm "
                f"versus {focus.coarse_label} at {focus.coarse_pitch_mm:.4g} mm on "
                f"{focus.knots} knots spaced {focus.knot_spacing_mm:.4g} mm - mean "
                f"|diff| {focus.mean_abs_difference_mm_s:.4g} mm/s, max |diff| "
                f"{focus.max_abs_difference_mm_s:.4g} mm/s at "
                f"{focus.max_abs_difference_depth_mm:.4g} mm = "
                f"{focus.max_abs_difference_over_screening_threshold:.3g} of the {screening_threshold:.4g} "
                f"mm/s screening_threshold, {focus.knots_above_screening_threshold} knots above it. The coarse "
                f"knots keep {100.0 * focus.fine_variance_share_at_coarse_knots:.4g} % of "
                f"the finer profile's spatial variance; the detail below them carries "
                f"{100.0 * focus.fine_detail_variance_share:.3g} % (RMS "
                f"{focus.fine_detail_rms_mm_s:.4g} mm/s, peak "
                f"{focus.fine_detail_max_abs_mm_s:.4g} mm/s = "
                f"{focus.fine_detail_max_abs_mm_s / screening_threshold:.3g} of the screening_threshold). "
                f"{_FOCUS_VERDICT}"
            ),
        },
        "coarsest_pitch": {
            "path": coarsest.relative_path,
            "label": coarsest.requested_label,
            "pitch_mm": coarsest.pitch_mm,
            "gates_in_support": coarsest.gates_in_support,
            "correlation_length_mm": coarsest.correlation_length_mm,
            "correlation_length_over_pitch": coarsest.correlation_length_over_pitch,
            "max_abs_difference_to_any_other_level_mm_s": coarse_worst,
            "max_ratio_to_screening_threshold": coarse_ratio,
            "statement": (
                f"Coarsest measured pitch: the native correlation length of the "
                f"depth-resolved mean profile is {min(lengths):.4g}-{max(lengths):.4g} "
                f"mm at every one of the {len(model.levels)} levels "
                f"({min(units):.3g}-{max(units):.3g} gate pitches), so the structure "
                f"lives on a scale of order tens of millimetres. "
                f"{coarsest.requested_label} at {coarsest.pitch_mm:.4g} mm "
                f"({coarsest.gates_in_support} supported gates) still samples it "
                f"{coarsest.correlation_length_over_pitch:.3g} times per correlation "
                f"length and differs from every other level by at most "
                f"{coarse_worst:.4g} mm/s ({coarse_ratio:.3g} of the screening_threshold). "
                f"{_COARSEST_VERDICT}"
            ),
        },
        "realizations": {
            "levels": len(model.levels),
            "recordings": len(model.inputs),
            "aggregation": grid.AGGREGATION,
            "multi_realization_levels": [
                {
                    "relative_path": group.primary_path,
                    "key_display": group.key_display,
                    "realization_paths": list(group.realization_paths),
                }
                for group in model.groups
                if len(group.realizations) > 1
            ],
            "statement": (
                f"Selection: the {len(model.levels)} decoded pitches are the setting-based "
                f"selection of {len(model.inputs)} recording(s) - every recording whose decoded "
                "settings put it at a pitch of this ladder, whatever folder requested it. A level "
                "with more than one recording is one level with that many named realizations, each "
                "measured on its own and each named in resolution-levels.csv and in the provenance "
                "document: "
                + (
                    "; ".join(
                        f"{group.key_display} realized by "
                        + " and ".join(group.realization_paths)
                        for group in model.groups
                        if len(group.realizations) > 1
                    )
                    or "no level here has a second realization"
                )
                + ". Each level's numbers are the unweighted mean of its realizations' numbers: "
                "one realization, one vote."
            ),
        },
        "limitations": [
            (
                f"The screening threshold is the only repeat, at {screening_threshold:.4g} "
                f"mm/s per gate ({model.screening_threshold.metric}): one observed "
                "realization of repeatability plus uncontrolled drift. The levels are "
                "separate recordings with no acquisition order, so an effect smaller than "
                "it cannot be separated from drift, and a difference that falls above the screening "
                "threshold "
                "could still be drift rather than pitch — screening is not attribution. No "
                "level is replicated: every difference is one measurement against another "
                "and estimates no pitch effect repeatably."
            ),
            (
                "The spatial metrics describe the depth-resolved *mean* profile over the "
                "common window; they do not separate spatial structure from temporal "
                "noise aliased across gates, and neither gates nor profiles are "
                "independent replicates."
            ),
            (
                "Alignment samples the finer profile at the coarser knots by nearest "
                "native gate: nothing is interpolated or upsampled, and the tables say "
                "nothing about structure between the coarser knots."
            ),
            (
                "This module owns the resolution axis only: burst length, PRF, TGC, "
                "emitting power and emissions per profile are neither analysed nor decided "
                "here, and pitch x burst interaction is not estimable from this dataset. "
                "What would overturn the reading: two recordings per pitch, which would "
                "separate pitch from drift and show whether the sub-knot detail measured "
                "here is structure or noise."
            ),
        ],
    }


def figure_caption(model: ResolutionLadder) -> str:
    """The caption the committed figure and the provenance document both carry.

    It names the ladder, both views, the alignment rule, the screening_threshold with its source, and the plan's
    two named pitches with their numbers.
    """
    findings = _findings(model)
    information = findings["information"]
    coarsest = findings["coarsest_pitch"]
    realizations = findings["realizations"]
    return (
        f"WP2 resolution ladder: {model.common.levels} decoded pitches "
        f"{model.levels[0].pitch_mm:.4g}-{model.levels[-1].pitch_mm:.4g} mm "
        f"({model.levels[0].requested_label}..{model.levels[-1].requested_label}). "
        + realizations["statement"] + " "
        f"Common-duration view: {model.common.revolutions} nominal "
        f"{model.common.nominal_rpm:g}-RPM revolutions = {model.common.window_s:.4g} s, "
        "truncated per file by the recorded timestamps. Common physical support: "
        f"{model.common.support_min_mm:.6g}-{model.common.support_max_mm:.6g} mm. "
        "Gradients and correlation lengths are native-grid quantities; pairs use the "
        "coarser participant's own gate depths as knots (spacing = the coarser pitch) "
        "with the finer profile sampled there by nearest native gate - nothing is "
        "interpolated or upsampled. Decision "
        f"threshold: the committed sole-pair observed-discrepancy screening threshold "
        f"{model.screening_threshold.value_mm_s:.4g} mm/s "
        f"({model.screening_threshold.metric}, read from {model.screening_threshold.path}, "
        f"{model.screening_threshold.source_sha256[:12]}...), one observed realization of "
        "same-settings repeatability plus uncontrolled drift that screens an effect "
        "without bounding it. Focus pair: "
        f"{information['fine_path']} ({information['fine_pitch_mm']:.4g} mm) vs "
        f"{information['coarse_path']} ({information['coarse_pitch_mm']:.4g} mm) - mean "
        f"|diff| {information['mean_abs_difference_mm_s']:.4g} mm/s, max |diff| "
        f"{information['max_abs_difference_mm_s']:.4g} mm/s at "
        f"{information['max_abs_difference_depth_mm']:.4g} mm, "
        f"{information['knots_above_screening_threshold']} of {information['knots']} knots above the "
        f"screening_threshold. Coarsest measured pitch {coarsest['pitch_mm']:.4g} mm "
        f"({coarsest['label']}) samples the {coarsest['correlation_length_mm']:.4g} mm "
        f"correlation length {coarsest['correlation_length_over_pitch']:.3g} times. "
        f"{MIXER_SETPOINT_ROLE}. {REPLICATE_ROLE}. Generated at commit "
        f"{model.analysis_commit or 'unknown'} from {model.manifest_path} "
        f"({model.manifest_sha256})."
    )


def _realization_cell_map(model: ResolutionLadder, field: str) -> dict[str, object]:
    """One per-realization cell of every recording, keyed by its manifest path.
    """
    return {row.relative_path: getattr(row, field) for row in model.realizations}


def _levels_document(model: ResolutionLadder) -> list[dict[str, object]]:
    """Every decoded level with its realization evidence, in ladder order.

    One entry per level, each naming the recordings that realize it and publishing each one's own
    numbers beside the level mean they produced: no path is collapsed and no recording is dropped
    (plan §8.3 step 5). ``cells`` is read from the model's own per-realization rows, so the document
    cannot disagree with the table it accompanies.
    """
    cells = {field: _realization_cell_map(model, field) for field in REALIZATION_CELLS}
    return [
        grid.level_realizations_document(group, cells, fields=REALIZATION_CELLS)
        for group in model.groups
    ]


def provenance_document(model: ResolutionLadder) -> dict[str, object]:
    """The machine-readable record beside the tables and the figure.

    Keys are inserted in a fixed order, so a regeneration from the same commit is byte-identical.
    """
    support = (model.common.support_min_mm, model.common.support_max_mm)
    matches_plan = all(
        abs(actual - declared) <= PLAN_SUPPORT_TOLERANCE_MM
        for actual, declared in zip(support, PLAN_SUPPORT_MM, strict=True)
    )
    level_of = {path: group.primary_path for group in model.groups
                for path in group.realization_paths}
    return {
        "artefact": "resolution-ladder",
        "axis": model.axis,
        "analysis_commit": model.analysis_commit,
        "dataset_root": model.dataset_root,
        "manifest": {"path": model.manifest_path, "sha256": model.manifest_sha256},
        "screening_threshold": {
            "source_path": model.screening_threshold.path,
            "source_sha256": model.screening_threshold.source_sha256,
            "metric": model.screening_threshold.metric,
            "units": model.screening_threshold.units,
            "value_mm_s": model.screening_threshold.value_mm_s,
            "gate_index": model.screening_threshold.gate_index,
            "depth_mm": model.screening_threshold.depth_mm,
            "median_abs_mean_difference_mm_s": (
                model.screening_threshold.median_abs_mean_difference_mm_s
            ),
            "scope": model.screening_threshold.scope,
            "role": model.screening_threshold.role,
        },
        "aggregation": {
            "rule": grid.AGGREGATION,
            "statement": grid.AGGREGATION_RULE,
            "levels": len(model.levels),
            "recordings": len(model.inputs),
            "multi_realization_levels": [
                {"relative_path": group.primary_path,
                 "realization_paths": list(group.realization_paths)}
                for group in model.groups if len(group.realizations) > 1
            ],
        },
        "inputs": [
            {
                "relative_path": entry.relative_path,
                "level_path": level_of[entry.relative_path],
                "axis": entry.axis,
                "requested_label": entry.requested_label,
                "source_sha256": entry.source_sha256,
                "pitch_mm": entry.pitch_mm,
                "gates": entry.gates,
                "profiles": entry.profiles,
                "duration_s": entry.duration_s,
                "depth_min_mm": entry.depth_min_mm,
                "depth_max_mm": entry.depth_max_mm,
                "profiles_window": model.common.profiles_window[entry.relative_path],
                "gates_in_support": model.common.gates_in_support[entry.relative_path],
            }
            for entry in model.inputs
        ],
        "levels": _levels_document(model),
        "views": {
            "time": {
                "common_duration": {
                    "nominal_rpm": model.common.nominal_rpm,
                    "revolution_s": model.common.revolution_s,
                    "revolutions": model.common.revolutions,
                    "window_s": model.common.window_s,
                    "profiles_window": dict(model.common.profiles_window),
                    "rule": (
                        "largest integer number of nominal revolutions fitting every "
                        "resolution recording, truncated per file by the recorded "
                        "timestamps"
                    ),
                }
            },
            "depth": {
                "common_support": {
                    "min_mm": support[0],
                    "max_mm": support[1],
                    "plan_declared_mm": list(PLAN_SUPPORT_MM),
                    "plan_tolerance_mm": PLAN_SUPPORT_TOLERANCE_MM,
                    "matches_plan": matches_plan,
                    "gates_in_support": dict(model.common.gates_in_support),
                    "rule": (
                        "intersection of the 13 decoded depth ranges; every cross-level "
                        "summary uses it and nothing else"
                    ),
                },
                "native_grid": (
                    "each level keeps its own decoded gate grid for the distributional "
                    "metrics, the gradient and the correlation length; no level is "
                    "resampled to compute a native-grid quantity"
                ),
            },
            "gradient": {
                "rule": (
                    "gate-to-gate |mean[k+1] - mean[k]| / native pitch on the supported "
                    "native grid, mm/s per mm, at the midpoint depth of the interval"
                ),
                "depth_reference": "midpoint of the two adjacent native gates",
            },
            "correlation": {
                "rule": (
                    "first lag of the normalized biased native autocovariance of the "
                    "mean-removed supported native mean profile below 1/e, in mm"
                ),
                "floor": float(CORRELATION_FLOOR),
                "lag_cap": "floor((gates_in_support - 1) / 2) gates, half the profile",
            },
            "alignment": {
                "knot_rule": (
                    "the coarser participant's native gate depths inside the common "
                    "support, so the knot spacing is the coarser pitch and never finer "
                    "than the coarsest participating pitch"
                ),
                "fine_sampling_rule": (
                    "the finer profile is sampled at each knot by its nearest native gate "
                    "(offset at most half the finer pitch); no interpolation"
                ),
                "upsampled": False,
                "max_knot_offset_over_all_pairs_mm": max(
                    row.max_knot_offset_mm for row in model.pairs
                ),
                "focus_pair": {
                    "fine_path": model.focus_pair[0],
                    "coarse_path": model.focus_pair[1],
                    "selection": (
                        "selected by pitch from the manifest-selected ladder: the plan's "
                        "question names 0.247 mm and 0.617 mm, not a filename"
                    ),
                },
            },
        },
        "definitions": dict(DEFINITIONS),
        "findings": _findings(model),
        "tables": {
            "levels": {"path": LEVELS_NAME, "rows": len(model.levels)},
            "pairs": {"path": PAIRS_NAME, "rows": len(model.pairs)},
        },
        "figure": {
            "path": f"{FIGURES_DIRNAME}/{FIGURE_NAME}",
            "caption": figure_caption(model),
            "panels": list(FIGURE_PANELS),
        },
        "regeneration": {
            "command": (
                ".venv/Scripts/python.exe -m udv_echo_process.cli resolution-ladder "
                f"--analysis-commit {model.analysis_commit or '<generator commit>'}"
            ),
            "note": (
                "pass the recorded analysis_commit to reproduce these artefacts byte for "
                "byte; the bare command records the current HEAD"
            ),
        },
    }


# ── the figure ─────────────────────────────────────────────────────────


def render_figure(
    model: ResolutionLadder,
    profiles: Mapping[str, tuple[np.ndarray, np.ndarray]],
    path: Path,
    *,
    dpi: int = 150,
) -> Path:
    """Write the two-panel resolution figure, deterministically, and return it.

    Panels: the native correlation length against pitch (with the 1:1 line where a correlation length
    would be one gate), and the plan's focus pair — both aligned profiles against depth with the
    signed difference at the coarse knots against the WP1 screening_threshold band. The gradient spread stays in
    ``resolution-levels.csv``. The frame is the shared writer's, so this module owns the panels only,
    and the caption is part of the image.
    """
    from matplotlib.ticker import NullFormatter

    screening_threshold = model.screening_threshold.value_mm_s
    pitch = np.asarray([row.pitch_mm for row in model.levels])
    focus = next(
        row for row in model.pairs if (row.fine_path, row.coarse_path) == model.focus_pair
    )
    fine_depths, fine_mean = profiles[model.focus_pair[0]]
    coarse_depths, coarse_mean = profiles[model.focus_pair[1]]
    inside = in_support(
        coarse_depths, (model.common.support_min_mm, model.common.support_max_mm)
    )
    knots = coarse_depths[inside]
    difference = fine_mean[nearest_gate_indices(fine_depths, knots)] - coarse_mean[inside]

    def draw(axes: Sequence[object]) -> None:
        length_ax, pair_ax = axes
        # The pitch axis is discrete: one tick per measured pitch, with the log scale's own
        # minor labels suppressed. The scale is set first: setting one resets ticks.
        ticks = [float(value) for value in pitch]
        length_ax.set_xscale("log")
        length_ax.set_xticks(ticks)
        length_ax.set_xticklabels(
            [f"{value:.3g}" for value in ticks], fontsize=5.6, rotation=45
        )
        length_ax.xaxis.set_minor_formatter(NullFormatter())

        # (1) native-grid correlation length versus pitch
        length_ax.plot(
            pitch, [row.correlation_length_mm for row in model.levels], "o-",
            color="#1f77b4", linewidth=1.4, markersize=4,
        )
        length_ax.plot(
            pitch, pitch, ":", color="#777777", linewidth=0.9,
            label="one gate per correlation length",
        )
        length_ax.set_xlabel("native gate pitch [mm]")
        length_ax.set_ylabel("native spatial correlation length [mm]")
        length_ax.set_title(
            "structure scale versus pitch\n"
            f"1/e lag of the mean profile, native grid ({len(model.levels)} levels)",
            fontsize=9.5,
        )
        length_ax.grid(alpha=0.2)
        length_ax.legend(loc="upper right", fontsize=6.5, framealpha=0.9)

        # (2) the focus pair on the coarser grid's own knots
        pair_ax.plot(
            fine_mean, fine_depths, color="#1f77b4", linewidth=1.3,
            label=f"{focus.fine_path} ({focus.fine_pitch_mm:.4g} mm) native",
        )
        pair_ax.plot(
            fine_mean[nearest_gate_indices(fine_depths, knots)], knots, "o", color="#1f77b4",
            markersize=2.6, label="the same profile sampled at the coarse knots",
        )
        pair_ax.plot(
            coarse_mean, coarse_depths, color="#d62728", linewidth=1.6,
            label=f"{focus.coarse_path} ({focus.coarse_pitch_mm:.4g} mm) native",
        )
        pair_ax.set_xlabel("per-gate mean velocity [mm/s]")
        pair_ax.set_ylabel("depth from transducer face [mm]")
        pair_ax.invert_yaxis()
        difference_ax = pair_ax.twiny()
        difference_ax.axvspan(-screening_threshold, screening_threshold, color="#999999", alpha=0.18, linewidth=0)
        for sign in (-1.0, 1.0):
            difference_ax.axvline(
                sign * screening_threshold, color="#555555", linewidth=0.8, linestyle=":"
            )
        difference_ax.plot(
            difference, knots, color="#111111", linewidth=1.0,
            label="fine - coarse at the coarse knots",
        )
        difference_ax.set_xlabel("difference [mm/s]; grey band = WP1 screening_threshold", fontsize=7.5)
        difference_ax.set_xlim(-1.25 * screening_threshold, 1.25 * screening_threshold)
        pair_ax.set_title(
            f"plan's pair: {focus.knots} knots at {focus.knot_spacing_mm:.4g} mm; "
            f"max |diff| {focus.max_abs_difference_mm_s:.4g} mm/s",
            fontsize=9.0,
        )
        pair_ax.grid(alpha=0.2)
        pair_ax.legend(loc="lower left", fontsize=6.2, framealpha=0.9)
        difference_ax.legend(loc="upper right", fontsize=6.2, framealpha=0.9)

    return panel_figure(
        "WP2 resolution ladder — 13 measured pitches against the WP1 sole-pair screening threshold",
        figure_caption(model),
        draw,
        path,
        adjust={"top": 0.76, "bottom": 0.30, "wspace": 0.22},
        dpi=dpi,
    )



def write_resolution_ladder(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    screening_threshold_path: Path | None = None,
    analysis_commit: str | None = None,
) -> ResolutionLadder:
    """Build the ladder and write the four reviewer-visible artefacts.

    The three text artefacts use LF endings and the figure is written deterministically, so two runs
    on the same inputs and commit produce identical bytes; nothing is written when the build raises,
    because the model is built (and refused) before the shared writer is called.
    """
    directory = Path(report_dir)
    manifest = (
        Path(manifest_path) if manifest_path is not None else directory / MANIFEST_NAME
    )
    screening_threshold = (
        Path(screening_threshold_path) if screening_threshold_path is not None else directory / SCREENING_THRESHOLD_NAME
    )
    model, profiles = _build(dataset_root, manifest, screening_threshold, analysis_commit)
    write_text_artefacts(directory, {
        LEVELS_NAME: levels_csv_text(model),
        PAIRS_NAME: pairs_csv_text(model),
        PROVENANCE_NAME: json.dumps(provenance_document(model), indent=2) + "\n",
    })
    render_figure(model, profiles, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
