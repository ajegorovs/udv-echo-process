"""The sparse views: one canonical vocabulary, one cut, one provenance (plan ``SA0``/``SA1``).

This module exists because SA1 had two of everything. The gate-statistics slice spelled
the three views ``primary-comparison``/``full-record``/``exploration`` as bare strings,
the recurrence slice spelled two of them with spaces inside a second enum, and only the
notebook reconciled the two - with a translation map, because the label the modules
disagreed about most was ``exploration``, whose *semantics* also differed (a contiguous
time+depth block against a caller's leading window). SA2 would have inherited both.

What is canonical here:

- :class:`SparseView` - the one typed view vocabulary. Its values are the hyphenated
  labels the results carry and the reports quote, so a view is spelled the same way in a
  statistical result, a recurrence result and a notebook;
- :data:`VIEW_RULES` - the rule each label means, so "exploration" cannot quietly mean
  two different cuts in two modules; every result carries its rule beside its label;
- :class:`WindowView` - one recording cut to one view: the samples, their native
  coordinates, the mask that selected them, and the identity of the file they came from.
  It is the *only* object a later stage should read a selected block or a selected trace
  from, so there is exactly one cutting path;
- :class:`ViewProvenance` - what a result was computed on, as a compact summary that
  serializes without the data block. It is the *same* type for every slice (statistics
  and recurrence alike), so no slice keeps a second parallel description of a view.

Coordinates are named so that the three different "supports" cannot be confused, because
SA1 had three fields whose names all said support and whose meanings did not agree:

- ``pass_support_mm`` - the **pass's declared** common physical support, the thing a
  depth-resolved comparison is restricted to;
- ``native_depth_extent_mm`` - the **recording's own** gate extent, i.e. what the
  instrument stored, before any restriction;
- :attr:`WindowView.participating_depth_extent_mm` - the extent of the gates this
  *selection* actually uses, after both the view's cut and the support restricton.

``native_gates`` is the recording's gate count - the native grid's dimension - and is
never the selected view's column count. That distinction is a SA1 defect this module
fixes: an exploration view selecting 11 of a 50-gate recording used to report
``native_gates=11``, so any consumer computing "the fraction of native gates supported"
was wrong for every exploration view.

No estimator lives here. This module knows how to select, label and describe a block; how
to summarise it is :mod:`udv_echo_process.analysis.sparse_gate_stats`, and how to
correlate it is :mod:`udv_echo_process.analysis.sparse_recurrence`.
"""

from __future__ import annotations

import math
from enum import Enum

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis._native_grid import TOLERANCE_S, in_support
from udv_echo_process.analysis._sparse_pass import DecodedPoint, primary_window
from udv_echo_process.models.base import ArrayModel, ValueModel, array_field


class SparseViewError(ValueError):
    """A view cannot be selected, cut or described as asked.

    The refusal of this module: raised for a window that is not finite and positive, a
    recording whose stamps cover no profile of the designed interval, exploration bounds
    that are not finite and increasing or that reach outside the stored record, and a
    selection that lands on no supported gate. The slices built on this module raise
    their own errors, and each of those is a subclass, so a caller may catch this as
    "the sparse analysis refused this view".
    """


class SparseView(str, Enum):
    """Which of the analysis plan's three views a block came from.

    One vocabulary for every slice. The values are the labels the results carry and the
    reports quote, so a reader never has to translate between a statistics result and a
    recurrence result. Being a ``str`` enum, a member compares equal to its own label.

    The plan's rule - that an exploratory selection is never silently the primary
    comparison - is carried by :data:`VIEW_RULES` and stated on every result, rather than
    left to a caller's memory.
    """

    #: The pass's designed leading window, cut by the recording's own stored stamps.
    PRIMARY = "primary-comparison"
    #: Every stored profile, for stationarity, ACF and spectral diagnostics.
    FULL_RECORD = "full-record"
    #: Explicitly selected time and depth bounds: a labelled exploratory selection.
    EXPLORATION = "exploration"


