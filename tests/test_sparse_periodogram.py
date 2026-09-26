"""SA2.2: the periodogram is proved mathematically before any committed shape is read.

The order of this file is the order the contract asks for. First the taper and the grid, because
every number below depends on them. Then the cases whose answer is known in closed form - a
bin-centred tone, an off-bin tone, two tones, DC, a line, a constant, white noise - and each
parity separately, because the one-sided folding differs between them. Then the estimator against
an **independent oracle**: the SA2.1 calibration harness's own transform, which is a different
implementation of the same definition, on axes where both must agree. Only then the committed
recordings, and only as a smoke test.

No committed spectral *shape* is interpreted anywhere in this file: what is checked on real data
is that an admitted axis produces a finite density, that a refused one does not, and that asking
the periodogram about 8.333 Hz on an emissions-128 view changes nothing at all.
"""

from __future__ import annotations

import inspect
import math

import _spectral_calibration as calibration
import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    WindowView,
    full_record_view,
    primary_view,
    view_provenance,
    view_rule,
)
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES
from udv_echo_process.analysis.sparse_periodogram import (
    PARSEVAL_REL_TOL,
    TAPER_NAME,
    SpectralEstimate,
    SpectralPeriodogramError,
    SpectralVerdict,
    periodic_hann,
    periodogram_of_view,
    taper_enbw_bins,
)
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_support import one_sided_frequency_grid
from udv_echo_process.analysis.sparse_target_support import target_frequency_support

#: The synthetic cadence. An exact uniform axis, so the closed-form answers below are exact.
DT_S = 0.02

#: The rotor target, as the exact fraction the calibration harness states.
ROTOR_HZ = calibration.TARGET_ROTOR_REFERENCE_HZ

#: Even and odd sample counts, so every folding rule is exercised.
N_EVEN = 256
N_ODD = 255

#: The bins the synthetic tones sit on, and the second tone's amplitude.
K_FIRST = 20
K_SECOND = 40
SECOND_AMPLITUDE = 0.5


def _stamps(count: int, *, dt_s: float = DT_S) -> np.ndarray:
    """An exact uniform axis of ``count`` samples."""
    return np.arange(count, dtype=float) * dt_s


def _uniform(count: int, *, dt_s: float = DT_S) -> tuple[np.ndarray, float, float]:
    """``(stamps, fs_eff, delta_f)`` for an exact uniform axis of ``count`` samples."""
    axis = _stamps(count, dt_s=dt_s)
    span = float(axis[-1] - axis[0])
    rate = (count - 1) / span
    return axis, rate, rate / count


def _window(
    trace: np.ndarray,
    time_s: np.ndarray,
    *,
    gates: int = 1,
    support_mask: np.ndarray | None = None,
) -> WindowView:
    """The smallest honest labelled view around one synthetic trace.

    Built directly rather than through the three named constructors, so a test can choose the
    stamps and the support independently - the constructors' own behaviour is SA1's subject.
    """
    stamps = np.asarray(time_s, dtype=float).reshape(-1)
    depths = np.arange(gates, dtype=float) * 2.0 + 10.0
    values = np.zeros((stamps.size, depths.size))
    values[:, 0] = np.asarray(trace, dtype=float).reshape(-1)
    mask = np.ones(depths.size, dtype=bool) if support_mask is None else support_mask
    return WindowView(
        view=SparseView.PRIMARY,
        view_rule=view_rule(SparseView.PRIMARY),
        relative_path="synthetic.BDD",
        source_sha256="0" * 64,
        job="synthetic",
        point_label="synthetic",
        order=1,
        values=values,
        time_s=stamps,
        depths_mm=depths,
        support_mask=mask,
        native_gates=int(depths.size),
        native_depth_extent_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        pass_support_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        start_index=0,
        stop_index=int(stamps.size),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )


def _periodogram(
    trace: np.ndarray, time_s: np.ndarray, **settings: object
) -> SpectralEstimate:
    """One synthetic trace through the estimator, cut from a labelled view.

    The public entry point takes a view, so this wraps the trace in the smallest one. It is the
    only place these tests build a view for a synthetic trace, so every test below still reads as
    one trace in, one result out.
    """
    window = _window(trace, time_s, gates=int(settings.pop("gates", 1)))
    return periodogram_of_view(window, depth_mm=float(window.depths_mm[0]), **settings)


def _tone(stamps: np.ndarray, frequency_hz: float, *, amplitude: float = 1.0) -> np.ndarray:
    """A real cosine at ``frequency_hz`` over ``stamps``."""
    return amplitude * np.cos(2.0 * np.pi * frequency_hz * stamps)


# --------------------------------------------------------------------------------------
# the taper, and the ENBW that comes from its coefficients rather than from memory
# --------------------------------------------------------------------------------------


def test_the_taper_is_the_periodic_hann_and_its_enbw_comes_from_its_coefficients() -> None:
    for count in (N_EVEN, N_ODD, 138, 826):
        weights = periodic_hann(count)
        index = np.arange(count, dtype=float)
        assert np.allclose(weights, 0.5 - 0.5 * np.cos(2.0 * np.pi * index / count))
        enbw = taper_enbw_bins(weights)
        assert enbw == pytest.approx(1.5, rel=1e-12), (
            "the periodic Hann's ENBW is exactly 1.5 bins, and it must be *derived* to be "
            f"claimed: got {enbw} at N={count}"
        )


