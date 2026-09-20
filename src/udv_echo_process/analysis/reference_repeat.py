"""WP1 — the sole-pair observed-discrepancy screening threshold (plan ``WP1``).

The committed sweep holds exactly one same-settings repeat: the base state
recorded twice as ``prf/600.BDD`` (669 profiles, 14.956 s) and
``res/1-8.BDD`` (517 profiles, 11.5529 s). Their difference is the **sole-pair
observed-discrepancy screening threshold**: one observed realization of
repeatability plus uncontrolled drift, because duration and unknown acquisition
time also differ — file metadata does not recover acquisition order, so magnitude
relative to this observation does not establish distinguishability or an axis effect;
every result remains screened, not proved (plan §2–§3.3).

What this module computes, from the manifest-selected files only:

- **Common-duration view** — the largest integer number of nominal 500-RPM
  revolutions fitting *both* recordings (96 revolutions at
  :data:`NOMINAL_REVOLUTION_S` = 0.12 s → 11.52 s), truncated per file by the
  recorded timestamps. Distributional metrics are only comparable inside such a
  shared window, so this is the only view
  :data:`COLUMNS`-keyed table uses.
- **Depth-resolved metrics** on each recording's native 50-gate grid: mean,
  median, robust spread (interquartile range, linear-interpolated percentiles),
  RMS about zero (DC-inclusive) and zero fraction. No gate is an independent
  experimental replicate and no p-value family is produced (plan §3.3).
- **The pairwise difference**, signed ``prf/600.BDD - res/1-8.BDD`` at every
  gate, field by field — orientation is a definition, not an inference.
- **The declared sole-pair observed-discrepancy screening threshold**: the largest
  absolute per-gate mean difference over depth, with the gate and depth where it
  occurs and the median absolute per-gate difference beside it. Later axis verdicts
  screen every effect against the sole-pair observed-discrepancy screening threshold and
  say only whether that effect falls above or below it — a non-causal screening outcome,
  not proof of an axis effect and not a bound on drift (plan §4 WP1 gate).
- **Temporal autocorrelation and PSD** per gate, on the identical 50-gate grid,
  from non-overlapping segments of one shared duration and therefore one shared
  frequency resolution for both recordings.
- **The recorded timestamps, measured** (R6): the median inter-profile interval,
  its interquartile range, the RMS and the maximum absolute deviation from that
  median are published for both recordings, together with the largest distance
  between a recorded timestamp and the uniform grid the temporal estimator uses.
  The uniform grid is kept only while that residual stays inside
  :data:`JITTER_TOLERANCE_CYCLES` at the top of the analysed band, and the
  criterion with its justification is recorded beside the decision; a record over
  it stops the analysis by name rather than being analysed on a grid it breaks.

The mixer setpoint (500 RPM → 8.33 Hz) is a *marker*, never a phase reference:
these files carry no tachometer, so dependence is read from each signal's own
autocorrelation. Nothing here infers rotor phase, wraps velocity or tests
significance.
"""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from pydantic import model_validator
from scipy.signal import periodogram

from udv_echo_process.analysis.sweep_inventory import MANIFEST_NAME, format_cell
from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: Repository-relative dataset root, the WP0 default (``sweep-inventory``).
DATASET_ROOT = Path("data/mixer-sensitivity-analysis/4MHz/0500RPM/001")

#: Repository-relative report directory, shared with WP0.
REPORT_DIR = Path("reports/mixer-sensitivity-analysis")

#: WP1 artefacts.
CSV_NAME = "reference-repeat.csv"
PROVENANCE_NAME = "reference-repeat.provenance.json"
FIGURES_DIRNAME = "figures"
FIGURE_NAME = "reference-repeat.png"

#: The only same-settings repeat in the committed sweep, as manifest paths.
REPEAT_PAIR: tuple[str, str] = ("prf/600.BDD", "res/1-8.BDD")

#: Difference orientation: ``diff = <prf/600.BDD> - <res/1-8.BDD>`` (mm/s).
DIFFERENCE_DEFINITION = f"{REPEAT_PAIR[0]} minus {REPEAT_PAIR[1]}"

#: Nominal mixer setpoint; the revolution used by the common-duration view.
NOMINAL_RPM = 500.0
NOMINAL_REVOLUTION_S = 60.0 / NOMINAL_RPM

#: Column order of ``reference-repeat.csv``; the field order of :class:`GateRow`
#: is the same tuple, so the table and the model cannot drift apart.
COLUMNS: tuple[str, ...] = (
    "gate_index",
    "depth_mm",
    "prf_600_mean_mm_s",
    "prf_600_median_mm_s",
    "prf_600_iqr_mm_s",
    "prf_600_rms_mm_s",
    "prf_600_zero_fraction",
    "res_1_8_mean_mm_s",
    "res_1_8_median_mm_s",
    "res_1_8_iqr_mm_s",
    "res_1_8_rms_mm_s",
    "res_1_8_zero_fraction",
    "diff_mean_mm_s",
    "diff_median_mm_s",
    "diff_iqr_mm_s",
    "diff_rms_mm_s",
    "diff_zero_fraction",
)

#: Metric names returned by :func:`gate_metrics`, in the order they are written.
METRICS: tuple[str, ...] = ("mean", "median", "iqr", "rms", "zero_fraction")

#: Temporal view: non-overlapping segments of this many profiles per recording.
#: 86 profiles is 15.9 nominal revolutions (1.9031 s at the shared profile
#: rate), which fits six whole segments in the shorter recording and gives a
#: frequency resolution of 0.52 Hz — fine enough to place the 8.33 Hz marker
#: and coarse enough to average seven segments at the low frequencies where
#: almost all of the fluctuation energy sits.
SEGMENT_PROFILES = 86

#: Autocorrelation lags reported, 0 … ``SEGMENT_PROFILES // 2``.
ACF_MAX_LAG_PROFILES = SEGMENT_PROFILES // 2

#: Estimator settings, recorded in the provenance so the spectra are defined.
PSD_WINDOW = "hann"
PSD_DETREND = "constant"
PSD_SCALING = "density"
ACF_ESTIMATOR = "biased (divide-by-N) autocovariance of the mean-removed segment"

#: Frequency band the two recordings' ensemble spectra are compared in — above
#: the segment resolution, below the 22.33 Hz Nyquist limit.
PSD_BAND_HZ: tuple[float, float] = (0.5, 20.0)

#: Nominal mixer setpoint, a depth/temporal marker only: these files carry no
#: tachometer, so it never supplies a phase reference (plan §3.1).
MIXER_SETPOINT_HZ = NOMINAL_RPM / 60.0

#: Largest relative disagreement between the two recordings' profile rates that
#: still counts as one shared time base.
_PROFILE_RATE_TOLERANCE = 1e-4

class ReferenceRepeatError(ValueError):
    """A WP1 input is not the pair the plan describes.

    Raised for a manifest that does not hold exactly one row per repeat path, a
    recorded source hash that does not match the bytes, or two recordings whose
    operating settings or gate grids differ. The command turns it into a
    non-zero exit with a named reason, never a traceback.
    """


