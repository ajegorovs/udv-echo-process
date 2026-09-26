"""SA2.2 - one view's periodogram, on the adopted uniform grid, with its admission on it.

The estimator is the *assumed-uniform-grid* periodogram: the samples are taken at their stored
stamps, but the transform assumes they sit on the uniform grid SA2.1 characterizes (``fs_eff =
(N - 1) / span``, bin spacing ``delta_f = fs_eff / N``). That assumption is not free, so this
module computes nothing until :class:`~udv_echo_process.analysis.sparse_spectral_admission
.SpectralAdmission` has admitted the axis, and the admission travels *inside* the result: a
spectrum cannot exist here without the evidence that one was allowed.

**A refused axis is a result, not an exception.** An irregular axis returns a
:class:`SpectralEstimate` whose verdict is :data:`SpectralVerdict.REFUSED_AXIS`, whose arrays are
empty and whose admission carries the failed conditions and their thresholds by name. Nothing is
computed anyway and no empty density is silently published as a spectrum.

**The taper is stated, not remembered.** :data:`TAPER_NAME` and :data:`TAPER_CONVENTION` pin the
periodic Hann (``w[n] = 0.5 - 0.5 cos(2 pi n / N)``, endpoint not repeated), and the ENBW the
result carries is derived from *those* coefficients by :func:`taper_enbw_bins` rather than from a
remembered "1.5 bins" - the symmetric convention gives ``1.5 * N / (N - 1)`` instead, 0.73 percent
apart at the smallest committed sample count.

**The density normalization is the reviewed one** (:data:`NORMALIZATION_RULE`): ``Pxx[k] =
|sum_n w[n] x[n] exp(-2j pi f_k t_n)|^2 / (fs_eff * sum_n w[n]^2)``, in ``(unit)^2 / Hz``, with the
one-sided folding of :data:`ONE_SIDED_RULE`. The folding is checked by an identity the result
validates on construction: ``sum_k Pxx[k] * delta_f`` equals ``sum_n (w[n] x[n])^2 / sum_n w[n]^2``
exactly, for both parities - which is why DC is never doubled and why the top bin is doubled for
odd ``N`` and not for even ``N``.

**The frequency grid is not re-derived here.** It comes from
:func:`~udv_echo_process.analysis.sparse_spectral_support.one_sided_frequency_grid`, the single
definition of bin positions in this repository, so the estimator cannot land on a grid the
target-support question was not asked of.

Narrow by intent: no Welch averaging, no resampling, no irregular-sampling estimator, no peak
search or condition comparison, no notebook figure, and no serialization.
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._sparse_view import (
    ViewProvenance,
    WindowView,
    view_provenance,
)
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_admission import (
    SpectralAdmission,
    spectral_admission,
)
from udv_echo_process.analysis.sparse_spectral_support import (
    TimebaseCharacterization,
    characterize_stamps,
    one_sided_frequency_grid,
)
from udv_echo_process.models.base import ArrayModel, array_field


class SpectralPeriodogramError(ValueError):
    """A periodogram was asked for in terms that cannot produce one.

    Raised for a depth that is not one of the view's native gates, a depth outside the pass's
    common support, an unknown detrending, or arrays that are not one series of one length. A
    *refused axis* is not this: that is a verdict on a well-posed request.
    """


class SpectralVerdict(str, Enum):
    """Whether a spectrum is defined for the axis asked about, and if not, why.

    ``DEFINED`` is the only verdict that carries a density. ``REFUSED_AXIS`` is the admission
    policy declining the axis: the result then carries the admission, whose condition verdicts
    name what failed and against which threshold. The refusal is never an exception and never an
    all-zero density - a zero spectrum is a measurement, and a refused axis was not measured.
    """

    DEFINED = "defined"
    REFUSED_AXIS = "refused-irregular-axis"


#: The taper, by name and by its exact coefficients' convention. The periodic Hann is the
#: spectral-estimation choice (the endpoint is not repeated), and it is *stated here* rather than
#: inferred, because the ENBW a reader applies depends on which convention produced the weights.
TAPER_NAME = "hann"

#: The convention of :data:`TAPER_NAME`, in the form the coefficients can be rebuilt from.
TAPER_CONVENTION = (
    "periodic: w[n] = 0.5 - 0.5 * cos(2 * pi * n / N) for n = 0 .. N - 1, the endpoint not "
    "repeated; the symmetric convention w[n] = 0.5 - 0.5 * cos(2 * pi * n / (N - 1)) instead "
    "has ENBW 1.5 * N / (N - 1) bins, which is why the value is measured from these "
    "coefficients rather than quoted as 1.5"
)

#: What the estimate is, for a reader who has only the result.
ESTIMATOR_NAME = (
    "single-view periodogram on the adopted uniform grid: real one-sided transform of the "
    "tapered, detrended trace, evaluated at the SA2.1 grid's own bin frequencies t_k = k * "
    "fs_eff / N"
)

#: The density normalization, as arithmetic rather than as a name.
NORMALIZATION_RULE = (
    "Pxx[k] = |sum_n w[n] * x[n] * exp(-2j * pi * f_k * t_n)|^2 / (fs_eff * sum_n w[n]^2) with "
    "f_k = k * fs_eff / N: a power spectral *density* in (unit)^2 / Hz, so a bin's power is "
    "Pxx[k] * delta_f and the integral over the one-sided grid is the window-normalized mean "
    "square of the analysed trace"
)

#: The one-sided folding, including both endpoint rules and both parities.
ONE_SIDED_RULE = (
    "one-sided with DC never doubled and every interior bin doubled; for even N the last bin "
    "sits exactly at Nyquist (fs_eff / 2) and is therefore not doubled; for odd N the last bin "
    "sits delta_f / 2 below Nyquist, is not Nyquist, and follows the interior rule - it is "
    "doubled, because the one-sided grid of an odd-length transform folds the upper half onto it"
)

#: The identity the result checks on construction, stated where a reader will see it - with the
#: scope it actually has. ``sum_k Pxx[k] * delta_f`` equals the window-normalized mean square of
#: the analysed trace **exactly when the transform's frequencies are an orthogonal set for the
#: stored stamps**, which is the case on an exactly uniform axis: the one-sided fold (DC once, the
#: interior bins twice, the top bin halved for even ``N``) then reproduces the full spectrum's
#: power. On an irregular axis the transform is not orthogonal - that is precisely the assumption
#: the admission tests - so the two powers differ, by a residual this result **carries** rather
#: than hides. Measured: below 1e-14 on an exact uniform axis, and up to 2.9e-4 across the
#: committed views (usually ~1e-4), against a folding error which is off by order 1.
ENERGY_IDENTITY_RULE = (
    "sum_k Pxx[k] * delta_f == sum_n (w[n] * x[n])^2 / sum_n w[n]^2, exact under the folding of "
    "ONE_SIDED_RULE when the grid's frequencies are orthogonal for the stored stamps (an exactly "
    "uniform axis); on an irregular axis the two differ by the grid assumption itself, and the "
    "relative difference is reported as energy_identity_error. It is not the raw variance of the "
    "trace, because the taper's own weighting is part of what the density describes"
)

#: The bound the identity is checked to. It is deliberately *not* a machine-epsilon bound: a
#: folding rule that is wrong by one endpoint bin is off by order 1, while the adopted grid's own
#: residual on irregular stamps is ~1e-5, so a bound here separates the defect from the
#: assumption. The measured error is carried on every result, so nothing is hidden behind it.
ENERGY_IDENTITY_TOL = 1e-3


def periodic_hann(count: int) -> np.ndarray:
    """The periodic Hann taper of ``count`` samples: ``w[n] = 0.5 - 0.5 cos(2 pi n / N)``.

    Raises:
        SpectralPeriodogramError: for fewer than two samples, where the taper is degenerate
            (``w[0] = 0`` alone, with nothing to describe a spectrum of).
    """
    if count < 2:
        raise SpectralPeriodogramError(
            f"a taper needs at least two samples to mean anything, got {count}"
        )
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(count, dtype=float) / float(count))


def taper_enbw_bins(weights: object) -> float:
    """The equivalent noise bandwidth of a taper, in bins, from its own coefficients.

    ``ENBW_bins = N * sum(w^2) / (sum(w))^2``. Computed rather than quoted: it is the number a
    reader divides a density by, and a hard-coded 1.5 is only right for one convention.
    """
    coefficients = np.asarray(weights, dtype=float)
    if coefficients.ndim != 1 or coefficients.size < 2:
        raise SpectralPeriodogramError(
            f"a taper is a one-dimensional series of coefficients, got shape {coefficients.shape}"
        )
    if not np.all(np.isfinite(coefficients)):
        raise SpectralPeriodogramError("a taper must be finite everywhere to have a bandwidth")
    total = float(np.sum(coefficients))
    if total == 0.0:
        raise SpectralPeriodogramError(
            "a taper whose coefficients sum to zero has no equivalent noise bandwidth"
        )
    return float(coefficients.size) * float(np.sum(coefficients**2)) / (total**2)


def _detrended(
    trace: np.ndarray, time_s: np.ndarray, detrending: Detrending
) -> tuple[np.ndarray, float | None]:
    """The analysed series, and the fitted slope when a line was removed.

    SA2 reuses :data:`Detrending` exactly as SA1 defined it, including the order: the line is
    fitted to the mean-removed trace, so the analysed series keeps a zero mean and the reported
    slope is the trend that was taken out rather than an intercept artefact.
    """
    if detrending is Detrending.NONE:
        return trace.copy(), None
    centered = trace - float(np.mean(trace))
    if detrending is Detrending.MEAN:
        return centered, None
    slope = float(np.polyfit(time_s, centered, 1)[0])
    return centered - slope * (time_s - float(np.mean(time_s))), slope


def _detrending_of(value: Detrending | str) -> Detrending:
    """SA1's detrending vocabulary, coerced with this module's own error type.

    Raises:
        SpectralPeriodogramError: for a name outside :class:`Detrending`.
    """
    if isinstance(value, Detrending):
        return value
    try:
        return Detrending(value)
    except ValueError as error:
        names = [item.value for item in Detrending]
        raise SpectralPeriodogramError(
            f"unknown detrending {value!r}: SA1's vocabulary is {names}, and SA2 adds none"
        ) from error


class SpectralEstimate(ArrayModel):
    """One gate's periodogram, its admission, and the definitions it was computed under.

    The axis quantities a reader needs (``profiles``, ``span_s``, ``dt_eff_s``,
    ``effective_sample_rate_hz``, ``nyquist_hz``, ``delta_f_hz``) are **properties of the carried
    characterization**, not a second copy that can drift from it: the same view produced the
    admission and the spectrum, and the grid came from
    :func:`~udv_echo_process.analysis.sparse_spectral_support.one_sided_frequency_grid` rather
    than from a spacing re-derived here.

    ``frequency_hz`` and ``psd`` are empty together, exactly when the verdict is not
    :data:`SpectralVerdict.DEFINED`. Scalars that a refused axis does not define are ``None``,
    never ``0.0``: a zero density reads as a measured zero.
    """

    # where this spectrum is: the view it was cut from, and which gate of that view
    provenance: ViewProvenance
    gate_index: int
    depth_mm: float
    quantity: str
    unit: str
    psd_unit: str

    # what allowed it, and what it is
    admission: SpectralAdmission
    verdict: SpectralVerdict
    message: str

    # what was done to the trace, and with which taper and rules
    detrending: Detrending
    linear_trend_per_s: float | None
    trace_mean_mm_s: float | None
    taper_name: str
    taper_convention: str
    enbw_bins: float | None
    enbw_hz: float | None
    estimator_name: str
    normalization_rule: str
    one_sided_rule: str
    energy_identity_rule: str

    # the spectrum itself, and the two powers the identity relates
    frequency_hz: array_field(np.float64, rank=1)
    psd: array_field(np.float64, rank=1)
    window_normalized_mean_square_power: float | None
    integrated_psd_power: float | None
    #: The relative difference between the two powers above. Exactness is a property of an
    #: orthogonal grid and this estimator's grid is the *assumed* one, so on an irregular axis the
    #: difference is a measurement of the assumption rather than an error to hide.
    energy_identity_error: float | None

    @property
    def view(self) -> str:
        """The view label this spectrum was cut from, from its one provenance."""
        return self.provenance.view

    @property
    def relative_path(self) -> str:
        """The source recording, from its one provenance."""
        return self.provenance.relative_path

    @property
    def label(self) -> str:
        """The recording's identity string, from its one provenance."""
        return self.provenance.point_label

    @property
    def characterization(self) -> TimebaseCharacterization:
        """The axis this spectrum was computed on - the admission's own, not a copy."""
        return self.admission.characterization

    @property
    def profiles(self) -> int:
        """``N``, the number of stored profiles the transform ran over."""
        return self.characterization.profiles

    @property
    def span_s(self) -> float | None:
        """The span of the view's own stamps."""
        return self.characterization.span_s

    @property
    def dt_eff_s(self) -> float | None:
        """The adopted effective interval, ``span / (N - 1)``."""
        return self.characterization.full_span_interval_s

    @property
    def effective_sample_rate_hz(self) -> float | None:
        """The adopted rate the transform assumed, ``(N - 1) / span``."""
        return self.characterization.effective_sample_rate_hz

    @property
    def nyquist_hz(self) -> float | None:
        """Mathematical Nyquist of the adopted rate, ``fs_eff / 2``."""
        return self.characterization.nyquist_hz

    @property
    def delta_f_hz(self) -> float | None:
        """The bin spacing of the grid, ``fs_eff / N`` - not ``1 / span``."""
        return self.characterization.frequency_resolution_hz

    @property
    def nyquist_is_represented(self) -> bool:
        """Whether a bin sits exactly at Nyquist: true for even ``N``, false for odd ``N``."""
        return self.profiles % 2 == 0

    @model_validator(mode="after")
    def _spectrum_matches_the_verdict(self) -> SpectralEstimate:
        """Hold the invariants of a defined spectrum, and those of a refusal.

        The central one is the linkage the review asked for: a spectrum exists exactly when the
        carried admission admits the axis. The energy identity is checked here too, because a
        one-sided folding rule that is wrong by one endpoint bin still *looks* like a spectrum.
        """
        admitted = self.admission.admitted
        if self.verdict is SpectralVerdict.DEFINED:
            if not admitted:
                raise ValueError(
                    "a spectrum cannot exist on an axis the carried admission refused: the "
                    "estimator is the assumed-uniform-grid one and its assumption is the thing "
                    "the admission tested"
                )
            if self.psd.size != self.frequency_hz.size or self.psd.size < 1:
                raise ValueError(
                    "a defined spectrum carries one density per grid frequency, got "
                    f"{self.psd.size} and {self.frequency_hz.size}"
                )
            if not np.all(np.isfinite(self.psd)) or not np.all(np.isfinite(self.frequency_hz)):
                raise ValueError("a defined spectrum holds only finite values")
            if self.enbw_bins is None or self.enbw_hz is None:
                raise ValueError("a defined spectrum states the taper's ENBW in bins and in Hz")
            delta = self.delta_f_hz
            if delta is None or not math.isfinite(delta) or delta <= 0.0:
                raise ValueError(f"a defined spectrum needs a positive bin spacing, got {delta!r}")
            if abs(self.enbw_hz - self.enbw_bins * delta) > 1e-9 * max(self.enbw_hz, delta):
                raise ValueError(
                    f"ENBW {self.enbw_hz!r} Hz is not {self.enbw_bins!r} bins at {delta!r} Hz"
                )
            integrated = self.integrated_psd_power
            windowed = self.window_normalized_mean_square_power
            if integrated is None or windowed is None:
                raise ValueError(
                    "a defined spectrum carries both powers the energy identity relates"
                )
            error = self.energy_identity_error
            if error is None or not math.isfinite(error):
                raise ValueError(
                    "a defined spectrum reports the relative difference between its integrated "
                    "density and its window-normalized power, exact or not"
                )
            if abs(error) > ENERGY_IDENTITY_TOL:
                raise ValueError(
                    "the one-sided folding does not close the energy identity: "
                    f"sum(Pxx) * delta_f = {integrated!r} against the window-normalized power "
                    f"{windowed!r} (relative difference {error!r}, bound "
                    f"{ENERGY_IDENTITY_TOL!r}); a folding rule that is wrong by one endpoint bin "
                    "still looks like a spectrum"
                )
            return self

        if self.verdict is SpectralVerdict.REFUSED_AXIS:
            if admitted:
                raise ValueError(
                    "a refusal whose carried admission admits the axis contradicts itself"
                )
            if self.psd.size != 0 or self.frequency_hz.size != 0:
                raise ValueError(
                    "a refused axis carries no density and no frequency axis: a zero spectrum "
                    "is a measurement, and this axis was not measured"
                )
            for name in (
                "enbw_bins",
                "enbw_hz",
                "window_normalized_mean_square_power",
                "integrated_psd_power",
                "energy_identity_error",
                "linear_trend_per_s",
                "trace_mean_mm_s",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"a refused axis reports {name} as {getattr(self, name)!r}: a value no "
                        "computation produced must not be published as a measurement"
                    )
            return self

        raise ValueError(f"unknown spectral verdict {self.verdict!r}")