def test_the_symmetric_hann_is_measurably_a_different_window() -> None:
    """The convention is not cosmetic: the two Hanns differ by 1.5 * N / (N - 1) exactly."""
    for count in (138, N_EVEN, 826):
        index = np.arange(count, dtype=float)
        symmetric = 0.5 - 0.5 * np.cos(2.0 * np.pi * index / (count - 1))
        expected = 1.5 * count / (count - 1)
        assert taper_enbw_bins(symmetric) == pytest.approx(expected, rel=1e-12)
        assert taper_enbw_bins(symmetric) > taper_enbw_bins(periodic_hann(count))


def test_a_taper_that_cannot_have_a_bandwidth_is_refused() -> None:
    with pytest.raises(SpectralPeriodogramError, match="one-dimensional"):
        taper_enbw_bins(np.zeros((2, 2)))
    with pytest.raises(SpectralPeriodogramError, match="finite"):
        taper_enbw_bins(np.array([1.0, np.nan]))
    with pytest.raises(SpectralPeriodogramError, match="no equivalent noise bandwidth"):
        taper_enbw_bins(np.array([1.0, -1.0]))
    with pytest.raises(SpectralPeriodogramError, match="at least two samples"):
        periodic_hann(1)


# --------------------------------------------------------------------------------------
# the grid: SA2.1's, not a re-derived spacing
# --------------------------------------------------------------------------------------


def test_the_estimator_lands_on_the_sa21_grid_and_not_on_one_over_span() -> None:
    stamps, rate, delta = _uniform(N_EVEN)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)
    grid = one_sided_frequency_grid(N_EVEN, rate)

    assert estimate.frequency_hz.size == N_EVEN // 2 + 1
    assert np.allclose(estimate.frequency_hz, grid["frequencies_hz"], rtol=0.0, atol=1e-12), (
        "the estimator's grid must be SA2.1's own, to the float precision of the span-derived "
        "rate"
    )
    assert estimate.delta_f_hz == pytest.approx(delta, rel=1e-12)
    assert estimate.delta_f_hz != pytest.approx(1.0 / estimate.span_s, rel=1e-12), (
        "delta_f = fs_eff / N is not 1 / span under the adopted rate, and the estimate must "
        "report the grid it actually used"
    )
    assert estimate.frequency_hz[0] == 0.0
    assert estimate.frequency_hz[-1] == pytest.approx(rate / 2.0, rel=1e-12)


# --------------------------------------------------------------------------------------
# closed-form cases
# --------------------------------------------------------------------------------------


def test_a_bin_centred_tone_lands_in_its_own_bin_and_its_lobe_holds_the_power() -> None:
    """The Hann distribution, measured: a quarter, a half, a quarter.

    A property of *this* taper at *this* bin alignment, not a universal spectral fact: a tone
    exactly on a bin, through the periodic Hann, puts its three-bin lobe at 1/4, 1/2, 1/4 of its
    peak with no leakage elsewhere - a different taper or a tone off the bin gives other numbers,
    which the tests below measure separately.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)

    assert estimate.verdict is SpectralVerdict.DEFINED
    assert int(np.argmax(estimate.psd)) == K_FIRST
    assert estimate.taper_name == TAPER_NAME

    peak = float(estimate.psd[K_FIRST])
    for neighbour in (K_FIRST - 1, K_FIRST + 1):
        assert float(estimate.psd[neighbour]) == pytest.approx(0.25 * peak, rel=1e-9)
    outside = np.concatenate([estimate.psd[: K_FIRST - 1], estimate.psd[K_FIRST + 2 :]])
    assert float(np.max(np.abs(outside))) < 1e-20 * peak, (
        "a bin-centred tone through a periodic Hann leaks nowhere else at all"
    )
    lobe = float(np.sum(estimate.psd[K_FIRST - 1 : K_FIRST + 2]) * delta)
    assert lobe == pytest.approx(estimate.window_normalized_mean_square_power, rel=1e-12)
    assert lobe == pytest.approx(0.5, rel=1e-9), "a unit-amplitude cosine has mean square 1/2"


def test_the_peak_bin_is_not_the_tone_power() -> None:
    """The reading rule, pinned so no reader can mistake a bin for an amplitude.

    For a coherent line the taper's own factor is exact: ``(sum w)^2 / (N * sum w^2) = 2/3`` for
    the periodic Hann (coherent gain 1/2, ENBW 3/2), so the bin a tone lands in holds two thirds
    of its mean square and the other third sits in the two neighbouring bins.
    """
    stamps, rate, delta = _uniform(N_EVEN)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)

    weights = periodic_hann(N_EVEN)
    coherent = float(np.sum(weights) ** 2) / (N_EVEN * float(np.sum(weights**2)))
    assert coherent == pytest.approx(2.0 / 3.0, rel=1e-12)
    assert rate > 0.0

    peak_power = float(estimate.psd[K_FIRST]) * delta
    total = float(estimate.window_normalized_mean_square_power)
    assert peak_power == pytest.approx(coherent * total, rel=1e-9)
    assert peak_power == pytest.approx(1.0 / 3.0, rel=1e-9)
    assert peak_power != pytest.approx(total, rel=1e-9), (
        "the peak bin is two thirds of the tone's mean square, never the tone's amplitude or "
        "its power: the lobe has to be summed"
    )


def test_an_off_bin_tone_conserves_power_and_leaks_into_its_neighbours() -> None:
    """Half a bin off: the power is conserved, the pair is symmetric, and the kernel widens.

    The measured pattern, which is what makes the reading rule non-obvious: the two bins the tone
    lies between hold ~0.4803 each, their outer neighbours ~0.0192 each, and the next pair out
    ~0.0004 each - so a half-bin tone is *not* confined to two bins, while a bin-centred one is
    confined to three exactly.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    on_bin = _periodogram(_tone(stamps, K_FIRST * delta), stamps)
    half = _periodogram(_tone(stamps, (K_FIRST + 0.5) * delta), stamps)
    share = lambda index: float(half.psd[index]) * delta / half.window_normalized_mean_square_power

    # The *signal's* mean square is not exactly 1/2 at a half-bin offset (its own sample mean is
    # not exactly zero, so removing it moves the mean square), which is why the two estimates'
    # windowed powers differ slightly. That is the signal, not the estimator.
    assert on_bin.window_normalized_mean_square_power == pytest.approx(0.5, rel=1e-9)
    assert half.window_normalized_mean_square_power == pytest.approx(0.5, rel=1e-4)
    assert half.integrated_psd_power == pytest.approx(
        half.window_normalized_mean_square_power, rel=1e-12
    ), "power is conserved whatever the tone's offset from the grid"
    assert abs(half.parseval_relative_error) < 1e-12, (
        "on an exactly uniform axis the fold is orthogonal, so the identity is exact"
    )
    assert share(K_FIRST) == pytest.approx(share(K_FIRST + 1), rel=1e-4), (
        "a half-bin tone is symmetric about the midpoint between two bins"
    )
    assert share(K_FIRST) == pytest.approx(0.4803, abs=1e-3)
    assert share(K_FIRST - 1) == pytest.approx(0.0192, abs=1e-3)
    assert share(K_FIRST - 2) == pytest.approx(0.00039, abs=1e-4)
    assert int(np.argmax(half.psd)) in (K_FIRST, K_FIRST + 1)
    cell = float(np.sum(half.psd[K_FIRST - 4 : K_FIRST + 5]) * delta)
    assert cell / half.window_normalized_mean_square_power > 0.9999, (
        "the four-bin-wide cell of a half-bin tone holds all but ~2e-5 of the power"
    )