def select_repeat_rows(manifest_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return the two ``REPEAT_PAIR`` manifest rows, in pair order.

    The pair is pinned to the WP0 manifest rather than to a hand-maintained
    filename list: the file being compared is the one the inventory decoded, and
    its ``source_sha256`` is the content identity
    :func:`build_reference_repeat` then re-checks against the bytes.

    Args:
        manifest_path: the committed ``manifest.csv`` (path as emitted by WP0).

    Returns:
        The ``prf/600.BDD`` row and the ``res/1-8.BDD`` row.

    Raises:
        ReferenceRepeatError: when the manifest is missing, unreadable, or does
            not carry exactly one row for each repeat path.
    """
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReferenceRepeatError(
            f"cannot read the manifest {path}: {exc}"
        ) from exc
    reader = csv.DictReader(text.splitlines())
    selected: dict[str, list[dict[str, str]]] = {name: [] for name in REPEAT_PAIR}
    for row in reader:
        relative = row.get("relative_path") or ""
        if relative in selected:
            selected[relative].append(row)
    for name in REPEAT_PAIR:
        matches = selected[name]
        if len(matches) != 1:
            raise ReferenceRepeatError(
                f"manifest {path} must hold exactly one row for {name}, found "
                f"{len(matches)}"
            )
    return selected[REPEAT_PAIR[0]][0], selected[REPEAT_PAIR[1]][0]


def common_revolution_count(
    durations_s: Sequence[float], *, revolution_s: float = NOMINAL_REVOLUTION_S
) -> int:
    """Largest integer number of ``revolution_s`` revolutions fitting every run.

    Args:
        durations_s: each recording's full duration in seconds.
        revolution_s: nominal revolution period (0.12 s at 500 RPM).

    Returns:
        The common revolution count, at least 1.

    Raises:
        ReferenceRepeatError: when no duration is given, a duration is not
            positive, or not even one revolution fits.
    """
    if not durations_s:
        raise ReferenceRepeatError("common_revolution_count needs at least one duration")
    if not all(math.isfinite(value) and value > 0.0 for value in durations_s):
        raise ReferenceRepeatError(
            f"every duration must be finite and positive, got {list(durations_s)}"
        )
    count = math.floor(min(durations_s) / revolution_s)
    if count < 1:
        raise ReferenceRepeatError(
            f"no whole {revolution_s:g}-s revolution fits {min(durations_s)} s"
        )
    return count


def gate_metrics(values: np.ndarray) -> dict[str, np.ndarray]:
    """Per-gate distributional metrics of a ``(profiles, gates)`` window.

    Definitions, in ``mm/s`` for every velocity metric and dimensionless for
    ``zero_fraction``:

    - ``mean`` — arithmetic mean over the window;
    - ``median`` — 50th percentile;
    - ``iqr`` — robust spread, the interquartile range ``p75 - p25`` with
      linear-interpolated percentiles (``numpy.percentile`` default);
    - ``rms`` — root mean square about zero, so a DC offset raises it: it is
      not a standard deviation and no mean is removed;
    - ``zero_fraction`` — fraction of samples exactly equal to ``0.0``.

    Args:
        values: the truncated ``(profiles, gates)`` velocity window.

    Returns:
        One length-``gates`` array per name in :data:`METRICS`.
    """
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ReferenceRepeatError(
            f"gate_metrics needs a 2-D (profiles, gates) array, got shape {array.shape}"
        )
    p25, p75 = np.percentile(array, [25.0, 75.0], axis=0)
    return {
        "mean": np.mean(array, axis=0),
        "median": np.median(array, axis=0),
        "iqr": p75 - p25,
        "rms": np.sqrt(np.mean(np.square(array), axis=0)),
        "zero_fraction": np.count_nonzero(array == 0.0, axis=0) / array.shape[0],
    }


# ── models ─────────────────────────────────────────────────────────────


class GateRow(ValueModel):
    """One gate of the common-duration view: both recordings and the difference.

    Field names are the ``reference-repeat.csv`` column names, in the same
    order, so the artifact and the model cannot drift. Every velocity field is
    ``mm/s`` and every ``*_zero_fraction`` is dimensionless.
    """

    gate_index: int
    depth_mm: float
    prf_600_mean_mm_s: float
    prf_600_median_mm_s: float
    prf_600_iqr_mm_s: float
    prf_600_rms_mm_s: float
    prf_600_zero_fraction: float
    res_1_8_mean_mm_s: float
    res_1_8_median_mm_s: float
    res_1_8_iqr_mm_s: float
    res_1_8_rms_mm_s: float
    res_1_8_zero_fraction: float
    diff_mean_mm_s: float
    diff_median_mm_s: float
    diff_iqr_mm_s: float
    diff_rms_mm_s: float
    diff_zero_fraction: float

    @model_validator(mode="after")
    def _check_difference_is_the_signed_pairwise_difference(self) -> GateRow:
        """Require ``diff = prf/600 - res/1-8`` on every field, not just on mean."""
        for metric in METRICS:
            expected = getattr(self, f"prf_600_{metric}_mm_s", None)
            other = getattr(self, f"res_1_8_{metric}_mm_s", None)
            if expected is None:
                expected = self.prf_600_zero_fraction
                other = self.res_1_8_zero_fraction
            difference = getattr(self, f"diff_{metric}_mm_s", self.diff_zero_fraction)
            if not math.isclose(difference, expected - other, rel_tol=1e-12):
                raise ValueError(
                    f"gate {self.gate_index}: diff_{metric} must be "
                    f"{DIFFERENCE_DEFINITION} ({expected - other}), got {difference}"
                )
        return self


class RepeatInput(ValueModel):
    """One recording of the repeat pair, as decoded and pinned to the manifest."""

    relative_path: str
    axis: str
    requested_label: str
    source_sha256: str
    profiles: int
    gates: int
    duration_s: float
    profile_period_s: float
    depth_min_mm: float
    depth_max_mm: float
    prf_period_us: float
    resolution_mm: float
    burst_length: int
    emissions_per_profile: int
    emit_power: str
    sensitivity: str
    tgc_mode: str
    sound_speed_ms: float
    velo_max_ms: float


class CommonView(ValueModel):
    """The shared time window every distributional summary is computed in."""

    nominal_rpm: float
    revolution_s: float
    revolutions: int
    window_s: float
    start_s: float
    profiles_a: int
    profiles_b: int
    gates: int


class ObservedDiscrepancyScreeningThreshold(ValueModel):
    """The declared sole-pair observed-discrepancy screening threshold.

    ``value_mm_s`` is the largest absolute per-gate mean difference over depth —
    the threshold every axis screens an effect against. It is *not* a bound: it
    combines true repeatability with uncontrolled drift, because the two
    recordings also differ in duration and acquisition time (plan §3.3).
    """

    metric: str = "max_gate_abs_mean_difference_mm_s"
    units: str = "mm/s"
    value_mm_s: float
    gate_index: int
    depth_mm: float
    median_abs_mean_difference_mm_s: float
    scope: str = (
        "sole-pair observed-discrepancy screening threshold: one observed realization of repeatability plus uncontrolled drift, screened and not a bound on either"
    )


class TemporalSeries(ValueModel):
    """One recording's ensemble autocorrelation and PSD on the 50-gate grid.

    Every curve is the mean over the identical 50 gates of the per-gate mean
    over that recording's non-overlapping segments, with ``p10``/``p90``
    carrying the spread *across gates* (not a confidence interval, and not a
    statement about independent replicates). Lag is seconds and nominal
    revolutions; frequency is Hz; spectral density is ``(mm/s)^2/Hz``.
    """

    relative_path: str
    source_sha256: str
    profiles: int
    profiles_analysed: int
    segments: int
    segment_profiles: int
    segment_duration_s: float
    gates: int
    lag_s: tuple[float, ...]
    lag_revolutions: tuple[float, ...]
    acf_mean: tuple[float, ...]
    acf_p10: tuple[float, ...]
    acf_p90: tuple[float, ...]
    acf_e_folding_lag_s: float
    frequency_hz: tuple[float, ...]
    psd_mean_mm2_s2_per_hz: tuple[float, ...]
    psd_p10_mm2_s2_per_hz: tuple[float, ...]
    psd_p90_mm2_s2_per_hz: tuple[float, ...]


class TemporalComparison(ValueModel):
    """The shared temporal view: one time base for both recordings.

    The two recordings carry the same acquisition settings, so they share one
    instrument profile rate; the analysis grid is that rate's mean (the two
    implied periods agree to ~5e-6 relative). Both then use segments of exactly
    :data:`SEGMENT_PROFILES` profiles, so the segment duration, the lag grid,
    the frequency grid and the frequency resolution are identical for the two
    files by construction — the plan's "identical segment duration" (§3.1).
    """

    profile_period_s: float
    profile_rate_hz: float
    segment_profiles: int
    segment_duration_s: float
    frequency_resolution_hz: float
    nyquist_hz: float
    acf_max_lag_profiles: int
    acf_estimator: str
    psd_window: str
    psd_detrend: str
    psd_scaling: str
    mixer_setpoint_hz: float
    band_hz: tuple[float, float]
    band_max_abs_level_difference_db: float
    band_max_difference_frequency_hz: float
    band_median_level_difference_db: float
    segments: tuple[int, int]
    series: tuple[TemporalSeries, TemporalSeries]

    @model_validator(mode="after")
    def _check_one_shared_time_base(self) -> TemporalComparison:
        first, second = self.series
        if (first.relative_path, second.relative_path) != REPEAT_PAIR:
            raise ValueError(
                f"temporal series must be {REPEAT_PAIR} in that order, got "
                f"{(first.relative_path, second.relative_path)}"
            )
        if first.segment_duration_s != second.segment_duration_s:
            raise ValueError(
                "the two recordings must be analysed with the identical segment "
                f"duration, got {first.segment_duration_s} and "
                f"{second.segment_duration_s}"
            )
        if self.segments != (first.segments, second.segments):
            raise ValueError("segments must match the two series")
        if first.lag_s != second.lag_s or first.frequency_hz != second.frequency_hz:
            raise ValueError(
                "the two recordings must share one lag grid and one frequency grid"
            )
        if not (
            first.segment_profiles
            == second.segment_profiles
            == self.segment_profiles
        ):
            raise ValueError("segment_profiles must match the two series")
        if first.gates != second.gates:
            raise ValueError("the two recordings must share the identical gate grid")
        return self


class ReferenceRepeat(ValueModel):
    """The WP1 result: the pair, the common window, the rows and the screening_threshold."""

    dataset_root: str
    manifest_path: str
    manifest_sha256: str
    analysis_commit: str | None = None
    input_a: RepeatInput
    input_b: RepeatInput
    common: CommonView
    screening_threshold: ObservedDiscrepancyScreeningThreshold
    rows: tuple[GateRow, ...]
    temporal: TemporalComparison
    timestamps: TimestampGrid

    @model_validator(mode="after")
    def _check_the_timestamp_measurement_is_this_pair_s(self) -> ReferenceRepeat:
        """The measurement must be the two inputs' own recorded timestamps, in pair order."""
        if tuple(item.relative_path for item in self.timestamps.per_input) != REPEAT_PAIR:
            raise ValueError(
                f"the timestamp measurement must cover {REPEAT_PAIR} in that order, got "
                f"{tuple(item.relative_path for item in self.timestamps.per_input)}"
            )
        for entry, item in zip(
            (self.input_a, self.input_b), self.timestamps.per_input, strict=True
        ):
            if item.source_sha256 != entry.source_sha256:
                raise ValueError(
                    f"{entry.relative_path}: the timestamp measurement is not of the analysed bytes"
                )
            if not math.isclose(item.uniform_period_s, entry.profile_period_s, rel_tol=1e-12):
                raise ValueError(
                    f"{entry.relative_path}: the measured uniform period "
                    f"{item.uniform_period_s} is not the period the temporal view uses "
                    f"{entry.profile_period_s}"
                )
        return self

    @model_validator(mode="after")
    def _check_rows_resolve_the_common_view(self) -> ReferenceRepeat:
        if len(self.rows) != self.common.gates:
            raise ValueError(
                f"expected one row per gate ({self.common.gates}), got "
                f"{len(self.rows)}"
            )
        if [row.gate_index for row in self.rows] != list(range(self.common.gates)):
            raise ValueError("rows must be ordered by gate_index from 0")
        depths = [row.depth_mm for row in self.rows]
        if any(b <= a for a, b in itertools.pairwise(depths)):
            raise ValueError("row depths must increase strictly with gate index")
        if (self.input_a.relative_path, self.input_b.relative_path) != REPEAT_PAIR:
            raise ValueError(
                f"inputs must be {REPEAT_PAIR} in that order, got "
                f"{(self.input_a.relative_path, self.input_b.relative_path)}"
            )
        if self.input_a.source_sha256 == self.input_b.source_sha256:
            raise ValueError("the two inputs must have different content hashes")
        return self


