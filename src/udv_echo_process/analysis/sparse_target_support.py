"""Is a specific frequency inside what this axis can honestly carry? (``SA2``).

The third SA2 question, and the only one that names a frequency. Three of its parts are
published separately because they can disagree, and collapsing them would hide the one case
this stage exists to report:

``band_supported``
    The **hard Nyquist impossibility**, decided by the characterized timestamps alone. 8.333 Hz
    cannot be carried by a 11.47 Hz axis, whatever the stamps look like, and that verdict needs
    no estimator. This is the one part that is answerable *before* admission.
``analysis_supported``
    Whether the estimator that would measure the band was admitted for this axis at all. An
    irregular E20 axis at 8.333 Hz is inside Nyquist and still unmeasurable here, and saying so
    as "band unsupported" would be a false statement about the physics of the axis.
``supported``
    The conjunction, and the user-facing answer.

**The grid is the adopted one.** Bin positions come from
:func:`~udv_echo_process.analysis.sparse_spectral_support.one_sided_frequencies`, i.e. from
``delta_f = fs_eff / N`` and never from ``1 / span``; see that module for why those differ.
Two consequences are handled explicitly here rather than assumed away:

* an odd-length real transform's highest bin sits **below** mathematical Nyquist
  (``floor(N/2) * delta_f < fs_eff / 2``), so "every one-sided grid contains a Nyquist bin" is
  false and :attr:`TargetFrequencySupport.nyquist_represented` says which case this axis is;
* the highest represented bin has no bin above it, so its cell's upper edge is the physical
  support edge instead of a midpoint to a bin that does not exist. The DC bin's lower edge is
  ``0`` for the same reason. Neither endpoint reads a fictitious neighbour.

**Cycles are reported, never refused.** ``cycles_in_view = target_hz * span_s`` on the view's
own span - not on its nominal duration - and it is an *interpretation-quality* diagnostic with
no threshold attached. A target can be inside Nyquist and poorly resolved by a short
observation, and that is a statement about the reading, not about the axis: refusing it would
be inventing a scientific threshold, which the design forbids. SA1's ``MIN_CANDIDATE_CYCLES``
is deliberately not reused here; it belongs to an autocorrelation period claim.
"""

from __future__ import annotations

import math

from udv_echo_process.analysis._sparse_view import SparseViewError
from udv_echo_process.analysis.sparse_spectral_admission import SpectralAdmission
from udv_echo_process.analysis.sparse_spectral_support import (
    TimebaseCharacterization,
    one_sided_frequency_grid,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "BAND_SUPPORT_RULE",
    "BIN_EDGE_TOLERANCE_BINS",
    "CELL_RULE",
    "CYCLES_ROLE",
    "SpectralSupportError",
    "TargetFrequencySupport",
    "band_support",
    "frequency_cell",
    "target_frequency_support",
]

#: The only tolerance used on the cell comparison, named rather than implicit. It exists because
#: a target placed exactly on a cell edge is a legitimate question - the boundary is arithmetic,
#: not physical - and the edge itself is computed from two roundings. It is a *relative* slack of
#: one billionth of a bin, three orders of magnitude below the interval deviation of the
#: best-behaved committed axis and twelve orders below any distortion the calibration measures.
BIN_EDGE_TOLERANCE_BINS = 1e-9

#: The band test, and why it is only the Nyquist impossibility.
BAND_SUPPORT_RULE = (
    "band_supported is true exactly when the target is below the axis's mathematical Nyquist "
    "frequency and the evaluated cell it falls in lies within the represented one-sided support. "
    "Strictly below: a target at exactly Nyquist is refused, because a real transform of an "
    "even-length record represents that frequency at a single bin whose value is the sum of a "
    "real alternating term - it is the edge of the representable band, not inside it. No margin "
    "ratio is applied, because none is a scientific threshold. For a target at or above Nyquist "
    "the nearest *existing* bin is the top one and the reported offset is its distance above that "
    "bin - greater than half a bin, which is the arithmetic statement that the grid holds no cell "
    "for this target. The cell test is not consulted for such a target at all, so no cell is ever "
    "read from a bin that does not exist."
)

