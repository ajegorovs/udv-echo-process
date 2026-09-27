"""The committed live recordings' own spectral capability, as one record per view (``SA2``).

The first result SA2 produces, and deliberately the narrowest one: for every committed
recording, on both of the views the analysis compares, the characterized axis, the admission
verdict and the two probe targets - the 104 ``recording x view`` records the plan asks for, and
not 52 generic ones. The primary comparison and the full record are kept apart because their
spans differ and a span is what a cycle count is made of.

**Nothing is published here.** The sweep is a query over the committed recordings, and the
artefact that publishes it belongs to SA7. This module exists so the committed capability is
*measurable* - and testable - without a report directory, and so the notebook that selects a
pass reads one function instead of re-deriving the sweep.

**Two targets, named once.** The probes are the recurrence target at 1 Hz and the rotor
reference at 8.333 Hz (500 rpm nominal), which is how the design names them; the labels here
are the ones a report can quote. Adding a target is adding a pair to :data:`PROBE_TARGETS`,
never a new column of bespoke code.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    WindowView,
    full_record_view,
    primary_view,
    view_provenance,
)
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES, PassRef
from udv_echo_process.analysis.sparse_spectral_admission import (
    AdmissionCondition,
    SpectralAdmission,
    spectral_admission,
)
from udv_echo_process.analysis.sparse_spectral_support import (
    TimebaseCharacterization,
    characterize_timebase,
)
from udv_echo_process.analysis.sparse_target_support import (
    TargetFrequencySupport,
    target_frequency_support,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CAPABILITY_VIEWS",
    "PROBE_TARGETS",
    "CommittedView",
    "SpectralCapability",
    "capability_of_view",
    "committed_spectral_capability",
    "committed_window_views",
]

#: The two probe targets of the design, as ``(label, frequency_hz)``. 8.333 Hz is the rotor
#: reference of a 500 rpm nominal table (25/3 Hz), not a rounded 8.3; it is written as the
#: fraction so that the target and the reference frequency are the same number.
PROBE_TARGETS: tuple[tuple[str, float], ...] = (
    ("recurrence-1hz", 1.0),
    ("rotor-8.333hz", 25.0 / 3.0),
)

#: The two views the capability row set is built over, in the order the plan introduces them.
CAPABILITY_VIEWS: tuple[SparseView, ...] = (SparseView.PRIMARY, SparseView.FULL_RECORD)


class SpectralCapability(ValueModel):
    """One ``recording x view`` capability record: the axis, its verdict and its targets.

    Every axis quantity is read through :attr:`admission`, whose characterization owns it, so a
    row cannot disagree with the verdict it carries. The row's own fields are the identity of the
    recording and of the view, which is what makes 104 records distinguishable at all.
    """

    #: The committed pass the recording belongs to, or ``None`` for a view not built from one.
    pass_name: str | None = None
    view: SparseView
    job: str
    point_label: str
    order: int
    relative_path: str
    source_sha256: str

    admission: SpectralAdmission
    #: One entry per probe target, in :data:`PROBE_TARGETS` order.
    targets: tuple[TargetFrequencySupport, ...] = ()

    @property
    def characterization(self) -> TimebaseCharacterization:
        """The characterized axis this record is about.
        """
        return self.admission.characterization

    @property
    def profiles(self) -> int:
        """Samples on the axis.
        """
        return self.characterization.profiles

    @property
    def span_s(self) -> float | None:
        """The span the stored stamps hold.
        """
        return self.characterization.span_s

    @property
    def effective_interval_s(self) -> float | None:
        """The adopted effective interval ``span / (N - 1)``.
        """
        return self.characterization.full_span_interval_s

    @property
    def effective_sample_rate_hz(self) -> float | None:
        """The adopted effective sample rate.
        """
        return self.characterization.effective_sample_rate_hz

    @property
    def nyquist_hz(self) -> float | None:
        """The axis's mathematical Nyquist frequency.
        """
        return self.characterization.nyquist_hz

    @property
    def frequency_resolution_hz(self) -> float | None:
        """The prospective bin spacing, ``fs_eff / N`` - not ``1 / span``.
        """
        return self.characterization.frequency_resolution_hz

    @property
    def max_relative_timing_error(self) -> float | None:
        """The admission operand: how far a stamp sits from the assumed grid.
        """
        return self.characterization.max_relative_timing_error

    @property
    def max_timing_error_s(self) -> float | None:
        """The same operand in seconds, the unit the logger's clock quantum is measured in.
        """
        return self.characterization.max_timing_error_s

    @property
    def max_relative_interval_deviation(self) -> float | None:
        """The design's interval diagnostic, carried beside the operand.
        """
        return self.characterization.max_relative_interval_deviation

    @property
    def largest_gap_ratio(self) -> float | None:
        """The longest interval over the median one.
        """
        return self.characterization.largest_gap_ratio

    @property
    def declared_window_s(self) -> float | None:
        """The interval the view's rule *asked* for, which is not the span it collected.
        """
        provenance = self.characterization.provenance
        return None if provenance is None else float(provenance.declared_window_s)

    @property
    def failed_conditions(self) -> tuple[AdmissionCondition, ...]:
        """The conditions the verdict failed, empty when the axis is admitted.
        """
        return self.admission.failed_conditions

    @property
    def provenance(self):
        """The shared SA1 provenance of the recording this row is about.
        """
        return self.characterization.provenance

    @property
    def admitted(self) -> bool:
        """Whether the estimator is admitted for this axis.
        """
        return self.admission.admitted

    @property
    def admission_reason(self) -> str:
        """Why it was admitted, or which conditions failed.
        """
        return self.admission.reason

    def target(self, label: str) -> TargetFrequencySupport:
        """The support verdict for one probe label.

        Raises:
            KeyError: for a label this record does not carry, with the labels it does, so a
                mistyped probe is a stated absence rather than an ``IndexError``.
        """
        for entry in self.targets:
            if entry.target_label == label:
                return entry
        raise KeyError(
            f"no target {label!r} on this record; it carries "
            f"{[entry.target_label for entry in self.targets]}"
        )


def capability_of_view(
    view: WindowView,
    *,
    pass_name: str | None = None,
    targets: Iterable[tuple[str, float]] = PROBE_TARGETS,
) -> SpectralCapability:
    """Characterize, admit and probe one view: the whole SA2.1 pipeline in one call.

    The chain is the design's - a view is characterized from its own stamps, the characterization
    is classified by the calibrated policy, and each target is then asked of the *admitted* axis -
    and target support is never consulted while admitting the estimator, which is what keeps an
    E128 axis from being reported as "unsupported" for a reason that belongs to its bandwidth.
    """
    provenance = view_provenance(view)
    characterization = characterize_timebase(view)
    admission = spectral_admission(characterization)
    return SpectralCapability(
        pass_name=pass_name,
        view=view.view,
        job=provenance.job,
        point_label=provenance.point_label,
        order=int(provenance.order),
        relative_path=provenance.relative_path,
        source_sha256=provenance.source_sha256,
        admission=admission,
        targets=tuple(
            target_frequency_support(admission, frequency_hz, label=label)
            for label, frequency_hz in targets
        ),
    )


class CommittedView(NamedTuple):
    """One committed ``recording x view``: the view, the pass that owns it, the pass's plan.

    The plan fingerprint is carried beside the view because the default row set spans **two**
    passes with **two** plans: a single fingerprint cannot stand for both, so the sweep states
    each pass's own fingerprint rather than picking one and silently dropping the other.

    The four condition fields are **forwarded scalar metadata**, not a second reading of the
    pass: ``kind`` is the job's kind, ``condition`` the job's run-wide
    ``(burst_length, emissions_per_profile, prf_us)`` triple, and ``resolution_mm``/``gates``
    the point's planned window pair. All four are read off the decoded point's own binding -
    ``job`` and the planned point's ``parameters`` - so a consumer that has to group cells by
    the condition they were actually acquired under (SA2.4's §4 repeat spread) reads it here,
    beside the same cell its numbers come from, instead of re-deriving it from the pass's log.
    ``WindowView`` and ``ViewProvenance`` are deliberately left unchanged: the condition is a
    property of the *acquisition*, not of the view, and a view that carried it could disagree
    with the job it was cut from.
    """

    pass_name: str
    plan_fingerprint: str
    view: WindowView
    #: The job's kind as the pass's own record states it (``scientific``/``common-reference``).
    kind: str | None = None
    #: The job's run-wide condition triple: ``(burst_length, emissions_per_profile, prf_us)``.
    condition: tuple[int, int, float] | None = None
    #: The point's planned window pitch in mm and native gate count - the design's window pair.
    resolution_mm: float | None = None
    gates: int | None = None


def committed_window_views(
    *,
    passes: Iterable[PassRef] | None = None,
    window_s: float | None = None,
) -> tuple[CommittedView, ...]:
    """Every committed live ``recording x view`` as a view, in the sweep's own order.

    The one place the row set is *built*, so a reader that measures a different quantity over
    the same cells (SA2.4's characterization report, and any later synthesis over the same
    observations) sweeps the committed passes exactly as the capability query does instead of
    re-deriving the scope, the window and the view order beside it. It decodes each pass once
    and cuts the same two views through the same SA1 constructors, in pass order, then the
    pass's own acquisition order, then primary comparison before full record.

    Adding a record type here (rather than a second hand-built sweep in a consumer) is what
    keeps the cell count, the pass labels and the plan fingerprints from drifting apart between
    the capability table and the report built on it.

    Args:
        passes: the passes to sweep. ``None`` is the passes the analysis compares - those the
            catalog marks as reproducibility sittings, campaign excluded - which is the row set
            the plan states. A campaign is a separate design with its own evidence, so sweeping
            it is a deliberate act with its own ref, not a default.
        window_s: the primary window to cut. ``None`` uses each pass's own common window, which
            is the window the committed analysis uses.

    Returns:
        ``2 * 52 = 104`` views for the default scope, each with its pass's name and plan
        fingerprint, in the order described above.
    """
    scope = COMMITTED_PASSES if passes is None else tuple(passes)
    views: list[CommittedView] = []
    for ref in scope:
        if passes is None and not ref.is_reproducibility_sitting:
            continue
        decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for point in decoding.points:
            job = point.binding.job
            parameters = point.binding.point.parameters
            window = decoding.window_s if window_s is None else float(window_s)
            for view in (
                primary_view(point, window_s=window, support_mm=decoding.support_mm),
                full_record_view(point, support_mm=decoding.support_mm),
            ):
                views.append(
                    CommittedView(
                        pass_name=ref.name,
                        plan_fingerprint=str(decoding.plan_fingerprint),
                        view=view,
                        kind=str(job.kind),
                        condition=(
                            int(job.burst_length),
                            int(job.emissions_per_profile),
                            float(job.prf_us),
                        ),
                        resolution_mm=float(parameters.resolution_mm),
                        gates=int(parameters.gates),
                    )
                )
    return tuple(views)


def committed_spectral_capability(
    *,
    passes: Iterable[PassRef] | None = None,
    targets: Iterable[tuple[str, float]] = PROBE_TARGETS,
    window_s: float | None = None,
) -> tuple[SpectralCapability, ...]:
    """Every committed live ``recording x view`` capability, in pass and acquisition order.

    Args:
        passes: the passes to sweep. ``None`` is the passes the analysis compares - those the
            catalog marks as reproducibility sittings, i.e. the two mixer-enabled sittings and
            their 52 recordings - because that is the row set the plan states. A campaign is a
            separate design with its own evidence, so sweeping it is a deliberate act with its
            own ref, not a default.
        targets: the probe targets, ``(label, frequency_hz)`` pairs.
        window_s: the primary window to cut. ``None`` uses each pass's own common window, which
            is the window the committed analysis uses.

    Returns:
        ``2 * 52 = 104`` records for the default scope, ordered by pass, then the pass's own
        acquisition order, then primary comparison before full record.
    """
    return tuple(
        capability_of_view(entry.view, pass_name=entry.pass_name, targets=targets)
        for entry in committed_window_views(passes=passes, window_s=window_s)
    )