# ── R6: the recorded timestamps, measured, and the criterion the grid is kept by ──

#: The quantitative jitter tolerance: the worst-case phase error the uniform grid may place on a
#: recorded sample, in cycles of the fastest frequency the analysis resolves.
JITTER_TOLERANCE_CYCLES = 1.0 / 16.0

#: The criterion, written as the quantity it bounds, and the physical/statistical justification the
#: tolerance rests on. Recorded verbatim in the provenance so the estimator choice is checkable.
JITTER_CRITERION_NAME = "uniform-grid phase error at the top of the analysed band"
JITTER_CRITERION = (
    "worst-case phase error of the uniform grid at the top of the analysed band: "
    "max_k |t_k - (t_0 + k x uniform_period_s)| x f_max <= 1/16 cycle, one criterion per input, "
    "f_max the Nyquist limit of that input's own profile rate"
)
JITTER_JUSTIFICATION = (
    "a sample the uniform grid places dt away from its recorded time is mis-phased by 2 pi f dt for "
    "every resolved component at f, so max|t_k - grid| x f_max is the worst-case phase error over "
    "the analysed band; 1/16 of a cycle (pi/8 rad) keeps the worst-placed sample's coherent "
    "(zero-lag) weight at cos(pi/8) = 0.924 of its unbiased value, i.e. caps the amplitude bias "
    "of the coherent sums and of the PSD cross terms at 7.6%, and keeps every sample inside its own "
    "cycle of the fastest resolved component so none can be attributed to a neighbouring cycle. The "
    "tolerance is a grid-error tolerance and says nothing about the flow; the four published "
    "statistics "
    "describe the recorded intervals themselves, while max_grid_residual_s also carries their "
    "cumulative departure, which is what a quantized interval accumulates over a record"
)
UNIFORM_GRID_ESTIMATOR = (
    "uniform grid at each record's own mean inter-profile interval, the period its first and last "
    "recorded timestamps imply; the residual is measured against that grid, not against a nominal "
    "PRF period"
)
UNIFORM_GRID_RETAINED = (
    "uniform grid retained: every input's worst-case phase error is below the tolerance at the top "
    "of the band it is analysed in, so the recorded timestamps need no resampling and no "
    "irregular-time estimator"
)
UNIFORM_GRID_REFUSED = (
    "uniform grid not supported: a recorded timestamp sits further from the uniform grid than the "
    "tolerance allows at the top of the analysed band; resample or use an irregular-time estimator "
    "rather than analysing the record on a grid its own timestamps do not support"
)


class TimestampJitter(ValueModel):
    """One recording's recorded inter-profile intervals, measured rather than assumed uniform.

    Every quantity is computed from the recorded profile timestamps. ``median_dt_s``,
    ``dt_iqr_s``, ``rms_deviation_s`` and ``max_abs_deviation_s`` describe the intervals
    themselves; ``uniform_period_s`` is the scalar the temporal estimator uses and
    ``max_grid_residual_s`` is the largest distance between a recorded timestamp and the grid that
    period places on the record — where the cumulative departure of a quantized interval shows up.
    ``criterion_met`` records whether that residual exceeds :data:`JITTER_TOLERANCE_CYCLES` at
    ``f_max_hz``.
    """

    relative_path: str
    source_sha256: str
    profiles: int
    intervals: int
    span_s: float
    median_dt_s: float
    dt_iqr_s: float
    rms_deviation_s: float
    max_abs_deviation_s: float
    uniform_period_s: float
    f_max_hz: float
    max_grid_residual_s: float
    worst_case_phase_cycles: float
    tolerance_cycles: float
    criterion_met: bool


class TimestampGrid(ValueModel):
    """The timestamp measurement of one artefact's inputs, with the estimator decision.

    ``per_input`` holds one :class:`TimestampJitter` per recording the artefact analyses, and the
    criterion, its tolerance and justification are recorded beside the decision they produced.
    A grid is only ever built by :func:`timestamp_grid`, which refuses every input whose criterion
    is not met, so ``retained`` is true exactly when every input passed.
    """

    name: str
    criterion: str
    tolerance_cycles: float
    justification: str
    estimator: str
    decision: str
    retained: bool
    per_input: tuple[TimestampJitter, ...]

    @model_validator(mode="after")
    def _check_the_decision_follows_the_measurements(self) -> TimestampGrid:
        if not self.per_input:
            raise ValueError("a timestamp grid needs at least one measured input")
        paths = [item.relative_path for item in self.per_input]
        if len(set(paths)) != len(paths):
            raise ValueError("every measured input must appear once")
        if self.retained != all(item.criterion_met for item in self.per_input):
            raise ValueError("the decision must follow the measured criteria")
        if self.tolerance_cycles != JITTER_TOLERANCE_CYCLES:
            raise ValueError(
                f"the tolerance is {JITTER_TOLERANCE_CYCLES!r} cycles; a record that moves it "
                "must be a stated decision, not a silent edit"
            )
        return self


