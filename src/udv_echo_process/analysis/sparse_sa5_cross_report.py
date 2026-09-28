"""SA5's cross-sitting report writer — the four committed artifacts of the cross schema.

``docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`` (the cross-sitting analogue of
the accepted v1 within-sitting contract) fixes four files under the plan's publish root
``reports/sparse-signal/``::

    sa5-cross-sitting.npz          the per-comparison per-knot arrays            (§3-§4)
    sa5-cross-sitting.csv          the one-row-per-comparison scalar set          (§6)
    sa5-cross-sitting.json         identity, provenance, states, context, digests (§5)
    sa5-cross-sitting.README.md    units, definitions, the two digest chains     (§7)

This module is the **writer** and nothing else. It serializes the between-sitting backend's
typed, in-memory result (:class:`~udv_echo_process.analysis.sparse_sa5_cross_models.CrossSittingComparison`)
into those four files: the codec's canonical container, the JSON of §5, the 30-column CSV of
§6 and the README of §7. It performs **no** comparison arithmetic: every number is the
backend's own (the §5 diagnostics and the §6 context quotations), every state and reason is
the backend's closed vocabulary, and the only numbers this module invents are digests over the
bytes it staged.

Where each authority sits
-------------------------
* The **comparison** is the backend's:
  :func:`~udv_echo_process.analysis.sparse_sa5_cross_sitting.compare_cross_sitting` resolves the
  72 frozen keys against two already digest-verified quartets and computes every §5 diagnostic
  and the two orthogonal typed states. It runs no input read of its own here.
* The **inputs** are the input layer's:
  :func:`~udv_echo_process.analysis.sparse_sa5_cross_input.load_published_quartets` reads the two
  committed quartets from the **fixed** source root and verifies each side's whole v1 digest
  chain (README -> JSON -> NPZ/CSV), so a side the input gate refuses never reaches a byte.
* The **container** is the codec's:
  :func:`~udv_echo_process.analysis.sparse_sa5_cross_npz.encode_cross_npz` writes the canonical
  ``ZIP_STORED`` archive of NPY v1.0 members, and every §3.3 invariant (dtype, shape, mask,
  state code, finite placeholder, strictly increasing knots) is enforced there and re-checked
  here by decoding the bytes this run staged.
* The **scalar reductions** are the backend's ``Diagnostics``; the CSV copies them once,
  formatted by one rule (:func:`format` with ``".17g"``), and the JSON never repeats them.

The source root is fixed, not the output root
---------------------------------------------
The writer accepts no argument but the publish root: ``--report-dir`` redirects **outputs**
only. The two sides are the two fixed reproducibility sittings, selected by name through the
input layer **from the committed source quartets under the repository's**
``reports/sparse-signal/`` (:data:`SOURCE_DIR`, anchored at the repository root), independent of
``--report-dir``. A scratch output directory therefore never redirects the reads to quartets
copied into it, and the reversed orientation ``live1 - live2`` refuses.

Publication and refusal gate (§11)
----------------------------------
The four files are staged beside their destination under unique, fsynced temporary names and
moved onto their final names one ``os.replace`` at a time. The set is **not** a transaction: a
failure after some renames leaves a mixed set, which the digests let a reader detect rather than
roll back. An existing file is never overwritten to guess ownership — if all four files exist
and are byte-identical to this run's staged products the publication is idempotent and does
nothing; if any file is missing or differs the run refuses without replacing any existing file.
A publication lock serializes runs and is taken **before** that ownership judgement. A stage
file or lock an interrupted run left behind is refused by name, and a frozen report tree
(anchored at the repository root, never the working directory) is refused as a destination.
An **unrelated sibling bearing the cross stem** — any entry named ``sa5-cross-sitting`` or
``sa5-cross-sitting.<something>`` that is not one of this writer's four names — is refused too,
because a name that shares the stem but is not a staged product is an unrelated file of unknown
provenance the schema says never to write beside. The sibling SA2.4 files and the two v1
quartets are never candidates for replacement: this writer stages only its own four names.

Fail closed on the structural verdict (§5.2, §10)
-------------------------------------------------
The run writes **nothing** unless the structural verdict holds: every check the backend computed
must be true **except** the ancillary ``repeat_context_identity_fully_established``, and every
one of the six artifact checks must hold on the staged bytes. A false structural check is a
refusal, never a published ``ok: false``: ``ok`` is the structural verdict, so a run that could
only publish ``ok: false`` refuses and leaves the destination byte-unchanged. The ancillary
repeat-identity check is the sole exception — it is published as ``false`` and does not gate the
run, because an unverifiable repeat context is a property of context, not of the comparison. A
container the codec refuses is likewise wrapped into this writer's refusal, so a codec rejection
surfaces as a nonzero, named refusal rather than an escaping ``ValueError``.

The recorded ``generator_command`` and a scratch root
-----------------------------------------------------
``generator_command`` records the **canonical** committed-root command
(``python -m udv_echo_process.analysis.sparse_sa5_cross_report --report-dir reports/sparse-signal``),
as the v1 writer's :func:`regeneration_command` records the canonical no-destination command. It
is the command that reproduces **this artifact set at its committed root**, so it never echoes a
scratch ``--report-dir`` a test or a caller used; a scratch run is not published and its recorded
command still names the root the committed artifact belongs at. The README's *Reproduce* section
is where a scratch root belongs, and its command carries ``--report-dir "$SA5_SCRATCH"`` so the
reproduction writes outside the checkout instead of over the committed root.

Reader entry point
------------------
The writer is reached from the command line as
``python -m udv_echo_process.analysis.sparse_sa5_cross_report [--report-dir <path>]``
(:func:`cross_report_main`) — the form :func:`regeneration_command` publishes. The command
resolves the two fixed sides, compares them, and publishes the four files; it never names,
reads or writes any other sitting.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import tempfile
import warnings
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from udv_echo_process.analysis import _floor_documents
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES
from udv_echo_process.analysis.sparse_sa5_cross_input import (
    LIVE1,
    LIVE2,
    ORIENTATION,
    SITTING_NAMES,
    comparison_keys,
    effect_id,
    load_published_quartets,
)
from udv_echo_process.analysis.sparse_sa5_cross_models import (
    COMPARISON_STATES,
    LABEL_DEFERRED,
    ComparisonState,
    CrossSittingComparison,
    EffectComparison,
    RepeatContext,
    RepeatContextState,
    SideContext,
    SideProvenance,
    SparseSa5CrossSittingError,
)
from udv_echo_process.analysis.sparse_sa5_cross_npz import (
    CROSS_MEMBER_SUFFIXES,
    CrossArrays,
    CrossNpzError,
    cross_member_names,
    decode_cross_npz,
    encode_cross_npz,
)
from udv_echo_process.analysis.sparse_sa5_cross_sitting import (
    compare_cross_sitting,
)
from udv_echo_process.analysis.sparse_sa5_effects import METHOD, WEIGHTING_RULE
from udv_echo_process.analysis.sparse_sa5_npz import EFFECT_STATE_CODES
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

__all__ = [
    "ANCILLARY_CHECK",
    "ARTIFACT_CHECK_NAMES",
    "BOOLEAN_COLUMNS",
    "CHECK_ORDER",
    "CSV_COLUMNS",
    "NONVALUE_KINDS",
    "NO_GO_LIST",
    "REPORT_DIR",
    "SCHEMA_ID",
    "SOURCE_DIR",
    "STATE_MEANINGS",
    "STEM",
    "UNDEFINED_SHAPE",
    "CrossArtifacts",
    "SparseSa5CrossReportError",
    "build_cross_artifacts",
    "build_cross_report",
    "cross_report_main",
    "regeneration_command",
    "write_cross_artifacts",
    "write_cross_report",
]

#: The JSON's ``schema`` value — the cross schema's closed id (§5.1).
SCHEMA_ID = "sa5-cross-sitting/v1"

#: The file stem of the cross set (§1).
STEM = "sa5-cross-sitting"

#: The plan's publish root (§1) — the default destination.
REPORT_DIR = Path("reports/sparse-signal")

#: The **fixed** source root the two committed quartets are read from (§1). It is anchored at
#: the repository root and is independent of ``--report-dir``: a scratch output directory never
#: redirects the reads.
SOURCE_DIR = REPORT_DIR

#: The four artifact suffixes.
NPZ_SUFFIX = ".npz"
CSV_SUFFIX = ".csv"
JSON_SUFFIX = ".json"
README_SUFFIX = ".README.md"

#: The README's first line, the marker a reader recognises as this writer's own.
README_TITLE_PREFIX = "# SA5 cross-sitting agreement artifacts"

#: The one **ancillary** check of §5.2/§10. It is published like every other check but is
#: **excluded** from the structural verdict: an unverifiable repeat context is a property of
#: *context*, not of the comparison, so a false value never makes ``ok`` false and never gates
#: this writer's run.
ANCILLARY_CHECK = "repeat_context_identity_fully_established"

#: The comparison's own check names, in the order §5.2 fixes them — copied verbatim from
#: :func:`~udv_echo_process.analysis.sparse_sa5_cross_sitting.compare_cross_sitting`.
CHECK_ORDER: tuple[str, ...] = (
    "no_output_artifact_written",
    "fixed_orientation_live2_minus_live1",
    "seventy_two_comparisons",
    "every_effect_id_resolves_in_both_sittings",
    "comparison_and_label_states_kept_separate",
    "no_label_but_deferred_pending_review_is_written",
    "no_recurrence_verdict",
    ANCILLARY_CHECK,
    "repeat_context_state_isolated_from_comparison_and_label",
)

#: The schema-level artifact checks of §5.2, computed on the bytes this run staged.
ARTIFACT_CHECK_NAMES: tuple[str, ...] = (
    "npz_members_are_the_closed_set",
    "every_comparison_position_carries_its_mask_and_state",
    "comparison_rows_are_the_frozen_order",
    "no_comparison_scalar_lives_outside_the_csv",
    "source_quartets_are_byte_unchanged",
    "digests_match_the_staged_bytes",
)

#: The CSV's closed column set, in order (§6). One row per comparison, 72 rows.
CSV_COLUMNS: tuple[str, ...] = (
    "effect_id",
    "view",
    "metric",
    "contrast",
    "units",
    "grid",
    "knot_count",
    "comparison_knot_count",
    "defined_count",
    "sign_count",
    "span_mm",
    "covered_depth_mm",
    "coverage_fraction",
    "signed_depth_average",
    "rms_difference",
    "positive_count",
    "negative_count",
    "zero_count",
    "sign_agreement",
    "zero1_count",
    "zero2_count",
    "shape_correlation",
    "peak1_value",
    "peak1_depth",
    "peak2_value",
    "peak2_depth",
    "peak_localized1",
    "peak_localized2",
    "peak_displacement",
    "peaks_coincide",
)

#: The three CSV columns that render a boolean as the lowercase ``true``/``false`` token (§8).
BOOLEAN_COLUMNS: frozenset[str] = frozenset(
    ("peak_localized1", "peak_localized2", "peaks_coincide")
)

#: The CSV cells that are **comparison reductions** and therefore must have exactly one home,
#: the CSV (§5, §6). The set is the CSV's reduction columns minus the ones that also appear —
#: legitimately — as a §5.4 context quotation under the source digest (``defined_count``,
#: ``covered_depth_mm``, ``coverage_fraction``, ``signed_depth_average``) and minus the
#: structural identity mirrors that §5.3 publishes in the JSON (``units``, ``grid``,
#: ``knot_count``, ``comparison_knot_count``). No other column name may appear as a JSON key.
REDUCTION_ONLY_COLUMNS: tuple[str, ...] = (
    "sign_count",
    "span_mm",
    "rms_difference",
    "positive_count",
    "negative_count",
    "zero_count",
    "sign_agreement",
    "zero1_count",
    "zero2_count",
    "shape_correlation",
    "peak1_value",
    "peak1_depth",
    "peak2_value",
    "peak2_depth",
    "peak_localized1",
    "peak_localized2",
    "peak_displacement",
    "peaks_coincide",
)

#: The three non-value position kinds (§5.6).
NONVALUE_KINDS: tuple[str, ...] = ("shape", "peak", "peak-displacement")

#: The JSON-only non-value state label for a refused profile correlation (§5.6).
UNDEFINED_SHAPE = "undefined-shape"

#: The effect state table A of §5.4, published once so a ``state1``/``state2`` code is never
#: ambiguous. It is the codec's own table, so the code and the text cannot drift.
STATE_MEANINGS: tuple[tuple[int, str], ...] = tuple(sorted(EFFECT_STATE_CODES.items()))

#: The JSON top-level field set of §5.1 (closed).
JSON_FIELDS: frozenset[str] = frozenset(
    (
        "schema",
        "ok",
        "checks",
        "artifact_checks",
        "comparison",
        "sitting1",
        "sitting2",
        "analysis_commit",
        "generator_revision",
        "generator_command",
        "provenance",
        "state_meanings",
        "comparisons",
        "npz_members",
        "nonvalue_rows",
        "nonvalue_counts",
        "limitations",
        "weighting_rule",
        "method",
        "artifacts",
    )
)

#: The closed key set of one comparison record (§5.3).
COMPARISON_FIELDS: frozenset[str] = frozenset(
    (
        "effect_id",
        "view",
        "metric",
        "contrast",
        "grid",
        "units",
        "knot_count",
        "comparison_knot_count",
        "participant_count",
        "support_mm",
        "comparison_state",
        "comparison_reason",
        "label_state",
        "context1",
        "context2",
    )
)

#: The closed key set of one §5.4 ``SideContext``.
SIDE_CONTEXT_FIELDS: frozenset[str] = frozenset(
    (
        "sitting",
        "units",
        "rms_magnitude",
        "signed_depth_average",
        "equal_knot_average",
        "max_abs_value",
        "max_abs_depth_mm",
        "covered_depth_mm",
        "coverage_fraction",
        "defined_count",
        "undefined_alignment_count",
        "undefined_operand_count",
        "knot_count",
        "repeats",
    )
)

#: The closed key set of one §5.4 ``RepeatContext`` (plus the three state-conditional range keys).
REPEAT_FIELDS: frozenset[str] = frozenset(
    (
        "operand",
        "clause",
        "state",
        "group_condition",
        "members",
        "identity_verified",
        "identity_basis",
        "reason",
    )
)

#: The three numerical range keys a ``selected`` repeat context adds (§5.4, amendment A1).
REPEAT_RANGE_KEYS: tuple[str, ...] = ("min_value", "max_value", "spread")

#: The closed key set of one §5.4 ``RepeatContextMember``.
REPEAT_MEMBER_FIELDS: frozenset[str] = frozenset(
    ("label", "order", "job", "value", "defined_count", "state", "reason")
)

#: The closed key set of one §5.4 ``SideProvenance``.
SIDE_PROVENANCE_FIELDS: frozenset[str] = frozenset(
    (
        "sitting",
        "pass_name",
        "plan",
        "plan_fingerprint",
        "stem",
        "json_sha256",
        "npz_sha256",
        "csv_sha256",
        "checks_ok",
        "artifact_checks_ok",
    )
)

#: What this artifact does not claim (§7, §15), quoted verbatim in the README.
NO_GO_LIST: tuple[str, ...] = (
    (
        "No agreement value, verdict, ranking or label is computed: this artifact publishes "
        "the comparison's numbers and states without a recurrence verdict, so `label_state` is "
        "`deferred-pending-review` for every comparable pair and absent otherwise."
    ),
    (
        "No `p`-value, floor, optimum or causality/population claim: this is two realizations "
        "compared descriptively, never inference."
    ),
    (
        "No Stage-2 pooling and no third sitting: Stage-2 is contextual, is not a sitting, and "
        "is never bound."
    ),
    (
        "A repeat-context range is descriptive only, is not a floor and not a replicate, and is "
        "`not-like-for-like` with any effect magnitude."
    ),
    (
        "No per-knot value in the JSON or the CSV, and no comparison scalar in the JSON: the "
        "NPZ is the per-knot array's one home and the CSV the comparison scalar's, while the "
        "JSON holds identity, provenance, states, context quotations and digests."
    ),
    (
        "No ndarray in the JSON (issue #49 remains open and unsolved), and no coarser-lattice "
        "or nearest-native knot mapping."
    ),
    (
        "The two oriented effect profiles `E1`/`E2` are not re-published here: their single "
        "home is each side's own `sa5-live-N-effects.npz` under its own digest chain."
    ),
)

#: The frozen report trees a destination may never enter: the committed passes' own report
#: directories, plus the one frozen tree that carries no ``PassRef``. Restated here rather than
#: imported from the SA2.4 writer so the two writers share no mutable state.
EXTRA_FROZEN_REPORT_DIRS: tuple[Path, ...] = (
    Path("reports/mixer-sensitivity-analysis"),
)


class SparseSa5CrossReportError(ValueError):
    """The cross-sitting artifacts cannot be built or published under the schema.

    Raised for a comparison that is not the fixed ``live2 - live1`` set of 72 records, a
    ``not resolvable`` row, a closed-vocabulary drift, an artifact check that failed on the
    staged bytes, a destination that is frozen or not this writer's, an existing file this run
    did not produce, or a leftover stage file or lock. A *typed non-value* — an undefined
    comparison knot, a refused correlation, a peak that is not localized — is not this error:
    it is data, published as a state code and a non-value row.
    """


def _refuse(message: str) -> SparseSa5CrossReportError:
    """One refusal, so every raise site states its reason in the same shape."""
    return SparseSa5CrossReportError(message)


# ── identity helpers ───────────────────────────────────────────────────


def regeneration_command(report_dir: str = REPORT_DIR.as_posix()) -> str:
    """The exact command that reproduces this artifact set at the recorded revision.

    It is the runnable module-invoked form the plan's verification section names
    (``python -m udv_echo_process.analysis.sparse_sa5_cross_report --report-dir <path>``),
    **not** an inline ``python -c``. The two sides are the fixed reproducibility sittings, so
    the command takes no sitting name; ``--report-dir`` redirects outputs only and never the
    reads of the committed source quartets.

    The recorded default is the **canonical committed root**, not whichever root a caller
    happened to write to: the command published in the JSON reproduces the artifact set at the
    root the committed artifact belongs at, exactly as the v1 writer records its canonical
    no-destination command. The README's *Reproduce* section is where a scratch root belongs, and
    it adds an explicit ``--report-dir "$SA5_SCRATCH"`` so the reproduction lands outside the
    checkout.
    """
    return (
        "python -m udv_echo_process.analysis.sparse_sa5_cross_report "
        f"--report-dir {report_dir}"
    )


def _file_digest(data: bytes) -> str:
    """A published digest over **exact file bytes**: ``sha256:`` of ``data`` unchanged.

    This is the container's digest (§5.7): the NPZ is already canonical by §4, so it is hashed
    over its exact bytes and no normalization is applied. Applying the CRLF-to-LF rule of
    :func:`_canonical_digest` to binary container bytes would silently change the digest of any
    container that happens to carry the byte pair ``0x0d 0x0a``.
    """
    return _floor_documents.DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def _canonical_digest(data: bytes) -> str:
    """A published digest over canonical (LF) **text** bytes, as the repository hashes text.

    For the JSON and the CSV only — the two published files that are UTF-8 text and may be
    materialised with CRLF by a Windows checkout. It must **not** be applied to the binary
    container, whose digest is :func:`_file_digest` over its exact bytes.
    """
    return _file_digest(data.replace(b"\r\n", b"\n"))


# ── the four byte products ─────────────────────────────────────────────


# Pydantic warns that the field name ``json`` shadows the deprecated ``BaseModel.json()``
# classmethod it would otherwise inherit. The schema fixes the field name (and the tests read
# ``artifacts.json``), so the cosmetic warning is silenced around the definition only.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "json" .* shadows an attribute in parent',
        category=UserWarning,
    )

    class CrossArtifacts(ValueModel):
        """The cross set's four staged products, as bytes, plus the identity they carry.

        A frozen :class:`~udv_echo_process.models.base.ValueModel` (immutable,
        ``extra="forbid"``) holding only scalars and ``bytes``. ``files`` is the publication
        order: the NPZ and the CSV first, then the JSON that binds them, then the README that
        binds the JSON — the order a reader follows the digest chain in.
        """

        stem: str
        npz: bytes
        csv: bytes
        json: bytes
        readme: bytes

        @property
        def npz_name(self) -> str:
            """The container's file name: ``<stem>.npz``."""
            return f"{self.stem}{NPZ_SUFFIX}"

        @property
        def csv_name(self) -> str:
            """The scalar table's file name: ``<stem>.csv``."""
            return f"{self.stem}{CSV_SUFFIX}"

        @property
        def json_name(self) -> str:
            """The document's file name: ``<stem>.json``."""
            return f"{self.stem}{JSON_SUFFIX}"

        @property
        def readme_name(self) -> str:
            """The README's file name: ``<stem>.README.md``."""
            return f"{self.stem}{README_SUFFIX}"

        @property
        def names(self) -> tuple[str, ...]:
            """The four file names, in publication order."""
            return (self.npz_name, self.csv_name, self.json_name, self.readme_name)

        @property
        def files(self) -> tuple[tuple[str, bytes], ...]:
            """The four ``(name, bytes)`` pairs, in publication order."""
            return (
                (self.npz_name, self.npz),
                (self.csv_name, self.csv),
                (self.json_name, self.json),
                (self.readme_name, self.readme),
            )

        def payloads(self) -> Mapping[str, bytes]:
            """The same four products as a name → bytes mapping."""
            return dict(self.files)

        def document(self) -> dict[str, object]:
            """The JSON product, parsed back — the reader's entry point, for a test or a reader."""
            return json.loads(self.json.decode("utf-8"))


