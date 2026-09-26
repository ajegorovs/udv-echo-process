"""SA2.1's calibration scaffold: the evidence behind ``SPECTRAL_UNIFORMITY_TOL``.

**This is not the SA2 estimator and must not become one.** It is a test-only module: nothing
under ``src/`` imports it, it is exported nowhere, and the spectral sum below exists so that the
*timestamp* calibration can measure a distortion instead of asserting one. SA2.2 implements the
reviewed public estimator contract (detrending, taper, one-sided normalization, units, the
result type) independently, and this module is not a prototype of it: it has no result type, no
detrending, no public API, and no claim to be reusable. If a later change finds itself importing
this from production, that is the sign that SA2.2 is being smuggled in sideways.

**What it measures.** The plan's §J procedure: take a tone, perturb the *sampled instants* the
analysis is given, and measure how far four quantities move away from the same tone on an exact
uniform grid. The estimator assumed by everyone involved is the one SA2 will ship - samples
treated as uniformly spaced at the adopted ``dt_eff = span / (N - 1)`` with bin spacing
``fs_eff / N``, a periodic Hann taper and the plan §I one-sided density - so the perturbation's
effect is measured on the estimator that will actually be applied, and nothing here is compared
against an estimator that does not exist.

**One construction, and it is the conservative one.** A perturbed axis is sampled at its own
perturbed instants: the values are the tone evaluated *at that axis's stamps*, and the stamps are
what the analysis is handed. The alternative reading - the instants were really uniform and only
the record is wrong - would make the distortion smaller for the family that matters most (a
rounded logger clock), so the construction here deliberately attributes the non-uniformity to the
axis rather than assuming a labelling error the analysis cannot detect. The unperturbed case is
the same construction on an exact uniform axis, so the two are the same functional and the
difference is the axis.

**Why the perturbed sum is a direct non-uniform sum.** The estimator assumes the samples sit on
``t_0 + n * dt_eff``. When they do not, the honest model of what it computes is the DFT of the
stored samples at their stored times, evaluated on the assumed uniform grid:
``X_k = sum_n w_n x_n exp(-2j pi f_k t_n)``. On an exact uniform axis this is the ordinary DFT
(pinned by a test), and because each axis reports its *own* ``fs_eff`` from its own span, the
perturbation's effect on the reported grid is included rather than idealized away.

**The families exist because one statistic cannot see all of them.** Five ways an axis can leave
a uniform grid, chosen so that the calibration can tell which *statistic* is sound rather than
merely which number is comfortable:

- ``quantized`` - every instant rounded to a clock quantum. This is what the instrument actually
  does (the committed stamps are rounded to 1e-4 s), and the rounding error does not accumulate;
- ``jitter`` - independent per-interval errors, which accumulate as a random walk;
- ``ramp`` - one interval error early, the opposite late, which accumulates to about half the
  span: the adversarial case for a fixed interval deviation, and the case that makes the interval
  statistic unsound as an admission operand;
- ``alternating`` - the interval error reverses every step, so the position error stays bounded;
- ``gap`` - one isolated long interval at a parameterized position, which the domination
  inequality of ``sparse_spectral_admission.GAP_DOMINANCE_RULE`` bounds from below.

Every family rescales its intervals to sum to the configured span, so all axes here share one
``dt_eff`` and the perturbation is the only difference.
"""

from __future__ import annotations

import contextlib
import io
import math
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from udv_echo_process.analysis.sparse_spectral_admission import DistortionBounds

#: The committed rate regimes, at the sample count and span the full-record view of one recording
#: of each configuration actually has (measured through the public reader; the four configurations
#: span 5.7x in rate, which is the acquisition's own range).
REGIMES: tuple[tuple[str, int, float], ...] = (
    ("emissions-8", 826, 12.5345),
    ("emissions-20", 560, 12.5179),
    ("emissions-64", 257, 12.4912),
    ("emissions-128", 144, 12.4686),
)

#: The nominal 500-RPM rotor reference, in Hz. Stated as the exact fraction rather than the
#: three-digit decimal these documents quote, so a bin-centring calculation is not quietly
#: rounded twice.
TARGET_ROTOR_REFERENCE_HZ = 25.0 / 3.0

#: The ~1 Hz recurrence scale this stage asks about, as a probe target rather than a hypothesis.
TARGET_RECURRENCE_HZ = 1.0

#: The interval-deviation grid. Two decades either side of the committed quantum's own value
#: (1e-4 s over a 15.2 ms interval is 6.5789e-3), so the threshold's neighbourhood is sampled
#: densely and both degenerate ends are represented.
DEVIATION_GRID: tuple[float, ...] = (
    0.0,
    1e-5,
    3e-5,
    1e-4,
    3e-4,
    1e-3,
    3e-3,
    1e-2,
    3e-2,
    1e-1,
    3e-1,
    1.0,
)

