"""SA5's per-record metric profiles, read from one :class:`WindowView` (prespec §"Named observables").

SA5's matrix is *setting contrast × observable × physical depth × sitting*, and its first
step - before any contrast, depth reduction or agreement summary - is one scalar per
``(recording, view, metric, native gate)``: ``M_record(z)`` "computed once on that
recording's declared view at its supported native gates; no pooling of time samples across
recordings" (prespec, "Oriented within-sitting contrasts"). This module is that step, and
only that step.

What it is
----------
:func:`read_metric_profile` reads the named observables the prespec keeps from the frozen
slices, one metric at a time, from one labelled view:

- :data:`MetricName.MEAN`, :data:`MetricName.STD`, :data:`MetricName.MAD_SCALED` - SA1's
  per-gate ``mean``/``std``/``mad_scaled`` rows, on the declared
  :data:`~udv_echo_process.analysis._sparse_view.SparseView.PRIMARY` view;
- :data:`MetricName.RECURRENCE_1E_LAG` and :data:`MetricName.RECURRENCE_PEAK_LAG` - SA1's
  *supported* 1/e decay lag and its descriptive recurrence-peak lag, in seconds, on a named
  ``primary-comparison`` or ``full-record`` view;
- :data:`MetricName.PHI` - SA2.4's ``band_fraction`` Φ for the fixed closed ``[0, low_hz]``
  Hz band, dimensionless, on either of those two views.

It computes **no estimator**. Every number is read from an object that already owns it:
:func:`~udv_echo_process.analysis.sparse_gate_stats.gate_statistics` for the three SA1 rows,
:func:`~udv_echo_process.analysis.sparse_recurrence.recurrence_of_view` for the two
recurrence lag scalars, and
:func:`~udv_echo_process.analysis.sparse_spectral_characterization.characterization_of_view`
for Φ. No transform, taper, grid, admission rule, threshold, verdict or reduction is added
here, and the constants the backends own (``MAD_SCALE``, the 1/e target, the weak-peak
threshold, the band's three states) are imported rather than restated.

What a profile keeps
--------------------
One :class:`MetricProfile` is a typed, scalar-only record of one view:

- its **metric**, its **units**, its **view** label and that view's own rule text;
- its **provenance** - the same
  :class:`~udv_echo_process.analysis._sparse_view.ViewProvenance` every sparse slice carries
  (source digest, job, point, order, the three depth extents, the windows), so a metric
  profile cannot be anonymous about which recording it came from or which cut it was read
  on;
- one :class:`GateMetric` **per supported gate**, in native depth order, each carrying its
  own column index within the view (and its ``depth_mm`` on the recording's native grid), a
  :class:`MetricState` and - where it has one - its value. **Every undefined or refused gate
  keeps its own state and its own reason**,
  copied from the backend that refused it: a constant trace's undefined autocorrelation, a
  1/e decay the lag range never reached, an admitted axis whose total power is exactly zero,
  an axis the admission declined. A refusal is never published as ``0.0``, and a defined
  zero is never published as a refusal;
- the **settings** the numbers were made under, as named scalar rows read from the same
  backend objects (the ACF estimator name, the lag resolution, the timebase verdict, the MAD
  scale, the band edge, the taper, ``Δf``, Nyquist, the effective rate, ...). A setting the
  backend itself carries as ``None`` - an axis that does not define it - is kept as ``None``,
  never as a fabricated zero.

Three invariants are asserted rather than assumed
-------------------------------------------------
- **One view is one axis.** The recurrence metrics read the timebase, the lag resolution and
  the frequency resolution off *every* gate's result and refuse the profile if two gates of
  one view disagree; the spectral slice's cell model already holds one cell to one admission,
  and this module reads that cell's own axis.
- **The label and the provenance are one cut.** A profile's view label is the provenance's
  own, its supported-gate row count is the provenance's ``supported_gates``, and its
  participating depths are the first and last of those rows, so a metric profile cannot quote
  one view's identity beside another view's numbers. The two views are never exchanged in one
  profile: a profile names exactly one, and :data:`ALLOWED_VIEWS` refuses a metric on a view
  the prespec does not declare for it (a fluctuation scale on the full record, anything on an
  exploratory cut).
- **No array is serialized.** A profile holds scalars and per-gate rows only - no ndarray
  field, no PSD, no ACF curve, no gate vector - so it round-trips through
  ``model_dump(mode="json")`` and :meth:`MetricProfile.json_text` refuses a non-finite value
  instead of emitting invalid JSON. The curves and spectra stay on the backend results they
  were computed on.

What is deliberately absent
---------------------------
No contrast, no depth reduction, no E20 four-run mean, no repeat spread, no floor, no
agreement number and no cross-sitting arithmetic of any kind: those are later SA5 artefacts
and each needs its own common-support and same-condition argument. Nothing here pools time
samples, gates or recordings, and no field is an uncertainty - profiles and gates inside one
recording are correlated observations, not independent replicates.
"""

