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
  source identity, the *view* the numbers came from, the time and depth support
  they were computed on, and the method settings;
- three labelled views — :data:`VIEW_PRIMARY` (the pass's designed leading window
  cut by the recording's own stored stamps), :data:`VIEW_FULL_RECORD` (every
  stored profile) and :data:`VIEW_EXPLORATION` (explicitly selected bounds, which
  must never silently replace the primary comparison);
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

from udv_echo_process.analysis._native_grid import TOLERANCE_S, in_support
from udv_echo_process.analysis._sparse_pass import DecodedPoint, primary_window
from udv_echo_process.analysis.reference_repeat import METRICS as FROZEN_METRICS
from udv_echo_process.analysis.reference_repeat import gate_metrics
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field


class SparseGateStatsError(ValueError):
    """A per-gate statistic or a depth reduction cannot be computed as asked.

    Raised for an input that is not a ``(profiles, gates)`` window, a window with
    no profile or a gate with no sample, a non-finite sample, an undefined
    statistic entering a reduction, a reduction whose values and depths disagree,
    or an exploration bound outside the record it is taken from. The caller may
    catch this as the module's refusal and as a ``ValueError``.
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

MAD_SCALING = (
    "median absolute deviation of the gate's own trace about its own median, scaled by 1.4826 "
    "(the normal-consistency factor: on a normal sample the scaled value estimates the standard "
    "deviation). The unscaled statistic is mad_scaled / 1.4826."
)

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

#: The three views the plan distinguishes. The label is part of every result, so a
#: reader can never mistake an exploratory selection for the primary comparison.
VIEW_PRIMARY = "primary-comparison"
VIEW_FULL_RECORD = "full-record"
VIEW_EXPLORATION = "exploration"
VIEW_LABELS: tuple[str, ...] = (VIEW_PRIMARY, VIEW_FULL_RECORD, VIEW_EXPLORATION)

VIEW_RULES: dict[str, str] = {
    VIEW_PRIMARY: (
        "the pass's designed leading window, cut by the recording's own stored timestamps: the "
        "primary-comparison view. It is never widened to the instrument's retained extra fraction "
        "of a second, and an exploratory selection never replaces it."
    ),
    VIEW_FULL_RECORD: (
        "every stored profile of the recording, for stationarity, ACF and spectral diagnostics: "
        "the full-record view, labelled separately from the primary comparison because its "
        "duration varies between recordings."
    ),
    VIEW_EXPLORATION: (
        "explicitly selected time and depth bounds: the exploration view. It is a labelled "
        "exploratory selection and must never silently replace the primary-comparison view."
    ),
}

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
      interpolation, the same convention the frozen ``iqr`` uses, so ``q50`` is
      the frozen ``median`` and ``q75 - q25`` is the frozen ``iqr``;
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
        array, [5.0, 25.0, 50.0, 75.0, 95.0], axis=0
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


class WindowView(ArrayModel):
    """One recording as one *view*: its samples, their native coordinates and its support mask.

    ``values`` is ``(profiles, gates)`` in ``mm/s``; ``time_s`` are the view's own
    stored timestamps in seconds, ``depths_mm`` the native gate depths in mm - the
    instrument's own coordinate, never relabelled or converted; ``support_mask``
    marks the gates inside the pass's common physical support. ``start_index`` and
    ``stop_index`` are the view's positions in the recording's stored profile
    axis, so the cut is auditable. ``declared_window_s`` records the interval that
    was *asked for* when it differs from the span the stored stamps achieve.
    """

    view: str
    view_rule: str
    relative_path: str
    source_sha256: str
    job: str
    point_label: str
    order: int
    values: array_field(np.float64, rank=2)
    time_s: array_field(np.float64, rank=1)
    depths_mm: array_field(np.float64, rank=1)
    support_mask: array_field(np.bool_, rank=1)
    start_index: int
    stop_index: int
    window_start_s: float
    window_end_s: float
    window_s: float
    support_mm: tuple[float, float]
    declared_window_s: float | None = None
    time_bounds_s: tuple[float, float] | None = None
    depth_bounds_mm: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _check_the_view_is_one_contiguous_supported_block(self) -> WindowView:
        if self.view not in VIEW_LABELS:
            raise ValueError(
                f"a view label is one of {list(VIEW_LABELS)}, got {self.view!r}"
            )
        if self.values.shape != (self.time_s.size, self.depths_mm.size):
            raise ValueError(
                f"the view's values {self.values.shape} must hold one sample per profile "
                f"and gate ({self.time_s.size}, {self.depths_mm.size})"
            )
        if self.values.shape[0] < 1 or self.values.shape[1] < 1:
            raise ValueError("a view holds at least one profile and one gate")
        if self.support_mask.shape != self.depths_mm.shape:
            raise ValueError(
                f"the support mask {self.support_mask.shape} must have one entry per native "
                f"gate {self.depths_mm.shape}"
            )
        if not np.any(self.support_mask):
            raise ValueError(
                "no native gate of this view lies inside the common support "
                f"[{self.support_mm[0]:g}, {self.support_mm[1]:g}] mm, so it cannot enter a "
                "depth-resolved comparison"
            )
        if self.stop_index - self.start_index != self.values.shape[0] or self.start_index < 0:
            raise ValueError(
                f"a view is one contiguous run of stored profiles: [{self.start_index}, "
                f"{self.stop_index}) does not hold {self.values.shape[0]} profile(s)"
            )
        steps = np.diff(self.time_s)
        if self.time_s.size > 1 and not np.all(steps >= 0.0):
            raise ValueError("the view's stored timestamps must not decrease")
        if self.depths_mm.size > 1 and not np.all(np.diff(self.depths_mm) > 0.0):
            raise ValueError(
                "the view's native gate depths must increase strictly; the instrument's native "
                "coordinate is preserved, never relabelled or resorted"
            )
        if not math.isclose(
            self.window_start_s, float(self.time_s[0]), abs_tol=TOLERANCE_S
        ) or not math.isclose(
            self.window_end_s, float(self.time_s[-1]), abs_tol=TOLERANCE_S
        ):
            raise ValueError(
                "the window's start/end must be the view's own first and last stored timestamp"
            )
        if not math.isclose(
            self.window_s,
            self.window_end_s - self.window_start_s,
            abs_tol=TOLERANCE_S,
        ):
            raise ValueError(
                "the window's duration must be the span of the stamps it was cut on, so a "
                "declared interval cannot be reported as achieved"
            )
        return self


class ViewProvenance(ValueModel):
    """What a result was computed from, and with which settings.

    Source identity (``relative_path``, ``source_sha256``, ``job``,
    ``point_label``, ``order``), the view and its rule, the time and depth support
    the numbers were computed on, and the estimator settings - so a result can be
    audited without the notebook that displayed it.
    """

    view: str
    view_rule: str
    relative_path: str
    source_sha256: str
    job: str
    point_label: str
    order: int
    start_index: int
    stop_index: int
    profiles: int
    native_gates: int
    supported_gates: int
    window_start_s: float
    window_end_s: float
    window_s: float
    support_mm: tuple[float, float]
    depth_support_mm: tuple[float, float]
    declared_window_s: float | None = None
    time_bounds_s: tuple[float, float] | None = None
    depth_bounds_mm: tuple[float, float] | None = None
    method: str
    percentile_method: str
    std_ddof: int
    mad_scale: float
    mad_scaling: str
    excess_kurtosis_convention: str
    constant_trace_rule: str

    @model_validator(mode="after")
    def _check_the_support_is_measured_not_claimed(self) -> ViewProvenance:
        if self.supported_gates < 1 or self.supported_gates > self.native_gates:
            raise ValueError(
                f"{self.supported_gates} supported gate(s) out of {self.native_gates} is not a "
                "support this result could have been computed on"
            )
        if self.profiles < 1 or self.stop_index - self.start_index != self.profiles:
            raise ValueError("the provenance's profile count must be the view's own")
        if self.depth_support_mm[0] >= self.depth_support_mm[1] and self.supported_gates > 1:
            raise ValueError(
                "the supported depth range must be increasing when more than one gate is supported"
            )
        return self


class GateStatistics(ArrayModel):
    """Every per-gate statistic of one :class:`WindowView`.

    ``statistics`` is ``(len(statistic_names), gates)``: one row per name in
    :data:`GATE_STATISTICS`, in that order, one column per *supported* gate, in the
    recording's native depth order - so the profiles are kept, per gate, and no
    reduction has happened yet. ``units`` is aligned with ``statistic_names``, and
    ``support_mask`` is the full-length native mask the columns were selected by.
    """

    statistic_names: tuple[str, ...]
    units: tuple[str, ...]
    statistics: array_field(np.float64, rank=2)
    depths_mm: array_field(np.float64, rank=1)
    support_mask: array_field(np.bool_, rank=1)
    provenance: ViewProvenance

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
    """

    statistic: str
    units: str
    value: float
    weighting: str
    weighting_rule: str
    gates: int
    weights: tuple[float, ...]
    weight_sum: float
    depth_support_mm: tuple[float, float]

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
        return self


