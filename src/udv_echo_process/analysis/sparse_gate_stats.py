"""Per-gate descriptive statistics and declared depth reductions (plan ``SA1``).

SA1's statistics half: the plan reuses the frozen ``gate_metrics`` (mean, median,
IQR, RMS, zero fraction) and then asks for "per-gate standard deviation, MAD
(state its scaling), min/max, q05/q25/q50/q75/q95, skewness and kurtosis with
explicit degenerate/constant-trace behavior" and for "depth reductions and their
weighting; keep gate profiles rather than collapsing them prematurely".

What this module is:

- :func:`extended_gate_metrics` — the eleven statistics beyond the frozen five,
  computed per gate for a ``(profiles, gates)`` window, in ``mm/s`` except the
  three shape/quality ones;
- :class:`~udv_echo_process.models.base.ArrayModel` results with provenance: the
  source identity, the *view* the numbers came from, the three depth extents they
  were computed on, and this module's own estimator settings;
- the three labelled views themselves live in
  :mod:`udv_echo_process.analysis._sparse_view`, which owns the one vocabulary
  (:class:`~udv_echo_process.analysis._sparse_view.SparseView`), the one cutting
  path (:class:`~udv_echo_process.analysis._sparse_view.WindowView`) and the one
  provenance every sparse slice shares. This module re-exports them rather than
  restating them, so a view is spelled and cut the same way here, in the
  recurrence slice and in the notebook;
- depth reductions whose weights are declared (:data:`WEIGHTING_EQUAL`,
  :data:`WEIGHTING_NATIVE_SLAB`), so a scalar summary is an argument with stated
  weights rather than an unlabelled average.

Two conventions are stated here because the plan demands them explicit, and both
are pinned by tests rather than left to a reader:

- **MAD is scaled by 1.4826** (:data:`MAD_SCALE`), the normal-consistency factor,
  so on a normal sample it estimates the same quantity as ``std``; the unscaled
  median absolute deviation is ``mad_scaled / 1.4826``;
- **a zero-variance gate has no shape**: skewness and excess kurtosis are
  undefined and reported as ``NaN`` (:data:`CONSTANT_TRACE_RULE`), never as
  ``0.0`` or an all-zero curve, while its location and spread statistics are
  exactly what the population moments give for a constant sample.

No interval is computed anywhere in this module, and this is deliberate: profiles
and gates inside one recording are correlated samples, not independent
realizations, so any interval over them would be a *pseudoreplicate* interval.
The reductions report a value and its weights, the results report which gates
carry an undefined statistic, and the uncertainty question stays with the
block-bootstrap/floor vocabulary the plan reserves for within-record
conditional statements.

What this module deliberately does not do (the notebook-preview half of SA1, and
later slices): representative gate traces, time slices and distributions;
detrending, normalized ACF, first zero crossing, 1/e decay, integral time and
recurrence peaks; spectra and sampling support (SA2). No estimator here is a
notebook's.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._sparse_view import (
    VIEW_LABELS,
    VIEW_RULES,
    SparseView,
    SparseViewError,
    ViewProvenance,
    WindowView,
    exploration_view,
    full_record_view,
    primary_view,
    view_provenance,
)
from udv_echo_process.analysis.reference_repeat import METRICS as FROZEN_METRICS
from udv_echo_process.analysis.reference_repeat import gate_metrics
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field

__all__ = [
    "CONSTANT_TRACE_RULE",
    "EXCESS_KURTOSIS_CONVENTION",
    "EXTENDED_STATISTICS",
    "GATE_STATISTICS",
    "MAD_SCALE",
    "MAD_SCALING",
    "METHOD",
    "REUSED_STATISTICS",
    "STATISTIC_UNITS",
    "VIEW_EXPLORATION",
    "VIEW_FULL_RECORD",
    "VIEW_LABELS",
    "VIEW_PRIMARY",
    "VIEW_RULES",
    "WEIGHTING_EQUAL",
    "WEIGHTING_EQUAL_RULE",
    "WEIGHTING_NATIVE_SLAB",
    "WEIGHTING_NATIVE_SLAB_RULE",
    "DepthReduction",
    "GateStatistics",
    "SparseGateStatsError",
    "SparseView",
    "SparseViewError",
    "ViewProvenance",
    "WindowView",
    "exploration_view",
    "extended_gate_metrics",
    "full_record_view",
    "gate_statistics",
    "native_slab_weights",
    "primary_view",
    "reduce_equal_weight",
    "reduce_native_slab",
    "statistic_units",
    "view_provenance",
]


class SparseGateStatsError(SparseViewError):
    """A per-gate statistic or a depth reduction cannot be computed as asked.

    Raised for an input that is not a ``(profiles, gates)`` window, a window with
    no profile or a gate with no sample, a non-finite sample, an undefined
    statistic entering a reduction, or a reduction whose values and depths
    disagree. A view that cannot be selected at all is refused by
    :class:`~udv_echo_process.analysis._sparse_view.SparseViewError`, of which this
    is a subclass, so a caller may catch either the statistics refusal or the whole
    sparse-view refusal - and both are a ``ValueError``.
    """


#: The statistics the plan keeps from the frozen WP1 module, under that module's
#: own names: this module *calls* ``gate_metrics`` rather than restating its
#: definitions, so a floor computed here is the frozen floor.
REUSED_STATISTICS: tuple[str, ...] = FROZEN_METRICS

#: The statistics SA1 adds, computed by :func:`extended_gate_metrics`.
EXTENDED_STATISTICS: tuple[str, ...] = (
    "std",
    "mad_scaled",
    "min",
    "max",
    "q05",
    "q25",
    "q50",
    "q75",
    "q95",
    "skewness",
    "excess_kurtosis",
)

#: Every per-gate statistic a :class:`GateStatistics` result carries, in row order.
GATE_STATISTICS: tuple[str, ...] = REUSED_STATISTICS + EXTENDED_STATISTICS

#: The normal-consistency scale :attr:`GateStatistics`'s ``mad_scaled`` row uses.
MAD_SCALE: float = 1.4826

#: The delta degrees of freedom every moment here is computed with: population moments, so a
#: single-profile view has a defined (zero) spread rather than an undefined one.
STD_DDOF = 0

MAD_SCALING = (
    "median absolute deviation of the gate's own trace about its own median, scaled by 1.4826 "
    "(the normal-consistency factor: on a normal sample the scaled value estimates the standard "
    "deviation). The unscaled statistic is mad_scaled / 1.4826."
)

#: The interpolation :func:`numpy.percentile` is *called with*, and the method every result
#: records. It is passed explicitly rather than left to numpy's default, so the recorded
#: convention and the executed one cannot drift apart when a numpy release changes a default.
PERCENTILE_METHOD = "linear"

#: How far the extended percentiles may differ from the frozen pair they claim to extend.
#: ``np.median``'s midpoint rule and ``np.percentile``'s linear interpolation are different
#: operations, so ``q50`` and the frozen ``median`` agree to floating point rather than
#: bit-exactly (one ULP on the committed data); ``q75 - q25`` and the frozen ``iqr`` do agree
#: bit-exactly there, but that is a measured property of these routines and not a guarantee
#: of them. Both are therefore checked against a relative tolerance, and a divergence past it
#: is refused as a contradiction inside one result rather than published as two rows.
PERCENTILE_AGREEMENT_TOL = 1e-9

EXCESS_KURTOSIS_CONVENTION = (
    "excess kurtosis: mean((x - mean)^4) / variance^2 - 3 on population (biased) moments, so a "
    "normal sample scores 0. This is the metric the plan calls kurtosis, minus three."
)

CONSTANT_TRACE_RULE = (
    "a zero-variance gate - one distinct value over the view, including a single-profile view - "
    "has no shape to describe: skewness and excess kurtosis are undefined and reported as NaN, "
    "never as 0.0 and never as an all-zero curve. Its location and spread statistics are exactly "
    "what population moments give for a constant sample - mean/min/max/median and every percentile "
    "equal to that value, std/mad_scaled/iqr exactly 0.0 - and they are reported rather than "
    "withheld. The test for 'constant' is exact variance == 0.0, so no epsilon band decides whether "
    "a gate has a shape. An undefined statistic is never silently averaged: the depth reductions "
    "refuse it and GateStatistics.unmeasured() names the gates that carry it."
)

METHOD = (
    "gate-local statistics over the view's supported gates, one value per gate in native depth "
    "order: the five frozen names come from reference_repeat.gate_metrics; percentiles use numpy's "
    "linear interpolation; std/variance/skewness/excess kurtosis are population moments (ddof=0); "
    "MAD is scaled by 1.4826. No interval is computed: the profiles and gates of one recording are "
    "correlated samples, not independent replicates."
)

#: The one view vocabulary, aliased from :mod:`.._sparse_view` so a call site can
#: spell a view without importing the view module directly. These are *aliases of
#: the single canonical enum members* - not a second vocabulary - and they are the
#: hyphenated labels every result carries, so a view reads the same in a statistics
#: result, a recurrence result and a notebook. :data:`VIEW_LABELS` and
#: :data:`VIEW_RULES` are imported from the same module and are the vocabulary's own
#: membership rule and rule text.
VIEW_PRIMARY = SparseView.PRIMARY
VIEW_FULL_RECORD = SparseView.FULL_RECORD
VIEW_EXPLORATION = SparseView.EXPLORATION

#: The weighting labels the depth reductions declare. Both state their rule; neither
#: hides a weighting behind an unlabelled average.
WEIGHTING_EQUAL = "unweighted: one supported gate, one vote"
WEIGHTING_NATIVE_SLAB = (
    "native-slab: each supported gate weighted by the depth interval it covers on its own grid"
)

WEIGHTING_EQUAL_RULE = (
    "Every supported gate carries one vote, whatever its depth: the rule the frozen WP0/WP1 "
    "supported_* cells use, restated here so a scalar summary of this module agrees with the "
    "table's own number. It is deliberately *not* a depth integral: an integral over a support "
    "that lands on gate positions gives the two end gates half a cell each, which is what the "
    "native-slab weighting measures and what makes the two reductions differ by the end gates' "
    "share rather than by an accident."
)

WEIGHTING_NATIVE_SLAB_RULE = (
    "Gate-count-aware weighting: each gate is weighted by the depth interval it actually covers, "
    "read from the participating gates' own coordinates (cells between neighbouring midpoints, the "
    "end gates extending half a gap), with every cell clipped to the analysed support. On the "
    "uniform native grids this reader enforces, with the support landing on gate positions - which "
    "is what the pass's common support does - each end cell is therefore clipped to half a pitch "
    "while every interior cell keeps a whole one, so the two end gates carry half of an interior "
    "gate's weight. The two reductions then coincide on a profile symmetric about the support "
    "centre (a linear ramp among them) and differ elsewhere by exactly that end-gate share, and "
    "they differ further wherever the participating grid or the support is not uniform. The "
    "weighting is declared so which of the two a scalar summary used is visible and chosen."
)

STATISTIC_UNITS: dict[str, str] = {
    name: (
        "mm/s" if name not in ("zero_fraction", "skewness", "excess_kurtosis") else "dimensionless"
    )
    for name in GATE_STATISTICS
}


def statistic_units(name: str) -> str:
    """The unit of one per-gate statistic: ``mm/s`` for a velocity, dimensionless otherwise.

    Args:
        name: one of :data:`GATE_STATISTICS`.

    Returns:
        The statistic's unit as this module's results carry it.

    Raises:
        SparseGateStatsError: for a name this module does not define, so a typo cannot
            pass as a dimensionless statistic.
    """
    if name not in STATISTIC_UNITS:
        raise SparseGateStatsError(
            f"unknown gate statistic {name!r}; this module's are {list(GATE_STATISTICS)}"
        )
    return STATISTIC_UNITS[name]


def extended_gate_metrics(values: np.ndarray) -> dict[str, np.ndarray]:
    """The SA1 statistics of a ``(profiles, gates)`` window, one value per gate.

    Definitions, all per gate and in ``mm/s`` except the dimensionless three:

    - ``std`` — population standard deviation about the gate's own mean
      (``ddof=0``), so a single-profile or constant gate scores exactly ``0.0``;
    - ``mad_scaled`` — the median absolute deviation about the gate's own median,
      scaled by :data:`MAD_SCALE` (1.4826) for normal consistency;
    - ``min`` / ``max`` — the extreme samples;
    - ``q05`` … ``q95`` — percentiles with ``numpy.percentile``'s linear
      interpolation. The interpolation is passed explicitly as
      :data:`PERCENTILE_METHOD`, the convention the frozen ``iqr`` uses, so ``q50``
      and the frozen ``median`` are the same quantity and ``q75 - q25`` and the
      frozen ``iqr`` are the same quantity - but they are not bit-identical
      *operations* (``np.median`` uses a midpoint rule where ``np.percentile``
      interpolates), so :func:`gate_statistics` checks the agreement at
      :data:`PERCENTILE_AGREEMENT_TOL` rather than asserting an identity the
      routines do not guarantee;
    - ``skewness`` — population third standardized moment
      ``mean((x - mean)^3) / std^3``;
    - ``excess_kurtosis`` — see :data:`EXCESS_KURTOSIS_CONVENTION`.

    Degenerate behaviour (:data:`CONSTANT_TRACE_RULE`): a gate whose variance is
    exactly zero scores ``0.0`` for every spread statistic and ``NaN`` for
    ``skewness`` and ``excess_kurtosis``. A single-profile view is that case.

    Args:
        values: the ``(profiles, gates)`` velocity window of one view.

    Returns:
        One length-``gates`` array per name in :data:`EXTENDED_STATISTICS`.

    Raises:
        SparseGateStatsError: for an array that is not 2-D, a window with no
            profile, or a non-finite sample (a statistic over NaN is not a
            measurement, and it is refused rather than averaged away).
    """
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise SparseGateStatsError(
            f"per-gate statistics need a 2-D (profiles, gates) array, got shape {array.shape}"
        )
    if array.shape[0] == 0:
        raise SparseGateStatsError(
            "per-gate statistics need at least one profile: an empty window has no distribution"
        )
    if not np.all(np.isfinite(array)):
        raise SparseGateStatsError(
            "the window carries non-finite samples; a statistic over NaN is not a measurement "
            "(refuse the gate explicitly instead of averaging it away)"
        )
    mean = array.mean(axis=0)
    centred = array - mean
    variance = np.var(array, axis=0)
    scale = np.sqrt(variance)
    median = np.median(array, axis=0)
    q05, q25, q50, q75, q95 = np.percentile(
        array, [5.0, 25.0, 50.0, 75.0, 95.0], axis=0, method=PERCENTILE_METHOD
    )
    # A gate with no variance has no shape: NaN, deliberately, and the constant
    # test is exact because a constant trace is exactly constant.
    degenerate = variance == 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        skewness = np.where(degenerate, np.nan, np.mean(centred**3, axis=0) / scale**3)
        excess = np.where(
            degenerate, np.nan, np.mean(centred**4, axis=0) / variance**2 - 3.0
        )
    return {
        "std": scale,
        "mad_scaled": MAD_SCALE * np.median(np.abs(array - median), axis=0),
        "min": array.min(axis=0),
        "max": array.max(axis=0),
        "q05": q05,
        "q25": q25,
        "q50": q50,
        "q75": q75,
        "q95": q95,
        "skewness": skewness,
        "excess_kurtosis": excess,
    }


class GateStatistics(ArrayModel):
    """Every per-gate statistic of one :class:`WindowView`.

    ``statistics`` is ``(len(statistic_names), gates)``: one row per name in
    :data:`GATE_STATISTICS`, in that order, one column per *supported* gate, in the
    recording's native depth order - so the profiles are kept, per gate, and no
    reduction has happened yet. ``units`` is aligned with ``statistic_names``, and
    ``support_mask`` is the *view's own* mask over the columns the view holds, which is
    what selected ``depths_mm`` here - not a mask over the recording's native grid, so
    its length is this view's column count.

    The estimator conventions this result was computed under travel on the result
    (:data:`METHOD`, :data:`PERCENTILE_METHOD`, :data:`MAD_SCALE`,
    :data:`EXCESS_KURTOSIS_CONVENTION`, :data:`CONSTANT_TRACE_RULE`), because they
    describe *how* the numbers were made, which is a property of this module's estimator
    rather than of the data. The native grid's own dimension is in ``provenance``:
    ``provenance.native_gates`` is the recording's gate count, never this result's
    column count.
    """

    statistic_names: tuple[str, ...]
    units: tuple[str, ...]
    statistics: array_field(np.float64, rank=2)
    depths_mm: array_field(np.float64, rank=1)
    support_mask: array_field(np.bool_, rank=1)
    provenance: ViewProvenance
    method: str
    percentile_method: str
    std_ddof: int
    mad_scale: float
    mad_scaling: str
    excess_kurtosis_convention: str
    constant_trace_rule: str

    @model_validator(mode="after")
    def _check_every_row_is_one_named_supported_statistic(self) -> GateStatistics:
        if self.statistics.shape != (len(self.statistic_names), self.depths_mm.size):
            raise ValueError(
                f"the statistics {self.statistics.shape} must hold one row per statistic "
                f"({len(self.statistic_names)}) and one column per supported gate "
                f"({self.depths_mm.size})"
            )
        if len(self.units) != len(self.statistic_names):
            raise ValueError("every statistic carries exactly one unit")
        if int(np.count_nonzero(self.support_mask)) != self.depths_mm.size:
            raise ValueError(
                "the columns must be exactly the gates the support mask selects"
            )
        return self

    def of(self, name: str) -> np.ndarray:
        """The row of one statistic, one value per supported gate, in native depth order.

        Raises:
            SparseGateStatsError: for a name this result does not carry.
        """
        if name not in self.statistic_names:
            raise SparseGateStatsError(
                f"unknown gate statistic {name!r}; this result's are "
                f"{list(self.statistic_names)}"
            )
        return self.statistics[self.statistic_names.index(name)]

    def unmeasured(self) -> dict[str, tuple[int, ...]]:
        """The statistics that carry an undefined (non-finite) value, and where.

        Only statistics with at least one undefined gate appear, and the positions
        are indices into this result's supported-gate columns: an undefined estimate
        is named rather than displayed as a zero curve, and never silently reduced.
        """
        return {
            name: tuple(int(index) for index in np.flatnonzero(~np.isfinite(self.of(name))))
            for name in self.statistic_names
            if not np.all(np.isfinite(self.of(name)))
        }


class DepthReduction(ValueModel):
    """One per-gate statistic reduced across depth, with its weighting declared.

    ``value`` is the weighted mean of the per-gate values, ``weights`` are the
    weights used (summing to 1), and ``weighting``/``weighting_rule`` state which
    weighting this is and why. The per-gate values are *not* consumed by this
    result: it is one scalar beside the profile it came from, never a replacement
    for it.

    Two different extents are kept apart here, because SA1 had three fields whose names
    all said support and whose meanings did not agree:

    - ``gate_extent_mm`` - the extent of the gates this reduction actually *reduced*,
      i.e. the participating gates of the profile handed in. It is a property of the
      input, and it is the same for both weightings;
    - ``slab_support_mm`` - the support interval the native-slab cells were clipped to,
      which is what the weights were constructed from. It is ``None`` exactly for equal
      weighting, which clips nothing: a reduction reports no clipping interval rather
      than echoing one it never used.
    """

    statistic: str
    units: str
    value: float
    weighting: str
    weighting_rule: str
    gates: int
    weights: tuple[float, ...]
    weight_sum: float
    gate_extent_mm: tuple[float, float]
    slab_support_mm: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _check_the_weights_are_declared_positive_and_normalized(self) -> DepthReduction:
        if len(self.weights) != self.gates:
            raise ValueError(
                f"{len(self.weights)} weight(s) for {self.gates} gate(s); a reduction weights "
                "every gate it reduces"
            )
        if not all(weight > 0.0 for weight in self.weights):
            raise ValueError("every weight of a depth reduction is positive")
        if not math.isclose(self.weight_sum, sum(self.weights), rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("the declared weight sum must be the sum of the declared weights")
        if not math.isclose(self.weight_sum, 1.0, rel_tol=1e-9):
            raise ValueError(
                f"a weighted mean's weights normalize to 1, got {self.weight_sum!r}"
            )
        if not math.isfinite(self.value):
            raise ValueError(
                f"a depth reduction of {self.statistic!r} must be finite, got {self.value!r}; "
                "an undefined statistic is refused, never reduced into a scalar"
            )
        if (self.slab_support_mm is not None) != (
            self.weighting == WEIGHTING_NATIVE_SLAB
        ):
            raise ValueError(
                "a clipping support is reported exactly by the native-slab weighting, which is "
                f"the only one that clips: got {self.slab_support_mm!r} with "
                f"{self.weighting!r}"
            )
        return self


def require_depth_support(support_mm: tuple[float, float]) -> tuple[float, float]:
    """One required depth-support interval, refused unless finite and increasing.

    Native-slab weighting is *defined* by the interval its cells are clipped to: with no
    interval and a uniform grid, full-pitch cells give every gate an equal share, so the
    reduced number would be the equal-weight one while declaring the slab rule. The
    support is therefore a required argument, and a degenerate interval (one point, or a
    reversed pair) is not a support.

    Raises:
        SparseGateStatsError: for an interval that is not finite and increasing.
    """
    low, high = float(support_mm[0]), float(support_mm[1])
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        raise SparseGateStatsError(
            "native-slab weighting needs a finite, increasing support interval to clip its "
            f"cells to, got ({low!r}, {high!r})"
        )
    return low, high


def _require_the_extended_percentiles_agree_with_the_frozen_pair(
    rows: dict[str, np.ndarray],
) -> None:
    """Refuse a result whose extended percentiles contradict the frozen pair they extend.

    The frozen five come from :func:`gate_metrics` (``median`` uses ``np.median``) and the
    extended eleven from :func:`extended_gate_metrics` (``q25``/``q50``/``q75`` use
    ``np.percentile``), so ``q50``/``median`` and ``q75 - q25``/``iqr`` are the same two
    quantities computed by different routines. They agree to floating point; a divergence
    past :data:`PERCENTILE_AGREEMENT_TOL` would mean one result publishes two contradicting
    rows for one quantity, which is refused here rather than left for a reader to notice.

    Raises:
        SparseGateStatsError: for a pair that disagrees past the tolerance.
    """
    scale = np.maximum(np.abs(rows["median"]), np.abs(rows["q50"]))
    scale = np.where(scale > 0.0, scale, 1.0)
    gaps = {
        "q50 against the frozen median": float(
            np.max(np.abs(rows["q50"] - rows["median"]) / scale)
        ),
        "q75 - q25 against the frozen iqr": float(
            np.max(np.abs((rows["q75"] - rows["q25"]) - rows["iqr"]) / scale)
        ),
    }
    offending = {
        what: gap for what, gap in gaps.items() if not gap <= PERCENTILE_AGREEMENT_TOL
    }
    if offending:
        named = "; ".join(f"{what} differs by {gap!r}" for what, gap in offending.items())
        raise SparseGateStatsError(
            "the extended percentiles contradict the frozen statistics they extend "
            f"({named}, tolerance {PERCENTILE_AGREEMENT_TOL!r}): one result may not publish "
            "two rows for one quantity"
        )


def gate_statistics(view: WindowView) -> GateStatistics:
    """Every per-gate statistic of one view, with its provenance.

    The five frozen names are :func:`gate_metrics`'s own, called on the same
    supported block this module extends, so the frozen floor and SA1's statistics
    cannot drift apart. The statistics are computed per gate and kept per gate: no
    reduction happens here.

    Args:
        view: one labelled :class:`WindowView`, built by :func:`primary_view`,
            :func:`full_record_view` or :func:`exploration_view`.

    Returns:
        One :class:`GateStatistics` with a row per :data:`GATE_STATISTICS` name and
        one column per supported gate.

    Raises:
        SparseGateStatsError: for an empty view or a non-finite sample.
    """
    mask = np.asarray(view.support_mask)
    supported = np.asarray(view.values, dtype=float)[:, mask]
    rows: dict[str, np.ndarray] = dict(gate_metrics(supported))
    rows.update(extended_gate_metrics(supported))
    _require_the_extended_percentiles_agree_with_the_frozen_pair(rows)
    names = GATE_STATISTICS
    return GateStatistics(
        statistic_names=names,
        units=tuple(statistic_units(name) for name in names),
        statistics=np.stack([np.asarray(rows[name], dtype=float) for name in names]),
        depths_mm=np.asarray(view.depths_mm, dtype=float)[mask],
        support_mask=mask,
        provenance=view_provenance(view),
        method=METHOD,
        percentile_method=PERCENTILE_METHOD,
        std_ddof=STD_DDOF,
        mad_scale=MAD_SCALE,
        mad_scaling=MAD_SCALING,
        excess_kurtosis_convention=EXCESS_KURTOSIS_CONVENTION,
        constant_trace_rule=CONSTANT_TRACE_RULE,
    )


def native_slab_weights(
    depths_mm: np.ndarray, *, support_mm: tuple[float, float]
) -> np.ndarray:
    """The share of the covered depth each participating gate speaks for.

    Cells are the intervals between neighbouring gate midpoints, the two end gates
    extending half a gap beyond themselves, and every cell is clipped to the required
    ``support_mm`` - so a gate the support only partly covers carries only the covered
    share, and a gate it does not reach at all is refused rather than handed a zero
    weight. The weights are read from the gates that are actually present, which is
    what makes the reduction gate-count-aware. On the uniform native grids this reader
    enforces with a support that lands on gate positions, each end cell is clipped to
    half a pitch while every interior cell keeps a whole one: the two ends carry half
    of an interior gate's weight. A single gate speaks for the whole of the support it
    covers, and for nothing when it lies outside it.

    Raises:
        SparseGateStatsError: for an empty or non-increasing native grid, a support
            that is not finite and increasing, or any gate covering no depth inside
            the support (a zero slab weight is not a weight).
    """
    low, high = require_depth_support(support_mm)
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    if depths.size == 0:
        raise SparseGateStatsError("native-slab weights need at least one gate")
    if depths.size > 1 and not np.all(np.diff(depths) > 0.0):
        raise SparseGateStatsError(
            "the native gate depths must increase strictly to carry slab weights; the "
            "instrument's native coordinate is never resorted"
        )
    if depths.size == 1:
        # One gate cannot take a pitch from its own grid: it speaks for the whole of the
        # support it sits in, which normalizes to 1, and for nothing at all otherwise.
        if not (low <= float(depths[0]) <= high):
            raise SparseGateStatsError(
                f"the single gate at {float(depths[0])!r} mm lies outside the support "
                f"[{low:g}, {high:g}] mm, so it covers no depth and carries no slab weight"
            )
        return np.ones(1)
    edges = np.empty(depths.size + 1)
    edges[1:-1] = 0.5 * (depths[:-1] + depths[1:])
    edges[0] = depths[0] - 0.5 * (depths[1] - depths[0])
    edges[-1] = depths[-1] + 0.5 * (depths[-1] - depths[-2])
    widths = np.clip(
        np.minimum(edges[1:], high) - np.maximum(edges[:-1], low), 0.0, None
    )
    uncovered = np.flatnonzero(widths <= 0.0)
    if uncovered.size:
        named = ", ".join(str(int(index)) for index in uncovered[:8])
        raise SparseGateStatsError(
            f"{uncovered.size} of {depths.size} gate(s) cover no depth inside the support "
            f"[{low:g}, {high:g}] mm (gate {named}); a slab weight is the share of the depth a "
            "gate speaks for, so a gate outside the support has no share and no weight - "
            "reduce over the supported gates, not the whole native grid"
        )
    total = float(widths.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise SparseGateStatsError(
            "these gates cover no depth inside the support, so they carry no slab weight"
        )
    return widths / total


def _reduce(
    values: np.ndarray,
    weights: np.ndarray,
    *,
    statistic: str,
    depths_mm: np.ndarray,
    weighting: str,
    weighting_rule: str,
    slab_support_mm: tuple[float, float] | None = None,
) -> DepthReduction:
    """One declared weighted mean of a per-gate statistic, refusing undefined input.
    """
    array = np.asarray(values, dtype=float).reshape(-1)
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    weights = np.asarray(weights, dtype=float).reshape(-1)
    if array.size == 0:
        raise SparseGateStatsError("a depth reduction needs at least one gate")
    if depths.size != array.size:
        raise SparseGateStatsError(
            f"a depth reduction needs one native depth per value, got {depths.size} depths for "
            f"{array.size} value(s)"
        )
    if depths.size > 1 and not np.all(np.diff(depths) > 0.0):
        raise SparseGateStatsError(
            "the native gate depths must increase strictly to be reduced over"
        )
    undefined = np.flatnonzero(~np.isfinite(array))
    if undefined.size:
        named = ", ".join(str(int(index)) for index in undefined[:8])
        raise SparseGateStatsError(
            f"the {statistic!r} statistic is not finite at {undefined.size} of {array.size} "
            f"gate(s) (gate {named}); an undefined statistic is not averaged away - exclude "
            "those gates explicitly, and report what the exclusion was"
        )
    return DepthReduction(
        statistic=statistic,
        units=statistic_units(statistic),
        value=float(np.sum(array * weights)),
        weighting=weighting,
        weighting_rule=weighting_rule,
        gates=int(array.size),
        weights=tuple(float(weight) for weight in weights),
        weight_sum=float(weights.sum()),
        gate_extent_mm=(float(depths.min()), float(depths.max())),
        slab_support_mm=slab_support_mm,
    )


def reduce_equal_weight(
    values: np.ndarray, *, statistic: str, depths_mm: np.ndarray
) -> DepthReduction:
    """One per-gate statistic reduced across depth with one vote per supported gate.

    The weighting is :data:`WEIGHTING_EQUAL`'s (:data:`WEIGHTING_EQUAL_RULE`): the
    rule the frozen table's ``supported_*`` cells use, so this scalar agrees with
    the table's own number rather than restating it.

    Args:
        values: the statistic's per-gate values.
        statistic: the statistic's name, for the result's provenance and units.
        depths_mm: the native gate depths of those values, one per value.

    Returns:
        A :class:`DepthReduction` whose ``weights`` are all ``1 / gates``.

    Raises:
        SparseGateStatsError: for an empty or mismatched input, a non-increasing
            native grid, or a value that is not finite.
    """
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        raise SparseGateStatsError("a depth reduction needs at least one gate")
    weights = np.full(array.size, 1.0 / array.size)
    return _reduce(
        array,
        weights,
        statistic=statistic,
        depths_mm=depths_mm,
        weighting=WEIGHTING_EQUAL,
        weighting_rule=WEIGHTING_EQUAL_RULE,
    )


def reduce_native_slab(
    values: np.ndarray,
    depths_mm: np.ndarray,
    *,
    statistic: str,
    support_mm: tuple[float, float],
) -> DepthReduction:
    """One per-gate statistic reduced across depth, weighted by the gates' own slab widths.

    The weighting is :data:`WEIGHTING_NATIVE_SLAB`'s
    (:data:`WEIGHTING_NATIVE_SLAB_RULE`): the share of the covered depth each
    participating gate speaks for, read from its own coordinates by
    :func:`native_slab_weights`. With a support that lands on gate positions the two
    end gates are clipped to half a cell each, so this reduction reproduces
    :func:`reduce_equal_weight` on a profile symmetric about the support centre and
    differs elsewhere by the end gates' share - a measured property, not an
    assumption, and the reason both weightings are offered with their weights.

    ``support_mm`` is required, and it is not a convenience: the clipping interval *is*
    the definition of this weighting. Without one, a uniform grid gives every gate an
    equal share, so the scalar would be the equal-weight number while the result
    declared the slab rule - a number labelled with a rule that did not apply.

    Raises:
        SparseGateStatsError: as :func:`reduce_equal_weight`, plus a support that
            is not finite and increasing, or any gate covering no depth inside it.
    """
    array = np.asarray(values, dtype=float).reshape(-1)
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    if array.size == 0:
        raise SparseGateStatsError("a depth reduction needs at least one gate")
    if depths.size != array.size:
        raise SparseGateStatsError(
            f"a depth reduction needs one native depth per value, got {depths.size} depths for "
            f"{array.size} value(s)"
        )
    weights = native_slab_weights(depths, support_mm=support_mm)
    return _reduce(
        array,
        weights,
        statistic=statistic,
        depths_mm=depths,
        weighting=WEIGHTING_NATIVE_SLAB,
        weighting_rule=WEIGHTING_NATIVE_SLAB_RULE,
        slab_support_mm=require_depth_support(support_mm),
    )