#: The three views, in the order the plan introduces them. Membership is the vocabulary's
#: own validity rule, and it holds for a label string as well as a member.
VIEW_LABELS: tuple[SparseView, ...] = (
    SparseView.PRIMARY,
    SparseView.FULL_RECORD,
    SparseView.EXPLORATION,
)

VIEW_RULES: dict[SparseView, str] = {
    SparseView.PRIMARY: (
        "the pass's designed leading window, cut by the recording's own stored timestamps: the "
        "primary-comparison view. It is never widened to the instrument's retained extra fraction "
        "of a second, and an exploratory selection never replaces it."
    ),
    SparseView.FULL_RECORD: (
        "every stored profile of the recording, for stationarity, ACF and spectral diagnostics: "
        "the full-record view, labelled separately from the primary comparison because its "
        "duration varies between recordings."
    ),
    SparseView.EXPLORATION: (
        "explicitly selected time and depth bounds: the exploration view. It is a labelled "
        "exploratory selection and must never silently replace the primary-comparison view."
    ),
}


def view_rule(view: SparseView | str) -> str:
    """The rule one view label means, refused by name for a label that is not one of the three.

    Raises:
        SparseViewError: for a label outside :data:`VIEW_LABELS`. A caller indexing
            :data:`VIEW_RULES` directly would get a bare ``KeyError``; this is the
            module's own refusal instead.
    """
    try:
        chosen = view if isinstance(view, SparseView) else SparseView(view)
    except ValueError as exc:
        raise SparseViewError(
            f"a view label is one of {[str(member.value) for member in VIEW_LABELS]}, "
            f"got {view!r}"
        ) from exc
    return VIEW_RULES[chosen]