def test_two_separated_tones_are_each_recovered() -> None:
    stamps, _rate, delta = _uniform(N_EVEN)
    both = _tone(stamps, K_FIRST * delta) + _tone(
        stamps, K_SECOND * delta, amplitude=SECOND_AMPLITUDE
    )
    estimate = _periodogram(both, stamps)

    for index, amplitude in ((K_FIRST, 1.0), (K_SECOND, SECOND_AMPLITUDE)):
        cell = float(np.sum(estimate.psd[index - 1 : index + 2]) * delta)
        assert cell == pytest.approx(0.5 * amplitude**2, rel=1e-9), (
            f"the tone at bin {index} must carry mean square {0.5 * amplitude**2}"
        )
        assert float(estimate.psd[index]) > float(estimate.psd[index - 1])
    assert estimate.window_normalized_mean_square_power == pytest.approx(
        0.5 * (1.0 + SECOND_AMPLITUDE**2), rel=1e-9
    )


def test_mean_removal_takes_the_dc_bin_and_records_that_it_ran() -> None:
    """A DC offset, with and without removal - and the Hann's own DC factor, measured."""
    stamps, _rate, delta = _uniform(N_EVEN)
    offset = 7.5
    signal = offset + _tone(stamps, K_FIRST * delta)

    kept = _periodogram(signal, stamps, detrending=Detrending.NONE)
    removed = _periodogram(signal, stamps, detrending=Detrending.MEAN)

    # With the offset kept, the DC bin holds the same coherent factor as a tone's own bin -
    # (sum w)^2 / (N * sum w^2) = 2/3 - so a bin is never the offset's power either.
    assert float(kept.psd[0]) * delta == pytest.approx((2.0 / 3.0) * offset**2, rel=1e-9)
    assert kept.trace_mean_mm_s == pytest.approx(offset, rel=1e-12)
    assert float(kept.psd[K_FIRST]) * delta == pytest.approx(1.0 / 3.0, rel=1e-9), (
        "the tone is unaffected by the offset that shares the transform"
    )

    assert removed.detrending is Detrending.MEAN
    assert removed.trace_mean_mm_s == pytest.approx(offset, rel=1e-12), (
        "the result records the offset that was removed, so the reader can see that it was"
    )
    assert float(removed.psd[0]) < 1e-20 * float(removed.psd[K_FIRST])
    assert float(removed.psd[K_FIRST]) * delta == pytest.approx(1.0 / 3.0, rel=1e-9)
    assert removed.window_normalized_mean_square_power == pytest.approx(0.5, rel=1e-9)