def _identity_cells(point: DecodedPoint) -> dict[str, object]:
    """The source-identity cells every view of one recording repeats.
    """
    return {
        "relative_path": str(point.relative_path),
        "source_sha256": str(point.source_sha256),
        "job": str(point.binding.job.job),
        "point_label": str(point.binding.point.label),
        "order": int(point.binding.order),
    }


def _window_view(
    point: DecodedPoint,
    *,
    view: str,
    values: np.ndarray,
    time_s: np.ndarray,
    depths: np.ndarray,
    start_index: int,
    stop_index: int,
    support_mm: tuple[float, float],
    declared_window_s: float | None = None,
    time_bounds_s: tuple[float, float] | None = None,
    depth_bounds_mm: tuple[float, float] | None = None,
) -> WindowView:
    """Assemble one labelled view, with the support mask the pass's shared view gives it.
    """
    stamps = np.asarray(time_s, dtype=float)
    grid = np.asarray(depths, dtype=float)
    return WindowView(
        view=view,
        view_rule=VIEW_RULES[view],
        **_identity_cells(point),
        values=np.asarray(values, dtype=float),
        time_s=stamps,
        depths_mm=grid,
        support_mask=in_support(grid, support_mm),
        start_index=int(start_index),
        stop_index=int(stop_index),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
        support_mm=(float(support_mm[0]), float(support_mm[1])),
        declared_window_s=declared_window_s,
        time_bounds_s=time_bounds_s,
        depth_bounds_mm=depth_bounds_mm,
    )