# ── the comparison domain and the NPZ records ──────────────────────────


def _is_comparable(record: EffectComparison) -> bool:
    """Whether a record carries a common comparison domain (§3)."""
    return record.comparison_state is ComparisonState.COMPARABLE


def _comparison_knot_count(record: EffectComparison) -> int:
    """``Kc`` — the number of comparison knots, the ``(Kc,)`` member shape (§3)."""
    return len(record.knots_mm)


def _require_record(record: EffectComparison) -> None:
    """Re-assert a record is the fixed schema's, never a drifted one (§5.3, §7)."""
    if record.comparison_state is ComparisonState.NOT_RESOLVABLE:
        raise _refuse(
            f"{record.effect_id}: a 'not resolvable with this design' row is never emitted "
            "(no resolvability rule is registered), so the run refuses rather than publish it"
        )
    if record.comparison_state.value not in COMPARISON_STATES:
        raise _refuse(
            f"{record.effect_id}: the comparison state {record.comparison_state.value!r} is "
            f"outside the closed vocabulary {COMPARISON_STATES}"
        )
    comparable = _is_comparable(record)
    if comparable and record.diagnostics is None:
        raise _refuse(
            f"{record.effect_id}: a comparable pair carries its §5 diagnostics"
        )
    if comparable and record.label_state != LABEL_DEFERRED:
        raise _refuse(
            f"{record.effect_id}: a comparable pair's label_state is {LABEL_DEFERRED!r}, got "
            f"{record.label_state!r}"
        )
    if not comparable and record.label_state is not None:
        raise _refuse(
            f"{record.effect_id}: a non-comparable pair carries no label_state, got "
            f"{record.label_state!r}; the two axes are separate"
        )
    if len(record.knots) != len(record.knots_mm):
        raise _refuse(
            f"{record.effect_id}: one comparison knot row per comparison depth"
        )
    if comparable:
        if not record.knots_mm:
            raise _refuse(
                f"{record.effect_id}: a comparable pair has a positive comparison knot count"
            )
        if record.support_mm is None:
            raise _refuse(
                f"{record.effect_id}: a comparable pair names its support intersection"
            )


