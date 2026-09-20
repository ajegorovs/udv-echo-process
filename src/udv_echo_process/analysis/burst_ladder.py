"""WP2, burst-length axis — the measured cycle ladder against the sole-pair screening threshold.

The committed sweep holds a 12-point burst-length ladder — one base-state recording per
requested cycle count, 2 (`burst_len/2.BDD`) to 32 (`burst_len/32.BDD`), over the same ~100 mm
window on the same 1.85 mm gate grid (plan §2). This module answers the plan's burst question
from the ``burst_len`` rows of the WP0 manifest, never a filename list (plan §4 WP2 gate):
where the empirical transition is, and whether 18 can be separated from 20 cycles.

One build produces the common views (plan §3.1, §3.2), the per-level native-grid metrics, the
matched full-record temporal view with its repeat floor, every unordered pair against the
committed WP1 screening_threshold (with the depth ranges where a difference clears it), the knees of the
dropout/variance/smoothing/bandwidth metrics, and the four artefacts.

The input binding is **not** written here: the manifest selection, the decode with its
hash/cell/grid re-checks, the clean-OFAT audit, the common views, the native-grid metrics, the
knot alignment, the committed WP1 screening_threshold and temporal-floor readers, the knees and the writers
belong to the shared layer (:mod:`udv_echo_process.analysis._native_grid`), which this axis
drives with its own axis name, key cell, settings and columns — and which the resolution, PRF and
TGC/power axes drive with theirs, so no axis can drift from the inventory contract its siblings
honour. Selection is by decoded **scientific fingerprint** (:data:`ELIGIBILITY`), never by folder
(plan §8.3 step 2, R1/R4): the cycle count is the only setting this axis may move, so every
recording sharing the rest of the fingerprint is eligible, and the dataset's two reference
recordings — both burst 10, one of them under the ``res`` folder — are two named realizations of
that one level. No ``burst_len`` row requests burst 10, so the committed ladder does not hold it
yet and the level is recorded as eligible evidence for the setting-based rebuild of §8.3 step 5.
What is left here is what is burst-specific: the columns, the rows, the findings, the
caption and the panels.

Only the decoded burst length may differ across the files, so a coupled ladder is refused rather
than analysed (plan §2). No profile or gate is an independent experimental replicate, the levels
carry no acquisition order, and no p-value is produced (plan §3.3). Burst axis only: resolution,
PRF, TGC/power and emissions are out of scope, 500 RPM is a marker (8.33 Hz) never a phase
reference, and the two ladders meet only at the reference, so pitch x burst interaction is not
estimable here.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis import _native_grid as grid
from udv_echo_process.analysis import reference_repeat as wp1
from udv_echo_process.analysis import sweep_inventory as inventory
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: The manifest axis this module owns, and the reviewer-visible artefacts.
AXIS = "burst_len"
LEVELS_NAME, PAIRS_NAME = "burst-levels.csv", "burst-pairs.csv"
PROVENANCE_NAME, FIGURE_NAME = "burst-ladder.provenance.json", "burst-ladder.png"
FIGURES_DIRNAME, SCREENING_THRESHOLD_NAME = "figures", "reference-repeat.provenance.json"

#: The plan's two questions — the region to highlight and the decision to make — both selected
#: from the manifest by decoded cycle count, never by filename.
FOCUS_WINDOW_CYCLES: tuple[int, int] = (16, 20)
FOCUS_PAIR_CYCLES: tuple[int, int] = (18, 20)

#: The plan's declared support window; the band every temporal metric integrates over and the
#: frequency above which power counts as high-frequency; the decoded settings that must *not*
#: move, because this axis changes the burst length only; and the manifest cells this axis
#: re-checks against every decoded recording (the shape and timing its summaries rest on).
PLAN_SUPPORT_MM: tuple[float, float] = (10.163, 96.743)
PSD_BAND_HZ: tuple[float, float] = (0.5, 20.0)
PSD_HF_ABOVE_HZ = 10.0
COUPLED_SETTINGS: tuple[str, ...] = (
    "prf_period_us", "resolution_mm", "emissions_per_profile", "emit_power", "sensitivity",
    "tgc_mode", "sound_speed_ms", "velo_max_ms", "gates",
)
VERIFIED_CELLS: tuple[str, ...] = (
    "profiles", "gates", "duration_s", "resolution_mm", "prf_period_us", "burst_length",
    "emissions_per_profile", "emit_power", "sensitivity", "tgc_mode",
)

#: The axis's setting-based contract (plan §8.3 step 2, R1/R4): the burst length is the only decoded
#: setting this ladder may move, so every recording sharing the rest of the fingerprint - whatever
#: folder its row sits in - is eligible. The dataset's two reference recordings share burst 10, a
#: level no ``burst_len`` row requests, and are recorded as its two realizations for the
#: setting-based rebuild of §8.3 step 5.
ELIGIBILITY = grid.AxisEligibility(
    axis=AXIS, ladder_label="burst", varied=("burst_length",)
)

#: Column order of the two tables: the dict rows of :class:`BurstLadder` carry exactly these
#: keys, so a table and its model cannot drift.
LEVEL_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "cycles", "profiles_window",
    "gates_in_support", "pitch_mm", "mean_mm_s", "robust_spread_mm_s", "rms_mm_s",
    "zero_fraction", "gradient_median_abs_mm_s_per_mm", "gradient_max_abs_mm_s_per_mm",
    "correlation_length_mm", "correlation_length_over_pitch", "acf_e_folding_lag_s",
    "psd_hf_share", "psd_centroid_hz", "psd_bandwidth_hz",
)
PAIR_COLUMNS: tuple[str, ...] = (
    "axis", "short_path", "short_label", "short_cycles", "long_path", "long_label",
    "long_cycles", "cycle_gap", "knots", "knot_spacing_mm", "max_knot_offset_mm",
    "mean_abs_difference_mm_s", "max_abs_difference_mm_s", "max_abs_difference_depth_mm",
    "knots_above_screening_threshold", "max_abs_difference_over_screening_threshold",
    "depth_ranges_above_screening_threshold_mm", "correlation_length_change_mm",
    "gradient_median_change_mm_s_per_mm", "robust_spread_change_mm_s",
    "zero_fraction_change", "hf_share_change", "acf_e_folding_lag_change_s",
)

#: The metrics the knees report: dropout, variance, spatial smoothing and bandwidth.
KNEE_METRICS: tuple[str, ...] = (
    "zero_fraction", "robust_spread_mm_s", "rms_mm_s", "correlation_length_mm",
    "gradient_max_abs_mm_s_per_mm", "psd_hf_share", "acf_e_folding_lag_s",
)

#: The error class of every message this module raises; the shared helpers raise the same class,
#: so one name covers a helper refusal and an axis refusal. The manifest-pinned level record is
#: the shape WP1 already binds, so the WP1 temporal estimator is reused.
BurstLadderError = grid.NativeGridError
LevelInput = wp1.RepeatInput
#: The knee of a ladder is axis-agnostic machinery: the shared layer's, re-exported here.
largest_step = grid.largest_step
#: The WP0 dataset and report locations this axis reads and writes by default, and the nominal
#: revolution its common-duration view counts in.
NOMINAL_REVOLUTION_S = wp1.NOMINAL_REVOLUTION_S
DATASET_ROOT = inventory.DATASET_ROOT
MANIFEST_NAME = inventory.MANIFEST_NAME
REPORT_DIR = inventory.REPORT_DIR


class BurstLadder(ValueModel):
    """The WP2 burst result: the level rows, the pair rows and the two matched views.

    ``levels`` and ``pairs`` are dict rows keyed by the declared column tuples; ``temporal``
    carries the ``floor`` read from the committed WP1 provenance.
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
    timestamps: dict[str, object]
    focus_pair: tuple[str, str]
    levels: tuple[dict[str, object], ...]
    pairs: tuple[dict[str, object], ...]

    @model_validator(mode="after")
    def _check_the_ladder_is_internally_consistent(self) -> BurstLadder:
        if [row.get("relative_path") for row in self.levels] != [
            entry.relative_path for entry in self.inputs
        ]:
            raise ValueError("every level must appear exactly once, in input order")
        for columns, rows in ((LEVEL_COLUMNS, self.levels), (PAIR_COLUMNS, self.pairs)):
            if any(tuple(row) != columns for row in rows):
                raise ValueError("a row must carry exactly the declared columns")
        if any(b <= a for a, b in itertools.pairwise(row["cycles"] for row in self.levels)):
            raise ValueError("levels must be ordered by increasing cycle count")
        if len(self.pairs) != len(self.levels) * (len(self.levels) - 1) // 2:
            raise ValueError(f"expected every unordered pair, got {len(self.pairs)} pairs")
        if self.focus_pair not in {(row["short_path"], row["long_path"]) for row in self.pairs}:
            raise ValueError(f"focus pair {self.focus_pair} must be one of the pairs")
        if self.screening_threshold.value_mm_s <= 0.0:
            raise ValueError("the repeatability screening_threshold must be positive")
        if self.timestamps.get("retained") is not True:
            raise ValueError("the uniform temporal grid must be measured and retained, not assumed")
        measured = [
            item["relative_path"] for item in self.timestamps["per_input"]  # type: ignore[index]
        ]
        if measured != [entry.relative_path for entry in self.inputs]:
            raise ValueError("the timestamp measurement must cover every level, in input order")
        return self