def periodogram_of_view(
    view: WindowView,
    *,
    depth_mm: float,
    quantity: str = "axial_velocity",
    unit: str = "mm/s",
    detrending: Detrending | str = Detrending.MEAN,
) -> SpectralEstimate:
    """One view's periodogram at one native gate depth, admitted first.

    This is the module's single public entry point, for the reason SA1's recurrence has one: the
    trace, its stamps and the identity they are reported under are the *view's own*, so a
    spectrum cannot be computed from samples of one window under the label of another. Selecting
    and cutting the samples is
    :mod:`udv_echo_process.analysis._sparse_view`'s job; characterizing them is
    :func:`~udv_echo_process.analysis.sparse_spectral_support.characterize_timebase`'s; admitting
    them is :func:`~udv_echo_process.analysis.sparse_spectral_admission.spectral_admission`'s.
    This module adds the transform, its taper, and the normalization that makes the result a
    density.

    The pipeline, in order: characterize the view's stamps, ask the admission policy, and only
    then compute. A refused axis is returned as a refusal
    (:data:`SpectralVerdict.REFUSED_AXIS`) carrying that admission; no uniform-grid density is
    computed for it, and none is returned.

    The target question is deliberately absent: whether a frequency of interest is *supported*
    is :func:`~udv_echo_process.analysis.sparse_target_support.target_frequency_support`'s
    answer, asked of the admission, and it neither is nor may become a condition on this
    function.

    Args:
        view: the view to cut the trace out of.
        depth_mm: the native gate depth to analyse, inside the view's common support.
        quantity: the measured quantity; ``axial_velocity`` for this sparse pass.
        unit: the velocity unit; ``mm/s`` for this sparse pass.
        detrending: SA1's vocabulary - ``mean`` (default), ``mean+linear`` or ``none``.

    Returns:
        :class:`SpectralEstimate` - the density and its definitions when the axis is admitted,
        or an explicit refusal carrying the admission otherwise. Either way the timebase, the
        taper and the normalization travel with the result.

    Raises:
        SparseViewError: for a depth that is not one of the view's native gates.
        SpectralPeriodogramError: for a depth outside the view's common support, an unknown
            detrending, or a quantity or unit that is not named.
        SpectralSupportError: for stamps the characterization cannot be built from.
    """
    column = view.column_of_depth(depth_mm)
    depths = np.asarray(view.depths_mm, dtype=float)
    if not bool(np.asarray(view.support_mask)[column]):
        raise SpectralPeriodogramError(
            f"the gate at {depths[column]!r} mm is one of this view's native gates but lies "
            "outside the pass's common physical support, so its trace is not one that a "
            "spectrum may be read from"
        )
    return _periodogram_of_trace(
        np.asarray(view.values, dtype=float)[:, column],
        time_s=np.asarray(view.time_s, dtype=float),
        provenance=view_provenance(view),
        gate_index=column,
        depth_mm=float(depths[column]),
        quantity=quantity,
        unit=unit,
        detrending=_detrending_of(detrending),
    )


