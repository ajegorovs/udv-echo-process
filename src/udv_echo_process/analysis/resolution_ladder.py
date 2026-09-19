"""WP2, resolution axis — the measured pitch ladder against the repeatability bound.

The committed sweep holds a 13-point resolution ladder: one base-state recording per
gate pitch, 0.247 mm (`res/0-2.BDD`, 365 gates) to 2.96 mm (`res/3-0.BDD`, 31 gates),
over the same ~100 mm window (plan §2). This module answers the plan's question —
*does 0.247 mm add information over 0.617 mm, and how coarse can a measured pitch go
before structure is lost* — from the ``res`` rows of the WP0 manifest, never a
filename list (plan §4 WP2 gate). What it computes:

- **Common-duration view** — the largest integer number of nominal 500-RPM
  revolutions (0.12 s) fitting *every* resolution recording: 93 revolutions =
  11.16 s, truncated per file by the recorded timestamps (plan §3.1).
- **Common physical support** — the intersection of the 13 decoded depth ranges,
  10.1626666667-96.7426666667 mm, for every cross-level summary (plan §3.2).
- **Level metrics on each native grid** — mean, robust spread (IQR), RMS about
  zero, zero fraction and gate-level temporal IQR over the common window, plus two
  spatial metrics computed *before* any comparison: the gate-to-gate gradient
  (|Δmean| / native pitch, at the interval midpoint) and the spatial correlation
  length (first native lag whose normalized autocovariance drops below 1/e).
- **Pairs on common knots** — every unordered level pair on the *coarser*
  participant's native gate depths inside the support, so knot spacing is never
  finer than the coarsest participating pitch. The finer level is *sampled* there
  by nearest native gate: no interpolation, no upsampling, no claim about
  structure between knots.
- **Effect versus the envelope** — the committed WP1 repeatability envelope
  (19.37 mm/s, read from ``reference-repeat.provenance.json`` and bound to this
  manifest) is the threshold: each pair reports the knots that clear it, where in
  depth, and by what ratio (plan §4 WP1 gate).
- **Detail below the coarse knots** — measured inside the finer recording alone, so
  no drift enters it: its native mean profile minus that same profile sampled at the
  coarse knots. That is the spatial variance a finer pitch adds here.

Gates and profiles are not independent replicates, the levels carry no acquisition
order (their differences hold drift as well as pitch), and no p-value family is
produced (plan §3.3). Resolution axis only: burst, PRF, TGC/power and emissions are
out of scope, and 500 RPM is a marker (8.33 Hz), never a phase reference.

Most of the machinery is *shared*, not duplicated: the common views, the native-grid
spatial metrics, the pairwise alignment, the WP1 envelope binding and the artefact
writers live in ``_native_grid.py``, which the burst, PRF and TGC/power axes of the
same plan reuse. WP1's temporal models (per-gate autocorrelation/PSD on a second time
base) have no counterpart here: this axis compares pitch, not time.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._native_grid import (
    CORRELATION_FLOOR,
    GRID_UNIFORMITY_RTOL,
    TOLERANCE_S,
    EnvelopeBinding,
    NativeGridError,
    common_support,
    correlation_length,
    csv_text,
    depth_ranges,
    in_support,
    nearest_gate_indices,
    read_envelope,
    sha256_file,
    spatial_gradient,
    window,
    wrap_caption,
)
from udv_echo_process.analysis.reference_repeat import (
    NOMINAL_REVOLUTION_S,
    NOMINAL_RPM,
    common_revolution_count,
    gate_metrics,
)
from udv_echo_process.analysis.sweep_inventory import (
    DATASET_ROOT,
    MANIFEST_NAME,
    REPORT_DIR,
    format_cell,
)
from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: The manifest axis this module owns, and the reviewer-visible artefacts.
AXIS = "res"
LEVELS_NAME = "resolution-levels.csv"
PAIRS_NAME = "resolution-pairs.csv"
PROVENANCE_NAME = "resolution-ladder.provenance.json"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "resolution-ladder.png"

#: The committed WP1 artefact the decision threshold is read from.
ENVELOPE_NAME = "reference-repeat.provenance.json"

#: The two pitches the plan's question names (0.247 mm, 0.617 mm): the focus pair
#: is selected by *pitch* from the manifest, in the same way every row is.
FOCUS_PITCHES_MM: tuple[float, float] = (0.246666666667, 0.616666666667)
FOCUS_PITCH_RTOL = 1e-6

#: The plan's stated common physical support, with the tolerance its wording allows.
PLAN_SUPPORT_MM: tuple[float, float] = (10.163, 96.743)
PLAN_SUPPORT_TOLERANCE_MM = 0.01

#: Column order of ``resolution-levels.csv``; the field order of :class:`LevelRow` is
#: the same tuple, so the table and the model cannot drift apart.
LEVEL_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "pitch_mm", "gates", "duration_s",
    "profiles", "profiles_window", "gates_in_support", "depth_min_mm",
    "depth_max_mm", "support_min_mm", "support_max_mm", "mean_mm_s",
    "robust_spread_mm_s", "rms_mm_s", "zero_fraction", "time_iqr_median_mm_s",
    "gradient_median_abs_mm_s_per_mm", "gradient_max_abs_mm_s_per_mm",
    "gradient_max_depth_mm", "correlation_length_mm", "correlation_lag_max_mm",
    "correlation_reaches_floor", "correlation_length_over_pitch",
)

#: Column order of ``resolution-pairs.csv``; one row per unordered level pair.
PAIR_COLUMNS: tuple[str, ...] = (
    "axis", "fine_path", "fine_label", "fine_pitch_mm", "coarse_path",
    "coarse_label", "coarse_pitch_mm", "knot_spacing_mm", "knots",
    "support_min_mm", "support_max_mm", "max_knot_offset_mm",
    "mean_abs_difference_mm_s", "median_abs_difference_mm_s",
    "max_abs_difference_mm_s", "max_abs_difference_depth_mm",
    "knots_above_envelope", "fraction_above_envelope",
    "max_abs_difference_over_envelope", "depth_ranges_above_envelope_mm",
    "fine_variance_share_at_coarse_knots", "fine_detail_rms_mm_s",
    "fine_detail_max_abs_mm_s", "fine_detail_variance_share",
)


#: The error class of every message this module raises. The native-grid helpers of
#: :mod:`udv_echo_process.analysis._native_grid` raise the same class, so a caller
#: catches a helper refusal and an axis refusal under one name.
ResolutionLadderError = NativeGridError


# ── models ─────────────────────────────────────────────────────────────


class LevelInput(ValueModel):
    """One resolution level, as decoded and bound to its manifest row."""

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
    """One row of ``resolution-levels.csv``: a level on its own native grid."""

    axis: str
    relative_path: str
    requested_label: str
    pitch_mm: float
    gates: int
    duration_s: float
    profiles: int
    profiles_window: int
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
    knots_above_envelope: int
    fraction_above_envelope: float
    max_abs_difference_over_envelope: float
    depth_ranges_above_envelope_mm: str
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
        if self.knots < 2 or self.knots_above_envelope > self.knots:
            raise ValueError(
                f"{self.knots} knots cannot carry {self.knots_above_envelope} "
                "above-envelope flags; a pair needs at least two knots"
            )
        return self


class ResolutionLadder(ValueModel):
    """The WP2 resolution result: the levels, the two views and every pair."""

    dataset_root: str
    manifest_path: str
    manifest_sha256: str
    envelope: EnvelopeBinding
    axis: str = AXIS
    analysis_commit: str | None = None
    inputs: tuple[LevelInput, ...]
    common: CommonView
    focus_pair: tuple[str, str]
    levels: tuple[LevelRow, ...]
    pairs: tuple[PairRow, ...]

    @model_validator(mode="after")
    def _check_the_ladder_is_internally_consistent(self) -> ResolutionLadder:
        paths = [row.relative_path for row in self.levels]
        if len(set(paths)) != len(paths) or paths != [
            entry.relative_path for entry in self.inputs
        ]:
            raise ValueError("every level must appear exactly once, in input order")
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
        if self.envelope.value_mm_s <= 0.0:
            raise ValueError("the repeatability envelope must be positive")
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


def select_level_rows(manifest_path: Path) -> tuple[dict[str, str], ...]:
    """Return every ``res`` manifest row, ordered by pitch and then by path.

    The ladder is bound to the WP0 manifest rather than to a hand-maintained
    filename list: the files compared are the ones the inventory decoded, and each
    row's ``source_sha256`` is the content identity :func:`_read_level` re-checks
    against the bytes.

    Raises:
        ResolutionLadderError: when the manifest is missing or unreadable, holds no
            ``res`` rows, repeats a relative path, carries a row that did not
            decode, gives a row no usable pitch, or gives two rows one pitch.
    """
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResolutionLadderError(f"cannot read the manifest {path}: {exc}") from exc
    selected = [
        row
        for row in csv.DictReader(text.splitlines())
        if (row.get("axis") or "") == AXIS
    ]
    if not selected:
        raise ResolutionLadderError(
            f"manifest {path} holds no res rows; the resolution ladder is selected "
            "from the WP0 inventory, never from a filename list"
        )
    counts: dict[str, int] = {}
    for row in selected:
        relative = (row.get("relative_path") or "").strip()
        if not relative:
            raise ResolutionLadderError(
                f"manifest {path} holds a res row without a relative_path"
            )
        counts[relative] = counts.get(relative, 0) + 1
    for relative, count in counts.items():
        if count != 1:
            raise ResolutionLadderError(
                f"manifest {path} must hold exactly one row for {relative}, found "
                f"{count}"
            )
    for row in selected:
        if row.get("decode_error"):
            raise ResolutionLadderError(
                f"{row['relative_path']}: the manifest records "
                f"decode_error={row['decode_error']!r}; a ladder must be selected "
                "from decoded recordings"
            )
        _row_pitch(row, path)
    ordered = sorted(
        selected, key=lambda row: (_row_pitch(row, path), row["relative_path"])
    )
    for first, second in itertools.pairwise(ordered):
        if _row_pitch(first, path) == _row_pitch(second, path):
            raise ResolutionLadderError(
                f"{first['relative_path']} and {second['relative_path']} carry the "
                f"same pitch {_row_pitch(first, path):g} mm; a ladder needs one row "
                "per pitch"
            )
    return tuple(ordered)


_VERIFIED_CELLS: tuple[tuple[str, str], ...] = (
    ("profiles", "profiles"),
    ("gates", "gates"),
    ("duration_s", "duration_s"),
    ("depth_min_mm", "depth_min_mm"),
    ("depth_max_mm", "depth_max_mm"),
    ("resolution_mm", "resolution_mm"),
    ("prf_period_us", "prf_period_us"),
    ("burst_length", "burst_length"),
    ("emissions_per_profile", "emissions_per_profile"),
    ("emit_power", "emit_power"),
    ("sensitivity", "sensitivity"),
    ("tgc_mode", "tgc_mode"),
)


def _read_level(
    dataset_root: Path, row: dict[str, str]
) -> tuple[LevelInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected level and bind it to its manifest row.

    Returns ``(entry, values, time_s, gate_depths_mm)`` — the manifest record and
    the ``(profiles, gates)`` velocity array in ``mm/s`` with its two axes.

    Raises:
        ResolutionLadderError: for a row with no usable path, bytes that do not
            reproduce the recorded SHA-256, a payload that is not one axial-velocity
            channel, a gate grid that is not the instrument's uniform increasing grid,
            or a re-checked cell that disagrees with the decoded value (a stale
            inventory must not be analysed).
    """
    relative = row.get("relative_path") or ""
    path = dataset_root / relative
    if not relative or not path.is_file():
        raise ResolutionLadderError(f"manifest row {relative!r} is not a file at {path}")
    recorded = (row.get("source_sha256") or "").strip()
    actual = sha256_file(path)
    if recorded != actual:
        raise ResolutionLadderError(
            f"source sha256 mismatch for {relative}: manifest records {recorded!r}, "
            f"file hashes to {actual!r}"
        )
    recording = load(path).recording
    if recording.source_asset.content_sha256 != actual:
        raise ResolutionLadderError(
            f"{relative}: the reader's content hash "
            f"{recording.source_asset.content_sha256!r} is not the file hash {actual!r}"
        )
    if len(recording.streams) != 1:
        raise ResolutionLadderError(
            f"{relative}: expected exactly one channel stream, found "
            f"{len(recording.streams)}"
        )
    stream = recording.streams[0]
    values = np.asarray(stream.data.values, dtype=float)
    time_s = np.asarray(stream.data.time_s, dtype=float)
    depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
    if stream.descriptor.unit != "mm/s" or values.ndim != 2:
        raise ResolutionLadderError(
            f"{relative}: expected a 2-D axial-velocity array in mm/s, got "
            f"{values.ndim}-D in {stream.descriptor.unit!r}"
        )
    if np.count_nonzero(np.isnan(values)):
        raise ResolutionLadderError(f"{relative}: the velocity array carries NaNs")
    config = stream.config
    observed = {
        "profiles": format_cell(int(values.shape[0])),
        "gates": format_cell(int(values.shape[1])),
        "duration_s": format_cell(float(time_s[-1] - time_s[0])),
        "depth_min_mm": format_cell(float(depths[0])),
        "depth_max_mm": format_cell(float(np.max(depths))),
        "resolution_mm": format_cell(config.resolution_mm),
        "prf_period_us": format_cell(1e6 / float(config.pulse_repetition_freq_hz)),
        "burst_length": format_cell(config.burst_length),
        "emissions_per_profile": format_cell(config.emissions_per_profile),
        "emit_power": format_cell(config.emit_power),
        "sensitivity": format_cell(config.sensitivity),
        "tgc_mode": format_cell(config.tgc_mode),
    }
    for cell, key in _VERIFIED_CELLS:
        if (row.get(cell) or "") != observed[key]:
            raise ResolutionLadderError(
                f"{relative}: manifest {cell}={row.get(cell)!r} does not match the "
                f"decoded {key}={observed[key]!r}; the comparison must not run on a "
                "stale inventory"
            )
    if depths.size < 2:
        raise ResolutionLadderError(
            f"{relative}: the gate grid holds {depths.size} gate(s)"
        )
    steps = np.diff(depths)
    pitch = float(steps.mean())
    if not np.all(steps > 0.0) or not math.isfinite(pitch) or pitch <= 0.0:
        raise ResolutionLadderError(
            f"{relative}: the native gate depths must increase strictly, got steps "
            f"including {steps.min()!r}"
        )
    deviation = float(np.abs(steps - pitch).max())
    if deviation > GRID_UNIFORMITY_RTOL * pitch:
        raise ResolutionLadderError(
            f"{relative}: the native gate grid is not uniform: steps deviate by "
            f"{deviation:.3g} mm from the {pitch:g} mm mean pitch"
        )
    if not math.isclose(pitch, float(config.resolution_mm), rel_tol=1e-6):
        raise ResolutionLadderError(
            f"{relative}: the decoded gate pitch {pitch!r} is not the manifest's "
            f"resolution_mm {config.resolution_mm!r}"
        )
    return (
        LevelInput(
            relative_path=relative,
            axis=row.get("axis") or "",
            requested_label=row.get("requested_label") or "",
            source_sha256=actual,
            pitch_mm=pitch,
            gates=int(values.shape[1]),
            profiles=int(values.shape[0]),
            duration_s=float(time_s[-1] - time_s[0]),
            depth_min_mm=float(depths[0]),
            depth_max_mm=float(np.max(depths)),
        ),
        values,
        time_s,
        depths,
    )