def primary_view(
    point: DecodedPoint, *, window_s: float, support_mm: tuple[float, float]
) -> WindowView:
    """One recording's primary-comparison view: the leading ``window_s``, cut by its own stamps.

    The cut is the pass's shared view (``_sparse_pass.primary_window``), so a
    notebook and a floor compute over the same interval: the designed exposure,
    never the instrument's retained surplus - which is why ``declared_window_s``
    (the interval asked for) and ``window_s`` (the span the stamps achieve) are
    both recorded and the view's end can only fall at or below the declared one.

    Raises:
        SparseGateStatsError: for a window that is not finite and positive, or a
            recording whose stamps cover no profile of the designed interval.
    """
    if not math.isfinite(window_s) or window_s <= 0.0:
        raise SparseGateStatsError(
            f"a primary window must be finite and positive, got {window_s!r}"
        )
    block = primary_window(point, window_s)
    profiles = int(block.shape[0])
    if profiles < 1:
        raise SparseGateStatsError(
            f"{point.relative_path}: no stored profile falls inside the designed "
            f"{window_s:g} s primary window; this recording cannot enter the primary comparison"
        )
    stamps = np.asarray(point.time_s, dtype=float)[:profiles]
    return _window_view(
        point,
        view=VIEW_PRIMARY,
        values=block,
        time_s=stamps,
        depths=np.asarray(point.depths, dtype=float),
        start_index=0,
        stop_index=profiles,
        support_mm=support_mm,
        declared_window_s=float(window_s),
    )


def full_record_view(
    point: DecodedPoint, *, support_mm: tuple[float, float]
) -> WindowView:
    """One recording's full-record view: every stored profile, labelled separately.

    The primary comparison is not replaced by this view: the plan reserves it for
    ACF, spectra and stationarity diagnostics, where the duration may vary between
    recordings and is therefore its own label rather than a shared interval.
    """
    values = np.asarray(point.values, dtype=float)
    stamps = np.asarray(point.time_s, dtype=float)
    return _window_view(
        point,
        view=VIEW_FULL_RECORD,
        values=values,
        time_s=stamps,
        depths=np.asarray(point.depths, dtype=float),
        start_index=0,
        stop_index=int(values.shape[0]),
        support_mm=support_mm,
    )


