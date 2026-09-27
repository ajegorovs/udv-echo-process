"""SA2.4 S2 - the committed-data scalar spectral characterization report (plan §§5-9).

The publish point of SA2.4, and deliberately a *scalar* one. It sweeps the committed
``recording x view`` cells the capability query already owns, reduces each supported gate with
SA2.4 S1's one prespecified metric, and writes three files under the sparse plan's designated
publish root:

    reports/sparse-signal/sa2-4-spectral-characterization.csv
    reports/sparse-signal/sa2-4-spectral-characterization.json
    reports/sparse-signal/README.md

**No estimator, admission rule, threshold or verdict is added here.** Every number is read from
an object that already owns it: the axis from ``SpectralAdmission.characterization``, the band
fraction from :func:`~udv_echo_process.analysis.sparse_spectral_characterization
.low_frequency_power_fraction`, the target rows from
:func:`~udv_echo_process.analysis.sparse_target_support.target_frequency_support`, the two probe
names from :data:`~udv_echo_process.analysis.sparse_spectral_capability.PROBE_TARGETS`, and the
estimator's own convention strings from the estimate. This module computes no transform, taper,
grid, normalization, admission or target verdict.

**The row set is the capability query's own scope, not a second hand-built sweep.** The writer
consumes :func:`~udv_echo_process.analysis.sparse_spectral_capability.committed_window_views`,
which is the one place the 52 recordings x 2 views are selected, so a report cannot silently
sweep a different set of cells than the capability table (plan §1: 104 cells; D4: every supported
gate, never a subset).

**Scalar content only, on the design's narrowed clause.** ``sa2-spectral-design.md`` permits a
committed machine-readable spectral artifact - without resolving issue #49 - only when its whole
content is named scalar reductions of a spectrum plus the named scalar metadata and provenance
needed to define, reproduce and interpret them, at the *observation unit's* cardinality. This
module therefore publishes:

* one CSV row per ``cell x supported gate`` - the identity, the axis scalars, the band-fraction
  scalars and the QA field; and
* one JSON cell per ``recording x view``, with its two target rows stated **once**, and a summary
  of counts.

No PSD array is serialized, no NPZ is shipped, no field follows a bin, sample or element, and
nothing is written for a whole ``SpectralEstimate``. The document is assembled field by field
from named scalars and properties - it never calls ``model_dump`` on an array-bearing model.

**Two plans, two fingerprints.** The default row set spans two reproducibility sittings, each a
realization of its own plan, so a bare ``plan_fingerprint`` cannot stand for both. The document
carries an explicit per-pass map ``plan_fingerprints`` **and** a documented aggregate
``plan_fingerprint`` (SHA-256 over the canonical JSON of that map, the repository's plan-hash
form), so a single recorded value still binds the whole row set while each pass keeps its own.

**Descriptive, never a floor - plan §4 is published, with the condition it is a repeat of.** The
design asks for a within-sitting repeat spread over the *repeated recordings of one condition*, as
its own row set. The committed sweep does not expose the plan's condition on a cell, but the
*acquisition* does: every decoded point binds to its job, and that job carries the run-wide
condition triple ``(burst_length, emissions_per_profile, prf_us)``, its ``kind``, and the point's
planned window pair ``(resolution_mm, window_gates)``. Those four scalars are forwarded through
:class:`~udv_echo_process.analysis.sparse_spectral_capability.CommittedView` - the accessor that
already owns the row set - so a group is keyed by ``(pass, kind, condition, resolution_mm,
window_gates)`` and every member of a group was acquired under one whole condition on one window. That
is what makes the spread a repeat of one condition rather than an average over several.

The committed set resolves into **6 repeated conditions per sitting, 12 across the two**, holding
**44 recordings** (**88 cells**); the recordings whose condition was acquired once - the
``cc1/cc2/cc3/cc4`` contrasts - are **singletons with no repeat**, and their **16 cells are
excluded**, not averaged in. The spread is published as its own JSON row set (:data:`REPEAT_SPREAD_RULE`):
per group, view and native gate, the member cells' own ``Phi`` and their descriptive min, max,
range and count. It is descriptive only - **never a floor or a resolvability threshold** -, no
condition or sitting is ranked, and no effect is labelled. No exploratory datum - an expected
fraction, a smoke observation, a per-sitting mean - is quoted, asserted or checked against
anywhere.

**Two precisions, stated separately.** The CSV rounds ``band_fraction`` to
:data:`FRACTION_DECIMALS` decimals and every other float to :data:`NUMBER_SIGNIFICANT_DIGITS`
significant digits; a *positive* fraction too small to survive those decimals is a refusal, never a
published zero. The JSON carries each float at its full double-precision value (Python's
shortest round-tripping repr) - a lossless copy, not a rounded one - and is written strictly
(``allow_nan=False``), so a non-finite value fails the run before any artefact is written rather
than becoming invalid JSON.

**Publication safety.** ``table_sha256`` is the repository's canonical LF digest
(:func:`~udv_echo_process.analysis._floor_documents.table_digest`) of the CSV bytes staged beside
the document, and it is populated only in the write path. The writer refuses when a check fails,
refuses any destination inside the repository that is not the plan's designated publish root
:data:`REPORT_DIR` (and any destination that is the repository root or one of its ancestors), and
refuses to overwrite a file beside the artefacts that is not one of its own - so no frozen tree, no
repository README and no hand-written file is clobbered. A **relative** destination is anchored at
the repository root, never the working directory, so the plan's own ``reports/sparse-signal``
resolves to the same tree wherever the command is run from; an absolute destination (a scratch
tree a caller owns) is used as given.

The three files are **staged beside the destination and moved into place one at a time**, each
``os.replace`` atomic on its own. That is not a transaction, and this module does not claim one:
if a rename fails partway the members already renamed hold the new bytes while the rest hold the
previous files, so the directory can be left holding a *mixed* set. What makes that detectable is
``table_sha256``: the document binds the table's exact bytes, so a reader who recomputes the CSV
digest finds a table that is not the document's. Staging means a build, a serialization or a
staging failure - the ordinary failure - leaves the destination as it was; the rename loop is the
one step that is not all-or-nothing. A lock beside the destination serializes (or refuses) a
concurrent publication into the same directory, staged temporary files are unique per run and
fsynced before any rename, and a leftover stage file or lock from an interrupted run is refused by
name rather than written over.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydantic import model_validator

from udv_echo_process.analysis import _floor_documents
from udv_echo_process.analysis._sparse_view import ViewProvenance
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES, PassRef
from udv_echo_process.analysis.sparse_periodogram import SpectralVerdict
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_admission import SpectralAdmission
from udv_echo_process.analysis.sparse_spectral_capability import (
    PROBE_TARGETS,
    committed_window_views,
)
from udv_echo_process.analysis.sparse_spectral_characterization import (
    DEFAULT_LOW_HZ,
    FRACTION_PRECISION,
    BandFractionError,
    BandFractionState,
    CellSpectralCharacterization,
    characterization_of_view,
)
from udv_echo_process.analysis.sparse_spectral_support import TimebaseCharacterization
from udv_echo_process.analysis.sparse_target_support import TargetFrequencySupport
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

__all__ = [
    "ARTEFACT_ID",
    "ARTEFACT_NAMES",
    "CSV_COLUMNS",
    "CSV_NAME",
    "DOC_NAME",
    "EXTRA_FROZEN_REPORT_DIRS",
    "FRACTION_DECIMALS",
    "GATE_RULE",
    "JSON_PRECISION_RULE",
    "LOCK_NAME",
    "NUMBER_SIGNIFICANT_DIGITS",
    "PLAN_FINGERPRINT_RULE",
    "PUBLISHED_VIEWS",
    "README_NAME",
    "README_TITLE",
    "REPEAT_CONDITION_KEY",
    "REPEAT_SPREAD_RULE",
    "REPORT_DIR",
    "RepeatCondition",
    "RepeatGroup",
    "RepeatMember",
    "RepeatMemberValue",
    "RepeatSpreadRow",
    "RepeatSpreadSummary",
    "SparseSignalReport",
    "SparseSignalReportError",
    "build_sparse_signal_report",
    "document",
    "document_text",
    "readme_text",
    "report_main",
    "table_text",
    "write_sparse_signal_report",
]

#: The plan's designated publish root (`sparse-signal-analysis-plan.md`, 249-253). SA2.4 starts
#: it with explicitly SA2.4-named files (plan D1); a later synthesis may add its own.
REPORT_DIR = Path("reports/sparse-signal")

#: The document's own artefact id, the identity a reader (and this writer's own ownership check)
#: uses to tell one of these documents from a hand-written file of the same name.
ARTEFACT_ID = "reports/sparse-signal/sa2-4-spectral-characterization"

#: The three artefact names, fixed so a reader of the plan can name them without reading code.
CSV_NAME = "sa2-4-spectral-characterization.csv"
DOC_NAME = "sa2-4-spectral-characterization.json"
README_NAME = "README.md"

#: The three names as one tuple, in publication order. The lock, the stage scan and the
#: ownership check all iterate it, so a fourth artefact would be a change here rather than a
#: missed site.
ARTEFACT_NAMES: tuple[str, ...] = (CSV_NAME, DOC_NAME, README_NAME)

#: The lock file a publication holds beside the artefacts. Created exclusively, so a second run
#: into the same directory is refused rather than racing this one's rename loop; removed when the
#: run ends or fails. A leftover lock means a run was interrupted and nobody should guess whether
#: it is still working - the operator removes it.
LOCK_NAME = ".sa2-4-spectral-characterization.publish-lock"

#: The README's first line, the marker the ownership check recognises (see :func:`_owned_file`).
README_TITLE = "# SA2.4 - committed-data spectral characterization (scalar report)"

#: The fraction's published precision, in decimals. Fixed here so the document states one
#: precision rather than the writer choosing it per run; S1 owns the constant's meaning.
FRACTION_DECIMALS = FRACTION_PRECISION

#: Every *other* float's published precision, in significant digits. A fixed significant-digit
#: rule keeps whole axes legible (a rate of 65.819 Hz) while still carrying an effective interval
#: of 0.01519 s and a parsed error of 8.6e-16 without inventing trailing zeros.
NUMBER_SIGNIFICANT_DIGITS = 12

#: The gate rule the report's rows obey, stated as the accessor that owns the question rather
#: than as a re-derived mask (plan §1, D4).
GATE_RULE = (
    "one row per cell x supported gate: the gates of a cell are exactly "
    "WindowView.supported_columns - the accessor that owns the question - enumerated in native "
    "depth order, never a re-derived mask and never a hand-picked subset. The report records the "
    "count per cell and asserts it against ViewProvenance.supported_gates."
)

#: The aggregate plan fingerprint's rule, as the arithmetic a reader can reproduce. The row set
#: spans two passes with two plans, so the aggregate covers the whole set while each pass keeps
#: its own fingerprint beside it.
PLAN_FINGERPRINT_RULE = (
    "plan_fingerprints maps each selected pass's own name to that pass's plan fingerprint, as "
    "the pass's own plan file hashes (RunPlan.plan_fingerprint). plan_fingerprint is the "
    "aggregate binding the whole row set: 'sha256:' + SHA-256 over the canonical JSON "
    "(sort_keys=True, separators=(',', ':'), ASCII) of that {pass_name: fingerprint} map, the "
    "same canonical-JSON form the repository hashes a run plan with. A single fingerprint cannot "
    "stand for two plans, and a bare one would bind the report to one sitting while reading as "
    "if it bound both."
)

#: The frozen report trees the plan fixes for SA2.4 (plan §5). Three are a committed pass's own
#: ``report_dir``, read from :data:`~udv_echo_process.analysis.sparse_passes.COMMITTED_PASSES` and
#: never restated here; ``reports/mixer-sensitivity-analysis`` is a frozen tree with no ``PassRef``
#: of its own, so it is named once, here, rather than left out of the guard by omission (the
#: omission an adversarial review found). A destination inside any of these is refused.
EXTRA_FROZEN_REPORT_DIRS: tuple[Path, ...] = (
    Path("reports/mixer-sensitivity-analysis"),
)

#: The two views the capability row set is built over, in the order the plan introduces them. The
#: repeat spread publishes a row per view, so the two are named once here and reused by the
#: document's ``views`` constants and by every group's cell count - a third view would be a change
#: here rather than a group count derived somewhere else.
PUBLISHED_VIEWS: tuple[str, ...] = ("primary-comparison", "full-record")

#: The whole condition a repeat group is keyed by, as the fields a reader compares. Named once so
#: the document, the rule and the writer's own grouping all spell the key the same way.
REPEAT_CONDITION_KEY: tuple[str, ...] = (
    "pass",
    "kind",
    "condition",
    "resolution_mm",
    "window_gates",
)

#: The §4 row set's rule, as the definition a reader can reproduce. It states the key, what a
#: member is, what a row carries, and - at length, because this is the claim the spread is most
#: likely to be misread as - that it is descriptive and never a floor.
REPEAT_SPREAD_RULE = (
    "plan §4's within-sitting repeat spread, as its own row set. A group is every recording of "
    "one pass acquired under one whole condition, keyed by "
    "(pass, kind, condition, resolution_mm, window_gates): the condition is the job's run-wide "
    "triple (burst_length, emissions_per_profile, prf_us), kind is the job's kind, and "
    "resolution_mm/window_gates are the point's planned window pair - all four forwarded, "
    "scalar-only, through committed_window_views, so a group is one condition on one window and "
    "never an average over several. window_gates is the planned native gate count of the window "
    "(the window's own dimension), never the cell's supported-gate row count. A recording whose "
    "condition was acquired once has no repeat and is excluded (the cc1/cc2/cc3/cc4 contrasts "
    "are exactly those singletons). For one group, one view and one native gate index the report "
    "states every member's own band_fraction at that gate (null where the member's axis was "
    "refused or its total power is zero - an undefined ratio is not a measured zero), the count "
    "n of members whose fraction is defined there, and the descriptive min, max and range of "
    "those n values. It is descriptive only: not a screening floor, not a resolvability "
    "threshold, no condition or sitting is ranked, and no effect is labelled."
)

#: The JSON's own precision rule, stated beside the CSV's (plan §5). The two are deliberately
#: different: the CSV is the fixed-precision table, the JSON is the lossless document, and a
#: single "floats are written at a stated fixed precision" sentence would be false of one of them.
JSON_PRECISION_RULE = (
    "Two precisions, stated separately. The CSV rounds band_fraction to fraction_decimals "
    "decimals and every other float to number_significant_digits significant digits, and a "
    "positive fraction that would round to a published zero is refused. The JSON carries every "
    "float at its full double-precision value (Python's shortest round-tripping repr), never "
    "rounded to the CSV's precision, so the document is a lossless copy of the numbers the "
    "table rounds for display. The JSON is strict: a non-finite value is refused "
    "(allow_nan=False) and fails the run before any file is written, never serialized as NaN or "
    "Infinity."
)

#: What the report does *not* do, repeated in the README beside every number it publishes.
NO_GO_LIST: tuple[str, ...] = (
    (
        "A refusal is not an absence. 'unsupported at 8.333 Hz' describes the instrument and the "
        "window; it never means that no 8.333-Hz component exists."
    ),
    (
        "No feature is labelled from the spectrum: the report locates no spectral maximum, "
        "singles out no frequency as the feature, and infers no recurrence label from a spectral "
        "shape."
    ),
    (
        "No physical mechanism is attributed. From a band-power fraction alone, genuine flow "
        "dynamics, slow drift, finite-record structure and the detrending choice are "
        "indistinguishable, so no mechanism is named and no configuration is ranked."
    ),
    (
        "No amplitude is read from a raw density maximum: the fraction is a band-integrated "
        "power ratio, not an amplitude."
    ),
    (
        "No anti-alias or transfer-function claim. Nyquist support is a sampling-support "
        "statement for the stored profile sequence only, and it matters most where a target sits "
        "closest to a band edge."
    ),
    (
        "No cross-sitting inference and no condition contrast. The report is per sitting, "
        "descriptive, and compares no sitting with another and no condition with another."
    ),
    (
        "No borrowed floor and no independence claim: the profiles and gates within a recording "
        "are not treated as independent, and no spread is read as a screening floor or a "
        "resolvability threshold."
    ),
    (
        "No floor and no effect label from the repeat spread. The §4 within-sitting spread is "
        "descriptive only: it repeats one whole condition (pass, kind, condition, resolution_mm, "
        "window_gates), states its members' own fractions with their min, max, range and count, "
        "and derives no screening floor, no resolvability threshold, no condition or sitting "
        "ranking and no labelled effect from them."
    ),
    "parseval_relative_error is a QA field, not a scientific observable.",
    "No new estimator, admission rule, threshold or tolerance is introduced by this report.",
    (
        "No exploratory datum enters the report, its checks or its wording: an expected "
        "fraction, a per-sitting mean and any assumed spread are uncommitted and are not quoted, "
        "asserted as an expectation, or checked against."
    ),
)

#: The band-state sentences the report publishes. They are fixed prose *without measurements*: a
#: refusal carries its admission's own reason (the one thing §6 requires of a refusal, because the
#: reason names the decision), and the two measured states carry this module's own statement of
#: what the state means. A number belongs in its own field, never restated inside a sentence beside
#: it - the fields carry the measurement, and prose that quoted it could drift from the field or
#: read as an expectation.
DEFINED_BAND_REASON = (
    "defined: the axis was admitted and its total power is positive, so the fraction is this "
    "gate's band power below the declared edge over its own total, a weighted cell overlap of the "
    "closed band on the one-sided grid"
)

DEFINED_ZERO_POWER_BAND_REASON = (
    "defined-zero-power: the axis was admitted and its window-normalized mean square power is "
    "zero, so the band power is the defined zero and the ratio is undefined (0/0) - a constant "
    "gate is a measurement, and this is not a refusal"
)

#: The CSV's own schema, in order. It is closed: a new column is a schema change, not a new
#: value, and every entry is a scalar of the observation unit.
#:
#: The table carries the *observation unit*: its identity, the settings that make a cell
#: comparable, the axis numbers, the gate's band-fraction numbers and the QA field. Per-cell
#: definition and metadata *text* - the estimator's full name, the taper's convention, the
#: normalization and one-sided fold, the admission's reason, the band state's own sentence and the
#: probe target rows - is stated **once per cell** in the document beside the table and once in the
#: README, never repeated on 5720 gate rows. That is the same split plan §5 makes for the target
#: rows, and it keeps the table a table of numbers rather than a table of prose.
CSV_COLUMNS: tuple[str, ...] = (
    # identity and provenance
    "pass",
    "job",
    "point_label",
    "order",
    "relative_path",
    "source_sha256",
    "view",
    "gate_index",
    "depth_mm",
    # the definitions every number was computed under
    "quantity",
    "unit",
    "psd_unit",
    "detrending",
    "low_band_hz",
    "taper_name",
    # the axis
    "profiles",
    "span_s",
    "dt_eff_s",
    "effective_sample_rate_hz",
    "nyquist_hz",
    "delta_f_hz",
    "duration_resolution_scale_hz",
    "max_relative_timing_error",
    "max_timing_error_s",
    "max_relative_interval_deviation",
    "largest_gap_ratio",
    "spectral_uniformity_tol",
    "admitted",
    "enbw_bins",
    "enbw_hz",
    # the band fraction (plan §2)
    "verdict",
    "band_state",
    "band_fraction",
    "band_power",
    "total_power",
    # QA
    "parseval_relative_error",
)


class SparseSignalReportError(ValueError):
    """The SA2.4 report cannot be built or written as asked.

    Raised for a row set that is not the committed capability scope, a cell whose gate rows do not
    agree with its own axis, a destination inside a frozen report tree or inside the repository but
    not at the designated publish root, an existing file beside the artefacts that this writer did
    not produce, a failed gate when a write was asked for, a number the declared precision cannot
    represent without publishing a false zero, a value strict JSON refuses to serialize, a missing
    analysis revision, and - re-wrapping S1's typed error - a band fraction the backend refused.
    Unlike a refusal *inside* a cell (which is a typed state and a published row), this error means
    the report itself is not the artefact the contract describes, and nothing is published.
    """


def _number(value: object, *, places: int | None = None) -> str:
    """One scalar as fixed-precision text; ``None`` is an empty cell, never ``0``.

    ``places`` is the number of *decimals* (the fraction's own precision); without it the number
    is written at :data:`NUMBER_SIGNIFICANT_DIGITS` significant digits. An undefined quantity is
    blank, because a printed zero reads as a measurement nobody made.

    Two values are refused rather than printed: a non-finite number (the table is strict data, and
    ``nan``/``inf`` cells read as measurements), and a *nonzero* number that the requested decimal
    precision would render as ``0.000...`` - printing it would publish a false zero, which is a
    worse error than a refusal (plan §2: a violation is a report failure, never a clamped number).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    number = float(value)
    if not math.isfinite(number):
        raise SparseSignalReportError(
            f"the table cannot carry the non-finite value {number!r}: a NaN or infinite cell "
            "reads as a measurement, so the run is refused instead"
        )
    if places is not None:
        text = f"{number:.{places}f}"
        if number != 0.0 and float(text) == 0.0:
            raise SparseSignalReportError(
                f"the value {number!r} is nonzero but the declared {places}-decimal precision "
                f"would print it as {text!r}, a false zero: widen the precision deliberately or "
                "leave the value unpublished, but do not publish a zero nobody measured"
            )
        return text
    return f"{number:.{NUMBER_SIGNIFICANT_DIGITS}g}"


def _flag(value: bool) -> str:
    """A boolean as the repository's table vocabulary spells it."""
    return "true" if value else "false"


class AxisScalars(ValueModel):
    """One cell's axis, as scalars read from the admission and its characterization.

    Every field is a property of the objects that own it - ``N``, span, the effective interval and
    rate, Nyquist, the bin spacing, the duration scale, the two irregularity diagnostics, the
    verdict and its reason, and the uniformity tolerance - so a reader sees the axis a fraction
    was measured on without this module re-deriving one. All gate rows of one cell carry the same
    axis by construction (one view supplies one time axis), and the report asserts that equality
    rather than assuming it.
    """

    profiles: int
    span_s: float | None
    dt_eff_s: float | None
    effective_sample_rate_hz: float | None
    nyquist_hz: float | None
    delta_f_hz: float | None
    duration_resolution_scale_hz: float | None
    max_relative_timing_error: float | None
    max_timing_error_s: float | None
    max_relative_interval_deviation: float | None
    largest_gap_ratio: float | None
    spectral_uniformity_tol: float
    min_samples: int
    admitted: bool
    admission_reason: str
    estimator: str

    @classmethod
    def of(
        cls, characterization: TimebaseCharacterization, admission: SpectralAdmission
    ) -> AxisScalars:
        """Read one cell's axis off the admission that carries it, never recomputing it."""
        return cls(
            profiles=int(characterization.profiles),
            span_s=characterization.span_s,
            dt_eff_s=characterization.full_span_interval_s,
            effective_sample_rate_hz=characterization.effective_sample_rate_hz,
            nyquist_hz=characterization.nyquist_hz,
            delta_f_hz=characterization.frequency_resolution_hz,
            duration_resolution_scale_hz=characterization.duration_resolution_scale_hz,
            max_relative_timing_error=characterization.max_relative_timing_error,
            max_timing_error_s=characterization.max_timing_error_s,
            max_relative_interval_deviation=(
                characterization.max_relative_interval_deviation
            ),
            largest_gap_ratio=characterization.largest_gap_ratio,
            spectral_uniformity_tol=float(admission.spectral_uniformity_tol),
            min_samples=int(admission.min_samples),
            admitted=bool(admission.admitted),
            admission_reason=str(admission.reason),
            estimator=str(admission.estimator),
        )


class TargetRow(ValueModel):
    """One probe target's support verdict, stated once per cell (plan §3).

    A restatement of §J at the gate-resolvable level, not a second verdict: every field is read
    from one :class:`TargetFrequencySupport` the target backend returned, including the two
    separate answers (``band_supported`` for the Nyquist/cell question and ``analysis_supported``
    for the estimator question) and the reason that decided the row.
    """

    target_label: str | None
    target_hz: float
    band_supported: bool
    analysis_supported: bool
    supported: bool
    reason: str
    band_reason: str
    analysis_reason: str
    nyquist_hz: float | None
    frequency_resolution_hz: float | None
    duration_resolution_scale_hz: float | None
    cycles_in_view: float | None
    nyquist_represented: bool | None
    prospective_bin: int | None
    prospective_bin_hz: float | None
    bin_offset_hz: float | None
    bin_offset_bins: float | None
    cell_low_hz: float | None
    cell_high_hz: float | None
    resolution_bins_to_target: int | None
    actual_span_s: float | None

    @classmethod
    def of(cls, target: TargetFrequencySupport) -> TargetRow:
        """Read one target row off the backend's own result."""
        return cls(
            target_label=target.target_label,
            target_hz=float(target.target_hz),
            band_supported=bool(target.band_supported),
            analysis_supported=bool(target.analysis_supported),
            supported=bool(target.supported),
            reason=str(target.reason),
            band_reason=str(target.band_reason),
            analysis_reason=str(target.analysis_reason),
            nyquist_hz=target.nyquist_hz,
            frequency_resolution_hz=target.frequency_resolution_hz,
            duration_resolution_scale_hz=target.duration_resolution_scale_hz,
            cycles_in_view=target.cycles_in_view,
            nyquist_represented=target.nyquist_represented,
            prospective_bin=target.prospective_bin,
            prospective_bin_hz=target.prospective_bin_hz,
            bin_offset_hz=target.bin_offset_hz,
            bin_offset_bins=target.bin_offset_bins,
            cell_low_hz=target.cell_low_hz,
            cell_high_hz=target.cell_high_hz,
            resolution_bins_to_target=target.resolution_bins_to_target,
            actual_span_s=target.actual_span_s,
        )


class GateRow(ValueModel):
    """One supported gate of one cell: its identity and its band-fraction scalars.

    ``fraction``, ``band_power`` and ``total_power`` are exactly what S1's
    :class:`LowFrequencyBandFraction` carries, with the three states kept apart: a refusal has all
    three ``None`` (an axis that was not measured), a defined zero has ``band_power == 0.0`` with
    ``fraction is None`` (0/0), and a defined row carries the ratio of its own two powers.
    """

    gate_index: int
    depth_mm: float
    verdict: SpectralVerdict
    band_state: BandFractionState
    band_fraction: float | None
    band_power: float | None
    total_power: float | None
    band_reason: str
    parseval_relative_error: float | None
    enbw_bins: float | None
    enbw_hz: float | None


#: The relative slack a spread row's own arithmetic is checked to. ``max - min`` on the two values
#: the row carries is exact in IEEE arithmetic, so this guards against a hand-built row rather
#: than loosening a real comparison.
SPREAD_REL_TOL = 1e-9


class RepeatCondition(ValueModel):
    """The run-wide condition a job records at: the design's comparison triple.

    ``burst_length``, ``emissions_per_profile`` and ``prf_us`` are dialog-only in the acquisition
    layer - a point cannot write them - so a job *is* the triple it holds them at, and a repeat of
    one condition is a repeat of the *whole* triple rather than of one field of it.
    """

    burst_length: int
    emissions_per_profile: int
    prf_us: float

    @property
    def as_triple(self) -> tuple[int, int, float]:
        """The condition's key form, as ``committed_window_views`` forwards it."""
        return (
            int(self.burst_length),
            int(self.emissions_per_profile),
            float(self.prf_us),
        )


class RepeatMember(ValueModel):
    """One recording of a repeat group, by its job and its own point label.

    A point label alone does not identify a recording - ``ctrl-begin`` is a label of several jobs -
    so a member is named by the pair, which is the pass's own identity for the recording.
    """

    job: str
    point_label: str


class RepeatMemberValue(ValueModel):
    """One member's own band fraction at one gate: its label and the number, or its absence.

    ``band_fraction`` is the member cell's ``band_fraction`` at this gate, carried at full
    precision, or ``None`` where the axis was refused or its total power is zero - an undefined
    ratio, never a measured zero.
    """

    job: str
    point_label: str
    band_fraction: float | None


class RepeatGroup(ValueModel):
    """Every recording of one pass acquired under one whole condition on one window.

    ``members`` are whole recordings, in acquisition order; ``n_recordings`` counts them and
    ``n_cells`` is that count times the two published views, so a reader sees the cells the spread
    is over. ``window_gates`` is the *planned native gate count of the window* - the window's own
    dimension - and is deliberately not named ``gates``, which would read as the cell's tuple of
    supported gate rows. A group holds at least two recordings: a condition acquired once has no
    repeat, and a one-member group would present a spread where none was measured.
    """

    pass_name: str
    kind: str
    condition: RepeatCondition
    resolution_mm: float
    window_gates: int
    members: tuple[RepeatMember, ...]
    n_recordings: int
    n_cells: int

    @model_validator(mode="after")
    def _check_the_group_is_a_same_condition_set(self) -> RepeatGroup:
        labels = [(member.job, member.point_label) for member in self.members]
        if self.n_recordings != len(labels):
            raise SparseSignalReportError(
                f"repeat group {self.pass_name}/{self.kind}/{self.condition.as_triple}/"
                f"{self.resolution_mm}/{self.window_gates}: n_recordings is {self.n_recordings} "
                f"but it names {len(labels)} member(s)"
            )
        if self.n_recordings < 2:
            raise SparseSignalReportError(
                f"repeat group {self.pass_name}/{self.kind}/{self.condition.as_triple}/"
                f"{self.resolution_mm}/{self.window_gates} holds {self.n_recordings} "
                "recording(s): a condition acquired once has no repeat, so it is a singleton and "
                "is excluded from the §4 row set rather than published as a spread of one"
            )
        if len(set(labels)) != len(labels):
            raise SparseSignalReportError(
                f"repeat group {self.pass_name}/{self.kind}/{self.condition.as_triple}/"
                f"{self.resolution_mm}/{self.window_gates} names a recording twice: {labels}"
            )
        if self.n_cells != self.n_recordings * len(PUBLISHED_VIEWS):
            raise SparseSignalReportError(
                f"repeat group {self.pass_name}/{self.kind}/{self.condition.as_triple}/"
                f"{self.resolution_mm}/{self.window_gates}: {self.n_cells} cell(s) against "
                f"{self.n_recordings} recording(s) on {len(PUBLISHED_VIEWS)} view(s)"
            )
        if self.window_gates < 1 or not (
            math.isfinite(self.resolution_mm) and self.resolution_mm > 0.0
        ):
            raise SparseSignalReportError(
                f"repeat group {self.pass_name}/{self.kind}/{self.condition.as_triple}: the "
                f"window pair ({self.resolution_mm!r} mm, {self.window_gates!r} gates) is not a "
                "window the design acquired"
            )
        return self


class RepeatSpreadRow(ValueModel):
    """One group's descriptive spread of ``band_fraction`` at one view and one native gate.

    ``members`` are every member cell's own value at this gate, in acquisition order; ``n`` counts
    the members whose fraction is *defined* there, and ``min``/``max``/``range`` summarize those n
    values and no others. With no defined member the three are ``None`` - an empty spread is not a
    zero - while one defined member gives the measured range ``0.0``: a repeat that did not vary,
    not a missing number.
    """

    pass_name: str
    kind: str
    condition: RepeatCondition
    resolution_mm: float
    window_gates: int
    view: str
    gate_index: int
    depth_mm: float
    members: tuple[RepeatMemberValue, ...]
    n: int
    min: float | None
    max: float | None
    range: float | None

    @model_validator(mode="after")
    def _check_the_row_is_the_members_own_summary(self) -> RepeatSpreadRow:
        if self.gate_index < 0:
            raise SparseSignalReportError(
                f"a repeat-spread row carries a negative gate index {self.gate_index}"
            )
        if self.view not in PUBLISHED_VIEWS:
            raise SparseSignalReportError(
                f"a repeat-spread row names view {self.view!r}; the published views are "
                f"{list(PUBLISHED_VIEWS)}"
            )
        if self.window_gates < 1 or not (math.isfinite(self.depth_mm)):
            raise SparseSignalReportError(
                "a repeat-spread row carries a non-finite depth or a window with no gate"
            )
        defined: list[float] = []
        for member in self.members:
            value = member.band_fraction
            if value is None:
                continue
            if not math.isfinite(value) or not (0.0 <= value <= 1.0 + SPREAD_REL_TOL):
                raise SparseSignalReportError(
                    f"repeat-spread member {member.job}/{member.point_label} carries a fraction "
                    f"{value!r} outside [0, 1]"
                )
            defined.append(float(value))
        if self.n != len(defined):
            raise SparseSignalReportError(
                f"repeat-spread row {self.pass_name}/{self.condition.as_triple}/{self.view}/"
                f"gate {self.gate_index}: n is {self.n} but {len(defined)} member(s) carry a "
                f"defined fraction of {len(self.members)}"
            )
        if not defined:
            if self.min is not None or self.max is not None or self.range is not None:
                raise SparseSignalReportError(
                    f"repeat-spread row {self.pass_name}/{self.condition.as_triple}/{self.view}/"
                    f"gate {self.gate_index}: no member carries a defined fraction, so the "
                    "summary must be three None values rather than a zero nobody measured"
                )
            return self
        low, high = min(defined), max(defined)
        if self.min != low or self.max != high:
            raise SparseSignalReportError(
                f"repeat-spread row {self.pass_name}/{self.condition.as_triple}/{self.view}/"
                f"gate {self.gate_index}: the stated min/max ({self.min!r}, {self.max!r}) are not "
                f"the members' own ({low!r}, {high!r})"
            )
        if self.range != high - low:
            raise SparseSignalReportError(
                f"repeat-spread row {self.pass_name}/{self.condition.as_triple}/{self.view}/"
                f"gate {self.gate_index}: the stated range {self.range!r} is not max - min "
                f"({high - low!r})"
            )
        return self


class RepeatSpreadSummary(ValueModel):
    """Counts over the §4 row set: how many repeats, never how they read.

    ``recordings`` and ``cells`` are the members of the repeat groups and the cells they occupy;
    ``singleton_recordings``/``singleton_cells`` are the recordings whose condition was acquired
    once and the cells they occupy, published so a reader can see they were *excluded* rather than
    averaged in. No scientific reading is here - only acquisition cardinality.
    """

    groups: int
    recordings: int
    cells: int
    singleton_recordings: int
    singleton_cells: int
    spread_rows: int


class CellDocument(ValueModel):
    """One ``recording x view`` cell's document row: provenance, condition, axis, targets, gates.

    ``estimated_gate_rows`` is the count the CSV carries for this cell - one per supported gate -
    and the model refuses a cell whose gate rows disagree with it, so the two artefacts cannot
    report different row sets for one cell.

    ``kind``, ``condition``, ``resolution_mm`` and ``window_gates`` are the acquisition metadata
    forwarded through
    :class:`~udv_echo_process.analysis.sparse_spectral_capability.CommittedView`: the job's kind,
    its run-wide condition triple and the point's planned window pair. They are named scalars
    (plan §6's permitted metadata), one per cell, and they are what lets the §4 repeat spread
    group this cell by the condition it was *acquired* under rather than by the identity of the
    job it happens to sit in. ``window_gates`` is the *planned native gate count of the window* -
    the window's own dimension - and is deliberately not named ``gates``, which is this cell's
    tuple of supported gate rows.
    """

    pass_name: str
    plan_fingerprint: str
    provenance: ViewProvenance
    kind: str
    condition: RepeatCondition
    resolution_mm: float
    window_gates: int
    quantity: str
    unit: str
    psd_unit: str
    detrending: Detrending
    low_band_hz: float
    estimator_name: str
    taper_name: str
    taper_convention: str
    normalization_rule: str
    one_sided_rule: str
    low_band_rule: str
    axis: AxisScalars
    targets: tuple[TargetRow, ...] = ()
    gates: tuple[GateRow, ...] = ()

    @property
    def view(self) -> str:
        """The view label this cell was cut from, from its one provenance."""
        return self.provenance.view

    @property
    def supported_gates(self) -> int:
        """The count of supported gates the provenance states - not the row count."""
        return int(self.provenance.supported_gates)

    @property
    def repeat_key(self) -> tuple[str, str, tuple[int, int, float], float, int]:
        """The whole condition this cell was acquired under, as the §4 grouping key.

        The key :data:`REPEAT_CONDITION_KEY` names - ``(pass, kind, condition, resolution_mm,
        window_gates)`` - is what makes two cells comparable as a *repeat*: every field is an
        acquisition fact read from the cell's forwarded metadata, so two cells that share the key
        were acquired under one condition on one window, and two that differ were not.
        """
        return (
            self.pass_name,
            self.kind,
            self.condition.as_triple,
            float(self.resolution_mm),
            int(self.window_gates),
        )

    @model_validator(mode="after")
    def _check_the_cell_is_one_axis_with_one_row_per_supported_gate(
        self,
    ) -> CellDocument:
        if self.axis.profiles != self.provenance.profiles:
            raise SparseSignalReportError(
                f"{self.provenance.relative_path}: the cell's axis holds "
                f"{self.axis.profiles} profile(s) and its provenance {self.provenance.profiles}"
            )
        if len(self.gates) != self.supported_gates:
            raise SparseSignalReportError(
                f"{self.provenance.relative_path}: the cell carries {len(self.gates)} gate "
                f"row(s) against {self.supported_gates} supported gate(s)"
            )
        seen = [row.gate_index for row in self.gates]
        if (
            len(set(seen)) != len(seen)
            or seen != sorted(seen)
            or any(i < 0 for i in seen)
        ):
            raise SparseSignalReportError(
                f"{self.provenance.relative_path}: a cell's gate rows are distinct, nonnegative "
                f"and in native depth order, got {seen}"
            )
        labels = [row.target_label for row in self.targets]
        expected = [label for label, _frequency in PROBE_TARGETS]
        if labels != expected:
            raise SparseSignalReportError(
                f"{self.provenance.relative_path}: a cell states its probe targets once each, in "
                f"{expected}, got {labels}"
            )
        for row in self.gates:
            if row.verdict is SpectralVerdict.REFUSED_AXIS:
                if not (
                    row.band_state is BandFractionState.REFUSED_AXIS
                    and row.band_fraction is None
                    and row.band_power is None
                    and row.total_power is None
                ):
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} carries verdict "
                        f"{row.verdict.value!r} with a band state of "
                        f"{row.band_state.value!r} and a numeric fraction; a refusal carries "
                        "three None values and no zero"
                    )
            elif row.verdict is not SpectralVerdict.DEFINED:
                raise SparseSignalReportError(
                    f"{self.provenance.relative_path}: unknown gate verdict {row.verdict!r}"
                )
            elif row.band_state is BandFractionState.REFUSED_AXIS:
                raise SparseSignalReportError(
                    f"{self.provenance.relative_path}: gate {row.gate_index} is a defined "
                    "spectrum whose band state reads as a refusal: the two are different answers"
                )
            elif row.band_state is BandFractionState.DEFINED_ZERO_POWER:
                if row.band_power != 0.0 or row.total_power != 0.0:
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} is a defined "
                        "zero power and must carry two exact zeros"
                    )
                if row.band_fraction is not None:
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} is a defined "
                        "zero power, whose fraction is 0/0 and therefore undefined"
                    )
            else:
                if (
                    row.band_fraction is None
                    or row.band_power is None
                    or row.total_power is None
                ):
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} is a defined "
                        "fraction and must carry the fraction and the two powers it is one ratio "
                        "of"
                    )
                if not (0.0 <= row.band_fraction <= 1.0 + 1e-9):
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} carries a "
                        f"fraction {row.band_fraction!r} outside the unit interval"
                    )
                if row.band_power > row.total_power * (1.0 + 1e-9):
                    raise SparseSignalReportError(
                        f"{self.provenance.relative_path}: gate {row.gate_index} carries a band "
                        f"power {row.band_power!r} above its total {row.total_power!r}"
                    )
        return self