def test_linear_detrending_reports_the_slope_it_removed_and_keeps_sa1s_order() -> None:
    """A pure line is removed exactly; a line plus a tone is removed and fitted, within reason.

    Two halves, because they say different things. On a pure line the removal is exact - slope to
    machine precision and a windowed power at the noise floor - which is what proves the fit is a
    least-squares line over the stored stamps and not something approximating one. On a line that
    shares the trace with a tone the *fitted* slope is only close (the tone correlates with the
    line a little over a finite window), so it is asserted as close, and the tone's survival is
    asserted separately.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    slope = 3.25

    pure = _periodogram(slope * stamps, stamps, detrending=Detrending.MEAN_AND_LINEAR)
    assert pure.linear_trend_per_s == pytest.approx(slope, rel=1e-9), (
        "a pure line is what the least-squares fit is exact on"
    )
    assert pure.window_normalized_mean_square_power < 1e-20, "and it leaves nothing behind"

    mixed = _periodogram(slope * stamps + _tone(stamps, K_FIRST * delta), stamps,
                         detrending=Detrending.MEAN_AND_LINEAR)
    mean = _periodogram(slope * stamps + _tone(stamps, K_FIRST * delta), stamps,
                        detrending=Detrending.MEAN)
    assert mixed.linear_trend_per_s == pytest.approx(slope, rel=1e-2), (
        "the fitted slope is the line the trace holds, to within the tone's own correlation "
        "with a line over a finite window"
    )
    assert mean.linear_trend_per_s is None, "a trend is reported exactly when a line was removed"
    assert int(np.argmax(mixed.psd)) == K_FIRST, "the tone survives the line's removal"
    assert float(mixed.psd[K_FIRST]) * delta == pytest.approx(1.0 / 3.0, rel=1e-3)
    assert float(mixed.psd[1]) * delta < 1e-3 * float(mixed.psd[K_FIRST]) * delta, (
        "what the removed line leaves behind is small and low-frequency, not a second tone"
    )


def test_a_constant_trace_is_a_zero_density_and_is_never_normalized_to_itself() -> None:
    """Decided deliberately: not refused, and never scaled into a shape.

    A mean-removed constant is a zero signal, and this estimator's normalization is absolute - a
    density per Hz - so the answer is exactly zero everywhere with the zero power reported beside
    it. What it must never become is a curve normalized by its own signal power, which is the
    only way a zero signal could produce a "shape".

    A constant that is *not* removed is a pure DC line, and the taper's own three-bin kernel is
    visible on it: two thirds at DC and one third in the first bin (the negative-frequency image
    folds onto it), nothing beyond. That is the taper, not a signal - again a property of this
    taper and this bin alignment, not a universal spectral fact.

    The contrast with SA1's normalized ACF is deliberate and worth stating: there the
    normalization divides by the signal's energy, so a constant after centring is *undefined* and
    the recurrence path refuses it. Here the density is absolute, so the zero signal has a
    perfectly well-defined zero density and it is returned as one.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    offset = 4.0
    constant = np.full(N_EVEN, offset)

    for detrending in (Detrending.MEAN, Detrending.MEAN_AND_LINEAR):
        estimate = _periodogram(constant, stamps, detrending=detrending)
        assert estimate.verdict is SpectralVerdict.DEFINED
        assert float(np.max(np.abs(estimate.psd))) <= 1e-24
        assert estimate.window_normalized_mean_square_power < 1e-24
        assert estimate.integrated_psd_power < 1e-24

    kept = _periodogram(constant, stamps, detrending=Detrending.NONE)
    assert float(kept.psd[0]) * delta == pytest.approx((2.0 / 3.0) * offset**2, rel=1e-9)
    assert float(kept.psd[1]) * delta == pytest.approx((1.0 / 3.0) * offset**2, rel=1e-9)
    assert float(np.max(kept.psd[2:])) < 1e-20 * float(kept.psd[0]), (
        "beyond the taper's own kernel a constant has nothing at all"
    )
    assert float(np.sum(kept.psd) * delta) == pytest.approx(offset**2, rel=1e-9), (
        "the whole density of a constant integrates to exactly its square"
    )


def test_seeded_white_noise_recovers_its_variance_and_its_share_per_band() -> None:
    """The normalization, checked statistically rather than asserted.

    Both directions: the whole integrated density recovers the analysed variance, and a band of
    interior bins recovers the fraction of it that band should hold. The second is what makes the
    *per-bin* level - and therefore the unit - correct rather than merely the total.
    """
    variance = 2.25
    realisations = 60
    band_lo, band_hi = 10, 40
    totals: list[float] = []
    bands: list[float] = []
    for seed in range(realisations):
        stamps, _rate, delta = _uniform(N_EVEN)
        rng = np.random.default_rng(seed)
        trace = np.sqrt(variance) * rng.normal(size=N_EVEN)
        estimate = _periodogram(trace, stamps)
        totals.append(float(estimate.integrated_psd_power))
        bands.append(float(np.sum(estimate.psd[band_lo : band_hi + 1]) * delta))

    # The analysed series is mean-removed, so its variance is (N - 1) / N of the drawn variance.
    analysed = variance * (N_EVEN - 1) / N_EVEN
    mean_total = float(np.mean(totals))
    assert mean_total == pytest.approx(analysed, rel=0.08), (
        f"the integrated density must recover the analysed variance: {mean_total} vs {analysed}"
    )
    # An interior bin is doubled (its negative-frequency image folds onto it), so a band of
    # interior bins holds *twice* its bin count's share of the power, not its count's share.
    expected_band = analysed * 2.0 * (band_hi - band_lo + 1) / N_EVEN
    mean_band = float(np.mean(bands))
    assert mean_band == pytest.approx(expected_band, rel=0.12), (
        f"a band of interior bins must hold its own doubled share of the power: {mean_band} vs "
        f"{expected_band}"
    )


# --------------------------------------------------------------------------------------
# parity: the folding rule, one branch at a time
# --------------------------------------------------------------------------------------


def test_even_n_represents_nyquist_and_does_not_double_that_bin() -> None:
    """The top bin sits exactly at Nyquist, and its share shows it was not double-counted."""
    stamps, rate, delta = _uniform(N_EVEN)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)

    assert estimate.nyquist_is_represented is True
    assert estimate.frequency_hz[-1] == pytest.approx(rate / 2.0, rel=1e-12)
    # a Nyquist-rate tone (alternating +A, -A) is what the top bin represents: measured, it
    # holds two thirds of the tone's mean square and its neighbour one third - the *folded*
    # image, not a doubled top bin (doubling would put two thirds in each).
    nyquist_tone = np.zeros(N_EVEN)
    nyquist_tone[::2] = 1.0
    nyquist_tone[1::2] = -1.0
    top = _periodogram(nyquist_tone, stamps)
    assert int(np.argmax(top.psd)) == N_EVEN // 2
    total = float(top.window_normalized_mean_square_power)
    assert total == pytest.approx(1.0, rel=1e-9), "an alternating unit tone has mean square 1"
    assert float(top.psd[-1]) * delta == pytest.approx((2.0 / 3.0) * total, rel=1e-9)
    assert float(top.psd[-2]) * delta == pytest.approx((1.0 / 3.0) * total, rel=1e-9)
    assert float(np.sum(top.psd[-2:]) * delta) == pytest.approx(total, rel=1e-9)
    assert float(np.sum(top.psd[:-2]) * delta) < 1e-20, (
        "a Nyquist-rate tone has no power anywhere but its own fold"
    )