def _cycles_of(row: Mapping[str, str], manifest_path: Path) -> int:
    """The row's decoded cycle count, refused unless it is a positive integer."""
    cell = (row.get("burst_length") or "").strip()
    try:
        cycles = int(cell)
    except ValueError:
        raise BurstLadderError(
            f"{row.get('relative_path')}: manifest burst_length={cell!r} in {manifest_path} is "
            "not an integer cycle count"
        ) from None
    if cycles < 1:
        raise BurstLadderError(f"{row.get('relative_path')}: burst_length={cell!r} <= 0")
    return cycles


def select_level_rows(manifest_path: Path) -> tuple[dict[str, str], ...]:
    """The representative row of every ``burst_len`` level the axis itself requested, by cycles.

    The ladder is bound to the WP0 manifest, never to a filename list: the selection, the ordering
    and the refusals are the shared axis-input layer's, driven with this axis's own contract. A
    same-settings recording sitting in another folder is eligible (:func:`level_groups`) but is not
    one of this axis's requested levels, so it does not redefine the committed ladder on its own.
    """
    path = Path(manifest_path)
    return grid.select_axis_rows(
        path, eligibility=ELIGIBILITY, order_key=lambda row: _cycles_of(row, path),
        order_label="cycle count",
    )


def level_groups(manifest_path: Path) -> tuple[grid.LevelGroup, ...]:
    """Every eligible ``burst`` level with all its realizations, by cycle count then path.

    The dataset's two reference recordings share burst 10 and are two named realizations of that one
    level, whichever folder each sits in (plan §8.3 step 2, R1). No ``burst_len`` row requests it, so
    it is eligible and recorded but not yet one of the ladder's levels: the setting-based rebuild of
    §8.3 step 5 joins it and renders the realizations into the provenance.
    """
    path = Path(manifest_path)
    return grid.level_groups(
        path, eligibility=ELIGIBILITY, order_key=lambda row: _cycles_of(row, path),
        order_label="cycle count",
    )