class Summary(ValueModel):
    """Counts over the published row set: acquisition cardinality, never a scientific reading."""

    cells: int
    gate_rows: int
    admitted_cells: int
    refused_cells: int
    defined_gates: int
    defined_zero_power_gates: int
    refused_axis_gates: int
    cells_by_pass: dict[str, int]
    cells_by_view: dict[str, int]
    target_supported_by_label: dict[str, int]
    target_band_supported_by_label: dict[str, int]


class SparseSignalReport(ValueModel):
    """The built SA2.4 report: the cells, the repeat spread, the checks, the digests and constants.

    A ``ValueModel`` holding scalars and scalar-only rows, so the whole document round-trips
    through JSON without an array anywhere. ``ok`` is the gate: every check true. ``table_sha256``
    is empty until the table has been written, because the digest *is* a property of those bytes.

    ``repeat_groups``/``repeat_spread``/``repeat_spread_summary`` are plan §4's own row set: the
    repeated conditions the committed set actually holds, keyed by the whole acquisition condition
    (see :data:`REPEAT_SPREAD_RULE`), and the descriptive spread of ``Phi`` across each group's
    cells. They are descriptive only - no floor, no threshold, no ranked condition or sitting.
    """

    study: str
    analysis_commit: str
    plan_fingerprint: str
    plan_fingerprints: dict[str, str]
    table_name: str
    table_sha256: str
    low_band_hz: float
    fraction_decimals: int
    number_significant_digits: int
    detrending: Detrending
    views: tuple[str, ...]
    quantity: str
    unit: str
    psd_unit: str
    gate_rule: str
    plan_fingerprint_rule: str
    probe_targets: tuple[tuple[str, float], ...]
    checks: dict[str, bool]
    cells: tuple[CellDocument, ...]
    summary: Summary
    repeat_spread_rule: str
    repeat_groups: tuple[RepeatGroup, ...]
    repeat_spread: tuple[RepeatSpreadRow, ...]
    repeat_spread_summary: RepeatSpreadSummary

    @property
    def ok(self) -> bool:
        """The report's gate: every check holds."""
        return all(self.checks.values())

    @property
    def failed_checks(self) -> tuple[str, ...]:
        """The failed check names, in declaration order, empty when the gate holds."""
        return tuple(name for name, ok in self.checks.items() if not ok)

    def csv_rows(self) -> list[dict[str, str]]:
        """The table's rows as scalar text, one per ``cell x supported gate``.

        Every cell of one axis carries the same axis text by construction, and the builder's check
        asserts it; the rows are built here from the same cell objects the document quotes, so the
        table and the document cannot disagree about a cell.
        """
        rows: list[dict[str, str]] = []
        for cell in self.cells:
            provenance = cell.provenance
            axis = cell.axis
            for gate in cell.gates:
                rows.append(
                    {
                        "pass": cell.pass_name,
                        "job": provenance.job,
                        "point_label": provenance.point_label,
                        "order": str(int(provenance.order)),
                        "relative_path": provenance.relative_path,
                        "source_sha256": provenance.source_sha256,
                        "view": cell.view,
                        "gate_index": str(int(gate.gate_index)),
                        "depth_mm": _number(gate.depth_mm),
                        "quantity": cell.quantity,
                        "unit": cell.unit,
                        "psd_unit": cell.psd_unit,
                        "detrending": Detrending(cell.detrending).value,
                        "low_band_hz": _number(cell.low_band_hz),
                        "taper_name": cell.taper_name,
                        "profiles": str(int(axis.profiles)),
                        "span_s": _number(axis.span_s),
                        "dt_eff_s": _number(axis.dt_eff_s),
                        "effective_sample_rate_hz": _number(
                            axis.effective_sample_rate_hz
                        ),
                        "nyquist_hz": _number(axis.nyquist_hz),
                        "delta_f_hz": _number(axis.delta_f_hz),
                        "duration_resolution_scale_hz": _number(
                            axis.duration_resolution_scale_hz
                        ),
                        "max_relative_timing_error": _number(
                            axis.max_relative_timing_error
                        ),
                        "max_timing_error_s": _number(axis.max_timing_error_s),
                        "max_relative_interval_deviation": _number(
                            axis.max_relative_interval_deviation
                        ),
                        "largest_gap_ratio": _number(axis.largest_gap_ratio),
                        "spectral_uniformity_tol": _number(
                            axis.spectral_uniformity_tol
                        ),
                        "admitted": _flag(axis.admitted),
                        "enbw_bins": _number(gate.enbw_bins),
                        "enbw_hz": _number(gate.enbw_hz),
                        "verdict": SpectralVerdict(gate.verdict).value,
                        "band_state": BandFractionState(gate.band_state).value,
                        "band_fraction": _number(
                            gate.band_fraction, places=self.fraction_decimals
                        ),
                        "band_power": _number(gate.band_power),
                        "total_power": _number(gate.total_power),
                        "parseval_relative_error": _number(
                            gate.parseval_relative_error
                        ),
                    }
                )
        return rows


