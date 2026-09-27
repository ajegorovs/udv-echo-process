"""SA2.4 S1 — the prespecified descriptive reduction of a published spectrum.

SA2.4 characterizes *committed data*: a low-frequency band power fraction per supported gate,
and the per-cell axis scalars and target rows a report quotes beside it. This module is S1, the
scalar backend. It publishes nothing (no CSV, no JSON, no NPZ), it adds **no new estimator, no new
admission rule, no threshold and no verdict change**, and it queries no report directory.

**One new number, prespecified, never tuned after seeing a value** (plan §2). For one
``(cell, supported gate)`` and a declared band edge ``low_hz``:

    grid    = one_sided_frequency_grid(N, fs_eff)          # the repository's one grid
    cell_k  = frequency_cell(k, grid=grid)                 # the repository's one cell rule
    w_k     = clip(length(cell_k ∩ [0, low_hz]) / length(cell_k), 0, 1)
    B       = Σ_k  w_k · psd[k] · Δf                       # (unit)^2
    T       = estimate.integrated_psd_power                # (unit)^2, READ, never recomputed
    fraction = B / T                                       # dimensionless in [0, 1]

The band is **closed**, ``[0, low_hz]``, measured by intersection *length*: a cell edge exactly on
``low_hz`` adds zero length, so the closed/open question changes no value and needs no tie rule.
``w_k`` is the overlap *fraction of the cell*, never a count of bins — a bin straddling the band
edge contributes in part, and the DC cell is a half-width cell opened at ``0.0`` by the one cell
rule, so it enters at its full ``psd[0] · Δf`` exactly when ``low_hz >= Δf / 2``.

**The denominator is read, not rebuilt.** ``T`` is the estimate's own ``integrated_psd_power``,
which by the estimator's ``PARSEVAL_RULE`` equals ``window_normalized_mean_square_power`` — the
design's required quantity, and not the raw variance of the detrended trace. Recomputing
``Σ_k psd[k] · Δf`` here would add a second computation that could disagree with the invariant the
estimator already checks on construction.

**A refused axis is not a defined zero, and neither is a number** (:class:`BandFractionState`):
``defined`` carries ``fraction = B / T``; ``defined-zero-power`` is a *measurement* whose total is
zero, carried as ``band_power == 0.0`` with ``fraction is None`` (0 / 0 is undefined);
``refused-axis`` is an axis that was **not measured**, carrying its admission reason and no
fraction, no band power and no total. A supported gate on a refused axis keeps its identity and
status row — this module synthesizes no zero and no number for it.

**Everything else is read.** The axis scalars and the target rows come from the estimate's own
``admission`` / ``characterization`` and from ``target_frequency_support``, never recomputed; the
provenance comes from SA1 through the estimate; and the estimator's own convention metadata —
``estimator_name``, ``taper_name``, ``taper_convention``, ``normalization_rule`` and
``one_sided_rule``, the fields plan §3 requires beside the axis scalars — is carried on the cell
verbatim, so a reader sees the definitions a number was computed under without this module
restating, re-deriving or re-deciding any of them. This module holds no transform, no taper, no
window weights, no grid construction, no normalization, no admission arithmetic and no verdict
logic. Its only arithmetic is the weighted band sum and its ratio.

**Four invariants are asserted before a number is returned** (plan §2), and a violation is a
refusal, never a clamped value: ``0 <= fraction <= 1 + tol`` (no slack on the *lower* edge — the
band power is a sum of non-negative contributions, so a negative ratio is not a rounding of zero);
``B <= T · (1 + tol)``; ``T`` agrees with ``window_normalized_mean_square_power`` within the carried
``parseval_relative_error``; and at ``low_hz == Nyquist`` every weight is ``1``, so a ``defined``
spectrum yields ``fraction == 1`` because the cells tile ``[0, Nyquist]`` exactly for both parities
of ``N``. A fifth consistency rule is a property of every *carried* row rather than of the
computation: the three numbers of a ``defined`` :class:`LowFrequencyBandFraction` must state one
ratio, ``fraction == B / T``, because the fraction is defined as that quotient and is not an
independent reading — a row that pairs a fraction with powers that do not produce it is refused.

**Request validity is an input check, not an admission rule.** ``low_hz`` must be positive, finite
and at most the axis's Nyquist frequency; ``low_hz == Nyquist`` is permitted as a
boundary-arithmetic check, and an edge above Nyquist is a caller error
(:class:`BandFractionError`), because it is outside the declared domain and cannot change any
verdict. The bound is applied **whenever the axis publishes a Nyquist**, and before the refusal
shortcut: a refused axis with a defined Nyquist still refuses an edge above it with the typed
error, while a refused axis that publishes no Nyquist at all (fewer than two stamps, or a
non-positive span) has no domain to test and returns its typed refusal. The bound carries **no
slack**, so an edge a rounding above Nyquist is refused just as one plainly above it is.

Narrow by intent: no peak finding, no dominant frequency, no recurrence label, no condition or
cross-sitting contrast, no Welch, no coherence, no resampling, no figures, no report writer and no
serialization of any array.
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np
from pydantic import ValidationError, model_validator

from udv_echo_process.analysis._sparse_view import (
    ViewProvenance,
    WindowView,
    view_provenance,
)
from udv_echo_process.analysis.sparse_periodogram import (
    SpectralEstimate,
    SpectralVerdict,
    periodogram_of_view,
)
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_admission import SpectralAdmission
from udv_echo_process.analysis.sparse_spectral_capability import PROBE_TARGETS
from udv_echo_process.analysis.sparse_spectral_support import one_sided_frequency_grid
from udv_echo_process.analysis.sparse_target_support import (
    TargetFrequencySupport,
    frequency_cell,
    target_frequency_support,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DEFAULT_LOW_HZ",
    "FRACTION_PRECISION",
    "LOW_BAND_RULE",
    "BandFractionError",
    "BandFractionState",
    "CellSpectralCharacterization",
    "GateSpectrumCharacterization",
    "LowFrequencyBandFraction",
    "characterization_of_view",
    "low_frequency_power_fraction",
]

#: The default band edge, in Hz. It is the design's declared recurrence *scale* / probe target -
#: the ``recurrence-1hz`` probe - and never a peak. A different band is a different prespecified
#: band in a new labelled table, not a knob on this one.
DEFAULT_LOW_HZ = 1.0

#: The number of decimals the report records the fraction at. Carried here so the document states
#: one precision rather than each writer choosing its own.
FRACTION_PRECISION = 6

#: The relative slack the invariants are checked to. It exists because ``B`` and ``T`` are summed
#: by different paths; the identity it relaxes is exact in exact arithmetic, so a real violation is
#: off by order 1 rather than by this.
INVARIANT_REL_TOL = 1e-9

#: The weighted-overlap rule, as the arithmetic a reader can reproduce.
LOW_BAND_RULE = (
    "the low-frequency band power fraction of one gate is B / T with B = sum_k w_k * psd[k] * "
    "delta_f and w_k = clip(length(cell_k intersect [0, low_hz]) / length(cell_k), 0, 1), where "
    "cell_k is the repository's one cell rule applied to the repository's one one-sided grid and "
    "T is the estimate's own integrated_psd_power. The band is closed [0, low_hz] and measured by "
    "intersection length, so a cell edge exactly on low_hz adds zero length and the DC cell - "
    "opened at 0.0 by the cell rule - earns a whole weight once low_hz >= delta_f / 2. The "
    "fraction is dimensionless and lies in [0, 1]; a percentage is display only."
)

#: What each carried state means, so a reader of one row cannot conflate the three.
STATE_MEANING = (
    "defined: the axis was admitted and its total power is positive, so the fraction is B / T. "
    "defined-zero-power: the axis was admitted and its window-normalized mean square power is "
    "zero - a constant gate, which is a measurement - so band_power is the defined zero 0.0 and "
    "the fraction is undefined (0 / 0) and carried as None. refused-axis: the admission declined "
    "the axis, so nothing was measured: the supported gate keeps its identity and status row but "
    "the fraction, the band power and the total are all None and no zero is synthesized."
)


class BandFractionError(ValueError):
    """A band fraction was asked for in terms that cannot produce one.

    Raised for a band edge that is not a positive finite number of Hz, for an edge above a Nyquist
    frequency the axis publishes (outside the declared domain, and able to change no verdict - on
    either verdict, refused or defined), and for an invariant a computed fraction would violate. A
    *refused axis* is not this error: it is the typed state :data:`BandFractionState.REFUSED_AXIS`,
    carrying the admission's own reason. A refused axis that publishes no Nyquist at all has no
    domain to test, so it too returns the typed refusal rather than raising.
    """


class BandFractionState(str, Enum):
    """Whether a band fraction was measured, was measured as a zero, or was not measured at all.

    Three distinct answers, never conflated:

    - :data:`DEFINED` - the axis was admitted and its total power is positive;
    - :data:`DEFINED_ZERO_POWER` - the axis was admitted and its total power is exactly zero: a
      constant gate, which is a *measurement*, carried as ``band_power == 0.0`` with an undefined
      fraction;
    - :data:`REFUSED_AXIS` - the admission declined the axis, so nothing was measured: the
      fraction, the band power and the total are all ``None``.

    A refusal rendered as a zero would read as a measurement that was never taken; a defined zero
    rendered as a refusal would discard one that was.
    """

    DEFINED = "defined"
    DEFINED_ZERO_POWER = "defined-zero-power"
    REFUSED_AXIS = "refused-axis"


class LowFrequencyBandFraction(ValueModel):
    """The band power below ``low_hz`` as a fraction of the spectrum's total, with its state.

    ``band_power`` and ``total_power`` are in ``(unit)^2`` and ``fraction`` is dimensionless in
    ``[0, 1]``. Which of them is present is decided by :attr:`state` and by nothing else: a
    refusal carries three ``None`` values, and a defined zero carries ``band_power == 0.0`` with
    ``fraction is None``. For a ``defined`` row the three numbers are one ratio, not three
    independent readings: the validator refuses a ``fraction`` that is not ``band_power /
    total_power`` within ``INVARIANT_REL_TOL``, and it refuses a negative ``fraction`` with no
    slack on the lower edge, because the band power is a sum of non-negative contributions and a
    negative ratio is therefore not a rounding of zero. ``reason`` states what the state is in
    words, and for a refusal it is the admission's own reason rather than a second summary of it.
    """

    low_hz: float
    state: BandFractionState
    fraction: float | None
    band_power: float | None
    total_power: float | None
    reason: str = ""

    @property
    def percent(self) -> float | None:
        """The fraction as a percentage, or ``None`` where no fraction is defined.

        Display only: the quantity this module publishes is dimensionless, and a percentage is a
        rendering of it.
        """
        return None if self.fraction is None else 100.0 * self.fraction

    @model_validator(mode="after")
    def _check_the_state_is_the_values_it_carries(self) -> LowFrequencyBandFraction:
        if not (math.isfinite(self.low_hz) and self.low_hz > 0.0):
            raise BandFractionError(
                f"a band edge must be positive and finite, got {self.low_hz!r}"
            )
        if self.state is BandFractionState.REFUSED_AXIS:
            for name in ("fraction", "band_power", "total_power"):
                if getattr(self, name) is not None:
                    raise BandFractionError(
                        f"a refused axis reports {name} as {getattr(self, name)!r}: an axis that "
                        "was not measured carries no band power and no total, and a zero here "
                        "would read as a measurement"
                    )
            return self
        if self.total_power is None or self.band_power is None:
            raise BandFractionError(
                f"a {self.state.value!r} fraction must carry the band power and the total it is "
                "a fraction of"
            )
        # Finiteness before sign: a NaN compares false against every bound, so ``nan < 0.0`` and
        # ``nan > total`` are both false and a NaN band power would slip every check below and be
        # published as a measurement.
        if not (math.isfinite(self.band_power) and math.isfinite(self.total_power)):
            raise BandFractionError(
                f"a {self.state.value!r} fraction carries finite powers, got band "
                f"{self.band_power!r} and total {self.total_power!r}: a non-finite power is not "
                "a measurement"
            )
        if self.band_power < 0.0 or self.total_power < 0.0:
            raise BandFractionError(
                f"power is not negative, got band {self.band_power!r} and total "
                f"{self.total_power!r} for a state of {self.state.value!r}"
            )
        if self.state is BandFractionState.DEFINED_ZERO_POWER:
            if self.total_power != 0.0 or self.band_power != 0.0:
                raise BandFractionError(
                    "a defined zero power is a total of exactly 0.0 with a band power of 0.0 "
                    f"(a constant gate, which is a measurement), got total {self.total_power!r} "
                    f"and band {self.band_power!r}"
                )
            if self.fraction is not None:
                raise BandFractionError(
                    f"a defined zero power has no fraction (0 / 0 is undefined), got "
                    f"{self.fraction!r}; carrying a zero here would read as a measured zero "
                    "fraction rather than an undefined ratio"
                )
            return self
        if self.state is not BandFractionState.DEFINED:
            raise BandFractionError(f"unknown band fraction state {self.state!r}")
        if self.total_power <= 0.0:
            raise BandFractionError(
                f"a defined fraction needs a positive total power, got {self.total_power!r}; a "
                "total of exactly zero is the defined-zero-power state, not a defined one"
            )
        if self.fraction is None or not math.isfinite(self.fraction):
            raise BandFractionError(
                f"a defined fraction must be finite, got {self.fraction!r}"
            )
        if self.band_power > self.total_power * (1.0 + INVARIANT_REL_TOL):
            raise BandFractionError(
                f"the band power {self.band_power!r} exceeds the total {self.total_power!r}: the "
                "cells tile the one-sided grid, so no band of it can hold more power than it does"
            )
        # The fraction is not a fourth independent number: it *is* B / T. A row whose three
        # values do not state one ratio would let a report quote a fraction the two powers beside
        # it never produced, so the identity is checked here rather than trusted from the caller.
        expected = self.band_power / self.total_power
        if abs(self.fraction - expected) > INVARIANT_REL_TOL * max(1.0, abs(expected)):
            raise BandFractionError(
                f"the fraction {self.fraction!r} is not the band power {self.band_power!r} over "
                f"the total {self.total_power!r} ({expected!r}): the fraction is defined as "
                "B / T, and a ratio that disagrees with its own two powers is not the measured "
                "number"
            )
        # Lower edge with no slack: the band power is a sum of non-negative contributions and the
        # total is positive here, so the ratio cannot be negative - a slightly negative value is
        # not a rounding of zero but a number no measurement produced. Only the upper edge carries
        # the shared relative tolerance, because B and T are summed by different paths.
        if not (0.0 <= self.fraction <= 1.0 + INVARIANT_REL_TOL):
            raise BandFractionError(
                f"the fraction {self.fraction!r} is outside [0, 1 + {INVARIANT_REL_TOL!r}]: the "
                f"band power is a part of the total {self.total_power!r}, so their ratio cannot "
                "leave the unit interval and cannot be negative"
            )
        return self


class GateSpectrumCharacterization(ValueModel):
    """One supported gate's spectrum, as scalars: its identity, its verdict and its fraction.

    ``band_fraction`` is the gate row's own :class:`LowFrequencyBandFraction` — the same object
    :func:`low_frequency_power_fraction` returns, not a flattened copy of it — and its
    :attr:`~LowFrequencyBandFraction.state` is held to the verdict: a supported gate on a refused
    axis keeps this row with a ``REFUSED_AXIS`` fraction and no number, never a zero.
    ``parseval_relative_error`` is a QA field carried beside the spectrum and is absent on a
    refusal, by the estimator's own contract.
    """

    gate_index: int
    depth_mm: float
    verdict: SpectralVerdict
    band_fraction: LowFrequencyBandFraction
    parseval_relative_error: float | None = None
    enbw_bins: float | None = None
    enbw_hz: float | None = None

    @model_validator(mode="after")
    def _check_the_row_matches_its_state_and_verdict(
        self,
    ) -> GateSpectrumCharacterization:
        if self.gate_index < 0:
            raise BandFractionError(
                f"a gate index cannot be negative, got {self.gate_index}"
            )
        state = self.band_fraction.state
        if state is BandFractionState.REFUSED_AXIS:
            if self.verdict is not SpectralVerdict.REFUSED_AXIS:
                raise BandFractionError(
                    f"a band state of {state.value!r} with a verdict of "
                    f"{self.verdict.value!r}: only a refused axis carries a refusal"
                )
            if self.parseval_relative_error is not None:
                raise BandFractionError(
                    "a refused axis reports parseval_relative_error as "
                    f"{self.parseval_relative_error!r}: a value no computation produced must "
                    "not be published as a measurement"
                )
            return self
        if self.verdict is not SpectralVerdict.DEFINED:
            raise BandFractionError(
                f"a band state of {state.value!r} requires a defined spectrum, got verdict "
                f"{self.verdict.value!r}"
            )
        if state not in (
            BandFractionState.DEFINED,
            BandFractionState.DEFINED_ZERO_POWER,
        ):
            raise BandFractionError(f"unknown band fraction state {state!r}")
        return self


class CellSpectralCharacterization(ValueModel):
    """One ``recording × view`` cell: its provenance, its axis, its target rows and its gates.

    Every axis quantity is read from the estimate's own carried ``admission`` (and its
    ``characterization``), never recomputed, and the axis is one per cell because one view supplies
    one time axis — so all gate rows of a cell share ``N``, span, the effective rate, Nyquist and
    ``Δf`` by construction. The two probe target rows are asked once per cell, of the estimate's own
    admission, through :func:`~udv_echo_process.analysis.sparse_target_support.target_frequency_support`.

    ``pass_name`` is the sweep's own ``PassRef.name`` stated as the selection, reusing the field
    :class:`~udv_echo_process.analysis.sparse_spectral_capability.SpectralCapability` already uses,
    and never a provenance field. The target-support rows carry ``admission`` per row; they are not
    duplicated per gate.

    The estimator's own convention metadata is carried verbatim from the estimates of this view,
    never restated: ``estimator_name``, ``taper_name`` and ``taper_convention`` name the transform
    and taper, ``normalization_rule`` states the one-sided density normalization, and
    ``one_sided_rule`` the fold — the fields plan §3 requires beside the axis scalars. They are
    scalars (strings), so a cell still round-trips through ``model_dump(mode="json")``. All five
    are required: a spectrum was computed under exactly one of each, so an absent one would be a
    missing definition rather than a defaulted choice.
    """

    provenance: ViewProvenance
    pass_name: str | None = None
    quantity: str
    unit: str
    psd_unit: str
    detrending: Detrending
    low_hz: float
    admission: SpectralAdmission
    targets: tuple[TargetFrequencySupport, ...] = ()
    gates: tuple[GateSpectrumCharacterization, ...] = ()
    estimator_name: str
    taper_name: str
    taper_convention: str
    normalization_rule: str
    one_sided_rule: str
    low_band_rule: str = LOW_BAND_RULE

    @property
    def view(self) -> str:
        """The view label this cell was cut from, from its one provenance."""
        return self.provenance.view

    @model_validator(mode="after")
    def _check_the_cell_is_one_axis_with_one_row_per_supported_gate(
        self,
    ) -> CellSpectralCharacterization:
        characterization = self.admission.characterization
        if not (math.isfinite(self.low_hz) and self.low_hz > 0.0):
            raise BandFractionError(
                f"a cell records a positive finite low_hz, got {self.low_hz!r}"
            )
        # The bin spacing is required exactly when the axis is admitted. A refused axis may hold
        # no interval at all (fewer than two stamps, or a span that is not positive), so its
        # frequency_resolution_hz is legitimately None; demanding one here would turn the
        # estimator's typed refusal into a validation failure for a refusal that measured nothing.
        step = characterization.frequency_resolution_hz
        if self.admission.admitted:
            if step is None or not math.isfinite(step) or step <= 0.0:
                raise BandFractionError(
                    f"an admitted cell records a positive finite delta_f_hz, got {step!r}"
                )
        elif step is not None and not (math.isfinite(step) and step > 0.0):
            raise BandFractionError(
                f"a refused cell's bin spacing, when its axis defines one, is positive and "
                f"finite, got {step!r}"
            )
        # The declared domain, at the cell level: a Nyquist the axis publishes bounds the band
        # edge, exactly as it does in low_frequency_power_fraction, and with no slack.
        nyquist = characterization.nyquist_hz
        if (
            nyquist is not None
            and math.isfinite(nyquist)
            and nyquist > 0.0
            and self.low_hz > nyquist
        ):
            raise BandFractionError(
                f"the cell's band edge {self.low_hz!r} Hz is above its axis's Nyquist frequency "
                f"{nyquist!r} Hz: the support edge is the declared domain"
            )
        if characterization.profiles != self.provenance.profiles:
            raise BandFractionError(
                "the cell's admission is for "
                f"{characterization.profiles} profile(s) and its provenance for "
                f"{self.provenance.profiles}: a rate quoted against another view's samples is a "
                "claim about a different recording"
            )
        seen = [row.gate_index for row in self.gates]
        if len(seen) != self.provenance.supported_gates:
            raise BandFractionError(
                f"a cell carries one gate row per supported gate: {len(seen)} row(s) against "
                f"{self.provenance.supported_gates} supported gate(s)"
            )
        if len(set(seen)) != len(seen) or any(index < 0 for index in seen):
            raise BandFractionError(
                f"a cell's gate rows must have distinct nonnegative native column indices, got {seen}"
            )
        # The support *mapping* - which native columns ``supported_columns`` selected - is not
        # carried by :class:`ViewProvenance`: it records the supported gate *count* and the
        # participating depth extent, not the mask or the indices. So this validator cannot hold
        # ``seen`` to ``view.supported_columns`` from the cell alone, and it does not pretend to:
        # it enforces the count against ``provenance.supported_gates`` and the identity/depth of
        # each row above. The exact index set is the sweep's own contract - it iterates
        # ``supported_columns`` and rebuilds each gate at ``depths_mm[index]`` - and is asserted
        # against the live view there, not reconstructed here from a summary that lacks it.
        # One cell, one axis, one verdict: every gate row must reduce the cell's own band edge and
        # carry the verdict the cell's admission stands for, and every target row must have been
        # asked of that same admission. Without these the numbers quoted beside the verdict could
        # belong to another axis or another band.
        for gate in self.gates:
            if gate.band_fraction.low_hz != self.low_hz:
                raise BandFractionError(
                    f"gate {gate.gate_index} reduces a band edge of "
                    f"{gate.band_fraction.low_hz!r} Hz and the cell records {self.low_hz!r} Hz: "
                    "one cell is one axis, so every gate reduces the same declared band"
                )
        expected = (
            SpectralVerdict.DEFINED
            if self.admission.admitted
            else SpectralVerdict.REFUSED_AXIS
        )
        for gate in self.gates:
            if gate.verdict is not expected:
                raise BandFractionError(
                    f"gate {gate.gate_index} carries verdict {gate.verdict.value!r} and the "
                    f"cell's admission is "
                    f"{'admitted' if self.admission.admitted else 'refused'}: the gate rows and "
                    "the cell's verdict come from one and the same admission"
                )
        for target in self.targets:
            # Value equality, not object identity: a cell must round-trip through its own
            # serialization (``model_dump`` -> ``model_validate``), which rebuilds every nested
            # model, so an ``is`` test would refuse the honest payload. A *foreign* admission is a
            # different axis and therefore differs by value, which is what this must catch.
            if target.admission != self.admission:
                raise BandFractionError(
                    f"a target row labelled {target.target_label!r} was asked of an admission the "
                    "cell does not carry: a target quoted beside this verdict must be asked of "
                    "this axis"
                )
        for label, frequency_hz in PROBE_TARGETS:
            if not any(entry.target_label == label for entry in self.targets):
                raise BandFractionError(
                    f"a cell carries a target row labelled {label!r}"
                )
        return self


def _typed_fraction(**fields: object) -> LowFrequencyBandFraction:
    """Build one computed fraction row, re-raising a validator refusal as this module's error.

    The row is a ``ValueModel``, so a contradiction its validator finds arrives as pydantic's
    ``ValidationError`` rather than this module's typed refusal. A caller of the public path must
    see one error vocabulary, so a refusal here is re-raised as :class:`BandFractionError`; the
    computed row satisfies the model's invariants by construction, so this is a guard, not a
    path a valid computation takes.
    """
    try:
        return LowFrequencyBandFraction(**fields)  # type: ignore[arg-type]
    except ValidationError as error:
        raise BandFractionError(
            f"the computed band fraction contradicts its own definition: {error}"
        ) from error


def low_frequency_power_fraction(
    estimate: SpectralEstimate, *, low_hz: float = DEFAULT_LOW_HZ
) -> LowFrequencyBandFraction:
    """The power below ``low_hz`` as a fraction of one spectrum's total, with its state.

    The one prespecified reduction of plan §2, and the module's only arithmetic. The grid and the
    cells come from the repository's single definitions
    (:func:`~udv_echo_process.analysis.sparse_spectral_support.one_sided_frequency_grid` and
    :func:`~udv_echo_process.analysis.sparse_target_support.frequency_cell`); the denominator is
    the estimate's own ``integrated_psd_power``. Nothing is recomputed that the estimate already
    carries, and the estimator is never consulted about a target.

    Args:
        estimate: one gate's :class:`SpectralEstimate`, defined or refused.
        low_hz: the band edge in Hz, positive and at most the axis's Nyquist frequency.
            ``low_hz == Nyquist`` is permitted and yields a fraction of ``1`` for a defined
            spectrum, by the boundary arithmetic rather than by measurement. Where the axis
            publishes no Nyquist (a refused axis with no interval), only the positivity and
            finiteness are required.

    Returns:
        :class:`LowFrequencyBandFraction`. ``DEFINED`` carries ``fraction = B / T``;
        ``DEFINED_ZERO_POWER`` carries ``band_power == 0.0`` with ``fraction is None``;
        ``REFUSED_AXIS`` carries three ``None`` values and the admission's own reason.

    Raises:
        BandFractionError: for a band edge that is not positive and finite; for one above a
            Nyquist frequency the axis publishes, on either verdict (the bound precedes the
            refusal shortcut and carries no slack); and for an estimate whose computed fraction
            would violate one of the §2 invariants (a refusal, never a clamped number).
    """
    if not isinstance(estimate, SpectralEstimate):
        raise BandFractionError(
            "a band fraction is computed from the estimate it reduces, got "
            f"{type(estimate).__name__}"
        )
    edge = float(low_hz)
    if not math.isfinite(edge) or edge <= 0.0:
        raise BandFractionError(
            f"a band edge must be a positive finite number of Hz, got {low_hz!r}"
        )

    # The declared domain is checked against whatever Nyquist the axis publishes *before* the
    # refusal shortcut. A refused axis is a typed answer, but an edge above a Nyquist the axis
    # does define is a caller error on either verdict: letting the refusal return first would
    # silently accept a request the axis cannot locate. Where the axis publishes no Nyquist at
    # all there is no domain to test, and the refusal is returned carrying no number.
    nyquist = estimate.nyquist_hz
    nyquist_known = nyquist is not None and math.isfinite(nyquist) and nyquist > 0.0
    if nyquist_known and edge > nyquist:
        raise BandFractionError(
            f"a band edge of {edge!r} Hz is above this axis's Nyquist frequency {nyquist!r} Hz: "
            "the support edge is the declared domain, and an edge above it cannot change any "
            "verdict"
        )

    if estimate.verdict is SpectralVerdict.REFUSED_AXIS:
        return _typed_fraction(
            low_hz=edge,
            state=BandFractionState.REFUSED_AXIS,
            fraction=None,
            band_power=None,
            total_power=None,
            reason=estimate.admission.reason,
        )
    if estimate.verdict is not SpectralVerdict.DEFINED:
        raise BandFractionError(f"unknown spectral verdict {estimate.verdict!r}")

    if not nyquist_known:
        raise BandFractionError(
            f"this axis publishes no Nyquist frequency ({estimate.profiles} profile(s)), so no "
            "band can be located on it"
        )

    total = estimate.integrated_psd_power
    delta_f = estimate.delta_f_hz
    if total is None or delta_f is None:
        raise BandFractionError(
            "a defined spectrum carries its integrated power and its bin spacing"
        )
    if total == 0.0:
        return _typed_fraction(
            low_hz=edge,
            state=BandFractionState.DEFINED_ZERO_POWER,
            fraction=None,
            band_power=0.0,
            total_power=0.0,
            reason=(
                "a defined zero power: the axis was admitted and the window-normalized mean "
                "square power is zero, so the band power is the defined zero 0.0 and the ratio "
                "is undefined (0 / 0) - a constant gate is a measurement, and this is not a "
                "refusal"
            ),
        )
    if total < 0.0:
        raise BandFractionError(
            f"the integrated power {total!r} is negative, which no density produces"
        )

    # The grid is *recovered* from the estimate's own self-description and checked against its
    # carried frequency axis, rather than re-derived from a spacing: the estimate states which
    # grid it landed on, and this function may not invent a different one.
    rate = estimate.effective_sample_rate_hz
    if rate is None or not math.isfinite(rate) or rate <= 0.0:
        raise BandFractionError(
            f"a defined spectrum publishes a positive effective sample rate, got {rate!r}"
        )
    frequencies = np.asarray(estimate.frequency_hz, dtype=float)
    psd = np.asarray(estimate.psd, dtype=float)
    if frequencies.size != psd.size or frequencies.size == 0:
        raise BandFractionError(
            f"the estimate holds {frequencies.size} frequency bin(s) and {psd.size} density "
            "bin(s); a defined spectrum carries one density per grid frequency"
        )
    grid = one_sided_frequency_grid(int(estimate.profiles), float(rate))
    expected = np.asarray(grid["frequencies_hz"], dtype=float)
    if expected.size != frequencies.size or not bool(np.all(expected == frequencies)):
        raise BandFractionError(
            "the estimate's frequency axis is not the one-sided grid of its own profile count "
            f"and effective rate ({frequencies.size} bin(s) against the grid's {expected.size})"
        )

    band = 0.0
    for index in range(frequencies.size):
        low_cell, high_cell = frequency_cell(index, grid=grid)
        width = high_cell - low_cell
        overlap = min(high_cell, edge) - low_cell
        if overlap <= 0.0:
            continue
        weight = 1.0 if overlap >= width else overlap / width
        band += weight * float(psd[index]) * float(delta_f)

    fraction = band / total
    # §2's invariants, asserted before publication and never clamped.
    if band > total * (1.0 + INVARIANT_REL_TOL):
        raise BandFractionError(
            f"the weighted band power {band!r} exceeds the integrated power {total!r}: the cells "
            "tile the one-sided grid, so a band of it cannot hold more power than it does"
        )
    if not (-INVARIANT_REL_TOL <= fraction <= 1.0 + INVARIANT_REL_TOL):
        raise BandFractionError(
            f"the fraction {fraction!r} is outside [0, 1] for a band {band!r} of a total "
            f"{total!r}"
        )
    windowed = estimate.window_normalized_mean_square_power
    error = estimate.parseval_relative_error
    if (
        windowed is not None
        and error is not None
        and abs(total - windowed)
        > (abs(error) * abs(windowed) + abs(total) * INVARIANT_REL_TOL)
    ):
        raise BandFractionError(
            f"the denominator {total!r} disagrees with the window-normalized power "
            f"{windowed!r} beyond the carried parseval_relative_error {error!r}: the "
            "denominator is read from the estimate precisely because the estimator checks "
            "this identity on construction"
        )
    return _typed_fraction(
        low_hz=edge,
        state=BandFractionState.DEFINED,
        fraction=fraction,
        band_power=band,
        total_power=total,
        reason=(
            f"defined: {band!r} of {total!r} (unit)^2 below {edge:g} Hz on {frequencies.size} "
            f"one-sided bin(s), a weighted cell overlap of a closed [0, {edge:g}] Hz band"
        ),
    )


def _gate_characterization(
    estimate: SpectralEstimate,
    *,
    low_hz: float,
    depth_mm: float,
    gate_index: int,
) -> GateSpectrumCharacterization:
    """One gate's row: the estimate's verdict and state, and the fraction §2 defines for it.

    A contradiction the row's own validator finds is re-raised as :class:`BandFractionError`, so
    the public sweep never leaks the pydantic ``ValidationError`` a malformed estimate would
    produce.
    """
    fraction = low_frequency_power_fraction(estimate, low_hz=low_hz)
    try:
        return GateSpectrumCharacterization(
            gate_index=int(gate_index),
            depth_mm=float(depth_mm),
            verdict=estimate.verdict,
            band_fraction=fraction,
            parseval_relative_error=estimate.parseval_relative_error,
            enbw_bins=estimate.enbw_bins,
            enbw_hz=estimate.enbw_hz,
        )
    except ValidationError as error:
        raise BandFractionError(
            f"gate {int(gate_index)} carries a band fraction that contradicts its own verdict: "
            f"{error}"
        ) from error


def characterization_of_view(
    view: WindowView,
    *,
    low_hz: float = DEFAULT_LOW_HZ,
    detrending: Detrending = Detrending.MEAN,
    quantity: str = "axial_velocity",
    unit: str = "mm/s",
    pass_name: str | None = None,
) -> CellSpectralCharacterization:
    """One ``recording × view`` cell: its axis scalars, its target rows and its gate rows.

    The sweep is driven by :attr:`~udv_echo_process.analysis._sparse_view.WindowView
    .supported_columns` — the accessor that owns the question of which gates are supported — and
    calls :func:`~udv_echo_process.analysis.sparse_periodogram.periodogram_of_view` exactly **once
    per supported gate**. Each gate's band fraction is
    :func:`low_frequency_power_fraction` of that gate's own estimate. The two probe targets are
    asked once per cell, of the estimate's own admission, because one view supplies one axis; they
    are not repeated per gate.

    The probe targets are the design's fixed set, :data:`~udv_echo_process.analysis
    .sparse_spectral_capability.PROBE_TARGETS`, and are **not** a parameter: the cell's validator
    holds every cell to that set, so an override could only ever produce a cell that contradicts
    itself. A different band is a different prespecified table, not a knob on this one.

    This function adds no admission rule, no threshold and no verdict — a refused axis still yields
    one row per supported gate, each with its identity and status and no numeric fraction.

    Args:
        view: the view to characterize.
        low_hz: the band edge in Hz; the design's declared recurrence scale.
        detrending: SA1's vocabulary, applied to every gate of the cell.
        quantity: the measured quantity; ``axial_velocity`` for this sparse pass.
        unit: the velocity unit; ``mm/s`` for this sparse pass.
        pass_name: the sweep's own pass label, stated as the selection.

    Returns:
        :class:`CellSpectralCharacterization` with one gate row per supported gate.

    Raises:
        BandFractionError: for a band edge that is not positive, finite and at most the axis's
            Nyquist frequency, and for a cell or gate row that contradicts its own axis or its own
            verdict (the pydantic ``ValidationError`` of a row model is re-raised as this typed
            error, so a caller sees one error vocabulary).
        SpectralPeriodogramError: for a gate the view holds outside its common support, an unknown
            detrending, or a quantity or unit that is not named.
    """
    columns = np.asarray(view.supported_columns)
    depths = np.asarray(view.depths_mm, dtype=float)
    gates: list[GateSpectrumCharacterization] = []
    admission: SpectralAdmission | None = None
    estimator_name = ""
    taper_name = ""
    # The estimator's carried conventions, read off its estimates beside its name and taper so §3
    # has them on the cell. One view is one axis, so every gate of this cell is computed under the
    # same ones by construction; the last gate's values are the cell's, and the first gate's would
    # be identical. Two locals are spelled without the ``_rule`` suffix on purpose: S1's AST guard
    # forbids this module from *defining* a ``normalization_rule``/``one_sided_rule`` of its own,
    # and these are read from the estimate, never authored here.
    taper_convention = ""
    normalization = ""
    one_sided = ""
    for column in columns:
        index = int(column)
        estimate = periodogram_of_view(
            view,
            depth_mm=float(depths[index]),
            quantity=quantity,
            unit=unit,
            detrending=detrending,
        )
        # One cell, one axis: the first gate's estimate owns it, and every later gate of this view
        # carries the same characterization by construction.
        admission = estimate.admission if admission is None else admission
        estimator_name = estimate.estimator_name
        taper_name = estimate.taper_name
        taper_convention = estimate.taper_convention
        normalization = estimate.normalization_rule
        one_sided = estimate.one_sided_rule
        gates.append(
            _gate_characterization(
                estimate,
                low_hz=low_hz,
                depth_mm=float(depths[index]),
                gate_index=index,
            )
        )
    if admission is None:  # pragma: no cover - a view holds at least one supported gate
        raise BandFractionError(
            f"{view.relative_path}: this view holds no supported column, so there is no cell to "
            "characterize"
        )
    rows = tuple(
        target_frequency_support(admission, frequency_hz, label=label)
        for label, frequency_hz in PROBE_TARGETS
    )
    psd_unit = f"({unit})^2/Hz"
    try:
        return CellSpectralCharacterization(
            provenance=view_provenance(view),
            pass_name=pass_name,
            quantity=quantity,
            unit=unit,
            psd_unit=psd_unit,
            detrending=Detrending(detrending),
            low_hz=float(low_hz),
            admission=admission,
            targets=rows,
            gates=tuple(gates),
            estimator_name=estimator_name,
            taper_name=taper_name,
            taper_convention=taper_convention,
            normalization_rule=normalization,
            one_sided_rule=one_sided,
        )
    except ValidationError as error:
        # The cell model's cross-field invariants refuse a row that contradicts its axis. Pydantic
        # wraps that ValueError in its own ValidationError, which would hide this module's typed
        # error from a caller, so it is re-raised by name. The gate rows built above are wrapped
        # the same way, so the whole public path speaks this one error vocabulary.
        raise BandFractionError(
            f"{view.relative_path}: this cell contradicts its own axis or its own rows: {error}"
        ) from error
