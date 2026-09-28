"""SA5's one-sitting report writer — the four committed artifacts of the accepted v1 schema.

``docs/dop3000/sa5-effect-artifact-schema-proposal.md`` (accepted v1, implementation
clarifications at ``ebf0224``) fixes four files **per sitting** under the plan's publish root
``reports/sparse-signal/``::

    sa5-live-N-effects.npz          the canonical effect-profile container        (§3-§4)
    sa5-live-N-effects.json         identity, provenance, non-values, digests   (§5)
    sa5-live-N-effects.csv          the one per-effect scalar row set            (§6)
    sa5-live-N-effects.README.md    units, definitions, digest binding           (§7)

This module is the writer and nothing else. It is *one sitting per invocation*: exactly one
:class:`~udv_echo_process.analysis.sparse_passes.PassRef` with
``is_reproducibility_sitting=True`` is accepted, no second sitting is ever read, and no
cross-sitting number (``E_live2 - E_live1``), no recurrence verdict, no Stage-2 product and no
floor is computed, stored or published. The engine it drives
(:mod:`~udv_echo_process.analysis.sparse_sa5_effects`) measures the sitting alone; this module
only *serializes* that result.

Where each authority sits
-------------------------
* The **measurement** is the engine's: :func:`~...sparse_sa5_effects.measure_sitting` decodes
  the sitting's committed recordings, reconciles every operand's ``source_sha256``, job,
  acquisition order and achieved settings against the committed per-pass inventory, and only
  then measures. The writer neither re-decodes a recording nor re-measures a metric; "the
  source digest is rechecked by the backend" is exactly that reconciliation, and a sitting the
  backend refuses never reaches a byte here.
* The **operand identity** is the binding's: :func:`~...sparse_sa5_bindings.bind_sitting` over
  the sitting's own committed ``points.csv`` yields the eleven :class:`OperandRow`s the JSON
  publishes as ``provenance``. It is called with the sitting's own support, so the binding
  published and the binding measured are one object.
* The **container** is the codec's: :func:`~...sparse_sa5_npz.encode_effect_npz` writes the
  canonical ``ZIP_STORED`` archive of NPY v1.0 members, and every §3.2 invariant (mask, state
  code, finite placeholder, ``-1`` sentinel) is enforced there and re-checked here by decoding
  the bytes this run staged.
* The **scalar reductions** are the engine's :class:`DepthSummary` / :class:`ProfileShape`; the
  CSV copies them once, formatted by one rule (:func:`format` with ``".17g"``), and the JSON
  never repeats them.

Deliberate non-arithmetic
-------------------------
The only numbers this module invents are digests (SHA-256 over staged bytes) and the two counts
the schema mirrors (``K``/``P``). Every other published number is read from the engine's typed
result or from the binding. There is no reduction of an effect profile to a scalar whose array
was omitted: the NPZ is the array's one home, the CSV the scalar's, the JSON the identity's.

Publication and refusal gate (§9)
---------------------------------
The four files are staged beside their destination under unique, fsynced temporary names and
moved onto their final names one ``os.replace`` at a time. The set is **not** a transaction: a
failure after some renames leaves a mixed set, which the digests let a reader detect rather than
roll back. An existing SA5 stem is never overwritten to guess ownership — if all four files
exist and are byte-identical to this run's staged products the publication is idempotent and
does nothing; if any file is missing or differs the run refuses without replacing any existing
file. A publication lock serializes runs and is taken **before** that ownership judgement, so a
concurrent run that published between a check and a lock is seen as existing rather than
clobbered. A stage file or lock an interrupted run left behind is refused by name, and a frozen
report tree (the WP/SA2.4 trees, ``reports/mixer-sensitivity-analysis``) — anchored at the
repository root, never the working directory — is refused as a destination.

Reader entry point
------------------
The writer is reached from the command line as
``python -m udv_echo_process.analysis.sparse_sa5_report --sitting <name> [--report-dir <path>]``
(:func:`report_main`) — the form :func:`regeneration_command` publishes. The command resolves a
committed sitting **name** to its :class:`PassRef` and refuses any name that is not one of the
two reproducibility sittings, so a campaign cannot be named into a report.
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
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from udv_echo_process.analysis import _floor_documents
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_passes import (
    COMMITTED_PASSES,
    PassRef,
    PassRole,
    pass_by_name,
)
from udv_echo_process.analysis.sparse_sa5_bindings import (
    CONTRASTS,
    OperandRow,
    SittingBinding,
    bind_sitting,
)
from udv_echo_process.analysis.sparse_sa5_effects import (
    CONTRAST_SOURCE,
    ENDPOINTS,
    METHOD,
    WEIGHTING_RULE,
    DepthEffects,
    EffectState,
    KnotEffect,
    ReadAligned,
    SittingEffects,
    measure_sitting,
)
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    MEMBER_DTYPES,
    MEMBER_SUFFIXES,
    PARTICIPANT_STATE_CODES,
    UNALIGNED_READ_CODE,
    EffectArrays,
    decode_effect_npz,
    effect_member_names,
    encode_effect_npz,
)
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

__all__ = [
    "ARTIFACT_CHECK_NAMES",
    "CSV_COLUMNS",
    "EFFECT_COUNT",
    "ENGINE_CHECK_ORDER",
    "NONVALUE_KINDS",
    "NO_GO_LIST",
    "NPZ_MEMBER_COUNT",
    "README_TITLE_PREFIX",
    "REPORT_DIR",
    "SCHEMA_ID",
    "STATE_MEANINGS",
    "Sa5Artifacts",
    "SparseSa5ReportError",
    "build_sa5_artifacts",
    "build_sa5_report",
    "effect_id",
    "effect_records",
    "regeneration_command",
    "report_main",
    "sitting_stem",
    "write_sa5_artifacts",
    "write_sa5_report",
]

#: The JSON's ``schema`` value — the closed schema id of §5.1.
SCHEMA_ID = "sa5-within-sitting-effects/v1"

#: The plan's publish root (§1). A destination inside the repository must be exactly this tree.
REPORT_DIR = Path("reports/sparse-signal")

#: The committed-pass naming the two reproducibility sittings share (``sparse-mixer-live-N``).
SITTING_PREFIX = "sparse-mixer-"

#: The file-stem form: ``sa5-live-N-effects`` (§1).
STEM_PREFIX = "sa5-"
STEM_SUFFIX = "-effects"

#: The four artifact suffixes; the set is published leaves-first so a reader follows the chain.
NPZ_SUFFIX = ".npz"
CSV_SUFFIX = ".csv"
JSON_SUFFIX = ".json"
README_SUFFIX = ".README.md"

#: The README's first line, the marker a reader recognises as this writer's own.
README_TITLE_PREFIX = "# SA5 within-sitting effect artifacts"

#: The effects of the frozen sweep: nine ``(metric, view)`` endpoints, each with the seven bound
#: contrasts plus the derived interaction (§2).
EFFECT_COUNT = len(ENDPOINTS) * (len(CONTRASTS) + 1)

#: The ten closed member suffixes of one effect, so the container carries ``72 x 10`` members.
NPZ_MEMBER_COUNT = EFFECT_COUNT * len(MEMBER_SUFFIXES)

#: The engine's own check names, in the order §5.1 fixes them. ``ok`` is true exactly when every
#: one of these and every :data:`ARTIFACT_CHECK_NAMES` entry is true.
ENGINE_CHECK_ORDER: tuple[str, ...] = (
    "operands_bound_to_decoded_sources",
    "inventory_digest_matches_every_operand",
    "achieved_settings_match_every_operand",
    "corners_share_their_own_grids",
    "emissions_operands_share_the_reference_pitch_and_grid",
    "every_endpoint_has_one_effect_per_knot",
    "e20_is_the_equal_weight_mean_of_the_four_runs",
    "no_block_local_anchor_enters_an_operand",
    "repeats_name_their_members_and_orders",
    "window_is_the_declared_primary",
    "no_cross_sitting_arithmetic",
)

#: The schema-level artifact checks of §5.1, computed on the bytes this run staged.
ARTIFACT_CHECK_NAMES: tuple[str, ...] = (
    "npz_members_are_the_closed_set",
    "every_undefined_position_carries_placeholder_mask_and_state",
    "participant_rows_are_the_declared_order",
    "digests_match_the_staged_bytes",
)

#: The CSV's closed column set, in order (§6). One row per effect, 72 rows.
CSV_COLUMNS: tuple[str, ...] = (
    "sitting",
    "effect_id",
    "view",
    "metric",
    "contrast",
    "units",
    "grid",
    "knot_count",
    "defined_count",
    "undefined_count",
    "undefined_alignment_count",
    "undefined_operand_count",
    "covered_depth_mm",
    "coverage_fraction",
    "support_low_mm",
    "support_high_mm",
    "half_pitch_mm",
    "max_abs_offset_mm",
    "signed_depth_average",
    "equal_knot_average",
    "rms_magnitude",
    "positive_fraction",
    "negative_fraction",
    "zero_fraction",
    "min_value",
    "min_depth_mm",
    "max_value",
    "max_depth_mm",
    "max_abs_value",
    "max_abs_depth_mm",
    "correlation",
    "correlation_defined_count",
)

#: The two grid labels the JSON and the CSV publish (§2/§5.3).
CORNER_GRID = "corner_knots"
EMISSIONS_GRID = "emissions_knots"

#: The JSON-only non-value state label for a refused profile correlation (§5.5).
UNDEFINED_SHAPE = "undefined-shape"

#: The four non-value position kinds (§5.5).
NONVALUE_KINDS: tuple[str, ...] = ("effect-knot", "operand-knot", "read", "shape")

#: The unit each CSV column carries where its name does not already say it. Depth columns are
#: millimetres; every remaining column's unit is the effect's own ``units`` cell.
COLUMN_UNITS: Mapping[str, str] = {
    "covered_depth_mm": "mm",
    "support_low_mm": "mm",
    "support_high_mm": "mm",
    "half_pitch_mm": "mm",
    "max_abs_offset_mm": "mm",
    "min_depth_mm": "mm",
    "max_depth_mm": "mm",
    "max_abs_depth_mm": "mm",
}

#: The two code spaces, as ``(code, text)`` pairs, published once per effect so a code is never
#: ambiguous (§8). They are the codec's own tables, which the backend enums are tested against.
STATE_MEANINGS: Mapping[str, tuple[tuple[int, str], ...]] = {
    "effect": tuple(sorted(EFFECT_STATE_CODES.items())),
    "participant": tuple(sorted(PARTICIPANT_STATE_CODES.items())),
}

#: What this artifact does not claim (§7, §9), quoted verbatim in the README.
NO_GO_LIST: tuple[str, ...] = (
    (
        "No cross-sitting number exists here: this run reads exactly one sitting, and "
        "`E_live2 - E_live1` and every other between-sitting comparison is a separate, later, "
        "reviewed artifact."
    ),
    (
        "No Stage-2 product: the Stage-2 E20/E64 campaign is contextual, is not a third sitting, "
        "and is not reached by this writer."
    ),
    (
        "No p-value, no floor, no optimum and no causality verdict: nothing here screens, ranks "
        "or decides."
    ),
    (
        "A descriptive recurrence-peak lag is not a period claim, and a descriptive repeat range "
        "is not a floor and not a replicate."
    ),
    "`correlation` describes the shape of a compared pair of profiles only; it is not a test.",
    (
        "No effect profile is reduced to a scalar row while its array is omitted: the NPZ is the "
        "profile array's one home, the CSV the per-effect scalar's, the JSON the identity's."
    ),
    (
        "No ndarray is placed in the JSON (issue #49 remains open and unsolved), and there are no "
        "per-depth repeat arrays."
    ),
)

#: The frozen report trees a destination may never enter: the committed passes' own report
#: directories, plus the one frozen tree that carries no ``PassRef``. Restated here rather than
#: imported from the SA2.4 writer so the two writers share no mutable state.
EXTRA_FROZEN_REPORT_DIRS: tuple[Path, ...] = (
    Path("reports/mixer-sensitivity-analysis"),
)

#: Table A's two non-zero codes, named for the CSV's split undefined counts.
_EFFECT_CODE_OPERAND = next(
    code
    for code, text in EFFECT_STATE_CODES.items()
    if text == EffectState.UNDEFINED_OPERAND.value
)
_EFFECT_CODE_UNALIGNED = next(
    code
    for code, text in EFFECT_STATE_CODES.items()
    if text == EffectState.UNDEFINED_ALIGNMENT.value
)
_EFFECT_CODE_BY_TEXT: Mapping[str, int] = {
    text: code for code, text in EFFECT_STATE_CODES.items()
}
_PARTICIPANT_CODE_BY_TEXT: Mapping[str, int] = {
    text: code for code, text in PARTICIPANT_STATE_CODES.items()
}


class SparseSa5ReportError(ValueError):
    """A sitting's four artifacts cannot be built or published under the accepted v1 schema.

    Raised for a pass that is not one of the two reproducibility sittings, a second sitting in
    one invocation, a destination that is frozen or not this writer's, an existing SA5 file this
    run did not produce, a leftover stage file or lock, a gate that does not hold, a non-finite
    number that would reach the JSON, or an artifact check that failed on the staged bytes. A
    *typed non-value* — an undefined knot, an unaligned read, a refused correlation — is not this
    error: it is data, published as a state code and a non-value row.
    """


def _refuse(message: str) -> SparseSa5ReportError:
    """One refusal, so every raise site states its reason in the same shape."""
    return SparseSa5ReportError(message)


# ── identity helpers ───────────────────────────────────────────────────


def sitting_stem(sitting: str) -> str:
    """The file stem of one sitting's artifact set (§1): ``sa5-live-1-effects``.

    Args:
        sitting: the pass name (``PassRef.name``), e.g. ``sparse-mixer-live-1``.

    Returns:
        ``"sa5-" + <the part after the committed-pass prefix> + "-effects"``.

    Raises:
        SparseSa5ReportError: for a name that is not a mixer-enabled sitting's, so a stem can
            never be invented for a dataset the schema does not name.
    """
    if not isinstance(sitting, str) or not sitting.startswith(SITTING_PREFIX):
        raise _refuse(
            f"{sitting!r} is not a mixer-enabled sitting name; the §1 stem rule is written for a "
            f"pass named {SITTING_PREFIX!r} + a sitting label (sparse-mixer-live-1, "
            "sparse-mixer-live-2)"
        )
    label = sitting[len(SITTING_PREFIX) :]
    if not label:
        raise _refuse(f"{sitting!r} carries no sitting label after {SITTING_PREFIX!r}")
    return f"{STEM_PREFIX}{label}{STEM_SUFFIX}"


def _label(value: object) -> str:
    """The frozen vocabulary label of one enum member or string."""
    return value.value if hasattr(value, "value") else str(value)


def effect_id(view: SparseView | str, metric: MetricName | str, contrast: str) -> str:
    """The deterministic effect id of §2: ``"<view>__<metric>__<contrast>"``.

    None of the three frozen vocabularies contains ``__``, so the id round-trips and a reader
    *could* split it — but a reader **must never parse the id**; it resolves the id through the
    JSON ``effects`` list, and the id is a stable key, not a grammar.

    Raises:
        SparseSa5ReportError: for an empty component or one that carries the ``__`` join, which
            would leave the id ambiguous.
    """
    parts = (_label(view), _label(metric), contrast)
    if any(not isinstance(part, str) or not part for part in parts):
        raise _refuse(f"an effect id is three non-empty labels, got {parts!r}")
    if any("__" in part for part in parts):
        raise _refuse(
            f"an effect-id component cannot itself carry '__', which would leave the id "
            f"ambiguous: {parts!r}"
        )
    return "__".join(parts)


def regeneration_command(sitting: str) -> str:
    """The exact command that reproduces this sitting's artifacts at the recorded revision.

    It is the runnable module-invoked form the analysis plan's verification section names
    (``python -m udv_echo_process.analysis.sparse_sa5_report --sitting <name>``), **not** an inline
    ``python -c``: a sitting is a committed pass selected by name, and the command resolves
    that name to its pass and refuses a name that is not one of the two reproducibility
    sittings — so a campaign such as ``stage2-e20-e64`` cannot be named into a report.
    """
    return f"python -m udv_echo_process.analysis.sparse_sa5_report --sitting {sitting}"


def _file_digest(data: bytes) -> str:
    """A published digest over **exact file bytes**: ``sha256:`` of ``data`` unchanged.

    This is the NPZ's digest (§5.7): the container is already canonical by §4, so it is hashed
    over its exact bytes and no normalization is applied or permitted. Applying the CRLF-to-LF
    rule of :func:`_canonical_digest` to binary container bytes would silently change the
    digest of any container that happens to carry the byte pair ``0x0d 0x0a`` — and the
    independent check hashes the container raw, so the two would disagree. Binary bytes go
    through this function and nothing else.
    """
    return _floor_documents.DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def _canonical_digest(data: bytes) -> str:
    """A published digest over canonical (LF) **text** bytes, as the repository hashes text.

    For the CSV and the JSON only — the two published files that are UTF-8 text and may be
    materialised with CRLF by a Windows checkout. Identical to
    :func:`udv_echo_process.analysis._floor_documents.table_digest` for a file, so a text
    artifact hashed here and a file hashed there agree. It must **not** be applied to the
    binary container, whose digest is :func:`_file_digest` over its exact bytes.
    """
    return _file_digest(data.replace(b"\r\n", b"\n"))


# ── the four byte products ─────────────────────────────────────────────


# Pydantic warns that the field name ``json`` shadows the deprecated ``BaseModel.json()``
# classmethod it would otherwise inherit. The accepted v1 schema fixes the field name (and the
# tests read ``artifacts.json``), so the cosmetic warning is silenced around the definition
# only; every other warning still surfaces.
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r'Field name "json" .* shadows an attribute in parent',
        category=UserWarning,
    )

    class Sa5Artifacts(ValueModel):
        """One sitting's four staged products, as bytes, plus the identity they carry.

        A frozen :class:`~udv_echo_process.models.base.ValueModel` (immutable, ``extra="forbid"``)
        holding only scalars and ``bytes``, so a published set is a value object that cannot be
        re-bound after construction. ``files`` is the publication order: the NPZ and the CSV
        first, then the JSON that binds them, then the README that binds the JSON — the order a
        reader follows the digest chain in.
        """

        sitting: str
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


# ── per-effect rows ────────────────────────────────────────────────────


class _EffectRows(ValueModel):
    """One effect's serialized pieces: its record, its CSV cells and its non-value rows.

    A frozen :class:`~udv_echo_process.models.base.ValueModel`, like every other record this
    writer builds: it is a private value object assembled once per effect and never re-bound,
    and its ``effect``/``record`` fields are the engine's own typed result and the codec's own
    array record, kept as the identical objects rather than rebuilt.
    """

    effect: DepthEffects
    key: str
    grid: str
    participant_labels: tuple[str, ...]
    record: EffectArrays
    cells: Mapping[str, object]
    nonvalue: tuple[Mapping[str, object], ...]


def effect_records(effects: SittingEffects) -> tuple[DepthEffects, ...]:
    """The 72 effects in the fixed §2 order: endpoint order, then contrast order, then interaction.

    Raises:
        SparseSa5ReportError: for a sitting whose endpoint set or contrast count is not the frozen
            one, or whose effect ids are not unique — the order is part of the schema, never
            inferred from names, and uniqueness is asserted rather than assumed.
    """
    ordered: list[DepthEffects] = []
    for metric, view in ENDPOINTS:
        endpoint = effects.endpoint(metric, view)
        if len(endpoint.contrasts) != len(CONTRASTS):
            raise _refuse(
                f"{effects.pass_name}: the {metric.value!r}/{view.value!r} endpoint carries "
                f"{len(endpoint.contrasts)} contrasts, the prespec fixes {len(CONTRASTS)}"
            )
        ordered.extend(endpoint.contrasts)
        ordered.append(endpoint.interaction)
    if len(ordered) != EFFECT_COUNT:
        raise _refuse(
            f"{effects.pass_name}: the endpoint sweep produced {len(ordered)} effects, the "
            f"schema fixes {EFFECT_COUNT}"
        )
    keys = [effect_id(item.view, item.metric, item.name) for item in ordered]
    if len(set(keys)) != len(keys):
        raise _refuse(
            f"{effects.pass_name}: two effects share an id; the 72 ids are asserted unique, never "
            "assumed"
        )
    return tuple(ordered)


def _participant_labels(knots: Sequence[KnotEffect], where: str) -> tuple[str, ...]:
    """The participant rows in contract order (§3.1), asserted identical at every knot.

    The order is the high operand's members in ``Operand.members`` order, then the low operand's
    members not already present. It is read from the measured operands rather than restated, so a
    binding change cannot silently reorder the ``(P,K)`` rows.
    """
    order: tuple[str, ...] | None = None
    for knot in knots:
        here = tuple(
            dict.fromkeys(
                member.label for operand in knot.operands for member in operand.members
            )
        )
        if order is None:
            order = here
        elif here != order:
            raise _refuse(
                f"{where}: the participant rows change between knots ({order} then {here}); the "
                "row order is a fixed part of the schema"
            )
    if not order:
        raise _refuse(f"{where}: an effect has no participant read to publish")
    return order


def _effect_code(state: EffectState) -> int:
    """Table A's code for one effect state, or a refusal naming the drift."""
    code = _EFFECT_CODE_BY_TEXT.get(_label(state))
    if code is None:
        raise _refuse(
            f"the effect state {_label(state)!r} has no code in table A "
            f"({list(EFFECT_STATE_CODES.values())})"
        )
    return code