from __future__ import annotations

import json
import math
from enum import Enum
from itertools import pairwise

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._sparse_view import (
    VIEW_RULES,
    SparseView,
    SparseViewError,
    ViewProvenance,
    WindowView,
    view_provenance,
)
from udv_echo_process.analysis.sparse_gate_stats import MAD_SCALE, gate_statistics
from udv_echo_process.analysis.sparse_recurrence import (
    Detrending,
    RecurrencePeak,
    RecurrenceVerdict,
    recurrence_of_view,
)
from udv_echo_process.analysis.sparse_spectral_characterization import (
    DEFAULT_LOW_HZ,
    BandFractionState,
    characterization_of_view,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ALLOWED_VIEWS",
    "METHOD",
    "METRICS",
    "METRIC_RULES",
    "METRIC_UNITS",
    "PRIMARY_METRICS",
    "RECURRENCE_METRICS",
    "RECURRENCE_PEAK_RULE",
    "SPECTRAL_METRICS",
    "STATE_MEANING",
    "GateMetric",
    "MetricName",
    "MetricProfile",
    "MetricSetting",
    "MetricState",
    "SparseSa5MetricsError",
    "allowed_views",
    "metric_rule",
    "metric_units",
    "read_metric_profile",
    "recurrence_peak_lag",
]


class SparseSa5MetricsError(SparseViewError):
    """A metric profile cannot be read from this view as asked.

    Raised for a metric this module does not define, a metric asked for on a view the
    prespec does not declare it on, an unknown detrending, a recurrence lag domain asked for
    beside a metric that has none, and a view whose own gates disagree about the axis they
    were measured on. A *refused measurement* - a constant trace, an unsupported 1/e decay,
    a declined spectral axis - is not this error: it is a typed :class:`MetricState` on the
    gate's own row. It is a subclass of
    :class:`~udv_echo_process.analysis._sparse_view.SparseViewError`, and therefore a
    ``ValueError``, so a caller may catch the whole sparse-view refusal.
    """


class MetricName(str, Enum):
    """The SA5 observables this module reads, one per prespec bullet.

    A ``str`` enum, so a member compares equal to its own label and a report can quote one
    without translation. Membership is :data:`METRICS`.
    """

    #: SA1's per-gate time mean, in ``mm/s`` - the signed profile (prespec observable 1).
    MEAN = "mean"
    #: SA1's per-gate population standard deviation, in ``mm/s`` - fluctuation scale.
    STD = "std"
    #: SA1's per-gate 1.4826-scaled median absolute deviation, in ``mm/s``.
    MAD_SCALED = "mad_scaled"
    #: SA1's supported 1/e decay lag of the trace ACF, in seconds - recurrence.
    RECURRENCE_1E_LAG = "recurrence-1e-lag"
    #: SA1's descriptive recurrence-peak lag, in seconds - never a period claim.
    RECURRENCE_PEAK_LAG = "recurrence-peak-lag"
    #: SA2.4's ``band_fraction`` Φ, dimensionless - spectral allocation.
    PHI = "band_fraction"


#: The fluctuation-scale observables, declared on the primary-comparison view only
#: (prespec observable 2 uses one view on both sides of a contrast).
PRIMARY_METRICS: tuple[MetricName, ...] = (
    MetricName.MEAN,
    MetricName.STD,
    MetricName.MAD_SCALED,
)

#: The recurrence observables. The prespec keeps recurrence on a named view and permits the
#: separately labelled full record beside the primary comparison; the two are never mixed in
#: one profile.
RECURRENCE_METRICS: tuple[MetricName, ...] = (
    MetricName.RECURRENCE_1E_LAG,
    MetricName.RECURRENCE_PEAK_LAG,
)

#: The spectral-allocation observable, on the same two named views.
SPECTRAL_METRICS: tuple[MetricName, ...] = (MetricName.PHI,)

#: Every metric this module reads, in the prespec's observable order.
METRICS: tuple[MetricName, ...] = (
    PRIMARY_METRICS + RECURRENCE_METRICS + SPECTRAL_METRICS
)

#: Which views each metric may be read on, given as the prespec declares them. A metric on a
#: view outside its own tuple is refused rather than computed: an exploratory cut is not the
#: prespecified table, and a fluctuation scale is not declared on the full record.
ALLOWED_VIEWS: dict[MetricName, tuple[SparseView, ...]] = {
    MetricName.MEAN: (SparseView.PRIMARY,),
    MetricName.STD: (SparseView.PRIMARY,),
    MetricName.MAD_SCALED: (SparseView.PRIMARY,),
    MetricName.RECURRENCE_1E_LAG: (SparseView.PRIMARY, SparseView.FULL_RECORD),
    MetricName.RECURRENCE_PEAK_LAG: (SparseView.PRIMARY, SparseView.FULL_RECORD),
    MetricName.PHI: (SparseView.PRIMARY, SparseView.FULL_RECORD),
}