def _cross_arrays(record: EffectComparison) -> CrossArrays:
    """One comparable record's five §3 arrays, with signed zeros preserved (§9)."""
    knots_mm = np.asarray(record.knots_mm, dtype="<f8")
    count = knots_mm.shape[0]
    difference = np.zeros(count, dtype="<f8")
    defined = np.zeros(count, dtype="<u1")
    state1 = np.zeros(count, dtype="<u1")
    state2 = np.zeros(count, dtype="<u1")
    for index, knot in enumerate(record.knots):
        state1[index] = knot.state1_code
        state2[index] = knot.state2_code
        if not knot.defined:
            # The placeholder is exactly +0.0; the arrays were zeroed with ``np.zeros``, so an
            # undefined position already carries it and a -0.0 can never masquerade as one.
            continue
        if knot.difference is None:
            raise _refuse(
                f"{record.effect_id}: a defined comparison knot carries its difference D"
            )
        defined[index] = 1
        difference[index] = float(knot.difference)
    return CrossArrays(
        effect_id=record.effect_id,
        comparison_knot_count=count,
        knots_mm=knots_mm,
        difference=difference,
        defined=defined,
        state1=state1,
        state2=state2,
    )


def _npz_records(comparison: CrossSittingComparison) -> tuple[CrossArrays, ...]:
    """The five-member records of every comparable comparison (§3, §3.1)."""
    return tuple(
        _cross_arrays(record) for record in comparison.records if _is_comparable(record)
    )


def _member_names(comparison: CrossSittingComparison) -> tuple[str, ...]:
    """The sorted closed member names of every comparable comparison (§5.5)."""
    return tuple(
        sorted(
            name
            for record in comparison.records
            if _is_comparable(record)
            for name in cross_member_names(record.effect_id)
        )
    )


# ── the CSV (§6) ───────────────────────────────────────────────────────


def _float_text(number: float) -> str:
    """One float cell: the round-trip ``format(value, ".17g")``, preserving a signed zero."""
    return format(float(number), ".17g")


def _csv_cells(record: EffectComparison) -> Mapping[str, object]:
    """One comparison's 30 CSV cells, from the backend's own reductions and the record (§6)."""
    comparable = _is_comparable(record)
    diag = record.diagnostics if comparable else None
    cells: dict[str, object] = {
        "effect_id": record.effect_id,
        "view": record.view,
        "metric": record.metric,
        "contrast": record.contrast,
        "units": record.units,
        "grid": record.grid,
        "knot_count": record.knot_count,
        "comparison_knot_count": (
            _comparison_knot_count(record) if comparable else None
        ),
        "defined_count": diag.defined_count if diag else None,
        "sign_count": diag.sign_count if diag else None,
        "span_mm": diag.span_mm if diag else None,
        "covered_depth_mm": diag.covered_depth_mm if diag else None,
        "coverage_fraction": diag.coverage_fraction if diag else None,
        "signed_depth_average": diag.signed_depth_average if diag else None,
        "rms_difference": diag.rms_difference if diag else None,
        "positive_count": diag.positive_count if diag else None,
        "negative_count": diag.negative_count if diag else None,
        "zero_count": diag.zero_count if diag else None,
        "sign_agreement": diag.sign_agreement if diag else None,
        "zero1_count": diag.zero1_count if diag else None,
        "zero2_count": diag.zero2_count if diag else None,
        "shape_correlation": diag.shape_correlation if diag else None,
        "peak1_value": diag.peak1_value if diag else None,
        "peak1_depth": diag.peak1_depth if diag else None,
        "peak2_value": diag.peak2_value if diag else None,
        "peak2_depth": diag.peak2_depth if diag else None,
        "peak_localized1": diag.peak_localized1 if diag else None,
        "peak_localized2": diag.peak_localized2 if diag else None,
        "peak_displacement": diag.peak_displacement if diag else None,
        "peaks_coincide": diag.peaks_coincide if diag else None,
    }
    missing = [column for column in CSV_COLUMNS if column not in cells]
    if missing:
        raise _refuse(
            f"{record.effect_id}: the CSV column set is closed; {missing} have no cell"
        )
    return cells


def _cell_text(value: object, *, boolean: bool) -> str:
    """One CSV cell text: a boolean token, an int as itself, a float by ``.17g``, ``None`` empty."""
    if value is None:
        return ""
    if boolean:
        if type(value) is not bool:
            raise _refuse(
                f"a CSV boolean cell is a bool or the empty field, got {value!r}"
            )
        return "true" if value else "false"
    if isinstance(value, bool):
        raise _refuse(
            "a CSV numeric cell is a number or the empty field, never a boolean"
        )
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float_text(value)
    if isinstance(value, str):
        return value
    raise _refuse(f"a CSV cell is a number or text, got {type(value).__name__}")


def _csv_text(comparison: CrossSittingComparison) -> str:
    """The 72-row scalar table, RFC 4180 quoting, LF terminators and one trailing newline (§6)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for record in comparison.records:
        cells = _csv_cells(record)
        writer.writerow(
            [
                _cell_text(cells[column], boolean=column in BOOLEAN_COLUMNS)
                for column in CSV_COLUMNS
            ]
        )
    return buffer.getvalue()


# ── non-value rows (§5.6) ──────────────────────────────────────────────


def _nonvalue_rows(record: EffectComparison) -> tuple[Mapping[str, object], ...]:
    """The typed-empty rows of one comparison, in the fixed §5.6 order.

    A ``not comparable`` comparison contributes none: its pair-level state and reason live in
    its comparison record. Otherwise the order is ``shape``, then ``peak`` (``live-1`` before
    ``live-2``), then ``peak-displacement``. A scalar whose emptiness is derivable from the
    CSV's own coverage fields is not a non-value row.
    """
    if not _is_comparable(record):
        return ()
    diag = record.diagnostics
    if diag is None:
        raise _refuse(
            f"{record.effect_id}: a comparable pair carries its §5 diagnostics"
        )
    rows: list[Mapping[str, object]] = []
    if diag.shape_correlation is None:
        rows.append(
            {
                "effect_id": record.effect_id,
                "kind": "shape",
                "side": None,
                "state": UNDEFINED_SHAPE,
                "reason": diag.shape_reason,
            }
        )
    for side, localized, reason in (
        ("live-1", diag.peak_localized1, diag.peak_reason1),
        ("live-2", diag.peak_localized2, diag.peak_reason2),
    ):
        if not localized:
            rows.append(
                {
                    "effect_id": record.effect_id,
                    "kind": "peak",
                    "side": side,
                    "state": reason,
                    "reason": reason,
                }
            )
    if diag.peak_displacement is None:
        rows.append(
            {
                "effect_id": record.effect_id,
                "kind": "peak-displacement",
                "side": None,
                "state": diag.peak_displacement_reason,
                "reason": diag.peak_displacement_reason,
            }
        )
    return tuple(rows)


def _nonvalue_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, int]]:
    """The totals by ``(state, kind)`` in the schema's nested map (§5.6)."""
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        state, kind = str(row["state"]), str(row["kind"])
        by_kind = counts.setdefault(state, {})
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {state: dict(sorted(counts[state].items())) for state in sorted(counts)}