# ── the two common views and the pure spatial helpers ──────────────────


def level_row(
    entry: LevelInput,
    values: np.ndarray,
    time_s: np.ndarray,
    depths: np.ndarray,
    *,
    window_s: float,
    support: tuple[float, float],
) -> LevelRow:
    """One level's row: the common-duration window on its own native grid.

    Every distributional metric uses the common window and only the gates inside
    the common support; both spatial metrics use that supported native grid.

    Raises:
        ResolutionLadderError: when fewer than two gates fall inside the common
            support, so the level's spatial metrics are undefined.
    """
    view = window(values, time_s, window_s)
    mask = in_support(depths, support)
    supported_gates = int(np.count_nonzero(mask))
    if supported_gates < 2:
        raise ResolutionLadderError(
            f"{entry.relative_path}: {supported_gates} gate(s) fall inside the common "
            f"support [{support[0]:g}, {support[1]:g}] mm; the spatial metrics need two"
        )
    per_gate = gate_metrics(view)
    means = per_gate["mean"][mask]
    supported = view[:, mask]
    gradient = spatial_gradient(depths[mask], means)
    correlation = correlation_length(depths[mask], means)
    return LevelRow(
        axis=entry.axis,
        relative_path=entry.relative_path,
        requested_label=entry.requested_label,
        pitch_mm=entry.pitch_mm,
        gates=entry.gates,
        duration_s=entry.duration_s,
        profiles=entry.profiles,
        profiles_window=int(view.shape[0]),
        gates_in_support=supported_gates,
        depth_min_mm=entry.depth_min_mm,
        depth_max_mm=entry.depth_max_mm,
        support_min_mm=support[0],
        support_max_mm=support[1],
        mean_mm_s=float(means.mean()),
        robust_spread_mm_s=float(
            np.percentile(means, 75.0) - np.percentile(means, 25.0)
        ),
        rms_mm_s=float(np.sqrt(np.mean(np.square(supported)))),
        zero_fraction=float(np.count_nonzero(supported == 0.0) / supported.size),
        time_iqr_median_mm_s=float(np.median(per_gate["iqr"][mask])),
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
    envelope: EnvelopeBinding,
) -> PairRow:
    """Compare a fine level with a coarse one on the coarser grid's own knots.

    The knots are the coarse participant's native gate depths inside the common
    support, so their spacing is the coarser pitch, never finer than the coarsest
    participating pitch (plan §3.2). The fine profile is sampled there by the shared
    :func:`nearest_gate_indices` — the nearest native gate's value, no interpolation —
    and the difference is the signed ``fine − coarse`` per-gate time mean in mm/s.

    The ``fine_detail_*`` fields are measured inside the *finer recording alone*: its
    supported native mean profile minus that same profile sampled at the coarse knots.
    No second recording enters them, so they carry no drift, and they bound how much
    spatial variance the finer pitch adds below the coarse knot spacing.

    Raises:
        ResolutionLadderError: when the arguments are not (fine, coarse), the coarser
            participant carries fewer than two knots in the support, or the finer
            profile has no spatial variance.
    """
    if fine.pitch_mm >= coarse.pitch_mm:
        raise ResolutionLadderError(
            f"a pair is (fine, coarse): {fine.relative_path} at {fine.pitch_mm:g} mm "
            f"is not finer than {coarse.relative_path} at {coarse.pitch_mm:g} mm"
        )
    fine_depths = np.asarray(fine_depths_mm, dtype=float)
    coarse_depths = np.asarray(coarse_depths_mm, dtype=float)
    coarse_mask = in_support(coarse_depths, support)
    knots = coarse_depths[coarse_mask]
    if knots.size < 2:
        raise ResolutionLadderError(
            f"{coarse.relative_path}: {knots.size} knot(s) fall inside the common "
            f"support [{support[0]:g}, {support[1]:g}] mm; a pair needs two"
        )
    fine_mean = np.asarray(fine_mean_mm_s, dtype=float)
    indices = nearest_gate_indices(fine_depths, knots)
    fine_at_knots = fine_mean[indices]
    difference = fine_at_knots - np.asarray(coarse_mean_mm_s, dtype=float)[coarse_mask]
    absolute = np.abs(difference)
    flagged = absolute > envelope.value_mm_s
    worst = int(np.argmax(absolute))
    fine_mask = in_support(fine_depths, support)
    native = fine_mean[fine_mask]
    native_variance = float(np.var(native))
    if native_variance == 0.0:
        raise ResolutionLadderError(
            f"{fine.relative_path}: the supported mean profile is constant, so the "
            "detail below the coarse knots is undefined"
        )
    mapped = fine_at_knots[nearest_gate_indices(knots, fine_depths[fine_mask])]
    detail = native - mapped
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
        max_knot_offset_mm=float(np.abs(fine_depths[indices] - knots).max()),
        mean_abs_difference_mm_s=float(absolute.mean()),
        median_abs_difference_mm_s=float(np.median(absolute)),
        max_abs_difference_mm_s=float(absolute[worst]),
        max_abs_difference_depth_mm=float(knots[worst]),
        knots_above_envelope=int(np.count_nonzero(flagged)),
        fraction_above_envelope=float(np.count_nonzero(flagged) / flagged.size),
        max_abs_difference_over_envelope=float(absolute[worst] / envelope.value_mm_s),
        depth_ranges_above_envelope_mm=depth_ranges(knots, flagged),
        fine_variance_share_at_coarse_knots=float(
            np.var(fine_at_knots) / native_variance
        ),
        fine_detail_rms_mm_s=float(np.sqrt(np.mean(np.square(detail)))),
        fine_detail_max_abs_mm_s=float(np.abs(detail).max()),
        fine_detail_variance_share=float(np.var(detail) / native_variance),
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