#: Each metric's unit, as its profile carries it. ``s`` for a lag in seconds and
#: ``dimensionless`` for a fraction - a Φ difference is a dimensionless difference, never a
#: relative percentage gain.
METRIC_UNITS: dict[MetricName, str] = {
    MetricName.MEAN: "mm/s",
    MetricName.STD: "mm/s",
    MetricName.MAD_SCALED: "mm/s",
    MetricName.RECURRENCE_1E_LAG: "s",
    MetricName.RECURRENCE_PEAK_LAG: "s",
    MetricName.PHI: "dimensionless",
}

#: The rule :func:`read_metric_profile` executes, stated once. It names the backends so a
#: reader cannot mistake this module for a second estimator.
METHOD = (
    "one scalar per (recording, view, metric, supported native gate), read from the frozen "
    "slices and never recomputed here: mean/std/mad_scaled from "
    "sparse_gate_stats.gate_statistics (SA1's frozen gate_metrics row plus its extended "
    "rows), recurrence-1e-lag and recurrence-peak-lag from "
    "sparse_recurrence.recurrence_of_view on the gate's own trace, and band_fraction from "
    "sparse_spectral_characterization.characterization_of_view. One view is one axis, no "
    "time sample, gate or recording is pooled, and no contrast, reduction, floor or "
    "cross-sitting arithmetic is performed."
)

#: The recurrence-peak-lag rule, stated because a peak is descriptive and must not be read
#: as a period or as a floor.
RECURRENCE_PEAK_RULE = (
    "the descriptive recurrence-peak lag of one gate: the lag of the *admissible* peak of "
    "the gate's normalized ACF - a peak that is not weak (its correlation is above the "
    "estimator's weak-peak threshold) and that the autocorrelation had fallen below that "
    "threshold before, so a shoulder riding a still-correlated plateau is not one - choosing "
    "the largest correlation and, on a tie, the smaller lag. Where no peak is admissible the "
    "quantity is undefined with the estimator's own peaks_reason and carries no number. The "
    "lag is descriptive: no period is claimed from it, and the prespec's prohibition on "
    "declaring an approximately 1 s physical period from a descriptive peak is inherited "
    "here."
)

#: Each metric's definition, as the profile's documented rule text. These are *references* to
#: the backend definitions, not restatements of their arithmetic.
METRIC_RULES: dict[MetricName, str] = {
    MetricName.MEAN: (
        "the gate's own time mean of the view's stored velocity samples in mm/s: SA1's "
        "frozen gate_metrics 'mean' row, computed once per supported native gate on the "
        "recording's declared view. Reused, never recomputed."
    ),
    MetricName.STD: (
        "the gate's own population standard deviation (ddof=0) about its own mean, in mm/s: "
        "SA1's extended 'std' row. A single-profile or constant gate scores exactly 0.0, "
        "which is what population moments give for a constant sample."
    ),
    MetricName.MAD_SCALED: (
        "the gate's own median absolute deviation about its own median, scaled by "
        f"{MAD_SCALE} (the normal-consistency factor), in mm/s: SA1's extended "
        "'mad_scaled' row."
    ),
    MetricName.RECURRENCE_1E_LAG: (
        "SA1's supported 1/e decay lag of the gate's mean-detrended normalized "
        "autocorrelation, in seconds: the lag at which the ACF has fallen to 1/e, "
        "interpolated on the estimator's own lag grid. It is reported only where the lag "
        "range reaches it; an effectively constant trace has no normalized autocorrelation "
        "at all, so the quantity is undefined there - never a substituted zero."
    ),
    MetricName.RECURRENCE_PEAK_LAG: RECURRENCE_PEAK_RULE,
    MetricName.PHI: (
        "SA2.4's band_fraction Φ for the fixed closed [0, low_hz] Hz band, dimensionless: "
        "B / T with B the cell-overlap-weighted band power of the gate's admitted "
        "uniform-grid periodogram and T its own integrated power. The three states are "
        "preserved per gate - defined, defined-zero-power (a constant gate: a measurement, "
        "with an undefined 0/0 fraction) and refused-axis (nothing measured) - and a missing "
        "fraction is never a zero."
    ),
}