def _read_level(
    dataset_root: Path, row: dict[str, str]
) -> tuple[LevelInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected level, returning ``(entry, values, time_s, depths)``.

    The entry is the manifest-pinned WP1 record the temporal estimator takes, and every check on
    the arrays is the shared axis-input layer's, against :data:`VERIFIED_CELLS`.
    """
    level = grid.read_decoded_level(Path(dataset_root), row, cells=VERIFIED_CELLS)
    observed, config = level.observed, level.config
    return (
        LevelInput(
            relative_path=level.relative_path, axis=level.axis,
            requested_label=level.requested_label, source_sha256=level.source_sha256,
            profiles=int(level.values.shape[0]), gates=int(level.values.shape[1]),
            duration_s=float(observed["duration_s"]),
            profile_period_s=float(observed["duration_s"] / (level.time_s.size - 1)),
            depth_min_mm=float(observed["depth_min_mm"]),
            depth_max_mm=float(observed["depth_max_mm"]),
            prf_period_us=float(observed["prf_period_us"]),
            resolution_mm=float(config.resolution_mm), burst_length=int(config.burst_length),
            emissions_per_profile=int(config.emissions_per_profile),
            emit_power=str(config.emit_power), sensitivity=str(config.sensitivity),
            tgc_mode=str(config.tgc_mode), sound_speed_ms=float(config.sound_speed_ms),
            velo_max_ms=float(config.velo_max_ms),
        ),
        level.values,
        level.time_s,
        level.depths,
    )


def _require_clean_ofat(entries: Sequence[LevelInput]) -> None:
    """Refuse a ladder where a setting other than the burst length moved.

    Decoded settings are compared, never folder names (plan §2): the shared audit, against
    :data:`COUPLED_SETTINGS`.
    """
    grid.require_clean_ofat(entries, COUPLED_SETTINGS, axis_label="burst-length")


def level_row(
    entry: LevelInput, metrics: grid.LevelMetrics, series: wp1.TemporalSeries
) -> dict[str, object]:
    """One level's row: the common-duration window on its own native grid.

    The distributional and spatial metrics are the shared metric layer's, on the supported native
    grid and before any alignment; the temporal ones summarise the level's own full-record
    ensemble ACF/PSD with the same shared band summary the WP1 floor uses.
    """
    psd = grid.psd_band_summary(
        series.frequency_hz, series.psd_mean_mm2_s2_per_hz, PSD_BAND_HZ,
        hf_above_hz=PSD_HF_ABOVE_HZ,
    )
    return {
        "axis": entry.axis, "relative_path": entry.relative_path,
        "requested_label": entry.requested_label, "cycles": entry.burst_length,
        "profiles_window": metrics.profiles_window,
        "gates_in_support": metrics.supported_gates,
        "pitch_mm": entry.resolution_mm, "mean_mm_s": float(metrics.means.mean()),
        "robust_spread_mm_s": float(
            np.percentile(metrics.means, 75.0) - np.percentile(metrics.means, 25.0)
        ),
        "rms_mm_s": float(np.sqrt(np.mean(np.square(metrics.supported)))),
        "zero_fraction": float(
            np.count_nonzero(metrics.supported == 0.0) / metrics.supported.size
        ),
        "gradient_median_abs_mm_s_per_mm": metrics.gradient.median_abs_mm_s_per_mm,
        "gradient_max_abs_mm_s_per_mm": metrics.gradient.max_abs_mm_s_per_mm,
        "correlation_length_mm": metrics.correlation.length_mm,
        "correlation_length_over_pitch": metrics.correlation.length_mm / entry.resolution_mm,
        "acf_e_folding_lag_s": series.acf_e_folding_lag_s,
        "psd_hf_share": psd["hf_share"], "psd_centroid_hz": psd["centroid_hz"],
        "psd_bandwidth_hz": psd["bandwidth_hz"],
    }


def pair_row(
    short: Mapping[str, object],
    short_profile: tuple[np.ndarray, np.ndarray],
    long: Mapping[str, object],
    long_profile: tuple[np.ndarray, np.ndarray],
    *,
    support: tuple[float, float],
    screening_threshold: grid.ScreeningThresholdBinding,
) -> dict[str, object]:
    """Compare a short-burst level with a longer-burst one on the shared knots.

    Each ``*_profile`` is ``(gate_depths_mm, per-gate time mean)``. The knots are the *longer*
    pulse's native gate depths inside the common support; the shorter profile is sampled there by
    the shared nearest-native-gate rule, and the difference is the signed ``short - long`` mm/s.
    """
    if short["cycles"] >= long["cycles"]:
        raise BurstLadderError(
            f"a pair is (short, long): {short['relative_path']} at {short['cycles']} cycles is "
            f"not shorter than {long['relative_path']} at {long['cycles']}"
        )
    short_depths, short_mean = (np.asarray(part, dtype=float) for part in short_profile)
    long_depths, long_mean = (np.asarray(part, dtype=float) for part in long_profile)
    aligned = grid.align_on_knots(
        short_depths, short_mean, long_depths, long_mean, path=str(short["relative_path"]),
        support=support, threshold_mm_s=screening_threshold.value_mm_s,
    )
    absolute, worst = aligned.absolute, aligned.worst
    return {
        "axis": short["axis"], "short_path": short["relative_path"],
        "short_label": short["requested_label"], "short_cycles": short["cycles"],
        "long_path": long["relative_path"], "long_label": long["requested_label"],
        "long_cycles": long["cycles"], "cycle_gap": long["cycles"] - short["cycles"],
        "knots": int(aligned.knots.size), "knot_spacing_mm": long["pitch_mm"],
        "max_knot_offset_mm": aligned.offset_mm,
        "mean_abs_difference_mm_s": float(absolute.mean()),
        "max_abs_difference_mm_s": float(absolute[worst]),
        "max_abs_difference_depth_mm": float(aligned.knots[worst]),
        "knots_above_screening_threshold": int(np.count_nonzero(aligned.flagged)),
        "max_abs_difference_over_screening_threshold": float(absolute[worst] / screening_threshold.value_mm_s),
        "depth_ranges_above_screening_threshold_mm": grid.depth_ranges(aligned.knots, aligned.flagged),
        "correlation_length_change_mm": long["correlation_length_mm"]
        - short["correlation_length_mm"],
        "gradient_median_change_mm_s_per_mm": long["gradient_median_abs_mm_s_per_mm"]
        - short["gradient_median_abs_mm_s_per_mm"],
        "robust_spread_change_mm_s": long["robust_spread_mm_s"] - short["robust_spread_mm_s"],
        "zero_fraction_change": long["zero_fraction"] - short["zero_fraction"],
        "hf_share_change": long["psd_hf_share"] - short["psd_hf_share"],
        "acf_e_folding_lag_change_s": long["acf_e_folding_lag_s"]
        - short["acf_e_folding_lag_s"],
    }


def _focus_pair(levels: Sequence[Mapping[str, object]]) -> tuple[str, str]:
    """The two levels the plan's 18-versus-20 question names, by decoded cycle count.

    Refuses a ladder without exactly one level at either named count.
    """
    selected: list[str] = []
    for cycles in FOCUS_PAIR_CYCLES:
        matches = [row for row in levels if row["cycles"] == cycles]
        if len(matches) != 1:
            raise BurstLadderError(
                f"the plan's question names {cycles} cycles, the manifest ladder holds "
                f"{len(matches)} level(s) at it; the selection is by cycle count, never a filename"
            )
        selected.append(str(matches[0]["relative_path"]))
    return selected[0], selected[1]


def _build(
    dataset_root: Path, manifest_path: Path, screening_threshold_path: Path, analysis_commit: str | None
) -> tuple[BurstLadder, dict[str, tuple[np.ndarray, np.ndarray]]]:
    """Build the ladder and return it beside each level's native mean profile."""
    rows = select_level_rows(manifest_path)  # a missing manifest is refused by name here
    manifest_sha256 = f"sha256:{grid.sha256_file(Path(manifest_path))}"
    screening_threshold = grid.read_screening_threshold(Path(screening_threshold_path), manifest_sha256)
    decoded = [_read_level(Path(dataset_root), row) for row in rows]
    entries = [entry for entry, *_ in decoded]
    _require_clean_ofat(entries)
    period = wp1.shared_profile_period_s([entry.profile_period_s for entry in entries])
    # R6: every level's recorded timestamps are measured against the uniform grid this period
    # places on them, at that level's own top-of-band frequency; a level over the tolerance stops
    # the build by name rather than being analysed on a grid it does not support.
    timestamp_grid = wp1.timestamp_grid([
        wp1.measure_timestamps(entry, time_s, f_max_hz=1.0 / (2.0 * period))
        for entry, _values, time_s, _depths in decoded
    ])
    revolutions = wp1.common_revolution_count([entry.duration_s for entry in entries])
    window_s = revolutions * wp1.NOMINAL_REVOLUTION_S
    support = grid.common_support([(entry.depth_min_mm, entry.depth_max_mm) for entry in entries])
    metrics = [
        grid.level_metrics(
            entry.relative_path, values, time_s, depths, window_s=window_s, support=support
        )
        for entry, values, time_s, depths in decoded
    ]
    series = [wp1.temporal_series(entry, values, period) for entry, values, _t, _d in decoded]
    levels = tuple(
        level_row(entry, own, own_series)
        for (entry, *_rest), own, own_series in zip(decoded, metrics, series, strict=True)
    )
    profiles = {
        entry.relative_path: (depths, own.per_gate["mean"])
        for (entry, _values, _time_s, depths), own in zip(decoded, metrics, strict=True)
    }
    pairs = tuple(
        pair_row(
            short, profiles[short["relative_path"]], long, profiles[long["relative_path"]],
            support=support, screening_threshold=screening_threshold,
        )
        for short, long in itertools.combinations(levels, 2)
    )
    floor = grid.read_temporal_floor(
        Path(screening_threshold_path), manifest_sha256, band_hz=PSD_BAND_HZ, hf_above_hz=PSD_HF_ABOVE_HZ
    )
    counts = {
        entry.relative_path: (own.profiles_window, own.supported_gates)
        for (entry, *_rest), own in zip(decoded, metrics, strict=True)
    }
    periods = [entry.profile_period_s for entry in entries]
    model = BurstLadder(
        dataset_root=Path(dataset_root).as_posix(),
        manifest_path=Path(manifest_path).as_posix(), manifest_sha256=manifest_sha256,
        screening_threshold=screening_threshold,
        analysis_commit=analysis_commit if analysis_commit is not None else current_revision(),
        eligibility=ELIGIBILITY,
        inputs=tuple(entries),
        groups=level_groups(manifest_path),
        common={
            "nominal_rpm": wp1.NOMINAL_RPM, "revolution_s": wp1.NOMINAL_REVOLUTION_S,
            "revolutions": revolutions, "window_s": window_s,
            "profiles_window": {path: window for path, (window, _g) in counts.items()},
            "gates_in_support": {path: gates for path, (_w, gates) in counts.items()},
            "support_min_mm": support[0], "support_max_mm": support[1],
            "levels": len(levels),
        },
        temporal={
            "profile_period_s": period, "profile_rate_hz": 1.0 / period,
            "period_spread_relative": (max(periods) - min(periods))
            / (sum(periods) / len(periods)),
            "wp1_period_relative_difference": abs(period - float(floor["profile_period_s"]))
            / period,
            "segment_profiles": wp1.SEGMENT_PROFILES,
            "segment_duration_s": (wp1.SEGMENT_PROFILES - 1) * period,
            "frequency_resolution_hz": (1.0 / period) / wp1.SEGMENT_PROFILES,
            "nyquist_hz": (1.0 / period) / 2.0, "band_hz": list(PSD_BAND_HZ),
            "levels": len(levels),
            "profiles_analysed": {own.relative_path: own.profiles_analysed for own in series},
            "segments": {own.relative_path: own.segments for own in series},
            "acf_estimator": wp1.ACF_ESTIMATOR, "psd_window": wp1.PSD_WINDOW,
            "psd_detrend": wp1.PSD_DETREND, "psd_scaling": wp1.PSD_SCALING, "floor": floor,
        },
        timestamps=wp1.timestamp_document(timestamp_grid),
        focus_pair=_focus_pair(levels), levels=levels, pairs=pairs,
    )
    return model, profiles


def build_burst_ladder(
    dataset_root: Path = inventory.DATASET_ROOT,
    manifest_path: Path = inventory.REPORT_DIR / inventory.MANIFEST_NAME,
    screening_threshold_path: Path = inventory.REPORT_DIR / SCREENING_THRESHOLD_NAME,
    *,
    analysis_commit: str | None = None,
) -> BurstLadder:
    """Build the WP2 burst ladder from the manifest-selected recordings.

    ``analysis_commit`` is the revision to record; ``None`` probes the checkout's short git SHA once
    (never blocking). A manifest, a WP1 screening_threshold, a coupled setting or a recording that contradicts
    its row is refused by name before anything is written.
    """
    return _build(dataset_root, Path(manifest_path), Path(screening_threshold_path), analysis_commit)[0]


#: Metric definitions, recorded verbatim in the provenance document (WP0's rule for its tables).
DEFINITIONS: dict[str, str] = {
    "cycles": "decoded burst length, re-checked against the manifest burst_length cell",
    "robust_spread": "IQR p75 - p25 across supported gates of the per-gate time means",
    "rms": "root mean square about zero over the common window and support, mm/s; not a sigma",
    "zero_fraction": "samples exactly 0.0 over the common window and support: dropout",
    "gradient": "median and maximum |mean[k+1] - mean[k]| / native pitch, mm/s per mm",
    "correlation_length": "first native lag whose normalized autocovariance < 1/e, mm",
    "difference": "signed short - long per-gate time mean at every common knot, mm/s",
    "screening_threshold": (
        "the committed sole-pair observed-discrepancy screening threshold "
        "max_gate_abs_mean_difference_mm_s, read from reference-repeat.provenance.json and "
        "pinned to this manifest's hash: the threshold every mean-profile effect is "
        "screened against. An effect above or below it is a screening outcome, not proof "
        "of a burst effect and not a bound on repeatability or uncontrolled drift"
    ),
    "figure": "both panels carry this document's caption and the generating commit",
    "knee": "the largest one-step change of a metric along the ladder, with monotonicity",
    "temporal_bandwidth": (
        "per level, from its full-record ensemble PSD inside 0.5-20 Hz: the spectral centroid and "
        "RMS bandwidth, the share of in-band power above 10 Hz, and the e-folding lag of the "
        "ensemble autocorrelation"
    ),
    "temporal_floor": (
        "the same temporal metrics for the two committed WP1 same-settings recordings, from the "
        "curves reference-repeat.provenance.json already records; their difference is the "
        "temporal screening threshold for those metrics — one observed realization of "
        "repeatability plus uncontrolled drift, not a bound on either"
    ),
    "replicates": "no profile and no gate is an independent experimental replicate",
    "time_view": "whole 500-RPM revolutions for every level; the full record for ACF/PSD",
    "depth_view": "each level on its own gate grid inside the common support",
    "comparability": "only the decoded burst length may differ across the ladder",
}

#: The two caveats that travel with every burst artefact, and the verdict :func:`_findings`
#: records so it cannot drift between the provenance document and the figure caption.
MIXER_SETPOINT_ROLE = (
    "nominal mixer marker only (500 RPM -> 8.33 Hz, one revolution = 0.12 s): no tachometer in "
    "these files, so the setpoint is not a phase reference"
)
REPLICATE_ROLE = (
    "no gate and no profile is an independent experimental replicate; the levels carry no "
    "acquisition order"
)
_FOCUS_VERDICT = (
    "Verdict: this evidence cannot support choosing 18 cycles over 20 or the reverse — the "
    "difference sits below the screening threshold and no level in the 16-20-cycle region "
    "falls above it against any other, so the screening outcome is that nothing is separated. "
    "Unidentifiable from this dataset: any burst effect "
    "smaller than the screening_threshold, and the pitch x burst interaction, because the two ladders meet "
    "only at the reference. What would overturn it: two recordings per cycle count in this "
    "region, which would separate the level effect from drift."
)

#: Panels of the reviewer-visible figure, in order.
FIGURE_PANELS: tuple[str, ...] = (
    (
        "dropout (zero fraction) and variance (robust spread, RMS) versus cycle count, with the "
        "plan's 16-20-cycle region shaded"
    ),
    (
        "the plan's question: the signed short - long per-gate mean difference of 18 versus 20 "
        "cycles at the shared knots against the WP1 screening_threshold band"
    ),
)


def levels_csv_text(model: BurstLadder) -> str:
    """Render ``burst-levels.csv`` from the model's own level rows."""
    return grid.csv_text(LEVEL_COLUMNS, model.levels)


def pairs_csv_text(model: BurstLadder) -> str:
    """Render ``burst-pairs.csv`` from the model's own pair rows."""
    return grid.csv_text(PAIR_COLUMNS, model.pairs)


def _findings(model: BurstLadder) -> dict[str, object]:
    """The plan's burst questions answered from the numbers the tables already carry.

    Every statement is composed from those values, so a regeneration says what it wrote. Nothing
    here is a p-value, a significance claim, or a decision about an axis this module does not own.
    """
    screening_threshold = model.screening_threshold.value_mm_s
    above = [row for row in model.pairs if row["knots_above_screening_threshold"]]
    worst = max(model.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    focus = next(
        row for row in model.pairs if (row["short_path"], row["long_path"]) == model.focus_pair
    )
    window = [
        row for row in model.pairs if FOCUS_WINDOW_CYCLES[0] <= row["short_cycles"]
        and row["long_cycles"] <= FOCUS_WINDOW_CYCLES[1]
    ]
    window_above = sum(1 for row in window if row["knots_above_screening_threshold"])
    floor = model.temporal["floor"]
    lengths = [row["correlation_length_mm"] for row in model.levels]
    shares = [row["psd_hf_share"] for row in model.levels]
    centroids = [row["psd_centroid_hz"] for row in model.levels]
    bandwidths = [row["psd_bandwidth_hz"] for row in model.levels]
    cycles = [row["cycles"] for row in model.levels]
    longest = model.levels[-1]
    at_the_longest = sum(1 for row in above if {row["short_label"], row["long_label"]} & {"28", "32"})
    return {
        "screening_threshold_gate": {
            "pairs": len(model.pairs), "screening_threshold_mm_s": screening_threshold,
            "pairs_above_screening_threshold": len(above),
            "clearances_involving_the_longest_bursts": at_the_longest,
            "max_abs_difference_mm_s": worst["max_abs_difference_mm_s"],
            "max_abs_difference_paths": [worst["short_path"], worst["long_path"]],
            "max_abs_difference_depth_mm": worst["max_abs_difference_depth_mm"],
            "max_ratio_to_screening_threshold": worst["max_abs_difference_over_screening_threshold"],
            "statement": (
                f"Effect gate: over the {len(model.pairs)} pairs the largest absolute per-knot "
                f"mean difference is {worst['max_abs_difference_mm_s']:.4g} mm/s "
                f"({worst['short_label']} vs {worst['long_label']} cycles) = "
                f"{worst['max_abs_difference_over_screening_threshold']:.3g} of the WP1 screening_threshold "
                f"{screening_threshold:.4g} mm/s; {len(above)} pairs put a knot above it, "
                f"{at_the_longest} of those at the longest bursts, and none covers the support."
            ),
        },
        "focus_18_vs_20": {
            "short_path": focus["short_path"], "long_path": focus["long_path"],
            "short_cycles": focus["short_cycles"], "long_cycles": focus["long_cycles"],
            "knots": focus["knots"], "knots_above_screening_threshold": focus["knots_above_screening_threshold"],
            "mean_abs_difference_mm_s": focus["mean_abs_difference_mm_s"],
            "max_abs_difference_mm_s": focus["max_abs_difference_mm_s"],
            "max_abs_difference_depth_mm": focus["max_abs_difference_depth_mm"],
            "ratio_to_screening_threshold": focus["max_abs_difference_over_screening_threshold"],
            "statement": (
                f"Plan question, 18 versus 20 cycles: the largest absolute per-knot mean "
                f"difference is {focus['max_abs_difference_mm_s']:.4g} mm/s at "
                f"{focus['max_abs_difference_depth_mm']:.4g} mm = "
                f"{focus['max_abs_difference_over_screening_threshold']:.3g} of the {screening_threshold:.4g} mm/s "
                f"screening_threshold, with {focus['knots_above_screening_threshold']} of {focus['knots']} knots above "
                f"it. {_FOCUS_VERDICT}"
            ),
        },
        "focus_window_16_20": {
            "cycles": list(FOCUS_WINDOW_CYCLES), "pairs": len(window),
            "pairs_above_screening_threshold": window_above,
            "max_ratio_to_screening_threshold": max(row["max_abs_difference_over_screening_threshold"] for row in window),
            "statement": (
                f"16-20-cycle region: {len(window)} unordered pairs, {window_above} of them "
                "clearing the screening_threshold, so no level differs from another by more than "
                "repeat-plus-drift there."
            ),
        },
        "knees": grid.knees(model.levels, KNEE_METRICS),
        "temporal_bandwidth": {
            "band_hz": list(PSD_BAND_HZ), "hf_above_hz": PSD_HF_ABOVE_HZ,
            "levels": len(model.levels), "segment_profiles": model.temporal["segment_profiles"],
            "frequency_resolution_hz": model.temporal["frequency_resolution_hz"],
            "nyquist_hz": model.temporal["nyquist_hz"],
            "hf_share_min": min(shares), "hf_share_max": max(shares),
            "centroid_hz_min": min(centroids), "centroid_hz_max": max(centroids),
            "bandwidth_hz_min": min(bandwidths), "bandwidth_hz_max": max(bandwidths),
            "floor_paths": list(floor["source_paths"]),
            "floor_hf_share_difference": floor["hf_share_difference"],
            "floor_centroid_difference_hz": floor["centroid_hz_difference"],
            "floor_bandwidth_difference_hz": floor["bandwidth_hz_difference"],
            "floor_e_folding_lag_difference_s": floor["e_folding_lag_difference_s"],
            "floor_band_level_difference_db": floor["band_max_abs_level_difference_db"],
            "statement": (
                f"Temporal bandwidth: the share of in-band power above {PSD_HF_ABOVE_HZ:g} Hz "
                f"ranges {min(shares):.4g}-{max(shares):.4g} (spread "
                f"{max(shares) - min(shares):.4g}) over the {len(model.levels)} levels, the "
                f"centroid {min(centroids):.4g}-{max(centroids):.4g} Hz and the RMS bandwidth "
                f"{min(bandwidths):.4g}-{max(bandwidths):.4g} Hz, against a same-settings repeat "
                f"floor of {floor['hf_share_difference']:.4g} in the same share and "
                f"{floor['bandwidth_hz_difference']:.4g} Hz in the bandwidth: a smaller bandwidth "
                "loss is not separable from repeat-plus-drift. The shortest bursts carry the "
                "largest share and the longest the smallest, the direction a longer pulse "
                "predicts, at a magnitude inside the floor."
            ),
        },
        "spatial_smoothing": {
            "levels": len(model.levels), "correlation_length_min_mm": min(lengths),
            "correlation_length_max_mm": max(lengths),
            "longest_path": longest["relative_path"], "longest_cycles": longest["cycles"],
            "longest_correlation_length_over_pitch": longest["correlation_length_over_pitch"],
            "gradient_max_abs_mm_s_per_mm": max(
                row["gradient_max_abs_mm_s_per_mm"] for row in model.levels
            ),
            "statement": (
                f"Spatial smoothing: the native correlation length of the depth-resolved mean "
                f"profile is {min(lengths):.4g}-{max(lengths):.4g} mm over {cycles[0]}-"
                f"{cycles[-1]} cycles ({min(lengths) / longest['pitch_mm']:.3g}-"
                f"{max(lengths) / longest['pitch_mm']:.3g} gate pitches), so the longer pulse is "
                "not shown to smooth the profile within this ladder."
            ),
        },
        "limitations": [
            (
                f"The screening threshold is the only repeat, {screening_threshold:.4g} mm/s per "
                f"gate ({model.screening_threshold.metric}): one observed realization of "
                "repeatability plus uncontrolled drift, not a bound on either. The levels are "
                "separate recordings with no acquisition order, so a smaller effect cannot be "
                "separated from drift and a larger one could still be drift or one recording "
                "rather than the burst length. No level is replicated."
            ),
            (
                f"Temporal metrics are screened against the same-settings WP1 pair through its "
                f"committed curves ({floor['source_paths'][0]} vs {floor['source_paths'][1]}), and "
                "one pair cannot estimate that floor's own spread."
            ),
            (
                "The file carries the velocity-time index only: the 500-RPM setpoint is a marker "
                "rather than a phase reference, the ensemble PSD is per gate, and nothing here "
                "separates a burst effect from aliased temporal noise or one recording's dropout."
            ),
            (
                "This module owns the burst-length axis only: resolution, PRF, TGC, emitting power "
                "and emissions per profile are neither analysed nor decided here, and the pitch x "
                "burst interaction is not estimable from this dataset."
            ),
        ],
    }


def figure_caption(model: BurstLadder) -> str:
    """The caption the committed figure and the provenance document both carry.

    It names the ladder, both time views, the common support, the alignment rule, the screening_threshold and
    the temporal floor with their sources, and the 18-versus-20 numbers.
    """
    findings = _findings(model)
    focus, temporal = findings["focus_18_vs_20"], findings["temporal_bandwidth"]
    window, common = findings["focus_window_16_20"], model.common
    cycles = [row["cycles"] for row in model.levels]
    return (
        f"WP2 burst ladder: {common['levels']} decoded burst lengths {cycles[0]}-{cycles[-1]} "
        f"cycles. Common-duration view: {common['revolutions']} nominal "
        f"{common['nominal_rpm']:g}-RPM revolutions = {common['window_s']:.4g} s, truncated per "
        f"file by the recorded timestamps. Common physical support: "
        f"{common['support_min_mm']:.6g}-{common['support_max_mm']:.6g} mm on the shared 1.85 mm "
        "grid, which contains the plan's declared window; gradients and correlation lengths are "
        "native-grid quantities and pairs use the longer pulse's own gate depths as knots, so "
        "nothing is interpolated or upsampled. Temporal view: full record in "
        f"{temporal['segment_profiles']}-profile segments on one shared "
        f"{model.temporal['profile_period_s']:.6g} s profile period, frequency resolution "
        f"{temporal['frequency_resolution_hz']:.4g} Hz, Nyquist {temporal['nyquist_hz']:.4g} Hz. "
        f"Decision threshold: the committed WP1 screening_threshold {model.screening_threshold.value_mm_s:.4g} mm/s "
        f"({model.screening_threshold.metric}, from {model.screening_threshold.path}, "
        f"{model.screening_threshold.source_sha256[:12]}...). Temporal floor: {temporal['floor_paths'][0]} "
        f"vs {temporal['floor_paths'][1]}, in-band power above {PSD_HF_ABOVE_HZ:g} Hz differing "
        f"by {temporal['floor_hf_share_difference']:.4g}. Plan question 18 vs 20 cycles: max "
        f"|diff| {focus['max_abs_difference_mm_s']:.4g} mm/s at "
        f"{focus['max_abs_difference_depth_mm']:.4g} mm = {focus['ratio_to_screening_threshold']:.3g} of the "
        f"screening_threshold, {focus['knots_above_screening_threshold']} of {focus['knots']} knots above it "
        f"({window['pairs']} pairs in the 16-20-cycle region, "
        f"{window['pairs_above_screening_threshold']} clearing it). {MIXER_SETPOINT_ROLE}. "
        f"{REPLICATE_ROLE}. Generated at commit {model.analysis_commit or 'unknown'} from "
        f"{model.manifest_path} ({model.manifest_sha256})."
    )


def provenance_document(model: BurstLadder) -> dict[str, object]:
    """The machine-readable record beside the tables and the figure.

    Keys are inserted in a fixed order, so a regeneration from the same commit is byte-identical.
    """
    common, temporal = model.common, model.temporal
    return {
        "artefact": "burst-ladder", "axis": model.axis,
        "analysis_commit": model.analysis_commit, "dataset_root": model.dataset_root,
        "manifest": {"path": model.manifest_path, "sha256": model.manifest_sha256},
        "screening_threshold": dict(model.screening_threshold.model_dump()) | {"source_path": model.screening_threshold.path},
        "timestamps": dict(model.timestamps),
        "inputs": [
            {
                "relative_path": entry.relative_path, "axis": entry.axis,
                "requested_label": entry.requested_label, "cycles": entry.burst_length,
                "source_sha256": entry.source_sha256, "profiles": entry.profiles,
                "gates": entry.gates, "duration_s": entry.duration_s,
                "prf_period_us": entry.prf_period_us, "resolution_mm": entry.resolution_mm,
                "emissions_per_profile": entry.emissions_per_profile,
                "emit_power": entry.emit_power, "sensitivity": entry.sensitivity,
                "tgc_mode": entry.tgc_mode, "depth_min_mm": entry.depth_min_mm,
                "depth_max_mm": entry.depth_max_mm,
                "profiles_window": common["profiles_window"][entry.relative_path],
                "gates_in_support": common["gates_in_support"][entry.relative_path],
            }
            for entry in model.inputs
        ],
        "views": {
            "time": {"common_duration": {
                key: common[key] for key in (
                    "nominal_rpm", "revolution_s", "revolutions", "window_s", "profiles_window"
                )
            } | {"rule": (
                "largest integer number of nominal revolutions fitting every burst recording, "
                "truncated per file by the recorded timestamps"
            )}},
            "depth": {
                "common_support": {
                    "min_mm": common["support_min_mm"], "max_mm": common["support_max_mm"],
                } | {
                    "plan_declared_mm": list(PLAN_SUPPORT_MM),
                    "contains_plan_window": common["support_min_mm"] <= PLAN_SUPPORT_MM[0]
                    and common["support_max_mm"] >= PLAN_SUPPORT_MM[1],
                    "gates_in_support": common["gates_in_support"],
                    "rule": "the intersection of the decoded depth ranges, used by every summary",
                },
                "native_grid": (
                    "each level keeps its own decoded gate grid for the distributional metrics, "
                    "the gradient and the correlation length; nothing is resampled"
                ),
            },
            "temporal": {
                "grid": {
                    key: temporal[key] for key in (
                        "profile_period_s", "profile_rate_hz", "period_spread_relative",
                        "wp1_period_relative_difference", "segment_profiles",
                        "segment_duration_s", "frequency_resolution_hz", "nyquist_hz", "band_hz",
                        "levels", "profiles_analysed", "segments", "acf_estimator", "psd_window",
                        "psd_detrend", "psd_scaling",
                    )
                },
                "mixer_setpoint_hz": wp1.NOMINAL_RPM / 60.0,
                "mixer_setpoint_role": MIXER_SETPOINT_ROLE,
                "rule": (
                    "every file's full record in non-overlapping segments of the identical "
                    "profile count on one shared profile period, so the segment duration, lag "
                    "grid, frequency grid and frequency resolution are identical for all 12 "
                    "files; each level's ensemble ACF/PSD is summarised in burst-levels.csv"
                ),
                "floor": temporal["floor"],
            },
            "alignment": {
                "knot_rule": (
                    "the longer pulse's native gate depths inside the common support, so the knot "
                    "spacing is never finer than that participant's own grid"
                ),
                "short_sampling_rule": (
                    "the shorter pulse's profile is sampled at each knot by its nearest native "
                    "gate (offset at most half its own pitch); no interpolation"
                ),
                "upsampled": False,
                "max_knot_offset_over_all_pairs_mm": max(
                    row["max_knot_offset_mm"] for row in model.pairs
                ),
                "focus_pair": {
                    "short_path": model.focus_pair[0], "long_path": model.focus_pair[1],
                    "selection": (
                        "selected by decoded cycle count from the manifest ladder: the plan's "
                        "question names 18 and 20 cycles, not a filename"
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
            "path": f"{FIGURES_DIRNAME}/{FIGURE_NAME}", "caption": figure_caption(model),
            "panels": list(FIGURE_PANELS),
        },
        "regeneration": {
            "command": (
                ".venv/Scripts/python.exe -m udv_echo_process.cli burst-ladder "
                f"--analysis-commit {model.analysis_commit or '<generator commit>'}"
            ),
            "note": (
                "pass the recorded analysis_commit to reproduce these artefacts byte for byte; "
                "the bare command records the current HEAD"
            ),
        },
    }


def render_figure(
    model: BurstLadder,
    profiles: Mapping[str, tuple[np.ndarray, np.ndarray]],
    path: Path,
    *,
    dpi: int = 150,
) -> Path:
    """Write the two-panel burst figure, deterministically, and return it.

    Panel 1 is dropout and variance against cycle count with the plan's 16-20-cycle region shaded;
    panel 2 the plan's own 18-versus-20 difference at the shared knots against the WP1 screening_threshold band.
    The frame is the shared writer's, so this module owns the panels only.
    """
    screening_threshold = model.screening_threshold.value_mm_s
    cycles = np.asarray([row["cycles"] for row in model.levels])
    focus = next(
        row for row in model.pairs if (row["short_path"], row["long_path"]) == model.focus_pair
    )

    def draw(axes: Sequence[object]) -> None:
        dropout_ax, focus_ax = axes
        dropout_ax.axvspan(*FOCUS_WINDOW_CYCLES, color="#ffd8a8", alpha=0.55, linewidth=0)
        dropout_ax.plot(
            cycles, [100.0 * row["zero_fraction"] for row in model.levels], "o-", color="#d62728",
            linewidth=1.4, markersize=4, label="dropout: samples equal to 0 [%]",
        )
        dropout_ax.set_xlabel("decoded burst length [cycles]")
        dropout_ax.set_ylabel("dropout [%]")
        dropout_ax.grid(alpha=0.2)
        variance_ax = dropout_ax.twinx()
        variance_ax.plot(
            cycles, [row["robust_spread_mm_s"] for row in model.levels], "s--", color="#1f77b4",
            linewidth=1.2, markersize=3.4, label="robust spread (IQR) [mm/s]",
        )
        variance_ax.plot(
            cycles, [row["rms_mm_s"] for row in model.levels], "^:", color="#2ca02c",
            linewidth=1.2, markersize=3.4, label="RMS about zero [mm/s]",
        )
        variance_ax.set_ylabel("spread / RMS [mm/s]")
        dropout_ax.legend(loc="upper left", fontsize=6.2, framealpha=0.9)
        variance_ax.legend(loc="upper right", fontsize=6.2, framealpha=0.9)

        short_depths, short_mean = profiles[model.focus_pair[0]]
        long_depths, long_mean = profiles[model.focus_pair[1]]
        support_mm = (model.common["support_min_mm"], model.common["support_max_mm"])
        inside = grid.in_support(long_depths, support_mm)
        knots = long_depths[inside]
        difference = (
            short_mean[grid.nearest_gate_indices(short_depths, knots)] - long_mean[inside]
        )
        focus_ax.axvspan(-screening_threshold, screening_threshold, color="#999999", alpha=0.25, linewidth=0)
        for sign in (-1.0, 1.0):
            focus_ax.axvline(sign * screening_threshold, color="#555555", linewidth=0.8, linestyle=":")
        focus_ax.plot(
            difference, knots, color="#111111", linewidth=1.2,
            label="18 - 20 cycles per-gate mean at the shared knots",
        )
        focus_ax.set_xlim(-1.25 * screening_threshold, 1.25 * screening_threshold)
        focus_ax.set_xlabel("difference [mm/s]; grey band = WP1 screening_threshold")
        focus_ax.set_ylabel("depth from transducer face [mm]")
        focus_ax.invert_yaxis()
        focus_ax.set_title(
            f"plan's pair: {focus['knots']} knots, max |diff| "
            f"{focus['max_abs_difference_mm_s']:.4g} mm/s = "
            f"{focus['max_abs_difference_over_screening_threshold']:.3g} screening_threshold", fontsize=9.5,
        )
        focus_ax.grid(alpha=0.2)
        focus_ax.legend(loc="lower left", fontsize=6.2, framealpha=0.9)

    return grid.panel_figure(
        "WP2 burst-length ladder — "
        f"{len(model.levels)} cycle counts against the WP1 sole-pair screening threshold",
        figure_caption(model), draw, path, caption_width=150, dpi=dpi,
        adjust={"top": 0.80, "bottom": 0.32, "wspace": 0.30},
    )


def write_burst_ladder(
    dataset_root: Path = inventory.DATASET_ROOT,
    report_dir: Path = inventory.REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    screening_threshold_path: Path | None = None,
    analysis_commit: str | None = None,
) -> BurstLadder:
    """Build the ladder and write the four reviewer-visible artefacts.

    The text artefacts use LF endings and the figure is written deterministically, so two runs on
    the same inputs and commit produce identical bytes; nothing is written when the build raises.
    """
    directory = Path(report_dir)
    manifest = (
        Path(manifest_path) if manifest_path is not None else directory / inventory.MANIFEST_NAME
    )
    screening_threshold = Path(screening_threshold_path) if screening_threshold_path is not None else directory / SCREENING_THRESHOLD_NAME
    model, profiles = _build(dataset_root, manifest, screening_threshold, analysis_commit)
    grid.write_text_artefacts(directory, {
        LEVELS_NAME: levels_csv_text(model),
        PAIRS_NAME: pairs_csv_text(model),
        PROVENANCE_NAME: json.dumps(provenance_document(model), indent=2) + "\n",
    })
    render_figure(model, profiles, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