def _periodogram_of_trace(
    trace: object,
    *,
    time_s: object,
    provenance: ViewProvenance,
    gate_index: int,
    depth_mm: float,
    quantity: str,
    unit: str,
    detrending: Detrending,
) -> SpectralEstimate:
    """The estimator behind :func:`periodogram_of_view`: one trace, one named provenance.

    Private for the reason SA1's counterpart is: this body will compute a spectrum for any two
    arrays of one length, and only :func:`periodogram_of_view` can supply the provenance that
    keeps that honest. The synthetic tests drive it directly, with a provenance built from a
    synthetic view, so the estimator is exercised on signals whose answer is known in closed
    form without a recording having to exist.
    """
    if not provenance.point_label.strip() or not provenance.source_sha256.strip():
        raise SpectralPeriodogramError(
            "a spectrum must name its source: the view provenance carries no point label or no "
            "source digest"
        )
    if not quantity.strip() or not unit.strip():
        raise SpectralPeriodogramError("every spectrum must name the quantity and unit it measured")

    raw = np.asarray(trace, dtype=np.float64)
    stamps = np.asarray(time_s, dtype=np.float64)
    if raw.ndim != 1:
        raise SpectralPeriodogramError(f"trace must be a 1-D series, got shape {raw.shape}")
    if stamps.ndim != 1:
        raise SpectralPeriodogramError(f"time_s must be a 1-D series, got shape {stamps.shape}")
    if raw.shape != stamps.shape:
        raise SpectralPeriodogramError(
            f"trace and time_s must share one length, got {raw.shape[0]} and {stamps.shape[0]}"
        )
    if not np.all(np.isfinite(raw)):
        raise SpectralPeriodogramError(
            "the trace holds a non-finite sample: a missing value is not a zero velocity, and "
            "this estimator does not impute one"
        )

    # 1. characterize the axis, 2. ask the admission policy - both before any transform.
    characterization = characterize_stamps(stamps)
    admission = spectral_admission(characterization)
    if not admission.admitted:
        return _refusal(
            provenance=provenance,
            gate_index=gate_index,
            depth_mm=depth_mm,
            quantity=quantity,
            unit=unit,
            detrending=detrending,
            admission=admission,
        )

    # 3. only now compute. The characterization that admitted the axis is the one used, so the
    #    grid cannot come from a different reading of the same stamps than the verdict did.
    count = int(characterization.profiles)
    rate = float(characterization.effective_sample_rate_hz)  # type: ignore[arg-type]
    delta_f = float(characterization.frequency_resolution_hz)  # type: ignore[arg-type]
    grid = one_sided_frequency_grid(count, rate)
    frequencies = np.asarray(grid["frequencies_hz"], dtype=np.float64)

    weights = periodic_hann(count)
    analysed, slope = _detrended(raw, stamps, detrending)
    tapered = weights * analysed

    # The density of the reviewed normalization, at the grid's own frequencies. The transform is
    # a real one-sided DFT: a matrix-vector product on the grid, which is the rFFT's definition
    # for uniform stamps and the assumed-grid transform for stamps that merely approximate them.
    transform = np.exp(-2j * np.pi * np.outer(frequencies, stamps))
    spectrum = transform @ tapered
    density = np.abs(spectrum) ** 2 / (rate * float(np.sum(weights**2)))
    density[1:] *= 2.0
    if count % 2 == 0:
        density[-1] *= 0.5

    windowed_power = float(np.dot(tapered, tapered) / np.sum(weights**2))
    integrated = float(np.sum(density) * delta_f)
    if windowed_power > 0.0:
        error = (integrated - windowed_power) / windowed_power
    elif integrated == 0.0:
        error = 0.0  # a zero signal integrates to zero: the identity holds trivially
    else:
        error = float("inf")  # power from no signal is impossible, and must not pass as exact
    enbw_bins = taper_enbw_bins(weights)
    mean = float(np.mean(raw))
    return SpectralEstimate(
        provenance=provenance,
        gate_index=int(gate_index),
        depth_mm=float(depth_mm),
        quantity=quantity,
        unit=unit,
        psd_unit=f"({unit})^2/Hz",
        admission=admission,
        verdict=SpectralVerdict.DEFINED,
        message=(
            f"admitted on the assumed uniform grid: {count} profiles over {float(characterization.span_s)!r} s "
            f"at {rate!r} Hz, {frequencies.size} one-sided bins from 0 to {float(frequencies[-1])!r} Hz"
        ),
        detrending=detrending,
        linear_trend_per_s=slope,
        trace_mean_mm_s=mean if math.isfinite(mean) else None,
        taper_name=TAPER_NAME,
        taper_convention=TAPER_CONVENTION,
        enbw_bins=enbw_bins,
        enbw_hz=enbw_bins * delta_f,
        estimator_name=ESTIMATOR_NAME,
        normalization_rule=NORMALIZATION_RULE,
        one_sided_rule=ONE_SIDED_RULE,
        energy_identity_rule=ENERGY_IDENTITY_RULE,
        frequency_hz=frequencies,
        psd=density,
        window_normalized_mean_square_power=windowed_power,
        integrated_psd_power=integrated,
        energy_identity_error=error,
    )