def table_text(model: SparseSignalReport) -> str:
    """The CSV's exact text: fixed schema, LF endings, one trailing newline.

    Written through ``csv.writer`` with a single-``\\n`` line terminator so a checkout's platform
    cannot change the bytes, and every value is already scalar text.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in model.csv_rows():
        writer.writerow([row[column] for column in CSV_COLUMNS])
    return buffer.getvalue()


def _axis_document(axis: AxisScalars) -> dict[str, object]:
    """One axis as named scalars, explicitly - no model dump, no array path."""
    return {
        "profiles": int(axis.profiles),
        "span_s": axis.span_s,
        "dt_eff_s": axis.dt_eff_s,
        "effective_sample_rate_hz": axis.effective_sample_rate_hz,
        "nyquist_hz": axis.nyquist_hz,
        "delta_f_hz": axis.delta_f_hz,
        "duration_resolution_scale_hz": axis.duration_resolution_scale_hz,
        "max_relative_timing_error": axis.max_relative_timing_error,
        "max_timing_error_s": axis.max_timing_error_s,
        "max_relative_interval_deviation": axis.max_relative_interval_deviation,
        "largest_gap_ratio": axis.largest_gap_ratio,
        "spectral_uniformity_tol": axis.spectral_uniformity_tol,
        "min_samples": int(axis.min_samples),
        "admitted": bool(axis.admitted),
        "admission_reason": axis.admission_reason,
        "estimator": axis.estimator,
    }


def _condition_document(condition: RepeatCondition) -> dict[str, object]:
    """One run-wide condition triple as named scalars."""
    return {
        "burst_length": int(condition.burst_length),
        "emissions_per_profile": int(condition.emissions_per_profile),
        "prf_us": condition.prf_us,
    }


def _repeat_member_document(member: RepeatMember) -> dict[str, object]:
    """One group member's label as named scalars."""
    return {"job": member.job, "point_label": member.point_label}