#: How many cycles the view holds, and what that number is not.
CYCLES_ROLE = (
    "cycles_in_view is target_hz * span_s on the view's own span, and it is an "
    "interpretation-quality diagnostic that never refuses a target. A target inside Nyquist "
    "whose cycle count is small is poorly resolved by this observation, not unsupported by this "
    "axis; refusing it would turn an arbitrary cycle threshold into a scientific one. The "
    "declared window, the achieved span and the cycle count are carried separately because "
    "discrete sampling makes the third a product of the second."
)

#: What "the evaluated cell" means, and its two endpoint rules.
CELL_RULE = (
    "the evaluated cell of a target is the cell of the nearest prospective DFT bin, whose edges "
    "are the midpoints to the neighbouring bins. The two endpoints do not have both neighbours: "
    "the DC cell's lower edge is 0.0 and the highest represented cell's upper edge is the "
    "physical support edge min(nyquist_hz, (index + 0.5) * delta_f), which is why an odd-length "
    "transform's top cell reaches Nyquist even though its top bin does not. No cell edge is read "
    "from a bin that does not exist. A target may sit anywhere inside the cell, including on its "
    "edge within BIN_EDGE_TOLERANCE_BINS, which is the only tolerance used on this comparison "
    "and is named rather than implicit."
)


class SpectralSupportError(SparseViewError):
    """A target-frequency question that was malformed rather than unanswerable.

    Distinct from an *unsupported* target in the same way SA1's bounds refusals are distinct
    from its verdicts: ``target_hz`` of zero or a negative number, or a non-finite one, is a
    caller error and is not a scientific verdict about the axis. A target above Nyquist is
    **not** an error - it is the answer ``band_supported=False`` with its reason.
    """


def frequency_cell(index: int, *, grid: dict[str, object]) -> tuple[float, float]:
    """The frequency cell of one bin of a published one-sided grid, ``(low_hz, high_hz)``.

    The cell's edges are the midpoints to the neighbouring bins, with the two endpoint rules of
    :data:`CELL_RULE` applied instead of a fictitious neighbour:

    - the DC cell opens at ``0.0``;
    - the highest represented cell closes at ``min(nyquist_hz, (index + 0.5) * delta_f)``, which
      is the physical support edge. For an even-length transform the top bin sits exactly at
      Nyquist and the midpoint would lie above it, so the clip is what makes the top cell end at
      Nyquist; for an odd-length transform the top bin sits half a bin *below* Nyquist and the
      midpoint to the bin that would exist there *is* Nyquist, so the clip changes nothing and
      the two parities agree on the same upper edge.

    Raises:
        SpectralSupportError: for an index outside the grid, so that no cell is invented for a
            bin that does not exist.
    """
    bins = int(grid["bins"])  # type: ignore[arg-type]
    delta = float(grid["delta_f_hz"])  # type: ignore[arg-type]
    nyquist = float(grid["nyquist_hz"])  # type: ignore[arg-type]
    position = int(index)
    if not 0 <= position < bins:
        raise SpectralSupportError(
            f"bin {position} is outside a one-sided grid of {bins} bins; the cells of a grid "
            "that does not exist are not defined"
        )
    low = 0.0 if position == 0 else (position - 0.5) * delta
    if position == bins - 1:
        high = min(nyquist, (position + 0.5) * delta)
    else:
        high = (position + 0.5) * delta
    return (low, high)