#: The gap-ratio grid: no gap, then one, then gaps spanning half a decade to 3x.
GAP_RATIO_GRID: tuple[float, ...] = (1.0001, 1.001, 1.01, 1.05, 1.1, 1.5, 3.0)

#: The jitter family's seed. Fixed, so the matrix is reproducible to the bit; a calibration that
#: could not be re-run would be an anecdote.
JITTER_SEED = 20260926

#: Which taper the calibration assumes. The plan's §I table names Hann, and the ENBW the eventual
#: estimator applies must follow from *these* coefficients rather than from a remembered "1.5
#: bins": the periodic convention is used here (``w[n] = 0.5 - 0.5 cos(2 pi n / N)``, the standard
#: spectral-estimation choice, whose ENBW is exactly 1.5 bins analytically) and the symmetric
#: convention is carried beside it in :func:`hann_enbw_bins`, so the difference between the two
#: conventions is a measured number rather than a convention nobody wrote down.
TAPER_CONVENTION = "periodic"

#: The band half-width, in bins, of the "band power" metric. Four bins around the tone's own bin:
#: wide enough to hold a Hann main lobe (four bins between zeros) and narrow enough that the metric
#: is about the tone rather than about the whole spectrum.
BAND_HALF_WIDTH_BINS = 4


class Distortion(NamedTuple):
    """One perturbed axis's four distortions against the same tone on the exact uniform grid.

    Frequencies are in bins of the baseline's grid; percentages are relative to the baseline's own
    value, so a quantity's finite-record bias cancels and only the axis's own contribution remains.
    """

    peak_frequency_error_bins: float
    band_power_error_percent: float
    windowed_power_error_percent: float
    target_response_error_percent: float

    def worst_fraction(self, bounds: DistortionBounds) -> float:
        """The distortion as a fraction of its own bound: above 1.0 means the bound is broken.

        The calibration's ordering statistic. Each metric is divided by its own declared bound, so
        the four are comparable and the largest fraction names the metric that binds.
        """
        return max(
            self.peak_frequency_error_bins / bounds.peak_frequency_error_bins,
            self.band_power_error_percent / bounds.band_power_error_percent,
            self.windowed_power_error_percent / bounds.windowed_power_error_percent,
            self.target_response_error_percent / bounds.target_response_error_percent,
        )

    def offending_metrics(self, bounds: DistortionBounds) -> tuple[str, ...]:
        """Every metric whose own bound this distortion breaks, in the bounds' own order.
        """
        broken = []
        if self.peak_frequency_error_bins > bounds.peak_frequency_error_bins:
            broken.append("peak_frequency_error_bins")
        if self.band_power_error_percent > bounds.band_power_error_percent:
            broken.append("band_power_error_percent")
        if self.windowed_power_error_percent > bounds.windowed_power_error_percent:
            broken.append("windowed_power_error_percent")
        if self.target_response_error_percent > bounds.target_response_error_percent:
            broken.append("target_response_error_percent")
        return tuple(broken)


class CalibrationCase(NamedTuple):
    """One perturbed axis measuring one tone: the axis's own statistics and its distortion.
    """

    family: str
    regime: str
    profiles: int
    span_s: float
    tone_label: str
    tone_hz: float
    on_bin: bool
    parameter: float
    duplicate_intervals: int
    negative_intervals: int
    strictly_increasing: bool
    max_relative_interval_deviation: float | None
    max_relative_timing_error: float | None
    largest_gap_ratio: float | None
    distortion: Distortion

    def operand(self, name: str) -> float | None:
        """One of the two candidate admission operands of this case, or ``None``.
        """
        if name == "timing_error":
            return self.max_relative_timing_error
        if name == "interval_deviation":
            return self.max_relative_interval_deviation
        raise ValueError(
            f"unknown operand {name!r}; the two are 'timing_error' and 'interval_deviation'"
        )

    @property
    def reaches_uniformity(self) -> bool:
        """Whether this axis is decided by the *uniformity* condition rather than by another one.

        The calibration's scope. An axis with two profiles sharing one stamp, or with an interval
        running backwards, is refused by the duplicate and monotonicity conditions before any
        uniformity threshold is consulted - and its spectrum is a degenerate quadratic form, not a
        distortion attributable to irregularity. Selecting the uniformity tolerance over such axes
        would let a pathology that another condition already refuses set this condition's
        threshold, which is both wrong and the one way a calibration can quietly import a topic it
        has no evidence about.
        """
        return (
            self.duplicate_intervals == 0
            and self.negative_intervals == 0
            and self.strictly_increasing
        )

    def report(self) -> str:
        """The case as one line, for the printed evidence.
        """
        return (
            f"{self.family}/{self.regime}/{self.tone_label}/p={self.parameter:g} "
            f"dev={self.max_relative_interval_deviation} "
            f"timing={self.max_relative_timing_error} dist={self.distortion}"
        )