def _repeat_group_document(group: RepeatGroup) -> dict[str, object]:
    """One repeat group as named scalars: its key, its members and its counts."""
    return {
        "pass": group.pass_name,
        "kind": group.kind,
        "condition": _condition_document(group.condition),
        "resolution_mm": group.resolution_mm,
        "window_gates": int(group.window_gates),
        "members": [_repeat_member_document(member) for member in group.members],
        "n_recordings": int(group.n_recordings),
        "n_cells": int(group.n_cells),
    }


def _repeat_row_document(row: RepeatSpreadRow) -> dict[str, object]:
    """One repeat-spread row as named scalars: its key, its members' own values and its summary."""
    return {
        "pass": row.pass_name,
        "kind": row.kind,
        "condition": _condition_document(row.condition),
        "resolution_mm": row.resolution_mm,
        "window_gates": int(row.window_gates),
        "view": row.view,
        "gate_index": int(row.gate_index),
        "depth_mm": row.depth_mm,
        "members": [
            {
                "job": member.job,
                "point_label": member.point_label,
                "band_fraction": member.band_fraction,
            }
            for member in row.members
        ],
        "n": int(row.n),
        "min": row.min,
        "max": row.max,
        "range": row.range,
    }


def _target_document(row: TargetRow) -> dict[str, object]:
    """One probe target row as named scalars."""
    return {
        "target_label": row.target_label,
        "target_hz": row.target_hz,
        "band_supported": bool(row.band_supported),
        "analysis_supported": bool(row.analysis_supported),
        "supported": bool(row.supported),
        "reason": row.reason,
        "band_reason": row.band_reason,
        "analysis_reason": row.analysis_reason,
        "nyquist_hz": row.nyquist_hz,
        "frequency_resolution_hz": row.frequency_resolution_hz,
        "duration_resolution_scale_hz": row.duration_resolution_scale_hz,
        "cycles_in_view": row.cycles_in_view,
        "nyquist_represented": row.nyquist_represented,
        "prospective_bin": row.prospective_bin,
        "prospective_bin_hz": row.prospective_bin_hz,
        "bin_offset_hz": row.bin_offset_hz,
        "bin_offset_bins": row.bin_offset_bins,
        "cell_low_hz": row.cell_low_hz,
        "cell_high_hz": row.cell_high_hz,
        "resolution_bins_to_target": row.resolution_bins_to_target,
        "actual_span_s": row.actual_span_s,
    }


def _gate_document(row: GateRow) -> dict[str, object]:
    """One gate row as named scalars."""
    return {
        "gate_index": int(row.gate_index),
        "depth_mm": row.depth_mm,
        "verdict": SpectralVerdict(row.verdict).value,
        "band_state": BandFractionState(row.band_state).value,
        "band_fraction": row.band_fraction,
        "band_power": row.band_power,
        "total_power": row.total_power,
        "band_reason": row.band_reason,
        "parseval_relative_error": row.parseval_relative_error,
        "enbw_bins": row.enbw_bins,
        "enbw_hz": row.enbw_hz,
    }


def document(model: SparseSignalReport) -> dict[str, object]:
    """The JSON document: the gate, the digests, the constants, the cells and the summary.

    Assembled field by field from named scalars. The per-cell probe target rows are stated **once
    here** and are deliberately not repeated on the CSV's per-gate rows (plan §5). ``repeat_spread``
    is the plan §4 row set: its rule, its key, the groups it was taken over and a row per group,
    view and native gate (see :data:`REPEAT_SPREAD_RULE`).
    """
    return {
        "artefact": ARTEFACT_ID,
        "study": model.study,
        "ok": model.ok,
        "checks": {name: bool(ok) for name, ok in model.checks.items()},
        "failed_checks": list(model.failed_checks),
        "analysis_commit": model.analysis_commit,
        "plan_fingerprint": model.plan_fingerprint,
        "plan_fingerprints": dict(model.plan_fingerprints),
        "plan_fingerprint_rule": model.plan_fingerprint_rule,
        "json_precision_rule": JSON_PRECISION_RULE,
        "table": model.table_name,
        "table_sha256": model.table_sha256,
        "constants": {
            "low_band_hz": model.low_band_hz,
            "detrending": Detrending(model.detrending).value,
            "views": list(model.views),
            "quantity": model.quantity,
            "unit": model.unit,
            "psd_unit": model.psd_unit,
            "probe_targets": [
                [label, frequency] for label, frequency in model.probe_targets
            ],
            "fraction_decimals": int(model.fraction_decimals),
            "number_significant_digits": int(model.number_significant_digits),
            "gate_rule": model.gate_rule,
            "low_band_rule": model.cells[0].low_band_rule if model.cells else None,
        },
        "repeat_spread_rule": model.repeat_spread_rule,
        "repeat_condition_key": list(REPEAT_CONDITION_KEY),
        "cells": [
            {
                "pass": cell.pass_name,
                "plan_fingerprint": cell.plan_fingerprint,
                "job": cell.provenance.job,
                "point_label": cell.provenance.point_label,
                "order": int(cell.provenance.order),
                "relative_path": cell.provenance.relative_path,
                "source_sha256": cell.provenance.source_sha256,
                "view": cell.view,
                "view_rule": cell.provenance.view_rule,
                "kind": cell.kind,
                "condition": _condition_document(cell.condition),
                "resolution_mm": cell.resolution_mm,
                "window_gates": int(cell.window_gates),
                "profiles": int(cell.provenance.profiles),
                "native_gates": int(cell.provenance.native_gates),
                "supported_gates": int(cell.provenance.supported_gates),
                "native_depth_extent_mm": list(cell.provenance.native_depth_extent_mm),
                "pass_support_mm": list(cell.provenance.pass_support_mm),
                "participating_depth_extent_mm": list(
                    cell.provenance.participating_depth_extent_mm
                ),
                "window_s": cell.provenance.window_s,
                "declared_window_s": cell.provenance.declared_window_s,
                "quantity": cell.quantity,
                "unit": cell.unit,
                "psd_unit": cell.psd_unit,
                "detrending": Detrending(cell.detrending).value,
                "low_band_hz": cell.low_band_hz,
                "estimator_name": cell.estimator_name,
                "taper_name": cell.taper_name,
                "taper_convention": cell.taper_convention,
                "normalization_rule": cell.normalization_rule,
                "one_sided_rule": cell.one_sided_rule,
                "axis": _axis_document(cell.axis),
                "targets": [_target_document(row) for row in cell.targets],
                "gates": [_gate_document(row) for row in cell.gates],
            }
            for cell in model.cells
        ],
        "repeat_groups": [
            _repeat_group_document(group) for group in model.repeat_groups
        ],
        "repeat_spread": [_repeat_row_document(row) for row in model.repeat_spread],
        "repeat_spread_summary": model.repeat_spread_summary.model_dump(mode="json"),
        "summary": model.summary.model_dump(mode="json"),
    }


def document_text(model: SparseSignalReport) -> str:
    """The JSON document's exact text: indented, LF, one trailing newline, strictly finite.

    ``allow_nan=False`` is the point of this function: a NaN or an infinity in any cell makes
    ``json.dumps`` raise, and the raise is re-typed here so a run that would publish invalid JSON
    fails as *this* module's refusal, before any artefact is written, rather than as a bare
    ``ValueError`` halfway through publication.
    """
    try:
        rendered = json.dumps(document(model), indent=2, allow_nan=False)
    except ValueError as exc:
        raise SparseSignalReportError(
            f"the document holds a value strict JSON cannot carry ({exc}); a non-finite number "
            "is never serialized, so the run is refused before any file is written"
        ) from exc
    return rendered + "\n"


def _gates_of(cell: CellSpectralCharacterization) -> tuple[GateRow, ...]:
    """One cell's gate rows, read off S1's own per-gate rows.

    The band fraction's three states are carried verbatim, so a refused axis keeps its identity
    row with no number and a defined zero keeps its measured zero. The *reason* is the state's own
    statement and never a second copy of the numbers beside it: a refusal carries its admission's
    own reason, which is the decision §6 requires on the record, and the two measured states carry
    this module's fixed sentences - so no sentence in the report restates a measurement that the
    fields already carry.
    """
    rows: list[GateRow] = []
    for gate in cell.gates:
        fraction = gate.band_fraction
        state = BandFractionState(fraction.state)
        if state is BandFractionState.REFUSED_AXIS:
            reason = str(fraction.reason)
        elif state is BandFractionState.DEFINED_ZERO_POWER:
            reason = DEFINED_ZERO_POWER_BAND_REASON
        else:
            reason = DEFINED_BAND_REASON
        rows.append(
            GateRow(
                gate_index=int(gate.gate_index),
                depth_mm=float(gate.depth_mm),
                verdict=SpectralVerdict(gate.verdict),
                band_state=state,
                band_fraction=fraction.fraction,
                band_power=fraction.band_power,
                total_power=fraction.total_power,
                band_reason=reason,
                parseval_relative_error=gate.parseval_relative_error,
                enbw_bins=gate.enbw_bins,
                enbw_hz=gate.enbw_hz,
            )
        )
    return tuple(rows)