class TargetFrequencySupport(ValueModel):
    """One target frequency asked of one characterized, admitted axis.

    The axis itself is carried through :attr:`admission`, whose
    :class:`~udv_echo_process.analysis.sparse_spectral_support.TimebaseCharacterization` owns
    every rate, span and bin spacing below. They are *not* copied onto this result: a second copy
    of ``delta_f`` is a second chance for the grid and the verdict to disagree.
    """

    target_hz: float
    admission: SpectralAdmission
    #: The probe's own label, when the caller has one: carried so a report quotes the name the
    #: design uses rather than a formatted frequency.
    target_label: str | None = None

    #: ``target_hz * span_s`` on the view's own span, or ``None`` when the axis has no span.
    cycles_in_view: float | None = None
    #: Whether a bin of this grid sits exactly at mathematical Nyquist (even-length transform).
    nyquist_represented: bool | None = None

    prospective_bin: int | None = None
    prospective_bin_hz: float | None = None
    bin_offset_hz: float | None = None
    bin_offset_bins: float | None = None
    cell_low_hz: float | None = None
    cell_high_hz: float | None = None

    band_supported: bool
    analysis_supported: bool
    band_reason: str
    analysis_reason: str
    reason: str

    cell_rule: str = CELL_RULE
    band_rule: str = BAND_SUPPORT_RULE
    cycles_role: str = CYCLES_ROLE

    @property
    def supported(self) -> bool:
        """The user-facing answer: both the band and the estimator have to hold.
        """
        return self.band_supported and self.analysis_supported

    @property
    def characterization(self) -> TimebaseCharacterization:
        """The characterized axis this target was asked of.
        """
        return self.admission.characterization

    @property
    def provenance(self):
        """The shared view provenance, or ``None`` for an axis characterized without a view.
        """
        return self.characterization.provenance

    @property
    def profiles(self) -> int:
        """The number of samples on the axis.
        """
        return self.characterization.profiles

    @property
    def nyquist_hz(self) -> float | None:
        """The axis's mathematical Nyquist frequency.
        """
        return self.characterization.nyquist_hz

    @property
    def frequency_resolution_hz(self) -> float | None:
        """The prospective DFT bin spacing, ``fs_eff / N``.
        """
        return self.characterization.frequency_resolution_hz

    @property
    def duration_resolution_scale_hz(self) -> float | None:
        """The observation-duration scale ``1 / span``, which is not the bin spacing.
        """
        return self.characterization.duration_resolution_scale_hz

    @property
    def declared_window_s(self) -> float | None:
        """The interval the selection asked for, when it was made through a view.
        """
        return None if self.provenance is None else self.provenance.declared_window_s

    @property
    def actual_span_s(self) -> float | None:
        """The span the stored stamps actually hold.
        """
        return self.characterization.span_s

    @property
    def resolution_bins_to_target(self) -> int | None:
        """How many bins separate the target from DC - the nearest prospective bin's index.
        """
        return self.prospective_bin


def _target(target_hz: object) -> float:
    """The target as a positive finite frequency, refused by name otherwise.
    """
    value = float(target_hz)  # type: ignore[arg-type]
    if not math.isfinite(value) or value <= 0.0:
        raise SpectralSupportError(
            f"a target frequency must be a positive finite number of Hz, got {target_hz!r}; a "
            "zero or negative target is not a frequency this axis can be asked about"
        )
    return value


def _nearest_bin(value: float, delta_f_hz: float, *, top: int) -> int:
    """The prospective bin nearest ``value``, by round-half-up on the bin index.

    Stated rather than left to a language default: at exactly half a bin the two neighbours are
    equally near, and the choice has to be one of them deterministically. Round-half-up puts the
    tie on the upper bin, whose cell the value then sits on the lower edge of - still inside it,
    by :data:`BIN_EDGE_TOLERANCE_BINS`.
    """
    return min(max(math.floor(value / delta_f_hz + 0.5), 0), top)


def band_support(characterization: TimebaseCharacterization, target_hz: float) -> bool:
    """The band question alone, answerable before any estimator is admitted.

    The hard Nyquist impossibility needs nothing but the characterized timestamps, so it is
    published on its own: a caller comparing a target against what the *axis* can carry does not
    have to obtain an admission verdict first, and an axis whose estimator is refused can still
    be reported as physically able to carry a band. Returns the same verdict
    :func:`target_frequency_support` folds into its result.
    """
    return _band_verdict(characterization, _target(target_hz))[0]