def _participant_code(read: ReadAligned) -> int:
    """Table B's code for one read: the metric state, or the read-level sentinel if unaligned."""
    if not read.aligned:
        return UNALIGNED_READ_CODE
    code = _PARTICIPANT_CODE_BY_TEXT.get(_label(read.state))
    if code is None:
        raise _refuse(
            f"the read state {_label(read.state)!r} has no code in table B "
            f"({list(PARTICIPANT_STATE_CODES.values())})"
        )
    return code


def _grid_label(knot: KnotEffect, corner_labels: frozenset[str]) -> str:
    """``corner_knots`` or ``emissions_knots``, derived from the participating recordings (§5.3)."""
    labels = [member.label for operand in knot.operands for member in operand.members]
    return (
        CORNER_GRID
        if all(label in corner_labels for label in labels)
        else EMISSIONS_GRID
    )


def _build_effect_rows(
    effects: SittingEffects,
    binding: SittingBinding,
) -> tuple[_EffectRows, ...]:
    """Serialize every effect: its canonical record, its CSV cells and its non-value rows."""
    corner_labels = frozenset(row.label for row in binding.corners)
    rows: list[_EffectRows] = []
    for effect in effect_records(effects):
        key = effect_id(effect.view, effect.metric, effect.name)
        knots = effect.effects
        participant_labels = _participant_labels(knots, key)
        grid = _grid_label(knots[0], corner_labels)
        record = _effect_arrays(key, effect, knots, participant_labels)
        rows.append(
            _EffectRows(
                effect=effect,
                key=key,
                grid=grid,
                participant_labels=participant_labels,
                record=record,
                cells=_csv_cells(
                    effects.pass_name, key, effect, grid, record, participant_labels
                ),
                nonvalue=_nonvalue_rows(key, effect, knots, participant_labels),
            )
        )
    return tuple(rows)


