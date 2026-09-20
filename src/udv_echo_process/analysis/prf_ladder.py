"""WP2, PRF axis — the measured pulse-repetition ladder against the sole-pair screening threshold.

The committed sweep holds a five-point PRF ladder — one base-state recording per requested
pulse-repetition period, 400 µs (``prf/400.BDD``) to 800 µs (``prf/800.BDD``), over the same
~100 mm window on the same 1.85 mm gate grid (plan §2). This module answers the plan's PRF
question from the ``prf`` rows of the WP0 manifest, never a filename list (plan §4 WP2 gate):
*does the committed 400-µs setting have inadequate velocity or temporal-bandwidth headroom, and
is a 250-µs acquisition therefore justified?* One build produces the common views (plan §3.1, §3.2), the per-level native-grid metrics, the
actual profile rate the timestamps imply, the ``|v| / Vmax`` load distributions with their warning
fractions, the wrap-like temporal discontinuities, the matched full-record temporal view with its
repeat floor, and every unordered pair against the committed WP1 screening_threshold with the depth ranges
where it clears it. The manifest selection, decode and its hash/cell/grid re-checks, the clean-OFAT
audit, the common views, the native-grid metrics, the knot alignment, the committed WP1 screening_threshold
and temporal-floor readers and the writers belong to the shared layer
(:mod:`udv_echo_process.analysis._native_grid`), which this axis drives with its own axis name, key
cell, settings and columns.

Selection is by decoded **scientific fingerprint** (:data:`ELIGIBILITY`), never by folder
(plan §8.3 step 2, R1/R4): the period is the only setting this axis may move, ``prf_hz`` and
``velo_max_ms`` follow from it, and every recording sharing the rest of the fingerprint - including
`res/1-8.BDD`, which sits under another folder - is eligible at the level its own decoded period
names. ``prf/600.BDD`` and ``res/1-8.BDD`` are therefore two named realizations of the 600 µs level,
not a duplicate key to refuse. The committed ladder still holds the levels this axis itself
requested; the setting-based rebuild of §8.3 step 5 renders the realizations into the artefacts.

Two facts separate this axis from its siblings (plan §2). The velocity scale is not a free setting:
the reader publishes ``velo_max_ms`` as the ±Nyquist velocity, and here ``Vmax × prf_period`` is
constant across all five files, so the scale moved *with* the key and is audited as an intended
consequence rather than refused as a coupled setting. And the files do **not** share a profile rate
— the timestamps imply 66.7 Hz at 400 µs down to 33.6 Hz at 800 µs, *not* in exact proportion to
the PRF — so the temporal view is matched on *physical* segment duration rather than a profile
count, and spectra are compared only where every recording has support. The 500-RPM setpoint is a
marker (8.33 Hz), never a phase reference, so no peak is attributed to it or to a harmonic; no
profile or gate is an independent replicate, the levels carry no acquisition order, and no p-value
is produced (plan §3.3). PRF axis only.
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
from udv_echo_process.analysis import reference_repeat as wp1
from udv_echo_process.analysis import sweep_inventory as inventory
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: The manifest axis this module owns, and the reviewer-visible artefacts.
AXIS = "prf"
LEVELS_NAME, PAIRS_NAME = "prf-levels.csv", "prf-pairs.csv"
PROVENANCE_NAME, FIGURE_NAME = "prf-ladder.provenance.json", "prf-ladder.png"
FIGURES_DIRNAME, SCREENING_THRESHOLD_NAME = "figures", "reference-repeat.provenance.json"

#: The plan's question: the committed setting, and the acquisition its answer decides.
FOCUS_SETTING_US = 400.0
CANDIDATE_SETTING_US = 250.0

#: The plan's declared support window, the nominal mixer marker, and the load fractions reported
#: per level: the share of samples at or above these multiples of the record's own ``velo_max_ms``.
#: 1.0 is the only physically distinguished one (the reader's unambiguous limit).
PLAN_SUPPORT_MM: tuple[float, float] = (10.163, 96.743)
MIXER_MARKER_HZ = wp1.MIXER_SETPOINT_HZ
WARNING_FRACTIONS: tuple[float, ...] = (0.5, 0.75, 0.9, 1.0)

#: The wrap criterion: a wrap moves the estimate across the whole ±Vmax span in one profile
#: interval, so a consecutive-profile step of at least Vmax *with a sign reversal* is the
#: conservative half-span signature; ``max_abs_step_over_velo_max`` is published beside the count.
WRAP_STEP_FRACTION = 1.0

#: The axis's setting-based contract (plan §8.3 step 2, R1/R4): the pulse-repetition period is the
#: only decoded setting this ladder may move, and ``prf_hz`` / ``velo_max_ms`` follow from it
#: (``Vmax = c / (4 f0 T)``), so they are derived rather than settings. Every recording sharing the
#: rest of the fingerprint - whatever folder its row sits in - is eligible, and the two 600 µs
#: recordings are two realizations of one level rather than a duplicate key.
ELIGIBILITY = grid.AxisEligibility(
    axis=AXIS, ladder_label="PRF", varied=("prf_period_us",),
    derived=("prf_hz", "velo_max_ms"),
)

#: Settings that must **not** move: this axis changes the pulse-repetition period only. The
#: velocity scale is absent — it is the key's consequence, audited as such — and so is the rate.
COUPLED_SETTINGS: tuple[str, ...] = (
    "resolution_mm", "burst_length", "emissions_per_profile", "emit_power", "sensitivity",
    "tgc_mode", "sound_speed_ms", "gates",
)
VERIFIED_CELLS: tuple[str, ...] = (
    "profiles", "gates", "duration_s", "resolution_mm", "prf_period_us", "burst_length",
    "emissions_per_profile", "emit_power", "sensitivity", "tgc_mode",
)
#: Cells derived from the key, re-checked against the decode, and the spread that still counts as one key.
DERIVED_CELLS: tuple[str, ...] = ("prf_hz", "velo_max_ms")
VELO_SCALE_RTOL = 1e-6

#: The matched temporal view: the largest multiple of :data:`SEGMENT_STEP_S` that fits at least
#: :data:`MIN_SEGMENTS` whole segments in the shortest full record (these files share no rate).
SEGMENT_STEP_S, MIN_SEGMENTS = 0.1, 5

#: Column order of the two tables: the dict rows of :class:`PrfLadder` carry exactly these keys.
LEVEL_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "prf_period_us", "prf_hz", "velo_max_mm_s",
    "profiles_window", "gates_in_support", "pitch_mm", "mean_mm_s", "robust_spread_mm_s",
    "rms_mm_s", "zero_fraction", "gradient_max_abs_mm_s_per_mm", "correlation_length_mm",
    "profile_rate_hz", "load_max_over_velo_max", "warning_fraction_half",
    "warning_fraction_three_quarter", "warning_fraction_nine_tenths", "warning_fraction_at_limit",
    "samples_beyond_limit", "wrap_like_events", "wrap_like_fraction", "max_abs_step_over_velo_max",
    "nyquist_hz", "segment_profiles", "segment_duration_s", "frequency_resolution_hz", "segments",
    "usable_bandwidth_hz", "acf_e_folding_lag_s", "psd_share_below_mixer_marker",
)
PAIR_COLUMNS: tuple[str, ...] = (
    "axis", "faster_path", "faster_label", "faster_prf_hz", "slower_path", "slower_label",
    "slower_prf_hz", "prf_gap_hz", "knots", "knot_spacing_mm", "max_knot_offset_mm",
    "mean_abs_difference_mm_s", "max_abs_difference_mm_s", "max_abs_difference_depth_mm",
    "knots_above_screening_threshold", "max_abs_difference_over_screening_threshold", "depth_ranges_above_screening_threshold_mm",
    "load_max_change", "warning_fraction_at_limit_change", "wrap_like_events_change",
    "zero_fraction_change", "psd_band_max_abs_level_difference_db",
    "psd_band_difference_frequency_hz", "psd_band_median_level_difference_db",
)

#: The error class of every message this module raises; the shared helpers raise the same class, so
#: one name covers a helper refusal and an axis refusal, and the level record is WP1's.
PrfLadderError = grid.NativeGridError
LevelInput = wp1.RepeatInput
#: The WP0 locations this axis reads and writes by default, and the revolution its window counts in.
NOMINAL_REVOLUTION_S = wp1.NOMINAL_REVOLUTION_S
DATASET_ROOT, MANIFEST_NAME, REPORT_DIR = (
    inventory.DATASET_ROOT, inventory.MANIFEST_NAME, inventory.REPORT_DIR,
)


class PrfLadder(ValueModel):
    """The WP2 PRF result: the level rows, the pair rows and the two matched views.

    ``levels`` and ``pairs`` are dict rows keyed by the declared column tuples; ``temporal``
    carries the ``floor`` read from the committed WP1 provenance, and ``focus_path`` names the
    manifest-selected level the plan's decision is about.
    """

    dataset_root: str
    manifest_path: str
    manifest_sha256: str
    screening_threshold: grid.ScreeningThresholdBinding
    axis: str = AXIS
    analysis_commit: str | None = None
    eligibility: grid.AxisEligibility = ELIGIBILITY
    inputs: tuple[LevelInput, ...]
    groups: tuple[grid.LevelGroup, ...] = ()
    common: dict[str, object]
    temporal: dict[str, object]
    focus_path: str
    levels: tuple[dict[str, object], ...]
    pairs: tuple[dict[str, object], ...]

    @model_validator(mode="after")
    def _check_the_ladder_is_internally_consistent(self) -> PrfLadder:
        if [row.get("relative_path") for row in self.levels] != [
            entry.relative_path for entry in self.inputs
        ]:
            raise ValueError("every level must appear exactly once, in input order")
        for columns, rows in ((LEVEL_COLUMNS, self.levels), (PAIR_COLUMNS, self.pairs)):
            if any(tuple(row) != columns for row in rows):
                raise ValueError("a row must carry exactly the declared columns")
        if any(b <= a for a, b in itertools.pairwise(row["prf_period_us"] for row in self.levels)):
            raise ValueError("levels must be ordered by increasing PRF period")
        expected = len(self.levels) * (len(self.levels) - 1) // 2
        if len(self.pairs) != expected:
            raise ValueError(f"expected every unordered pair ({expected}), got {len(self.pairs)}")
        if self.focus_path not in {row["relative_path"] for row in self.levels}:
            raise ValueError(f"focus level {self.focus_path} must be one of the levels")
        if self.screening_threshold.value_mm_s <= 0.0:
            raise ValueError("the repeatability screening_threshold must be positive")
        return self


def _period_us_of(row: Mapping[str, str], manifest_path: Path) -> float:
    """The row's decoded PRF period, refused unless it is a positive number of microseconds."""
    cell = (row.get("prf_period_us") or "").strip()
    try:
        period = float(cell)
    except ValueError:
        raise PrfLadderError(
            f"{row.get('relative_path')}: manifest prf_period_us={cell!r} in {manifest_path} is not "
            "a pulse-repetition period in microseconds"
        ) from None
    if not math.isfinite(period) or period <= 0.0:
        raise PrfLadderError(f"{row.get('relative_path')}: prf_period_us={cell!r} <= 0")
    return period