def _cell_document(
    cell: CellSpectralCharacterization,
    *,
    pass_name: str,
    plan_fingerprint: str,
    kind: str,
    condition: RepeatCondition,
    resolution_mm: float,
    window_gates: int,
) -> CellDocument:
    """One cell as the report's own cell document, everything read from S1's result.

    The four acquisition fields are forwarded from the entry's own
    :class:`~udv_echo_process.analysis.sparse_spectral_capability.CommittedView` - not re-read
    from the pass or the view - so a cell's condition key is the sweep's own statement about it.
    """
    return CellDocument(
        pass_name=pass_name,
        plan_fingerprint=plan_fingerprint,
        provenance=cell.provenance,
        kind=kind,
        condition=condition,
        resolution_mm=resolution_mm,
        window_gates=window_gates,
        quantity=cell.quantity,
        unit=cell.unit,
        psd_unit=cell.psd_unit,
        detrending=Detrending(cell.detrending),
        low_band_hz=float(cell.low_hz),
        estimator_name=cell.estimator_name,
        taper_name=cell.taper_name,
        taper_convention=cell.taper_convention,
        normalization_rule=cell.normalization_rule,
        one_sided_rule=cell.one_sided_rule,
        low_band_rule=cell.low_band_rule,
        axis=AxisScalars.of(cell.admission.characterization, cell.admission),
        targets=tuple(TargetRow.of(target) for target in cell.targets),
        gates=_gates_of(cell),
    )


def _summary(cells: Sequence[CellDocument]) -> Summary:
    """Counts over the published rows: how many observations, never how they read."""
    gates = [gate for cell in cells for gate in cell.gates]
    by_state = {state: 0 for state in BandFractionState}
    for gate in gates:
        by_state[BandFractionState(gate.band_state)] += 1
    cells_by_pass: dict[str, int] = {}
    cells_by_view: dict[str, int] = {}
    for cell in cells:
        cells_by_pass[cell.pass_name] = cells_by_pass.get(cell.pass_name, 0) + 1
        cells_by_view[cell.view] = cells_by_view.get(cell.view, 0) + 1
    supported: dict[str, int] = {}
    band_supported: dict[str, int] = {}
    for label, _frequency in PROBE_TARGETS:
        supported[label] = 0
        band_supported[label] = 0
    for cell in cells:
        for target in cell.targets:
            if target.target_label is None:
                continue
            if target.supported:
                supported[target.target_label] = (
                    supported.get(target.target_label, 0) + 1
                )
            if target.band_supported:
                band_supported[target.target_label] = (
                    band_supported.get(target.target_label, 0) + 1
                )
    return Summary(
        cells=len(cells),
        gate_rows=len(gates),
        admitted_cells=sum(1 for cell in cells if cell.axis.admitted),
        refused_cells=sum(1 for cell in cells if not cell.axis.admitted),
        defined_gates=by_state[BandFractionState.DEFINED],
        defined_zero_power_gates=by_state[BandFractionState.DEFINED_ZERO_POWER],
        refused_axis_gates=by_state[BandFractionState.REFUSED_AXIS],
        cells_by_pass=cells_by_pass,
        cells_by_view=cells_by_view,
        target_supported_by_label=supported,
        target_band_supported_by_label=band_supported,
    )


def _condition_of(triple: tuple[int, int, float]) -> RepeatCondition:
    """One forwarded condition triple as the typed condition the row set carries."""
    return RepeatCondition(
        burst_length=int(triple[0]),
        emissions_per_profile=int(triple[1]),
        prf_us=float(triple[2]),
    )


def _repeat_spread(
    cells: Sequence[CellDocument],
) -> tuple[tuple[RepeatGroup, ...], tuple[RepeatSpreadRow, ...], RepeatSpreadSummary]:
    """The §4 row set: the repeated conditions and the spread of ``Phi`` across their cells.

    Grouping is by :attr:`CellDocument.repeat_key` - the whole acquisition condition
    ``(pass, kind, condition, resolution_mm, window_gates)`` - so every member of a group was
    acquired under one condition on one window and a group is never an average over several. A key
    held by a single recording is a **singleton**: its condition was not repeated, so it is
    excluded from the spread and only counted, never published as a group of one.

    For each surviving group the rows state, per view and per native gate index, every member
    cell's own ``band_fraction`` (``None`` where the axis was refused or its total is zero) with
    ``n``, ``min``, ``max`` and ``range`` over the defined values. Members of one group share the
    window, so their native grids are the same grid; that is asserted here rather than assumed, so
    a group whose members disagreed about depth would refuse rather than align two grids by index.

    Raises:
        SparseSignalReportError: when two members of one group do not carry the same native gate
            indices or the same depth at one of them - a disagreement a shared window makes
            impossible, so its arrival means a cell was built from a different grid than its
            group's.
    """
    by_key: dict[
        tuple[str, str, tuple[int, int, float], float, int], list[CellDocument]
    ] = {}
    for cell in cells:
        by_key.setdefault(cell.repeat_key, []).append(cell)

    groups: list[RepeatGroup] = []
    rows: list[RepeatSpreadRow] = []
    group_recordings = 0
    singleton_recordings = 0
    for key in sorted(by_key):
        # One recording holds one cell per view, so the distinct (job, point label) pairs are the
        # recordings the key spans - a *member* is a recording, not a cell.
        members: dict[tuple[str, str], list[CellDocument]] = {}
        for cell in by_key[key]:
            members.setdefault(
                (cell.provenance.job, cell.provenance.point_label), []
            ).append(cell)
        if len(members) < 2:
            singleton_recordings += len(members)
            continue
        ordered = sorted(
            members.items(),
            key=lambda item: (
                min(int(cell.provenance.order) for cell in item[1]),
                item[0],
            ),
        )
        condition = _condition_of(key[2])
        groups.append(
            RepeatGroup(
                pass_name=key[0],
                kind=key[1],
                condition=condition,
                resolution_mm=float(key[3]),
                window_gates=int(key[4]),
                members=tuple(
                    RepeatMember(job=label[0], point_label=label[1])
                    for label, _ in ordered
                ),
                n_recordings=len(ordered),
                n_cells=len(ordered) * len(PUBLISHED_VIEWS),
            )
        )
        group_recordings += len(ordered)
        by_view: dict[str, dict[tuple[str, str], CellDocument]] = {}
        for label, member_cells in ordered:
            for cell in member_cells:
                by_view.setdefault(cell.view, {})[label] = cell
        for view in PUBLISHED_VIEWS:
            view_cells = by_view.get(view, {})
            if len(view_cells) != len(ordered):
                raise SparseSignalReportError(
                    f"repeat group {key}: {len(view_cells)} of {len(ordered)} recording(s) carry "
                    f"the {view!r} view; a repeated condition is repeated on both views"
                )
            gate_values: dict[
                int, dict[tuple[str, str], tuple[float, float | None]]
            ] = {}
            for label, cell in view_cells.items():
                for gate in cell.gates:
                    gate_values.setdefault(int(gate.gate_index), {})[label] = (
                        float(gate.depth_mm),
                        gate.band_fraction,
                    )
            for index in sorted(gate_values):
                per_member = gate_values[index]
                if set(per_member) != set(view_cells):
                    missing = sorted(set(view_cells) - set(per_member))
                    raise SparseSignalReportError(
                        f"repeat group {key}/{view}: gate {index} is missing on {missing}, so the "
                        "group's members do not share one native grid"
                    )
                depth = per_member[ordered[0][0]][0]
                for label, (member_depth, _fraction) in per_member.items():
                    if abs(member_depth - depth) > SPREAD_REL_TOL:
                        raise SparseSignalReportError(
                            f"repeat group {key}/{view}: gate {index} is at {member_depth!r} mm on "
                            f"{label} and {depth!r} mm on {ordered[0][0]}, so the members are not "
                            "on one native grid and their values cannot be aligned by index"
                        )
                member_values = tuple(
                    RepeatMemberValue(
                        job=label[0],
                        point_label=label[1],
                        band_fraction=per_member[label][1],
                    )
                    for label, _ in ordered
                )
                defined = [
                    float(value.band_fraction)
                    for value in member_values
                    if value.band_fraction is not None
                ]
                rows.append(
                    RepeatSpreadRow(
                        pass_name=key[0],
                        kind=key[1],
                        condition=condition,
                        resolution_mm=float(key[3]),
                        window_gates=int(key[4]),
                        view=view,
                        gate_index=int(index),
                        depth_mm=depth,
                        members=member_values,
                        n=len(defined),
                        min=min(defined) if defined else None,
                        max=max(defined) if defined else None,
                        range=(max(defined) - min(defined)) if defined else None,
                    )
                )

    summary = RepeatSpreadSummary(
        groups=len(groups),
        recordings=group_recordings,
        cells=group_recordings * len(PUBLISHED_VIEWS),
        singleton_recordings=singleton_recordings,
        singleton_cells=singleton_recordings * len(PUBLISHED_VIEWS),
        spread_rows=len(rows),
    )
    return tuple(groups), tuple(rows), summary