def exploration_view(
    point: DecodedPoint,
    *,
    time_bounds_s: tuple[float, float],
    depth_bounds_mm: tuple[float, float],
    support_mm: tuple[float, float],
) -> WindowView:
    """One recording's exploration view: explicitly selected time and depth bounds.

    The selection is by index on the recording's own monotone stamps and increasing
    native gate grid, so the view stays one contiguous supported block and the
    native depth coordinate is preserved. Bounds must lie inside the stored record
    and select at least one supported gate: an exploratory selection may not widen
    the record it came from, and this view is labelled so it can never be mistaken
    for the primary comparison.

    Raises:
        SparseGateStatsError: for bounds that are not finite and increasing, that
            reach outside the stored record, or that select no supported gate.
    """
    stamps = np.asarray(point.time_s, dtype=float)
    grid = np.asarray(point.depths, dtype=float)
    values = np.asarray(point.values, dtype=float)
    low_s, high_s = _require_bounds(time_bounds_s, what="time")
    low_mm, high_mm = _require_bounds(depth_bounds_mm, what="depth")
    if low_s < float(stamps[0]) - TOLERANCE_S or high_s > float(stamps[-1]) + TOLERANCE_S:
        raise SparseGateStatsError(
            f"{point.relative_path}: the exploratory time bounds [{low_s:g}, {high_s:g}] s "
            f"reach outside the stored record [{float(stamps[0]):g}, "
            f"{float(stamps[-1]):g}] s; a selection is taken from the record, never widened"
        )
    if low_mm < float(grid[0]) - TOLERANCE_S or high_mm > float(grid[-1]) + TOLERANCE_S:
        raise SparseGateStatsError(
            f"{point.relative_path}: the exploratory depth bounds [{low_mm:g}, {high_mm:g}] mm "
            f"reach outside the stored native grid [{float(grid[0]):g}, {float(grid[-1]):g}] mm"
        )
    inside_time = np.flatnonzero(
        (stamps >= low_s - TOLERANCE_S) & (stamps <= high_s + TOLERANCE_S)
    )
    if inside_time.size == 0:
        raise SparseGateStatsError(
            f"{point.relative_path}: no stored profile falls inside [{low_s:g}, {high_s:g}] s"
        )
    inside_depth = np.flatnonzero(
        (grid >= low_mm - TOLERANCE_S) & (grid <= high_mm + TOLERANCE_S)
    )
    mask = (
        in_support(grid[inside_depth], support_mm)
        if inside_depth.size
        else np.zeros(0, bool)
    )
    if not np.any(mask):
        raise SparseGateStatsError(
            f"{point.relative_path}: no native gate inside [{low_mm:g}, {high_mm:g}] mm lies "
            f"inside the common support [{support_mm[0]:g}, {support_mm[1]:g}] mm; this "
            "selection cannot enter a depth-resolved comparison"
        )
    gates = inside_depth[mask]
    start_index, stop_index = int(inside_time[0]), int(inside_time[-1]) + 1
    return _window_view(
        point,
        view=VIEW_EXPLORATION,
        values=values[start_index:stop_index][:, gates],
        time_s=stamps[start_index:stop_index],
        depths=grid[gates],
        start_index=start_index,
        stop_index=stop_index,
        support_mm=support_mm,
        time_bounds_s=(low_s, high_s),
        depth_bounds_mm=(low_mm, high_mm),
    )


def _require_bounds(bounds: tuple[float, float], *, what: str) -> tuple[float, float]:
    """One pair of explicit bounds, refused unless finite and increasing.
    """
    low, high = float(bounds[0]), float(bounds[1])
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        raise SparseGateStatsError(
            f"the {what} bounds must be finite and increasing, got ({low!r}, {high!r})"
        )
    return low, high