def declared_bounds() -> DistortionBounds:
    """The plan's declared distortion bounds, read from the module that ships the policy.

    Imported here rather than restated, so a bound cannot be edited in the calibration while the
    shipped policy keeps another number - and so that the calibration provably consumes the
    *declared* bounds rather than ones chosen to produce a comfortable threshold.
    """
    from udv_echo_process.analysis.sparse_spectral_admission import (
        DECLARED_DISTORTION_BOUNDS,
    )

    return DECLARED_DISTORTION_BOUNDS


# --------------------------------------------------------------------------------------------
# tapers
# --------------------------------------------------------------------------------------------


def hann(count: int, *, convention: str = TAPER_CONVENTION) -> np.ndarray:
    """A Hann taper of ``count`` samples, in the named convention.

    ``periodic`` is ``0.5 - 0.5 cos(2 pi n / N)`` for ``n = 0 .. N - 1`` - the choice a spectral
    estimator uses, because its DFT is a sum of three adjacent bins with no wrap-around.
    ``symmetric`` is the same expression over ``N - 1``, which is the filter-design convention and
    is not the same taper at any finite ``N``.
    """
    if count < 1:
        raise ValueError(f"a taper of {count} sample(s) is not a taper")
    index = np.arange(count, dtype=float)
    denominator = float(count) if convention == "periodic" else float(count - 1)
    if denominator <= 0.0:
        raise ValueError(f"a {convention} taper needs at least two samples, got {count}")
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * index / denominator)


def hann_enbw_bins(count: int) -> dict[str, float]:
    """The equivalent noise bandwidth, in bins, derived from the actual coefficients.

    ``ENBW_bins = N * sum(w^2) / (sum(w))^2``. Derived rather than remembered, because the two Hann
    conventions differ: only the periodic taper gives exactly 1.5 bins, and a normalization that
    assumed 1.5 for whichever taper happened to be implemented would be applying another window's
    correction.
    """
    periodic = hann(count)
    symmetric = hann(count, convention="symmetric")
    return {
        "periodic": float(count * np.sum(periodic**2) / np.sum(periodic) ** 2),
        "symmetric": float(count * np.sum(symmetric**2) / np.sum(symmetric) ** 2),
    }


# --------------------------------------------------------------------------------------------
# axes: exact uniform, and the five perturbation families
# --------------------------------------------------------------------------------------------


def uniform_stamps(profiles: int, span_s: float) -> np.ndarray:
    """An exact uniform axis: ``profiles`` stamps spanning ``span_s`` exactly.
    """
    return np.linspace(0.0, float(span_s), int(profiles), dtype=float)


def _from_intervals(intervals: np.ndarray, span_s: float) -> np.ndarray:
    """Stamps from intervals rescaled to sum to ``span_s``, so every axis shares one ``dt_eff``.
    """
    rescaled = np.asarray(intervals, dtype=float) * (float(span_s) / float(np.sum(intervals)))
    return np.concatenate(([0.0], np.cumsum(rescaled)))


def quantized_stamps(profiles: int, span_s: float, deviation: float) -> np.ndarray:
    """Every instant rounded to a clock quantum of ``deviation`` effective intervals.

    The instrument's own pathology: the logger's timestamp resolution is fixed, so the deviation
    from the median interval is one quantum however long the interval is, and the rounding error
    does not accumulate.
    """
    exact = uniform_stamps(profiles, span_s)
    dt = float(span_s) / (profiles - 1)
    quantum = float(deviation) * dt
    if quantum <= 0.0:
        return exact
    return np.round(exact / quantum) * quantum


def jitter_stamps(profiles: int, span_s: float, deviation: float) -> np.ndarray:
    """Independent per-interval errors drawn uniformly from ``+/- deviation``, then rescaled.
    """
    if deviation <= 0.0:
        return uniform_stamps(profiles, span_s)
    dt = float(span_s) / (profiles - 1)
    generator = np.random.default_rng(JITTER_SEED)
    draw = generator.uniform(-1.0, 1.0, size=profiles - 1)
    return _from_intervals(dt * (1.0 + float(deviation) * draw), span_s)