def _refusal(
    *,
    provenance: ViewProvenance,
    gate_index: int,
    depth_mm: float,
    quantity: str,
    unit: str,
    detrending: Detrending,
    admission: SpectralAdmission,
) -> SpectralEstimate:
    """The result of declining an axis: the admission, and no spectrum.

    Every quantity a computation would have produced is ``None`` rather than ``0.0``, and both
    arrays are empty, so nothing in the result can be read as a measurement that was not made.
    """
    return SpectralEstimate(
        provenance=provenance,
        gate_index=int(gate_index),
        depth_mm=float(depth_mm),
        quantity=quantity,
        unit=unit,
        psd_unit=f"({unit})^2/Hz",
        admission=admission,
        verdict=SpectralVerdict.REFUSED_AXIS,
        message=(
            "no spectrum: the admission policy declined this axis under the assumed-uniform-grid "
            f"estimator - {admission.reason}"
        ),
        detrending=detrending,
        linear_trend_per_s=None,
        trace_mean_mm_s=None,
        taper_name=TAPER_NAME,
        taper_convention=TAPER_CONVENTION,
        enbw_bins=None,
        enbw_hz=None,
        estimator_name=ESTIMATOR_NAME,
        normalization_rule=NORMALIZATION_RULE,
        one_sided_rule=ONE_SIDED_RULE,
        energy_identity_rule=ENERGY_IDENTITY_RULE,
        frequency_hz=np.empty(0, dtype=np.float64),
        psd=np.empty(0, dtype=np.float64),
        window_normalized_mean_square_power=None,
        integrated_psd_power=None,
        energy_identity_error=None,
    )