def test_odd_n_does_not_represent_nyquist_and_doubles_its_top_bin() -> None:
    stamps, rate, delta = _uniform(N_ODD)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)

    assert estimate.nyquist_is_represented is False
    assert estimate.frequency_hz[-1] == pytest.approx(rate / 2.0 - delta / 2.0, rel=1e-12)
    assert estimate.frequency_hz[-1] < rate / 2.0
    assert abs(estimate.parseval_relative_error) < 1e-12, (
        "the odd-N folding closes exactly on a uniform axis without a Nyquist bin to halve"
    )
    # and the parity claim itself: the same tone's share of the top bin differs between parities
    # only because the bin a tone lands in is a different distance from Nyquist, never because
    # one parity was halved and the other was not
    even = _periodogram(_tone(stamps, K_FIRST * delta), stamps)
    assert int(np.argmax(even.psd)) == K_FIRST


def test_the_parseval_identity_holds_at_floating_point_accuracy() -> None:
    """The identity as the implementation invariant it now is, not as a scientific allowance.

    The transform is the orthogonal DFT of the assumed uniform sequence, so the folded density
    integrates to the window-normalized mean square for **every** defined spectrum - on this
    synthetic axis and, the committed smoke below asserts, on real irregular stamps too. It is
    therefore checked at floating-point accuracy, and it is *not* a measure of how irregular the
    stamps were: that is the admission's ``max_relative_timing_error``.
    """
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)
        error = estimate.parseval_relative_error
        assert error is not None
        assert abs(error) <= PARSEVAL_REL_TOL, (count, error)
        assert abs(error) < 1e-14, (
            "the fold is orthogonal arithmetic on a signal whose taper is known exactly, so the "
            f"identity must close far inside the bound: got {error}"
        )


def test_the_parseval_identity_is_checked_on_construction_not_merely_reported() -> None:
    """A wrong folding rule still looks like a spectrum, so the model refuses one."""
    stamps, _rate, delta = _uniform(N_EVEN)
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)
    payload = estimate.model_dump()
    payload["parseval_relative_error"] = 0.5  # a folding error would be this large
    with pytest.raises(ValidationError, match="Parseval"):
        SpectralEstimate(**payload)

    payload = estimate.model_dump()
    payload["parseval_relative_error"] = None
    with pytest.raises(ValidationError, match="always available"):
        SpectralEstimate(**payload)

    payload = estimate.model_dump()
    payload["psd"] = np.asarray(estimate.psd)[:-1]
    with pytest.raises(ValidationError, match="one density per grid frequency"):
        SpectralEstimate(**payload)


def _spectral_difference(
    production: np.ndarray, reference: np.ndarray, *, delta_f: float
) -> dict[str, float]:
    """Three scalars comparing a production density with a nonuniform reference density.

    ``integrated`` is the relative difference of the integrated power, ``worst_bin`` the largest
    single-bin difference relative to the reference's peak, and ``l1``/``l2`` the normalized
    one- and two-norm spectral differences. They are diagnostics: nothing downstream is gated on
    them, and they are not admission thresholds.
    """
    left = np.asarray(production, dtype=float)
    right = np.asarray(reference, dtype=float)
    assert left.size == right.size
    peak = float(np.max(right))
    return {
        "integrated": abs(float(np.sum(left) * delta_f) - float(np.sum(right) * delta_f))
        / max(float(np.sum(right) * delta_f), 1e-300),
        "worst_bin": float(np.max(np.abs(left - right))) / max(peak, 1e-300),
        "l1": float(np.sum(np.abs(left - right))) / max(float(np.sum(right)), 1e-300),
        "l2": float(np.sqrt(np.sum((left - right) ** 2)))
        / max(float(np.sqrt(np.sum(right**2))), 1e-300),
    }