class WindowView(ArrayModel):
    """One recording as one *view*: its samples, their native coordinates and its support mask.

    ``values`` is ``(profiles, gates)`` in ``mm/s``; ``time_s`` are the view's own stored
    timestamps in seconds, ``depths_mm`` the native gate depths of the view's own columns
    in mm - the instrument's own coordinate, never relabelled or converted;
    ``support_mask`` marks which of *those columns* the pass's common physical support
    selected. ``start_index`` and ``stop_index`` are the view's positions in the
    recording's stored profile axis, so the cut is auditable. ``declared_window_s``
    records the interval that was *asked for* when it differs from the span the stored
    stamps achieve.

    Three dimensions are kept apart on purpose, because one number cannot mean all three:
    ``native_gates`` and ``native_depth_extent_mm`` describe the recording the selection
    was taken from, ``depths_mm`` describes the columns this view actually holds, and
    ``pass_support_mm`` is the pass-wide restriction both are read against. An
    exploration view of 11 gates out of a 50-gate recording reports ``native_gates == 50``.
    """

    view: SparseView
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
    native_gates: int
    native_depth_extent_mm: tuple[float, float]
    pass_support_mm: tuple[float, float]
    start_index: int
    stop_index: int
    window_start_s: float
    window_end_s: float
    window_s: float
    declared_window_s: float | None = None
    time_bounds_s: tuple[float, float] | None = None
    depth_bounds_mm: tuple[float, float] | None = None

    @property
    def participating_depth_extent_mm(self) -> tuple[float, float]:
        """The depth extent of the gates this selection actually uses, support included.

        Measured from the view's own supported columns, never copied from a declared
        range, so a reader can see which depths the numbers cover. A view holds at least
        one supported gate by construction, so this is always defined.
        """
        supported = np.asarray(self.depths_mm, dtype=float)[
            np.flatnonzero(np.asarray(self.support_mask))
        ]
        return float(supported.min()), float(supported.max())

    @property
    def supported_columns(self) -> np.ndarray:
        """The view's own column indices the support mask selects, in native depth order.

        The one place a slice should ask "which of this view's gates are supported", so
        the statistics, the trace and the recurrence cannot drift apart on the index.
        """
        return np.flatnonzero(np.asarray(self.support_mask))

    def column_of_depth(self, depth_mm: float) -> int:
        """The view's own column index of one native gate depth.

        Raises:
            SparseViewError: for a depth that is not one of this view's native gates. The
                instrument's grid is the coordinate, so a depth between two gates is not
                rounded to a neighbour here: a caller asks for a gate the view holds.
        """
        grid = np.asarray(self.depths_mm, dtype=float)
        matches = np.flatnonzero(np.abs(grid - float(depth_mm)) <= TOLERANCE_S)
        if matches.size != 1:
            raise SparseViewError(
                f"{self.relative_path}: {float(depth_mm)!r} mm is not one of this view's "
                f"native gate depths [{float(grid[0]):g}, {float(grid[-1]):g}] mm "
                f"({grid.size} gate(s), {matches.size} match(es))"
            )
        return int(matches[0])

    @model_validator(mode="after")
    def _check_the_view_is_one_contiguous_supported_block(self) -> WindowView:
        if self.view_rule != VIEW_RULES[SparseView(self.view)]:
            raise ValueError(
                f"the rule of the {SparseView(self.view).value!r} view is fixed by the "
                "plan, and a view whose rule disagrees with its label would carry a "
                "meaning nothing else in the repository shares"
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
                f"the support mask {self.support_mask.shape} must have one entry per gate of "
                f"this view {self.depths_mm.shape}"
            )
        if not np.any(self.support_mask):
            raise ValueError(
                "no native gate of this view lies inside the common support "
                f"[{self.pass_support_mm[0]:g}, {self.pass_support_mm[1]:g}] mm, so it cannot "
                "enter a depth-resolved comparison"
            )
        if self.native_gates < self.depths_mm.size:
            raise ValueError(
                f"this view holds {self.depths_mm.size} gate column(s) of a recording with "
                f"{self.native_gates} native gate(s): a view selects from the native grid, "
                "it never enlarges it"
            )
        for name, extent in (
            ("native", self.native_depth_extent_mm),
            ("pass support", self.pass_support_mm),
        ):
            if not (
                math.isfinite(extent[0])
                and math.isfinite(extent[1])
                and extent[0] < extent[1]
            ):
                raise ValueError(
                    f"the {name} depth extent must be finite and increasing, got "
                    f"({extent[0]!r}, {extent[1]!r})"
                )
        low, high = self.native_depth_extent_mm
        if (
            float(self.depths_mm.min()) < low - TOLERANCE_S
            or float(self.depths_mm.max()) > high + TOLERANCE_S
        ):
            raise ValueError(
                f"this view's gate depths [{float(self.depths_mm.min()):g}, "
                f"{float(self.depths_mm.max()):g}] mm must lie inside the recording's own "
                f"native grid [{low:g}, {high:g}] mm"
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
    """What a view's result was computed on: identity, the three extents, and the windows.

    A compact summary that serializes without the data block, so a report can quote what a
    number rests on. It is the *same* type for every sparse slice - the per-gate statistics
    and the trace recurrence both carry one - so no slice keeps a parallel description of a
    view, and a later stage has one place to read a source identity from.

    It is the authority for source identity (``relative_path``, ``source_sha256``,
    ``job``, ``point_label``, ``order``), the native grid's dimension and extent, the
    pass's declared support, the selection's participating extent, the time and depth
    windows, and the view's own rule. Estimator settings are deliberately *not* here:
    they belong to the result that used them, not to the data the result is about.
    """

    view: SparseView
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
    native_depth_extent_mm: tuple[float, float]
    pass_support_mm: tuple[float, float]
    participating_depth_extent_mm: tuple[float, float]
    supported_gates: int
    window_start_s: float
    window_end_s: float
    window_s: float
    declared_window_s: float | None = None
    time_bounds_s: tuple[float, float] | None = None
    depth_bounds_mm: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _check_the_provenance_is_the_views_own_and_not_a_claim(self) -> ViewProvenance:
        if self.view_rule != VIEW_RULES[SparseView(self.view)]:
            raise ValueError(
                f"a provenance records the {SparseView(self.view).value!r} view's own rule, "
                "so a label whose rule text disagrees with it is refused rather than carried"
            )
        if self.supported_gates < 1 or self.supported_gates > self.native_gates:
            raise ValueError(
                f"{self.supported_gates} supported gate(s) out of {self.native_gates} native "
                "gate(s) is not a support a result could have been computed on"
            )
        if self.profiles < 1 or self.stop_index - self.start_index != self.profiles:
            raise ValueError("the provenance's profile count must be the view's own")
        if (
            self.participating_depth_extent_mm[0] >= self.participating_depth_extent_mm[1]
            and self.supported_gates > 1
        ):
            raise ValueError(
                "the participating depth extent must be increasing when more than one gate "
                "is supported"
            )
        return self


def view_provenance(view: WindowView) -> ViewProvenance:
    """The provenance record of one view: its identity, its three extents and its windows.

    The native dimension and extent come from the view's own record of them, and the
    participating extent is *measured* from the view's supported native gates, so a reader
    can see which depths the numbers actually cover.
    """
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
        native_gates=view.native_gates,
        native_depth_extent_mm=view.native_depth_extent_mm,
        pass_support_mm=view.pass_support_mm,
        participating_depth_extent_mm=view.participating_depth_extent_mm,
        supported_gates=int(np.count_nonzero(view.support_mask)),
        window_start_s=view.window_start_s,
        window_end_s=view.window_end_s,
        window_s=view.window_s,
        declared_window_s=view.declared_window_s,
        time_bounds_s=view.time_bounds_s,
        depth_bounds_mm=view.depth_bounds_mm,
    )


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