def view_provenance(view: WindowView) -> ViewProvenance:
    """The provenance record of one view: its identity, support and method settings.

    The depth support is *measured* from the view's own supported native gates, not
    copied from the pass's declared range, so a reader can see which depths the
    numbers actually cover.
    """
    supported = np.flatnonzero(view.support_mask)
    depths = np.asarray(view.depths_mm, dtype=float)[supported]
    return ViewProvenance(
        view=view.view,
        view_rule=view.view_rule,
        relative_path=view.relative_path,
        source_sha256=view.source_sha256,
        job=view.job,
        point_label=view.point_label,
        order=view.order,
        start_index=view.start_index,
        stop_index=view.stop_index,
        profiles=int(view.values.shape[0]),
        native_gates=int(view.depths_mm.size),
        supported_gates=int(supported.size),
        window_start_s=view.window_start_s,
        window_end_s=view.window_end_s,
        window_s=view.window_s,
        support_mm=view.support_mm,
        depth_support_mm=(float(depths.min()), float(depths.max())),
        declared_window_s=view.declared_window_s,
        time_bounds_s=view.time_bounds_s,
        depth_bounds_mm=view.depth_bounds_mm,
        method=METHOD,
        percentile_method="linear",
        std_ddof=0,
        mad_scale=MAD_SCALE,
        mad_scaling=MAD_SCALING,
        excess_kurtosis_convention=EXCESS_KURTOSIS_CONVENTION,
        constant_trace_rule=CONSTANT_TRACE_RULE,
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
    names = GATE_STATISTICS
    return GateStatistics(
        statistic_names=names,
        units=tuple(statistic_units(name) for name in names),
        statistics=np.stack([np.asarray(rows[name], dtype=float) for name in names]),
        depths_mm=np.asarray(view.depths_mm, dtype=float)[mask],
        support_mask=mask,
        provenance=view_provenance(view),
    )


def native_slab_weights(
    depths_mm: np.ndarray, *, support_mm: tuple[float, float] | None = None
) -> np.ndarray:
    """The share of the depth support each participating gate speaks for.

    Cells are the intervals between neighbouring gate midpoints, the two end gates
    extending half a gap beyond themselves, and every cell is clipped to
    ``support_mm`` when one is given - so a gate the support only partly covers
    carries only the covered share. The weights are read from the gates that are
    actually present, which is what makes the reduction gate-count-aware. On the
    uniform native grids this reader enforces with a support that lands on gate
    positions, each end cell is clipped to half a pitch while every interior cell
    keeps a whole one: the two ends carry half of an interior gate's weight. A
    single gate speaks for the whole of whatever support it covers.

    Raises:
        SparseGateStatsError: for an empty or non-increasing native grid, bounds
            that are not finite and increasing, or gates covering no depth inside
            the support.
    """
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    if depths.size == 0:
        raise SparseGateStatsError("native-slab weights need at least one gate")
    if depths.size > 1 and not np.all(np.diff(depths) > 0.0):
        raise SparseGateStatsError(
            "the native gate depths must increase strictly to carry slab weights; the "
            "instrument's native coordinate is never resorted"
        )
    if depths.size == 1:
        return np.ones(1)
    edges = np.empty(depths.size + 1)
    edges[1:-1] = 0.5 * (depths[:-1] + depths[1:])
    edges[0] = depths[0] - 0.5 * (depths[1] - depths[0])
    edges[-1] = depths[-1] + 0.5 * (depths[-1] - depths[-2])
    widths = np.diff(edges)
    if support_mm is not None:
        low, high = _require_bounds(
            (float(support_mm[0]), float(support_mm[1])), what="depth"
        )
        widths = np.clip(
            np.minimum(edges[1:], high) - np.maximum(edges[:-1], low), 0.0, None
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
        depth_support_mm=(float(depths.min()), float(depths.max())),
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
    support_mm: tuple[float, float] | None = None,
) -> DepthReduction:
    """One per-gate statistic reduced across depth, weighted by the gates' own slab widths.

    The weighting is :data:`WEIGHTING_NATIVE_SLAB`'s
    (:data:`WEIGHTING_NATIVE_SLAB_RULE`): the share of the analysed support each
    participating gate covers, read from its own coordinates by
    :func:`native_slab_weights`. With a support that lands on gate positions the
    two end gates are clipped to half a cell each, so this reduction reproduces
    :func:`reduce_equal_weight` on a profile symmetric about the support centre and
    differs elsewhere by the end gates' share - a measured property, not an
    assumption, and the reason both weightings are offered with their weights.

    Raises:
        SparseGateStatsError: as :func:`reduce_equal_weight`, plus a support that
            is not finite and increasing or covers none of the given gates.
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
    )