class MetricState(str, Enum):
    """Whether one gate's metric was measured, was measured as a zero, or was not measured.

    Every state is the *backend's own* vocabulary where the backend has one - the two
    refusal labels below are literally :class:`BandFractionState`'s and
    :class:`RecurrenceVerdict`'s values - so a gate row cannot invent a state its estimator
    never produced. Membership is the type's own validity rule.
    """

    #: Measured: the row carries a finite value.
    DEFINED = "defined"
    #: The axis was admitted and its total power is exactly zero (a constant gate): a
    #: measurement, whose fraction is undefined (0 / 0) and carried as no value.
    DEFINED_ZERO_POWER = BandFractionState.DEFINED_ZERO_POWER.value
    #: The admission declined the axis: nothing was measured, and no zero is synthesized.
    REFUSED_AXIS = BandFractionState.REFUSED_AXIS.value
    #: The trace is constant (or effectively so): its normalized autocorrelation is
    #: undefined, so no recurrence quantity exists on it.
    UNDEFINED_CONSTANT_TRACE = RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE.value
    #: The estimator ran and the quantity is not defined on this trace's own support: a 1/e
    #: decay the lag range never reached, or a trace with no admissible recurrence peak.
    UNDEFINED_NOT_SUPPORTED = "undefined-not-supported"
    #: The estimator returned no usable scalar for this gate (a non-finite or absent
    #: estimate). Named rather than shown as a zero.
    UNDEFINED_NO_ESTIMATE = "undefined-no-estimate"


#: What the states mean, so a reader of one row cannot conflate them. The three spectral
#: states keep SA2.4's own meanings; the recurrence ones keep the estimator's verdicts.
STATE_MEANING = (
    "defined: the metric was measured and the row carries a finite value. "
    "defined-zero-power: the spectral axis was admitted and the window-normalized mean "
    "square power is exactly zero - a constant gate, which is a measurement - so the "
    "fraction is undefined (0 / 0) and no value is carried. refused-axis: the admission "
    "declined the axis, so nothing was measured and no zero is synthesized. "
    "undefined-constant-trace: the gate's trace is constant to within its own scale, so its "
    "normalized autocorrelation does not exist. undefined-not-supported: the estimator ran "
    "and the quantity is not defined on this trace's own support (a 1/e decay the lag range "
    "never reached, or no admissible recurrence peak). undefined-no-estimate: the backend "
    "carried no usable scalar for this gate. A refused or unsupported measurement is never "
    "published as 0.0, and a defined zero is never published as a refusal."
)


class MetricSetting(ValueModel):
    """One named scalar setting the metric's numbers were produced under.

    ``value`` is ``float | int | str | bool | None``: a scalar the backend itself carries,
    and ``None`` exactly where that backend carries ``None`` (the axis does not define it).
    A fabricated ``0.0`` for a setting an axis does not have is the substitution every sparse
    slice refuses, so it is refused here too. A list or an array is not a setting value.
    """

    name: str
    value: float | int | str | bool | None

    @model_validator(mode="after")
    def _check_the_setting_is_one_named_scalar(self) -> MetricSetting:
        if not self.name.strip():
            raise ValueError("every setting states its name")
        if self.value is not None and not isinstance(
            self.value, (bool, int, float, str)
        ):
            raise ValueError(
                f"the setting {self.name!r} must be a scalar, got {type(self.value).__name__}: "
                "a profile serializes scalars, never an array"
            )
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError(
                f"the setting {self.name!r} states its value or carries None"
            )
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError(
                f"the setting {self.name!r} must be finite, got {self.value!r}: an undefined "
                "setting is carried as None rather than as a non-finite number"
            )
        return self


class GateMetric(ValueModel):
    """One native gate's value of one metric, with its own state and reason.

    ``value`` is not ``None`` exactly when :attr:`state` is
    :data:`MetricState.DEFINED`, so a reader can never mistake an undefined or refused gate
    for a measured zero. ``reason`` states what the row is in words; for an undefined or
    refused row it is the *backend's own* reason (the constant-trace message, the supported
    quantity's reason, the admission's own reason), copied rather than summarised.
    """

    gate_index: int
    depth_mm: float
    state: MetricState
    value: float | None
    reason: str

    @model_validator(mode="after")
    def _check_the_value_is_the_state_it_carries(self) -> GateMetric:
        if self.gate_index < 0:
            raise ValueError(f"a gate index cannot be negative, got {self.gate_index}")
        if not math.isfinite(self.depth_mm):
            raise ValueError(
                f"a native gate depth must be finite, got {self.depth_mm!r}"
            )
        if self.state is MetricState.DEFINED:
            if self.value is None:
                raise ValueError(
                    "a defined metric carries a value: an undefined one is named by its state"
                )
            if not math.isfinite(self.value):
                raise ValueError(
                    f"a defined metric must be finite, got {self.value!r}: a non-finite value "
                    "is not a measurement"
                )
        elif self.value is not None:
            raise ValueError(
                f"a {self.state.value!r} row carries no value, got {self.value!r}: a number "
                "here would read as a measurement that was never taken"
            )
        if not self.reason.strip():
            raise ValueError("every gate row states why it is or is not reported")
        return self

    @property
    def defined(self) -> bool:
        """Whether this gate's metric was measured."""
        return self.state is MetricState.DEFINED