def ramp_stamps(profiles: int, span_s: float, deviation: float) -> np.ndarray:
    """One interval error early and the opposite late: the accumulating worst case.

    Half the intervals run ``+deviation`` fast and half the same amount slow, which balances to the
    same span; the position error grows through the first half and returns through the second,
    reaching ``deviation * span / 2`` at its extreme - 5% of the span at ``deviation = 0.1``, and
    ``deviation * (profiles - 1) / 2`` effective intervals. This is the family that makes the two
    candidate operands disagree: at ``deviation = 0.1`` on the E8 geometry its interval deviation
    reads 0.222 while its timing error reads 41.3 intervals, and its measured distortion is *lower*
    than that of an ``alternating`` axis reading 0.182 and 0.0999 - so the interval deviation ranks
    the two axes the wrong way round.
    """
    if deviation <= 0.0:
        return uniform_stamps(profiles, span_s)
    dt = float(span_s) / (profiles - 1)
    half = (profiles - 1) // 2
    errors = np.concatenate(
        (np.full(half, float(deviation)), np.full(profiles - 1 - half, -float(deviation)))
    )
    return _from_intervals(dt * (1.0 + errors), span_s)


def alternating_stamps(profiles: int, span_s: float, deviation: float) -> np.ndarray:
    """The interval error reversing every step, so the position error stays bounded.

    The fastest error an interval sequence can carry - a half-sample jitter at the sampling rate -
    and therefore the family that scatters power furthest from the tone. Note that its *measured*
    interval deviation exceeds its declared one (0.182 against 0.1 on the E8 geometry): the axis has
    two interval levels and an odd number of intervals, so the design's median reference lands on
    whichever level the middle sample happens to be, inflating the relative deviation by up to
    1/0.9. The same parity accident moves the value by 22% while the axis is unchanged, which is a
    second reason the median-referenced spread is reported rather than admitted on.
    """
    if deviation <= 0.0:
        return uniform_stamps(profiles, span_s)
    dt = float(span_s) / (profiles - 1)
    signs = np.where(np.arange(profiles - 1) % 2 == 0, 1.0, -1.0)
    return _from_intervals(dt * (1.0 + float(deviation) * signs), span_s)


def gap_stamps(profiles: int, span_s: float, ratio: float, *, position: int = 1) -> np.ndarray:
    """One isolated interval of ``ratio`` times the others, at a stated position.

    ``position`` decides how much of the accumulation the axis reaches, and the domination
    inequality of ``sparse_spectral_admission.GAP_DOMINANCE_RULE`` is checked over positions rather
    than only at one.
    """
    intervals = np.ones(profiles - 1, dtype=float)
    intervals[int(position)] = float(ratio)
    return _from_intervals(intervals, span_s)


FAMILIES: dict[str, object] = {
    "quantized": quantized_stamps,
    "jitter": jitter_stamps,
    "ramp": ramp_stamps,
    "alternating": alternating_stamps,
}


# --------------------------------------------------------------------------------------------
# signals, the reference spectrum and the distortion metrics
# --------------------------------------------------------------------------------------------


def tone(stamps: np.ndarray, frequency_hz: float, *, phase: float = 0.0) -> np.ndarray:
    """One unit-amplitude tone evaluated at the given instants.

    The signal is a continuous-time sinusoid read at the axis's own stamps, so a perturbed axis
    samples the same physical signal at different instants - which is what the construction means,
    and the only form in which "the axis moved the spectrum" is a sentence about the axis.
    """
    return np.cos(2.0 * np.pi * float(frequency_hz) * np.asarray(stamps, dtype=float) + float(phase))


def tones(profiles: int, span_s: float) -> tuple[dict[str, object], ...]:
    """The tones one regime's grid can carry: both probe targets, on-bin and half-bin off.

    Bin-centred and off-bin tones are both included because they fail differently: a bin-centred
    tone's energy sits in one bin and a timestamp error spreads it, while an off-bin tone's energy
    is already split and a timestamp error shifts its centroid. A target that is not representable
    (above Nyquist, or too near DC or the top bin for the three-bin peak rule and the four-bin band
    to be well defined) is left out rather than silently tested at another frequency.
    """
    delta_f = (profiles - 1) / float(span_s) / profiles
    nyquist = 0.5 * (profiles - 1) / float(span_s)
    table = []
    for label, target in (
        ("recurrence-1hz", TARGET_RECURRENCE_HZ),
        ("rotor-8.333hz", TARGET_ROTOR_REFERENCE_HZ),
    ):
        nearest = round(target / delta_f)
        for on_bin, frequency in ((True, nearest * delta_f), (False, (nearest + 0.5) * delta_f)):
            if nearest < 3 or frequency <= 0.0:
                continue
            if frequency + 5.0 * delta_f >= nyquist:
                continue
            table.append(
                {
                    "label": f"{label}|{'on' if on_bin else 'off'}-bin",
                    "frequency_hz": float(frequency),
                    "on_bin": bool(on_bin),
                }
            )
    return tuple(table)