def _aggregate_fingerprint(fingerprints: Mapping[str, str]) -> str:
    """The aggregate plan fingerprint: canonical JSON of the per-pass map, through SHA-256.

    The same canonical-JSON form the repository hashes a run plan with, so a reader reproduces the
    value from the map printed beside it (see :data:`PLAN_FINGERPRINT_RULE`).
    """
    canonical = json.dumps(
        dict(fingerprints), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _frozen_report_dirs() -> tuple[Path, ...]:
    """Every frozen report tree the plan fixes (plan §5): a slice must not enter one.

    The three committed passes' own ``report_dir``s come from the pass catalog and are never
    restated here; ``reports/mixer-sensitivity-analysis`` is a frozen tree with no ``PassRef`` of
    its own and is carried by :data:`EXTRA_FROZEN_REPORT_DIRS`, so it cannot be dropped by
    omission (the omission an adversarial review found).
    """
    committed = tuple(
        Path(ref.report_dir) for ref in COMMITTED_PASSES if ref.report_dir is not None
    )
    return (*committed, *EXTRA_FROZEN_REPORT_DIRS)


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or lies inside it, by resolved path."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _repository_root() -> Path:
    """The checkout this module is part of, from its own location.

    ``src/udv_echo_process/analysis/<this file>`` is four levels below the repository root, in the
    source layout the packaging tests hold this repository to. The root is read from the module's
    own path rather than from the working directory, so the guard does not move when a caller runs
    from somewhere else - which is exactly when a relative ``--report-dir`` could otherwise be
    resolved against the wrong tree.
    """
    return Path(__file__).resolve().parents[3]


def _resolve_destination(report_dir: Path) -> Path:
    """Anchor a *relative* destination at the repository root, never at the working directory.

    The plan's publish root is written relative (``reports/sparse-signal``), so a bare
    ``--report-dir`` must resolve to ``<repository>/reports/sparse-signal`` wherever the command
    is run from - a working directory is not part of the plan. An absolute destination (a scratch
    tree a caller or a test owns) is used as given, which is what lets the writer be exercised
    without touching the checkout.
    """
    candidate = Path(report_dir)
    if candidate.is_absolute():
        return candidate
    return _repository_root() / candidate


def _destination_refusal(report_dir: Path) -> str | None:
    """Why ``report_dir`` may not be published to, or ``None`` when it may.

    The rules, narrowest first: the destination may not be the repository root or an ancestor of
    it (writing ``README.md`` there would clobber the repository's own); a destination *inside* the
    repository must be exactly the plan's designated publish root :data:`REPORT_DIR`; and no
    destination may lie inside a frozen report tree. A destination outside the repository - a
    scratch directory a test or a trial run owns - is left to the caller, which is what lets the
    writer be exercised without touching the checkout.

    Resolution goes through :func:`_resolve_destination`, so a relative destination is judged
    against the repository it would actually land in rather than against the working directory.
    Returned rather than raised so the same predicate can raise here and be published as a check.
    """
    destination = _resolve_destination(report_dir).resolve()
    repository = _repository_root()
    designated = (repository / REPORT_DIR).resolve()
    if destination.exists() and not destination.is_dir():
        return (
            f"the report directory {report_dir.as_posix()!r} exists and is not a directory, so "
            "the three artefacts cannot be placed inside it"
        )
    if _inside(repository, destination):
        return (
            f"the report directory {report_dir.as_posix()!r} is the repository root or one of its "
            f"ancestors ({repository.as_posix()!r}): this writer publishes only under the plan's "
            f"designated root {REPORT_DIR.as_posix()!r} or outside the repository entirely, and "
            "would otherwise clobber the repository's own files"
        )
    if _inside(destination, repository) and destination != designated:
        return (
            f"the report directory {report_dir.as_posix()!r} lies inside the repository "
            f"({repository.as_posix()!r}) but is not the plan's designated publish root "
            f"{REPORT_DIR.as_posix()!r}: SA2.4 writes only its own files under that root and leaves "
            "every committed tree byte-unchanged"
        )
    for frozen_dir in _frozen_report_dirs():
        if _inside(destination, frozen_dir):
            return (
                f"the report directory {report_dir.as_posix()!r} lies inside the frozen tree "
                f"{frozen_dir.as_posix()!r} (plan §5): SA2.4 writes only its own files under "
                f"{REPORT_DIR.as_posix()!r} and leaves every committed report byte-unchanged"
            )
    return None


def _owned_file(destination: Path, name: str) -> bool:
    """Whether ``destination/name`` is absent, or a file this writer itself produced.

    A file is recognised by the marker its own kind carries: the CSV by its closed header, the
    document by its ``artefact`` id, the README by its fixed first line. Anything else - a
    hand-written ``README.md``, a repository file, another slice's table of the same name, a
    directory - is not ours and is left untouched, so a destination cannot quietly overwrite work
    this writer did not do.
    """
    path = destination / name
    if not path.is_file():
        return not path.exists()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    except UnicodeDecodeError:
        return False
    if name == CSV_NAME:
        first_line = text.split("\n", 1)[0]
        return first_line == ",".join(CSV_COLUMNS)
    if name == DOC_NAME:
        try:
            parsed = json.loads(text)
        except ValueError:
            return False
        return isinstance(parsed, dict) and parsed.get("artefact") == ARTEFACT_ID
    if name == README_NAME:
        return text.startswith(README_TITLE)
    return False


def _stage(destination: Path, name: str, text: str) -> Path:
    """Write one artefact beside its destination under a unique private name; fsync; return it.

    The temporary name comes from :func:`tempfile.mkstemp` in the destination directory, so two
    runs can never collide on one path and a crash cannot be confused with a live run's name. The
    bytes are flushed and ``fsync``-ed before the descriptor closes, so the rename in
    :func:`_publish` never makes a not-yet-durable file visible under the artefact's name.

    Nothing is published until every artefact has been staged: :func:`_publish` moves the staged
    files onto their final names, so a refusal or a ``json.dumps`` on the way leaves the
    destination as it was rather than holding a table whose document never arrived.
    """
    descriptor, temporary = tempfile.mkstemp(
        dir=destination, prefix=f".{name}.", suffix=".tmp"
    )
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _acquire_lock(destination: Path) -> Path:
    """Create the publication lock exclusively, or refuse naming the holder.

    Two runs publishing into one directory would interleave their three ``os.replace`` calls and
    could leave a set drawn from both - the set is not a transaction, so serialization is the
    honest guard rather than a claim the loop is atomic. ``O_CREAT | O_EXCL`` is what makes this a
    race-free *claim*: exactly one opener wins, and a loser is refused by name.

    Raises:
        SparseSignalReportError: when the lock already exists - a concurrent run holds it, or an
            interrupted one left it. The two cannot be told apart from the file alone, so neither
            is guessed at: the run refuses and the operator removes the lock once no writer holds
            it.
    """
    lock = destination / LOCK_NAME
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SparseSignalReportError(
            f"{lock.as_posix()!r} already exists: another publication into "
            f"{destination.as_posix()!r} is in progress, or a previous run was interrupted before "
            "it could release this lock. Two runs would interleave their files and the set is not "
            "a transaction, so this run refuses rather than racing; remove the lock only once no "
            "writer holds it."
        ) from exc
    os.close(descriptor)
    return lock


def _stale_temporaries(destination: Path) -> tuple[Path, ...]:
    """Any leftover stage file a previous run left behind, by the names this writer stages.

    A stage file is named ``.<artefact>.<random>.tmp`` beside the destination, so it is found by
    the artefact prefix rather than by a filename list kept here. A stale one is evidence that a
    run was interrupted between staging and publishing - which is exactly the state a reader must
    not mistake for a complete set - so it is refused rather than silently adopted or deleted.
    """
    found: list[Path] = []
    for name in ARTEFACT_NAMES:
        found.extend(sorted(destination.glob(f".{name}.*.tmp")))
    return tuple(found)


def _publish(destination: Path, staged: Sequence[tuple[Path, str]]) -> None:
    """Move every staged artefact onto its own name, removing any leftover stage on failure.

    Each ``os.replace`` is atomic on its own - a reader never sees a half-written file under an
    artefact's name - but the loop is **not** a transaction: a failure after some renames have
    landed leaves those artefacts holding the new bytes and the rest holding the previous files,
    a mixed set this writer does not roll back (there is no backup machinery). The pair is made
    detectable instead: the document carries the table's own ``table_sha256``, so a reader who
    recomputes the CSV digest finds a table the document does not bind.
    """
    remaining = list(staged)
    try:
        for path, name in staged:
            os.replace(path, destination / name)
            remaining.remove((path, name))
    finally:
        _discard(remaining)


def _discard(staged: Sequence[tuple[Path, str]]) -> None:
    """Remove staged artefacts that were never published, so a failed run leaves no debris."""
    for path, _name in staged:
        try:
            path.unlink()
        except OSError:
            pass


#: The CSV columns that are a property of the *cell's axis* rather than of the gate row. The
#: report asserts these are byte-identical across one cell's rows: one view supplies one time
#: axis, so N, span, the effective rate, Nyquist, the bin spacing and the verdict cannot differ
#: between the gate rows of a cell (plan §1).
AXIS_COLUMNS: tuple[str, ...] = (
    "profiles",
    "span_s",
    "dt_eff_s",
    "effective_sample_rate_hz",
    "nyquist_hz",
    "delta_f_hz",
    "duration_resolution_scale_hz",
    "max_relative_timing_error",
    "max_timing_error_s",
    "max_relative_interval_deviation",
    "largest_gap_ratio",
    "spectral_uniformity_tol",
    "admitted",
    "taper_name",
)

#: The CSV columns that identify the cell a row belongs to, and the gate row within it.
CELL_KEY_COLUMNS: tuple[str, ...] = (
    "pass",
    "job",
    "point_label",
    "order",
    "relative_path",
    "view",
)


def _axis_identical_across_each_cells_rows(rows: Sequence[Mapping[str, str]]) -> bool:
    """Whether every cell's table rows carry one identical axis, from the table's own text.

    Read from the published row text rather than from the model that produced it: the claim is
    that the *table* cannot show two different axes for one cell, which is what a reader of the
    CSV would otherwise be checking by eye.
    """
    seen: dict[tuple[str, ...], tuple[tuple[str, ...], int]] = {}
    for row in rows:
        cell = tuple(row[column] for column in CELL_KEY_COLUMNS)
        axis = tuple(row[column] for column in AXIS_COLUMNS)
        previous = seen.get(cell)
        if previous is None:
            seen[cell] = (axis, 1)
        elif previous[0] != axis:
            return False
        else:
            seen[cell] = (axis, previous[1] + 1)
    return bool(seen)


def _cell_table_key(cell: CellDocument) -> tuple[str, ...]:
    """The published table key of one cell, spelled as :meth:`SparseSignalReport.csv_rows` spells it.

    Kept beside :data:`CELL_KEY_COLUMNS` so the count check compares the table's own key text with
    the cell it came from, rather than with a key derived some other way.
    """
    provenance = cell.provenance
    values: dict[str, str] = {
        "pass": cell.pass_name,
        "job": provenance.job,
        "point_label": provenance.point_label,
        "order": str(int(provenance.order)),
        "relative_path": provenance.relative_path,
        "view": cell.view,
    }
    return tuple(values[column] for column in CELL_KEY_COLUMNS)


def _published_float(text: str) -> float | None:
    """One published table cell as a number, or ``None`` for the blank an undefined value carries."""
    return None if text == "" else float(text)


def _rows_per_cell(rows: Sequence[Mapping[str, str]]) -> dict[tuple[str, ...], int]:
    """How many published rows each cell key holds, counted from the table's own text."""
    counts: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = tuple(row[column] for column in CELL_KEY_COLUMNS)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _repeat_checks(
    *,
    cells: Sequence[CellDocument],
    groups: Sequence[RepeatGroup],
    rows: Sequence[RepeatSpreadRow],
    summary: RepeatSpreadSummary,
) -> dict[str, bool]:
    """The §4 row set's own gate: the categorical and numeric invariants of the grouping.

    Read from the published objects - the cells, the groups and the rows - rather than from the
    grouping code that produced them, so a defect in that code is visible as a failed check rather
    than as a report that agrees with itself:

    * **the groups are exactly the conditions the sweep repeats** - the keys held by two or more
      recordings, with no group of one and the singletons only counted;
    * **a group is one whole condition** - every member recording of a group carries the group's
      own key, the members are distinct, and the cell count is the member count times the views;
    * **the rows cover each group, view and gate once** - and each row's members are that group's
      members, in acquisition order, carrying those members' own published fractions at that gate;
    * **each row is its members' own descriptive arithmetic** - ``n`` the defined count,
      ``min``/``max`` their extremes, ``range`` their difference, and three ``None`` values where
      no member is defined - with the summary's counts matching the groups and the rows.

    None of them screens a number against an exploratory value: they assert the grouping's own
    cardinality and arithmetic.
    """

    def key_of(
        group: RepeatGroup,
    ) -> tuple[str, str, tuple[int, int, float], float, int]:
        return (
            group.pass_name,
            group.kind,
            group.condition.as_triple,
            float(group.resolution_mm),
            int(group.window_gates),
        )

    recordings_by_key: dict[tuple, set[tuple[str, str, str]]] = {}
    key_of_recording: dict[tuple[str, str, str], tuple] = {}
    for cell in cells:
        recording = (cell.pass_name, cell.provenance.job, cell.provenance.point_label)
        recordings_by_key.setdefault(cell.repeat_key, set()).add(recording)
        key_of_recording[recording] = cell.repeat_key

    repeated_keys = {key for key, held in recordings_by_key.items() if len(held) >= 2}
    singleton_recordings = sum(
        len(held) for key, held in recordings_by_key.items() if len(held) == 1
    )
    group_keys = {key_of(group) for group in groups}

    groups_are_the_repeats = group_keys == repeated_keys and all(
        len(group.members) >= 2 for group in groups
    )

    groups_are_one_condition = bool(groups) and all(
        len({(member.job, member.point_label) for member in group.members})
        == len(group.members)
        == group.n_recordings
        and group.n_cells == group.n_recordings * len(PUBLISHED_VIEWS)
        and all(
            key_of_recording.get((group.pass_name, member.job, member.point_label))
            == key_of(group)
            for member in group.members
        )
        for group in groups
    )

    group_by_key = {key_of(group): group for group in groups}
    cell_gate_value: dict[tuple[tuple[str, str, str], str, int], float | None] = {}
    gate_indices_by_key: dict[tuple, set[int]] = {}
    for cell in cells:
        recording = (cell.pass_name, cell.provenance.job, cell.provenance.point_label)
        for gate in cell.gates:
            index = int(gate.gate_index)
            cell_gate_value[(recording, cell.view, index)] = gate.band_fraction
            gate_indices_by_key.setdefault(cell.repeat_key, set()).add(index)

    expected_cells = {
        (key, view, index)
        for key in group_keys
        for view in PUBLISHED_VIEWS
        for index in gate_indices_by_key[key]
    }
    seen_cells = {
        (
            (
                row.pass_name,
                row.kind,
                row.condition.as_triple,
                float(row.resolution_mm),
                int(row.window_gates),
            ),
            row.view,
            int(row.gate_index),
        )
        for row in rows
    }
    rows_cover_the_groups = expected_cells == seen_cells and all(
        tuple((member.job, member.point_label) for member in row.members)
        == tuple(
            (member.job, member.point_label)
            for member in group_by_key[
                (
                    row.pass_name,
                    row.kind,
                    row.condition.as_triple,
                    float(row.resolution_mm),
                    int(row.window_gates),
                )
            ].members
        )
        and all(
            member.band_fraction
            == cell_gate_value.get(
                (
                    (row.pass_name, member.job, member.point_label),
                    row.view,
                    int(row.gate_index),
                )
            )
            for member in row.members
        )
        for row in rows
    )

    def arithmetic_holds(row: RepeatSpreadRow) -> bool:
        defined = [
            member.band_fraction
            for member in row.members
            if member.band_fraction is not None
        ]
        if row.n != len(defined):
            return False
        if not defined:
            return row.min is None and row.max is None and row.range is None
        return (
            row.min == min(defined)
            and row.max == max(defined)
            and row.range == max(defined) - min(defined)
        )

    summary_holds = (
        summary.groups == len(groups)
        and summary.recordings == sum(group.n_recordings for group in groups)
        and summary.cells == sum(group.n_cells for group in groups)
        and summary.singleton_recordings == singleton_recordings
        and summary.singleton_cells == singleton_recordings * len(PUBLISHED_VIEWS)
        and summary.spread_rows == len(rows)
        and summary.recordings + summary.singleton_recordings
        == len(
            {
                (cell.pass_name, cell.provenance.job, cell.provenance.point_label)
                for cell in cells
            }
        )
    )

    return {
        "the_repeat_groups_are_the_conditions_the_sweep_repeats": groups_are_the_repeats,
        "a_repeat_group_is_one_whole_condition": groups_are_one_condition,
        "the_repeat_spread_covers_each_group_view_and_gate_once": rows_cover_the_groups,
        "the_repeat_spread_is_its_members_own_descriptive_arithmetic": bool(rows)
        and all(arithmetic_holds(row) for row in rows)
        and summary_holds,
    }


def _checks(
    *,
    cells: Sequence[CellDocument],
    rows: Sequence[Mapping[str, str]],
    model_plan_fingerprints: Mapping[str, str],
    aggregate: str,
    report_dir: Path,
) -> dict[str, bool]:
    """Every gate the report holds itself to, each one a property of what it publishes.

    The names are the report's own vocabulary and the order is fixed, so a reader can see which
    claim failed rather than only that one did. None of them screens a number against an
    exploratory value: they assert the row set's cardinality, the schema, the three-state rule,
    the unit interval, the fingerprint binding and the destination.

    **Only claims a defect could break are stated here.** A rule already enforced by a
    ``CellDocument`` validator on construction - a cell's gate rows against its own provenance, the
    two probe-target labels - is *not* repeated: a check that cannot fail is not evidence, so the
    state rules below are read off the published table's own text, which is what a reader sees,
    rather than off the model that produced it.
    """
    pass_names = {cell.pass_name for cell in cells}
    expected_passes = {
        ref.name for ref in COMMITTED_PASSES if ref.is_reproducibility_sitting
    }
    views = {cell.view for cell in cells}

    published = [
        (
            row["band_state"],
            _published_float(row["band_fraction"]),
            _published_float(row["band_power"]),
            _published_float(row["total_power"]),
        )
        for row in rows
    ]
    defined = [
        entry for entry in published if entry[0] == BandFractionState.DEFINED.value
    ]
    refused = [
        entry for entry in published if entry[0] == BandFractionState.REFUSED_AXIS.value
    ]
    zero = [
        entry
        for entry in published
        if entry[0] == BandFractionState.DEFINED_ZERO_POWER.value
    ]

    counts = _rows_per_cell(rows)
    expected_counts = {_cell_table_key(cell): cell.supported_gates for cell in cells}
    dimensions_hold = set(counts) == set(expected_counts) and all(
        counts[key] == expected for key, expected in expected_counts.items()
    )

    return {
        "one_hundred_and_four_cells": len(cells) == 104,
        "both_reproducibility_sittings_are_present": pass_names == expected_passes,
        "both_views_are_present": views == {"primary-comparison", "full-record"},
        "every_cell_publishes_one_table_row_per_supported_gate": dimensions_hold,
        "the_table_schema_is_the_closed_one": bool(rows)
        and all(set(row) == set(CSV_COLUMNS) for row in rows),
        "one_axis_per_cell": _axis_identical_across_each_cells_rows(rows),
        "the_band_edge_is_the_prespecified_one": all(
            cell.low_band_hz == DEFAULT_LOW_HZ for cell in cells
        ),
        "detrending_is_mean_on_both_views": all(
            Detrending(cell.detrending) is Detrending.MEAN for cell in cells
        ),
        "published_fractions_lie_in_the_unit_interval": bool(defined)
        and all(
            fraction is not None and 0.0 <= fraction <= 1.0 + 1e-9
            for _state, fraction, _band, _total in defined
        ),
        "a_published_band_power_is_a_part_of_its_total": bool(defined)
        and all(
            band is not None and total is not None and band <= total * (1.0 + 1e-9)
            for _state, _fraction, band, total in defined
        ),
        "a_published_fraction_is_the_ratio_of_its_published_powers": bool(defined)
        and all(
            fraction is not None
            and band is not None
            and total is not None
            and total != 0.0
            and abs(fraction - band / total) <= 1e-6 + 1e-9 * abs(band / total)
            for _state, fraction, band, total in defined
        ),
        "a_refused_axis_publishes_no_numeric_fraction": all(
            fraction is None and band is None and total is None
            for _state, fraction, band, total in refused
        ),
        "a_defined_zero_power_publishes_two_zeros_and_no_fraction": all(
            fraction is None and band == 0.0 and total == 0.0
            for _state, fraction, band, total in zero
        ),
        "plan_fingerprints_are_per_pass_and_the_aggregate_is_their_hash": bool(
            model_plan_fingerprints
        )
        and aggregate == _aggregate_fingerprint(model_plan_fingerprints),
        "the_destination_is_the_designated_root_or_outside_the_repository": (
            _destination_refusal(report_dir) is None
        ),
    }


def build_sparse_signal_report(
    *,
    passes: Iterable[PassRef] | None = None,
    analysis_commit: str | None = None,
    report_dir: Path = REPORT_DIR,
) -> SparseSignalReport:
    """Build the SA2.4 report: one cell per committed ``recording x view``, nothing written.

    The sweep is the capability query's own
    (:func:`~udv_echo_process.analysis.sparse_spectral_capability.committed_window_views`), and
    each cell is S1's :func:`~udv_echo_process.analysis.sparse_spectral_characterization
    .characterization_of_view` at the prespecified band edge, detrending, quantity and unit. Every
    number in the result is read from the objects that own it.

    Args:
        passes: the passes to sweep. ``None`` is the two reproducibility sittings the analysis
            compares (the default scope of the capability query), which is the plan's row set.
        analysis_commit: the revision to record. ``None`` reads the checkout's short git SHA, so a
            bare run records HEAD.
        report_dir: the directory the artefact is destined for; used only for the destination
            guard, never for a write here.

    Returns:
        :class:`SparseSignalReport` with ``table_sha256`` empty - the digest is a property of the
        bytes :func:`write_sparse_signal_report` writes.

    Raises:
        SparseSignalReportError: when no analysis revision can be recorded, when a cell's own
            rows contradict its axis, when the destination is inside the repository but not the
            plan's designated publish root (or is the repository root or one of its ancestors), or
            when S1 refuses a band fraction this report asked for (the backend's typed error is
            re-raised in this module's own vocabulary).
    """
    destination = _resolve_destination(report_dir)
    refusal = _destination_refusal(destination)
    if refusal is not None:
        raise SparseSignalReportError(refusal)
    commit = analysis_commit if analysis_commit is not None else current_revision()
    if not commit:
        raise SparseSignalReportError(
            "no analysis revision to record: pass --analysis-commit, or run inside a git "
            "checkout whose HEAD can be read (a bare run records HEAD)"
        )
    entries = committed_window_views(passes=passes)
    plan_fingerprints: dict[str, str] = {}
    for entry in entries:
        plan_fingerprints[entry.pass_name] = entry.plan_fingerprint
    if not plan_fingerprints:
        raise SparseSignalReportError(
            "the selected scope holds no pass, so there is no row set to characterize"
        )
    cells: list[CellDocument] = []
    for entry in entries:
        # The acquisition metadata comes from the sweep's own entry, never re-read here: a cell
        # whose condition is not forwarded cannot be placed in the §4 row set, and a missing one is
        # a refusal rather than a group key invented from the recording's identity.
        if entry.kind is None or entry.condition is None:
            raise SparseSignalReportError(
                f"{entry.view.relative_path}: the swept entry carries no forwarded acquisition "
                "condition, so this cell cannot be grouped by the condition it was acquired under"
            )
        if entry.resolution_mm is None or entry.gates is None:
            raise SparseSignalReportError(
                f"{entry.view.relative_path}: the swept entry carries no forwarded window pair "
                "(resolution_mm, gates), so this cell cannot be keyed as a repeat"
            )
        try:
            characterized = characterization_of_view(
                entry.view,
                low_hz=DEFAULT_LOW_HZ,
                detrending=Detrending.MEAN,
                quantity="axial_velocity",
                unit="mm/s",
                pass_name=entry.pass_name,
            )
        except BandFractionError as error:
            raise SparseSignalReportError(
                f"{entry.view.relative_path}: the characterization backend refused this cell "
                f"({error})"
            ) from error
        cells.append(
            _cell_document(
                characterized,
                pass_name=entry.pass_name,
                plan_fingerprint=entry.plan_fingerprint,
                kind=str(entry.kind),
                condition=_condition_of(entry.condition),
                resolution_mm=float(entry.resolution_mm),
                window_gates=int(entry.gates),
            )
        )
    aggregate = _aggregate_fingerprint(plan_fingerprints)
    repeat_groups, repeat_rows, repeat_summary = _repeat_spread(cells)
    model = SparseSignalReport(
        study=(
            "SA2.4 committed-data spectral characterization: the scalar report of "
            "docs/dop3000/sa2-4-characterization-plan.md"
        ),
        analysis_commit=str(commit),
        plan_fingerprint=aggregate,
        plan_fingerprints=dict(plan_fingerprints),
        table_name=CSV_NAME,
        table_sha256="",
        low_band_hz=float(DEFAULT_LOW_HZ),
        fraction_decimals=int(FRACTION_DECIMALS),
        number_significant_digits=int(NUMBER_SIGNIFICANT_DIGITS),
        detrending=Detrending.MEAN,
        views=PUBLISHED_VIEWS,
        quantity="axial_velocity",
        unit="mm/s",
        psd_unit="(mm/s)^2/Hz",
        gate_rule=GATE_RULE,
        plan_fingerprint_rule=PLAN_FINGERPRINT_RULE,
        probe_targets=tuple((label, value) for label, value in PROBE_TARGETS),
        checks={},
        cells=tuple(cells),
        summary=_summary(cells),
        repeat_spread_rule=REPEAT_SPREAD_RULE,
        repeat_groups=repeat_groups,
        repeat_spread=repeat_rows,
        repeat_spread_summary=repeat_summary,
    )
    rows = model.csv_rows()
    checks = _checks(
        cells=model.cells,
        rows=rows,
        model_plan_fingerprints=model.plan_fingerprints,
        aggregate=model.plan_fingerprint,
        report_dir=destination,
    )
    checks.update(
        _repeat_checks(
            cells=model.cells,
            groups=model.repeat_groups,
            rows=model.repeat_spread,
            summary=model.repeat_spread_summary,
        )
    )
    return model.model_copy(update={"checks": checks})


def write_sparse_signal_report(
    report_dir: Path = REPORT_DIR,
    *,
    passes: Iterable[PassRef] | None = None,
    analysis_commit: str | None = None,
) -> SparseSignalReport:
    """Build the report and write its three files under ``report_dir``.

    Nothing is published unless the whole report holds: the build refuses a row set, a cell, a
    destination or a fraction it cannot publish, and this function refuses again when ``ok`` is
    false, so a report whose own gate failed never reaches the disk.

    Publication is staged, and honestly so. The table is rendered in memory, staged beside the
    destination under a unique, fsynced temporary name and digested with the repository's canonical
    LF rule (:func:`~udv_echo_process.analysis._floor_documents.table_digest`), that digest is
    recorded in the document, and the document (strict JSON - a non-finite value raises here) and
    the README are staged too. Only then are the three moved onto their final names, one
    ``os.replace`` at a time. Each rename is atomic on its own, but the loop is **not** a
    transaction: a failure after some renames have landed leaves a mixed set, which this writer
    does not roll back. The ordinary failures - a build, a refusal, a serialization, a staging
    fault - leave the destination as it was, with no half-written table and no stray stage file;
    the rename loop is the one step that is not all-or-nothing, and ``table_sha256`` in the
    document is what makes a mixed set detectable. A publication lock beside the destination makes
    two runs into one directory serialize (or refuse) rather than interleave, and a leftover stage
    file or lock from an interrupted run is refused by name.

    Three files beside the artefacts are overwritten only if this writer produced them: an
    ``README.md`` the writer did not write - the repository's own, or a hand-written one - makes
    the run refuse rather than clobber it.

    Args:
        report_dir: the directory to write into. The plan's designated root, or a directory
            outside the repository (a scratch tree a test owns). A *relative* path is anchored at
            the repository root, so the plan's own default lands in the same tree wherever the
            command is run from.
        passes: the passes to sweep, as :func:`build_sparse_signal_report`.
        analysis_commit: the revision to record, as :func:`build_sparse_signal_report`.

    Returns:
        The written :class:`SparseSignalReport`, its ``table_sha256`` populated from the bytes
        that were staged.

    Raises:
        SparseSignalReportError: as :func:`build_sparse_signal_report`, and when a check fails, an
            existing file beside the artefacts is not one this writer produced, a concurrent
            publication holds the lock, or an interrupted run left a stage file or lock behind.
    """
    destination = _resolve_destination(report_dir)
    model = build_sparse_signal_report(
        passes=passes, analysis_commit=analysis_commit, report_dir=destination
    )
    if not model.ok:
        raise SparseSignalReportError(
            "the report does not hold its own gate, so nothing is written; failed checks: "
            f"{list(model.failed_checks)}"
        )
    for name in ARTEFACT_NAMES:
        if not _owned_file(destination, name):
            raise SparseSignalReportError(
                f"{(destination / name).as_posix()!r} already exists and is not an artefact this "
                "writer produced, so it is left untouched; point --report-dir at the designated "
                f"{REPORT_DIR.as_posix()!r} root or at an empty directory"
            )
    destination.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(destination)
    try:
        stale = _stale_temporaries(destination)
        if stale:
            raise SparseSignalReportError(
                "an interrupted run left staged temporary file(s) beside the destination: "
                f"{[path.as_posix() for path in stale]}. They are evidence that a previous "
                "publication was cut off between staging and publishing, so this run refuses "
                "rather than guessing whether they are safe to adopt or delete; remove them once "
                "no writer holds the directory."
            )
        staged: list[tuple[Path, str]] = []
        try:
            staged_csv = _stage(destination, CSV_NAME, table_text(model))
            staged.append((staged_csv, CSV_NAME))
            model = model.model_copy(
                update={"table_sha256": _floor_documents.table_digest(staged_csv)}
            )
            staged.append(
                (_stage(destination, DOC_NAME, document_text(model)), DOC_NAME)
            )
            staged.append(
                (_stage(destination, README_NAME, readme_text(model)), README_NAME)
            )
        except BaseException:
            _discard(staged)
            raise
        _publish(destination, staged)
    finally:
        lock.unlink(missing_ok=True)
    return model


def readme_text(model: SparseSignalReport) -> str:
    """The README: what the files are, the definitions, the digests and the no-go list.

    It states the settings a reader needs to interpret a number (band edge, detrending, taper and
    its convention, normalization, the two views), the reproduction command at the recorded
    revision, the digest rule, and - verbatim from the contract - what the report does not claim.
    The first line is :data:`README_TITLE`, the marker the writer's own ownership check recognises.
    """
    lines: list[str] = []
    lines.append(README_TITLE)
    lines.append("")
    lines.append(
        "The scalar characterization of the committed sparse recordings, per "
        "`recording x view x supported gate`. It publishes named scalar reductions of an "
        "already-published density and the scalar metadata needed to interpret them; no density "
        "array, no whole estimate and no field that follows a bin is published here."
    )
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append(
        f"- `{CSV_NAME}` - one row per `cell x supported gate` (plan §5): identity, the settings, "
        "the axis numbers, the gate's band-fraction numbers and the QA field."
    )
    lines.append(
        f"- `{DOC_NAME}` - the gate (`ok`, `checks`), the plan fingerprints and the analysis "
        "revision, the prespecified constants, one record per cell with its two probe target "
        "rows stated once, the estimator's and taper's definitions, the admission's reason, the "
        "descriptive plan §4 repeat-spread row set (its rule, groups, rows and counts), and a "
        "summary of counts."
    )
    lines.append(f"- `{README_NAME}` - this file.")
    lines.append("")
    lines.append("## The published quantity, defined")
    lines.append("")
    lines.append(
        f"- **`band_fraction`** - the low-frequency band power fraction `Phi = B / T` at a closed "
        f"`[0, {model.low_band_hz:g}] Hz` band, where `B = sum_k w_k * psd[k] * delta_f` and "
        "`w_k = clip(length(cell_k intersect [0, low_band_hz]) / length(cell_k), 0, 1)` is the "
        "overlap *fraction of the bin's own cell*, on the repository's one one-sided frequency "
        "grid and its one cell rule. `T` is the estimate's own `integrated_psd_power`, which "
        "equals the window-normalized mean-square power: the denominator is **read**, never "
        "recomputed. `Phi` is dimensionless in `[0, 1]`; a percentage is display only. The "
        "reduction is read on the repository's one **discrete** one-sided grid as this "
        "cell-overlap weighted sum - a step-function power on the fixed grid - and is **never a "
        "continuous-band integral** (plan §6)."
    )
    lines.append(
        f"- The band edge `low_band_hz = {model.low_band_hz:g} Hz` is the design's declared "
        "recurrence scale and probe target, not a located spectral feature. A different band is a "
        "different prespecified band in a new labelled table. A cell edge exactly on the band "
        "edge adds zero length, so the closed/open question changes no value."
    )
    lines.append(
        "- **`band_state`** - the three states never conflated: `defined` carries `B / T`; "
        "`defined-zero-power` is a measured zero total (a constant gate) whose ratio is `0/0` and "
        "therefore undefined, carried as `band_power == 0.0`; `refused-axis` was **not measured** "
        "and carries no fraction, no band power and no total."
    )
    lines.append(
        "- **`band_power`**, **`total_power`** - in `(mm/s)^2`; `band_power <= total_power` and "
        "the fraction is the ratio of the two numbers printed beside it."
    )
    lines.append(
        "- **`parseval_relative_error`** - a QA field: the relative difference between the "
        "integrated density and the window-normalized power, an implementation invariant of the "
        "one-sided fold at floating-point accuracy. It is not a measure of timestamp "
        "irregularity, and it is not compared across jobs."
    )
    lines.append(
        "- **the axis fields** - `profiles`, `span_s`, `dt_eff_s`, `effective_sample_rate_hz`, "
        "`nyquist_hz`, `delta_f_hz`, `duration_resolution_scale_hz`, "
        "`max_relative_timing_error`, `max_timing_error_s`, "
        "`max_relative_interval_deviation`, `largest_gap_ratio`, `spectral_uniformity_tol` and "
        "`admitted` are read from the estimate's own admission and its characterization; "
        "`delta_f_hz` is the bin spacing `fs_eff / N` and is **not** `1 / span`, which is "
        "`duration_resolution_scale_hz`. The admission's own reason is stated once per cell in "
        "the document, not repeated on every gate row."
    )
    lines.append(
        "- **the probe target rows** (JSON only, once per cell) - the 1 Hz recurrence scale and "
        "the 8.333 Hz rotor reference, each with `band_supported` (the Nyquist and cell answer) "
        "and `analysis_supported` (the estimator answer) stated separately, their reasons, the "
        "nearest bin, the bin offset and the evaluated cell edges."
    )
    lines.append(
        "- **`repeat_spread`** (JSON only, plan §4) - the within-sitting repeat spread, published "
        "as its own row set. A group is every recording of one pass acquired under one whole "
        "condition on one window, keyed by `(pass, kind, condition, resolution_mm, "
        "window_gates)` with "
        "the condition the job's run-wide `(burst_length, emissions_per_profile, prf_us)` triple; "
        "the four acquisition fields are forwarded by the capability sweep "
        "(`committed_window_views`), so a group is one condition rather than an average over "
        "several. Per group, view and native gate the row states every member cell's own "
        "`band_fraction` (`null` where it is undefined - a refused axis or a `0/0` ratio, never a "
        "measured zero), the count `n` of members whose fraction is defined there, and the "
        "descriptive `min`, `max` and `range` of those values. A recording whose condition was "
        "acquired once has no repeat and is excluded (the `cc1/cc2/cc3/cc4` contrasts); "
        f"`repeat_spread_summary` states {model.repeat_spread_summary.groups} group(s) over "
        f"{model.repeat_spread_summary.recordings} recording(s) / {model.repeat_spread_summary.cells} "
        f"cell(s) and {model.repeat_spread_summary.singleton_recordings} singleton recording(s) / "
        f"{model.repeat_spread_summary.singleton_cells} cell(s) excluded. **Descriptive only**: "
        "this is not a screening floor, not a resolvability threshold, no condition or sitting is "
        "ranked, and no effect is labelled."
    )
    lines.append("")
    lines.append("## Field glossary (the closed schema)")
    lines.append("")
    lines.append(
        "Every field the CSV and the JSON publish is named below: the field set is **closed**, "
        "so a new field is a schema change rather than a new value (plan §6). Every entry is a "
        "scalar of the observation unit - a column of the table or a named scalar in the "
        "document - and none follows a bin, a sample or an element. In the document `cells[*]` "
        "is one `recording x view` and `cells[*].gates[*]` one of its supported gates."
    )
    lines.append("")
    lines.append(
        "- **per gate (one CSV row, and `cells[*].gates[*]`)** - `gate_index`, `depth_mm`, "
        "`verdict`, `band_state`, `band_fraction`, `band_power`, `total_power`, `band_reason`, "
        "`parseval_relative_error`, `enbw_bins`, `enbw_hz`."
    )
    lines.append(
        "- **cell provenance and settings (`cells[*]`)** - `pass`, `plan_fingerprint`, `job`, "
        "`point_label`, `order`, `relative_path`, `source_sha256`, `view`, `view_rule`, "
        "`quantity`, `unit`, `psd_unit`, `detrending`, `low_band_hz`, `estimator_name`, "
        "`taper_name`, `taper_convention`, `normalization_rule`, `one_sided_rule`."
    )
    lines.append(
        "- **cell window extent and acquisition condition (`cells[*]`)** - `profiles`, "
        "`native_gates`, `supported_gates`, `native_depth_extent_mm`, `pass_support_mm`, "
        "`participating_depth_extent_mm`, `window_s`, `declared_window_s`, and the condition the "
        "§4 grouping reads: `kind`, `condition.burst_length`, `condition.emissions_per_profile`, "
        "`condition.prf_us`, `resolution_mm` and `window_gates`. `window_gates` is the planned "
        "native gate count of the window - the window's own dimension - and is deliberately not "
        "the cell's `gates` row count."
    )
    lines.append(
        "- **axis (`cells[*].axis`, JSON only)** - `profiles`, `span_s`, `dt_eff_s`, "
        "`effective_sample_rate_hz`, `nyquist_hz`, `delta_f_hz`, "
        "`duration_resolution_scale_hz`, `max_relative_timing_error`, `max_timing_error_s`, "
        "`max_relative_interval_deviation`, `largest_gap_ratio`, `spectral_uniformity_tol`, "
        "`min_samples`, `admitted`, `admission_reason`, `estimator`. `min_samples` is the "
        "admission's own sample floor - the minimum profile count the axis is admitted at - "
        "quoted as metadata and read, never recomputed."
    )
    lines.append(
        "- **probe target (`cells[*].targets[*]`, JSON only)** - `target_label`, `target_hz`, "
        "`band_supported`, `analysis_supported`, `supported`, `reason`, `band_reason`, "
        "`analysis_reason`, `nyquist_hz`, `frequency_resolution_hz`, "
        "`duration_resolution_scale_hz`, `cycles_in_view`, `nyquist_represented`, "
        "`prospective_bin`, `prospective_bin_hz`, `bin_offset_hz`, `bin_offset_bins`, "
        "`cell_low_hz`, `cell_high_hz`, `resolution_bins_to_target`, `actual_span_s`."
    )
    lines.append(
        "- **plan §4 repeat row set (JSON only)** - `repeat_spread_rule`, `repeat_condition_key`, "
        "`repeat_groups`, `repeat_spread`, `repeat_spread_summary`; each group and row is keyed "
        "by `(pass, kind, condition, resolution_mm, window_gates)` and its remaining fields are "
        "the ones named above (`members`, `n_recordings`, `n_cells`; `view`, `gate_index`, "
        "`depth_mm`, `members`, `n`, `min`, `max`, `range`)."
    )
    lines.append("")
    lines.append("## Settings every number was computed under")
    lines.append("")
    lines.append(
        f"- views: `{', '.join(model.views)}` (the primary comparison and the full record)"
    )
    lines.append(f"- detrending: `{Detrending(model.detrending).value}` on both views")
    cells = model.cells
    lines.append(
        "- estimator: `{}`, taper `{}`, convention: {}".format(
            cells[0].estimator_name if cells else "",
            cells[0].taper_name if cells else "",
            cells[0].taper_convention if cells else "",
        )
    )
    lines.append(
        "- normalization: {}".format(cells[0].normalization_rule if cells else "")
    )
    lines.append(
        "- one-sided fold: {}".format(cells[0].one_sided_rule if cells else "")
    )
    lines.append(
        f"- quantity and unit: `{model.quantity}` in `{model.unit}`; density `{model.psd_unit}`"
    )
    lines.append(f"- gate rule: {model.gate_rule}")
    lines.append("")
    lines.append("## Provenance and digests")
    lines.append("")
    lines.append(f"- analysis revision: `{model.analysis_commit}`")
    lines.append(
        f"- plan fingerprint (aggregate over the row set): `{model.plan_fingerprint}`"
    )
    for name in sorted(model.plan_fingerprints):
        lines.append(
            f"- plan fingerprint of `{name}`: `{model.plan_fingerprints[name]}`"
        )
    lines.append(f"- plan fingerprint rule: {model.plan_fingerprint_rule}")
    lines.append(f"- `{CSV_NAME}` sha256: `{model.table_sha256}`")
    lines.append(
        "- the digest is the SHA-256 of the table's canonical LF bytes, so a Windows checkout "
        "with CRLF materialised on disk hashes to the same value git stores. It is populated "
        "from the bytes this run staged, not from a tree regenerated beside it."
    )
    lines.append(f"- {JSON_PRECISION_RULE}")
    lines.append(
        "- every file is UTF-8 with LF endings and exactly one trailing newline; the numbers are "
        "formatted by one fixed rule per artefact (above), so a regeneration at this revision can "
        "be compared byte for byte - that comparison is the report's own regeneration test, not a "
        "claim this file makes about bytes it did not read."
    )
    lines.append(
        "- publication is staged, and honestly so: the three files are written beside the "
        "destination under unique, fsynced temporary names and moved onto their final names one "
        "`os.replace` at a time. Each rename is atomic on its own, but the three-file set is "
        "**not** a transaction - a failure after some renames have landed can leave a mixed set, "
        "and that is left for a reader to detect rather than rolled back. What detects it is this "
        "document's `table_sha256`: recompute the `"
        + CSV_NAME
        + "` digest and compare it with "
        "the value above. The ordinary failures (a build, a refusal, a serialization or staging "
        "fault) leave the destination as it was. A publication lock beside these files makes two "
        "runs into one directory serialize rather than interleave, and an existing file this "
        "writer did not produce - or a stage file or lock an interrupted run left behind - is "
        "refused rather than overwritten."
    )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append(
        "uv run python -m udv_echo_process.cli sparse-signal-report "
        f"--analysis-commit {model.analysis_commit}"
    )
    lines.append("```")
    lines.append("")
    lines.append("## What this report does not claim")
    lines.append("")
    for item in NO_GO_LIST:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## The gate")
    lines.append("")
    for name, held in model.checks.items():
        lines.append(f"- `{name}` - {'ok' if held else 'FAILED'}")
    # No trailing blank line: every artefact ends in exactly one newline, so a reader's diff is
    # the writer's precision and not noise.
    return "\n".join(lines) + "\n"


def report_main(argv: list[str] | None = None) -> None:
    """``sparse-signal-report`` - write SA2.4's scalar characterization report.

    Two flags only, both about provenance and destination: ``--report-dir`` (default: the plan's
    designated root) and ``--analysis-commit`` (default: the checkout's HEAD). There is no band
    knob: the band edge is the prespecified constant of this table, and a different band is a new
    labelled table rather than an option here. The command exits 0 when every check holds and 1
    otherwise, naming the failures.
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-signal-report",
        description=(
            "SA2.4: the committed-data scalar spectral characterization report - one row per "
            "recording x view x supported gate, the prespecified low-frequency band power "
            "fraction, and a scalar-only JSON beside it"
        ),
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR.as_posix(),
        help="directory to write the table, the document and the README into",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help="revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    destination = _resolve_destination(Path(args.report_dir))
    try:
        model = write_sparse_signal_report(
            destination, analysis_commit=args.analysis_commit
        )
    except SparseSignalReportError as exc:
        print(f"udv-sparse-signal-report: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    summary = model.summary
    repeat = model.repeat_spread_summary
    print(
        f"cells   : {summary.cells} ({', '.join(f'{name}: {count}' for name, count in sorted(summary.cells_by_pass.items()))})"
    )
    print(
        f"gate rows: {summary.gate_rows} - defined {summary.defined_gates}, "
        f"defined-zero-power {summary.defined_zero_power_gates}, "
        f"refused-axis {summary.refused_axis_gates}"
    )
    print(
        "targets : "
        + "; ".join(
            f"{label} supported {summary.target_supported_by_label.get(label, 0)}/{summary.cells}"
            for label, _frequency in model.probe_targets
        )
    )
    print(
        f"repeats : {repeat.groups} group(s) over {repeat.recordings} recording(s) / "
        f"{repeat.cells} cell(s), {repeat.singleton_recordings} singleton recording(s) / "
        f"{repeat.singleton_cells} cell(s) excluded; {repeat.spread_rows} spread row(s)"
    )
    print(f"commit  : {model.analysis_commit}")
    print(f"plan    : {model.plan_fingerprint}")
    print(f"table   : {destination / CSV_NAME}")
    print(f"document: {destination / DOC_NAME}")
    print(f"digest  : {model.table_sha256}")
    failed = list(model.failed_checks)
    for name in failed:
        print(f"udv-sparse-signal-report: check failed: {name}", file=sys.stderr)
    print(f"checks  : {'all pass' if not failed else failed}")
    raise SystemExit(0 if model.ok else 1)