def _band_verdict(
    characterization: TimebaseCharacterization, target_hz: float
) -> tuple[bool, str, dict[str, object]]:
    """``(supported, reason, grid quantities)`` for one target against one axis.
    """
    profiles = int(characterization.profiles)
    delta = characterization.frequency_resolution_hz
    nyquist = characterization.nyquist_hz
    quantities: dict[str, object] = {
        "grid": None,
        "index": None,
        "index_hz": None,
        "offset_hz": None,
        "offset_bins": None,
        "low": None,
        "high": None,
    }
    if delta is None or nyquist is None:
        return (
            False,
            (
                "the axis publishes no bin spacing and no Nyquist frequency "
                f"({profiles} sample{'s' if profiles != 1 else ''}), so no band can be located "
                "on it"
            ),
            quantities,
        )
    grid = one_sided_frequency_grid(profiles, float(characterization.effective_sample_rate_hz))
    top = int(grid["bins"]) - 1
    index = _nearest_bin(target_hz, delta, top=top)
    low, high = frequency_cell(index, grid=grid)
    slack = BIN_EDGE_TOLERANCE_BINS * delta
    quantities.update(
        {
            "grid": grid,
            "index": index,
            "index_hz": index * delta,
            "offset_hz": target_hz - index * delta,
            "offset_bins": target_hz / delta - index,
            "low": low,
            "high": high,
        }
    )
    if target_hz >= nyquist:
        return (
            False,
            (
                f"{target_hz:.6g} Hz is at or above this axis's Nyquist frequency "
                f"{nyquist:.6g} Hz: band-supported requires strictly below it"
            ),
            quantities,
        )
    if not low - slack <= target_hz <= high + slack:
        return (
            False,
            (
                f"{target_hz:.6g} Hz falls outside the evaluated cell [{low:.6g}, {high:.6g}] Hz "
                f"of bin {index} (bin {index * delta:.6g} Hz), so the grid does not evaluate it"
            ),
            quantities,
        )
    return (
        True,
        (
            f"{target_hz:.6g} Hz is below this axis's Nyquist frequency {nyquist:.6g} Hz and "
            f"inside bin {index}'s cell [{low:.6g}, {high:.6g}] Hz"
        ),
        quantities,
    )


def target_frequency_support(
    admission: SpectralAdmission, target_hz: float, *, label: str | None = None
) -> TargetFrequencySupport:
    """Whether ``target_hz`` is supported by the axis this admission was issued for.

    The whole point of taking a :class:`SpectralAdmission` rather than a view is that the two
    refusals stay distinct: an E128 axis refuses 8.333 Hz because the band is impossible, and an
    axis whose estimator was refused refuses every target for the other reason. Both are reported
    side by side, and :attr:`TargetFrequencySupport.reason` names whichever decided it.

    Raises:
        SpectralSupportError: for a target that is not a positive finite frequency. An
            *unsupported* target is not an error and never raises.
    """
    value = _target(target_hz)
    characterization = admission.characterization
    supported, band_reason, quantities = _band_verdict(characterization, value)
    span = characterization.span_s
    cycles = value * span if span is not None and span > 0.0 else None
    grid = quantities["grid"]
    if admission.admitted:
        analysis_reason = (
            f"the single-view uniform-grid estimator is admitted for this axis "
            f"({admission.estimator}): {admission.reason}"
        )
    else:
        analysis_reason = (
            "the estimator that would measure this band refused the timestamp grid, so no "
            f"target on this axis is measurable here: {admission.reason}"
        )
    if not supported:
        reason = band_reason
    elif not admission.admitted:
        reason = analysis_reason
    else:
        reason = (
            f"{band_reason}; the estimator is admitted, so the target is supported "
            f"({cycles:.4g} cycles in view)"
            if cycles is not None
            else "(no span to count cycles over)"
        )
    return TargetFrequencySupport(
        target_hz=value,
        admission=admission,
        target_label=label,
        cycles_in_view=cycles,
        nyquist_represented=(
            None if grid is None else bool(grid["nyquist_is_represented"])  # type: ignore[index]
        ),
        prospective_bin=quantities["index"],  # type: ignore[arg-type]
        prospective_bin_hz=quantities["index_hz"],  # type: ignore[arg-type]
        bin_offset_hz=quantities["offset_hz"],  # type: ignore[arg-type]
        bin_offset_bins=quantities["offset_bins"],  # type: ignore[arg-type]
        cell_low_hz=quantities["low"],  # type: ignore[arg-type]
        cell_high_hz=quantities["high"],  # type: ignore[arg-type]
        band_supported=supported,
        analysis_supported=bool(admission.admitted),
        band_reason=band_reason,
        analysis_reason=analysis_reason,
        reason=reason,
    )