def _require_bounds(bounds: tuple[float, float], *, what: str) -> tuple[float, float]:
    """One pair of explicit bounds, refused unless finite and increasing.
    """
    low, high = float(bounds[0]), float(bounds[1])
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        raise SparseViewError(
            f"the {what} bounds must be finite and increasing, got ({low!r}, {high!r})"
        )
    return low, high


def _window_view(
    point: DecodedPoint,
    *,
    view: SparseView,
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
    """Assemble one labelled view over the pass's declared support.

    The support mask is taken over the columns this view holds, which is what makes the
    ``values`` block and the mask the same shape; the recording's *native* grid dimension
    and extent travel separately so a selection can never be mistaken for the grid.
    """
    stamps = np.asarray(time_s, dtype=float)
    grid = np.asarray(depths, dtype=float)
    native = np.asarray(point.depths, dtype=float)
    return WindowView(
        view=view,
        view_rule=VIEW_RULES[view],
        **_identity_cells(point),
        values=np.asarray(values, dtype=float),
        time_s=stamps,
        depths_mm=grid,
        support_mask=in_support(grid, support_mm),
        native_gates=int(native.size),
        native_depth_extent_mm=(float(native.min()), float(native.max())),
        pass_support_mm=(float(support_mm[0]), float(support_mm[1])),
        start_index=int(start_index),
        stop_index=int(stop_index),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
        declared_window_s=declared_window_s,
        time_bounds_s=time_bounds_s,
        depth_bounds_mm=depth_bounds_mm,
    )


def primary_view(
    point: DecodedPoint, *, window_s: float, support_mm: tuple[float, float]
) -> WindowView:
    """One recording's primary-comparison view: the leading ``window_s``, cut by its own stamps.

    The cut is the pass's shared view (``_sparse_pass.primary_window``), so a notebook and
    a floor compute over the same interval: the designed exposure, never the instrument's
    retained surplus - which is why ``declared_window_s`` (the interval asked for) and
    ``window_s`` (the span the stamps achieve) are both recorded and the view's end can
    only fall at or below the declared one.

    Raises:
        SparseViewError: for a window that is not finite and positive, or a recording
            whose stamps cover no profile of the designed interval.
    """
    if not math.isfinite(window_s) or window_s <= 0.0:
        raise SparseViewError(
            f"a primary window must be finite and positive, got {window_s!r}"
        )
    stamps = np.asarray(point.time_s, dtype=float)
    span_s = float(stamps[-1] - stamps[0]) if stamps.size > 1 else 0.0
    if span_s < window_s - TOLERANCE_S:
        raise SparseViewError(
            f"{point.relative_path}: the stored record spans {span_s:g} s, less than the "
            f"designed {window_s:g} s primary window. The primary comparison is refused "
            "rather than widened - and rather than narrowed to whatever the record happens "
            "to hold: a cut that is not the designed exposure is not the shared comparison, "
            "and two recordings cut to different widths are not comparable at all"
        )
    block = primary_window(point, window_s)
    profiles = int(block.shape[0])
    if profiles < 1:
        raise SparseViewError(
            f"{point.relative_path}: no stored profile falls inside the designed "
            f"{window_s:g} s primary window; this recording cannot enter the primary comparison"
        )
    stamps = np.asarray(point.time_s, dtype=float)[:profiles]
    return _window_view(
        point,
        view=SparseView.PRIMARY,
        values=block,
        time_s=stamps,
        depths=np.asarray(point.depths, dtype=float),
        start_index=0,
        stop_index=profiles,
        support_mm=support_mm,
        declared_window_s=float(window_s),
    )


def full_record_view(point: DecodedPoint, *, support_mm: tuple[float, float]) -> WindowView:
    """One recording's full-record view: every stored profile, labelled separately.

    The primary comparison is not replaced by this view: the plan reserves it for ACF,
    spectra and stationarity diagnostics, where the duration may vary between recordings
    and is therefore its own label rather than a shared interval.
    """
    values = np.asarray(point.values, dtype=float)
    stamps = np.asarray(point.time_s, dtype=float)
    return _window_view(
        point,
        view=SparseView.FULL_RECORD,
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

    The selection is by index on the recording's own monotone stamps and increasing native
    gate grid, so the view stays one contiguous supported block and the native depth
    coordinate is preserved. Bounds must lie inside the stored record and select at least
    one supported gate: an exploratory selection may not widen the record it came from, and
    this view is labelled so it can never be mistaken for the primary comparison.

    An exploration view is the *same* kind of object as the primary one, on different
    bounds - which is what lets a later stage read a trace from whichever view the reader
    selected without reinterpreting the label.

    Raises:
        SparseViewError: for bounds that are not finite and increasing, that reach outside
            the stored record, or that select no supported gate.
    """
    stamps = np.asarray(point.time_s, dtype=float)
    grid = np.asarray(point.depths, dtype=float)
    values = np.asarray(point.values, dtype=float)
    low_s, high_s = _require_bounds(time_bounds_s, what="time")
    low_mm, high_mm = _require_bounds(depth_bounds_mm, what="depth")
    if low_s < float(stamps[0]) - TOLERANCE_S or high_s > float(stamps[-1]) + TOLERANCE_S:
        raise SparseViewError(
            f"{point.relative_path}: the exploratory time bounds [{low_s:g}, {high_s:g}] s "
            f"reach outside the stored record [{float(stamps[0]):g}, "
            f"{float(stamps[-1]):g}] s; a selection is taken from the record, never widened"
        )
    if low_mm < float(grid[0]) - TOLERANCE_S or high_mm > float(grid[-1]) + TOLERANCE_S:
        raise SparseViewError(
            f"{point.relative_path}: the exploratory depth bounds [{low_mm:g}, {high_mm:g}] mm "
            f"reach outside the stored native grid [{float(grid[0]):g}, {float(grid[-1]):g}] mm"
        )
    inside_time = np.flatnonzero(
        (stamps >= low_s - TOLERANCE_S) & (stamps <= high_s + TOLERANCE_S)
    )
    if inside_time.size == 0:
        raise SparseViewError(
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
        raise SparseViewError(
            f"{point.relative_path}: no native gate inside [{low_mm:g}, {high_mm:g}] mm lies "
            f"inside the common support [{support_mm[0]:g}, {support_mm[1]:g}] mm; this "
            "selection cannot enter a depth-resolved comparison"
        )
    gates = inside_depth[mask]
    start_index, stop_index = int(inside_time[0]), int(inside_time[-1]) + 1
    return _window_view(
        point,
        view=SparseView.EXPLORATION,
        values=values[start_index:stop_index][:, gates],
        time_s=stamps[start_index:stop_index],
        depths=grid[gates],
        start_index=start_index,
        stop_index=stop_index,
        support_mm=support_mm,
        time_bounds_s=(low_s, high_s),
        depth_bounds_mm=(low_mm, high_mm),
    )