class MetricProfile(ValueModel):
    """One ``(recording, view, metric)`` profile: every supported gate's scalar, typed.

    ``gates`` is one :class:`GateMetric` per supported native gate, in the recording's native
    depth order - the view's own :attr:`WindowView.supported_columns` order - so a profile is
    a depth-resolved record rather than a reduction. ``units`` is the metric's unit, ``view``
    and ``view_rule`` are the view's own label and rule, and ``provenance`` is the same
    :class:`ViewProvenance` every sparse slice carries.

    No field is an array: a profile holds scalars and per-gate rows only, so it round-trips
    through ``model_dump(mode="json")`` and :meth:`json_text` serializes it without embedding
    any data block. The ACF curves, spectra and per-gate statistic matrices stay on the
    backend results they were computed on.
    """

    metric: MetricName
    units: str
    view: SparseView
    view_rule: str
    provenance: ViewProvenance
    gates: tuple[GateMetric, ...]
    method: str
    settings: tuple[MetricSetting, ...] = ()

    @model_validator(mode="after")
    def _check_the_profile_is_one_views_own_gates(self) -> MetricProfile:
        if self.units != METRIC_UNITS[MetricName(self.metric)]:
            raise ValueError(
                f"the {MetricName(self.metric).value!r} metric is quantified in "
                f"{METRIC_UNITS[MetricName(self.metric)]!r}, not {self.units!r}"
            )
        if self.view not in ALLOWED_VIEWS[MetricName(self.metric)]:
            raise ValueError(
                f"the {MetricName(self.metric).value!r} metric is declared on "
                f"{[member.value for member in ALLOWED_VIEWS[MetricName(self.metric)]]}, "
                f"not on {SparseView(self.view).value!r}"
            )
        if self.view_rule != VIEW_RULES[SparseView(self.view)]:
            raise ValueError(
                "a profile carries the view's own rule, so a label whose rule text "
                "disagrees with it is refused rather than carried"
            )
        if (
            self.provenance.view != self.view
            or self.provenance.view_rule != self.view_rule
        ):
            raise ValueError(
                "a profile's label and its provenance are one cut: the provenance records "
                f"{SparseView(self.provenance.view).value!r}, the profile "
                f"{SparseView(self.view).value!r}"
            )
        if not self.gates:
            raise ValueError("a profile carries at least one supported gate")
        if len(self.gates) != self.provenance.supported_gates:
            raise ValueError(
                f"a profile carries one row per supported gate: {len(self.gates)} row(s) "
                f"against {self.provenance.supported_gates} supported gate(s)"
            )
        indices = [row.gate_index for row in self.gates]
        if len(set(indices)) != len(indices):
            raise ValueError(
                f"a profile's gate rows name distinct native indices, got {indices}"
            )
        depths = [row.depth_mm for row in self.gates]
        if len(depths) > 1 and any(
            later <= earlier for earlier, later in pairwise(depths)
        ):
            raise ValueError(
                "a profile's rows are in strictly increasing native depth order, got "
                f"{depths}"
            )
        extent = self.provenance.participating_depth_extent_mm
        if not (
            math.isclose(depths[0], extent[0], rel_tol=0.0, abs_tol=1e-12)
            and math.isclose(depths[-1], extent[1], rel_tol=0.0, abs_tol=1e-12)
        ):
            raise ValueError(
                f"a profile's rows must span the participating depth extent {extent!r}, got "
                f"[{depths[0]!r}, {depths[-1]!r}]: a profile is one view's own supported gates"
            )
        return self

    @property
    def values(self) -> tuple[float | None, ...]:
        """Every gate's value in native depth order, ``None`` where the metric is undefined."""
        return tuple(row.value for row in self.gates)

    @property
    def depths_mm(self) -> tuple[float, ...]:
        """The native depths of this profile's rows, in order."""
        return tuple(row.depth_mm for row in self.gates)

    @property
    def defined_count(self) -> int:
        """How many of this profile's gates carry a measured value."""
        return sum(1 for row in self.gates if row.defined)

    def undefined(self) -> tuple[GateMetric, ...]:
        """The rows that carry no value, each with its own state and its own reason."""
        return tuple(row for row in self.gates if not row.defined)

    def json_text(self) -> str:
        """Canonical JSON text of this profile: scalars and per-gate rows, no arrays.

        ``allow_nan=False``, so a non-finite number fails the call rather than becoming
        invalid JSON, and the dump is the model's own ``mode="json"`` payload - which holds
        no ndarray by construction, because no field of this model is an array.

        Raises:
            ValueError: for a non-finite value anywhere in the payload.
        """
        return json.dumps(
            self.model_dump(mode="json"),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def allowed_views(metric: MetricName | str) -> tuple[SparseView, ...]:
    """The views one metric is declared on.

    Raises:
        SparseSa5MetricsError: for a metric this module does not define.
    """
    return ALLOWED_VIEWS[_metric(metric)]


def metric_units(metric: MetricName | str) -> str:
    """The unit one metric's values are in.

    Raises:
        SparseSa5MetricsError: for a metric this module does not define.
    """
    return METRIC_UNITS[_metric(metric)]


def metric_rule(metric: MetricName | str) -> str:
    """The definition of one metric, as its profile's rows quote it.

    Raises:
        SparseSa5MetricsError: for a metric this module does not define.
    """
    return METRIC_RULES[_metric(metric)]


def _metric(metric: MetricName | str) -> MetricName:
    """The enum member for ``metric``, or this module's refusal naming the allowed ones."""
    if isinstance(metric, MetricName):
        return metric
    try:
        return MetricName(metric)
    except ValueError as error:
        raise SparseSa5MetricsError(
            f"unknown SA5 metric {metric!r}; this module's are "
            f"{[member.value for member in METRICS]}"
        ) from error


def _detrending_of(detrending: Detrending | str) -> Detrending:
    """The detrending enum member for ``detrending``, or this module's refusal."""
    if isinstance(detrending, Detrending):
        return detrending
    try:
        return Detrending(detrending)
    except ValueError as error:
        raise SparseSa5MetricsError(
            f"unknown detrending {detrending!r}; SA1's are "
            f"{[member.value for member in Detrending]}"
        ) from error


def recurrence_peak_lag(result: object) -> RecurrencePeak | None:
    """The admissible descriptive peak :data:`RECURRENCE_PEAK_RULE` selects, or ``None``.

    Args:
        result: one gate's
            :class:`~udv_echo_process.analysis.sparse_recurrence.TraceRecurrence`.

    Returns:
        The peak with the largest correlation among those that are not weak and were
        preceded by a dip below the weak threshold (ties resolved to the smaller lag), or
        ``None`` when the trace holds no such peak.
    """
    admissible = [
        peak
        for peak in result.recurrence_peaks
        if not peak.weak and peak.preceded_by_dip_below_weak_threshold
    ]
    if not admissible:
        return None
    return max(admissible, key=lambda peak: (peak.correlation, -peak.lag_s))


def _shared(results: list[object], attribute: str, metric: MetricName) -> object:
    """One attribute every gate's result agrees on, or this module's refusal.

    One view is one time axis, so a lag resolution, a frequency resolution or a timebase
    verdict that differs between two gates of the same profile means the numbers do not
    describe one axis and the profile is refused rather than published.
    """
    values = [getattr(result, attribute) for result in results]
    first = values[0]
    for index, value in enumerate(values[1:], start=1):
        if value != first:
            raise SparseSa5MetricsError(
                f"the {metric.value!r} profile's gates do not share one axis: "
                f"{attribute} is {first!r} at the first gate and {value!r} at gate {index}, "
                "so these scalars were not measured on one view"
            )
    return first


def _common(results: list[object], attribute: str) -> object:
    """One attribute's value where every gate that *defines* it agrees, else ``None``.

    A refusal legitimately does not define every quantity - an achieved lag range exists only
    where a curve was computed - so gates carrying ``None`` are excluded from the comparison
    and the value is ``None`` only where no gate of the view defines it. Where two gates
    define it and disagree the value is ``None`` rather than whichever came first.
    """
    values = {getattr(result, attribute) for result in results}
    values.discard(None)
    return values.pop() if len(values) == 1 else None


def _gate_statistic_rows(
    view: WindowView, metric: MetricName
) -> tuple[tuple[GateMetric, ...], tuple[MetricSetting, ...]]:
    """SA1's per-gate row for one metric, read gate by gate from :func:`gate_statistics`."""
    statistics = gate_statistics(view)
    row = statistics.of(metric.value)
    columns = np.asarray(view.supported_columns)
    depths = np.asarray(view.depths_mm, dtype=float)
    rows: list[GateMetric] = []
    for position, column in enumerate(columns):
        depth = float(depths[int(column)])
        if not math.isclose(
            float(statistics.depths_mm[position]), depth, rel_tol=0.0, abs_tol=1e-12
        ):
            raise SparseSa5MetricsError(
                f"the statistics result places {float(statistics.depths_mm[position])!r} mm at "
                f"supported column {position} and the view places {depth!r} mm: the two are "
                "not one cut"
            )
        value = float(row[position])
        if math.isfinite(value):
            rows.append(
                GateMetric(
                    gate_index=int(column),
                    depth_mm=depth,
                    state=MetricState.DEFINED,
                    value=value,
                    reason=METRIC_RULES[metric],
                )
            )
        else:
            rows.append(
                GateMetric(
                    gate_index=int(column),
                    depth_mm=depth,
                    state=MetricState.UNDEFINED_NO_ESTIMATE,
                    value=None,
                    reason=(
                        f"SA1's {metric.value!r} statistic is not finite at this gate, so it "
                        "is not a measurement; an undefined statistic is never reduced or "
                        "published as a zero"
                    ),
                )
            )
    settings = [
        MetricSetting(name="method", value=statistics.method),
        MetricSetting(name="std_ddof", value=statistics.std_ddof),
    ]
    if metric is MetricName.MAD_SCALED:
        settings.extend(
            (
                MetricSetting(name="mad_scale", value=statistics.mad_scale),
                MetricSetting(name="mad_scaling", value=statistics.mad_scaling),
            )
        )
    return tuple(rows), tuple(settings)


def _recurrence_rows(
    view: WindowView,
    metric: MetricName,
    detrending: Detrending,
    max_lag_s: float | None,
) -> tuple[tuple[GateMetric, ...], tuple[MetricSetting, ...]]:
    """SA1's recurrence lag scalars, read gate by gate from :func:`recurrence_of_view`."""
    columns = np.asarray(view.supported_columns)
    depths = np.asarray(view.depths_mm, dtype=float)
    results = [
        recurrence_of_view(
            view,
            depth_mm=float(depths[int(column)]),
            detrending=detrending,
            max_lag_s=max_lag_s,
        )
        for column in columns
    ]
    # One view is one axis, so the axis the lag scales were measured on is checked across
    # every gate rather than read from whichever gate happened to come first.
    lag_resolution = _shared(results, "lag_resolution_s", metric)
    frequency_resolution = _shared(results, "frequency_resolution_hz", metric)
    timebase = _shared(results, "timebase", metric)
    estimator = _shared(results, "acf_estimator", metric)
    resolved_detrending = _shared(results, "detrending", metric)
    weak_peak = _shared(results, "weak_peak_correlation", metric)
    min_cycles = _shared(results, "min_candidate_cycles", metric)

    rows: list[GateMetric] = []
    for column, result in zip(columns, results):
        depth = float(depths[int(column)])
        if result.verdict is not RecurrenceVerdict.DEFINED:
            state = MetricState.UNDEFINED_CONSTANT_TRACE
            if result.verdict is not RecurrenceVerdict.UNDEFINED_CONSTANT_TRACE:
                state = MetricState.UNDEFINED_NO_ESTIMATE
            rows.append(
                GateMetric(
                    gate_index=int(column),
                    depth_mm=depth,
                    state=state,
                    value=None,
                    reason=result.message,
                )
            )
            continue
        if metric is MetricName.RECURRENCE_1E_LAG:
            quantity = result.decay_1e_lag
            if not quantity.supported:
                rows.append(
                    GateMetric(
                        gate_index=int(column),
                        depth_mm=depth,
                        state=MetricState.UNDEFINED_NOT_SUPPORTED,
                        value=None,
                        reason=quantity.reason,
                    )
                )
                continue
            rows.append(
                GateMetric(
                    gate_index=int(column),
                    depth_mm=depth,
                    state=MetricState.DEFINED,
                    value=float(quantity.value),
                    reason=quantity.reason,
                )
            )
            continue
        peak = recurrence_peak_lag(result)
        if peak is None:
            rows.append(
                GateMetric(
                    gate_index=int(column),
                    depth_mm=depth,
                    state=MetricState.UNDEFINED_NOT_SUPPORTED,
                    value=None,
                    reason=(
                        f"{RECURRENCE_PEAK_RULE} This trace holds no admissible peak: "
                        f"{result.peaks_reason}"
                    ),
                )
            )
            continue
        rows.append(
            GateMetric(
                gate_index=int(column),
                depth_mm=depth,
                state=MetricState.DEFINED,
                value=float(peak.lag_s),
                reason=(
                    f"{RECURRENCE_PEAK_RULE} The selected peak is at {peak.lag_s!r} s with "
                    f"correlation {peak.correlation!r} (weak threshold "
                    f"{weak_peak!r}). Peak note: {peak.reason}"
                ),
            )
        )
    settings = (
        MetricSetting(name="acf_estimator", value=str(estimator)),
        MetricSetting(
            name="detrending",
            value=str(getattr(resolved_detrending, "value", resolved_detrending)),
        ),
        MetricSetting(name="lag_resolution_s", value=_scalar(lag_resolution)),
        MetricSetting(
            name="frequency_resolution_hz", value=_scalar(frequency_resolution)
        ),
        MetricSetting(name="timebase", value=str(getattr(timebase, "value", timebase))),
        MetricSetting(
            name="requested_max_lag_s",
            value=_scalar(_shared(results, "requested_max_lag_s", metric)),
        ),
        MetricSetting(name="max_lag_s", value=_scalar(_common(results, "max_lag_s"))),
        MetricSetting(name="weak_peak_correlation", value=float(weak_peak)),
        MetricSetting(name="min_candidate_cycles", value=float(min_cycles)),
    )
    return tuple(rows), settings


def _spectral_rows(
    view: WindowView, *, low_hz: float, detrending: Detrending
) -> tuple[tuple[GateMetric, ...], tuple[MetricSetting, ...]]:
    """SA2.4's Φ per gate, read from :func:`characterization_of_view`'s own cell."""
    cell = characterization_of_view(view, low_hz=low_hz, detrending=detrending)
    rows = tuple(
        GateMetric(
            gate_index=int(row.gate_index),
            depth_mm=float(row.depth_mm),
            state=MetricState(row.band_fraction.state.value),
            value=(
                None
                if row.band_fraction.fraction is None
                else float(row.band_fraction.fraction)
            ),
            reason=row.band_fraction.reason,
        )
        for row in cell.gates
    )
    characterization = cell.admission.characterization
    settings = (
        MetricSetting(name="low_hz", value=float(cell.low_hz)),
        MetricSetting(name="detrending", value=str(cell.detrending.value)),
        MetricSetting(name="admitted", value=bool(cell.admission.admitted)),
        MetricSetting(name="admission_reason", value=cell.admission.reason),
        MetricSetting(name="estimator_name", value=cell.estimator_name),
        MetricSetting(name="taper_name", value=cell.taper_name),
        MetricSetting(name="normalization_rule", value=cell.normalization_rule),
        MetricSetting(name="one_sided_rule", value=cell.one_sided_rule),
        MetricSetting(
            name="effective_sample_rate_hz",
            value=_scalar(characterization.effective_sample_rate_hz),
        ),
        MetricSetting(name="nyquist_hz", value=_scalar(characterization.nyquist_hz)),
        MetricSetting(
            name="delta_f_hz", value=_scalar(characterization.frequency_resolution_hz)
        ),
        MetricSetting(name="profiles", value=int(characterization.profiles)),
    )
    return rows, settings


def _scalar(value: object) -> float | int | str | bool | None:
    """One backend scalar as a setting value: ``None`` stays ``None``, never a zero."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def read_metric_profile(
    view: WindowView,
    *,
    metric: MetricName | str,
    low_hz: float = DEFAULT_LOW_HZ,
    detrending: Detrending | str = Detrending.MEAN,
    max_lag_s: float | None = None,
) -> MetricProfile:
    """One metric's per-gate profile of one labelled view, read from the frozen backends.

    The single entry point, and deliberately per ``(view, metric)``: a profile is one
    recording's declared view at its supported native gates, so there is no parameter for a
    second view, a second recording or a reduction - the prespec's contrasts and its sitting
    tables are later artefacts, and none of their arithmetic is offered here.

    Args:
        view: one labelled :class:`WindowView`, built by ``primary_view``,
            ``full_record_view`` or ``exploration_view``.
        metric: one of :data:`METRICS`.
        low_hz: the Φ band edge in Hz; the design's declared recurrence scale. Used only by
            :data:`MetricName.PHI`.
        detrending: SA1's detrending vocabulary, passed to the recurrence and spectral
            estimators (the three gate statistics apply none).
        max_lag_s: the declared recurrence lag domain in seconds, applied to every gate of
            the view; ``None`` uses the estimator's own default. The prespec compares a
            recurrence scalar at a depth only on a *common supported lag domain*, so the
            declared domain is a setting of this endpoint and is carried on the profile. It
            is a recurrence setting: asking for one beside a spectral or fluctuation metric
            is refused rather than ignored.

    Returns:
        One :class:`MetricProfile` with a row per supported native gate, in native depth
        order, each carrying its own state and reason.

    Raises:
        SparseSa5MetricsError: for a metric this module does not define, a metric on a view
            the prespec does not declare it on, an unknown detrending, a lag domain asked
            for beside a metric that has none, and a view whose own gates disagree about the
            axis they were measured on.
        SparseViewError: for a view the sparse slices themselves refuse (an empty
            selection, a non-finite sample, a band edge above the axis's Nyquist frequency).
    """
    chosen = _metric(metric)
    label = SparseView(view.view)
    if label not in ALLOWED_VIEWS[chosen]:
        raise SparseSa5MetricsError(
            f"the {chosen.value!r} metric is declared on "
            f"{[member.value for member in ALLOWED_VIEWS[chosen]]}, not on {label.value!r} "
            f"({VIEW_RULES[label]}): an exploratory cut and an exchanged view are refused "
            "rather than computed"
        )
    resolved = _detrending_of(detrending)
    if max_lag_s is not None and chosen not in RECURRENCE_METRICS:
        raise SparseSa5MetricsError(
            f"max_lag_s is a recurrence setting and the {chosen.value!r} metric has no lag "
            "domain: pass it only with a recurrence metric rather than letting it be ignored"
        )
    if chosen in PRIMARY_METRICS:
        rows, settings = _gate_statistic_rows(view, chosen)
    elif chosen in RECURRENCE_METRICS:
        rows, settings = _recurrence_rows(view, chosen, resolved, max_lag_s)
    else:
        rows, settings = _spectral_rows(view, low_hz=float(low_hz), detrending=resolved)
    return MetricProfile(
        metric=chosen,
        units=METRIC_UNITS[chosen],
        view=label,
        view_rule=view.view_rule,
        provenance=view_provenance(view),
        gates=rows,
        method=METHOD,
        settings=settings,
    )