# ── the JSON record builders (§5.3-§5.4) ───────────────────────────────


def _optional_float(value: object) -> float | None:
    """A quoted scalar as a JSON number or ``null``, never a bool."""
    return None if value is None else float(value)  # type: ignore[arg-type]


def _optional_int(value: object) -> int | None:
    """A quoted count as a JSON integer or ``null``, never a bool."""
    return None if value is None else int(value)  # type: ignore[arg-type]


def _side_provenance_document(provenance: SideProvenance) -> dict[str, object]:
    """One side's §5.4 ``SideProvenance`` record — the ten published cells."""
    document: dict[str, object] = {
        "sitting": provenance.sitting,
        "pass_name": provenance.pass_name,
        "plan": provenance.plan,
        "plan_fingerprint": provenance.plan_fingerprint,
        "stem": provenance.stem,
        "json_sha256": provenance.json_sha256,
        "npz_sha256": provenance.npz_sha256,
        "csv_sha256": provenance.csv_sha256,
        "checks_ok": bool(provenance.checks_ok),
        "artifact_checks_ok": bool(provenance.artifact_checks_ok),
    }
    if set(document) != SIDE_PROVENANCE_FIELDS:
        raise _refuse("a side provenance record lost or gained a field")
    return document


def _repeat_member_document(member: object) -> dict[str, object]:
    """One quoted repeat member (§5.4 ``RepeatContextMember``)."""
    document: dict[str, object] = {
        "label": member.label,
        "order": int(member.order),
        "job": member.job,
        "value": _optional_float(member.value),
        "defined_count": int(member.defined_count),
        "state": member.state,
        "reason": member.reason,
    }
    if set(document) != REPEAT_MEMBER_FIELDS:
        raise _refuse("a repeat member record lost or gained a field")
    return document


def _repeat_document(context: RepeatContext) -> dict[str, object]:
    """One §5.4 ``RepeatContext`` record, its numerical range keys state-conditional (A1)."""
    document: dict[str, object] = {
        "operand": context.operand,
        "clause": context.clause,
        "state": context.state.value,
        "group_condition": context.group_condition,
        "members": [_repeat_member_document(member) for member in context.members],
        "identity_verified": bool(context.identity_verified),
        "identity_basis": context.identity_basis,
        "reason": context.reason,
    }
    if context.state is RepeatContextState.SELECTED:
        # Present iff selected *and* identity proved; a selected context proves it by construction.
        if not context.identity_verified:
            raise _refuse(
                f"the {context.operand!r} repeat context is selected but not identity-verified"
            )
        document["min_value"] = _optional_float(context.min_value)
        document["max_value"] = _optional_float(context.max_value)
        document["spread"] = _optional_float(context.spread)
    elif any(getattr(context, key) is not None for key in REPEAT_RANGE_KEYS):
        raise _refuse(
            f"the {context.operand!r} repeat context is {context.state.value!r} but carries a "
            "numerical range; a non-selected context publishes no range"
        )
    expected = REPEAT_FIELDS | (
        frozenset(REPEAT_RANGE_KEYS)
        if context.state is RepeatContextState.SELECTED
        else frozenset()
    )
    if set(document) != expected:
        raise _refuse("a repeat context record lost or gained a field")
    return document


def _side_context_document(context: SideContext) -> dict[str, object]:
    """One §5.4 ``SideContext`` — the frozen context quotation plus its repeat contexts."""
    document: dict[str, object] = {
        "sitting": context.sitting,
        "units": context.units,
        "rms_magnitude": _optional_float(context.rms_magnitude),
        "signed_depth_average": _optional_float(context.signed_depth_average),
        "equal_knot_average": _optional_float(context.equal_knot_average),
        "max_abs_value": _optional_float(context.max_abs_value),
        "max_abs_depth_mm": _optional_float(context.max_abs_depth_mm),
        "covered_depth_mm": _optional_float(context.covered_depth_mm),
        "coverage_fraction": _optional_float(context.coverage_fraction),
        "defined_count": _optional_int(context.defined_count),
        "undefined_alignment_count": _optional_int(context.undefined_alignment_count),
        "undefined_operand_count": _optional_int(context.undefined_operand_count),
        "knot_count": _optional_int(context.knot_count),
        "repeats": [_repeat_document(item) for item in context.repeats],
    }
    if set(document) != SIDE_CONTEXT_FIELDS:
        raise _refuse("a side context record lost or gained a field")
    return document


def _comparison_document(record: EffectComparison) -> dict[str, object]:
    """One comparison record's closed key set (§5.3)."""
    comparable = _is_comparable(record)
    support = record.support_mm
    document: dict[str, object] = {
        "effect_id": record.effect_id,
        "view": record.view,
        "metric": record.metric,
        "contrast": record.contrast,
        "grid": record.grid,
        "units": record.units,
        "knot_count": _optional_int(record.knot_count),
        "comparison_knot_count": (
            _comparison_knot_count(record) if comparable else None
        ),
        "participant_count": _optional_int(record.participant_count),
        "support_mm": (
            None if support is None else [float(support[0]), float(support[1])]
        ),
        "comparison_state": record.comparison_state.value,
        "comparison_reason": record.comparison_reason,
        "label_state": record.label_state,
        "context1": _side_context_document(record.context1),
        "context2": _side_context_document(record.context2),
    }
    if set(document) != COMPARISON_FIELDS:
        raise _refuse("a comparison record lost or gained a field")
    return document


# ── artifact checks (§5.2) ─────────────────────────────────────────────


def _source_quartets_are_byte_unchanged(
    source_dir: Path, comparison: CrossSittingComparison
) -> bool:
    """Whether both source quartets' published bytes still hash to the recorded provenance."""
    root = Path(source_dir)
    for provenance in (comparison.provenance1, comparison.provenance2):
        stem = provenance.stem
        try:
            json_bytes = (root / f"{stem}.json").read_bytes()
            npz_bytes = (root / f"{stem}.npz").read_bytes()
            csv_bytes = (root / f"{stem}.csv").read_bytes()
        except OSError:
            return False
        if (
            _canonical_digest(json_bytes) != provenance.json_sha256
            or _file_digest(npz_bytes) != provenance.npz_sha256
            or _canonical_digest(csv_bytes) != provenance.csv_sha256
        ):
            return False
    return True


def _no_comparison_scalar_in_json(json_text: str) -> bool:
    """Whether every comparison reduction has exactly one home — the CSV (§5, §6)."""
    return all(f'"{column}":' not in json_text for column in REDUCTION_ONLY_COLUMNS)


def _artifact_checks(
    *,
    npz: bytes,
    csv_bytes: bytes,
    json_text: str,
    comparison: CrossSittingComparison,
    source_dir: Path,
    npz_digest: str,
    csv_digest: str,
) -> dict[str, bool]:
    """The six §5.2 artifact checks, each computed from the bytes this run staged."""
    expected_members = _member_names(comparison)
    with zipfile.ZipFile(io.BytesIO(npz)) as archive:
        names = archive.namelist()
    shapes = {
        record.effect_id: _comparison_knot_count(record)
        for record in comparison.records
        if _is_comparable(record)
    }
    try:
        decode_cross_npz(npz, expected=shapes)
        positions_ok = True
    except ValueError:
        positions_ok = False
    order_ok = tuple(record.effect_id for record in comparison.records) == tuple(
        effect_id(view, metric, contrast)
        for metric, view, contrast in comparison_keys()
    )
    return {
        "npz_members_are_the_closed_set": list(names) == list(expected_members),
        "every_comparison_position_carries_its_mask_and_state": bool(positions_ok),
        "comparison_rows_are_the_frozen_order": bool(order_ok),
        "no_comparison_scalar_lives_outside_the_csv": bool(
            _no_comparison_scalar_in_json(json_text)
        ),
        "source_quartets_are_byte_unchanged": bool(
            _source_quartets_are_byte_unchanged(source_dir, comparison)
        ),
        "digests_match_the_staged_bytes": bool(
            _file_digest(npz) == npz_digest
            and _canonical_digest(csv_bytes) == csv_digest
        ),
    }


# ── the four products, built from one typed comparison ─────────────────