def _effect_arrays(
    key: str,
    effect: DepthEffects,
    knots: Sequence[KnotEffect],
    participant_labels: tuple[str, ...],
) -> EffectArrays:
    """One effect's ten §3 arrays, with every placeholder, mask and state code in closed tables."""
    knot_count = len(knots)
    participant_count = len(participant_labels)
    knots_mm = np.asarray(effect.knots_mm, dtype="<f8")
    values = np.zeros(knot_count, dtype="<f8")
    defined = np.zeros(knot_count, dtype="<u1")
    state = np.zeros(knot_count, dtype="<u1")
    for index, knot in enumerate(knots):
        code = _effect_code(knot.state)
        state[index] = code
        if code == 0:
            if knot.value is None:
                raise _refuse(
                    f"{key}: a defined knot carries no value at index {index}"
                )
            values[index] = float(knot.value)
            defined[index] = 1

    gate = np.full((participant_count, knot_count), -1, dtype="<i4")
    depth = np.zeros((participant_count, knot_count), dtype="<f8")
    offset = np.zeros((participant_count, knot_count), dtype="<f8")
    value = np.zeros((participant_count, knot_count), dtype="<f8")
    p_defined = np.zeros((participant_count, knot_count), dtype="<u1")
    p_state = np.full((participant_count, knot_count), UNALIGNED_READ_CODE, dtype="<u1")
    for index, knot in enumerate(knots):
        reads = {
            member.label: member
            for operand in knot.operands
            for member in operand.members
        }
        for row, label in enumerate(participant_labels):
            read = reads.get(label)
            if read is None:
                raise _refuse(
                    f"{key}: knot {index} carries no read for the participant {label!r}"
                )
            code = _participant_code(read)
            p_state[row, index] = code
            if read.aligned:
                if read.gate_index is None or read.gate_index < 0:
                    raise _refuse(
                        f"{key}: an aligned read carries a nonnegative gate index"
                    )
                gate[row, index] = int(read.gate_index)
                depth[row, index] = float(read.depth_mm)
                offset[row, index] = float(read.offset_mm)
            if code == 0:
                if read.value is None:
                    raise _refuse(
                        f"{key}: a defined read carries no value at knot {index}"
                    )
                value[row, index] = float(read.value)
                p_defined[row, index] = 1

    return EffectArrays(
        effect_id=key,
        knot_count=knot_count,
        participant_count=participant_count,
        knots_mm=knots_mm,
        effect=values,
        defined=defined,
        state=state,
        participant_gate_index=gate,
        participant_depth_mm=depth,
        participant_offset_mm=offset,
        participant_value=value,
        participant_defined=p_defined,
        participant_state=p_state,
    )


def _float_text(number: float | None) -> str:
    """One scalar cell: the empty field where undefined, else ``format(value, ".17g")`` (§6)."""
    if number is None:
        return ""
    return format(float(number), ".17g")


def _csv_cells(
    sitting: str,
    key: str,
    effect: DepthEffects,
    grid: str,
    record: EffectArrays,
    participant_labels: tuple[str, ...],
) -> Mapping[str, object]:
    """One effect's 32 CSV cells, from the engine's own reductions and this run's state array."""
    summary = effect.summary
    states = np.asarray(record.state)
    cells: dict[str, object] = {
        "sitting": sitting,
        "effect_id": key,
        "view": _label(effect.view),
        "metric": _label(effect.metric),
        "contrast": effect.name,
        "units": effect.units,
        "grid": grid,
        "knot_count": int(summary.knot_count),
        "defined_count": int(summary.defined_count),
        "undefined_count": int(summary.undefined_count),
        "undefined_alignment_count": int(
            np.count_nonzero(states == _EFFECT_CODE_UNALIGNED)
        ),
        "undefined_operand_count": int(
            np.count_nonzero(states == _EFFECT_CODE_OPERAND)
        ),
        "covered_depth_mm": float(summary.covered_depth_mm),
        "coverage_fraction": (
            None
            if summary.coverage_fraction is None
            else float(summary.coverage_fraction)
        ),
        "support_low_mm": float(effect.support_mm[0]),
        "support_high_mm": float(effect.support_mm[1]),
        "half_pitch_mm": float(effect.half_pitch_mm),
        "max_abs_offset_mm": float(effect.max_abs_offset_mm),
        "signed_depth_average": summary.signed_depth_average,
        "equal_knot_average": summary.equal_knot_average,
        "rms_magnitude": summary.rms_magnitude,
        "positive_fraction": summary.positive_fraction,
        "negative_fraction": summary.negative_fraction,
        "zero_fraction": summary.zero_fraction,
        "min_value": summary.min_value,
        "min_depth_mm": summary.min_depth_mm,
        "max_value": summary.max_value,
        "max_depth_mm": summary.max_depth_mm,
        "max_abs_value": summary.max_abs_value,
        "max_abs_depth_mm": summary.max_abs_depth_mm,
        "correlation": effect.shape.correlation,
        "correlation_defined_count": int(effect.shape.defined_count),
    }
    missing = [column for column in CSV_COLUMNS if column not in cells]
    if missing:
        raise _refuse(f"{key}: the CSV column set is closed; {missing} have no cell")
    if len(participant_labels) < 1:
        raise _refuse(f"{key}: an effect publishes at least one participant row")
    return cells