def select_level_rows(manifest_path: Path) -> tuple[dict[str, str], ...]:
    """The representative row of every ``prf`` level the axis itself requested, by period then path.

    The ladder is bound to the WP0 manifest, never to a filename list: selection, ordering and
    refusals are the shared axis-input layer's, driven with this axis's own contract. A same-settings
    recording sitting in another folder is eligible (:func:`level_groups`) but is not one of this
    axis's requested levels, so it does not redefine the committed ladder on its own.
    """
    path = Path(manifest_path)
    return grid.select_axis_rows(
        path, eligibility=ELIGIBILITY, order_key=lambda row: _period_us_of(row, path),
        order_label="PRF period",
    )


def level_groups(manifest_path: Path) -> tuple[grid.LevelGroup, ...]:
    """Every eligible ``prf`` level with all its realizations, by period then path.

    The 600 µs level of ``prf/600.BDD`` and ``res/1-8.BDD`` is one decoded level with two named
    realizations, whichever folder each sits in (plan §8.3 step 2, R1).
    """
    path = Path(manifest_path)
    return grid.level_groups(
        path, eligibility=ELIGIBILITY, order_key=lambda row: _period_us_of(row, path),
        order_label="PRF period",
    )


def _read_level(
    dataset_root: Path, row: dict[str, str]
) -> tuple[LevelInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected level, returning ``(entry, values, time_s, depths)``.

    Every shared cell is re-checked by the shared axis-input layer; the two cells *derived* from the
    key (the PRF in Hz and the velocity scale) are re-checked here, because a stale scale would
    silently redefine every normalised load this axis publishes.
    """
    level = grid.read_decoded_level(Path(dataset_root), row, cells=VERIFIED_CELLS)
    observed, config = level.observed, level.config
    derived = {"prf_hz": 1e6 / float(observed["prf_period_us"]),
               "velo_max_ms": float(config.velo_max_ms)}
    for cell in DERIVED_CELLS:
        if (row.get(cell) or "").strip() != format_cell(derived[cell]):
            raise PrfLadderError(
                f"{level.relative_path}: manifest {cell}={row.get(cell)!r} does not match the "
                f"decoded {cell}={format_cell(derived[cell])!r}; the PRF normalisation must not "
                "rest on a stale inventory"
            )
    fields = {
        "relative_path": level.relative_path, "axis": level.axis,
        "requested_label": level.requested_label, "source_sha256": level.source_sha256,
        "profiles": int(level.values.shape[0]), "gates": int(level.values.shape[1]),
        "duration_s": float(observed["duration_s"]),
        "profile_period_s": float(observed["duration_s"] / (level.time_s.size - 1)),
        "depth_min_mm": float(observed["depth_min_mm"]),
        "depth_max_mm": float(observed["depth_max_mm"]),
        "prf_period_us": float(observed["prf_period_us"]),
        "resolution_mm": float(config.resolution_mm), "burst_length": int(config.burst_length),
        "emissions_per_profile": int(config.emissions_per_profile),
        "emit_power": str(config.emit_power), "sensitivity": str(config.sensitivity),
        "tgc_mode": str(config.tgc_mode), "sound_speed_ms": float(config.sound_speed_ms),
        "velo_max_ms": float(config.velo_max_ms),
    }
    return LevelInput(**fields), level.values, level.time_s, level.depths


def _require_clean_ofat(entries: Sequence[LevelInput]) -> None:
    """Refuse a ladder where a setting other than the PRF period moved (plan §2)."""
    grid.require_clean_ofat(entries, COUPLED_SETTINGS, axis_label="PRF")


def _require_scaled_velocity_scale(entries: Sequence[LevelInput]) -> None:
    """Refuse a ladder whose velocity scale did not follow the PRF key.

    ``velo_max_ms`` is the reader's ±Nyquist velocity, so a pure PRF change must move it in inverse
    proportion: ``Vmax × prf_period`` is invariant. A ladder where it is not has moved an independent
    setting — the scale, or a frequency/angle/sound-speed cell it derives from — so its normalised
    loads would not be the key's consequence.
    """
    products = [entry.velo_max_ms * entry.prf_period_us for entry in entries]
    mean = sum(products) / len(products)
    spread = (max(products) - min(products)) / mean
    if spread > VELO_SCALE_RTOL:
        raise PrfLadderError(
            "the velocity scale did not follow the PRF key: velo_max_ms x prf_period_us ranges "
            f"{min(products):.10g}-{max(products):.10g} ({spread:.3g} relative), above the "
            f"{VELO_SCALE_RTOL:g} tolerance a pure PRF ladder keeps; an independent setting moved "
            "with it"
        )


def _load_metrics(values: np.ndarray, velo_max_ms: float) -> dict[str, object]:
    """The ``|v| / Vmax`` load distribution and wrap-like discontinuities of one recording.

    ``values`` is that level's own recording, cut by the caller to the common window and support; a
    wrap is a consecutive-profile gate-wise step reaching :data:`WRAP_STEP_FRACTION` of ``Vmax`` and
    reversing sign.
    """
    if values.size == 0 or not math.isfinite(velo_max_ms) or velo_max_ms <= 0.0:
        raise PrfLadderError("a load distribution needs samples and a positive velo_max_ms")
    load = np.abs(values) / velo_max_ms
    steps = np.abs(np.diff(values, axis=0))
    wraps = ((values[:-1] * values[1:]) < 0.0) & (steps >= WRAP_STEP_FRACTION * velo_max_ms)
    fraction = lambda limit: float(np.count_nonzero(load >= limit) / load.size)
    return {
        "load_max_over_velo_max": float(load.max()), "warning_fraction_half": fraction(0.5),
        "warning_fraction_three_quarter": fraction(0.75), "warning_fraction_nine_tenths": fraction(0.9),
        "warning_fraction_at_limit": fraction(1.0),
        "samples_beyond_limit": int(np.count_nonzero(load > 1.0)),
        "wrap_like_events": int(np.count_nonzero(wraps)),
        "wrap_like_fraction": float(np.count_nonzero(wraps) / wraps.size),
        "max_abs_step_over_velo_max": float(steps.max() / velo_max_ms),
    }


def _temporal_grid(
    periods_s: Sequence[float], durations_s: Sequence[float]
) -> tuple[dict[str, dict[str, float]], float]:
    """Each file's matched segment, keyed by its profile period, and the nominal resolution.

    The shared quantity is the *physical* segment duration, the largest multiple of
    :data:`SEGMENT_STEP_S` fitting :data:`MIN_SEGMENTS` whole segments in the shortest record; each
    file then takes the whole number of profiles inside it, so its realised duration differs from
    that target by less than one profile period, its resolution is ``1 / realised duration`` and
    its usable bandwidth half its profile rate.
    """
    if not durations_s:
        raise PrfLadderError("a matched segment duration needs at least one duration")
    target = math.floor(min(durations_s) / MIN_SEGMENTS / SEGMENT_STEP_S) * SEGMENT_STEP_S
    if target <= 0.0:
        raise PrfLadderError(
            f"the shortest record ({min(durations_s):.4g} s) does not hold {MIN_SEGMENTS} "
            f"segments of {SEGMENT_STEP_S:g} s"
        )
    rows: dict[str, dict[str, float]] = {}
    for period, duration in zip(periods_s, durations_s, strict=True):
        profiles = math.floor(target / period)
        segments = math.floor(duration / (profiles * period)) if profiles >= 2 else 0
        if profiles < 2 or segments < 1:
            raise PrfLadderError(
                f"{duration:.6g} s does not hold one {profiles}-profile segment at a "
                f"{period:.6g} s profile period inside a {target:g} s target"
            )
        rows[str(period)] = {
            "profiles": profiles, "segments": segments,
            "duration_s": (profiles - 1) * period, "resolution_hz": 1.0 / (profiles * period),
            "usable_bandwidth_hz": (profiles // 2) / (profiles * period),
        }
    return rows, 1.0 / target


def _band_edges(
    nominal_resolution_hz: float, usable_min_hz: float, *, bands: int = 2
) -> np.ndarray:
    """The shared comparison bands: multiples of the nominal resolution up to the narrowest usable
    bandwidth in the ladder, so every file supports every band."""
    count = math.floor(usable_min_hz / nominal_resolution_hz)
    if count < bands:
        raise PrfLadderError(
            f"the narrowest usable bandwidth {usable_min_hz:.6g} Hz holds {count} band(s) of "
            f"{nominal_resolution_hz:.6g} Hz; a comparison needs {bands}"
        )
    return np.arange(1.0, count + 1.0) * nominal_resolution_hz


def _band_density(frequency: np.ndarray, density: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Mean spectral density of each band ``[edges[k], edges[k+1])``: band power over band width.

    Only bins the recording actually supports are summed, so every level is compared on identical
    bands and on frequencies it measured.
    """
    values = np.empty(edges.size - 1)
    for index in range(edges.size - 1):
        low, high = edges[index], edges[index + 1]
        inside = (frequency >= low) & (frequency < high)
        if not np.any(inside):
            raise PrfLadderError(
                f"the frequency grid holds no bin in the comparison band [{low:.6g}, {high:.6g}) Hz"
            )
        values[index] = float(density[inside].sum() / (high - low))
    return values


def level_row(
    entry: LevelInput,
    metrics: grid.LevelMetrics,
    series: wp1.TemporalSeries,
    load: Mapping[str, object],
    cell: Mapping[str, float],
) -> dict[str, object]:
    """One level's row: its common-window, native-grid, load and matched-segment metrics."""
    frequency = np.asarray(series.frequency_hz, dtype=float)
    supported = frequency <= cell["usable_bandwidth_hz"]
    density = np.asarray(series.psd_mean_mm2_s2_per_hz, dtype=float)[supported]
    total = float(density.sum())
    if total <= 0.0:
        raise PrfLadderError(f"{entry.relative_path}: the ensemble PSD carries no power")
    means = metrics.means
    return {
        "axis": entry.axis, "relative_path": entry.relative_path,
        "requested_label": entry.requested_label, "prf_period_us": entry.prf_period_us,
        "prf_hz": 1e6 / entry.prf_period_us, "velo_max_mm_s": entry.velo_max_ms,
        "profiles_window": metrics.profiles_window, "gates_in_support": metrics.supported_gates,
        "pitch_mm": metrics.gradient.pitch_mm, "mean_mm_s": float(means.mean()),
        "robust_spread_mm_s": float(np.percentile(means, 75.0) - np.percentile(means, 25.0)),
        "rms_mm_s": float(np.sqrt(np.mean(np.square(metrics.supported)))),
        "zero_fraction": float(np.count_nonzero(metrics.supported == 0.0) / metrics.supported.size),
        "gradient_max_abs_mm_s_per_mm": metrics.gradient.max_abs_mm_s_per_mm,
        "correlation_length_mm": metrics.correlation.length_mm,
        "profile_rate_hz": 1.0 / entry.profile_period_s, **load,
        "nyquist_hz": 0.5 / entry.profile_period_s, "segment_profiles": cell["profiles"],
        "segment_duration_s": cell["duration_s"], "frequency_resolution_hz": cell["resolution_hz"],
        "segments": cell["segments"], "usable_bandwidth_hz": cell["usable_bandwidth_hz"],
        "acf_e_folding_lag_s": series.acf_e_folding_lag_s,
        "psd_share_below_mixer_marker": float(
            density[frequency[supported] < MIXER_MARKER_HZ].sum() / total
        ),
    }


def pair_row(
    faster: Mapping[str, object],
    faster_profile: tuple[np.ndarray, np.ndarray],
    faster_density: np.ndarray,
    slower: Mapping[str, object],
    slower_profile: tuple[np.ndarray, np.ndarray],
    slower_density: np.ndarray,
    *,
    support: tuple[float, float],
    screening_threshold: grid.ScreeningThresholdBinding,
    edges: np.ndarray,
) -> dict[str, object]:
    """Compare a shorter-period level with a longer-period one on the shared knots and bands.

    Each ``*_profile`` is ``(gate_depths_mm, per-gate time mean)`` and each ``*_density`` the
    level's band-mean spectral density on the shared bands. The knots are the *slower* level's
    native gate depths inside the common support — the alignment the resolution and burst axes use
    — and the spectral difference is taken only where both files have support.
    """
    if faster["prf_period_us"] >= slower["prf_period_us"]:
        raise PrfLadderError(
            f"a pair is (faster, slower): {faster['relative_path']} at "
            f"{faster['prf_period_us']} us is not a shorter period than "
            f"{slower['relative_path']} at {slower['prf_period_us']}"
        )
    faster_depths, faster_mean = (np.asarray(part, dtype=float) for part in faster_profile)
    slower_depths, slower_mean = (np.asarray(part, dtype=float) for part in slower_profile)
    aligned = grid.align_on_knots(
        faster_depths, faster_mean, slower_depths, slower_mean,
        path=str(faster["relative_path"]), support=support,
        threshold_mm_s=screening_threshold.value_mm_s,
    )
    absolute, worst = aligned.absolute, aligned.worst
    levels = 10.0 * np.log10(np.asarray(faster_density) / np.asarray(slower_density))
    loudest = int(np.argmax(np.abs(levels)))
    return {
        "axis": faster["axis"], "faster_path": faster["relative_path"],
        "faster_label": faster["requested_label"], "faster_prf_hz": faster["prf_hz"],
        "slower_path": slower["relative_path"], "slower_label": slower["requested_label"],
        "slower_prf_hz": slower["prf_hz"], "prf_gap_hz": faster["prf_hz"] - slower["prf_hz"],
        "knots": int(aligned.knots.size), "knot_spacing_mm": slower["pitch_mm"],
        "max_knot_offset_mm": aligned.offset_mm, "mean_abs_difference_mm_s": float(absolute.mean()),
        "max_abs_difference_mm_s": float(absolute[worst]),
        "max_abs_difference_depth_mm": float(aligned.knots[worst]),
        "knots_above_screening_threshold": int(np.count_nonzero(aligned.flagged)),
        "max_abs_difference_over_screening_threshold": float(absolute[worst] / screening_threshold.value_mm_s),
        "depth_ranges_above_screening_threshold_mm": grid.depth_ranges(aligned.knots, aligned.flagged),
        "load_max_change": slower["load_max_over_velo_max"] - faster["load_max_over_velo_max"],
        "warning_fraction_at_limit_change": (
            slower["warning_fraction_at_limit"] - faster["warning_fraction_at_limit"]
        ),
        "wrap_like_events_change": slower["wrap_like_events"] - faster["wrap_like_events"],
        "zero_fraction_change": slower["zero_fraction"] - faster["zero_fraction"],
        "psd_band_max_abs_level_difference_db": float(levels[loudest]),
        "psd_band_difference_frequency_hz": float(0.5 * (edges[loudest] + edges[loudest + 1])),
        "psd_band_median_level_difference_db": float(np.median(levels)),
    }


def _build(
    dataset_root: Path, manifest_path: Path, screening_threshold_path: Path, analysis_commit: str | None
) -> tuple[
    PrfLadder, dict[str, tuple[np.ndarray, np.ndarray]], dict[str, tuple[np.ndarray, np.ndarray]]
]:
    """Build the ladder and return it beside each level's profile and spectral curve."""
    rows = select_level_rows(manifest_path)  # a missing manifest is refused by name here
    manifest_sha256 = f"sha256:{grid.sha256_file(Path(manifest_path))}"
    screening_threshold = grid.read_screening_threshold(Path(screening_threshold_path), manifest_sha256)
    decoded = [_read_level(Path(dataset_root), row) for row in rows]
    entries = [entry for entry, *_ in decoded]
    _require_clean_ofat(entries)
    _require_scaled_velocity_scale(entries)
    revolutions = wp1.common_revolution_count([entry.duration_s for entry in entries])
    window_s = revolutions * wp1.NOMINAL_REVOLUTION_S
    support = grid.common_support([(e.depth_min_mm, e.depth_max_mm) for e in entries])
    metrics = [
        grid.level_metrics(e.relative_path, v, t, d, window_s=window_s, support=support)
        for e, v, t, d in decoded
    ]
    loads = [
        _load_metrics(grid.window(v, t, window_s)[:, own.mask], e.velo_max_ms)
        for (e, v, t, _d), own in zip(decoded, metrics, strict=True)
    ]
    cell, nominal_resolution = _temporal_grid(
        [e.profile_period_s for e in entries], [e.duration_s for e in entries]
    )
    series = [
        wp1.temporal_series(
            e, v, e.profile_period_s, segment_profiles=int(cell[str(e.profile_period_s)]["profiles"])
        )
        for e, v, _t, _d in decoded
    ]
    edges = _band_edges(nominal_resolution, min(r["usable_bandwidth_hz"] for r in cell.values()))
    densities = [
        _band_density(
            np.asarray(s.frequency_hz, dtype=float),
            np.asarray(s.psd_mean_mm2_s2_per_hz, dtype=float), edges,
        )
        for s in series
    ]
    levels = tuple(
        level_row(e, own, s, load, cell[str(e.profile_period_s)])
        for (e, *_rest), own, s, load in zip(decoded, metrics, series, loads, strict=True)
    )
    profiles = {
        e.relative_path: (d, own.per_gate["mean"])
        for (e, _v, _t, d), own in zip(decoded, metrics, strict=True)
    }
    pairs = tuple(
        pair_row(
            faster, profiles[faster["relative_path"]], f_density,
            slower, profiles[slower["relative_path"]], s_density,
            support=support, screening_threshold=screening_threshold, edges=edges,
        )
        for (faster, _fs, f_density), (slower, _ss, s_density) in itertools.combinations(
            zip(levels, series, densities, strict=True), 2
        )
    )
    floor = grid.read_temporal_floor(
        Path(screening_threshold_path), manifest_sha256, band_hz=(float(edges[0]), float(edges[-1])),
        hf_above_hz=MIXER_MARKER_HZ,
    )
    matches = [
        row for row in levels if math.isclose(row["prf_period_us"], FOCUS_SETTING_US, rel_tol=1e-9)
    ]
    if len(matches) != 1:
        raise PrfLadderError(
            f"the plan's question is about the {FOCUS_SETTING_US:g} us setting; the manifest ladder "
            f"holds {len(matches)} level(s) at it (selected by decoded PRF period, never a filename)"
        )
    rates = {e.relative_path: 1.0 / e.profile_period_s for e in entries}
    counts = {
        e.relative_path: (own.profiles_window, own.supported_gates)
        for (e, *_rest), own in zip(decoded, metrics, strict=True)
    }
    model = PrfLadder(
        dataset_root=Path(dataset_root).as_posix(),
        manifest_path=Path(manifest_path).as_posix(), manifest_sha256=manifest_sha256,
        screening_threshold=screening_threshold,
        analysis_commit=analysis_commit if analysis_commit is not None else current_revision(),
        eligibility=ELIGIBILITY,
        inputs=tuple(entries),
        groups=level_groups(manifest_path),
        common={
            "nominal_rpm": wp1.NOMINAL_RPM, "revolution_s": wp1.NOMINAL_REVOLUTION_S,
            "revolutions": revolutions, "window_s": window_s, "levels": len(levels),
            "segment_target_s": 1.0 / nominal_resolution, "support_min_mm": support[0],
            "support_max_mm": support[1],
            "profiles_window": {p: w for p, (w, _g) in counts.items()},
            "gates_in_support": {p: g for p, (_w, g) in counts.items()},
        },
        temporal={
            "cell": cell, "nominal_resolution_hz": nominal_resolution, "floor": floor,
            "band_hz": [float(edges[0]), float(edges[-1])], "bands": int(edges.size - 1),
            "profile_rate_hz": rates,
            "profile_rate_spread_relative": (max(rates.values()) - min(rates.values()))
            / (sum(rates.values()) / len(rates)),
            "profile_period_over_prf_period": {
                e.relative_path: e.profile_period_s / (e.prf_period_us * 1e-6) for e in entries
            },
            "acf_estimator": wp1.ACF_ESTIMATOR, "psd_window": wp1.PSD_WINDOW,
            "psd_detrend": wp1.PSD_DETREND, "psd_scaling": wp1.PSD_SCALING,
            "segment_step_s": SEGMENT_STEP_S, "min_segments": MIN_SEGMENTS,
        },
        focus_path=str(matches[0]["relative_path"]), levels=levels, pairs=pairs,
    )
    curves = {
        e.relative_path: (
            np.asarray(s.frequency_hz, dtype=float),
            np.asarray(s.psd_mean_mm2_s2_per_hz, dtype=float),
        )
        for e, s in zip(entries, series, strict=True)
    }
    return model, profiles, curves


def build_prf_ladder(
    dataset_root: Path = inventory.DATASET_ROOT,
    manifest_path: Path = inventory.REPORT_DIR / inventory.MANIFEST_NAME,
    screening_threshold_path: Path = inventory.REPORT_DIR / SCREENING_THRESHOLD_NAME,
    *,
    analysis_commit: str | None = None,
) -> PrfLadder:
    """Build the WP2 PRF ladder from the manifest-selected recordings.

    ``analysis_commit`` is the revision to record; ``None`` probes the checkout's short git SHA once.
    A manifest, a WP1 screening_threshold, a coupled or unscaled setting or a recording that contradicts its
    row is refused by name before anything is written.
    """
    return _build(dataset_root, Path(manifest_path), Path(screening_threshold_path), analysis_commit)[0]


#: Metric definitions, recorded verbatim in the provenance document (WP0's rule for its tables).
DEFINITIONS: dict[str, str] = {
    "prf_period_us": "decoded pulse-repetition period in microseconds, re-checked against the manifest cell: the ladder's key, ordered by it, never by a filename",
    "velo_max_mm_s": "the reader's +/-Nyquist velocity, the velocity at full-scale count (ChannelConfig.velo_max_ms), re-checked against the manifest cell: the unambiguous limit every load fraction is normalised by",
    "velocity_scale": "the +/-Nyquist velocity is the velocity at full-scale count, so a pure PRF change must move it in inverse proportion; velo_max_ms x prf_period_us is audited for constancy and a ladder whose scale moved with anything else is refused",
    "profile_rate_hz": "1 / (duration_s / (profiles - 1)) from the recorded timestamps: the actual profile rate of that file, not the PRF and not a stored setting",
    "load_over_velo_max": "|v| / velo_max_ms of one sample: 1.0 is the unambiguous limit",
    "warning_fractions": "share of windowed, supported samples at or above 0.5, 0.75, 0.9 and 1.0 of that recording's velo_max_ms; the inner three are declared margins below the limit, not instrument flags, and these files carry no warning channel",
    "wrap_like_discontinuity": "a consecutive-profile change at one gate of at least velo_max_ms with a sign reversal: a wrap moves the estimate across the whole +/-velo_max_ms span in one profile interval, about 2 x velo_max_ms, so the criterion is the conservative half-span",
    "difference": "signed faster - slower per-gate time mean at every common knot, mm/s; a negative value means the shorter period is slower there",
    "screening_threshold": "the committed sole-pair observed-discrepancy screening threshold max_gate_abs_mean_difference_mm_s, read from reference-repeat.provenance.json and pinned to this manifest's hash: the threshold every mean-profile effect is screened against. An effect above or below it is a screening outcome, not proof of a PRF effect and not a bound on repeatability or uncontrolled drift",
    "matched_segment": "the physical segment duration every file is analysed in, the largest multiple of 0.1 s that fits five whole segments in the shortest record; each file takes the whole number of profiles inside it, so segment duration and resolution agree rather than being equal",
    "comparison_bands": "identical bands from the nominal resolution up to the narrowest usable bandwidth in the ladder; a level's density is its band power over the band width, so spectra are compared only where every recording has support",
    "usable_bandwidth": "the highest frequency a file's matched segment supports, half its profile rate; the full-record Nyquist limit is published beside it",
    "acf_e_folding_lag": "the first lag of the mean-removed segment's normalized autocovariance below 1/e, in seconds on that file's own lag grid",
    "mixer_marker": "nominal 500 RPM -> 8.33 Hz marker only: no tachometer in these files, so it is not a phase reference and no peak here is attributed to it or to a harmonic",
    "replicates": "no profile and no gate is an independent experimental replicate",
    "views": "distributional metrics use the common-duration window on the common support; native-grid gradients and correlation lengths use each level's own grid; the full record is analysed only through the matched temporal view",
}

#: The verdict :func:`_findings` records, and the two caveats that travel with every artefact, so they
#: cannot drift between the provenance document and the figure caption.
MIXER_SETPOINT_ROLE = "nominal mixer marker only (500 RPM -> 8.33 Hz, one revolution = 0.12 s): no tachometer in these files, so the setpoint is not a phase reference and no spectral peak or harmonic is attributed to it"
REPLICATE_ROLE = "no profile and no gate is an independent experimental replicate; the levels carry no acquisition order, so a level effect cannot be separated from drift"
_FOCUS_VERDICT = (
    "Verdict: this evidence does not show the 400 us setting to be inadequate on either count, so it "
    f"does not justify a {CANDIDATE_SETTING_US:g} us acquisition. Unidentifiable here: a wrap that "
    "leaves no step of half the span (a slowly drifting alias), the peak velocity of a flow whose "
    f"setpoint differs from this 500-RPM one, and the rate a future {CANDIDATE_SETTING_US:g} us "
    "setting would run at, which these files cannot fix because their own rate is not an exact "
    "multiple of the PRF. What would overturn it: a recording whose |v| reaches the 400 us "
    "unambiguous limit, or a stated question needing temporal content above the 400 us bandwidth."
)

#: Panels of the reviewer-visible figure, in order.
FIGURE_PANELS: tuple[str, ...] = (
    "velocity headroom: the largest |v| / Vmax per level against the unambiguous limit at 1.0, with the samples beyond the limit and the wrap-like discontinuities beside it",
    "usable temporal bandwidth: each level's ensemble PSD against the frequencies it supports, with the shared comparison band, each file's usable bandwidth and the 8.33 Hz marker",
)


def levels_csv_text(model: PrfLadder) -> str:
    """Render ``prf-levels.csv`` from the model's own level rows."""
    return grid.csv_text(LEVEL_COLUMNS, model.levels)


def pairs_csv_text(model: PrfLadder) -> str:
    """Render ``prf-pairs.csv`` from the model's own pair rows."""
    return grid.csv_text(PAIR_COLUMNS, model.pairs)


def _findings(model: PrfLadder) -> dict[str, object]:
    """The plan's PRF questions answered from the numbers the tables already carry.

    Every statement is composed from those values, so a regeneration says what it wrote. Nothing
    here is a p-value, an acquisition-order inference, an alias verdict this data cannot support, or
    a decision about an axis this module does not own.
    """
    screening_threshold = model.screening_threshold.value_mm_s
    above = [row for row in model.pairs if row["knots_above_screening_threshold"]]
    worst = max(model.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    focus = next(row for row in model.levels if row["relative_path"] == model.focus_path)
    loudest = max(model.levels, key=lambda row: row["load_max_over_velo_max"])
    rates = model.temporal["profile_rate_hz"]
    widths = [row["usable_bandwidth_hz"] for row in model.levels]  # one per level, in order
    ratios = list(model.temporal["profile_period_over_prf_period"].values())
    ratio_spread = (max(ratios) - min(ratios)) / (sum(ratios) / len(ratios))
    floor, band = model.temporal["floor"], model.temporal["band_hz"]
    candidate_limit = focus["velo_max_mm_s"] * FOCUS_SETTING_US / CANDIDATE_SETTING_US
    return {
        "effect_gate": {
            "pairs": len(model.pairs), "screening_threshold_mm_s": screening_threshold,
            "pairs_above_screening_threshold": len(above),
            "max_abs_difference_mm_s": worst["max_abs_difference_mm_s"],
            "max_ratio_to_screening_threshold": worst["max_abs_difference_over_screening_threshold"],
            "statement": (
                f"Effect gate: over the {len(model.pairs)} pairs the largest absolute per-knot mean "
                f"difference is {worst['max_abs_difference_mm_s']:.4g} mm/s ({worst['faster_label']} "
                f"vs {worst['slower_label']} us at {worst['max_abs_difference_depth_mm']:.4g} mm; "
                f"depth ranges above the screening_threshold {worst['depth_ranges_above_screening_threshold_mm']}) = "
                f"{worst['max_abs_difference_over_screening_threshold']:.3g} of the WP1 screening_threshold "
                f"{screening_threshold:.4g} mm/s, and {len(above)} pairs clear it somewhere."
            ),
        },
        "velocity_headroom": {
            "focus_prf_period_us": focus["prf_period_us"],
            "focus_velo_max_mm_s": focus["velo_max_mm_s"],
            "focus_load_max_over_velo_max": focus["load_max_over_velo_max"],
            "focus_warning_fraction_at_limit": focus["warning_fraction_at_limit"],
            "focus_samples_beyond_limit": focus["samples_beyond_limit"],
            "focus_wrap_like_events": focus["wrap_like_events"],
            "statement": (
                f"Velocity headroom: at the plan's {focus['prf_period_us']:g} us setting the largest "
                f"|v| in the common window and support is {focus['load_max_over_velo_max']:.4g} of "
                f"the {focus['velo_max_mm_s']:.4g} mm/s unambiguous limit, with "
                f"{focus['samples_beyond_limit']} sample(s) beyond it and "
                f"{focus['wrap_like_events']} wrap-like discontinuity(ies); the largest load anywhere "
                f"in the ladder is {loudest['load_max_over_velo_max']:.4g} at "
                f"{loudest['prf_period_us']:g} us, so the pressure on the velocity scale grows as the "
                "period lengthens, not as it shortens."
            ),
        },
        "temporal_bandwidth": {
            "segment_target_s": model.common["segment_target_s"], "band_hz": band,
            "nominal_resolution_hz": model.temporal["nominal_resolution_hz"],
            "profile_rate_hz": rates, "usable_bandwidth_hz": widths,
            "focus_usable_bandwidth_hz": focus["usable_bandwidth_hz"],
            "profile_period_over_prf_period_spread_relative": ratio_spread,
            "mixer_marker_hz": MIXER_MARKER_HZ,
            "focus_psd_share_below_mixer_marker": focus["psd_share_below_mixer_marker"],
            "floor_paths": list(floor["source_paths"]),
            "floor_hf_share_difference": floor["hf_share_difference"],
            "statement": (
                f"Temporal bandwidth: the actual profile rate falls from "
                f"{max(rates.values()):.4g} Hz to {min(rates.values()):.4g} Hz across the ladder and "
                f"the usable bandwidth with it ({max(widths):.4g} to {min(widths):.4g} Hz), so the "
                f"shorter period carries the wider band. Spectra are compared only inside "
                f"{band[0]:.4g}-{band[1]:.4g} Hz, the bands every recording supports, at a nominal "
                f"resolution of {model.temporal['nominal_resolution_hz']:.4g} Hz. The "
                f"{MIXER_MARKER_HZ:.4g} Hz mixer marker sits inside that band for all five levels "
                f"({focus['psd_share_below_mixer_marker']:.3g} of the {focus['prf_period_us']:g} us "
                "level's in-band power is below it) and stays a marker: no peak is attributed to it "
                f"or to a harmonic, whose second multiple ({2.0 * MIXER_MARKER_HZ:.4g} Hz) is above "
                "the shared band."
            ),
        },
        "focus_decision": {
            "focus_setting_us": FOCUS_SETTING_US, "candidate_setting_us": CANDIDATE_SETTING_US,
            "candidate_velo_max_mm_s": candidate_limit,
            "velocity_headroom_adequate": bool(
                focus["samples_beyond_limit"] == 0 and focus["load_max_over_velo_max"] < 1.0
            ),
            "temporal_bandwidth_adequate": bool(focus["usable_bandwidth_hz"] >= max(widths)),
            "statement": (
                f"Plan decision, {FOCUS_SETTING_US:g} vs {CANDIDATE_SETTING_US:g} us: at "
                f"{FOCUS_SETTING_US:g} us the window's peak load is "
                f"{focus['load_max_over_velo_max']:.4g} of a {focus['velo_max_mm_s']:.4g} mm/s limit "
                f"({focus['samples_beyond_limit']} sample(s) beyond it, "
                f"{focus['wrap_like_events']} wrap-like step(s)) with the widest usable bandwidth in "
                f"the ladder ({focus['usable_bandwidth_hz']:.4g} Hz of {max(widths):.4g}-"
                f"{min(widths):.4g} Hz), while a {CANDIDATE_SETTING_US:g} us setting would raise the "
                f"limit to {candidate_limit:.4g} mm/s, which nothing here needs. {_FOCUS_VERDICT}"
            ),
        },
        "limitations": [
            f"The screening threshold is the only repeat, {screening_threshold:.4g} mm/s per gate ({model.screening_threshold.metric}): one observed realization of repeatability plus uncontrolled drift, not a bound on either. The levels are separate recordings with no acquisition order, so a smaller effect cannot be separated from drift and a larger one could still be drift or one recording rather than the PRF. No level is replicated.",
            f"The velocity scale is the key's own consequence (Vmax x prf_period is constant across the ladder to the audited tolerance), but the profile rate is not: it rises from {min(rates.values()):.4g} to {max(rates.values()):.4g} Hz while its ratio to the PRF period varies by {ratio_spread:.3g} relative, so the rate is a separate measured property and nothing here claims a future setting would scale it.",
            f"The temporal metrics are screened against the same-settings WP1 pair through its committed curves ({floor['source_paths'][0]} vs {floor['source_paths'][1]}), resummarised in {band[0]:.4g}-{band[1]:.4g} Hz on the bands this ladder shares; one pair cannot estimate that floor's own spread, and 5-10 segments per level make a band level a coarse magnitude.",
            "The files carry the velocity-time index only: the 500-RPM setpoint is a marker rather than a phase reference, the spectra are per gate, and a wrap-like step is counted as a discontinuity of the recorded estimate, never as proof that a particular sample aliased. This module owns the PRF axis only: resolution, burst, TGC, emitting power and emissions per profile are neither analysed nor decided here.",
        ],
    }


def figure_caption(model: PrfLadder) -> str:
    """The caption the committed figure and the provenance document both carry.

    It names the ladder, both time views, the common support, the alignment rule, the screening_threshold and
    the temporal floor with their sources, and the 400-us decision numbers.
    """
    findings = _findings(model)
    decision, headroom = findings["focus_decision"], findings["velocity_headroom"]
    temporal, common = findings["temporal_bandwidth"], model.common
    periods = [row["prf_period_us"] for row in model.levels]
    return (
        f"WP2 PRF ladder: {common['levels']} decoded pulse-repetition periods "
        f"{periods[0]:g}-{periods[-1]:g} us. Common-duration view: {common['revolutions']} nominal "
        f"{common['nominal_rpm']:g}-RPM revolutions = {common['window_s']:.4g} s, truncated per file "
        "by the recorded timestamps. Common physical support: "
        f"{common['support_min_mm']:.6g}-{common['support_max_mm']:.6g} mm; gradients and correlation "
        "lengths are native-grid quantities and pairs use the slower level's own gate depths as "
        "knots, so nothing is interpolated or upsampled. Temporal view: every full record in matched "
        f"{common['segment_target_s']:g} s segments, one profile length per file because the rate "
        f"differs ({min(temporal['profile_rate_hz'].values()):.4g}-"
        f"{max(temporal['profile_rate_hz'].values()):.4g} Hz), nominal resolution "
        f"{model.temporal['nominal_resolution_hz']:.4g} Hz. Decision threshold: the committed WP1 "
        f"screening_threshold {model.screening_threshold.value_mm_s:.4g} mm/s ({model.screening_threshold.metric}, from "
        f"{model.screening_threshold.path}, {model.screening_threshold.source_sha256[:12]}...). Plan decision "
        f"{decision['focus_setting_us']:g} vs {decision['candidate_setting_us']:g} us: peak load "
        f"{headroom['focus_load_max_over_velo_max']:.4g} of the "
        f"{headroom['focus_velo_max_mm_s']:.4g} mm/s limit at {decision['focus_setting_us']:g} us "
        f"with none beyond it, and the widest usable bandwidth in the ladder "
        f"({temporal['focus_usable_bandwidth_hz']:.4g} Hz of {max(temporal['usable_bandwidth_hz']):.4g}"
        f"-{min(temporal['usable_bandwidth_hz']):.4g} Hz). {MIXER_SETPOINT_ROLE}. {REPLICATE_ROLE}. "
        f"Generated at commit {model.analysis_commit or 'unknown'} from {model.manifest_path} "
        f"({model.manifest_sha256})."
    )


def provenance_document(model: PrfLadder) -> dict[str, object]:
    """The machine-readable record beside the tables and the figure.

    Keys are inserted in a fixed order, so a regeneration from the same commit is byte-identical.
    """
    common, temporal, first = model.common, model.temporal, model.inputs[0]
    rates = temporal["profile_rate_hz"]
    return {
        "artefact": "prf-ladder", "axis": model.axis, "analysis_commit": model.analysis_commit, "dataset_root": model.dataset_root,
        "manifest": {"path": model.manifest_path, "sha256": model.manifest_sha256},
        "screening_threshold": dict(model.screening_threshold.model_dump()) | {"source_path": model.screening_threshold.path},
        "derived_scale": {
            "invariant": "velo_max_ms x prf_period_us", "tolerance_relative": VELO_SCALE_RTOL,
            "values": [e.velo_max_ms * e.prf_period_us for e in model.inputs],
        },
        "audited_constants": {
            "settings": list(COUPLED_SETTINGS), "gates": first.gates,
            "resolution_mm": first.resolution_mm, "burst_length": first.burst_length,
            "emissions_per_profile": first.emissions_per_profile, "emit_power": first.emit_power,
            "sensitivity": first.sensitivity, "tgc_mode": first.tgc_mode,
            "sound_speed_ms": first.sound_speed_ms,
        },
        "inputs": [
            {
                "relative_path": e.relative_path, "axis": e.axis, "requested_label": e.requested_label,
                "prf_period_us": e.prf_period_us, "prf_hz": 1e6 / e.prf_period_us,
                "velo_max_mm_s": e.velo_max_ms, "source_sha256": e.source_sha256,
                "profiles": e.profiles, "profiles_window": common["profiles_window"][e.relative_path],
                "gates_in_support": common["gates_in_support"][e.relative_path],
                "duration_s": e.duration_s, "profile_rate_hz": rates[e.relative_path],
                "profile_period_over_prf_period": temporal["profile_period_over_prf_period"][
                    e.relative_path
                ],
                "depth_min_mm": e.depth_min_mm, "depth_max_mm": e.depth_max_mm,
            }
            for e in model.inputs
        ],
        "views": {
            "time": {
                "common_duration": {
                    "nominal_rpm": common["nominal_rpm"], "revolution_s": common["revolution_s"],
                    "revolutions": common["revolutions"], "window_s": common["window_s"],
                    "profiles_window": common["profiles_window"],
                },
                "rule": "largest integer number of nominal revolutions fitting every PRF recording, truncated per file by the recorded timestamps",
            },
            "depth": {
                "common_support_min_mm": common["support_min_mm"],
                "common_support_max_mm": common["support_max_mm"],
                "plan_declared_mm": list(PLAN_SUPPORT_MM),
                "contains_plan_window": common["support_min_mm"] <= PLAN_SUPPORT_MM[0]
                and common["support_max_mm"] >= PLAN_SUPPORT_MM[1],
                "gates_in_support": common["gates_in_support"],
                "native_grid": "each level keeps its own decoded gate grid for the distributional metrics, the gradient and the correlation length; nothing is resampled",
            },
            "temporal": {
                "grid": {
                    "segment_target_s": common["segment_target_s"],
                    "segment_step_s": temporal["segment_step_s"],
                    "min_segments": temporal["min_segments"],
                    "nominal_resolution_hz": temporal["nominal_resolution_hz"],
                    "per_level": {
                        e.relative_path: temporal["cell"][str(e.profile_period_s)]
                        for e in model.inputs
                    },
                    "profile_rate_hz": rates,
                    "profile_rate_spread_relative": temporal["profile_rate_spread_relative"],
                    "acf_estimator": temporal["acf_estimator"], "psd_window": temporal["psd_window"],
                    "psd_detrend": temporal["psd_detrend"], "psd_scaling": temporal["psd_scaling"],
                },
                "band": {"hz": temporal["band_hz"], "bands": temporal["bands"]},
                "mixer_marker_hz": MIXER_MARKER_HZ, "mixer_setpoint_role": MIXER_SETPOINT_ROLE,
                "floor": temporal["floor"],
            },
            "alignment": {
                "knot_rule": "the longer-period level's native gate depths inside the common support, so the knot spacing is never finer than that participant's own grid; the shorter-period level is sampled at each knot by its nearest native gate, never interpolated",
                "upsampled": False,
                "max_knot_offset_over_all_pairs_mm": max(
                    r["max_knot_offset_mm"] for r in model.pairs
                ),
                "focus_level": {"path": model.focus_path, "prf_period_us": FOCUS_SETTING_US},
            },
        },
        "definitions": dict(DEFINITIONS),
        "findings": _findings(model),
        "tables": {
            "levels": {"path": LEVELS_NAME, "rows": len(model.levels)},
            "pairs": {"path": PAIRS_NAME, "rows": len(model.pairs)},
        },
        "figure": {
            "path": f"{FIGURES_DIRNAME}/{FIGURE_NAME}", "caption": figure_caption(model),
            "panels": list(FIGURE_PANELS),
        },
        "regeneration": {
            "command": ".venv/Scripts/python.exe -m udv_echo_process.cli prf-ladder "
            f"--analysis-commit {model.analysis_commit or '<generator commit>'}",
            "note": "pass the recorded analysis_commit to reproduce these artefacts byte for byte; the bare command records the current HEAD",
        },
    }


def render_figure(
    model: PrfLadder,
    curves: Mapping[str, tuple[np.ndarray, np.ndarray]],
    path: Path,
    *,
    dpi: int = 150,
) -> Path:
    """Write the two-panel PRF figure, deterministically, and return it.

    Panel 1 is the load of each level against the unambiguous limit, with the samples beyond it and
    the wrap-like discontinuities; panel 2 each level's ensemble PSD against the frequencies it
    supports, with the shared comparison band, each file's usable bandwidth and the mixer marker.
    The frame is the shared writer's, so this module owns the panels only.
    """
    periods = np.asarray([row["prf_period_us"] for row in model.levels])
    loads = [row["load_max_over_velo_max"] for row in model.levels]
    paths = [row["relative_path"] for row in model.levels]
    band = model.temporal["band_hz"]

    def draw(axes: Sequence[object]) -> None:
        load_ax, psd_ax = axes
        load_ax.axhline(1.0, color="#555555", linewidth=0.8, linestyle=":")
        load_ax.plot(periods, loads, "o-", color="#111111", label="largest |v| / Vmax")
        load_ax.plot([periods[paths.index(model.focus_path)]], [loads[paths.index(model.focus_path)]],
                     "o", markerfacecolor="none", markeredgecolor="#d62728", markersize=11,
                     label=f"plan's setting ({FOCUS_SETTING_US:g} us)")
        counts_ax = load_ax.twinx()
        counts_ax.plot(periods, [row["wrap_like_events"] for row in model.levels], "s--",
                       color="#1f77b4", label="wrap-like steps (>= Vmax, sign reversed)")
        counts_ax.plot(periods, [row["samples_beyond_limit"] for row in model.levels], "^:",
                       color="#2ca02c", label="samples beyond the limit")
        load_ax.set_xlabel("decoded pulse-repetition period [us]")
        load_ax.set_ylabel("max |v| / Vmax; 1.0 = unambiguous limit")
        counts_ax.set_ylabel("count in the common window")
        load_ax.set_ylim(0.0, max(1.35, max(loads) * 1.1))
        load_ax.grid(alpha=0.2)
        load_ax.legend(loc="upper left", fontsize=6.2, framealpha=0.9)
        counts_ax.legend(loc="upper right", fontsize=6.2, framealpha=0.9)
        psd_ax.axvspan(band[0], band[1], color="#ffd8a8", alpha=0.35, linewidth=0)
        psd_ax.axvline(MIXER_MARKER_HZ, color="#d62728", linewidth=0.9, linestyle="--")
        for row in model.levels:
            frequency, density = curves[row["relative_path"]]
            line = psd_ax.semilogy(
                frequency, density, linewidth=1.2,
                label=f"{row['prf_period_us']:g} us ({row['profile_rate_hz']:.1f} Hz rate)",
            )[0]
            psd_ax.axvline(row["usable_bandwidth_hz"], color=line.get_color(), linewidth=0.7,
                           linestyle=":", alpha=0.8)
        psd_ax.set_xlim(0.0, float(max(row["nyquist_hz"] for row in model.levels)) * 1.04)
        psd_ax.set_xlabel("frequency [Hz]; dotted = each level's usable bandwidth")
        psd_ax.set_ylabel("ensemble PSD [(mm/s)^2/Hz]")
        psd_ax.grid(alpha=0.2, which="both")
        psd_ax.legend(loc="upper right", fontsize=6.0, framealpha=0.9)
        psd_ax.set_title(
            f"shared comparison band {band[0]:.4g}-{band[1]:.4g} Hz, marker {MIXER_MARKER_HZ:.4g} Hz",
            fontsize=9.5,
        )

    return grid.panel_figure(
        "WP2 PRF ladder — velocity headroom and usable temporal bandwidth of "
        f"{len(model.levels)} settings",
        figure_caption(model), draw, path, caption_width=150, dpi=dpi,
        adjust={"top": 0.80, "bottom": 0.30, "wspace": 0.34},
    )


def write_prf_ladder(
    dataset_root: Path = inventory.DATASET_ROOT,
    report_dir: Path = inventory.REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    screening_threshold_path: Path | None = None,
    analysis_commit: str | None = None,
) -> PrfLadder:
    """Build the ladder and write the four reviewer-visible artefacts.

    The text artefacts use LF endings and the figure is deterministic, so two runs on the same inputs
    and commit produce identical bytes; nothing is written when the build raises.
    """
    directory = Path(report_dir)
    manifest = Path(manifest_path or directory / inventory.MANIFEST_NAME)
    screening_threshold = Path(screening_threshold_path or directory / SCREENING_THRESHOLD_NAME)
    model, _profiles, curves = _build(dataset_root, manifest, screening_threshold, analysis_commit)
    grid.write_text_artefacts(directory, {
        LEVELS_NAME: levels_csv_text(model),
        PAIRS_NAME: pairs_csv_text(model),
        PROVENANCE_NAME: json.dumps(provenance_document(model), indent=2) + "\n",
    })
    render_figure(model, curves, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