def _build(
    dataset_root: Path,
    manifest_path: Path,
    envelope_path: Path,
    analysis_commit: str | None,
) -> tuple[ResolutionLadder, dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Build the ladder and return it beside each level's native mean profile."""
    rows = select_level_rows(manifest_path)
    manifest_sha256 = f"sha256:{sha256_file(Path(manifest_path))}"
    envelope = read_envelope(Path(envelope_path), manifest_sha256)
    root = Path(dataset_root)
    decoded = [_read_level(root, row) for row in rows]
    revolutions = common_revolution_count([entry.duration_s for entry, *_ in decoded])
    window_s = revolutions * NOMINAL_REVOLUTION_S
    support = common_support(
        [(entry.depth_min_mm, entry.depth_max_mm) for entry, *_ in decoded]
    )
    levels = tuple(
        level_row(entry, values, time_s, depths, window_s=window_s, support=support)
        for entry, values, time_s, depths in decoded
    )
    profiles = {
        entry.relative_path: (
            depths,
            gate_metrics(window(values, time_s, window_s))["mean"],
        )
        for entry, values, time_s, depths in decoded
    }
    pairs = tuple(
        pair_row(
            fine,
            profiles[fine.relative_path][1],
            profiles[fine.relative_path][0],
            coarse,
            profiles[coarse.relative_path][1],
            profiles[coarse.relative_path][0],
            support=support,
            envelope=envelope,
        )
        for (fine, *_), (coarse, *_) in itertools.combinations(decoded, 2)
    )
    commit = analysis_commit if analysis_commit is not None else current_revision()
    model = ResolutionLadder(
        dataset_root=root.as_posix(),
        manifest_path=Path(manifest_path).as_posix(),
        manifest_sha256=manifest_sha256,
        envelope=envelope,
        analysis_commit=commit,
        inputs=tuple(entry for entry, *_ in decoded),
        common=CommonView(
            nominal_rpm=NOMINAL_RPM,
            revolution_s=NOMINAL_REVOLUTION_S,
            revolutions=revolutions,
            window_s=window_s,
            profiles_window={
                entry.relative_path: int(
                    np.count_nonzero(time_s <= time_s[0] + window_s + TOLERANCE_S)
                )
                for entry, _values, time_s, _depths in decoded
            },
            gates_in_support={
                entry.relative_path: int(np.count_nonzero(in_support(depths, support)))
                for entry, _values, _time_s, depths in decoded
            },
            support_min_mm=support[0],
            support_max_mm=support[1],
            levels=len(levels),
        ),
        focus_pair=_focus_pair(levels),
        levels=levels,
        pairs=pairs,
    )
    return model, profiles


def build_resolution_ladder(
    dataset_root: Path = DATASET_ROOT,
    manifest_path: Path = REPORT_DIR / MANIFEST_NAME,
    envelope_path: Path = REPORT_DIR / ENVELOPE_NAME,
    *,
    analysis_commit: str | None = None,
) -> ResolutionLadder:
    """Build the WP2 resolution ladder from the manifest-selected recordings.

    Args:
        dataset_root: root holding the ``<axis>/<label>.BDD`` points.
        manifest_path: the WP0 manifest the ladder is selected from and re-checked
            against.
        envelope_path: the committed WP1 provenance the threshold is read from.
        analysis_commit: revision to record; ``None`` probes the checkout's short git
            SHA once (never blocking), and passing it reproduces a committed
            artefact.

    Returns:
        The levels, the two common views, the focus pair and every pair row.

    Raises:
        ResolutionLadderError: for a manifest that is missing, unreadable, empty of
            ``res`` rows, duplicated, undecodable or stale; for a WP1 envelope that is
            missing or bound to another manifest; and for any recording whose settings
            or grid contradict its manifest row.
    """
    return _build(
        dataset_root, Path(manifest_path), Path(envelope_path), analysis_commit
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
    "envelope": (
        "the committed WP1 repeatability envelope, max_gate_abs_mean_difference_mm_s, "
        "read from reference-repeat.provenance.json and bound to this manifest's hash: "
        "an upper bound on repeatability *plus* uncontrolled drift, not a repeatability "
        "estimate, and the threshold of every effect here"
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
    "repeat-plus-drift envelope, so this evidence cannot support that claim; it "
    "equally cannot exclude a real effect smaller than the bound, which one "
    "same-settings repeat cannot resolve."
)
_COARSEST_VERDICT = (
    "On this evidence the coarsest *measured* pitch preserves the structure the finer "
    "pitches show, and no measured pitch is shown to lose it - a statement about the "
    "13 recorded pitches only: nothing finer or coarser was measured, and a resolution "
    "effect smaller than the drift-inclusive envelope would be invisible here."
)

#: Panels of the reviewer-visible figure.
FIGURE_PANELS: tuple[str, ...] = (
    (
        "native-grid spatial correlation length versus gate pitch, with the 1:1 line "
        "where a correlation length would equal one gate"
    ),
    (
        "the plan's 0.247 mm vs 0.617 mm pair: both aligned profiles versus depth, the "
        "signed difference at the 0.617 mm knots and the WP1 envelope band; the native "
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


def regeneration_command(model: ResolutionLadder) -> str:
    """The exact command that reproduces the committed artefacts byte for byte."""
    return (
        ".venv/Scripts/python.exe -m udv_echo_process.cli resolution-ladder "
        f"--analysis-commit {model.analysis_commit or '<generator commit>'}"
    )


def _findings(model: ResolutionLadder) -> dict[str, object]:
    """The plan's questions answered from the numbers the tables already carry.

    Every statement is composed from those values, so a regeneration says what it
    wrote. Nothing here is a p-value or a significance claim, and nothing here
    decides an axis this module does not own.
    """
    envelope = model.envelope.value_mm_s
    pairs = model.pairs
    above = [row for row in pairs if row.knots_above_envelope]
    worst = max(pairs, key=lambda row: row.max_abs_difference_mm_s)
    focus = next(
        row for row in pairs if (row.fine_path, row.coarse_path) == model.focus_pair
    )
    lengths = [row.correlation_length_mm for row in model.levels]
    units = [row.correlation_length_over_pitch for row in model.levels]
    coarsest = model.levels[-1]

    coarse_pairs = [row for row in pairs if row.coarse_path == coarsest.relative_path]
    coarse_worst = max(row.max_abs_difference_mm_s for row in coarse_pairs)
    coarse_ratio = max(row.max_abs_difference_over_envelope for row in coarse_pairs)
    gate_tail = (
        f"{len(above)} of {len(pairs)} pairs put a knot above the envelope, named with "
        "their depth ranges in resolution-pairs.csv"
        if above
        else (
            f"not one of the {len(pairs)} pairs puts a knot above the envelope, so no "
            "level differs from another by more than repeat-plus-drift anywhere in the "
            "common support"
        )
    )
    return {
        "envelope_gate": {
            "pairs": len(pairs),
            "envelope_mm_s": envelope,
            "envelope_source_sha256": model.envelope.source_sha256,
            "pairs_above_envelope": len(above),
            "max_abs_difference_mm_s": worst.max_abs_difference_mm_s,
            "max_abs_difference_fine_path": worst.fine_path,
            "max_abs_difference_coarse_path": worst.coarse_path,
            "max_abs_difference_depth_mm": worst.max_abs_difference_depth_mm,
            "max_ratio_to_envelope": worst.max_abs_difference_over_envelope,
            "statement": (
                f"Effect gate: the largest absolute per-knot mean-profile difference "
                f"over the {len(pairs)} pairs is {worst.max_abs_difference_mm_s:.4g} "
                f"mm/s ({worst.fine_label} vs {worst.coarse_label} at "
                f"{worst.max_abs_difference_depth_mm:.4g} mm) = "
                f"{worst.max_abs_difference_over_envelope:.3g} of the WP1 envelope "
                f"{envelope:.4g} mm/s; {gate_tail}."
            ),
        },
        "information": {
            "fine_path": focus.fine_path,
            "coarse_path": focus.coarse_path,
            "fine_pitch_mm": focus.fine_pitch_mm,
            "coarse_pitch_mm": focus.coarse_pitch_mm,
            "knot_spacing_mm": focus.knot_spacing_mm,
            "knots": focus.knots,
            "knots_above_envelope": focus.knots_above_envelope,
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
                f"{focus.max_abs_difference_over_envelope:.3g} of the {envelope:.4g} "
                f"mm/s envelope, {focus.knots_above_envelope} knots above it. The coarse "
                f"knots keep {100.0 * focus.fine_variance_share_at_coarse_knots:.4g} % of "
                f"the finer profile's spatial variance; the detail below them carries "
                f"{100.0 * focus.fine_detail_variance_share:.3g} % (RMS "
                f"{focus.fine_detail_rms_mm_s:.4g} mm/s, peak "
                f"{focus.fine_detail_max_abs_mm_s:.4g} mm/s = "
                f"{focus.fine_detail_max_abs_mm_s / envelope:.3g} of the envelope). "
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
            "max_ratio_to_envelope": coarse_ratio,
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
                f"{coarse_worst:.4g} mm/s ({coarse_ratio:.3g} of the envelope). "
                f"{_COARSEST_VERDICT}"
            ),
        },
        "limitations": [
            (
                f"The only repeat bounds repeatability plus uncontrolled drift "
                f"({envelope:.4g} mm/s per gate, {model.envelope.metric}). The levels are "
                "separate recordings with no acquisition order, so an effect smaller than "
                "that bound cannot be separated from drift, and a difference that clears "
                "it could still be drift rather than pitch. No level is replicated: every "
                "difference is one measurement against another and estimates no pitch "
                "effect repeatably."
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

    It names the ladder, both views, the alignment rule, the envelope and its source,
    the focus pair's numbers and the two caveats: the setpoint is not a phase
    reference, and nothing here is an independent replicate.
    """
    findings = _findings(model)
    information = findings["information"]
    coarsest = findings["coarsest_pitch"]
    return (
        f"WP2 resolution ladder: {model.common.levels} decoded pitches "
        f"{model.levels[0].pitch_mm:.4g}-{model.levels[-1].pitch_mm:.4g} mm "
        f"({model.levels[0].requested_label}..{model.levels[-1].requested_label}). "
        f"Common-duration view: {model.common.revolutions} nominal "
        f"{model.common.nominal_rpm:g}-RPM revolutions = {model.common.window_s:.4g} s, "
        "truncated per file by the recorded timestamps. Common physical support: "
        f"{model.common.support_min_mm:.6g}-{model.common.support_max_mm:.6g} mm. "
        "Gradients and correlation lengths are native-grid quantities; pairs use the "
        "coarser participant's own gate depths as knots (spacing = the coarser pitch) "
        "with the finer profile sampled there by nearest native gate - nothing is "
        "interpolated or upsampled. Decision "
        f"threshold: the committed WP1 envelope {model.envelope.value_mm_s:.4g} mm/s "
        f"({model.envelope.metric}, read from {model.envelope.path}, "
        f"{model.envelope.source_sha256[:12]}...), an upper bound on same-settings "
        "repeatability plus uncontrolled drift. Focus pair: "
        f"{information['fine_path']} ({information['fine_pitch_mm']:.4g} mm) vs "
        f"{information['coarse_path']} ({information['coarse_pitch_mm']:.4g} mm) - mean "
        f"|diff| {information['mean_abs_difference_mm_s']:.4g} mm/s, max |diff| "
        f"{information['max_abs_difference_mm_s']:.4g} mm/s at "
        f"{information['max_abs_difference_depth_mm']:.4g} mm, "
        f"{information['knots_above_envelope']} of {information['knots']} knots above the "
        f"envelope. Coarsest measured pitch {coarsest['pitch_mm']:.4g} mm "
        f"({coarsest['label']}) samples the {coarsest['correlation_length_mm']:.4g} mm "
        f"correlation length {coarsest['correlation_length_over_pitch']:.3g} times. "
        f"{MIXER_SETPOINT_ROLE}. {REPLICATE_ROLE}. Generated at commit "
        f"{model.analysis_commit or 'unknown'} from {model.manifest_path} "
        f"({model.manifest_sha256})."
    )


def provenance_document(model: ResolutionLadder) -> dict[str, object]:
    """The machine-readable record beside the tables and the figure.

    Keys are inserted in a fixed order and floats keep Python's shortest round-trip
    representation, so a regeneration from the same commit is byte-identical.
    """
    support = (model.common.support_min_mm, model.common.support_max_mm)
    matches_plan = all(
        abs(actual - declared) <= PLAN_SUPPORT_TOLERANCE_MM
        for actual, declared in zip(support, PLAN_SUPPORT_MM, strict=True)
    )
    return {
        "artefact": "resolution-ladder",
        "axis": model.axis,
        "analysis_commit": model.analysis_commit,
        "dataset_root": model.dataset_root,
        "manifest": {"path": model.manifest_path, "sha256": model.manifest_sha256},
        "envelope": {
            "source_path": model.envelope.path,
            "source_sha256": model.envelope.source_sha256,
            "metric": model.envelope.metric,
            "units": model.envelope.units,
            "value_mm_s": model.envelope.value_mm_s,
            "gate_index": model.envelope.gate_index,
            "depth_mm": model.envelope.depth_mm,
            "median_abs_mean_difference_mm_s": (
                model.envelope.median_abs_mean_difference_mm_s
            ),
            "scope": model.envelope.scope,
            "role": model.envelope.role,
        },
        "inputs": [
            {
                "relative_path": entry.relative_path,
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
            "command": regeneration_command(model),
            "note": (
                "pass the recorded analysis_commit to reproduce these artefacts byte for "
                "byte; the bare command records the current HEAD"
            ),
        },
    }


# ── the figure ─────────────────────────────────────────────────────────


def _focus_series(
    model: ResolutionLadder, profiles: Mapping[str, tuple[np.ndarray, np.ndarray]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The focus pair's native profiles and its difference at the coarse knots."""
    fine_path, coarse_path = model.focus_pair
    fine_depths, fine_mean = profiles[fine_path]
    coarse_depths, coarse_mean = profiles[coarse_path]
    inside = in_support(
        coarse_depths, (model.common.support_min_mm, model.common.support_max_mm)
    )
    knots = coarse_depths[inside]
    difference = (
        fine_mean[nearest_gate_indices(fine_depths, knots)] - coarse_mean[inside]
    )
    return fine_depths, fine_mean, knots, difference


def render_figure(
    model: ResolutionLadder,
    profiles: Mapping[str, tuple[np.ndarray, np.ndarray]],
    path: Path,
    *,
    dpi: int = 150,
) -> Path:
    """Write the two-panel resolution figure, deterministically, and return it.

    Panels: the native correlation length against pitch (with the 1:1 line where a
    correlation length would be one gate), and the plan's focus pair — both aligned
    profiles against depth with the signed difference at the coarse knots against
    the WP1 envelope band. The gradient spread stays in ``resolution-levels.csv``:
    the figure carries only what the resolution decision needs. The caption is part
    of the image, so the figure cannot be separated from its caveats.

    Args:
        model: the built ladder (supplies every number the panels annotate).
        profiles: each level's ``(gate_depths_mm, per-gate time mean)`` on its native
            grid, as :func:`build_resolution_ladder`'s internal build returns them.
        path: target PNG path (parent directories are created).
        dpi: figure resolution.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt
    from matplotlib.ticker import NullFormatter

    envelope = model.envelope.value_mm_s
    figure, axes = plt.subplots(1, 2, figsize=(12.0, 5.4), dpi=dpi)
    length_ax, pair_ax = axes
    pitch = np.asarray([row.pitch_mm for row in model.levels])

    # The pitch axis is discrete: one tick per measured pitch, with the log scale's
    # own minor labels suppressed. The scale is set first: setting one resets ticks.
    ticks = [float(value) for value in pitch]
    length_ax.set_xscale("log")
    length_ax.set_xticks(ticks)
    length_ax.set_xticklabels(
        [f"{value:.3g}" for value in ticks], fontsize=5.6, rotation=45
    )
    length_ax.xaxis.set_minor_formatter(NullFormatter())

    # (1) native-grid correlation length versus pitch
    length_ax.plot(
        pitch,
        [row.correlation_length_mm for row in model.levels],
        "o-",
        color="#1f77b4",
        linewidth=1.4,
        markersize=4,
    )
    length_ax.plot(
        pitch,
        pitch,
        ":",
        color="#777777",
        linewidth=0.9,
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
    fine_depths, fine_mean, knots, difference = _focus_series(model, profiles)
    focus = next(
        row for row in model.pairs if (row.fine_path, row.coarse_path) == model.focus_pair
    )
    coarse_depths, coarse_mean = profiles[model.focus_pair[1]]
    pair_ax.plot(
        fine_mean,
        fine_depths,
        color="#1f77b4",
        linewidth=1.3,
        label=f"{focus.fine_path} ({focus.fine_pitch_mm:.4g} mm) native",
    )
    pair_ax.plot(
        fine_mean[nearest_gate_indices(fine_depths, knots)],
        knots,
        "o",
        color="#1f77b4",
        markersize=2.6,
        label="the same profile sampled at the coarse knots",
    )
    pair_ax.plot(
        coarse_mean,
        coarse_depths,
        color="#d62728",
        linewidth=1.6,
        label=f"{focus.coarse_path} ({focus.coarse_pitch_mm:.4g} mm) native",
    )
    pair_ax.set_xlabel("per-gate mean velocity [mm/s]")
    pair_ax.set_ylabel("depth from transducer face [mm]")
    pair_ax.invert_yaxis()
    difference_ax = pair_ax.twiny()
    difference_ax.axvspan(-envelope, envelope, color="#999999", alpha=0.18, linewidth=0)
    for sign in (-1.0, 1.0):
        difference_ax.axvline(
            sign * envelope, color="#555555", linewidth=0.8, linestyle=":"
        )
    difference_ax.plot(
        difference,
        knots,
        color="#111111",
        linewidth=1.0,
        label="fine - coarse at the coarse knots",
    )
    difference_ax.set_xlabel("difference [mm/s]; grey band = WP1 envelope", fontsize=7.5)
    difference_ax.set_xlim(-1.25 * envelope, 1.25 * envelope)
    pair_ax.set_title(
        f"plan's pair: {focus.knots} knots at {focus.knot_spacing_mm:.4g} mm; "
        f"max |diff| {focus.max_abs_difference_mm_s:.4g} mm/s",
        fontsize=9.0,
    )
    pair_ax.grid(alpha=0.2)
    pair_ax.legend(loc="lower left", fontsize=6.2, framealpha=0.9)
    difference_ax.legend(loc="upper right", fontsize=6.2, framealpha=0.9)

    figure.suptitle(
        "WP2 resolution ladder — 13 measured pitches against the WP1 repeatability bound",
        fontsize=11,
        y=0.975,
    )
    figure.text(
        0.008,
        0.008,
        wrap_caption(figure_caption(model)),
        fontsize=5.2,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.76, bottom=0.30, wspace=0.22)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=dpi)
    plt.close(figure)
    return target


def write_resolution_ladder(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    envelope_path: Path | None = None,
    analysis_commit: str | None = None,
) -> ResolutionLadder:
    """Build the ladder and write the four reviewer-visible artefacts.

    ``resolution-levels.csv``, ``resolution-pairs.csv``,
    ``resolution-ladder.provenance.json`` and ``figures/resolution-ladder.png`` are
    written with LF endings (the figure is binary), so two runs on the same inputs and
    commit produce identical bytes. Nothing is written when the build raises: a failed
    selection leaves no half-artefact behind.

    Args:
        dataset_root: root holding the ``<axis>/<label>.BDD`` points.
        report_dir: directory the artefacts land in (``figures/`` inside it).
        manifest_path: the WP0 manifest, default ``<report_dir>/manifest.csv``.
        envelope_path: the WP1 provenance the threshold is read from, default
            ``<report_dir>/reference-repeat.provenance.json``.
        analysis_commit: revision to record; ``None`` probes the checkout.

    Returns:
        The built :class:`ResolutionLadder`.
    """
    directory = Path(report_dir)
    manifest = (
        Path(manifest_path) if manifest_path is not None else directory / MANIFEST_NAME
    )
    envelope = (
        Path(envelope_path) if envelope_path is not None else directory / ENVELOPE_NAME
    )
    model, profiles = _build(dataset_root, manifest, envelope, analysis_commit)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / LEVELS_NAME).write_text(
        levels_csv_text(model), encoding="utf-8", newline=""
    )
    (directory / PAIRS_NAME).write_text(
        pairs_csv_text(model), encoding="utf-8", newline=""
    )
    (directory / PROVENANCE_NAME).write_text(
        json.dumps(provenance_document(model), indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    render_figure(model, profiles, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