def measure_timestamps(
    entry: RepeatInput, time_s: np.ndarray, *, f_max_hz: float
) -> TimestampJitter:
    """Measure one recording's recorded profile timestamps (plan §8.3 step 4, R6).

    Args:
        entry: the recording's manifest-pinned record (path, hash, profile period).
        time_s: the recorded profile timestamps, in seconds.
        f_max_hz: the highest frequency the analysis of this record resolves (its Nyquist limit).

    Returns:
        The interval statistics, the uniform period, the grid residual and whether the residual
        stays inside :data:`JITTER_TOLERANCE_CYCLES` at ``f_max_hz``.

    Raises:
        ReferenceRepeatError: when fewer than two timestamps are given, a timestamp is not finite,
            the timestamps do not increase strictly, or ``f_max_hz`` is not positive and finite.
    """
    times = np.asarray(time_s, dtype=float)
    if times.ndim != 1 or times.size < 2:
        raise ReferenceRepeatError(
            f"{entry.relative_path}: profile-interval statistics need at least two recorded "
            f"timestamps, got shape {times.shape}"
        )
    if not np.all(np.isfinite(times)):
        raise ReferenceRepeatError(f"{entry.relative_path}: the recorded timestamps are not finite")
    if not (math.isfinite(f_max_hz) and f_max_hz > 0.0):
        raise ReferenceRepeatError(f"f_max_hz must be positive and finite, got {f_max_hz!r}")
    intervals = np.diff(times)
    if np.any(intervals <= 0.0):
        raise ReferenceRepeatError(
            f"{entry.relative_path}: the recorded profile timestamps are not strictly increasing; "
            "a repeated or reversed profile has no uniform grid"
        )
    median = float(np.median(intervals))
    deviation = intervals - median
    period = float((times[-1] - times[0]) / (times.size - 1))
    residual = float(np.max(np.abs(times - (times[0] + np.arange(times.size) * period))))
    return TimestampJitter(
        relative_path=entry.relative_path,
        source_sha256=entry.source_sha256,
        profiles=int(times.size),
        intervals=int(intervals.size),
        span_s=float(times[-1] - times[0]),
        median_dt_s=median,
        dt_iqr_s=float(np.percentile(intervals, 75.0) - np.percentile(intervals, 25.0)),
        rms_deviation_s=float(np.sqrt(np.mean(np.square(deviation)))),
        max_abs_deviation_s=float(np.max(np.abs(deviation))),
        uniform_period_s=period,
        f_max_hz=float(f_max_hz),
        max_grid_residual_s=residual,
        worst_case_phase_cycles=float(residual * f_max_hz),
        tolerance_cycles=JITTER_TOLERANCE_CYCLES,
        criterion_met=bool(residual * f_max_hz <= JITTER_TOLERANCE_CYCLES),
    )


def timestamp_grid(jitters: Sequence[TimestampJitter]) -> TimestampGrid:
    """The estimator decision of one artefact: keep the uniform grid only where it is justified.

    Raises:
        ReferenceRepeatError: when any input's measured worst-case phase error exceeds
            :data:`JITTER_TOLERANCE_CYCLES`. The message names the remedy — resample, or use an
            irregular-time estimator — because the committed uniform-grid estimator must not be
            kept for a record the measurement does not support.
    """
    measured = tuple(jitters)
    if not measured:
        raise ReferenceRepeatError("a timestamp grid needs at least one measured input")
    over = [
        f"{item.relative_path} ({item.worst_case_phase_cycles:.4g} cycles > "
        f"{JITTER_TOLERANCE_CYCLES:g} at {item.f_max_hz:.6g} Hz)"
        for item in measured
        if not item.criterion_met
    ]
    if over:
        raise ReferenceRepeatError(
            f"{UNIFORM_GRID_REFUSED}: " + "; ".join(over)
        )
    return TimestampGrid(
        name=JITTER_CRITERION_NAME,
        criterion=JITTER_CRITERION,
        tolerance_cycles=JITTER_TOLERANCE_CYCLES,
        justification=JITTER_JUSTIFICATION,
        estimator=UNIFORM_GRID_ESTIMATOR,
        decision=UNIFORM_GRID_RETAINED,
        retained=True,
        per_input=measured,
    )


def timestamp_document(grid: TimestampGrid) -> dict[str, object]:
    """The timestamp measurement and decision as the provenance document records them.

    Keys are inserted in a fixed order, so a regeneration from the same commit is byte-identical.
    """
    return {
        "name": grid.name,
        "criterion": grid.criterion,
        "tolerance_cycles": grid.tolerance_cycles,
        "justification": grid.justification,
        "estimator": grid.estimator,
        "decision": grid.decision,
        "retained": grid.retained,
        "per_input": [
            {
                "relative_path": item.relative_path,
                "source_sha256": item.source_sha256,
                "profiles": item.profiles,
                "intervals": item.intervals,
                "span_s": item.span_s,
                "median_dt_s": item.median_dt_s,
                "dt_iqr_s": item.dt_iqr_s,
                "rms_deviation_s": item.rms_deviation_s,
                "max_abs_deviation_s": item.max_abs_deviation_s,
                "uniform_period_s": item.uniform_period_s,
                "f_max_hz": item.f_max_hz,
                "max_grid_residual_s": item.max_grid_residual_s,
                "worst_case_phase_cycles": item.worst_case_phase_cycles,
                "criterion_met": item.criterion_met,
            }
            for item in grid.per_input
        ],
    }


# ── decoding and binding ───────────────────────────────────────────────