def _nonvalue_rows(
    key: str,
    effect: DepthEffects,
    knots: Sequence[KnotEffect],
    participant_labels: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    """Every effect-knot, operand-knot and read whose scalar is missing, then the shape row (§5.5).

    The row set is the *missing-value* set, not the refusal set: a position appears because no
    value is carried and its ``state`` is the distinct reason. A shape row alone uses the
    JSON-only ``undefined-shape`` label and carries no NPZ code.
    """
    rows: list[Mapping[str, object]] = []
    for index, knot in enumerate(knots):
        if knot.state is not EffectState.DEFINED:
            rows.append(
                {
                    "effect_id": key,
                    "kind": "effect-knot",
                    "knot_index": index,
                    "depth_mm": float(knot.depth_mm),
                    "side": None,
                    "member": None,
                    "state": _label(knot.state),
                    "reason": knot.reason,
                }
            )
        for operand in knot.operands:
            if operand.state is EffectState.DEFINED:
                continue
            rows.append(
                {
                    "effect_id": key,
                    "kind": "operand-knot",
                    "knot_index": index,
                    "depth_mm": float(knot.depth_mm),
                    "side": operand.name,
                    "member": None,
                    "state": _label(operand.state),
                    "reason": operand.reason,
                }
            )
        reads = {
            member.label: (operand.name, member)
            for operand in knot.operands
            for member in operand.members
        }
        for label in participant_labels:
            side, read = reads[label]
            if read.defined:
                continue
            rows.append(
                {
                    "effect_id": key,
                    "kind": "read",
                    "knot_index": index,
                    "depth_mm": float(knot.depth_mm),
                    "side": side,
                    "member": label,
                    "state": PARTICIPANT_STATE_CODES[_participant_code(read)],
                    "reason": read.reason,
                }
            )
    if effect.shape.correlation is None:
        rows.append(
            {
                "effect_id": key,
                "kind": "shape",
                "knot_index": None,
                "depth_mm": None,
                "side": None,
                "member": None,
                "state": UNDEFINED_SHAPE,
                "reason": effect.shape.reason,
            }
        )
    return tuple(rows)


# ── the four products, built from one sitting's typed result ───────────


def build_sa5_report(
    pass_ref: PassRef,
    *,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> Sa5Artifacts:
    """Measure one committed sitting and build its four artifacts, or refuse by name.

    Args:
        pass_ref: the sitting to publish. It must be a nine-job design realization whose plan
            marks it a reproducibility sitting; the Stage-2 campaign and the zero-signal first
            pass are refused.
        analysis_commit: the revision the JSON records; defaults to the checkout's short SHA.
        generator_revision: the generator's own revision; defaults to the checkout's short SHA.

    Returns:
        :class:`Sa5Artifacts` for **this sitting alone**.

    Raises:
        SparseSa5ReportError: for a pass that is not a reproducibility sitting, a pass without a
            per-pass inventory, or any condition the engine or the binding refuses.
    """
    _require_sitting_ref(pass_ref)
    effects = measure_sitting(pass_ref)
    binding = bind_sitting(
        _inventory_rows(pass_ref),
        plan_name=pass_ref.name,
        support_mm=effects.support_mm,
    )
    return build_sa5_artifacts(
        effects,
        binding,
        sitting=pass_ref.name,
        stem=sitting_stem(pass_ref.name),
        analysis_commit=analysis_commit,
        generator_revision=generator_revision,
    )


def build_sa5_artifacts(
    effects: SittingEffects,
    binding: SittingBinding,
    *,
    sitting: str,
    stem: str,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> Sa5Artifacts:
    """Build the sitting's four products as bytes, refusing anything the schema does not admit.

    Args:
        effects: the sitting's own typed result (``measure_sitting`` / ``measure_binding``), for
            one sitting only.
        binding: the same sitting's frozen operand binding, already reconciled with the decoded
            recordings by the engine. It supplies ``provenance``, the participant jobs and orders,
            and the control context.
        sitting: the pass name the artifacts are published under.
        stem: the file stem, from :func:`sitting_stem` for a committed sitting.
        analysis_commit: the revision the JSON records; defaults to the checkout's short SHA.
        generator_revision: the generator's own revision; defaults to the checkout's short SHA.

    Returns:
        :class:`Sa5Artifacts` — the canonical NPZ, the strict JSON, the scalar CSV and the
        README, with the digests inside the JSON and the README already bound to the bytes.

    Raises:
        SparseSa5ReportError: for a sitting that does not hold its own gate, a non-finite number
            that would reach the JSON, an effect order or count that is not the frozen one, or an
            artifact check that fails on the staged bytes.
    """
    if not isinstance(effects, SittingEffects):
        raise _refuse(
            f"a sitting's effects are a SittingEffects, got {type(effects).__name__}"
        )
    if not isinstance(binding, SittingBinding):
        raise _refuse(
            f"a sitting's binding is a SittingBinding, got {type(binding).__name__}"
        )
    if effects.plan != binding.plan:
        raise _refuse(
            f"the measured sitting names the plan {effects.plan!r}, the binding names "
            f"{binding.plan!r}; the two must be one sitting"
        )
    keys = tuple(effects.checks)
    if set(keys) != set(ENGINE_CHECK_ORDER):
        raise _refuse(
            f"{sitting}: the engine's checks are {sorted(keys)}, the schema's eleven are "
            f"{sorted(ENGINE_CHECK_ORDER)}; a check that moved is a schema change"
        )
    if not effects.ok:
        failed = sorted(name for name, held in effects.checks.items() if not held)
        raise _refuse(
            f"{sitting}: the engine's own gate does not hold (failed: {failed}), so nothing is "
            "written"
        )
    commit = _revision_text(analysis_commit, "analysis_commit")
    generator = _revision_text(generator_revision, "generator_revision")

    rows = _build_effect_rows(effects, binding)
    npz = encode_effect_npz([row.record for row in rows])
    csv_bytes = _csv_text(rows).encode("utf-8")
    npz_digest = _file_digest(npz)
    csv_digest = _canonical_digest(csv_bytes)

    artifact_checks = _artifact_checks(
        npz=npz, csv=csv_bytes, rows=rows, npz_digest=npz_digest, csv_digest=csv_digest
    )
    failed = sorted(name for name, held in artifact_checks.items() if not held)
    if failed:
        raise _refuse(
            f"{sitting}: the artifact checks do not hold (failed: {failed}), so nothing is written"
        )
    if set(artifact_checks) != set(ARTIFACT_CHECK_NAMES):
        raise _refuse(
            f"{sitting}: the artifact checks are {sorted(artifact_checks)}, the schema's four are "
            f"{sorted(ARTIFACT_CHECK_NAMES)}"
        )

    document = _document(
        effects=effects,
        binding=binding,
        rows=rows,
        sitting=sitting,
        stem=stem,
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
            f"{sitting}: the document cannot be serialized as strict JSON ({exc}); a non-finite "
            "number fails the run before any byte is written"
        ) from exc
    json_bytes = (json_text + "\n").encode("utf-8")
    json_digest = _canonical_digest(json_bytes)

    readme = _readme_text(
        effects=effects,
        binding=binding,
        rows=rows,
        sitting=sitting,
        stem=stem,
        analysis_commit=commit,
        generator_revision=generator,
        npz_digest=npz_digest,
        csv_digest=csv_digest,
        json_digest=json_digest,
    ).encode("utf-8")

    artifacts = Sa5Artifacts(
        sitting=sitting,
        stem=stem,
        npz=npz,
        csv=csv_bytes,
        json=json_bytes,
        readme=readme,
    )
    _verify_digest_binding(artifacts, npz_digest, csv_digest, json_digest)
    return artifacts


def _revision_text(value: str | None, name: str) -> str:
    """One revision string, defaulting to the checkout's short SHA and never to a guess."""
    if value is None:
        return current_revision() or ""
    if not isinstance(value, str):
        raise _refuse(f"{name} is a revision string, got {type(value).__name__}")
    return value


def _artifact_checks(
    *,
    npz: bytes,
    csv: bytes,
    rows: Sequence[_EffectRows],
    npz_digest: str,
    csv_digest: str,
) -> dict[str, bool]:
    """The four §5.1 artifact checks, each computed from the bytes this run staged."""
    expected_members = _member_names(row.key for row in rows)
    with zipfile.ZipFile(io.BytesIO(npz)) as archive:
        names = archive.namelist()
    shapes = {
        row.key: (row.record.knot_count, row.record.participant_count) for row in rows
    }
    try:
        decode_effect_npz(npz, expected=shapes)
        undefined_positions_ok = True
    except ValueError:
        undefined_positions_ok = False
    order_ok = all(
        row.record.participant_count == len(row.participant_labels)
        and row.record.knot_count == len(row.effect.knots_mm)
        and len(set(row.participant_labels)) == len(row.participant_labels)
        for row in rows
    )
    return {
        "npz_members_are_the_closed_set": list(names) == list(expected_members),
        "every_undefined_position_carries_placeholder_mask_and_state": bool(
            undefined_positions_ok
        ),
        "participant_rows_are_the_declared_order": bool(order_ok),
        "digests_match_the_staged_bytes": bool(
            _file_digest(npz) == npz_digest and _canonical_digest(csv) == csv_digest
        ),
    }


def _verify_digest_binding(
    artifacts: Sa5Artifacts, npz_digest: str, csv_digest: str, json_digest: str
) -> None:
    """Re-check the whole chain against the staged bytes: README → JSON → NPZ + CSV."""
    readme = artifacts.readme.decode("utf-8")
    document = artifacts.document()
    recorded = document.get("artifacts")
    if not isinstance(recorded, dict):
        raise _refuse(
            f"{artifacts.sitting}: the document publishes no artifacts object"
        )
    try:
        npz_bound = recorded["npz"]["sha256"]  # type: ignore[index]
        csv_bound = recorded["csv"]["sha256"]  # type: ignore[index]
        npz_name = recorded["npz"]["file"]  # type: ignore[index]
        csv_name = recorded["csv"]["file"]  # type: ignore[index]
    except (KeyError, TypeError) as exc:
        raise _refuse(
            f"{artifacts.sitting}: the artifacts object must name both files and their digests "
            f"({exc})"
        ) from exc
    if npz_bound != npz_digest or csv_bound != csv_digest:
        raise _refuse(
            f"{artifacts.sitting}: the digests the document records are not the digests of the "
            "staged bytes"
        )
    if npz_name != artifacts.npz_name or csv_name != artifacts.csv_name:
        raise _refuse(
            f"{artifacts.sitting}: the artifacts object names {npz_name!r}/{csv_name!r} rather "
            f"than {artifacts.npz_name!r}/{artifacts.csv_name!r}"
        )
    if f"{json_digest}" not in readme:
        raise _refuse(
            f"{artifacts.sitting}: the README does not bind the document's own canonical-LF "
            f"digest {json_digest}, so the digest chain is broken"
        )
    if _canonical_digest(artifacts.json) != json_digest:
        raise _refuse(f"{artifacts.sitting}: the document's own digest is unstable")
    if artifacts.npz_name not in readme or artifacts.csv_name not in readme:
        raise _refuse(
            f"{artifacts.sitting}: the README names neither the container nor the table"
        )


def _member_names(effect_keys: Iterable[str]) -> tuple[str, ...]:
    """The sorted closed member-name list: the ten suffixes of every effect, globally sorted."""
    names = [name for key in effect_keys for name in effect_member_names(key)]
    return tuple(sorted(names))


def _document(
    *,
    effects: SittingEffects,
    binding: SittingBinding,
    rows: Sequence[_EffectRows],
    sitting: str,
    stem: str,
    analysis_commit: str,
    generator_revision: str,
    npz_digest: str,
    csv_digest: str,
    artifact_checks: Mapping[str, bool],
) -> dict[str, object]:
    """The strict-JSON document of §5, its field set closed and its every number from upstream."""
    participants_by_key = {
        row.key: _participants(row.participant_labels, binding) for row in rows
    }
    nonvalue = [entry for row in rows for entry in row.nonvalue]
    document: dict[str, object] = {
        "schema": SCHEMA_ID,
        "ok": bool(effects.ok and all(artifact_checks.values())),
        "checks": {name: bool(effects.checks[name]) for name in ENGINE_CHECK_ORDER},
        "artifact_checks": {
            name: bool(artifact_checks[name]) for name in ARTIFACT_CHECK_NAMES
        },
        "analysis_commit": analysis_commit,
        "generator_revision": generator_revision,
        "generator_command": regeneration_command(sitting),
        "sitting": sitting,
        "plan": effects.plan,
        "plan_fingerprint": effects.plan_fingerprint,
        "window_s": float(effects.window_s),
        "window_revolutions": int(effects.window_revolutions),
        "support_mm": [float(effects.support_mm[0]), float(effects.support_mm[1])],
        "method": METHOD,
        "contrast_source": CONTRAST_SOURCE,
        "provenance": [_operand_document(row) for row in binding.operands],
        "control_labels": list(binding.control_labels),
        "effects": [
            _effect_document(row, participants_by_key[row.key]) for row in rows
        ],
        "npz_members": list(_member_names(row.key for row in rows)),
        "nonvalue_rows": nonvalue,
        "nonvalue_counts": _nonvalue_counts(nonvalue),
        "repeats": [_repeat_document(group) for group in effects.repeats],
        "artifacts": {
            "npz": {"file": f"{stem}{NPZ_SUFFIX}", "sha256": npz_digest},
            "csv": {"file": f"{stem}{CSV_SUFFIX}", "sha256": csv_digest},
        },
    }
    return document


def _effect_document(
    row: _EffectRows, participants: Sequence[Mapping[str, object]]
) -> dict:
    """One effect's JSON record: structure, not numbers (§5.3)."""
    effect = row.effect
    operands = [
        {
            "name": operand.name,
            "kind": operand.kind,
            "members": [member.label for member in operand.members],
        }
        for operand in effect.effects[0].operands
    ]
    return {
        "effect_id": row.key,
        "view": _label(effect.view),
        "metric": _label(effect.metric),
        "contrast": effect.name,
        "expression": effect.expression,
        "reduction": effect.reduction,
        "units": effect.units,
        "grid": row.grid,
        "knot_count": len(effect.knots_mm),
        "participant_count": len(participants),
        "operand_names": list(effect.operand_names),
        "operands": operands,
        "coefficients": [float(value) for value in effect.coefficients],
        "participants": list(participants),
        "support_mm": [float(effect.support_mm[0]), float(effect.support_mm[1])],
        "half_pitch_mm": float(effect.half_pitch_mm),
        "alignment_rule": effect.alignment_rule,
        "state_meanings": {
            "effect": [
                {"code": code, "text": text} for code, text in STATE_MEANINGS["effect"]
            ],
            "participant": [
                {"code": code, "text": text}
                for code, text in STATE_MEANINGS["participant"]
            ],
        },
    }


def _operand_document(row: OperandRow) -> dict[str, object]:
    """One bound operand's provenance row (§5.2) — the seventeen published cells."""
    return {
        "label": row.label,
        "job": row.job,
        "order": int(row.order),
        "identity": row.identity,
        "relative_path": row.relative_path,
        "source_sha256": row.source_sha256,
        "plan": row.plan,
        "plan_fingerprint": row.plan_fingerprint,
        "burst_length": int(row.burst_length),
        "emissions_per_profile": int(row.emissions_per_profile),
        "prf_us": float(row.prf_us),
        "resolution_mm": float(row.resolution_mm),
        "gates": int(row.gates),
        "first_gate_mm": float(row.first_gate_mm),
        "last_gate_mm": float(row.last_gate_mm),
        "supported_gates": int(row.supported_gates),
        "window_s": float(row.window_s),
    }


def _participants(
    labels: Sequence[str], binding: SittingBinding
) -> list[dict[str, object]]:
    """The participant rows in the declared §3.1 order, each an actual recording."""
    published: list[dict[str, object]] = []
    for label in labels:
        row = binding.by_label(label)
        published.append(
            {
                "label": row.label,
                "job": row.job,
                "order": int(row.order),
                "kind": "recording",
            }
        )
    return published


def _repeat_document(group: object) -> dict[str, object]:
    """One descriptive repeat group, scalars only (§5.6)."""
    members = [
        {
            "label": member.label,
            "order": int(member.order),
            "job": member.job,
            "value": None if member.value is None else float(member.value),
            "defined_count": int(member.defined_count),
            "state": None if member.state is None else _label(member.state),
            "reason": member.reason,
        }
        for member in group.members
    ]
    return {
        "condition": group.condition,
        "metric": _label(group.metric),
        "view": _label(group.view),
        "units": group.units,
        "knot_count": int(group.knot_count),
        "defined_members": int(group.defined_members),
        "min_value": None if group.min_value is None else float(group.min_value),
        "max_value": None if group.max_value is None else float(group.max_value),
        "spread": None if group.spread is None else float(group.spread),
        "rule": group.rule,
        "statement": group.statement,
        "members": members,
    }


def _nonvalue_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, int]]:
    """The totals by ``(state, kind)`` in the schema's nested map (§5.5)."""
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        state, kind = str(row["state"]), str(row["kind"])
        by_kind = counts.setdefault(state, {})
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {state: dict(sorted(counts[state].items())) for state in sorted(counts)}


def _csv_text(rows: Sequence[_EffectRows]) -> str:
    """The 72-row scalar table, RFC 4180 quoting, LF terminators and one trailing newline (§6)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([_cell_text(row.cells[column]) for column in CSV_COLUMNS])
    return buffer.getvalue()


def _cell_text(value: object) -> str:
    """One CSV cell text: an int as itself, a float by ``.17g``, ``None`` as the empty field."""
    if value is None:
        return ""
    if isinstance(value, bool):
        raise _refuse("a CSV cell is a number or the empty field, never a boolean")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float_text(value)
    if isinstance(value, str):
        return value
    raise _refuse(f"a CSV cell is a number or text, got {type(value).__name__}")


# ── the README (§7) ────────────────────────────────────────────────────


def _readme_text(
    *,
    effects: SittingEffects,
    binding: SittingBinding,
    rows: Sequence[_EffectRows],
    sitting: str,
    stem: str,
    analysis_commit: str,
    generator_revision: str,
    npz_digest: str,
    csv_digest: str,
    json_digest: str,
) -> str:
    """The README: units, definitions, the two views, the digest chain and the no-go list (§7)."""
    lines: list[str] = []
    lines.append(f"{README_TITLE_PREFIX} — `{sitting}`")
    lines.append("")
    lines.append(
        "One committed sitting's within-sitting effect profiles and their scalar reductions, "
        "published under the accepted v1 schema "
        "(`docs/dop3000/sa5-effect-artifact-schema-proposal.md`). This set is **one sitting**: it "
        "is not a comparison, holds no between-sitting number and reaches no Stage-2 product."
    )
    lines.append("")
    lines.append("## Files and the digest chain")
    lines.append("")
    lines.append(
        f"- `{stem}{NPZ_SUFFIX}` — the canonical `ZIP_STORED` container of NPY v1.0 members: the "
        "per-effect profile arrays and the per-participant reads (§3–§4). It is the profile "
        "array's one home."
    )
    lines.append(
        f"- `{stem}{CSV_SUFFIX}` — one row per effect (72 rows), the **sole** per-effect scalar "
        "record: the reductions, the coverage and the correlation (§6)."
    )
    lines.append(
        f"- `{stem}{JSON_SUFFIX}` — the identity, the closed schema, the provenance, the "
        "alignment and operand definitions, the non-value rows, the descriptive repeats and the "
        "digests (§5). It carries no ndarray and no per-effect scalar."
    )
    lines.append(f"- `{stem}{README_SUFFIX}` — this file.")
    lines.append("")
    lines.append(
        "The chain is one-way: this README binds the document, the document binds the container "
        "and the table, and a file never carries its own digest."
    )
    lines.append("")
    lines.append(
        f"- `{stem}{NPZ_SUFFIX}` sha256: `{npz_digest}` (over its exact file bytes)."
    )
    lines.append(
        f"- `{stem}{CSV_SUFFIX}` sha256: `{csv_digest}` (over its canonical LF bytes, so a "
        "Windows checkout with CRLF materialised on disk hashes to the value git stores)."
    )
    lines.append(
        f"- `{stem}{JSON_SUFFIX}` sha256: `{json_digest}` (canonical LF bytes; this is the "
        "reader's entry point to the chain)."
    )
    lines.append(
        "- every digest is lowercase hex with the `sha256:` prefix, computed from the bytes this "
        "run staged, at the analysis revision below — never from a tree regenerated beside the "
        "destination."
    )
    lines.append("")
    lines.append("## The observation unit and the effect identity")
    lines.append("")
    lines.append(
        "One **effect** per `(sitting, view, metric, contrast-or-interaction)`: nine "
        "`(metric, view)` endpoints, each carrying the seven bound contrasts plus the derived "
        "pitch×burst interaction — 72 effects, the whole row set of the NPZ, the JSON and the "
        "CSV. The effect id is the ordered concatenation of the three frozen vocabulary values, "
        "joined by `__`:"
    )
    lines.append("")
    lines.append("```")
    lines.append('effect_id = "<view>__<metric>__<contrast>"')
    lines.append("```")
    lines.append("")
    lines.append(
        "A reader resolves an id through the JSON `effects` list and **must never parse the id** "
        "string; the id is a stable key, not a grammar."
    )
    lines.append("")
    lines.append("## The NPZ members (closed per effect)")
    lines.append("")
    lines.append(
        "For every effect the member-name set is exactly the ten suffixes below, "
        "prefix-qualified by the effect id, and there is no other member. `K = knot_count` and "
        "`P = participant_count` are published per effect in the document, so the shapes are "
        "stated in two places and must agree."
    )
    lines.append("")
    lines.append("| member | dtype | shape | meaning |")
    lines.append("| --- | --- | --- | --- |")
    for suffix in MEMBER_SUFFIXES:
        lines.append(_member_row(suffix))
    lines.append("")
    lines.append(
        "- **participant rows (`P`)** are the distinct recordings the effect's operands read, in "
        "the engine's contract order: the high operand's members in `Operand.members` order, then "
        "the low operand's members not already present. A corner two-sided contrast has `P = 2`, "
        "the interaction has `P = 4`, an emissions contrast has `P = 5`. The document's "
        "`participants` list publishes the same order, and the `(P,K)` shapes are checked against "
        "it."
    )
    lines.append(
        "- **the finite placeholder**: an undefined effect knot carries `0.0`, mask `0` and a "
        "non-zero state code; a `0.0` in a value array is a measurement only where its mask is "
        "`1`. An **unaligned** read is `gate_index = -1`, depth/offset/value `0.0`, mask `0` and "
        "state code `6`; an **aligned** read whose metric is undefined keeps its real gate index, "
        "depth and offset and carries only a `0.0` value with mask `0` and a code `1`–`5`."
    )
    lines.append(
        "- **strictly increasing knots**, exact little-endian dtypes and C-contiguous payloads; "
        "no member contains `NaN`, `Inf` or an object, so `allow_pickle=False` reading is exact."
    )
    lines.append("")
    lines.append(_weighting_section(effects, rows))
    lines.append("")
    lines.append(_alignment_section(effects))
    lines.append("")
    lines.append("## The CSV columns (closed, one row per effect)")
    lines.append("")
    lines.append(
        "The table is keyed `effect_id` and has one row per effect in the fixed order, with the "
        "columns below in order. An undefined scalar is the **empty field**, never `0`; every "
        'finite float is rendered with `format(value, ".17g")`, the round-trip decimal for '
        "binary64."
    )
    lines.append("")
    for column in CSV_COLUMNS:
        lines.append(_column_row(column))
    lines.append("")
    lines.append("## Acquisitions and anchors, in order")
    lines.append("")
    lines.append(
        "The eleven bound operands, in acquisition order. No block-local anchor is an operand."
    )
    lines.append("")
    lines.append("| order | label | job | relative path | source sha256 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in sorted(binding.operands, key=lambda item: (item.order, item.label)):
        lines.append(
            f"| {int(row.order)} | `{row.label}` | `{row.job}` | `{row.relative_path}` | "
            f"`{row.source_sha256}` |"
        )
    lines.append("")
    if binding.control_labels:
        anchors = ", ".join(f"`{label}`" for label in binding.control_labels)
        lines.append(
            f"Block-local anchor controls present, **context only** and bound to no operand: "
            f"{anchors}."
        )
    else:
        lines.append("No block-local anchor control is present in this sitting.")
    lines.append("")
    lines.append(_views_section(effects))
    lines.append("")
    lines.append("## Non-value rows")
    lines.append("")
    lines.append(
        "`nonvalue_rows` records every effect-knot, operand-knot, participant read or "
        "profile-correlation position whose scalar value is missing, one row per such position, "
        "with `kind` in "
        f"{', '.join(f'`{kind}`' for kind in NONVALUE_KINDS)}. It is the missing-value set, not "
        "the refusal set: a position appears because no value is carried, and its `state` is the "
        "distinct reason. A refusal or an unsupported measurement is never a `0.0`, and a "
        "**defined measured zero** is a value, never a non-value row. `nonvalue_counts` states "
        "the totals by `(state, kind)`."
    )
    lines.append("")
    examples = [row for row in (entry for item in rows for entry in item.nonvalue)][:3]
    for entry in examples:
        lines.append(
            f"- `{entry['kind']}` at `{entry['effect_id']}`"
            + (
                f" knot {entry['knot_index']}"
                if entry["knot_index"] is not None
                else ""
            )
            + f": `{entry['state']}` — {entry['reason']}"
        )
    if not examples:
        lines.append(
            "- this sitting carries no non-value position: every effect knot is defined."
        )
    lines.append("")
    lines.append("## Code vocabulary")
    lines.append("")
    lines.append(
        "The two `uint8` code spaces are closed. A code outside its table is a refused artifact."
    )
    lines.append("")
    lines.append("Table A — effect state (`<effect_id>__state.npy`):")
    lines.append("")
    lines.append("| code | text |")
    lines.append("| --- | --- |")
    for code, text in STATE_MEANINGS["effect"]:
        lines.append(f"| {code} | `{text}` |")
    lines.append("")
    lines.append(
        "Table B — participant read state (`<effect_id>__participant_state.npy`), the metric "
        "states plus the read-level unaligned sentinel:"
    )
    lines.append("")
    lines.append("| code | text |")
    lines.append("| --- | --- |")
    for code, text in STATE_MEANINGS["participant"]:
        lines.append(f"| {code} | `{text}` |")
    lines.append("")
    lines.append("## Repeat groups — descriptive only")
    lines.append("")
    lines.append(
        "`repeats` describes same-whole-condition repeat groups as scalars: member labels, "
        "orders, jobs, values, defined counts, states and reasons, and the group's spread. No "
        "spread is a floor, no member is a replicate, and there is no per-depth repeat array."
    )
    lines.append("")
    lines.append("## Provenance and digests")
    lines.append("")
    lines.append(f"- sitting: `{sitting}`.")
    lines.append(f"- plan: `{effects.plan}`.")
    lines.append(f"- plan fingerprint: `{effects.plan_fingerprint}`.")
    lines.append(f"- analysis revision: `{analysis_commit}`.")
    lines.append(f"- generator revision: `{generator_revision}`.")
    lines.append(
        f"- window: {effects.window_s:g} s, {effects.window_revolutions} revolutions."
    )
    lines.append(
        f"- common support: {effects.support_mm[0]:.17g} .. {effects.support_mm[1]:.17g} mm."
    )
    lines.append(
        "Publication is staged: every file is written beside its destination under a unique, "
        "fsynced temporary name and moved onto its final name with one `os.replace` at a time. "
        "The four-file set is **not** a transaction, so a failure after some renames can leave a "
        "mixed set — one a reader detects by recomputing the digests above. An existing SA5 stem "
        "is never overwritten to guess ownership: a full byte-identical set is left untouched, "
        "and any missing or differing file makes the run refuse rather than replace a file it did "
        "not produce."
    )
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append(
        f"Run from a checkout of the recorded generator revision `{generator_revision}`. "
        "Set `SA5_SCRATCH` to an absolute directory **outside the checkout**; do not "
        "regenerate into this committed report root. A later checkout has a different "
        "default revision and must not overwrite an existing artifact set."
    )
    lines.append("")
    lines.append("```bash")
    lines.append(
        f'{regeneration_command(sitting)} --report-dir "$SA5_SCRATCH" '
        f"--analysis-commit {analysis_commit} "
        f"--generator-revision {generator_revision}"
    )
    lines.append("```")
    lines.append("")
    lines.append("## What this artifact does not claim")
    lines.append("")
    for item in NO_GO_LIST:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## The gate")
    lines.append("")
    for name in ENGINE_CHECK_ORDER:
        lines.append(f"- `{name}` — {'ok' if effects.checks[name] else 'FAILED'}")
    for name in ARTIFACT_CHECK_NAMES:
        lines.append(f"- `{name}` — ok")
    # No trailing blank line: every artifact ends in exactly one newline.
    return "\n".join(lines) + "\n"


def _member_row(suffix: str) -> str:
    """One README table row for a closed NPZ member suffix."""
    dtype = MEMBER_DTYPES[suffix]
    per_knot = suffix in ("knots_mm", "effect", "defined", "state")
    shape = "(K,)" if per_knot else "(P,K)"
    meaning = _MEMBER_MEANING[suffix]
    return f"| `<effect_id>__{suffix}.npy` | `{dtype.str}` | `{shape}` | {meaning} |"


#: What each closed member means, for the README's member table (§3).
_MEMBER_MEANING: Mapping[str, str] = {
    "knots_mm": "the effect's knot depths, strictly increasing",
    "effect": "the oriented effect value where defined, the finite placeholder `0.0` where not",
    "defined": "the mask: `1` exactly where the effect state is `defined`, else `0`",
    "state": "the effect state code (table A)",
    "participant_gate_index": "each participant's native gate index, `-1` where that read is unaligned",
    "participant_depth_mm": "each participant's native depth, `0.0` where that read is unaligned",
    "participant_offset_mm": "each participant's signed `depth - knot` offset, `0.0` where unaligned",
    "participant_value": "each participant's measured value, `0.0` where not defined",
    "participant_defined": "mask: `1` exactly where the read state is `defined`, else `0`",
    "participant_state": "the participant read state code (table B)",
}


#: What each CSV column is, for the README's column list (§6).
_COLUMN_MEANING: Mapping[str, str] = {
    "sitting": "the pass name this row set belongs to",
    "effect_id": "`<view>__<metric>__<contrast>`, the stable key into the JSON `effects` list",
    "view": "`primary-comparison` or `full-record`",
    "metric": "the observable (`mean`, `std`, `mad_scaled`, `recurrence-1e-lag`, "
    "`recurrence-peak-lag`, `band_fraction`)",
    "contrast": "the bound contrast name, or `pitch_x_burst_interaction`",
    "units": "the effect's unit (`mm/s`, `s` or `dimensionless`)",
    "grid": "`corner_knots` or `emissions_knots` — the knot grid the effect was aligned on",
    "knot_count": "`K`, the number of knots",
    "defined_count": "the knot count whose effect is defined",
    "undefined_count": "`K` less the defined count",
    "undefined_alignment_count": "the knots with effect state code `2` (undefined-alignment)",
    "undefined_operand_count": "the knots with effect state code `1` (undefined-operand)",
    "covered_depth_mm": "`L`, the summed depth of adjacent knot pairs whose both endpoints define "
    "the effect",
    "coverage_fraction": "`L / (last knot - first knot)`; empty for a one-knot profile",
    "support_low_mm": "the low edge of the effect's participating common support (not the "
    "coverage denominator)",
    "support_high_mm": "the high edge of that common support",
    "half_pitch_mm": "half the mean knot pitch, the alignment tolerance",
    "max_abs_offset_mm": "the alignment scalar: the largest absolute native offset used (the "
    "engine's `DepthEffects` row, not the summary)",
    "signed_depth_average": "the trapezoidal signed depth average over the valid intervals; empty "
    "where `L = 0`",
    "equal_knot_average": "the equal-weight mean over defined knots (not the integral)",
    "rms_magnitude": "the trapezoidal RMS magnitude over the valid intervals; empty where `L = 0`",
    "positive_fraction": "the fraction of defined non-zero knots with a positive effect",
    "negative_fraction": "the fraction of defined non-zero knots with a negative effect",
    "zero_fraction": "the fraction of defined knots with an exactly zero effect (the "
    "denominator is `defined_count`, unlike the two non-zero-knot fractions above)",
    "min_value": "the smallest defined effect",
    "min_depth_mm": "the depth the minimum was reached at",
    "max_value": "the largest defined effect",
    "max_depth_mm": "the depth the maximum was reached at",
    "max_abs_value": "the largest absolute effect (ties resolved to the shallower depth)",
    "max_abs_depth_mm": "the depth the largest absolute effect was reached at",
    "correlation": "the Pearson correlation of the compared pair of profiles; empty on a shape "
    "refusal",
    "correlation_defined_count": "the number of common defined knots the correlation used",
}


def _column_row(column: str) -> str:
    """One README bullet for a closed CSV column."""
    unit = COLUMN_UNITS.get(column)
    suffix = f" (unit `{unit}`)" if unit else ""
    return f"- **`{column}`**{suffix} — {_COLUMN_MEANING[column]}."


def _weighting_section(effects: SittingEffects, rows: Sequence[_EffectRows]) -> str:
    """The README's weighting section: the engine's rule text, quoted, with the unit."""
    units = sorted({row.effect.units for row in rows})
    return (
        "## The physical-depth weighting rule\n\n"
        f"{WEIGHTING_RULE}\n\n"
        "The unit of every value and reduction is the effect's own `units` cell "
        f"({', '.join(f'`{unit}`' for unit in units)}); displacements are `mm/s`, lags `s` and "
        "`band_fraction` `dimensionless` (a Φ difference is a dimensionless difference, never a "
        "relative percentage gain)."
    )


def _alignment_section(effects: SittingEffects) -> str:
    """The README's alignment section: the engine's rule text, quoted once."""
    rule = effects.endpoints[0].contrasts[0].alignment_rule
    return f"## The alignment rule\n\n{rule}"


def _views_section(effects: SittingEffects) -> str:
    """The README's view section: the two named views and their differing axes."""
    views = sorted({view.value for view in (item.view for item in effects.endpoints)})
    return (
        "## The two views\n\n"
        f"This set carries the two named views `{views[0]}` and `{views[1]}`, never mixed in one "
        "profile. The **primary comparison** is the sitting's declared window "
        f"({effects.window_s:g} s, {effects.window_revolutions} revolutions), cut from each "
        "recording's own stored stamps; the **full record** keeps every stored profile of the "
        "recording, so it is the longer view. Both are read on the recording's own native gate "
        "grid: the longer view has the finer frequency resolution `1/T` at the same effective "
        "sample rate and Nyquist `1/(2·dt)`, and a fluctuation scale (`mean`, `std`, `mad_scaled`) "
        "is declared on the primary comparison only. The exact duration, gate pitch and sample "
        "rate of each view are the recordings' own decoded axes, published per gate by the "
        "recordings' own reports; this set publishes no axis number it did not measure."
    )


# ── publication (§9) ───────────────────────────────────────────────────


def write_sa5_report(
    pass_ref: PassRef,
    destination: Path,
    *,
    analysis_commit: str | None = None,
    generator_revision: str | None = None,
) -> Sa5Artifacts:
    """Build one sitting's artifacts and publish them into ``destination``.

    Args:
        pass_ref: the sitting to publish, as :func:`build_sa5_report`.
        destination: the directory to write into. The plan's designated root, or a directory
            outside the repository (a scratch tree a caller or a test owns). A *relative* path is
            anchored at the repository root, so the plan's own default lands in the same tree
            wherever the command is run from.
        analysis_commit: the revision to record, as :func:`build_sa5_report`.
        generator_revision: the generator's own revision, as :func:`build_sa5_report`.

    Returns:
        The :class:`Sa5Artifacts` that were built and published.

    Raises:
        SparseSa5ReportError: as :func:`build_sa5_report`, and any refusal of
            :func:`write_sa5_artifacts`.
    """
    _require_destination(destination)
    artifacts = build_sa5_report(
        pass_ref, analysis_commit=analysis_commit, generator_revision=generator_revision
    )
    write_sa5_artifacts(artifacts, destination)
    return artifacts


def write_sa5_artifacts(artifacts: Sa5Artifacts, destination: Path) -> None:
    """Publish an already-built four-file set, or refuse without replacing any existing file.

    The destination rules are checked first (a frozen tree, the repository root, or a tree inside
    the repository that is not the plan's publish root is refused). The publication lock is then
    taken **before** the ownership of any existing file is judged, and the idempotent/differing
    decision is made *under* the lock: if all four names already exist and are byte-identical to
    this run's products the set is published idempotently and does nothing; any missing or
    differing file makes the run refuse and leave every existing file untouched. Deciding
    ownership before the lock would let a concurrent run that published between our check and our
    lock be silently overwritten, so the check is not made outside the lock. A leftover stage file
    or lock from an interrupted run is refused by name rather than adopted or deleted.

    Raises:
        SparseSa5ReportError: on any destination, ownership, lock or stage refusal.
    """
    directory = _require_destination(destination)
    directory.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(directory, artifacts.stem)
    try:
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


def _existing_set_is_this_run(directory: Path, artifacts: Sa5Artifacts) -> bool:
    """Whether the destination already carries this run's complete byte-identical set.

    Called **under** the publication lock, so a concurrent run cannot publish between the check
    and the publish and be silently overwritten. Returns ``True`` for the idempotent case (all
    four names present as files and byte-identical), and refuses, naming the reason, for a
    non-file entry, an incomplete set or any differing byte.
    """
    existing = [name for name, _ in artifacts.files if (directory / name).exists()]
    if not existing:
        return False
    not_files = [name for name in existing if not (directory / name).is_file()]
    if not_files:
        raise _refuse(
            f"{directory.as_posix()!r} carries a non-file entry named {not_files[0]!r}; an "
            "SA5 artifact name must be a file this writer produced"
        )
    missing = [name for name, _ in artifacts.files if name not in existing]
    if missing:
        raise _refuse(
            f"{directory.as_posix()!r} carries an incomplete SA5 set: existing "
            f"{existing}, missing {missing}. A partial set is evidence of an interrupted "
            "publication or an unrelated file, and this writer never guesses ownership, so "
            "it refuses without replacing any existing file."
        )
    differing = [
        name
        for name, payload in artifacts.files
        if (directory / name).read_bytes() != payload
    ]
    if differing:
        raise _refuse(
            f"{directory.as_posix()!r} carries an SA5 file this run did not produce "
            f"({differing}); its bytes differ from this run's staged products, so the "
            "publication refuses rather than clobber a file of unknown provenance."
        )
    return True


def _require_destination(destination: Path) -> Path:
    """Resolve and gate one destination, refusing a frozen or foreign tree (§9)."""
    directory = _resolve_destination(destination)
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


def _resolve_destination(destination: Path) -> Path:
    """Anchor a *relative* destination at the repository root, never the working directory."""
    return _anchor_repository(destination)


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
    """Every frozen report tree this writer must not enter: the passes' own, plus the extra one.

    The three committed passes' own ``report_dir``s come from the pass catalog and are never
    restated here; ``reports/mixer-sensitivity-analysis`` is a frozen tree with no ``PassRef`` of
    its own and is carried by :data:`EXTRA_FROZEN_REPORT_DIRS`, so it cannot be dropped by
    omission. Every entry is a repository-relative path and is anchored at the repository root
    (:func:`_anchor_repository`), so the guard compares against the same tree wherever the
    command is run from — a relative path resolved against the *working* directory would point
    at a same-named scratch tree under an unrelated cwd and protect the wrong location.
    """
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
    """Why ``directory`` may not be published to, or ``None`` when it may (§9).

    The rules, narrowest first: the destination may not be the repository root or an ancestor of
    it; a destination *inside* the repository must be exactly the plan's designated publish root
    :data:`REPORT_DIR`; and no destination may lie inside a frozen report tree. A destination
    outside the repository — a scratch directory a caller or a test owns — is left to the caller,
    which is what lets the writer be exercised without touching the checkout.
    """
    resolved = directory.resolve()
    repository = _repository_root()
    designated = (repository / REPORT_DIR).resolve()
    if resolved.exists() and not resolved.is_dir():
        return (
            f"the destination {directory.as_posix()!r} exists and is not a directory, so the four "
            "artifacts cannot be placed inside it"
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
                f"{frozen.as_posix()!r}: the WP and SA2.4 reports are byte-untouched by any run of "
                "this generator"
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
            "it could release this lock. Two runs would interleave their files and the set is not "
            "a transaction, so this run refuses rather than racing; remove the lock only once no "
            "writer holds it."
        ) from exc
    os.close(descriptor)
    return lock


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


def _require_sitting_ref(pass_ref: PassRef) -> None:
    """Refuse a pass that is not one of the two reproducibility sittings (§1, §9)."""
    if not isinstance(pass_ref, PassRef):
        raise _refuse(f"a sitting is a PassRef, got {type(pass_ref).__name__}")
    if pass_ref.role is not PassRole.SITTING:
        raise _refuse(
            f"{pass_ref.name!r} is a {pass_ref.role.value}, not a sitting: an SA5 effect artifact "
            "is published per sitting only, and the Stage-2 campaign is contextual, never a third "
            "sitting"
        )
    if not pass_ref.is_reproducibility_sitting:
        raise _refuse(
            f"{pass_ref.name!r} is not a reproducibility sitting "
            "(is_reproducibility_sitting is False): only the two mixer-enabled sittings live-1 "
            "and live-2 are published by this generator, one invocation each, and a "
            "sitting-shaped pass that is acquisition provenance rather than a replicate is never "
            "counted as one"
        )
    if pass_ref.report_dir is None:
        raise _refuse(
            f"{pass_ref.name!r} has no per-pass inventory directory to bind from"
        )
    if _inventory_path(pass_ref) is None:
        raise _refuse(
            f"{pass_ref.name!r} has no committed points.csv under {pass_ref.report_dir}"
        )


def _inventory_path(pass_ref: PassRef) -> Path | None:
    """The sitting's committed per-pass inventory, or ``None`` when it is not there."""
    if pass_ref.report_dir is None:
        return None
    path = Path(pass_ref.report_dir) / "points.csv"
    return path if path.is_file() else None


def _inventory_rows(pass_ref: PassRef) -> tuple[dict[str, str], ...]:
    """The sitting's committed per-pass inventory rows, or a refusal naming the missing file."""
    path = _inventory_path(pass_ref)
    if path is None:
        raise _refuse(
            f"{pass_ref.name!r} has no committed per-pass inventory at "
            f"{Path(str(pass_ref.report_dir)) / 'points.csv'}; a sitting is bound from its own "
            "committed points.csv and this writer will not substitute one"
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _refuse(f"cannot read the per-pass inventory {path}: {exc}") from exc
    return tuple(csv.DictReader(text.splitlines()))


# ── the command line (§9) ──────────────────────────────────────────────


def report_main(argv: Sequence[str] | None = None) -> None:
    """``sparse-sa5-report`` — write one committed sitting's four SA5 artifacts.

    The runnable module-invoked form the plan's verification section names:
    ``python -m udv_echo_process.analysis.sparse_sa5_report --sitting <name> [--report-dir <path>]``.

    The one required flag is ``--sitting``: a committed pass **name**. It is resolved to its
    :class:`~udv_echo_process.analysis.sparse_passes.PassRef` and every pass that is not one of
    the two reproducibility sittings is refused — a campaign (``stage2-e20-e64``), the
    zero-signal first pass or an unknown name is not a sitting this writer publishes, so a
    caller cannot name a campaign into a report. ``--report-dir`` selects the destination
    (default: the plan's designated root) and ``--analysis-commit``/``--generator-revision``
    override the revisions the JSON records (default: the checkout's short SHA).

    Exits 0 when the sitting's gate holds and its four files are published, and 1 on any
    refusal, naming the reason on stderr. Nothing is written when a refusal is raised, so a
    refused run leaves the destination byte-unchanged.

    Raises:
        SystemExit: 0 on a published set, 1 on a refusal (and 2 on a usage error, from
            :mod:`argparse`).
    """
    parser = argparse.ArgumentParser(
        prog="udv-sparse-sa5-report",
        description=(
            "SA5: one committed sitting's within-sitting effect artifacts — the canonical NPZ "
            "container, the scalar CSV, the strict JSON document and the README — for exactly "
            "one reproducibility sitting"
        ),
    )
    parser.add_argument(
        "--sitting",
        required=True,
        help="name of a committed reproducibility sitting (sparse-mixer-live-1 or -2)",
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
        pass_ref = pass_by_name(args.sitting)
    except KeyError as exc:
        reason = exc.args[0] if exc.args else exc
        print(f"udv-sparse-sa5-report: {reason}", file=sys.stderr)
        raise SystemExit(1) from None
    try:
        artifacts = write_sa5_report(
            pass_ref,
            Path(args.report_dir),
            analysis_commit=args.analysis_commit,
            generator_revision=args.generator_revision,
        )
    except SparseSa5ReportError as exc:
        print(f"udv-sparse-sa5-report: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    document = artifacts.document()
    print(f"sitting : {artifacts.sitting}")
    print(f"plan    : {document['plan']}")
    print(
        f"effects : {len(document['effects'])} effects, "
        f"{len(document['npz_members'])} container members"
    )
    for name in artifacts.names:
        print(f"file    : {Path(args.report_dir) / name}")
    print(f"npz     : {document['artifacts']['npz']['sha256']}")
    print(f"csv     : {document['artifacts']['csv']['sha256']}")
    print(f"checks  : {'all pass' if document['ok'] else 'FAILED'}")
    raise SystemExit(0)


if __name__ == "__main__":
    report_main()