def test_the_production_transform_makes_the_admitted_approximation() -> None:
    """The estimator uses the adopted grid, not the stored times - shown by an invariance.

    Two axes with the same endpoints and the same sample count differ only *inside*: one exactly
    uniform, one jittered far inside the admitted timing error. The production spectra are
    therefore **bit-identical** under ``Detrending.NONE``, because the Fourier basis is the
    adopted uniform grid and the endpoints and ``N`` are all it depends on. The nonuniform
    reference, which evaluates at the stored times, disagrees with *itself* on those two axes -
    which is exactly why it is the oracle and not the estimator.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    rng = np.random.default_rng(20260926)
    jittered = stamps + rng.normal(scale=1e-3 * DT_S, size=N_EVEN)
    jittered[0], jittered[-1] = stamps[0], stamps[-1]
    trace = _tone(stamps, K_FIRST * delta) + 0.2 * _tone(stamps, K_SECOND * delta)

    plain = _periodogram(trace, stamps, detrending=Detrending.NONE)
    moved = _periodogram(trace, jittered, detrending=Detrending.NONE)

    assert plain.verdict is SpectralVerdict.DEFINED
    assert moved.verdict is SpectralVerdict.DEFINED
    timing = moved.admission.characterization.max_relative_timing_error
    assert timing is not None and timing > 0.0, (
        "the second axis really did move off the uniform grid, so the invariance below is not "
        "vacuous"
    )
    assert np.array_equal(plain.psd, moved.psd), (
        "the production transform must not depend on the stored stamps inside the window: its "
        "Fourier coordinates are the admitted uniform grid"
    )
    assert np.array_equal(plain.frequency_hz, moved.frequency_hz)

    taper = calibration.hann(N_EVEN)
    uniform_reference = np.asarray(
        calibration.reference_spectrum(stamps, trace, taper=taper)["density"], dtype=float
    )
    moved_reference = np.asarray(
        calibration.reference_spectrum(jittered, trace, taper=taper)["density"], dtype=float
    )
    assert not np.allclose(uniform_reference, moved_reference, rtol=1e-9, atol=1e-12), (
        "the stored-timestamp reference must move with the stamps, or it is not that reference"
    )


def test_an_admitted_but_irregular_axis_is_the_uniform_estimate_by_a_bounded_amount() -> None:
    """The approximation the admission granted, quantified where it is made.

    On a jittered axis that is admitted, the production spectrum is the *uniform-grid* estimate of
    the trace - it agrees with the reference evaluated on the exact uniform axis - while it differs
    from the reference evaluated at the stored times. That difference is the cost of the
    approximation, it is measurable, it is bounded here as a recorded diagnostic (never as an
    admission threshold), and the admission carries the timing error that justified it.
    """
    stamps, _rate, delta = _uniform(N_EVEN)
    rng = np.random.default_rng(7)
    jittered = stamps + rng.normal(scale=2e-2 * DT_S, size=N_EVEN)
    jittered[0], jittered[-1] = stamps[0], stamps[-1]
    trace = _tone(stamps, K_FIRST * delta) + 0.2 * _tone(stamps, K_SECOND * delta)
    analysed = trace - float(np.mean(trace))

    production = _periodogram(trace, jittered)
    assert production.verdict is SpectralVerdict.DEFINED
    timing = production.admission.characterization.max_relative_timing_error
    assert timing is not None and 0.0 < timing <= production.admission.spectral_uniformity_tol, (
        "the axis is admitted and irregular: the timing error that admitted it travels on the "
        f"result, got {timing}"
    )

    taper = calibration.hann(N_EVEN)
    as_uniform = np.asarray(
        calibration.reference_spectrum(stamps, analysed, taper=taper)["density"], dtype=float
    )
    as_stored = np.asarray(
        calibration.reference_spectrum(jittered, analysed, taper=taper)["density"], dtype=float
    )
    assert np.allclose(production.psd, as_uniform, rtol=1e-9, atol=1e-12), (
        "the production estimator must be the uniform-grid estimate, not the stored-times one"
    )
    difference = _spectral_difference(
        production.psd, as_stored, delta_f=float(production.delta_f_hz)
    )
    assert difference["integrated"] > 0.0, (
        "on an irregular axis the two estimators are not the same estimator, and the difference "
        "must be visible"
    )
    for name, value in difference.items():
        assert value < 0.05, (name, value, "recorded order, not a threshold")


# --------------------------------------------------------------------------------------
# the independent oracle
# --------------------------------------------------------------------------------------


def test_the_estimator_agrees_with_the_sa21_reference_on_exact_uniform_axes() -> None:
    """Two implementations of one definition, compared only where both apply.

    The reference is the SA2.1 calibration harness's transform - a different code path, written
    for the calibration - so agreement here is implementation independence, not a tautology. It
    is only meaningful on an exact uniform axis, which is exactly where the assumed-grid
    estimator's assumption holds and the two must coincide.
    """
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        cases = [("first", K_FIRST, 1.0), ("second", K_SECOND, SECOND_AMPLITUDE)]
        if count == N_EVEN:
            # the Nyquist-rate tone: the case where the two parities must differ, and the only
            # signal that tests the even-N halving rule rather than assuming its absence
            cases.append(("nyquist", count // 2, 1.0))
        for name, bin_index, amplitude in cases:
            if name == "nyquist":
                trace = np.empty(count)
                trace[::2] = amplitude
                trace[1::2] = -amplitude
            else:
                trace = _tone(stamps, bin_index * delta, amplitude=amplitude) + 3.0
            estimate = _periodogram(trace, stamps, detrending=Detrending.NONE)
            reference = calibration.reference_spectrum(
                stamps, trace, taper=calibration.hann(count)
            )
            density = np.asarray(reference["density"], dtype=float)
            assert estimate.frequency_hz.size == density.size
            assert np.allclose(estimate.frequency_hz, reference["frequency_hz"], atol=1e-12)
            assert np.allclose(estimate.psd, density, rtol=1e-9, atol=1e-12), (
                f"the public estimator and the calibration reference must agree at N={count}, "
                f"the {name} tone"
            )


def test_on_an_exact_uniform_axis_the_transform_is_the_one_sided_rfft() -> None:
    """The production transform, reproduced independently from ``np.fft.rfft``.

    The estimator is the admitted uniform-grid periodogram, so on an axis where the adopted grid is
    the actual one its density is exactly what a hand-written one-sided `rfft` of the tapered trace
    produces under the reviewed normalization. This test rebuilds that density from `np.fft.rfft`
    and `np.fft.rfftfreq` without touching the module's own helpers, so the transform, the bin
    positions and the folding (DC once, interior bins twice, and for even ``N`` a Nyquist bin that
    is the transform's own endpoint and so is not doubled) are each checked against arithmetic
    written here.
    """
    for count in (N_EVEN, N_ODD):
        stamps, rate, delta = _uniform(count)
        trace = _tone(stamps, K_FIRST * delta) + 0.3 * _tone(stamps, K_SECOND * delta)
        estimate = _periodogram(trace, stamps, detrending=Detrending.NONE)

        weights = periodic_hann(count)
        tapered = weights * np.asarray(trace, dtype=float)
        density = np.abs(np.fft.rfft(tapered)) ** 2 / (rate * float(np.sum(weights**2)))
        density[1:] *= 2.0
        if count % 2 == 0:
            density[-1] *= 0.5

        assert estimate.frequency_hz.size == density.size == count // 2 + 1
        assert np.allclose(
            estimate.frequency_hz, np.fft.rfftfreq(count, d=1.0 / rate), rtol=0.0, atol=1e-12
        )
        assert np.allclose(estimate.psd, density, rtol=1e-9, atol=1e-12), (
            f"on an exact uniform axis the estimator must be the one-sided rFFT at N={count}"
        )


# --------------------------------------------------------------------------------------
# refusals, and the linkage that makes a spectrum require an admission
# --------------------------------------------------------------------------------------


def test_a_refused_axis_returns_a_refusal_carrying_the_failed_condition() -> None:
    stamps, _rate, delta = _uniform(N_EVEN)
    stamps = stamps.copy()
    stamps[10] = stamps[11]  # one duplicated stamp: the admission refuses the axis
    estimate = _periodogram(_tone(stamps, K_FIRST * delta), stamps)

    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    assert estimate.admission.admitted is False
    assert estimate.psd.size == 0 and estimate.frequency_hz.size == 0
    for name in ("enbw_bins", "enbw_hz", "integrated_psd_power", "trace_mean_mm_s"):
        assert getattr(estimate, name) is None, (
            f"{name} must be None on a refusal: no computation produced it"
        )
    failed = [
        item.condition.value for item in estimate.admission.conditions if item.satisfied is False
    ]
    assert failed, "a refusal names the conditions it failed"
    assert "duplicate" in " ".join(failed)
    assert any(item.threshold is not None for item in estimate.admission.conditions if not item.satisfied), (
        "a failed condition states the threshold it was measured against"
    )
    assert estimate.normalization_rule and estimate.one_sided_rule, (
        "the definitions travel with the refusal too, so the refusal is readable"
    )


def test_a_spectrum_cannot_be_built_on_an_axis_its_admission_refused() -> None:
    stamps, _rate, _delta = _uniform(N_EVEN)
    stamps = stamps.copy()
    stamps[5] = stamps[6]
    estimate = _periodogram(np.zeros(N_EVEN), stamps)
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS

    payload = estimate.model_dump()
    payload["verdict"] = SpectralVerdict.DEFINED
    payload["psd"] = np.zeros(3)
    payload["frequency_hz"] = np.zeros(3)
    with pytest.raises(ValidationError, match="cannot exist on an axis the carried admission"):
        SpectralEstimate(**payload)

    # and the refusal itself may not publish a scalar no computation produced
    payload = estimate.model_dump()
    payload["integrated_psd_power"] = 0.0
    with pytest.raises(ValidationError, match="must not be published as a measurement"):
        SpectralEstimate(**payload)


def test_a_depth_outside_the_common_support_is_an_error_and_not_a_refusal() -> None:
    stamps = _stamps(N_EVEN)
    window = _window(
        _tone(stamps, 1.0), stamps, gates=3, support_mask=np.array([True, True, False])
    )
    outside = float(window.depths_mm[2])
    with pytest.raises(SpectralPeriodogramError, match="common physical support"):
        periodogram_of_view(window, depth_mm=outside)
    with pytest.raises(SpectralPeriodogramError, match="unknown detrending"):
        periodogram_of_view(window, depth_mm=float(window.depths_mm[0]), detrending="cubic")
    with pytest.raises(Exception, match="native gate"):
        periodogram_of_view(window, depth_mm=999.0)


def test_the_estimator_has_no_target_parameter_at_all() -> None:
    """Target support decides nothing here - it cannot, because it is not an argument."""
    parameters = set(inspect.signature(periodogram_of_view).parameters)
    assert parameters == {"view", "depth_mm", "quantity", "unit", "detrending"}
    for absent in ("frequency_hz", "target_hz", "target", "probe"):
        assert absent not in parameters


# --------------------------------------------------------------------------------------
# committed data: a smoke test, and deliberately nothing more
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def committed() -> dict[str, tuple[WindowView, WindowView]]:
    """One committed recording per acquisition job, in both views, decoded from the first pass."""
    ref = next(item for item in COMMITTED_PASSES if item.is_reproducibility_sitting)
    decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
    chosen: dict[str, tuple[WindowView, WindowView]] = {}
    for point in decoding.points:
        views = (
            primary_view(point, window_s=decoding.window_s, support_mm=decoding.support_mm),
            full_record_view(point, support_mm=decoding.support_mm),
        )
        job = view_provenance(views[0]).job
        if job not in chosen:
            chosen[job] = views
    return chosen


def _supported_depth(view: WindowView) -> float:
    """The middle gate of a view's supported columns."""
    columns = view.supported_columns
    return float(np.asarray(view.depths_mm, dtype=float)[columns[len(columns) // 2]])


def test_every_committed_view_this_stage_admits_produces_a_finite_density(
    committed: dict[str, tuple[WindowView, WindowView]],
) -> None:
    assert len(committed) >= 3, f"expected several jobs in one sitting, got {sorted(committed)}"
    worst = 0.0
    for job, views in sorted(committed.items()):
        for view in views:
            estimate = periodogram_of_view(view, depth_mm=_supported_depth(view))
            assert estimate.verdict is SpectralVerdict.DEFINED, (job, view.view)
            assert np.all(np.isfinite(estimate.psd))
            assert estimate.psd.size == estimate.profiles // 2 + 1
            assert estimate.integrated_psd_power >= 0.0
            assert estimate.relative_path and estimate.provenance.source_sha256
            # The Parseval identity is an implementation invariant now, and the committed axes are
            # irregular: the fold still closes at floating-point accuracy, because the transform is
            # the orthogonal DFT of the admitted uniform sequence and not an evaluation at the
            # stored times.
            error = estimate.parseval_relative_error
            assert error is not None and math.isfinite(error)
            assert abs(error) <= PARSEVAL_REL_TOL, (job, view.view, error)
            worst = max(worst, abs(error))
    assert worst < 1e-12, (
        f"the worst Parseval residual over these committed views is {worst}: the identity is an "
        "invariant of the fold, and it must hold on real irregular stamps too"
    )


def test_the_uniform_grid_approximation_on_committed_views_is_visible_and_small(
    committed: dict[str, tuple[WindowView, WindowView]],
) -> None:
    """The uniform-grid estimate against the stored-timestamp evaluation, on committed axes.

    Production (the admitted uniform-grid rFFT) against the stored-timestamp nonuniform
    evaluation, on the same trace over the same axis: how much does taking the approximation
    actually cost? It is *recorded* here and reported in the PR; it is deliberately not an
    admission threshold, because the approximation's admission question was settled in SA2.1 by
    ``max_relative_timing_error <= SPECTRAL_UNIFORMITY_TOL`` and is not re-litigated here.
    """
    seen: dict[str, dict[str, float]] = {}
    for job, views in sorted(committed.items()):
        for view in views:
            depth = _supported_depth(view)
            estimate = periodogram_of_view(view, depth_mm=depth)
            assert estimate.verdict is SpectralVerdict.DEFINED, (job, view.view)
            assert estimate.taper_name == TAPER_NAME, (
                "the reference below must use the same taper, or the comparison is between two "
                "differences at once"
            )
            column = view.column_of_depth(depth)
            stamps = np.asarray(view.time_s, dtype=float)
            trace = np.asarray(view.values, dtype=float)[:, column]
            # the reference takes the analysed series, which for the default detrending is the
            # mean-removed trace: the detrending is deliberately fitted against the stored stamps
            analysed = trace - float(np.mean(trace))
            reference = calibration.reference_spectrum(
                stamps, analysed, taper=calibration.hann(estimate.profiles)
            )
            difference = _spectral_difference(
                estimate.psd,
                np.asarray(reference["density"], dtype=float),
                delta_f=float(estimate.delta_f_hz),
            )
            timing = estimate.admission.characterization.max_relative_timing_error
            assert timing is not None
            key = f"{job}/{view.view.value}"
            seen[key] = {**difference, "timing": abs(timing), "profiles": float(estimate.profiles)}
            # A residual that is exactly zero everywhere would mean the two estimators had been
            # conflated; a large one would mean the approximation is not the small perturbation
            # SA2.1 calibrated for. The bound is an order, recorded rather than tuned.
            assert difference["integrated"] <= 5e-3, (key, difference)
            assert difference["l2"] <= 0.5, (key, difference)
    assert len(seen) >= 4, f"expected at least one view per job, got {sorted(seen)}"
    assert max(item["integrated"] for item in seen.values()) > 0.0, (
        "the committed stamps are irregular, so the two estimators cannot coincide exactly"
    )
    # the diagnostics travel with the test run for the report
    for key in sorted(seen):
        item = seen[key]
        print(
            f"{key:42s} N={item['profiles']:5.0f} timing={item['timing']:.3e} "
            f"integrated={item['integrated']:.3e} worst_bin={item['worst_bin']:.3e} "
            f"l1={item['l1']:.3e} l2={item['l2']:.3e}"
        )


def test_an_emissions_128_view_produces_a_spectrum_and_still_cannot_carry_rotor_rate(
    committed: dict[str, tuple[WindowView, WindowView]],
) -> None:
    """The separation this stage exists to keep, on real data: admitted, and band-refused.

    Asking the periodogram about the rotor frequency must change nothing at all - the two
    questions are asked in different places, of different objects, and the second one is not an
    argument of the first.
    """
    view = committed["emissions-128"][0]
    depth = _supported_depth(view)
    estimate = periodogram_of_view(view, depth_mm=depth)
    assert estimate.verdict is SpectralVerdict.DEFINED
    assert estimate.nyquist_hz is not None and estimate.nyquist_hz < ROTOR_HZ, (
        "an emissions-128 axis is admitted for the estimator while its band ends below 8.333 Hz"
    )
    support = target_frequency_support(estimate.admission, ROTOR_HZ, label="rotor")
    assert support.supported is False
    assert support.band_supported is False
    assert "nyquist" in support.reason.lower()

    # and the periodogram is unchanged by that question having been asked
    again = periodogram_of_view(view, depth_mm=depth)
    assert np.array_equal(estimate.psd, again.psd)
    assert estimate.verdict is again.verdict

    # in the low band it has no such problem: a supported target below Nyquist is supported
    low = target_frequency_support(estimate.admission, 1.0, label="recurrence-scale")
    assert low.supported is True
    assert float(np.max(estimate.psd[: max(2, int(2.0 / estimate.delta_f_hz))])) >= 0.0
    assert math.isfinite(float(estimate.integrated_psd_power))