def build_cross_artifacts(
    comparison: CrossSittingComparison,
    *,
    source_dir: Path,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> CrossArtifacts:
    """Build the cross set's four products as bytes, refusing anything the schema does not admit.

    Args:
        comparison: the run's typed result — 72 records over the two fixed sides.
        source_dir: the directory the two committed quartets were resolved from. It is re-read
            here so ``source_quartets_are_byte_unchanged`` is asserted against the published
            bytes, not merely trusted from the provenance tokens.
        analysis_commit: the revision the JSON records; defaults to the checkout's short SHA.
        generator_revision: the generator's own revision; defaults to the checkout's short SHA.

    Returns:
        :class:`CrossArtifacts` — the canonical NPZ, the strict JSON, the scalar CSV and the
        README, with the digests inside the JSON and the README already bound to the bytes.

    Raises:
        SparseSa5CrossReportError: for a comparison that is not the fixed ``live2 - live1`` set,
            a closed-vocabulary drift, a non-finite number that would reach the JSON, or an
            artifact check that fails on the staged bytes.
    """
    if not isinstance(comparison, CrossSittingComparison):
        raise _refuse(
            f"a comparison is a CrossSittingComparison, got {type(comparison).__name__}"
        )
    _require_comparison(comparison)
    commit = _revision_text(analysis_commit, "analysis_commit")
    generator = _revision_text(generator_revision, "generator_revision")
    for record in comparison.records:
        _require_record(record)

    npz_records = _npz_records(comparison)
    try:
        npz = encode_cross_npz(npz_records)
    except SparseSa5CrossReportError:
        # A §3 invariant this module re-asserted (``_cross_arrays``) is its own refusal.
        raise
    except CrossNpzError as exc:
        raise _refuse(
            "the container codec refuses the comparison's arrays "
            f"({exc}), so nothing is written"
        ) from exc
    csv_bytes = _csv_text(comparison).encode("utf-8")
    npz_digest = _file_digest(npz)
    csv_digest = _canonical_digest(csv_bytes)

    nonvalue = [row for record in comparison.records for row in _nonvalue_rows(record)]
    probe = _document(
        comparison=comparison,
        nonvalue=nonvalue,
        analysis_commit=commit,
        generator_revision=generator,
        npz_digest=npz_digest,
        csv_digest=csv_digest,
        artifact_checks={name: True for name in ARTIFACT_CHECK_NAMES},
    )
    artifact_checks = _artifact_checks(
        npz=npz,
        csv_bytes=csv_bytes,
        json_text=json.dumps(
            probe,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ),
        comparison=comparison,
        source_dir=Path(source_dir),
        npz_digest=npz_digest,
        csv_digest=csv_digest,
    )
    failed = sorted(name for name, held in artifact_checks.items() if not held)
    if failed:
        raise _refuse(
            f"the artifact checks do not hold (failed: {failed}), so nothing is written"
        )
    if set(artifact_checks) != set(ARTIFACT_CHECK_NAMES):
        raise _refuse(
            f"the artifact checks are {sorted(artifact_checks)}, the schema's six are "
            f"{sorted(ARTIFACT_CHECK_NAMES)}"
        )

    document = _document(
        comparison=comparison,
        nonvalue=nonvalue,
        analysis_commit=commit,
        generator_revision=generator,
        npz_digest=npz_digest,
        csv_digest=csv_digest,
        artifact_checks=artifact_checks,
    )
    try:
        json_text = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except ValueError as exc:
        raise _refuse(
            f"the document cannot be serialized as strict JSON ({exc}); a non-finite number "
            "fails the run before any byte is written"
        ) from exc
    json_bytes = (json_text + "\n").encode("utf-8")
    json_digest = _canonical_digest(json_bytes)

    readme = _readme_text(
        comparison=comparison,
        npz_digest=npz_digest,
        csv_digest=csv_digest,
        json_digest=json_digest,
        analysis_commit=commit,
        generator_revision=generator,
        artifact_checks=artifact_checks,
    ).encode("utf-8")

    artifacts = CrossArtifacts(
        stem=STEM, npz=npz, csv=csv_bytes, json=json_bytes, readme=readme
    )
    _verify_digest_binding(artifacts, npz_digest, csv_digest, json_digest)
    return artifacts


def _require_comparison(comparison: CrossSittingComparison) -> None:
    """Re-assert the run's identity: fixed orientation, 72 unique records in the frozen order."""
    if comparison.comparison != ORIENTATION:
        raise _refuse(
            f"the comparison is {comparison.comparison!r}, the schema fixes {ORIENTATION!r}; "
            "the reversed orientation is refused, never silently accepted"
        )
    if (comparison.sitting1, comparison.sitting2) != SITTING_NAMES:
        raise _refuse(
            f"the comparison sides are ({comparison.sitting1!r}, {comparison.sitting2!r}), the "
            f"schema fixes {SITTING_NAMES}"
        )
    if comparison.schema_id != "sa5-within-sitting-effects/v1":
        raise _refuse(
            f"the comparison names the source schema {comparison.schema_id!r}, not the v1 "
            "within-sitting schema"
        )
    keys = tuple(record.effect_id for record in comparison.records)
    expected = tuple(
        effect_id(view, metric, contrast)
        for metric, view, contrast in comparison_keys()
    )
    if keys != expected:
        raise _refuse(
            "the comparison records are not the frozen 72 keys in endpoint/contrast/interaction "
            "order"
        )
    if set(comparison.checks) != set(CHECK_ORDER):
        raise _refuse(
            f"the comparison's checks are {sorted(comparison.checks)}, the schema's nine are "
            f"{sorted(CHECK_ORDER)}; a check that moved is a schema change"
        )
    failed = sorted(
        name
        for name, held in comparison.checks.items()
        if name != ANCILLARY_CHECK and not held
    )
    if failed:
        raise _refuse(
            f"the comparison's own structural gate does not hold (failed: {failed}), so nothing "
            f"is written; ``ok`` is the structural verdict, never a published ``ok: false`` (the "
            f"sole exception is the ancillary {ANCILLARY_CHECK!r})"
        )


def _revision_text(value: str | None, name: str) -> str:
    """One revision string, defaulting to the checkout's short SHA and never to a guess."""
    if value is None:
        return current_revision() or ""
    if not isinstance(value, str):
        raise _refuse(f"{name} is a revision string, got {type(value).__name__}")
    return value


def _cross_ok(
    comparison: CrossSittingComparison, artifact_checks: Mapping[str, bool]
) -> bool:
    """The structural verdict (§10): every artifact check and every check but the ancillary one."""
    structural = all(
        held for name, held in comparison.checks.items() if name != ANCILLARY_CHECK
    )
    return bool(structural and all(artifact_checks.values()))


def _document(
    *,
    comparison: CrossSittingComparison,
    nonvalue: Sequence[Mapping[str, object]],
    analysis_commit: str,
    generator_revision: str,
    npz_digest: str,
    csv_digest: str,
    artifact_checks: Mapping[str, bool],
) -> dict[str, object]:
    """The strict-JSON document of §5, its field set closed and its every number from upstream."""
    document: dict[str, object] = {
        "schema": SCHEMA_ID,
        "ok": _cross_ok(comparison, artifact_checks),
        "checks": {name: bool(comparison.checks[name]) for name in CHECK_ORDER},
        "artifact_checks": {
            name: bool(artifact_checks[name]) for name in ARTIFACT_CHECK_NAMES
        },
        "comparison": comparison.comparison,
        "sitting1": comparison.sitting1,
        "sitting2": comparison.sitting2,
        "analysis_commit": analysis_commit,
        "generator_revision": generator_revision,
        "generator_command": regeneration_command(),
        "provenance": {
            LIVE1: _side_provenance_document(comparison.provenance1),
            LIVE2: _side_provenance_document(comparison.provenance2),
        },
        "state_meanings": {
            "effect": [{"code": code, "text": text} for code, text in STATE_MEANINGS]
        },
        "comparisons": [_comparison_document(record) for record in comparison.records],
        "npz_members": list(_member_names(comparison)),
        "nonvalue_rows": [dict(row) for row in nonvalue],
        "nonvalue_counts": _nonvalue_counts(nonvalue),
        "limitations": list(comparison.limitations),
        "weighting_rule": WEIGHTING_RULE,
        "method": METHOD,
        "artifacts": {
            "npz": {"file": f"{STEM}{NPZ_SUFFIX}", "sha256": npz_digest},
            "csv": {"file": f"{STEM}{CSV_SUFFIX}", "sha256": csv_digest},
        },
    }
    if set(document) != JSON_FIELDS:
        raise _refuse("the JSON document lost or gained a top-level field")
    return document


def _verify_digest_binding(
    artifacts: CrossArtifacts, npz_digest: str, csv_digest: str, json_digest: str
) -> None:
    """Re-check the whole chain against the staged bytes: README → JSON → NPZ + CSV."""
    readme = artifacts.readme.decode("utf-8")
    document = artifacts.document()
    recorded = document.get("artifacts")
    if not isinstance(recorded, dict):
        raise _refuse("the document publishes no artifacts object")
    try:
        npz_bound = recorded["npz"]["sha256"]  # type: ignore[index]
        csv_bound = recorded["csv"]["sha256"]  # type: ignore[index]
        npz_name = recorded["npz"]["file"]  # type: ignore[index]
        csv_name = recorded["csv"]["file"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise _refuse(
            f"the artifacts object must name both files and their digests ({exc})"
        ) from exc
    if npz_bound != npz_digest or csv_bound != csv_digest:
        raise _refuse(
            "the digests the document records are not the digests of the staged bytes"
        )
    if npz_name != artifacts.npz_name or csv_name != artifacts.csv_name:
        raise _refuse(
            f"the artifacts object names {npz_name!r}/{csv_name!r} rather than "
            f"{artifacts.npz_name!r}/{artifacts.csv_name!r}"
        )
    if json_digest not in readme:
        raise _refuse(
            f"the README does not bind the document's own canonical-LF digest {json_digest}, "
            "so the digest chain is broken"
        )
    if _canonical_digest(artifacts.json) != json_digest:
        raise _refuse("the document's own digest is unstable")
    if artifacts.npz_name not in readme or artifacts.csv_name not in readme:
        raise _refuse("the README names neither the container nor the table")


# ── the README (§7) ────────────────────────────────────────────────────


#: What each closed NPZ member means, for the README's member table (§3).
_MEMBER_MEANING: Mapping[str, str] = {
    "knots_mm": "the comparison knot depths, strictly increasing",
    "difference": "the oriented difference `D = E2 - E1` where defined, the finite placeholder "
    "`0.0` where not",
    "defined": "the common-defined mask: `1` exactly where both sides' state code is `0`, else `0`",
    "state1": "the live-1 effect state code (table A)",
    "state2": "the live-2 effect state code (table A)",
}

#: The dtype and shape of each closed member, for the README's member table (§3).
_MEMBER_SHAPE: Mapping[str, tuple[str, str]] = {
    "knots_mm": ("<f8", "(Kc,)"),
    "difference": ("<f8", "(Kc,)"),
    "defined": ("<u1", "(Kc,)"),
    "state1": ("<u1", "(Kc,)"),
    "state2": ("<u1", "(Kc,)"),
}

#: What each CSV column is, for the README's column list (§6).
_COLUMN_MEANING: Mapping[str, str] = {
    "effect_id": "`<view>__<metric>__<contrast>`, the stable key into the JSON `comparisons` list",
    "view": "`primary-comparison` or `full-record`",
    "metric": "the observable (`mean`, `std`, `mad_scaled`, `recurrence-1e-lag`, "
    "`recurrence-peak-lag`, `band_fraction`)",
    "contrast": "the bound contrast name, or `pitch_x_burst_interaction`",
    "units": "the effect's unit (`mm/s`, `s` or `dimensionless`)",
    "grid": "`corner_knots` or `emissions_knots` — the knot grid both sides were aligned on",
    "knot_count": "the mirrored source `K` (structural identity, equal on both sides)",
    "comparison_knot_count": "`Kc`, the number of native knots inside both supports' "
    "intersection — the `(Kc,)` NPZ member shape",
    "defined_count": "`|D|`, the knots where both sides are defined",
    "sign_count": "`|S|`, the common-defined knots where both effects carry a defined non-zero "
    "sign",
    "span_mm": "the comparison span (last knot − first knot, `0.0` when `Kc == 1`)",
    "covered_depth_mm": "`L`, the depth of adjacent comparison-knot pairs whose both endpoints "
    "are defined",
    "coverage_fraction": "`L / span`; empty when `span == 0`",
    "signed_depth_average": "`D̄`, the trapezoidal signed depth average over the valid "
    "intervals; empty where `L = 0`",
    "rms_difference": "`RMS(D)`, the trapezoidal RMS difference over the valid intervals; empty "
    "where `L = 0`",
    "positive_count": "the defined differences with a positive sign (sums with the next two to "
    "`defined_count`)",
    "negative_count": "the defined differences with a negative sign",
    "zero_count": "the defined differences that are numerically zero (a `−0.0` counts here, "
    "never as negative)",
    "sign_agreement": "`A_sign`, the fraction of `|S|` with matching signs; empty where `|S| = 0`",
    "zero1_count": "the live-1 defined-zero knots over the comparison domain",
    "zero2_count": "the live-2 defined-zero knots over the comparison domain",
    "shape_correlation": "the Pearson correlation of the two profiles over `|D|`; empty on a "
    "shape refusal (its reason is the JSON `shape` non-value row)",
    "peak1_value": "the live-1 numerical maximum `M*_1`, defined whenever `|D| ≥ 1`",
    "peak1_depth": "the shallower depth the live-1 maximum was reached at",
    "peak2_value": "the live-2 numerical maximum `M*_2`, defined whenever `|D| ≥ 1`",
    "peak2_depth": "the shallower depth the live-2 maximum was reached at",
    "peak_localized1": "whether live-1's numerical maximum is a localized peak",
    "peak_localized2": "whether live-2's numerical maximum is a localized peak",
    "peak_displacement": "`z*_2 − z*_1` (positive = deeper in live-2); empty unless both sides "
    "are localized",
    "peaks_coincide": "whether the two localized peaks coincide within tolerance; empty unless "
    "both sides are localized",
}


def _readme_text(
    *,
    comparison: CrossSittingComparison,
    npz_digest: str,
    csv_digest: str,
    json_digest: str,
    analysis_commit: str,
    generator_revision: str,
    artifact_checks: Mapping[str, bool],
) -> str:
    """The README: orientation, units, definitions, both digest chains and the no-go list (§7)."""
    lines: list[str] = []
    lines.append(f"{README_TITLE_PREFIX} — one comparison, `{comparison.comparison}`")
    lines.append("")
    lines.append(
        "The between-sitting agreement artifact: one comparison, "
        f"`{comparison.comparison}` (`{comparison.sitting2}` minus `{comparison.sitting1}`), "
        "published under the cross-sitting schema "
        "(`docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`), the analogue of the "
        "accepted v1 within-sitting contract. It holds **one** oriented comparison over 72 "
        "endpoints; it is never a per-sitting file and never a third sitting."
    )
    lines.append("")
    lines.append("## Files and the digest chain")
    lines.append("")
    lines.append(
        f"- `{STEM}{NPZ_SUFFIX}` — the canonical `ZIP_STORED` container of NPY v1.0 members: "
        "for every **comparable** comparison, the five per-knot arrays of §3. It is the "
        "per-knot comparison array's one home."
    )
    lines.append(
        f"- `{STEM}{CSV_SUFFIX}` — one row per comparison (72 rows), the **sole** comparison "
        "scalar record: every §5 reduction, the coverage and the peak columns (§6)."
    )
    lines.append(
        f"- `{STEM}{JSON_SUFFIX}` — identity, the closed schema, the two sides' provenance "
        "digests, the typed states and reasons, the frozen context quotations, the non-value "
        "rows and the digests (§5). It carries no ndarray and no comparison reduction."
    )
    lines.append(f"- `{STEM}{README_SUFFIX}` — this file.")
    lines.append("")
    lines.append(
        "The chain is one-way: this README binds the document, the document binds the container "
        "and the table, and a file never carries its own digest."
    )
    lines.append("")
    lines.append(
        f"- `{STEM}{NPZ_SUFFIX}` sha256: `{npz_digest}` (over its exact file bytes)."
    )
    lines.append(
        f"- `{STEM}{CSV_SUFFIX}` sha256: `{csv_digest}` (over its canonical LF bytes, so a "
        "Windows checkout with CRLF materialised on disk hashes to the value git stores)."
    )
    lines.append(
        f"- `{STEM}{JSON_SUFFIX}` sha256: `{json_digest}` (canonical LF bytes; this is the "
        "reader's entry point to the chain)."
    )
    lines.append(
        "- every digest is lowercase hex with the `sha256:` prefix, computed from the bytes this "
        "run staged, at the analysis revision below — never from a tree regenerated beside the "
        "destination."
    )
    lines.append("")
    lines.append("## The two source quartets and their digest chains")
    lines.append("")
    lines.append(
        "The two sides are the two fixed reproducibility sittings, read **by name** through the "
        "input layer from the committed source quartets under `reports/sparse-signal/`, "
        "independent of any scratch output directory. Each side's chain is "
        "`README -> JSON (canonical LF) -> NPZ (exact bytes) + CSV (canonical LF)`, recomputed "
        "by this run from the published bytes and never re-derived."
    )
    lines.append("")
    for provenance in (comparison.provenance1, comparison.provenance2):
        lines.append(
            f"- `{provenance.sitting}` (`{provenance.pass_name}`, stem `{provenance.stem}`, "
            f"plan `{provenance.plan}`, plan fingerprint `{provenance.plan_fingerprint}`):"
        )
        lines.append(f"  - JSON sha256: `{provenance.json_sha256}`")
        lines.append(f"  - NPZ sha256: `{provenance.npz_sha256}`")
        lines.append(f"  - CSV sha256: `{provenance.csv_sha256}`")
        lines.append(
            f"  - own checks hold: `{str(provenance.checks_ok).lower()}`, own artifact checks "
            f"hold: `{str(provenance.artifact_checks_ok).lower()}`"
        )
    lines.append("")
    lines.append("## The comparison unit and the effect identity")
    lines.append("")
    lines.append(
        "One comparison per `(view, metric, contrast-or-interaction)`: nine `(metric, view)` "
        "endpoints, each carrying the seven bound contrasts plus the derived pitch×burst "
        "interaction — 72 comparisons, the whole row set of the NPZ, the JSON and the CSV. "
        "`grid` is a function of the contrast, asserted and never chosen. The comparison key is "
        "the ordered triple; the effect id is their `__` join:"
    )
    lines.append("")
    lines.append("```")
    lines.append('effect_id = "<view>__<metric>__<contrast>"')
    lines.append("```")
    lines.append("")
    lines.append(
        "A reader resolves an id through the JSON `comparisons` list and **must never parse the "
        "id** string; the id is a stable key, not a grammar."
    )
    lines.append("")
    lines.append("## The NPZ members (closed per comparable comparison)")
    lines.append("")
    lines.append(
        "For every **comparable** comparison the member-name set is exactly the five suffixes "
        "below, prefix-qualified by the effect id, and there is no other member. A "
        "**not comparable** comparison contributes **no** member. `Kc` is published as "
        "`comparison_knot_count` in the document, so the shape is stated in two places and must "
        "agree."
    )
    lines.append("")
    lines.append("| member | dtype | shape | meaning |")
    lines.append("| --- | --- | --- | --- |")
    for suffix in CROSS_MEMBER_SUFFIXES:
        dtype, shape = _MEMBER_SHAPE[suffix]
        lines.append(
            f"| `<effect_id>__{suffix}.npy` | `{dtype}` | `{shape}` | {_MEMBER_MEANING[suffix]} |"
        )
    lines.append("")
    lines.append(
        "- **the finite placeholder**: an undefined comparison position carries `0.0`, mask `0` "
        "and a non-zero state code; the mask is `1` exactly where both sides' state code is `0`. "
        "The stored `difference` is the IEEE-754 binary64 result of `E2 - E1` exactly as the "
        "backend computes it: a `-0.0` is written as `-0.0` (never normalized), occupies a "
        "**defined** position, and counts in `zero_count` — it is never negative."
    )
    lines.append(
        "- **strictly increasing knots**, exact little-endian dtypes and C-contiguous payloads; "
        "no member contains `NaN`, `Inf` or an object, so `allow_pickle=False` reading is exact."
    )
    lines.append("")
    lines.append("## The physical-depth weighting rule")
    lines.append("")
    lines.append(WEIGHTING_RULE)
    lines.append("")
    lines.append(
        "The unit of every difference and reduction is the effect's own `units` cell (`mm/s`, "
        "`s` or `dimensionless`); a `band_fraction` difference is dimensionless, never a relative "
        "percentage. Weights describe physical depth, not gate count; a signed average can "
        "cancel a spatially changing difference, so it is never the sole magnitude summary."
    )
    lines.append("")
    lines.append("## The method")
    lines.append("")
    lines.append(METHOD)
    lines.append("")
    lines.append("## The two views")
    lines.append("")
    lines.append(
        "The set carries the two named views `primary-comparison` and `full-record`, never mixed "
        "in one comparison. The **primary comparison** is each sitting's declared window, cut "
        "from each recording's own stored stamps; the **full record** keeps every stored profile "
        "of the recording, so it is the longer view. Both are read on the recording's own native "
        "gate grid: the longer view has the finer frequency resolution `1/T` at the same "
        "effective sample rate and Nyquist `1/(2·dt)`, and a fluctuation scale is declared on "
        "the primary comparison only. The exact duration, gate pitch and sample rate of each view "
        "are the frozen quartets' own decoded axes, published per gate by the recordings' own "
        "reports; this set publishes no axis number it did not measure."
    )
    lines.append("")
    lines.append("## The CSV columns (closed, one row per comparison)")
    lines.append("")
    lines.append(
        "The table is keyed `effect_id` and has one row per comparison in the fixed order "
        "(endpoint, then contrast, then interaction), with the 30 columns below in order. An "
        "undefined scalar is the **empty field**, never `0`; every finite float is rendered with "
        '`format(value, ".17g")`, the round-trip decimal for binary64. A non-comparable row '
        "keeps its structural identity cells where they are known (including its state and "
        "reason, read from the JSON) and leaves every reduction and boolean cell empty."
    )
    lines.append("")
    for column in CSV_COLUMNS:
        lines.append(f"- **`{column}`** — {_COLUMN_MEANING[column]}.")
    lines.append("")
    lines.append("## The typed states")
    lines.append("")
    lines.append(
        "`comparison_state` is `comparable` or `not comparable`; `not resolvable with this "
        "design` requires a separately reviewed rule, none is registered, and such a row is "
        "refused. `label_state` is a **different axis**: `deferred-pending-review` for a "
        "comparable pair and absent otherwise, never a verdict and never a `comparison_state`. "
        "The per-knot `state1`/`state2` codes use table A:"
    )
    lines.append("")
    lines.append("| code | text |")
    lines.append("| --- | --- |")
    for code, text in STATE_MEANINGS:
        lines.append(f"| {code} | `{text}` |")
    lines.append("")
    lines.append(
        "A non-value row (`nonvalue_rows`) records a scalar whose value is missing because the "
        "comparison could not carry it — `undefined-shape`, an un-localized `peak`, or "
        "`peak-displacement`; a scalar whose emptiness is derivable from a CSV count is left to "
        "the CSV. A `not comparable` pair contributes no non-value row."
    )
    lines.append("")
    lines.append("## The repeat context and its conditional range")
    lines.append("")
    lines.append(
        "Each side's frozen magnitude/coverage context is quoted from its own CSV row and "
        "published **beside** the comparison, never as this artifact's reduction. A repeat "
        "context attaches to an operand only when the operand's whole achieved condition is "
        "provable from the published metadata; a non-selected context "
        "(`repeat-context-unavailable` or `repeat-context-identity-unverifiable`) publishes "
        "**no** numerical range: its `min_value`/`max_value`/`spread` keys are omitted entirely "
        "— not `null`, not `0` — so a range can never be read against an operand whose condition "
        "is not proved equal to the group's. A repeat context is context only and is excluded "
        "from every comparison decision."
    )
    lines.append("")
    lines.append("## The gate: structural `ok` vs the ancillary repeat-identity check")
    lines.append("")
    lines.append(
        "`ok` is the **structural** verdict: true exactly when every `artifact_checks` entry is "
        "true **and** every `checks` entry is true **except** "
        "`repeat_context_identity_fully_established`. That ancillary check is **false** whenever "
        "any operand's repeat context is `repeat-context-identity-unverifiable`; it is published "
        "as `false` and it does **not** make `ok` false. A pair whose repeat context is "
        "unavailable or unverifiable is still `comparable`, with identical `comparison_state`, "
        "`label_state` and diagnostics to the same pair with a selected context."
    )
    lines.append("")
    for name in CHECK_ORDER:
        held = "ok" if comparison.checks.get(name) else "FAILED"
        lines.append(f"- `{name}` — {held}")
    for name in ARTIFACT_CHECK_NAMES:
        held = "ok" if artifact_checks.get(name) else "FAILED"
        lines.append(f"- `{name}` — {held}")
    lines.append("")
    lines.append("## Provenance and digests")
    lines.append("")
    lines.append(f"- comparison: `{comparison.comparison}`.")
    lines.append(f"- analysis revision: `{analysis_commit}`.")
    lines.append(f"- generator revision: `{generator_revision}`.")
    lines.append(
        "Publication is staged: every file is written beside its destination under a unique, "
        "fsynced temporary name and moved onto its final name with one `os.replace` at a time. "
        "The four-file set is **not** a transaction, so a failure after some renames can leave a "
        "mixed set — one a reader detects by recomputing the digests above. An existing file is "
        "never overwritten to guess ownership: a full byte-identical set is left untouched, and "
        "any missing or differing file makes the run refuse rather than replace a file it did "
        "not produce."
    )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append(
        "Run from a checkout of the recorded generator revision. Set `SA5_SCRATCH` to an "
        "absolute directory **outside the checkout**; do not regenerate into this committed "
        "report root. `--report-dir` redirects the **outputs** only: the two sides are always "
        "read from the committed source quartets, so a scratch directory never redirects the "
        "reads. A later checkout has a different default revision and must not overwrite an "
        "existing artifact set."
    )
    lines.append("")
    lines.append("```bash")
    lines.append(
        f'{regeneration_command()} --report-dir "$SA5_SCRATCH" '
        f"--analysis-commit {analysis_commit} --generator-revision {generator_revision}"
    )
    lines.append("```")
    lines.append("")
    lines.append("## What this artifact does not claim")
    lines.append("")
    for item in NO_GO_LIST:
        lines.append(f"- {item}")
    # No trailing blank line: every artifact ends in exactly one newline.
    return "\n".join(lines) + "\n"


# ── the run, from the fixed source quartets ────────────────────────────


def build_cross_report(
    *,
    source_dir: Path | None = None,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> CrossArtifacts:
    """Load the two fixed source quartets, compare them, and build the four artifacts.

    Args:
        source_dir: the directory the committed quartets are read from; defaults to the fixed
            :data:`SOURCE_DIR` anchored at the repository root. It is never the output root.
        analysis_commit: the revision the JSON records; defaults to the checkout's short SHA.
        generator_revision: the generator's own revision; defaults to the checkout's short SHA.

    Returns:
        :class:`CrossArtifacts` for the one ``live2 - live1`` comparison.

    Raises:
        SparseSa5CrossReportError: for an input the input layer or backend refuses, or any
            refusal of :func:`build_cross_artifacts`.
    """
    root = _anchor_repository(source_dir or SOURCE_DIR)
    live1, live2 = load_published_quartets(root)
    try:
        comparison = compare_cross_sitting(live1, live2)
    except SparseSa5CrossSittingError as exc:
        raise _refuse(f"the comparison is refused: {exc}") from exc
    return build_cross_artifacts(
        comparison,
        source_dir=root,
        analysis_commit=analysis_commit,
        generator_revision=generator_revision,
    )


# ── publication (§11) ──────────────────────────────────────────────────


def write_cross_report(
    destination: Path,
    *,
    source_dir: Path | None = None,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> CrossArtifacts:
    """Build the cross set from the fixed source quartets and publish it into ``destination``.

    Args:
        destination: the directory to write into. The plan's designated root, or a directory
            outside the repository (a scratch tree a caller or a test owns). A *relative* path is
            anchored at the repository root. It redirects outputs only and never the reads.
        source_dir: the directory the committed quartets are read from, as
            :func:`build_cross_report`.
        analysis_commit: the revision to record, as :func:`build_cross_report`.
        generator_revision: the generator's own revision, as :func:`build_cross_report`.

    Returns:
        The :class:`CrossArtifacts` that were built and published.

    Raises:
        SparseSa5CrossReportError: as :func:`build_cross_report`, and any refusal of
            :func:`write_cross_artifacts`.
    """
    _require_destination(destination)
    artifacts = build_cross_report(
        source_dir=source_dir,
        analysis_commit=analysis_commit,
        generator_revision=generator_revision,
    )
    write_cross_artifacts(artifacts, destination)
    return artifacts


def write_cross_artifacts(artifacts: CrossArtifacts, destination: Path) -> None:
    """Publish an already-built four-file set, or refuse without replacing any existing file.

    The destination rules are checked first (a frozen tree, the repository root, or a tree
    inside the repository that is not the plan's publish root is refused). The publication lock
    is then taken **before** the ownership of any existing file is judged, and the
    idempotent/differing decision is made *under* the lock: if all four names already exist and
    are byte-identical to this run's products the set is published idempotently and does
    nothing; any missing or differing file makes the run refuse and leave every existing file
    untouched. An **unrelated entry bearing the cross stem** (a bare ``sa5-cross-sitting`` or any
    ``sa5-cross-sitting.<something>`` that is not one of the four names) is refused too, because
    it shares the stem but is not a product this writer staged. A leftover stage file or lock
    from an interrupted run is refused by name rather than adopted or deleted. Only this writer's
    four names are ever staged, so a sibling SA2.4 file or a v1 quartet is never a candidate for
    replacement.

    Raises:
        SparseSa5CrossReportError: on any destination, ownership, foreign-stem, lock or stage
            refusal.
    """
    directory = _require_destination(destination)
    directory.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(directory, artifacts.stem)
    try:
        foreign = _foreign_stem_entries(directory, artifacts)
        if foreign:
            raise _refuse(
                f"{directory.as_posix()!r} carries an unrelated entry bearing the cross stem "
                f"{artifacts.stem!r}: {[path.name for path in foreign]}. A name that shares the "
                "stem but is not one of this writer's four files is an unrelated file of "
                "unknown provenance, so this run refuses rather than write beside it; remove it "
                "once no writer holds the directory."
            )
        if _existing_set_is_this_run(directory, artifacts):
            return
        stale = _stale_temporaries(directory, artifacts.stem)
        if stale:
            raise _refuse(
                "an interrupted run left staged temporary file(s) beside the destination: "
                f"{[path.name for path in stale]}. They are evidence that a previous publication "
                "was cut off between staging and publishing, so this run refuses rather than "
                "guessing whether they are safe to adopt or delete; remove them once no writer "
                "holds the directory."
            )
        staged: list[tuple[Path, str]] = []
        try:
            for name, payload in artifacts.files:
                staged.append((_stage_bytes(directory, name, payload), name))
        except BaseException:
            _discard(staged)
            raise
        _publish(directory, staged)
    finally:
        lock.unlink(missing_ok=True)


def _existing_set_is_this_run(directory: Path, artifacts: CrossArtifacts) -> bool:
    """Whether the destination already carries this run's complete byte-identical set."""
    existing = [name for name, _ in artifacts.files if (directory / name).exists()]
    if not existing:
        return False
    not_files = [name for name in existing if not (directory / name).is_file()]
    if not_files:
        raise _refuse(
            f"{directory.as_posix()!r} carries a non-file entry named {not_files[0]!r}; a "
            "cross-sitting artifact name must be a file this writer produced"
        )
    missing = [name for name, _ in artifacts.files if name not in existing]
    if missing:
        raise _refuse(
            f"{directory.as_posix()!r} carries an incomplete cross-sitting set: existing "
            f"{existing}, missing {missing}. A partial set is evidence of an interrupted "
            "publication or an unrelated file, and this writer never guesses ownership, so it "
            "refuses without replacing any existing file."
        )
    differing = [
        name
        for name, payload in artifacts.files
        if (directory / name).read_bytes() != payload
    ]
    if differing:
        raise _refuse(
            f"{directory.as_posix()!r} carries a cross-sitting file this run did not produce "
            f"({differing}); its bytes differ from this run's staged products, so the "
            "publication refuses rather than clobber a file of unknown provenance."
        )
    return True


def _require_destination(destination: Path) -> Path:
    """Resolve and gate one destination, refusing a frozen or foreign tree (§11)."""
    directory = _anchor_repository(destination)
    message = _destination_refusal(directory)
    if message is not None:
        raise _refuse(message)
    return directory


def _anchor_repository(path: Path) -> Path:
    """Anchor a possibly-relative path at the repository root, never the working directory."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return _repository_root() / candidate


def _repository_root() -> Path:
    """The checkout this module is part of, from its own location (four levels up)."""
    return Path(__file__).resolve().parents[3]


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or lies inside it, by resolved path."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _frozen_report_dirs() -> tuple[Path, ...]:
    """Every frozen report tree this writer must not enter: the passes' own, plus the extra one."""
    committed = tuple(
        _anchor_repository(Path(ref.report_dir))
        for ref in COMMITTED_PASSES
        if ref.report_dir is not None
    )
    return (
        *committed,
        *(_anchor_repository(path) for path in EXTRA_FROZEN_REPORT_DIRS),
    )


def _destination_refusal(directory: Path) -> str | None:
    """Why ``directory`` may not be published to, or ``None`` when it may (§11)."""
    resolved = directory.resolve()
    repository = _repository_root()
    designated = (repository / REPORT_DIR).resolve()
    if resolved.exists() and not resolved.is_dir():
        return (
            f"the destination {directory.as_posix()!r} exists and is not a directory, so the "
            "four artifacts cannot be placed inside it"
        )
    if _inside(repository, resolved):
        return (
            f"the destination {directory.as_posix()!r} is the repository root or one of its "
            f"ancestors ({repository.as_posix()!r}): this writer publishes only under the plan's "
            f"designated root {REPORT_DIR.as_posix()!r} or outside the repository entirely, and "
            "would otherwise clobber the repository's own files"
        )
    if _inside(resolved, repository) and resolved != designated:
        return (
            f"the destination {directory.as_posix()!r} lies inside the repository "
            f"({repository.as_posix()!r}) but is not the plan's designated publish root "
            f"{REPORT_DIR.as_posix()!r}: SA5 writes only its own files under that root and leaves "
            "every committed tree byte-unchanged"
        )
    for frozen in _frozen_report_dirs():
        if _inside(resolved, frozen):
            return (
                f"the destination {directory.as_posix()!r} lies inside the frozen tree "
                f"{frozen.as_posix()!r}: the WP and SA2.4 reports are byte-untouched by any run "
                "of this generator"
            )
    return None


def _stage_bytes(directory: Path, name: str, payload: bytes) -> Path:
    """Write one product beside its destination under a unique private name; fsync; return it."""
    descriptor, temporary = tempfile.mkstemp(
        dir=directory, prefix=f".{name}.", suffix=".tmp"
    )
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _acquire_lock(directory: Path, stem: str) -> Path:
    """Create the publication lock exclusively, or refuse naming the interrupt/concurrency."""
    lock = directory / f".{stem}.publish-lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise _refuse(
            f"{lock.as_posix()!r} already exists: another publication into "
            f"{directory.as_posix()!r} is in progress, or a previous run was interrupted before "
            "it could release this lock. Two runs would interleave their files and the set is "
            "not a transaction, so this run refuses rather than racing; remove the lock only "
            "once no writer holds it."
        ) from exc
    os.close(descriptor)
    return lock


def _foreign_stem_entries(
    directory: Path, artifacts: CrossArtifacts
) -> tuple[Path, ...]:
    """Any entry bearing the cross stem that is not one of this writer's four names (§11).

    A sibling such as ``sa5-cross-sitting.notes`` — or a bare ``sa5-cross-sitting`` — shares the
    stem but is not a name this writer stages, so it is an unrelated file of unknown provenance
    the schema says never to write beside. The lock
    (``.sa5-cross-sitting.publish-lock``) and any stage temporary are dot-prefixed and are judged
    by their own rules, so they are deliberately excluded here.
    """
    known = frozenset(artifacts.names)
    prefix = f"{artifacts.stem}."
    return tuple(
        sorted(
            path
            for path in directory.iterdir()
            if path.name not in known
            and (path.name == artifacts.stem or path.name.startswith(prefix))
        )
    )


def _stale_temporaries(directory: Path, stem: str) -> tuple[Path, ...]:
    """Any leftover stage file a previous run left behind, by the names this writer stages."""
    found: list[Path] = []
    for suffix in (NPZ_SUFFIX, CSV_SUFFIX, JSON_SUFFIX, README_SUFFIX):
        name = f"{stem}{suffix}"
        found.extend(sorted(directory.glob(f".{name}.*.tmp")))
    return tuple(found)


def _publish(directory: Path, staged: Sequence[tuple[Path, str]]) -> None:
    """Move every staged product onto its own name, removing any leftover stage on failure."""
    remaining = list(staged)
    try:
        for path, name in staged:
            os.replace(path, directory / name)
            remaining.remove((path, name))
    finally:
        _discard(remaining)


def _discard(staged: Sequence[tuple[Path, str]]) -> None:
    """Remove staged products that were never published, so a failed run leaves no debris."""
    for path, _name in staged:
        try:
            path.unlink()
        except OSError:
            pass


# ── the command line (§11) ─────────────────────────────────────────────


def cross_report_main(argv: Sequence[str] | None = None) -> None:
    """``sa5-cross-report`` — write the one committed cross-sitting artifact set.

    The runnable module-invoked form the plan's verification section names:
    ``python -m udv_echo_process.analysis.sparse_sa5_cross_report [--report-dir <path>]``.

    ``--report-dir`` selects the destination (default: the plan's designated root) and redirects
    **outputs** only: the two sides are always the two fixed reproducibility sittings, read by
    name from the committed source quartets. ``--analysis-commit``/``--generator-revision``
    override the revisions the JSON records (default: the checkout's short SHA).

    Exits 0 when the gate holds and the four files are published, and 1 on any refusal, naming
    the reason on stderr. Nothing is written when a refusal is raised, so a refused run leaves
    the destination byte-unchanged.

    Raises:
        SystemExit: 0 on a published set, 1 on a refusal (and 2 on a usage error, from argparse).
    """
    parser = argparse.ArgumentParser(
        prog="udv-sa5-cross-report",
        description=(
            "SA5: the cross-sitting agreement artifacts — the canonical NPZ container, the "
            "scalar CSV, the strict JSON document and the README — for the fixed live2 - live1 "
            "comparison over the two committed reproducibility sittings"
        ),
    )
    parser.add_argument(
        "--report-dir",
        default=REPORT_DIR.as_posix(),
        help="directory to publish the four artifacts into (default: the plan's root)",
    )
    parser.add_argument(
        "--analysis-commit",
        default=None,
        help="revision to record (default: the checkout's short git SHA)",
    )
    parser.add_argument(
        "--generator-revision",
        default=None,
        help="generator revision to record (default: the checkout's short git SHA)",
    )
    args = parser.parse_args(argv)
    try:
        artifacts = write_cross_report(
            Path(args.report_dir),
            analysis_commit=args.analysis_commit,
            generator_revision=args.generator_revision,
        )
    except (SparseSa5CrossReportError, SparseSa5CrossSittingError) as exc:
        print(f"udv-sa5-cross-report: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    document = artifacts.document()
    print(f"comparison : {document['comparison']}")
    print(
        f"comparisons: {len(document['comparisons'])} rows, "
        f"{len(document['npz_members'])} container members"
    )
    for name in artifacts.names:
        print(f"file       : {Path(args.report_dir) / name}")
    print(f"npz        : {document['artifacts']['npz']['sha256']}")
    print(f"csv        : {document['artifacts']['csv']['sha256']}")
    print(f"checks     : {'all pass' if document['ok'] else 'FAILED'}")
    raise SystemExit(0)


if __name__ == "__main__":
    cross_report_main()