def spectra_for_tones(
    stamps: np.ndarray, signals: dict[str, np.ndarray], *, taper: np.ndarray
) -> dict[str, dict[str, object]]:
    """The assumed-uniform-grid DFT of samples taken at ``stamps``, one spectrum per tone.

    ``X_k = sum_n w_n x_n exp(-2j pi f_k t_n)`` with ``f_k = k * fs_eff / N`` and
    ``fs_eff = (N - 1) / (t[-1] - t[0])``; then ``Pxx_k = |X_k|^2 / (fs_eff * sum(w^2))`` with the
    conventional one-sided doubling of every bin except DC and the Nyquist bin (the latter only
    when ``N`` is even and that bin exists). On an exact uniform axis this is the ordinary
    rFFT-based periodogram, which a test pins.

    The transform matrix is built once and applied to every tone, because it depends on the axis
    and not on the signal.
    """
    axis = np.asarray(stamps, dtype=float)
    count = axis.size
    span = float(axis[-1] - axis[0])
    rate = (count - 1) / span
    delta_f = rate / count
    frequencies = np.arange(count // 2 + 1, dtype=float) * delta_f
    transform = np.exp(-2j * np.pi * np.outer(frequencies, axis))
    weights = np.asarray(taper, dtype=float)
    norm = rate * float(np.sum(weights**2))
    out: dict[str, dict[str, object]] = {}
    for label, values in signals.items():
        density = np.abs(transform @ (weights * np.asarray(values, dtype=float))) ** 2 / norm
        if density.size > 2:
            density[1:] *= 2.0
        if count % 2 == 0:
            density[-1] /= 2.0
        out[label] = {
            "frequency_hz": frequencies,
            "delta_f_hz": float(delta_f),
            "density": density,
            "effective_sample_rate_hz": float(rate),
            "nyquist_hz": float(0.5 * rate),
        }
    return out


def reference_spectrum(
    stamps: np.ndarray, values: np.ndarray, *, taper: np.ndarray
) -> dict[str, object]:
    """One tone's spectrum, the single-signal form of :func:`spectra_for_tones`.
    """
    return spectra_for_tones(stamps, {"tone": np.asarray(values, dtype=float)}, taper=taper)["tone"]


def peak_position_bins(
    density: np.ndarray, *, centre_bin: int, half_width: int = 2
) -> float:
    """Where a known tone's power sits, in bins: the power-weighted centroid of its main lobe.

    The centroid runs over the ``half_width`` bins either side of ``centre_bin`` - the tone's own
    nearest bin, which a calibration is allowed to know because the signal is synthetic - so the
    estimate is a continuous function of the perturbation.

    That continuity is the whole reason this rule and not an argmax rule is used. A peak locator
    that first finds the largest bin is *discontinuous*: a perturbation small enough to move the
    argmax by one bin moves the reported peak by the centroid's own curvature, which on a Hann
    taper at half-bin offset is 0.059 bins - twenty times the declared bound, present at every
    perturbation size including the smallest, and a property of the locator rather than of the
    axis. Measuring the axis with such a rule would report a distortion floor that no perturbation
    caused and hide the real dependence on the perturbation behind it.
    """
    density = np.asarray(density, dtype=float)
    low = max(int(centre_bin) - half_width, 0)
    high = min(int(centre_bin) + half_width, density.size - 1)
    indices = np.arange(low, high + 1, dtype=float)
    weights = density[low : high + 1]
    total = float(np.sum(weights))
    return float(centre_bin) if total <= 0.0 else float(np.sum(indices * weights) / total)


def band_power(spectrum: dict[str, object], centre_bin: int, *, half_width: int) -> float:
    """The power in ``centre_bin +/- half_width`` bins, each bin contributing its own width.
    """
    density = np.asarray(spectrum["density"], dtype=float)
    low = max(int(centre_bin) - half_width, 0)
    high = min(int(centre_bin) + half_width, density.size - 1)
    return float(np.sum(density[low : high + 1]) * float(spectrum["delta_f_hz"]))


def distortion(
    baseline: dict[str, object], case: dict[str, object], *, target_hz: float
) -> Distortion:
    """The four declared distortions of one perturbed spectrum against its uniform baseline.
    """
    baseline_delta = float(baseline["delta_f_hz"])
    baseline_density = np.asarray(baseline["density"], dtype=float)
    case_density = np.asarray(case["density"], dtype=float)
    centre = round(float(target_hz) / baseline_delta)
    centre = min(max(centre, 2), baseline_density.size - 3)
    baseline_band = band_power(baseline, centre, half_width=BAND_HALF_WIDTH_BINS)
    case_band = band_power(case, centre, half_width=BAND_HALF_WIDTH_BINS)
    baseline_total = float(np.sum(baseline_density) * baseline_delta)
    case_total = float(np.sum(case_density) * float(case["delta_f_hz"]))
    baseline_tone = float(baseline_density[centre])
    case_tone = float(case_density[centre])
    return Distortion(
        peak_frequency_error_bins=abs(
            peak_position_bins(case_density, centre_bin=centre)
            - peak_position_bins(baseline_density, centre_bin=centre)
        ),
        band_power_error_percent=(
            100.0 * abs(case_band - baseline_band) / baseline_band if baseline_band > 0.0 else 0.0
        ),
        windowed_power_error_percent=(
            100.0 * abs(case_total - baseline_total) / baseline_total
            if baseline_total > 0.0
            else 0.0
        ),
        target_response_error_percent=(
            100.0 * abs(case_tone - baseline_tone) / baseline_tone if baseline_tone > 0.0 else 0.0
        ),
    )


# --------------------------------------------------------------------------------------------
# the matrix
# --------------------------------------------------------------------------------------------


def axis_statistics(stamps: np.ndarray) -> dict[str, float | int | bool | None]:
    """The two candidate operands, the gap diagnostic and the pathology counts of one axis.

    Re-derived here instead of imported, so that the threshold is not checked against a statistic
    the module it calibrates computes: if those two ever disagreed, the calibration would be
    selecting a tolerance for a quantity nobody admits on. ``tests/test_sparse_spectral_calibration.py``
    pins the agreement on every constructed axis and on the committed ones.
    """
    intervals = np.diff(stamps)
    median = float(np.median(intervals))
    span = float(stamps[-1] - stamps[0])
    adopted = span / (stamps.size - 1)
    grid = stamps[0] + np.arange(stamps.size, dtype=float) * adopted
    duplicates = int(np.count_nonzero(intervals == 0.0))
    negatives = int(np.count_nonzero(intervals < 0.0))
    return {
        "duplicate_intervals": duplicates,
        "negative_intervals": negatives,
        "strictly_increasing": bool(not duplicates and not negatives),
        "max_relative_interval_deviation": (
            float(np.max(np.abs(intervals - median)) / median) if median > 0.0 else None
        ),
        "max_relative_timing_error": (
            float(np.max(np.abs(stamps - grid)) / adopted) if adopted > 0.0 else None
        ),
        "largest_gap_ratio": float(np.max(intervals) / median) if median > 0.0 else None,
    }


def calibration_matrix(
    *,
    regimes: tuple[tuple[str, int, float], ...] = REGIMES,
    deviations: tuple[float, ...] = DEVIATION_GRID,
    gap_ratios: tuple[float, ...] = GAP_RATIO_GRID,
) -> tuple[CalibrationCase, ...]:
    """Every perturbed axis measuring every tone its grid can carry, with its distortion.

    Deterministic: the jitter family is seeded and every other family is a closed-form
    construction, so two runs produce the same matrix to the bit.
    """
    cases: list[CalibrationCase] = []
    for regime, profiles, span in regimes:
        taper = hann(profiles)
        table = tones(profiles, span)
        perturbations: list[tuple[str, float, np.ndarray]] = []
        for family, builder in FAMILIES.items():
            for deviation in deviations:
                perturbations.append(
                    (family, float(deviation), builder(profiles, span, float(deviation)))
                )
        for ratio in gap_ratios:
            perturbations.append(("gap", float(ratio), gap_stamps(profiles, span, ratio)))
        for family, parameter, stamps in perturbations:
            signals = {str(item["label"]): tone(stamps, float(item["frequency_hz"])) for item in table}
            perturbed = spectra_for_tones(stamps, signals, taper=taper)
            uniform = uniform_stamps(profiles, span)
            baselines = spectra_for_tones(
                uniform,
                {
                    str(item["label"]): tone(uniform, float(item["frequency_hz"]))
                    for item in table
                },
                taper=taper,
            )
            statistics = axis_statistics(stamps)
            for item in table:
                label = str(item["label"])
                cases.append(
                    CalibrationCase(
                        family=family,
                        regime=regime,
                        profiles=int(profiles),
                        span_s=float(span),
                        tone_label=label,
                        tone_hz=float(item["frequency_hz"]),
                        on_bin=bool(item["on_bin"]),
                        parameter=float(parameter),
                        duplicate_intervals=int(statistics["duplicate_intervals"]),
                        negative_intervals=int(statistics["negative_intervals"]),
                        strictly_increasing=bool(statistics["strictly_increasing"]),
                        max_relative_interval_deviation=statistics[
                            "max_relative_interval_deviation"
                        ],
                        max_relative_timing_error=statistics["max_relative_timing_error"],
                        largest_gap_ratio=statistics["largest_gap_ratio"],
                        distortion=distortion(
                            baselines[label], perturbed[label], target_hz=float(item["frequency_hz"])
                        ),
                    )
                )
    return tuple(cases)


def select_tolerance(
    cases: tuple[CalibrationCase, ...], *, operand: str, bounds: DistortionBounds
) -> dict[str, object]:
    """The largest operand value at which the policy is still **sound**.

    The plan §J rule, stated so that it cannot be satisfied by an accident of sampling. For an
    operand ``v`` define

        sound(v)  <=>  every axis this matrix contains with ``operand <= v`` has all four measured
                       distortions inside the declared bounds

    and select ``tolerance = max { v : sound(v) }``. Note what this is *not*: it is not "the largest
    operand that some clean case was built with". That weaker reading is what a tolerance chosen
    first and illustrated afterwards would satisfy, and this matrix breaks it at once - there are
    axes at a large operand with mild distortion (a jog in the sample grid, absorbed by the adopted
    full-span interval) alongside axes at a small operand with severe distortion, so selecting the
    largest clean *value* would hand out a threshold that admits axes measurably worse than the one
    the bound was read off.

    Soundness therefore has to be tested over everything at or below the candidate, not just at it,
    and the returned ``violations`` are that test - empty by construction here, and asserted empty
    by the caller, which is what makes the threshold a measurement rather than a choice.

    The scope is every axis that reaches the uniformity condition at all
    (:attr:`CalibrationCase.reaches_uniformity`): an axis with duplicate stamps or a backwards
    interval is refused by another condition before uniformity is consulted.
    """
    scored = []
    for case in cases:
        value = case.operand(operand)
        if value is None or not case.reaches_uniformity:
            continue
        scored.append((float(value), case.distortion.worst_fraction(bounds) <= 1.0, case))
    if not scored:
        raise ValueError(
            f"no axis reaches the uniformity condition on the {operand!r} operand, so no "
            "tolerance can be selected at the declared bounds"
        )
    worst_breaking = min((value for value, clean, _ in scored if not clean), default=None)
    candidates = [
        value for value, clean, _ in scored if clean and (worst_breaking is None or value < worst_breaking)
    ]
    if not candidates:
        raise ValueError(
            f"every axis that reaches the uniformity condition already breaks a declared bound on "
            f"the {operand!r} operand (smallest at {worst_breaking!r}), so the statistic carries no "
            "sound threshold at these bounds"
        )
    tolerance = max(candidates)
    return {
        "operand": operand,
        "tolerance": float(tolerance),
        "violations": tuple(
            case
            for value, clean, case in scored
            if value <= tolerance and not clean
        ),
        "nearest_below": max((value for value, _, _ in scored if value < tolerance), default=None),
        "nearest_above": min((value for value, _, _ in scored if value > tolerance), default=None),
        "first_breaking": worst_breaking,
        "cases_considered": len(scored),
        "cases_inside": sum(1 for _, clean, _ in scored if clean),
    }


def worst_case(
    cases: tuple[CalibrationCase, ...],
    *,
    operand: str,
    bands: tuple[tuple[float, float], ...] = (),
) -> CalibrationCase | None:
    """The case with the largest distortion fraction, optionally within operand bands.

    Also scoped to the axes that reach the uniformity condition: a degenerate axis's distortion is
    not a distortion this condition is being calibrated to tolerate.
    """
    bounds = declared_bounds()
    pool = [
        case
        for case in cases
        if case.reaches_uniformity
        and (value := case.operand(operand)) is not None
        and (not bands or any(low <= float(value) <= high for low, high in bands))
    ]
    if not pool:
        return None
    return max(pool, key=lambda case: case.distortion.worst_fraction(bounds))


def worst_by_operand(
    cases: tuple[CalibrationCase, ...], *, operand: str
) -> tuple[tuple[str, float, float], ...]:
    """Worst distortion fraction per decade of the operand, in increasing operand order.

    The *monotonicity* evidence, and it is stated against the operand rather than against each
    family's perturbation parameter on purpose. A perturbation parameter is not a measurement: the
    ``quantized`` family's quantum is a *clock resolution*, and a quantum that happens to divide
    the interval exactly yields an exactly uniform axis (reported as such, with a near-zero timing
    error) - so its distortion is not monotone in its own parameter, while the axis it produces is
    perfectly well behaved. Ordering by the operand states the property that actually matters and
    that a threshold rests on: **the distortion does not fall as the operand grows**, across every
    family at once. A calibration whose distortion fell with its own admission statistic could not
    select a threshold at all.

    Returns:
        ``(bucket label, largest operand in that decade, worst distortion fraction)`` per decade.
    """
    bounds = declared_bounds()
    buckets: dict[int, tuple[float, float]] = {}
    for case in cases:
        value = case.operand(operand)
        if value is None or not case.reaches_uniformity:
            continue
        number = float(value)
        exponent = -300 if number <= 0.0 else math.floor(math.log10(number))
        fraction = case.distortion.worst_fraction(bounds)
        previous = buckets.get(exponent)
        buckets[exponent] = (
            number if previous is None else max(previous[0], number),
            fraction if previous is None else max(previous[1], fraction),
        )
    return tuple(
        (f"1e{exponent}", largest, fraction)
        for exponent, (largest, fraction) in sorted(buckets.items())
    )


def gap_domination_lower_bound(profiles: int, ratio: float) -> float:
    """The timing error one isolated interval of ``ratio`` forces, from the domination inequality.

    ``(g - 1) * (N - 1) / (N - 2 + g)``: the exact lower bound on ``max_relative_timing_error``
    for a gap of ratio ``g``, derived in
    ``sparse_spectral_admission.GAP_DOMINANCE_RULE``. A test checks it over constructed axes, which
    is what lets the gap statistic be a diagnostic instead of a second threshold.
    """
    return (float(ratio) - 1.0) * (profiles - 1) / (profiles - 2 + float(ratio))


def table(rows: tuple[tuple[object, ...], ...], header: tuple[str, ...]) -> str:
    """A fixed-width text table, for the printed calibration evidence.
    """
    widths = [
        max(len(str(header[index])), *(len(str(row[index])) for row in rows))
        for index in range(len(header))
    ]
    lines = ["  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(header))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(str(cell).ljust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(lines)


def _print_summary(cases: tuple[CalibrationCase, ...]) -> None:
    """Write the calibration evidence: both candidate tolerances, and whether each is sound.

    The two operands are reported together on purpose. The one that ships is the one whose
    admitted set contains no bound-violating case; the other is printed beside it because the
    difference between them is the finding, not a footnote.
    """
    bounds = declared_bounds()
    print(f"declared bounds: {bounds}")
    print(f"cases: {len(cases)}")
    print()
    for operand in ("timing_error", "interval_deviation"):
        outcome = select_tolerance(cases, operand=operand, bounds=bounds)
        print(f"operand                    : {operand}")
        print(f"selected tolerance         : {outcome['tolerance']:.6g}")
        print(f"nearest case below / above : {outcome['nearest_below']} / {outcome['nearest_above']}")
        print(
            f"cases considered / inside  : {outcome['cases_considered']} / {outcome['cases_inside']}"
        )
        print(f"violations at or below it  : {len(outcome['violations'])}")
        for case in outcome["violations"][:8]:
            print(
                f"    {case.family:12s} {case.regime:13s} {case.tone_label:24s} "
                f"operand={case.operand(operand):.6g} "
                f"frac={case.distortion.worst_fraction(bounds):.3g} "
                f"broke={case.distortion.offending_metrics(bounds)}"
            )
        print()
    print("worst case inside each selected tolerance")
    for operand in ("timing_error", "interval_deviation"):
        outcome = select_tolerance(cases, operand=operand, bounds=bounds)
        worst = worst_case(cases, operand=operand, bands=((0.0, outcome["tolerance"]),))
        print(f"  {operand:18s} tol={outcome['tolerance']:.6g}  {worst.report() if worst else None}")
    print()
    print("worst case immediately above each selected tolerance")
    for operand in ("timing_error", "interval_deviation"):
        outcome = select_tolerance(cases, operand=operand, bounds=bounds)
        above = outcome["nearest_above"]
        worst = worst_case(cases, operand=operand, bands=((float(above), float(above)),))
        print(f"  {operand:18s} operand={above}  {worst.report() if worst else None}")
    print()
    print("ENBW derived from the actual coefficients, in bins")
    for profiles in (138, 144, 257, 560, 790, 826):
        values = hann_enbw_bins(profiles)
        print(
            f"  N={profiles:4d}  periodic={values['periodic']:.12f}  "
            f"symmetric={values['symmetric']:.12f}"
        )
    print()
    print("worst distortion fraction by operand decade")
    for operand in ("timing_error", "interval_deviation"):
        rows = worst_by_operand(cases, operand=operand)
        print(f"  {operand} (bound fraction, per decade)")
        for label, largest, fraction in rows:
            print(f"    {label:>6s} up to {largest:.6g}  worst={fraction:.3g}")


def summary_text(cases: tuple[CalibrationCase, ...]) -> str:
    """The calibration evidence as text, so a test can assert what a reviewer will read.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_summary(cases)
    return buffer.getvalue()


def main() -> None:
    """Print the calibration evidence for the four committed rate regimes.

    ``python tests/_spectral_calibration.py`` reproduces the numbers the shipped tolerance was
    read off; the same text is asserted in ``tests/test_sparse_spectral_calibration.py``.
    """
    print(summary_text(calibration_matrix()))


if __name__ == "__main__":
    main()