#: Manifest cells re-checked against the decoded recording, in row-column order.
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


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_recording(
    dataset_root: Path, row: dict[str, str]
) -> tuple[RepeatInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected recording and bind it to its manifest row.

    Returns:
        ``(input, values, time_s, gate_depths_mm)`` — the manifest record, the
        ``(profiles, gates)`` velocity array in ``mm/s`` and the two axes.

    Raises:
        ReferenceRepeatError: when the row has no usable path, the file's bytes
            do not reproduce the recorded SHA-256, the payload is not exactly
            one axial-velocity channel, or a re-checked manifest cell disagrees
            with the decoded value.
    """
    relative = row.get("relative_path") or ""
    path = dataset_root / relative
    if not relative or not path.is_file():
        raise ReferenceRepeatError(f"manifest row {relative!r} is not a file at {path}")
    recorded = (row.get("source_sha256") or "").strip()
    actual = _sha256_file(path)
    if recorded != actual:
        raise ReferenceRepeatError(
            f"source sha256 mismatch for {relative}: manifest records "
            f"{recorded!r}, file hashes to {actual!r}"
        )
    bundle = load(path)
    recording = bundle.recording
    if recording.source_asset.content_sha256 != actual:
        raise ReferenceRepeatError(
            f"{relative}: the reader's content hash "
            f"{recording.source_asset.content_sha256!r} is not the file hash "
            f"{actual!r}"
        )
    if len(recording.streams) != 1:
        raise ReferenceRepeatError(
            f"{relative}: expected exactly one channel stream, found "
            f"{len(recording.streams)}"
        )
    stream = recording.streams[0]
    unit = stream.descriptor.unit
    values = np.asarray(stream.data.values, dtype=float)
    time_s = np.asarray(stream.data.time_s, dtype=float)
    depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
    if unit != "mm/s" or values.ndim != 2:
        raise ReferenceRepeatError(
            f"{relative}: expected a 2-D axial-velocity array in mm/s, got "
            f"{values.ndim}-D in {unit!r}"
        )
    if np.count_nonzero(np.isnan(values)):
        raise ReferenceRepeatError(f"{relative}: the velocity array carries NaNs")
    config = stream.config
    observed = {
        "profiles": format_cell(int(values.shape[0])),
        "gates": format_cell(int(values.shape[1])),
        "duration_s": format_cell(float(time_s[-1] - time_s[0])),
        "depth_min_mm": format_cell(float(depths[0])),
        "depth_max_mm": format_cell(float(np.max(depths))),
        "resolution_mm": format_cell(config.resolution_mm),
        "prf_period_us": format_cell(_prf_period_us(config)),
        "burst_length": format_cell(config.burst_length),
        "emissions_per_profile": format_cell(config.emissions_per_profile),
        "emit_power": format_cell(config.emit_power),
        "sensitivity": format_cell(config.sensitivity),
        "tgc_mode": format_cell(config.tgc_mode),
    }
    for cell, key in _VERIFIED_CELLS:
        if (row.get(cell) or "") != observed[key]:
            raise ReferenceRepeatError(
                f"{relative}: manifest {cell}={row.get(cell)!r} does not match the "
                f"decoded {key}={observed[key]!r}; the comparison must not run on "
                "a stale inventory"
            )
    entry = RepeatInput(
        relative_path=relative,
        axis=row.get("axis") or "",
        requested_label=row.get("requested_label") or "",
        source_sha256=actual,
        profiles=int(values.shape[0]),
        gates=int(values.shape[1]),
        duration_s=float(time_s[-1] - time_s[0]),
        profile_period_s=float((time_s[-1] - time_s[0]) / (time_s.size - 1)),
        depth_min_mm=float(depths[0]),
        depth_max_mm=float(np.max(depths)),
        prf_period_us=_prf_period_us(config),
        resolution_mm=float(config.resolution_mm),
        burst_length=int(config.burst_length),
        emissions_per_profile=int(config.emissions_per_profile),
        emit_power=str(config.emit_power),
        sensitivity=str(config.sensitivity),
        tgc_mode=str(config.tgc_mode),
        sound_speed_ms=float(config.sound_speed_ms),
        velo_max_ms=float(config.velo_max_ms),
    )
    return entry, values, time_s, depths


def _prf_period_us(config) -> float:
    """PRF period in microseconds, inverted back from the reader's Hz field."""
    return 1e6 / float(config.pulse_repetition_freq_hz)


def _require_same_settings(a: RepeatInput, b: RepeatInput) -> None:
    """Refuse to call two recordings a repeat unless every setting agrees."""
    moved = [
        field
        for field in (
            "prf_period_us",
            "resolution_mm",
            "burst_length",
            "emissions_per_profile",
            "emit_power",
            "sensitivity",
            "tgc_mode",
            "sound_speed_ms",
            "velo_max_ms",
            "gates",
        )
        if getattr(a, field) != getattr(b, field)
    ]
    if moved:
        raise ReferenceRepeatError(
            f"{a.relative_path} and {b.relative_path} are not a same-settings "
            f"repeat: {sorted(moved)} differ"
        )


def _window(values: np.ndarray, time_s: np.ndarray, window_s: float) -> np.ndarray:
    """The leading ``window_s`` of a recording, as ``(profiles, gates)`` samples.

    The cut is the recorded timestamp, so both recordings are cut at the same
    *duration* even though their profile counts differ; a 1 ns tolerance keeps
    the last sample on the boundary from depending on float rounding.
    """
    keep = time_s <= time_s[0] + window_s + 1e-9
    return values[keep]


# ── temporal view: autocorrelation and PSD on one shared time base ─────


def shared_profile_period_s(periods_s: Sequence[float]) -> float:
    """The one instrument profile period the repeat pair is analysed on.

    The two recordings carry the same acquisition settings, so their implied
    profile periods must agree; the analysis grid is their mean, which keeps the
    segment duration, lag grid and frequency grid identical for both files. The
    recorded timestamps deviate from that grid by well under a millisecond over
    a whole record, so no sample is moved.

    Args:
        periods_s: each recording's implied profile period in seconds.

    Returns:
        The mean period, in seconds.

    Raises:
        ReferenceRepeatError: when fewer than two periods are given, one is not
            finite and positive, or they disagree by more than
            :data:`_PROFILE_RATE_TOLERANCE` relative — the pair then does not
            share a profile rate and must not be compared on one grid.
    """
    values = [float(value) for value in periods_s]
    if len(values) < 2 or not all(
        math.isfinite(value) and value > 0.0 for value in values
    ):
        raise ReferenceRepeatError(
            f"at least two finite positive profile periods are needed, got {values}"
        )
    mean = sum(values) / len(values)
    spread = (max(values) - min(values)) / mean
    if spread > _PROFILE_RATE_TOLERANCE:
        raise ReferenceRepeatError(
            f"the recordings do not share a profile rate: periods {values} differ "
            f"by {spread:.3g} relative, above the {_PROFILE_RATE_TOLERANCE:g} "
            "tolerance a shared temporal grid needs"
        )
    return mean


def _segment_acf(segment: np.ndarray, max_lag: int) -> np.ndarray:
    """Normalized autocorrelation of one mean-removed segment, lags 0…max_lag."""
    centered = segment - segment.mean()
    variance = float(np.var(centered))
    if variance == 0.0:
        raise ReferenceRepeatError(
            "a constant segment has no autocorrelation; the segment window is "
            "too short for a gate whose velocity never moves"
        )
    full = np.correlate(centered, centered, mode="full")[centered.size - 1 :]
    return full[: max_lag + 1] / (centered.size * variance)


def _ensemble(per_gate: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean and 10th/90th percentile across the identical gate grid."""
    return (
        per_gate.mean(axis=0),
        np.percentile(per_gate, 10.0, axis=0),
        np.percentile(per_gate, 90.0, axis=0),
    )


def temporal_series(
    entry: RepeatInput,
    values: np.ndarray,
    profile_period_s: float,
    *,
    segment_profiles: int = SEGMENT_PROFILES,
) -> TemporalSeries:
    """Per-gate autocorrelation and PSD of one recording, on ``profile_period_s``.

    Args:
        entry: the recording's manifest-pinned record (path, hash, gate count).
        values: the recording's full ``(profiles, gates)`` velocity array.
        profile_period_s: the analysis period (see
            :func:`shared_profile_period_s`).
        segment_profiles: the segment length in profiles. The committed
            default is :data:`SEGMENT_PROFILES`, which every caller on a
            shared profile rate uses — WP1, resolution and burst pass nothing
            and their artefacts are unchanged. The PRF ladder's files do *not*
            share a profile rate, so it passes the per-file length its matched
            physical segment duration implies; the reported
            ``frequency_resolution_hz`` is then ``1 / segment_duration_s``.

    Returns:
        The ensemble curves: every value is the mean over the identical 50 gates
        of that gate's mean over the recording's non-overlapping segments, with
        the across-gate 10th and 90th percentiles beside it.

    Raises:
        ReferenceRepeatError: when the segment is shorter than two profiles, no
            whole segment fits the record, or a gate is constant over a segment
            (its normalized autocorrelation is undefined).
    """
    if segment_profiles < 2:
        raise ReferenceRepeatError(
            f"a segment needs at least two profiles, got {segment_profiles}"
        )
    max_lag = segment_profiles // 2
    gates = int(values.shape[1])
    segments = int(values.shape[0] // segment_profiles)
    if segments < 1:
        raise ReferenceRepeatError(
            f"{entry.relative_path}: {values.shape[0]} profiles do not hold one "
            f"{segment_profiles}-profile segment"
        )
    blocks = values[: segments * segment_profiles].reshape(
        segments, segment_profiles, gates
    )
    rate_hz = 1.0 / profile_period_s
    acf_per_gate = np.empty((gates, max_lag + 1))
    # One segment defines the grid; every later segment must land on it, which a
    # shared segment length guarantees.
    frequency, _ = periodogram(
        blocks[0, :, 0],
        fs=rate_hz,
        window=PSD_WINDOW,
        detrend=PSD_DETREND,
        scaling=PSD_SCALING,
    )
    psd_per_gate = np.empty((gates, frequency.size))
    for gate in range(gates):
        acf = np.zeros(max_lag + 1)
        psd = np.zeros(frequency.size)
        for segment in range(segments):
            block = blocks[segment, :, gate]
            acf += _segment_acf(block, max_lag) / segments
            bins, density = periodogram(
                block,
                fs=rate_hz,
                window=PSD_WINDOW,
                detrend=PSD_DETREND,
                scaling=PSD_SCALING,
            )
            if bins.shape != frequency.shape or not np.array_equal(bins, frequency):
                raise ReferenceRepeatError(
                    "the periodogram frequency grid moved between segments; a "
                    "shared segment length must give a shared grid"
                )
            psd += density
        acf_per_gate[gate] = acf
        psd_per_gate[gate] = psd / segments
    acf_mean, acf_p10, acf_p90 = _ensemble(acf_per_gate)
    psd_mean, psd_p10, psd_p90 = _ensemble(psd_per_gate)
    below = np.flatnonzero(acf_mean < 1.0 / math.e)
    e_folding = int(below[0]) if below.size else max_lag
    lag_s = np.arange(max_lag + 1) * profile_period_s
    return TemporalSeries(
        relative_path=entry.relative_path,
        source_sha256=entry.source_sha256,
        profiles=int(values.shape[0]),
        profiles_analysed=int(segments * segment_profiles),
        segments=segments,
        segment_profiles=segment_profiles,
        segment_duration_s=(segment_profiles - 1) * profile_period_s,
        gates=gates,
        lag_s=tuple(float(value) for value in lag_s),
        lag_revolutions=tuple(
            float(value / NOMINAL_REVOLUTION_S) for value in lag_s
        ),
        acf_mean=tuple(float(value) for value in acf_mean),
        acf_p10=tuple(float(value) for value in acf_p10),
        acf_p90=tuple(float(value) for value in acf_p90),
        acf_e_folding_lag_s=float(lag_s[e_folding]),
        frequency_hz=tuple(float(value) for value in frequency),
        psd_mean_mm2_s2_per_hz=tuple(float(value) for value in psd_mean),
        psd_p10_mm2_s2_per_hz=tuple(float(value) for value in psd_p10),
        psd_p90_mm2_s2_per_hz=tuple(float(value) for value in psd_p90),
    )


def temporal_comparison(
    entry_a: RepeatInput,
    values_a: np.ndarray,
    entry_b: RepeatInput,
    values_b: np.ndarray,
    profile_period_s: float,
) -> TemporalComparison:
    """The shared temporal view of the repeat pair, plus its band comparison.

    The band comparison is the largest absolute level difference
    ``10·log10(psd_prf600 / psd_res18)`` inside :data:`PSD_BAND_HZ`, its
    frequency and the median level difference in the same band — a magnitude
    statement about fluctuation energy, not a significance test.
    """
    series_a = temporal_series(entry_a, values_a, profile_period_s)
    series_b = temporal_series(entry_b, values_b, profile_period_s)
    frequency = np.asarray(series_a.frequency_hz)
    inside = (frequency >= PSD_BAND_HZ[0]) & (frequency <= PSD_BAND_HZ[1])
    levels = np.zeros(frequency.shape)
    levels[inside] = 10.0 * np.log10(
        np.asarray(series_a.psd_mean_mm2_s2_per_hz)[inside]
        / np.asarray(series_b.psd_mean_mm2_s2_per_hz)[inside]
    )
    worst = int(np.argmax(np.abs(levels)))
    rate_hz = 1.0 / profile_period_s
    return TemporalComparison(
        profile_period_s=profile_period_s,
        profile_rate_hz=rate_hz,
        segment_profiles=SEGMENT_PROFILES,
        segment_duration_s=series_a.segment_duration_s,
        frequency_resolution_hz=rate_hz / SEGMENT_PROFILES,
        nyquist_hz=rate_hz / 2.0,
        acf_max_lag_profiles=ACF_MAX_LAG_PROFILES,
        acf_estimator=ACF_ESTIMATOR,
        psd_window=PSD_WINDOW,
        psd_detrend=PSD_DETREND,
        psd_scaling=PSD_SCALING,
        mixer_setpoint_hz=MIXER_SETPOINT_HZ,
        band_hz=PSD_BAND_HZ,
        band_max_abs_level_difference_db=float(np.max(np.abs(levels))),
        band_max_difference_frequency_hz=float(frequency[worst]),
        band_median_level_difference_db=float(np.median(levels[inside])),
        segments=(series_a.segments, series_b.segments),
        series=(series_a, series_b),
    )


def build_reference_repeat(
    dataset_root: Path = DATASET_ROOT,
    manifest_path: Path = REPORT_DIR / "manifest.csv",
    *,
    analysis_commit: str | None = None,
) -> ReferenceRepeat:
    """Build the WP1 result for the only same-settings repeat.

    Args:
        dataset_root: root holding the ``<axis>/<label>.BDD`` points.
        manifest_path: the WP0 manifest the pair is selected from and re-checked
            against.
        analysis_commit: revision to record. ``None`` probes the checkout.

    Returns:
        The pair, the common-duration view, one :class:`GateRow` per gate and the
        declared screening_threshold.

    Raises:
        ReferenceRepeatError: for a manifest that does not select exactly this
            pair, a source hash that does not match the bytes, a decoded cell
            that disagrees with the manifest, or two recordings that are not a
            same-settings repeat.
    """
    rows = select_repeat_rows(manifest_path)
    root = Path(dataset_root)
    decoded = [_read_recording(root, row) for row in rows]
    entry_a, values_a, time_a, depths_a = decoded[0]
    entry_b, values_b, time_b, depths_b = decoded[1]
    _require_same_settings(entry_a, entry_b)
    if entry_a.gates != entry_b.gates or not np.allclose(
        depths_a, depths_b, rtol=0.0, atol=1e-9
    ):
        raise ReferenceRepeatError(
            f"{entry_a.relative_path} and {entry_b.relative_path} do not share a "
            "gate grid; a depth-resolved repeat needs the identical 50-gate grid"
        )
    revolutions = common_revolution_count([entry_a.duration_s, entry_b.duration_s])
    window_s = revolutions * NOMINAL_REVOLUTION_S
    window_a = _window(values_a, time_a, window_s)
    window_b = _window(values_b, time_b, window_s)
    metrics_a = gate_metrics(window_a)
    metrics_b = gate_metrics(window_b)
    profile_period_s = shared_profile_period_s(
        [entry_a.profile_period_s, entry_b.profile_period_s]
    )
    # R6: the recorded timestamps are measured, and the uniform grid the temporal view uses is
    # only kept where the measured phase error at the top of the analysed band stays inside the
    # tolerance; a record over it is refused by name rather than analysed on a grid it breaks.
    timestamps = timestamp_grid([
        measure_timestamps(entry, time_s, f_max_hz=1.0 / (2.0 * profile_period_s))
        for entry, time_s in ((entry_a, time_a), (entry_b, time_b))
    ])
    gate_rows = tuple(
        GateRow(
            gate_index=gate,
            depth_mm=float(depths_a[gate]),
            **{
                f"prf_600_{metric}_mm_s"
                if metric != "zero_fraction"
                else "prf_600_zero_fraction": float(metrics_a[metric][gate])
                for metric in METRICS
            },
            **{
                f"res_1_8_{metric}_mm_s"
                if metric != "zero_fraction"
                else "res_1_8_zero_fraction": float(metrics_b[metric][gate])
                for metric in METRICS
            },
            **{
                f"diff_{metric}_mm_s"
                if metric != "zero_fraction"
                else "diff_zero_fraction": float(
                    metrics_a[metric][gate] - metrics_b[metric][gate]
                )
                for metric in METRICS
            },
        )
        for gate in range(entry_a.gates)
    )
    absolute = np.abs([row.diff_mean_mm_s for row in gate_rows])
    worst = int(np.argmax(absolute))
    commit = analysis_commit if analysis_commit is not None else current_revision()
    return ReferenceRepeat(
        dataset_root=root.as_posix(),
        manifest_path=Path(manifest_path).as_posix(),
        manifest_sha256=f"sha256:{_sha256_file(Path(manifest_path))}",
        analysis_commit=commit,
        input_a=entry_a,
        input_b=entry_b,
        common=CommonView(
            nominal_rpm=NOMINAL_RPM,
            revolution_s=NOMINAL_REVOLUTION_S,
            revolutions=revolutions,
            window_s=window_s,
            start_s=float(time_a[0]),
            profiles_a=int(window_a.shape[0]),
            profiles_b=int(window_b.shape[0]),
            gates=entry_a.gates,
        ),
        screening_threshold=ObservedDiscrepancyScreeningThreshold(
            value_mm_s=float(absolute[worst]),
            gate_index=int(gate_rows[worst].gate_index),
            depth_mm=float(gate_rows[worst].depth_mm),
            median_abs_mean_difference_mm_s=float(np.median(absolute)),
        ),
        rows=gate_rows,
        temporal=temporal_comparison(
            entry_a, values_a, entry_b, values_b, profile_period_s
        ),
        timestamps=timestamps,
    )


# ── the artefacts a reviewer reads ─────────────────────────────────────


#: Metric definitions, recorded verbatim in the provenance document so the
#: table cannot be read without them.
DEFINITIONS: dict[str, str] = {
    "mean": (
        "arithmetic mean of the per-gate time series inside the common-duration "
        "window, mm/s"
    ),
    "median": "50th percentile of the same window, mm/s",
    "iqr": (
        "robust spread: interquartile range p75 - p25 of the same window, with "
        "linear-interpolated percentiles (numpy.percentile default), mm/s"
    ),
    "rms": (
        "root mean square about zero of the same window, mm/s: DC-inclusive, so "
        "a mean offset raises it (it is not a standard deviation)"
    ),
    "zero_fraction": (
        "count of samples exactly equal to 0.0 divided by the window length, "
        "dimensionless"
    ),
    "depth_view": (
        "each recording's native gate grid; both repeat files carry the identical "
        "50 gates from 10.1626666667 mm to 100.812666667 mm, so no interpolation "
        "or resampling is applied anywhere in this report"
    ),
    "time_view": (
        "common-duration window for every distributional metric; full record in "
        "non-overlapping segments of one shared duration for autocorrelation and "
        "PSD"
    ),
    "replicates": (
        "no profile and no gate is an independent experimental replicate: the "
        "pair is one recording each and their difference carries both "
        "repeatability and uncontrolled drift"
    ),
}

#: The marker/harmonic caveat that must travel with every temporal plot.
MIXER_SETPOINT_ROLE = (
    "nominal mixer marker only (500 RPM -> 8.33 Hz, one revolution = 0.12 s): "
    "these files carry no tachometer, so the setpoint is not a phase reference "
    "and no harmonic is attributed to it"
)


def csv_rows(model: ReferenceRepeat) -> tuple[dict[str, str], ...]:
    """The gate rows as formatted CSV cells, in :data:`COLUMNS` order."""
    return tuple(
        {column: format_cell(getattr(row, column)) for column in COLUMNS}
        for row in model.rows
    )


def csv_text(model: ReferenceRepeat) -> str:
    """Render ``reference-repeat.csv`` (LF endings, one trailing newline)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(COLUMNS), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    writer.writerows(csv_rows(model))
    return buffer.getvalue()


def _series_document(series: TemporalSeries) -> dict[str, object]:
    return {
        "relative_path": series.relative_path,
        "source_sha256": series.source_sha256,
        "profiles": series.profiles,
        "profiles_analysed": series.profiles_analysed,
        "segments": series.segments,
        "gates": series.gates,
        "acf": {
            "lag_s": list(series.lag_s),
            "lag_revolutions": list(series.lag_revolutions),
            "mean": list(series.acf_mean),
            "p10": list(series.acf_p10),
            "p90": list(series.acf_p90),
            "e_folding_lag_s": series.acf_e_folding_lag_s,
        },
        "psd": {
            "frequency_hz": list(series.frequency_hz),
            "mean_mm2_s2_per_hz": list(series.psd_mean_mm2_s2_per_hz),
            "p10_mm2_s2_per_hz": list(series.psd_p10_mm2_s2_per_hz),
            "p90_mm2_s2_per_hz": list(series.psd_p90_mm2_s2_per_hz),
        },
    }


def regeneration_command(model: ReferenceRepeat) -> str:
    """The exact command that reproduces the committed artefacts byte for byte."""
    return (
        ".venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat "
        f"--analysis-commit {model.analysis_commit or '<generator commit>'}"
    )


def figure_caption(model: ReferenceRepeat) -> str:
    """The caption the committed figure and the provenance document both carry.

    It names the pair, the signed difference orientation with its units, both
    time views, the temporal segment length and frequency resolution, the
    declared screening_threshold, the generator commit and the two caveats that keep the
    plots honest: the setpoint is not a phase reference, and profiles/gates are
    not independent replicates.
    """
    temporal = model.temporal
    series_a, series_b = temporal.series
    return (
        f"WP1 reference repeat: {REPEAT_PAIR[0]} vs {REPEAT_PAIR[1]} "
        "(identical operating settings). "
        f"Common-duration view: {model.common.revolutions} nominal "
        f"{model.common.nominal_rpm:g}-RPM revolutions = {model.common.window_s:.4g} s, "
        f"{model.common.profiles_a} / {model.common.profiles_b} profiles of the two "
        "recordings. "
        f"Difference = {DIFFERENCE_DEFINITION} (signed, mm/s), field by field. "
        "Declared sole-pair observed-discrepancy screening threshold = "
        f"{model.screening_threshold.value_mm_s:.4g} mm/s: the largest absolute per-gate "
        "mean difference over depth, the threshold every mean-profile effect is "
        "screened against — a non-causal screening outcome, not a bound on "
        "same-settings repeatability or uncontrolled drift. "
        f"Temporal view: full record in {temporal.segment_profiles}-profile "
        f"non-overlapping segments ({series_a.segments} / {series_b.segments} "
        f"segments, {temporal.segment_duration_s:.4g} s each, identical for both "
        f"files); frequency resolution {temporal.frequency_resolution_hz:.4g} Hz, "
        f"Nyquist {temporal.nyquist_hz:.4g} Hz, PSD {temporal.psd_window} window, "
        f"{temporal.psd_detrend} detrend, {temporal.psd_scaling} scaling. "
        f"{MIXER_SETPOINT_ROLE}. "
        f"Generated at commit {model.analysis_commit or 'unknown'} from "
        f"{model.manifest_path} ({model.manifest_sha256}); profiles and gates are "
        "not independent replicates, and the difference is a screening outcome, not a bound."
    )


def provenance_document(model: ReferenceRepeat) -> dict[str, object]:
    """The machine-readable record beside the table and the figure.

    Keys are inserted in a fixed order and floats keep Python's shortest
    round-trip representation, so a regeneration from the same commit is
    byte-identical.
    """
    temporal = model.temporal
    series_a, series_b = temporal.series
    return {
        "artefact": "reference-repeat",
        "analysis_commit": model.analysis_commit,
        "dataset_root": model.dataset_root,
        "manifest": {
            "path": model.manifest_path,
            "sha256": model.manifest_sha256,
        },
        "inputs": [
            {
                "relative_path": entry.relative_path,
                "axis": entry.axis,
                "requested_label": entry.requested_label,
                "source_sha256": entry.source_sha256,
                "profiles": entry.profiles,
                "gates": entry.gates,
                "duration_s": entry.duration_s,
                "profile_period_s": entry.profile_period_s,
                "prf_period_us": entry.prf_period_us,
                "resolution_mm": entry.resolution_mm,
                "burst_length": entry.burst_length,
                "emissions_per_profile": entry.emissions_per_profile,
                "emit_power": entry.emit_power,
                "sensitivity": entry.sensitivity,
                "tgc_mode": entry.tgc_mode,
                "sound_speed_ms": entry.sound_speed_ms,
                "velo_max_ms": entry.velo_max_ms,
            }
            for entry in (model.input_a, model.input_b)
        ],
        "timestamps": timestamp_document(model.timestamps),
        "difference": {
            "definition": DIFFERENCE_DEFINITION,
            "units": "mm/s",
            "note": (
                "every diff_* column is the prf/600 value minus the res/1-8 value "
                "at the same gate; a negative value means res/1-8 is faster there"
            ),
        },
        "definitions": dict(DEFINITIONS),
        "views": {
            "common_duration": {
                "nominal_rpm": model.common.nominal_rpm,
                "revolution_s": model.common.revolution_s,
                "revolutions": model.common.revolutions,
                "window_s": model.common.window_s,
                "start_s": model.common.start_s,
                "profiles_prf_600": model.common.profiles_a,
                "profiles_res_1_8": model.common.profiles_b,
                "gates": model.common.gates,
                "rule": (
                    "largest integer number of nominal revolutions fitting both "
                    "recordings, truncated per file by the recorded timestamps"
                ),
            },
            "temporal": {
                "profile_period_s": temporal.profile_period_s,
                "profile_rate_hz": temporal.profile_rate_hz,
                "segment_profiles": temporal.segment_profiles,
                "segment_duration_s": temporal.segment_duration_s,
                "frequency_resolution_hz": temporal.frequency_resolution_hz,
                "nyquist_hz": temporal.nyquist_hz,
                "acf_max_lag_profiles": temporal.acf_max_lag_profiles,
                "acf_estimator": temporal.acf_estimator,
                "psd_window": temporal.psd_window,
                "psd_detrend": temporal.psd_detrend,
                "psd_scaling": temporal.psd_scaling,
                "mixer_setpoint_hz": temporal.mixer_setpoint_hz,
                "mixer_setpoint_role": MIXER_SETPOINT_ROLE,
                "band_hz": list(temporal.band_hz),
                "band_max_abs_level_difference_db": (
                    temporal.band_max_abs_level_difference_db
                ),
                "band_max_difference_frequency_hz": (
                    temporal.band_max_difference_frequency_hz
                ),
                "band_median_level_difference_db": (
                    temporal.band_median_level_difference_db
                ),
                "segments": {
                    series_a.relative_path: series_a.segments,
                    series_b.relative_path: series_b.segments,
                },
                "e_folding_lag_s": {
                    series_a.relative_path: series_a.acf_e_folding_lag_s,
                    series_b.relative_path: series_b.acf_e_folding_lag_s,
                },
                "series": [
                    _series_document(series_a),
                    _series_document(series_b),
                ],
            },
        },
        "screening_threshold": {
            "metric": model.screening_threshold.metric,
            "units": model.screening_threshold.units,
            "value_mm_s": model.screening_threshold.value_mm_s,
            "gate_index": model.screening_threshold.gate_index,
            "depth_mm": model.screening_threshold.depth_mm,
            "median_abs_mean_difference_mm_s": (
                model.screening_threshold.median_abs_mean_difference_mm_s
            ),
            "scope": model.screening_threshold.scope,
        },
        "figure": {
            "path": f"{FIGURES_DIRNAME}/{FIGURE_NAME}",
            "caption": figure_caption(model),
            "panels": [
                (
                    "depth profiles: per-gate median with a median +/- IQR/2 band, "
                    "both recordings (common-duration view)"
                ),
                (
                    "signed difference prf/600 - res/1-8 versus depth with the "
                    "declared screening_threshold"
                ),
                (
                    "ensemble autocorrelation over the identical 50 gates versus "
                    "lag, both recordings"
                ),
                (
                    "ensemble PSD over the identical 50 gates versus frequency, "
                    "both recordings"
                ),
            ],
        },
        "regeneration": {
            "command": regeneration_command(model),
            "note": (
                "pass the recorded analysis_commit to reproduce these artefacts "
                "byte for byte; the bare command records the current HEAD"
            ),
        },
    }


# ── the figure ─────────────────────────────────────────────────────────


def _wrap(text: str, width: int = 108) -> str:
    """Wrap the caption into the figure's footnote without breaking words."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + len(word) + 1 <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def render_figure(
    model: ReferenceRepeat, path: Path, *, dpi: int = 150
) -> Path:
    """Write the four-panel WP1 figure, deterministically, and return its path.

    Panels: the two depth profiles (median ± IQR/2 over the common-duration
    view), their signed difference with the declared screening_threshold, and the two
    temporal comparisons — ensemble autocorrelation and ensemble PSD over the
    identical 50 gates on the one shared segment grid. The caption is part of
    the image, so the figure cannot be separated from its caveats.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    temporal = model.temporal
    series_a, series_b = temporal.series
    depth = np.asarray([row.depth_mm for row in model.rows])
    colors = {"a": "#1f77b4", "b": "#d62728"}
    labels = {REPEAT_PAIR[0]: "prf/600.BDD", REPEAT_PAIR[1]: "res/1-8.BDD"}

    figure, axes = plt.subplots(2, 2, figsize=(10.0, 8.0), dpi=dpi)
    profiles, difference_ax, acf_ax, psd_ax = axes.ravel()

    # (1) depth profiles, common-duration view
    for key, row_prefix, relative in (
        ("a", "prf_600", REPEAT_PAIR[0]),
        ("b", "res_1_8", REPEAT_PAIR[1]),
    ):
        median = np.asarray([getattr(row, f"{row_prefix}_median_mm_s") for row in model.rows])
        iqr = np.asarray([getattr(row, f"{row_prefix}_iqr_mm_s") for row in model.rows])
        profiles.plot(
            median,
            depth,
            color=colors[key],
            label=f"{labels[relative]} median",
            linewidth=1.4,
        )
        profiles.fill_betweenx(
            depth,
            median - iqr / 2.0,
            median + iqr / 2.0,
            color=colors[key],
            alpha=0.18,
            linewidth=0,
            label=f"{labels[relative]} ± IQR/2",
        )
    profiles.set_xlabel("velocity [mm/s]")
    profiles.set_ylabel("depth from transducer face [mm]")
    profiles.set_title(
        "depth profiles, common-duration view\n"
        f"{model.common.revolutions} rev = {model.common.window_s:.4g} s, "
        f"{model.common.profiles_a} profiles each",
        fontsize=9.5,
    )
    profiles.invert_yaxis()
    profiles.grid(alpha=0.2)
    profiles.legend(loc="upper left", fontsize=6.5, framealpha=0.9)

    # (2) the signed difference and the declared screening_threshold
    screening_threshold = model.screening_threshold.value_mm_s
    difference_ax.axvspan(-screening_threshold, screening_threshold, color="#999999", alpha=0.2, linewidth=0)
    difference_ax.plot(
        [row.diff_mean_mm_s for row in model.rows],
        depth,
        color="#111111",
        linewidth=1.6,
        label="per-gate mean difference",
    )
    difference_ax.plot(
        [row.diff_median_mm_s for row in model.rows],
        depth,
        color="#ff7f0e",
        linewidth=1.0,
        linestyle="--",
        label="per-gate median difference",
    )
    for sign in (-1.0, 1.0):
        difference_ax.axvline(
            sign * screening_threshold, color="#555555", linewidth=0.8, linestyle=":"
        )
    difference_ax.axvline(0.0, color="#bbbbbb", linewidth=0.8)
    difference_ax.set_xlabel("difference [mm/s]")
    difference_ax.set_ylabel("depth from transducer face [mm]")
    difference_ax.set_title(
        f"signed difference {DIFFERENCE_DEFINITION}\n"
        f"declared screening_threshold ±{screening_threshold:.4g} mm/s "
        f"(worst at {model.screening_threshold.depth_mm:.4g} mm)",
        fontsize=9.5,
    )
    difference_ax.invert_yaxis()
    difference_ax.grid(alpha=0.2)
    difference_ax.legend(loc="lower right", fontsize=6.5, framealpha=0.9)

    # (3) ensemble autocorrelation over the identical 50 gates
    for key, series in (("a", series_a), ("b", series_b)):
        lag = np.asarray(series.lag_revolutions)
        acf_ax.fill_between(
            lag,
            series.acf_p10,
            series.acf_p90,
            color=colors[key],
            alpha=0.12,
            linewidth=0,
        )
        acf_ax.plot(
            lag,
            series.acf_mean,
            color=colors[key],
            linewidth=1.4,
            label=(
                f"{labels[series.relative_path]} "
                f"(1/e at {series.acf_e_folding_lag_s:.3g} s)"
            ),
        )
    acf_ax.axhline(1.0 / math.e, color="#555555", linestyle=":", linewidth=0.8)
    acf_ax.axhline(0.0, color="#bbbbbb", linewidth=0.8)
    acf_ax.axvline(1.0, color="#999999", linestyle="--", linewidth=0.8)
    acf_ax.set_xlabel("lag [nominal revolutions]")
    acf_ax.set_ylabel("ensemble autocorrelation [-]")
    acf_ax.set_title(
        "temporal autocorrelation\n"
        f"mean over the identical {series_a.gates} gates; "
        f"{temporal.segment_profiles}-profile segments",
        fontsize=9.5,
    )
    acf_ax.grid(alpha=0.2)
    acf_ax.legend(loc="upper right", fontsize=6.5, framealpha=0.9)

    # (4) ensemble PSD over the identical 50 gates
    for key, series in (("a", series_a), ("b", series_b)):
        frequency = np.asarray(series.frequency_hz)[1:]
        mean = np.asarray(series.psd_mean_mm2_s2_per_hz)[1:]
        psd_ax.fill_between(
            frequency,
            np.asarray(series.psd_p10_mm2_s2_per_hz)[1:],
            np.asarray(series.psd_p90_mm2_s2_per_hz)[1:],
            color=colors[key],
            alpha=0.12,
            linewidth=0,
        )
        psd_ax.plot(
            frequency,
            mean,
            color=colors[key],
            linewidth=1.4,
            label=labels[series.relative_path],
        )
    band_lo, band_hi = temporal.band_hz
    psd_ax.axvspan(band_lo, band_hi, color="#999999", alpha=0.12, linewidth=0)
    psd_ax.axvline(
        temporal.mixer_setpoint_hz,
        color="#2ca02c",
        linestyle="--",
        linewidth=1.0,
        label=f"500 RPM marker {temporal.mixer_setpoint_hz:.3g} Hz (not a phase reference)",
    )
    psd_ax.axvline(
        temporal.nyquist_hz, color="#777777", linestyle=":", linewidth=0.8
    )
    psd_ax.set_xscale("log")
    psd_ax.set_yscale("log")
    psd_ax.set_xlabel("frequency [Hz]")
    psd_ax.set_ylabel("PSD [(mm/s)²/Hz]")
    psd_ax.set_title(
        "ensemble PSD\n"
        f"identical {series_a.gates} gates; Δf = "
        f"{temporal.frequency_resolution_hz:.4g} Hz",
        fontsize=9.5,
    )
    psd_ax.grid(alpha=0.2, which="both")
    psd_ax.legend(loc="upper right", fontsize=6.5, framealpha=0.9)
    psd_ax.text(
        0.98,
        0.04,
        f"{band_lo:g}–{band_hi:g} Hz: max |Δ| = "
        f"{temporal.band_max_abs_level_difference_db:.3g} dB, median "
        f"{temporal.band_median_level_difference_db:.2g} dB",
        transform=psd_ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
    )

    figure.suptitle(
        "WP1 sole-pair observed-discrepancy screening threshold — the only same-settings repeat in the "
        "committed mixer sweep",
        fontsize=11,
    )
    figure.text(
        0.01,
        0.012,
        _wrap(figure_caption(model)),
        fontsize=5.8,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(top=0.88, bottom=0.22, hspace=0.42, wspace=0.30)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=dpi)
    plt.close(figure)
    return target


def write_reference_repeat(
    dataset_root: Path = DATASET_ROOT,
    report_dir: Path = REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    analysis_commit: str | None = None,
) -> ReferenceRepeat:
    """Build the WP1 result and write the three reviewer-visible artefacts.

    ``reference-repeat.csv``, ``reference-repeat.provenance.json`` and
    ``figures/reference-repeat.png`` are written as UTF-8 with LF endings (the
    figure is binary), so two runs on the same inputs and commit produce
    identical bytes. Nothing is written when the build raises: a failed
    selection leaves no half-artefact behind.

    Args:
        dataset_root: root holding the ``<axis>/<label>.BDD`` points.
        report_dir: directory the artefacts land in (``figures/`` inside it).
        manifest_path: the WP0 manifest the pair is selected from; defaults to
            the committed ``<report_dir>/manifest.csv``.
        analysis_commit: revision to record; ``None`` probes the checkout.

    Returns:
        The built :class:`ReferenceRepeat`.
    """
    manifest = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(REPORT_DIR) / MANIFEST_NAME
    )
    model = build_reference_repeat(
        dataset_root, manifest, analysis_commit=analysis_commit
    )
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CSV_NAME).write_text(
        csv_text(model), encoding="utf-8", newline=""
    )
    (directory / PROVENANCE_NAME).write_text(
        json.dumps(provenance_document(model), indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    render_figure(model, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
