"""SA5's **independent verifier** of one sitting's published effect artifacts (§11).

``docs/dop3000/sa5-effect-artifact-schema-proposal.md`` (accepted v1) publishes, per
sitting, four files under ``reports/sparse-signal/``: ``sa5-live-N-effects.npz`` (the
profile arrays), ``sa5-live-N-effects.csv`` (the one per-effect scalar row set),
``sa5-live-N-effects.json`` (identity, provenance, definitions, non-value rows, repeats,
digests) and ``sa5-live-N-effects.README.md`` (definitions and digest binding). §10.4 makes
an independent verifier part of the contract, and §11 fixes what it must do:

1. re-derive the binding from the sitting's **own committed ``points.csv``**
   (:func:`~udv_echo_process.analysis.sparse_sa5_bindings.bind_sitting`) and the **decoded
   recordings** (:func:`~udv_echo_process.analysis._sparse_pass.decode_pass`), reconciling
   every operand's digest, job, acquisition order and achieved settings against the file it
   names — an inventory row is not evidence until it is reconciled with that file;
2. **recompute** the metrics and effects through the frozen slices
   (``read_metric_profile`` → :func:`~udv_echo_process.analysis.sparse_sa5_effects.measure_binding`),
   including the E20 equal-weight mean, rather than trusting the artifact's numbers;
3. compare **element-wise**: every NPZ array, every CSV scalar, the JSON structure,
   provenance and non-value rows, against the recomputed profiles and states;
4. re-check the invariants a writer could get wrong silently (clauses, states, shapes,
   participant order, member set, anchors, no cross-sitting number);
5. check the **digests last** — a matching digest over wrong numbers is still wrong.

This module is that program and nothing else. It is deliberately *not* a reader of the
artifact's own claims: it never imports the generator, never reads a staged value as input,
and never trusts the writer's ``ok``, ``checks`` or ``npz_members`` — each of those is a
claim to be contradicted by the recomputation. It publishes nothing, writes no file, and
measures **one sitting per invocation**: a :class:`~sparse_passes.PassRef` that is not a
reproducibility sitting (the Stage-2 campaign, the first zero-signal pass, a sitting-shaped
dataset with no published effects) is refused before any file is opened. No cross-sitting
arithmetic is performed anywhere.

How the four layers are checked, and why the order matters
----------------------------------------------------------
The NPZ is decoded through the **shared canonical codec**
(:func:`~udv_echo_process.analysis.sparse_sa5_npz.decode_effect_npz`), which owns the §4
byte rule — a compressed member, a drifted timestamp, an out-of-order or missing member, or
a payload that is not the fixed little-endian NPY v1.0 array is refused there rather than
here. That makes the container *valid*; it does not make its numbers *right*, which is why
every array is then compared element-wise against the independently recomputed profile.
The CSV is parsed as text and each cell compared against the recomputed
``DepthSummary``/``ProfileShape``: an undefined scalar is the empty field, a number is
``format(value, ".17g")``, so the comparison is exact and a single rounded or shifted digit
fails. The JSON is checked as a **closed** structure (a new field is a schema change, not a
new value), its mirrored shape counts and its ``npz_members`` against the recomputed closed
member set, its provenance rows against the reconciled binding, its ``nonvalue_rows``
against the recomputed missing positions and its ``repeats`` against the engine's own
descriptive groups. The digests come last, over the exact bytes this run read: the NPZ's
file bytes, the CSV's canonical-LF bytes and the JSON's canonical-LF bytes, all three of which
the README must carry (and every ``sha256:`` token the README states must be one of them).

Where this verifier is deliberately lenient
-------------------------------------------
The doc fixes some cells exactly and leaves others to the writer's discretion; the leniency
is named rather than silent. ``state_meanings`` is checked **per code space**: §5.3 fixes the
§8 vocabulary but not its exact rendering, so both the writer's ``{effect: [{code, text}]}``
lists and a plain ``{effect: {code: text}}`` mapping are read, but each named space must equal
its **own** closed table — the two spaces are not interchangeable, so a content-only scan that
merely looked for every text somewhere would accept the tables swapped or a dropped code. A
``member`` cell of an ``operand-knot`` non-value row may be the offending member's label or
null, because §5.5 fixes ``side``/``member`` only where the position is the effect's own and
states the member rule for a ``read`` row. ``nonvalue_counts`` is read as the nested
``state → kind → total`` mapping, which is the natural reading of §5.5's "totals by
``(state, kind)``". Nothing else is loosened: a wrong number, state, reason, count, order,
name or digest is a refusal.

Two limits are stated rather than hidden. The verifier cannot check that the JSON's
``analysis_commit`` names the revision this process has checked out — it never runs a
version-control command — so that cell is only required to be a non-empty string, and
whether it is the *right* commit stays a reviewer's check. And it verifies the artifact
against a fresh recomputation **in this process at the code it imports**: a verifier run at
an analysis revision other than the one the JSON records establishes a disagreement, not
that the published bytes were wrong when they were written.

The recomputation seam
----------------------
:func:`recompute_sa5_sources` is the *only* way the verifier obtains a binding and its
effects, and it is a module-level function so a test can replace the source-loading with a
synthetic sitting while the comparisons stay real. It must never be replaced in a published
verification: :func:`verify_sa5_artifacts` refuses when the recomputation itself refuses,
rather than falling back to the artifact's own numbers.

It composes the same three frozen steps
:func:`~udv_echo_process.analysis.sparse_sa5_effects.measure_sitting` composes — decode the
pass, bind the sitting's own committed inventory, measure the effects — rather than calling
it, for the one reason §11.1 needs: the binding is an input to the comparison (the JSON's
provenance rows are checked against the eleven rows the binding holds), so the verifier must
keep it rather than take it back as a side effect.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.analysis._floor_documents import table_digest
from udv_echo_process.analysis._native_grid import TOLERANCE_S
from udv_echo_process.analysis._sparse_pass import PassDecoding, decode_pass
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_inventory import SparseIngestError
from udv_echo_process.analysis.sparse_passes import PassRef, PassRole
from udv_echo_process.analysis.sparse_sa5_bindings import (
    Operand,
    SittingBinding,
    bind_sitting,
    recording,
)
from udv_echo_process.analysis.sparse_sa5_effects import (
    CONTRAST_SOURCE,
    ENDPOINTS,
    INTERACTION_NAME,
    METHOD,
    DepthEffects,
    EffectState,
    OperandRead,
    ReadAligned,
    SittingEffects,
    measure_binding,
)
from udv_echo_process.analysis.sparse_sa5_metrics import (
    MetricName,
    MetricState,
)
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    MEMBER_DTYPES,
    MEMBER_SUFFIXES,
    PARTICIPANT_STATE_CODES,
    UNALIGNED_READ_CODE,
    EffectArrays,
    EffectShape,
    NpzContainerError,
    NpzSchemaError,
    decode_effect_npz,
    member_name,
)
from udv_echo_process.analysis.sparse_spectral_characterization import DEFAULT_LOW_HZ

__all__ = [
    "ARTIFACT_CHECKS",
    "CSV_COLUMNS",
    "ENGINE_CHECKS",
    "JSON_KEYS",
    "SCHEMA",
    "Sa5Sources",
    "Sa5Verification",
    "Sa5VerificationError",
    "artifact_dir_of",
    "artifact_paths",
    "artifact_stem",
    "effect_id_of",
    "recompute_sa5_sources",
    "verify_sa5_artifacts",
]

#: The schema label the JSON must carry (§5.1).
SCHEMA = "sa5-within-sitting-effects/v1"

#: The two grid labels a §5.3 effect record may carry (§5.3, §2).
CORNER_GRID = "corner_knots"
EMISSIONS_GRID = "emissions_knots"

#: The digest prefix every published digest carries (§5.7).
DIGEST_PREFIX = "sha256:"

#: The prefix a pass name must carry for its artifact stem to be derivable (§1).
_PASS_PREFIX = "sparse-mixer-"

#: The closed CSV column set, in the doc's order (§6).
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

#: The CSV's text columns; every other cell is a number or the empty field.
CSV_TEXT_COLUMNS: tuple[str, ...] = (
    "sitting",
    "effect_id",
    "view",
    "metric",
    "contrast",
    "units",
    "grid",
)

#: The closed top-level JSON field set (§5).
JSON_KEYS: tuple[str, ...] = (
    "schema",
    "ok",
    "checks",
    "artifact_checks",
    "analysis_commit",
    "generator_revision",
    "generator_command",
    "sitting",
    "plan",
    "plan_fingerprint",
    "window_s",
    "window_revolutions",
    "support_mm",
    "method",
    "contrast_source",
    "provenance",
    "control_labels",
    "artifacts",
    "effects",
    "npz_members",
    "nonvalue_rows",
    "nonvalue_counts",
    "repeats",
)

#: The closed field set of one §5.3 effect record.
EFFECT_KEYS: tuple[str, ...] = (
    "effect_id",
    "view",
    "metric",
    "contrast",
    "expression",
    "reduction",
    "units",
    "grid",
    "knot_count",
    "participant_count",
    "operand_names",
    "operands",
    "coefficients",
    "participants",
    "support_mm",
    "half_pitch_mm",
    "alignment_rule",
    "state_meanings",
)

#: The closed field set of one operand definition (§5.3).
OPERAND_KEYS: tuple[str, ...] = ("name", "kind", "members")

#: The closed field set of one participant row (§3.1, §5.3).
PARTICIPANT_KEYS: tuple[str, ...] = ("label", "job", "order", "kind")

#: The closed field set of one provenance row (§5.2, ``OperandRow``).
PROVENANCE_KEYS: tuple[str, ...] = (
    "label",
    "job",
    "order",
    "identity",
    "relative_path",
    "source_sha256",
    "plan",
    "plan_fingerprint",
    "burst_length",
    "emissions_per_profile",
    "prf_us",
    "resolution_mm",
    "gates",
    "first_gate_mm",
    "last_gate_mm",
    "supported_gates",
    "window_s",
)

#: The closed field set of one non-value row (§5.5).
NONVALUE_KEYS: tuple[str, ...] = (
    "effect_id",
    "kind",
    "knot_index",
    "depth_mm",
    "side",
    "member",
    "state",
    "reason",
)

#: The non-value row kinds (§5.5).
NONVALUE_KINDS: tuple[str, ...] = ("effect-knot", "operand-knot", "read", "shape")

#: The JSON-only shape state label; it has no NPZ code (§5.5).
SHAPE_STATE = "undefined-shape"

#: The closed field set of one repeat group (§5.6).
REPEAT_KEYS: tuple[str, ...] = (
    "condition",
    "metric",
    "view",
    "units",
    "knot_count",
    "defined_members",
    "min_value",
    "max_value",
    "spread",
    "rule",
    "statement",
    "members",
)

#: The closed field set of one repeat member (§5.6).
REPEAT_MEMBER_KEYS: tuple[str, ...] = (
    "label",
    "order",
    "job",
    "value",
    "defined_count",
    "state",
    "reason",
)

#: The engine's own check names (§5.1).
ENGINE_CHECKS: tuple[str, ...] = (
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

#: The schema-level artifact check names (§5.1).
ARTIFACT_CHECKS: tuple[str, ...] = (
    "npz_members_are_the_closed_set",
    "every_undefined_position_carries_placeholder_mask_and_state",
    "participant_rows_are_the_declared_order",
    "digests_match_the_staged_bytes",
)

#: The three digest-bearing artifact kinds, and the file extension of each (§1).
_ARTIFACT_EXTENSIONS: Mapping[str, str] = {
    "npz": ".npz",
    "csv": ".csv",
    "json": ".json",
}

#: The reverse tables: the backend's own state text back to the schema's closed code (§8).
_EFFECT_CODE_BY_TEXT: Mapping[str, int] = {
    text: code for code, text in EFFECT_STATE_CODES.items()
}
_PARTICIPANT_CODE_BY_TEXT: Mapping[str, int] = {
    text: code for code, text in PARTICIPANT_STATE_CODES.items()
}

#: The two §8 code-space labels ``state_meanings`` is read under. The vocabulary is closed and
#: the two spaces are *not* interchangeable (codes ``1`` and ``2`` differ between them), so a
#: space is resolved by its own label rather than by a content-only scan that could be satisfied
#: with the two tables swapped.
_EFFECT_SPACE = "effect"
_PARTICIPANT_SPACE = "participant"

#: A ``sha256:<64 hex>`` digest token as a published file names one; a bare 64-hex source digest
#: (an operand's ``source_sha256``) has no prefix and is deliberately not matched by this.
_DIGEST_TOKEN = re.compile(r"sha256:[0-9a-f]{64}")

#: A knot's alignment is a refusal once the nearest native gate lies farther than half the
#: knot pitch away; the engine's own tolerance, restated for the verifier's re-derivation.
GATE_TOLERANCE_MM = 1e-6

#: The relative tolerance a decoded setting is reconciled with (the engine's own).
GRID_RTOL = 1e-6


class Sa5VerificationError(SparseIngestError):
    """A sitting's published artifacts are not the recomputed ones, or cannot be verified.

    Raised for a pass that is not exactly one reproducibility sitting, for a missing or
    unreadable artifact file, for a recomputation that refuses (so there is no independent
    number to compare against), and for any disagreement between the artifact and the
    recomputation — a wrong array, scalar, state, reason, count, order, name or digest. The
    message lists **every** disagreement found, not the first, because one tampered cell
    usually implies several.
    """


class Sa5Sources(NamedTuple):
    """One sitting's recomputed evidence: its decoding, its binding and its effects."""

    decoding: PassDecoding
    binding: SittingBinding
    effects: SittingEffects


class Sa5Verification(NamedTuple):
    """What one successful verification established, with the digests it read."""

    sitting: str
    plan: str
    artifact_dir: Path
    stem: str
    effect_count: int
    csv_rows: int
    checks: Mapping[str, bool]
    digests: Mapping[str, str]

    @property
    def ok(self) -> bool:
        """True exactly when every check of the verification holds."""
        return all(self.checks.values())


class _ExpectedEffect(NamedTuple):
    """One effect as the recomputation says it must appear in all three artifacts."""

    effect_id: str
    grid: str
    view: str
    metric: str
    contrast: str
    record: Mapping[str, object]
    csv: Mapping[str, object]
    arrays: EffectArrays
    effect: DepthEffects


class _ExpectedEffects(NamedTuple):
    """The whole recomputed sitting: its 72 effects, their member set and their shapes."""

    records: tuple[_ExpectedEffect, ...]
    by_id: Mapping[str, _ExpectedEffect]
    members: tuple[str, ...]
    shapes: Mapping[str, EffectShape]


class _Failures:
    """The disagreements found so far, each a sentence naming what and where."""

    def __init__(self, where: str) -> None:
        self.where = where
        self.items: list[str] = []

    def require(self, ok: bool, message: str) -> bool:
        """Record ``message`` unless ``ok``, and return ``ok`` for a caller to branch on."""
        if not ok:
            self.items.append(message)
        return bool(ok)

    def equal(self, what: str, found: object, expected: object) -> bool:
        """Record a disagreement when two cells differ, showing both."""
        return self.require(
            found == expected,
            f"{what}: the artifact carries {found!r}, the recomputation has {expected!r}",
        )


# ── naming and paths (§1) ──────────────────────────────────────────────


def artifact_stem(pass_name: str) -> str:
    """The file stem one sitting's artifacts carry: ``sa5-live-1-effects`` (§1)."""
    if not pass_name.startswith(_PASS_PREFIX):
        raise Sa5VerificationError(
            f"{pass_name!r} does not name a mixer-enabled sitting ('{_PASS_PREFIX}...'), so "
            "no SA5 effect artifact stem can be derived for it"
        )
    return f"sa5-{pass_name[len(_PASS_PREFIX) :]}-effects"


def artifact_paths(directory: Path, stem: str) -> Mapping[str, Path]:
    """The four published files of one stem: NPZ, CSV, JSON and README (§1)."""
    paths = {
        kind: Path(directory) / f"{stem}{extension}"
        for kind, extension in _ARTIFACT_EXTENSIONS.items()
    }
    paths["readme"] = Path(directory) / f"{stem}.README.md"
    return paths


def artifact_dir_of(pass_ref: PassRef) -> Path:
    """The publish root a sitting's four files live under: ``reports/sparse-signal/`` (§1).

    §1 puts both products under the plan's publish root ``reports/sparse-signal/``, which
    sits beside the per-pass report directories (``reports/sparse-mixer-live-1`` and so on),
    so the root is derived from the ref's own ``report_dir`` rather than guessed from a
    working directory. A caller that keeps the files elsewhere passes ``artifact_dir``
    explicitly and this derivation is not consulted.
    """
    if pass_ref.report_dir is None:
        raise Sa5VerificationError(
            f"{pass_ref.name}: this pass has no report directory, so neither its own "
            "reports nor the SA5 publish root beside them can be located"
        )
    return Path(pass_ref.report_dir).parent / "sparse-signal"


def effect_id_of(
    view: SparseView | str, metric: MetricName | str, contrast: str
) -> str:
    """The deterministic effect id: ``<view>__<metric>__<contrast>`` (§2)."""
    return f"{SparseView(view).value}__{MetricName(metric).value}__{contrast}"


# ── the recomputation seam (§11.1–§11.2) ───────────────────────────────


def recompute_sa5_sources(
    pass_ref: PassRef,
    *,
    root: Path,
    plan_path: Path,
    directory: Path,
    low_hz: float = DEFAULT_LOW_HZ,
    max_lag_s: float | None = None,
) -> Sa5Sources:
    """Re-derive one sitting's binding and effects from its own committed sources.

    The three steps §11 fixes, in order: decode the sitting's recordings
    (:func:`~udv_echo_process.analysis._sparse_pass.decode_pass`), read the sitting's own
    committed ``points.csv`` and bind it (:func:`bind_sitting`), then measure the effects
    and summaries with the frozen slices (:func:`measure_binding`). Nothing here reads an
    artifact: the numbers this returns are the verifier's own.

    Raises:
        SparseIngestError: for any condition the loader, the binding or the engine refuses,
            and therefore for a sitting that cannot be verified independently.
    """
    decoded = decode_pass(root, plan_path=plan_path, plan_name=pass_ref.name)
    rows = _inventory_rows(Path(directory) / "points.csv")
    binding = bind_sitting(rows, plan_name=pass_ref.name, support_mm=decoded.support_mm)
    effects = measure_binding(
        binding,
        decoded.points,
        pass_name=pass_ref.name,
        low_hz=low_hz,
        max_lag_s=max_lag_s,
    )
    return Sa5Sources(decoding=decoded, binding=binding, effects=effects)


def _inventory_rows(path: Path) -> tuple[dict[str, str], ...]:
    """The committed per-pass inventory rows, or a refusal naming the file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise Sa5VerificationError(
            f"cannot read the sitting's committed per-pass inventory {path}: {exc}. A "
            "verification binds the artifact to the inventory the sitting committed, so "
            "this file is required"
        ) from exc
    return tuple(csv.DictReader(text.splitlines()))


# ── the entry point ────────────────────────────────────────────────────


def verify_sa5_artifacts(
    pass_ref: PassRef,
    *,
    artifact_dir: Path | None = None,
    stem: str | None = None,
    dataset_root: Path | None = None,
    plan_path: Path | None = None,
    low_hz: float = DEFAULT_LOW_HZ,
    max_lag_s: float | None = None,
) -> Sa5Verification:
    """Verify one sitting's published SA5 artifacts against a fresh recomputation.

    Args:
        pass_ref: **one** committed pass, which must be a reproducibility sitting. The
            Stage-2 campaign, a sitting-shaped dataset with no published effects and any
            pass that is not a mixer-enabled sitting are refused before a file is read.
        artifact_dir: where the four files live, or the ref's own ``report_dir``.
        stem: the artifact stem, or the one the pass name derives (``sa5-live-1-effects``).
        dataset_root: the dataset root, or the ref's own.
        plan_path: the run-plan file, or the ref's own.
        low_hz: the Φ band edge, as the recomputation's slice reads it.
        max_lag_s: the declared recurrence lag domain, as the recomputation's slice reads it.

    Returns:
        :class:`Sa5Verification` — the checks that held, the digests read and the counts of
        the compared rows.

    Raises:
        Sa5VerificationError: for a pass that is not one reproducibility sitting, a missing
            or unreadable artifact file, a recomputation that refuses, or any disagreement
            between the artifacts and the recomputation. All disagreements are listed.
    """
    _require_one_sitting(pass_ref)
    expected_stem = artifact_stem(pass_ref.name)
    if stem is not None and stem != expected_stem:
        raise Sa5VerificationError(
            f"{pass_ref.name}: the artifact stem {stem!r} is not this sitting's "
            f"{expected_stem!r}; one invocation verifies one sitting's own files"
        )
    directory = (
        Path(artifact_dir) if artifact_dir is not None else artifact_dir_of(pass_ref)
    )
    if pass_ref.report_dir is None:
        raise Sa5VerificationError(
            f"{pass_ref.name}: the committed per-pass inventory directory is missing"
        )
    paths = artifact_paths(directory, expected_stem)
    for kind, path in paths.items():
        if not path.is_file():
            raise Sa5VerificationError(
                f"{pass_ref.name}: the published {kind} file {path} is missing; a "
                "verification compares all four files, and an absent one is a refusal"
            )

    root = Path(dataset_root) if dataset_root is not None else Path(pass_ref.root)
    plan = Path(plan_path) if plan_path is not None else Path(pass_ref.plan_path)
    try:
        sources = recompute_sa5_sources(
            pass_ref,
            root=root,
            plan_path=plan,
            directory=Path(pass_ref.report_dir),
            low_hz=low_hz,
            max_lag_s=max_lag_s,
        )
    except (SparseIngestError, ValueError) as exc:
        raise Sa5VerificationError(
            f"{pass_ref.name}: the sitting cannot be recomputed from its committed "
            f"sources, so there is no independent number to verify against: {exc}"
        ) from exc

    failures = _Failures(pass_ref.name)
    _reconcile_operands(failures, sources)
    try:
        expected = _expected_effects(failures, sources)
    except Sa5VerificationError:
        raise
    except (ValueError, TypeError) as exc:
        raise Sa5VerificationError(
            f"{pass_ref.name}: the recomputation is not itself a §3 effect artifact, so "
            f"there is nothing to compare the published files against: {exc}"
        ) from exc

    raw_npz, records = _decode_container(failures, paths["npz"], expected.shapes)
    if records is not None:
        _compare_arrays(failures, expected, records)

    _, csv_rows = _read_csv_text(failures, paths["csv"])
    _, document = _read_json(failures, paths["json"])

    _compare_csv(failures, expected, pass_ref.name, csv_rows)
    if document is not None:
        _compare_json(
            failures,
            expected,
            sources,
            document,
            expected_stem=expected_stem,
        )
        _verify_digests(
            failures,
            document=document,
            raw_npz=raw_npz,
            paths=paths,
            expected_stem=expected_stem,
        )

    if failures.items:
        listed = "\n".join(f"  - {item}" for item in failures.items)
        raise Sa5VerificationError(
            f"{pass_ref.name}: the published artifacts disagree with the independent "
            f"recomputation in {len(failures.items)} place(s):\n{listed}"
        )
    assert document is not None and raw_npz is not None  # narrowed by the walks above
    return Sa5Verification(
        sitting=pass_ref.name,
        plan=sources.binding.plan,
        artifact_dir=directory,
        stem=expected_stem,
        effect_count=len(expected.records),
        csv_rows=len(csv_rows),
        checks={
            "operands_bound_to_decoded_sources": True,
            "npz_arrays_match_the_recomputed_profiles": True,
            "csv_scalars_match_the_recomputed_summaries": True,
            "json_structure_and_provenance_match_the_recomputation": True,
            "nonvalue_rows_are_the_recomputed_missing_positions": True,
            "digests_match_the_staged_bytes": True,
        },
        digests={
            "npz": f"{DIGEST_PREFIX}{_sha256(raw_npz)}",
            "csv": table_digest(paths["csv"]),
            "json": table_digest(paths["json"]),
        },
    )


def _require_one_sitting(pass_ref: PassRef) -> None:
    """Refuse anything but exactly one mixer-enabled reproducibility sitting (§1, §9)."""
    if pass_ref.name == "stage2-e20-e64" or pass_ref.role is not PassRole.SITTING:
        raise Sa5VerificationError(
            f"{pass_ref.name!r} is not a sitting: the Stage-2 campaign is contextual, is "
            "not a third sitting and is not reached by the SA5 effect schema. One "
            "invocation verifies one sitting, and no cross-sitting number exists"
        )
    if not pass_ref.is_reproducibility_sitting:
        raise Sa5VerificationError(
            f"{pass_ref.name!r} is not one of the mixer-enabled reproducibility sittings, "
            "so it publishes no SA5 effect artifact to verify"
        )


# ── the expected effects (§2, §3, §5.3, §6) ────────────────────────────


def _reconcile_operands(failures: _Failures, sources: Sa5Sources) -> None:
    """§11.1: every bound operand row against the decoded recording it names.

    An inventory row is not evidence until it is reconciled with the file it names, so the
    artifact's own provenance is never the source of truth here: each row's digest, path,
    job, acquisition order, achieved settings and stored grid are compared with the decoded
    recording. The engine refuses such a mismatch before it measures anything, but the
    verifier states the disagreement itself rather than inheriting it, so a verification
    failure names the operand and the cell.
    """
    binding, decoding = sources.binding, sources.decoding
    # The plan identity the inventory stamps on every row is a claim about *which* run the
    # recordings belong to, so it is reconciled with the plan the recordings were decoded from.
    # The artifact's own plan_fingerprint is compared with the binding elsewhere; without this
    # an inventory whose plan_fingerprint field was edited would agree with a matching JSON.
    decoded_fingerprint = getattr(decoding, "plan_fingerprint", None)
    if decoded_fingerprint is None:
        failures.require(
            False,
            "the decoded pass carries no plan fingerprint, so the committed inventory's plan "
            "identity cannot be reconciled with the plan the recordings were decoded from",
        )
    else:
        failures.require(
            str(binding.plan_fingerprint) == str(decoded_fingerprint),
            f"the committed inventory's plan fingerprint {binding.plan_fingerprint!r} is not "
            f"the decoded run plan's {str(decoded_fingerprint)!r}: points.csv is not evidence "
            f"until its plan identity reconciles with the plan it names",
        )
    by_label: dict[str, list[object]] = {}
    for point in decoding.points:
        label = str(point.binding.point.label)  # type: ignore[attr-defined]
        by_label.setdefault(label, []).append(point)
    for row in binding.operands:
        matches = by_label.get(row.label, [])
        if len(matches) != 1:
            failures.require(
                False,
                f"operand {row.label!r}: the decoded sitting holds {len(matches)} "
                "recording(s) with that label; an operand needs exactly one",
            )
            continue
        point = matches[0]
        config = point.config  # type: ignore[attr-defined]
        depths = np.asarray(point.depths, dtype=float)  # type: ignore[attr-defined]
        time_s = np.asarray(point.time_s, dtype=float)  # type: ignore[attr-defined]
        failures.equal(
            f"operand {row.label!r} source_sha256",
            str(point.source_sha256),  # type: ignore[attr-defined]
            row.source_sha256,
        )
        failures.equal(
            f"operand {row.label!r} relative_path",
            str(point.relative_path),  # type: ignore[attr-defined]
            row.relative_path,
        )
        failures.equal(
            f"operand {row.label!r} job",
            str(point.binding.job.job),  # type: ignore[attr-defined]
            row.job,
        )
        failures.equal(
            f"operand {row.label!r} acquisition order",
            int(point.binding.order),  # type: ignore[attr-defined]
            row.order,
        )
        failures.equal(
            f"operand {row.label!r} burst_length",
            int(config.burst_length or 0),
            row.burst_length,
        )
        failures.equal(
            f"operand {row.label!r} emissions_per_profile",
            int(config.emissions_per_profile or 0),
            row.emissions_per_profile,
        )
        prf_us = 1e6 / float(config.pulse_repetition_freq_hz)
        failures.require(
            abs(prf_us - row.prf_us) <= GRID_RTOL * abs(row.prf_us),
            f"operand {row.label!r} prf_us: the decoded recording is {prf_us!r} us, the "
            f"inventory binds {row.prf_us!r} us",
        )
        failures.equal(f"operand {row.label!r} gates", int(depths.size), row.gates)
        failures.require(
            abs(float(depths[0]) - row.first_gate_mm) <= GATE_TOLERANCE_MM
            and abs(float(depths[-1]) - row.last_gate_mm) <= GATE_TOLERANCE_MM,
            f"operand {row.label!r} grid: the decoded recording spans "
            f"[{float(depths[0]):g}, {float(depths[-1]):g}] mm, the inventory binds "
            f"[{row.first_gate_mm:g}, {row.last_gate_mm:g}] mm",
        )
        resolution = float(config.resolution_mm or 0.0)
        failures.require(
            abs(resolution - row.resolution_mm) <= GRID_RTOL * abs(row.resolution_mm),
            f"operand {row.label!r} resolution_mm: the decoded recording is {resolution!r} "
            f"mm, the inventory binds {row.resolution_mm!r} mm",
        )
        span = float(time_s[-1] - time_s[0]) if time_s.size >= 1 else 0.0
        failures.require(
            time_s.size >= 2 and span + TOLERANCE_S >= row.window_s,
            f"operand {row.label!r} window: the decoded recording stores a "
            f"{span!r} s span, shorter than the declared {row.window_s!r} s primary window",
        )


def _expected_effects(failures: _Failures, sources: Sa5Sources) -> _ExpectedEffects:
    """Every effect the artifacts must carry, recomputed from the binding and the engine."""
    binding = sources.binding
    effects = sources.effects
    corner_labels = {row.label for row in binding.corners}

    records: list[_ExpectedEffect] = []
    for metric, view in ENDPOINTS:
        endpoint = effects.endpoint(metric, view)
        for name in (*[spec.name for spec in binding.contrasts], INTERACTION_NAME):
            if name == INTERACTION_NAME:
                effect = endpoint.interaction
                sides = tuple(recording(row.label) for row in binding.corners)
                uses_corners = True
            else:
                spec = next(item for item in binding.contrasts if item.name == name)
                effect = next(item for item in endpoint.contrasts if item.name == name)
                sides = (spec.high, spec.low)
                uses_corners = (
                    set(spec.high.members) | set(spec.low.members) <= corner_labels
                )
            records.append(
                _expected_effect(
                    failures,
                    binding=binding,
                    effect=effect,
                    sides=sides,
                    view=view,
                    metric=metric,
                    grid=CORNER_GRID if uses_corners else EMISSIONS_GRID,
                )
            )

    by_id: dict[str, _ExpectedEffect] = {}
    for record in records:
        if record.effect_id in by_id:
            raise Sa5VerificationError(
                f"the recomputation produced the effect id {record.effect_id!r} twice; the "
                "72 ids are unique by construction and this would make the schema ambiguous"
            )
        by_id[record.effect_id] = record
    members = tuple(
        sorted(
            member_name(record.effect_id, suffix)
            for record in records
            for suffix in MEMBER_SUFFIXES
        )
    )
    return _ExpectedEffects(
        records=tuple(records),
        by_id=by_id,
        members=members,
        shapes={
            record.effect_id: EffectShape(
                record.arrays.knot_count, record.arrays.participant_count
            )
            for record in records
        },
    )


def _participant_labels(sides: Sequence[Operand]) -> tuple[str, ...]:
    """The fixed participant order: the high side's members, then the low side's (§3.1)."""
    labels: list[str] = []
    for side in sides:
        for label in side.members:
            if label not in labels:
                labels.append(label)
    return tuple(labels)


def _expected_effect(
    failures: _Failures,
    *,
    binding: SittingBinding,
    effect: DepthEffects,
    sides: Sequence[Operand],
    view: SparseView,
    metric: MetricName,
    grid: str,
) -> _ExpectedEffect:
    """One effect's expected arrays, its §5.3 record and its §6 CSV cells."""
    effect_id = effect_id_of(view, metric, effect.name)
    labels = _participant_labels(sides)
    knot_count = len(effect.knots_mm)
    participant_count = len(labels)

    # The participant order the binding fixes is checked against the engine's own reads: a
    # row order the writer could have inferred from member names is never accepted.
    observed: tuple[str, ...] = ()
    for row in effect.effects[:1]:
        seen: list[str] = []
        for side in row.operands:
            for member in side.members:
                if member.label not in seen:
                    seen.append(member.label)
        observed = tuple(seen)
    failures.require(
        observed == labels,
        f"{effect_id}: the recomputed participant order {observed} is not the binding's "
        f"declared order {labels}",
    )

    knots = np.asarray([float(depth) for depth in effect.knots_mm], dtype=float)
    values = np.asarray(
        [0.0 if row.value is None else float(row.value) for row in effect.effects],
        dtype=float,
    )
    defined = np.asarray(
        [1 if row.defined else 0 for row in effect.effects], dtype=np.uint8
    )
    state = np.asarray(
        [_effect_code(row.state) for row in effect.effects], dtype=np.uint8
    )
    gate_index = np.full((participant_count, knot_count), -1, dtype=np.int32)
    depth_mm = np.zeros((participant_count, knot_count), dtype=float)
    offset_mm = np.zeros((participant_count, knot_count), dtype=float)
    participant_value = np.zeros((participant_count, knot_count), dtype=float)
    participant_defined = np.zeros((participant_count, knot_count), dtype=np.uint8)
    participant_state = np.zeros((participant_count, knot_count), dtype=np.uint8)
    for index, row in enumerate(effect.effects):
        reads = {
            member.label: member for side in row.operands for member in side.members
        }
        for position, label in enumerate(labels):
            read = reads[label]
            participant_state[position, index] = (
                UNALIGNED_READ_CODE
                if not read.aligned
                else _participant_code(read.state)
            )
            if read.gate_index is not None:
                gate_index[position, index] = int(read.gate_index)
            if read.depth_mm is not None:
                depth_mm[position, index] = float(read.depth_mm)
            if read.offset_mm is not None:
                offset_mm[position, index] = float(read.offset_mm)
            if read.defined:
                participant_defined[position, index] = 1
                participant_value[position, index] = float(read.value)  # type: ignore[arg-type]

    arrays = EffectArrays(
        effect_id=effect_id,
        knot_count=knot_count,
        participant_count=participant_count,
        knots_mm=np.ascontiguousarray(knots, dtype=MEMBER_DTYPES["knots_mm"]),
        effect=np.ascontiguousarray(values, dtype=MEMBER_DTYPES["effect"]),
        defined=np.ascontiguousarray(defined, dtype=MEMBER_DTYPES["defined"]),
        state=np.ascontiguousarray(state, dtype=MEMBER_DTYPES["state"]),
        participant_gate_index=np.ascontiguousarray(
            gate_index, dtype=MEMBER_DTYPES["participant_gate_index"]
        ),
        participant_depth_mm=np.ascontiguousarray(
            depth_mm, dtype=MEMBER_DTYPES["participant_depth_mm"]
        ),
        participant_offset_mm=np.ascontiguousarray(
            offset_mm, dtype=MEMBER_DTYPES["participant_offset_mm"]
        ),
        participant_value=np.ascontiguousarray(
            participant_value, dtype=MEMBER_DTYPES["participant_value"]
        ),
        participant_defined=np.ascontiguousarray(
            participant_defined, dtype=MEMBER_DTYPES["participant_defined"]
        ),
        participant_state=np.ascontiguousarray(
            participant_state, dtype=MEMBER_DTYPES["participant_state"]
        ),
    )

    participants = tuple(
        {
            "label": label,
            "job": binding.by_label(label).job,
            "order": binding.by_label(label).order,
            "kind": "recording",
        }
        for label in labels
    )
    record: dict[str, object] = {
        "effect_id": effect_id,
        "view": SparseView(view).value,
        "metric": MetricName(metric).value,
        "contrast": effect.name,
        "expression": effect.expression,
        "reduction": effect.reduction,
        "units": effect.units,
        "grid": grid,
        "knot_count": knot_count,
        "participant_count": participant_count,
        "operand_names": [side.name for side in sides],
        "operands": [
            {"name": side.name, "kind": side.kind, "members": list(side.members)}
            for side in sides
        ],
        "coefficients": list(effect.coefficients),
        "participants": list(participants),
        "support_mm": list(effect.support_mm),
        "half_pitch_mm": effect.half_pitch_mm,
        "alignment_rule": effect.alignment_rule,
    }
    summary = effect.summary
    shape = effect.shape
    csv: dict[str, object] = {
        "sitting": binding.plan,
        "effect_id": effect_id,
        "view": SparseView(view).value,
        "metric": MetricName(metric).value,
        "contrast": effect.name,
        "units": effect.units,
        "grid": grid,
        "knot_count": knot_count,
        "defined_count": summary.defined_count,
        "undefined_count": summary.undefined_count,
        "undefined_alignment_count": int(np.count_nonzero(state == 2)),
        "undefined_operand_count": int(np.count_nonzero(state == 1)),
        "covered_depth_mm": summary.covered_depth_mm,
        "coverage_fraction": summary.coverage_fraction,
        "support_low_mm": effect.support_mm[0],
        "support_high_mm": effect.support_mm[1],
        "half_pitch_mm": effect.half_pitch_mm,
        "max_abs_offset_mm": effect.max_abs_offset_mm,
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
        "correlation": shape.correlation,
        "correlation_defined_count": shape.defined_count,
    }
    return _ExpectedEffect(
        effect_id=effect_id,
        grid=grid,
        view=SparseView(view).value,
        metric=MetricName(metric).value,
        contrast=effect.name,
        record=record,
        csv=csv,
        arrays=arrays,
        effect=effect,
    )


def _effect_code(state: EffectState) -> int:
    """The §8 table A code of one backend effect state, or a refusal naming the drift."""
    try:
        return _EFFECT_CODE_BY_TEXT[EffectState(state).value]
    except KeyError as exc:
        raise Sa5VerificationError(
            f"the backend carried the effect state {state!r}, which is outside the schema's "
            "closed table A vocabulary"
        ) from exc


def _participant_code(state: MetricState | None) -> int:
    """The §8 table B code of one aligned read's state, or a refusal naming the drift."""
    if state is None:
        raise Sa5VerificationError(
            "an aligned read carries the metric slice's own gate state; a read with none "
            "is the unaligned sentinel and must be coded as one"
        )
    try:
        return _PARTICIPANT_CODE_BY_TEXT[MetricState(state).value]
    except KeyError as exc:
        raise Sa5VerificationError(
            f"the backend carried the metric state {state!r}, which is outside the schema's "
            "closed table B vocabulary"
        ) from exc


# ── the NPZ layer (§3, §4, §11.3) ──────────────────────────────────────


def _decode_container(
    failures: _Failures, path: Path, shapes: Mapping[str, EffectShape]
) -> tuple[bytes | None, tuple[EffectArrays, ...] | None]:
    """Read the container through the shared codec, or record its refusal."""
    raw = Path(path).read_bytes()
    if not raw:
        failures.require(False, f"{path.name}: the container carries no byte")
        return None, None
    try:
        records = decode_effect_npz(raw, expected=dict(shapes))
    except (NpzContainerError, NpzSchemaError) as exc:
        failures.require(
            False,
            f"{path.name} is not a canonical §3/§4 effects container: {exc}",
        )
        return raw, None
    return raw, records


def _compare_arrays(
    failures: _Failures,
    expected: _ExpectedEffects,
    records: tuple[EffectArrays, ...],
) -> None:
    """Every decoded array against the recomputed profile, member by member."""
    found = {record.effect_id for record in records}
    missing = sorted(set(expected.by_id) - found)
    extra = sorted(found - set(expected.by_id))
    failures.require(
        not missing,
        f"the container carries no member for the effect(s) {missing} the recomputation "
        "produced",
    )
    failures.require(
        not extra,
        f"the container carries the effect(s) {extra} the recomputation never produced",
    )
    for record in records:
        want = expected.by_id.get(record.effect_id)
        if want is None:
            continue
        for suffix in MEMBER_SUFFIXES:
            mine = getattr(record, suffix)
            theirs = getattr(want.arrays, suffix)
            if mine.dtype != theirs.dtype:
                failures.require(
                    False,
                    f"{member_name(record.effect_id, suffix)}: the container declares "
                    f"{mine.dtype.str}, the recomputation's member is {theirs.dtype.str}",
                )
                continue
            if mine.shape != theirs.shape:
                failures.require(
                    False,
                    f"{member_name(record.effect_id, suffix)}: the container has shape "
                    f"{mine.shape}, the recomputation has {theirs.shape}",
                )
                continue
            differing = _difference(mine, theirs)
            failures.require(
                differing is None,
                f"{member_name(record.effect_id, suffix)}: {differing}",
            )
        failures.require(
            (record.knot_count, record.participant_count)
            == (want.arrays.knot_count, want.arrays.participant_count),
            f"{record.effect_id}: the container's K/P "
            f"({record.knot_count}, {record.participant_count}) is not the recomputation's "
            f"({want.arrays.knot_count}, {want.arrays.participant_count})",
        )


def _difference(found: np.ndarray, expected: np.ndarray) -> str | None:
    """A sentence describing the first positional difference, or ``None`` when equal."""
    equal = found == expected
    if bool(np.all(equal)):
        return None
    flat = np.argwhere(~equal)
    position = tuple(int(value) for value in flat[0])
    count = int(flat.shape[0])
    return (
        f"{count} of {found.size} position(s) differ from the recomputed array; the first "
        f"is at {position}: the container carries {found[position].item()!r}, the "
        f"recomputation has {expected[position].item()!r}"
    )


# ── the CSV layer (§6, §11.3) ──────────────────────────────────────────


def _read_csv_text(
    failures: _Failures, path: Path
) -> tuple[bytes | None, list[dict[str, str]]]:
    """The CSV's canonical text and its parsed rows, or a recorded refusal."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # §6 fixes the CSV as UTF-8 text. A lossy ``errors="replace"`` decode would turn a
        # malformed byte sequence into U+FFFD cells that a reader could mistake for data, so
        # the bytes are read strictly and a non-UTF-8 file is refused by name.
        failures.require(
            False,
            f"{path.name} is not valid UTF-8 ({exc}); §6 fixes the CSV as UTF-8, so a byte "
            f"sequence that does not decode is a refused artifact, not a cell repaired to "
            f"U+FFFD",
        )
        return raw, []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        failures.require(False, f"{path.name}: the CSV carries no header row")
        return raw, []
    header = tuple(rows[0])
    if header != CSV_COLUMNS:
        failures.require(
            False,
            f"{path.name}: the header is not the closed §6 column set in order; the file "
            f"has {list(header)}",
        )
        return raw, []
    parsed: list[dict[str, str]] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(CSV_COLUMNS):
            failures.require(
                False,
                f"{path.name} row {number}: {len(row)} cell(s) for the "
                f"{len(CSV_COLUMNS)} closed columns",
            )
            continue
        parsed.append(dict(zip(CSV_COLUMNS, row, strict=True)))
    if not parsed:
        failures.require(False, f"{path.name}: the CSV carries no data row")
    return raw, parsed


def _compare_csv(
    failures: _Failures,
    expected: _ExpectedEffects,
    sitting: str,
    rows: list[dict[str, str]],
) -> None:
    """Every CSV cell against the recomputed summary, in the fixed effect order (§2)."""
    if not rows:
        return
    wanted = [record.effect_id for record in expected.records]
    found = [row["effect_id"] for row in rows]
    if found != wanted:
        first = next(
            (
                index
                for index, (left, right) in enumerate(zip(found, wanted, strict=False))
                if left != right
            ),
            min(len(found), len(wanted)),
        )
        failures.require(
            False,
            f"the CSV's effect rows are not the §2 effect order: row {first + 1} carries "
            f"{found[first] if first < len(found) else '<absent>'!r} where the "
            f"recomputation has {wanted[first] if first < len(wanted) else '<absent>'!r} "
            f"({len(found)} row(s) for {len(wanted)} effect(s))",
        )
        return
    for row in rows:
        want = expected.by_id[row["effect_id"]]
        for column in CSV_COLUMNS:
            text = row[column]
            cell = want.csv[column]
            if column == "sitting":
                failures.equal(f"{want.effect_id} CSV {column}", text, sitting)
                continue
            if column in CSV_TEXT_COLUMNS:
                failures.equal(f"{want.effect_id} CSV {column}", text, cell)
                continue
            if text == "":
                failures.equal(f"{want.effect_id} CSV {column}", None, cell)
                continue
            try:
                number: float | None = float(text)
            except ValueError:
                failures.require(
                    False,
                    f"{want.effect_id} CSV {column}: {text!r} is not a number and not the "
                    "empty field",
                )
                continue
            failures.equal(f"{want.effect_id} CSV {column}", number, cell)
        failures.equal(
            f"{want.effect_id} CSV knot_count",
            _integer_or_none(row["knot_count"]),
            want.csv["knot_count"],
        )
        failures.equal(
            f"{want.effect_id} CSV undefined_alignment_count",
            _integer_or_none(row["undefined_alignment_count"]),
            want.csv["undefined_alignment_count"],
        )
        failures.equal(
            f"{want.effect_id} CSV undefined_operand_count",
            _integer_or_none(row["undefined_operand_count"]),
            want.csv["undefined_operand_count"],
        )
        failures.equal(
            f"{want.effect_id} CSV correlation_defined_count",
            _integer_or_none(row["correlation_defined_count"]),
            want.csv["correlation_defined_count"],
        )


def _integer_or_none(text: str) -> float | int | None:
    """An integer cell as an int, or its text when it is not one."""
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return text


# ── the JSON layer (§5, §11.3–§11.4) ───────────────────────────────────


def _read_json(failures: _Failures, path: Path) -> tuple[bytes | None, object | None]:
    """The JSON's exact bytes and its parsed document, or a recorded refusal."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        failures.require(False, f"{path.name} is not UTF-8: {exc}")
        return raw, None
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        failures.require(False, f"{path.name} is not strict JSON: {exc}")
        return raw, None
    try:
        canonical = _canonical_json(document)
    except ValueError as exc:
        # json.loads accepts the bare ``NaN``/``Infinity`` tokens (and a literal such as
        # ``1e400`` that overflows binary64), while §5 fixes allow_nan=False: the document is
        # not a §5 artifact. This is caught here so the refusal is typed rather than a bare
        # ValueError escaping the verifier.
        failures.require(
            False,
            f"{path.name} carries a non-finite number — the JSON ``NaN``/``Infinity`` token or "
            f"a literal that overflows binary64 — and §5 fixes strict JSON with "
            f"allow_nan=False, so a non-finite value fails the run: {exc}",
        )
        return raw, None
    failures.require(
        raw == canonical.encode("utf-8"),
        f"{path.name}: the bytes are not the §5 canonical strict JSON (UTF-8, "
        "ensure_ascii=True, sort_keys=True, ','/':' separators, LF endings and one "
        "trailing newline): re-serializing the document does not reproduce the file",
    )
    return raw, document


def _canonical_json(document: object) -> str:
    """The §5 canonical text: sorted keys, ASCII, tight separators, one LF."""
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def _compare_json(
    failures: _Failures,
    expected: _ExpectedEffects,
    sources: Sa5Sources,
    document: object,
    *,
    expected_stem: str,
) -> None:
    """The JSON structure, provenance, non-value rows and repeats (§5, §11)."""
    if not isinstance(document, dict):
        failures.require(False, "the JSON document is not an object")
        return
    if sorted(document) != sorted(JSON_KEYS):
        missing = sorted(set(JSON_KEYS) - set(document))
        extra = sorted(set(document) - set(JSON_KEYS))
        failures.require(
            False,
            f"the JSON's field set is closed: it is missing {missing} and carries the "
            f"unexpected {extra}",
        )
    failures.equal("JSON schema", document.get("schema"), SCHEMA)

    binding = sources.binding
    effects = sources.effects
    failures.equal("JSON sitting", document.get("sitting"), binding.plan)
    failures.equal("JSON plan", document.get("plan"), binding.plan)
    failures.equal(
        "JSON plan_fingerprint",
        document.get("plan_fingerprint"),
        binding.plan_fingerprint,
    )
    failures.equal("JSON window_s", document.get("window_s"), binding.window_s)
    failures.equal(
        "JSON window_revolutions",
        document.get("window_revolutions"),
        binding.window_revolutions,
    )
    failures.equal(
        "JSON support_mm", document.get("support_mm"), list(binding.support_mm)
    )
    failures.equal("JSON method", document.get("method"), METHOD)
    failures.equal(
        "JSON contrast_source", document.get("contrast_source"), CONTRAST_SOURCE
    )
    failures.equal(
        "JSON control_labels",
        document.get("control_labels"),
        list(binding.control_labels),
    )
    for key in ("analysis_commit", "generator_revision", "generator_command"):
        failures.require(
            isinstance(document.get(key), str) and bool(document.get(key)),
            f"JSON {key}: a non-empty string names the revision that produced the files, "
            f"got {document.get(key)!r}",
        )
    # The regeneration command is deterministic, so it is not enough for it to be some
    # non-empty string: it must name the sitting it regenerates. A command for another sitting
    # (or one that names none) does not reproduce these bytes, and the sitting is the one piece
    # of the command the verifier knows independently of the writer.
    command = document.get("generator_command")
    if isinstance(command, str) and command:
        failures.require(
            "\n" not in command and command == command.strip(),
            f"JSON generator_command: one deterministic command line, got {command!r}",
        )
        failures.require(
            binding.plan in command,
            f"JSON generator_command: the command must name the sitting it regenerates "
            f"({binding.plan!r}); it does not reproduce these files otherwise, got {command!r}",
        )

    _compare_checks(failures, document, effects)
    _compare_provenance(failures, document, binding)
    _compare_effects(failures, document, expected)
    _compare_members(failures, document, expected)
    _compare_nonvalue_rows(failures, document, expected)
    _compare_repeats(failures, document, effects)
    _compare_artifacts(failures, document, expected_stem)


def _compare_checks(
    failures: _Failures, document: Mapping[str, object], effects: SittingEffects
) -> None:
    """The engine's own checks and the artifact checks (§5.1)."""
    checks = document.get("checks")
    if isinstance(checks, dict):
        failures.equal("JSON checks key set", sorted(checks), sorted(ENGINE_CHECKS))
        for name in ENGINE_CHECKS:
            if name in checks:
                failures.equal(f"JSON checks[{name!r}]", checks[name], True)
    else:
        failures.require(False, f"JSON checks: an object of verdicts, got {checks!r}")
    recomputed = {
        name: effects.checks.get(name)
        for name in ENGINE_CHECKS
        if name in effects.checks
    }
    for name, value in sorted(recomputed.items()):
        if isinstance(checks, dict) and name in checks:
            failures.equal(f"JSON checks[{name!r}]", checks[name], bool(value))
    artifact_checks = document.get("artifact_checks")
    if isinstance(artifact_checks, dict):
        failures.equal(
            "JSON artifact_checks key set",
            sorted(artifact_checks),
            sorted(ARTIFACT_CHECKS),
        )
        for name in ARTIFACT_CHECKS:
            if name in artifact_checks:
                failures.equal(
                    f"JSON artifact_checks[{name!r}]", artifact_checks[name], True
                )
    else:
        failures.require(
            False,
            f"JSON artifact_checks: an object of verdicts, got {artifact_checks!r}",
        )
    ok = document.get("ok")
    failures.require(isinstance(ok, bool), f"JSON ok: a boolean, got {ok!r}")
    if (
        isinstance(ok, bool)
        and isinstance(checks, dict)
        and isinstance(artifact_checks, dict)
    ):
        failures.equal(
            "JSON ok", ok, bool(all(checks.values()) and all(artifact_checks.values()))
        )


def _compare_provenance(
    failures: _Failures, document: Mapping[str, object], binding: SittingBinding
) -> None:
    """The eleven bound operand rows, reconciled row by row (§5.2, §11.1)."""
    provenance = document.get("provenance")
    if not isinstance(provenance, list):
        failures.require(False, f"JSON provenance: a list of rows, got {provenance!r}")
        return
    expected = [
        {key: getattr(row, key) for key in PROVENANCE_KEYS} for row in binding.operands
    ]
    labels = [row["label"] for row in expected]
    found = [row.get("label") if isinstance(row, dict) else None for row in provenance]
    if found != labels:
        failures.require(
            False,
            f"JSON provenance: the {len(found)} row(s) {found} are not the eleven bound "
            f"operands {labels} in contract order",
        )
        return
    for row in provenance:
        assert isinstance(row, dict)
        label = row["label"]
        if sorted(row) != sorted(PROVENANCE_KEYS):
            failures.require(
                False,
                f"JSON provenance[{label!r}]: its field set is closed; the file carries "
                f"{sorted(set(row) - set(PROVENANCE_KEYS))} unexpectedly and is missing "
                f"{sorted(set(PROVENANCE_KEYS) - set(row))}",
            )
            continue
        want = expected[labels.index(label)]
        for key in PROVENANCE_KEYS:
            failures.equal(f"JSON provenance[{label!r}].{key}", row.get(key), want[key])


def _compare_effects(
    failures: _Failures, document: Mapping[str, object], expected: _ExpectedEffects
) -> None:
    """The 72 effect records: order, closed fields and the mirrored structure (§5.3)."""
    effects = document.get("effects")
    if not isinstance(effects, list):
        failures.require(False, f"JSON effects: a list of records, got {effects!r}")
        return
    wanted = [record.effect_id for record in expected.records]
    found = [
        record.get("effect_id") if isinstance(record, dict) else None
        for record in effects
    ]
    if found != wanted:
        failures.require(
            False,
            f"JSON effects: the {len(found)} record(s) are not the §2 effect order "
            f"{len(wanted)}; the first disagreement is at position "
            f"{next((index for index, (a, b) in enumerate(zip(found, wanted)) if a != b), min(len(found), len(wanted)))}",
        )
        return
    for record in effects:
        assert isinstance(record, dict)
        want = expected.by_id[record["effect_id"]]
        if sorted(record) != sorted(EFFECT_KEYS):
            failures.require(
                False,
                f"JSON effects[{record['effect_id']!r}]: its field set is closed; it "
                f"carries {sorted(set(record) - set(EFFECT_KEYS))} unexpectedly and is "
                f"missing {sorted(set(EFFECT_KEYS) - set(record))}",
            )
            continue
        for key, value in want.record.items():
            failures.equal(
                f"JSON effects[{record['effect_id']!r}].{key}", record.get(key), value
            )
        _compare_state_meanings(failures, record)


def _compare_state_meanings(failures: _Failures, record: Mapping[str, object]) -> None:
    """The §8 code spaces, each under its own label, each equal to its own closed table.

    §5.3 fixes the §8 vocabulary and not its exact rendering, so the writer's
    ``{effect: [{code, text}, ...]}`` list and a plain ``{effect: {code: text}}`` mapping are
    both read. What is *not* loose is the code space: the two spaces are not interchangeable
    (codes ``1`` and ``2`` carry different texts), and a content-only scan that merely checked
    that every text appeared somewhere would accept the two tables swapped, or a space whose
    own code was dropped because the other space happens to name the same code — leaving a
    reader unable to resolve an NPZ state code. Each named space is therefore required, and each
    must equal its own table exactly.
    """
    meanings = record.get("state_meanings")
    where = f"JSON effects[{record.get('effect_id')!r}].state_meanings"
    if not isinstance(meanings, Mapping):
        failures.require(
            False, f"{where}: an object naming the two code spaces, got {meanings!r}"
        )
        return
    failures.equal(
        f"{where} spaces", sorted(meanings), [_EFFECT_SPACE, _PARTICIPANT_SPACE]
    )
    for space, table in (
        (_EFFECT_SPACE, EFFECT_STATE_CODES),
        (_PARTICIPANT_SPACE, PARTICIPANT_STATE_CODES),
    ):
        if space not in meanings:
            failures.require(
                False,
                f"{where}: the {space!r} code space is not named, so a reader cannot "
                f"resolve the NPZ's {space} state codes",
            )
            continue
        codes = _space_codes(meanings[space])
        if codes is None:
            failures.require(
                False,
                f"{where}[{space!r}]: a code → text mapping, or a list of code/text rows, "
                f"got {meanings[space]!r}",
            )
            continue
        failures.equal(
            f"{where}[{space!r}]",
            codes,
            {int(code): text for code, text in table.items()},
        )


def _space_codes(node: object) -> dict[int, str] | None:
    """One §8 code space's ``code → text`` mapping, whatever the rendering, or ``None``.

    Accepts the two renderings the schema leaves open — a mapping keyed by the code (a decimal
    string or an int) with text values, and a sequence of ``{code, text}`` rows (or
    ``(code, text)`` pairs). Anything else, or any group that mixes the two, is ``None`` so the
    caller refuses it rather than guessing which space a code belongs to.
    """
    if isinstance(node, Mapping):
        pairs: dict[int, str] = {}
        for key, value in node.items():
            code = _state_code(key)
            if code is None or not isinstance(value, str):
                return None
            pairs[code] = value
        return pairs
    if isinstance(node, Sequence) and not isinstance(node, str | bytes):
        pairs = {}
        for item in node:
            pair = _code_text_pair(item)
            if pair is None:
                return None
            pairs[pair[0]] = pair[1]
        return pairs
    return None


def _code_text_pair(item: object) -> tuple[int, str] | None:
    """One ``{code, text}`` row (or a two-element ``(code, text)`` pair), or ``None``."""
    if isinstance(item, Mapping):
        if sorted(item) != ["code", "text"]:
            return None
        code = _state_code(item.get("code"))
        text = item.get("text")
        if code is None or not isinstance(text, str):
            return None
        return code, text
    if (
        isinstance(item, Sequence)
        and not isinstance(item, str | bytes)
        and len(item) == 2
    ):
        code = _state_code(item[0])
        if code is None or not isinstance(item[1], str):
            return None
        return code, item[1]
    return None


def _state_code(value: object) -> int | None:
    """A state code as an int: an int itself, a bool refused, or a decimal-digit string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _compare_members(
    failures: _Failures, document: Mapping[str, object], expected: _ExpectedEffects
) -> None:
    """``npz_members`` equals the closed member set of §3 exactly (§5.4)."""
    members = document.get("npz_members")
    if not isinstance(members, list):
        failures.require(False, f"JSON npz_members: a list of names, got {members!r}")
        return
    failures.equal("JSON npz_members", members, list(expected.members))
    duplicates = sorted({name for name in members if members.count(name) > 1})
    failures.require(
        not duplicates,
        f"JSON npz_members: the name(s) {duplicates} appear more than once; the member set "
        "is closed and exact",
    )


def _compare_nonvalue_rows(
    failures: _Failures, document: Mapping[str, object], expected: _ExpectedEffects
) -> None:
    """The missing-value rows are exactly the recomputed missing positions (§5.5, §11.3)."""
    rows = document.get("nonvalue_rows")
    if not isinstance(rows, list):
        failures.require(False, f"JSON nonvalue_rows: a list of rows, got {rows!r}")
        return
    wanted = _expected_nonvalue_rows(expected)
    found: dict[tuple[str, str, object, object, object], Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict) or sorted(row) != sorted(NONVALUE_KEYS):
            failures.require(
                False,
                f"JSON nonvalue_rows: every row carries exactly {list(NONVALUE_KEYS)}, "
                f"got {sorted(row) if isinstance(row, dict) else row!r}",
            )
            continue
        if row["kind"] not in NONVALUE_KINDS:
            failures.require(
                False,
                f"JSON nonvalue_rows: the kind {row['kind']!r} is not one of "
                f"{list(NONVALUE_KINDS)}",
            )
            continue
        found[_nonvalue_key(row)] = row
    missing = sorted(wanted.keys() - found.keys())
    extra = sorted(found.keys() - wanted.keys(), key=repr)
    failures.require(
        not missing,
        f"JSON nonvalue_rows: the recomputation has the missing position(s) {missing} the "
        "file does not record",
    )
    failures.require(
        not extra,
        f"JSON nonvalue_rows: the file records the position(s) {extra} that carry a "
        "recomputed value",
    )
    for key, want in wanted.items():
        row = found.get(key)
        if row is None:
            continue
        for field in ("state", "reason"):
            failures.equal(
                f"JSON nonvalue_rows[{key!r}].{field}", row[field], want[field]
            )
        failures.equal(
            f"JSON nonvalue_rows[{key!r}].depth_mm", row["depth_mm"], want["depth_mm"]
        )
        _compare_nonvalue_member(failures, key, want, row)
    _compare_nonvalue_counts(failures, document, wanted)


def _compare_nonvalue_member(
    failures: _Failures,
    key: tuple[str, str, object, object, object],
    want: Mapping[str, object],
    row: Mapping[str, object],
) -> None:
    """``member``: exact where §5.5 fixes it, the offending label or null elsewhere."""
    kind = want["kind"]
    if kind in ("effect-knot", "shape"):
        failures.equal(f"JSON nonvalue_rows[{key!r}].member", row["member"], None)
        failures.equal(f"JSON nonvalue_rows[{key!r}].side", row["side"], None)
        return
    if kind == "read":
        failures.equal(
            f"JSON nonvalue_rows[{key!r}].member", row["member"], want["member"]
        )
        return
    failures.require(
        row["member"] in (want["member"], None),
        f"JSON nonvalue_rows[{key!r}].member: the artifact carries {row['member']!r}, the "
        f"recomputed argument's member is {want['member']!r} or null",
    )


def _nonvalue_key(row: Mapping[str, object]) -> tuple[str, str, object, object, object]:
    """The position a non-value row names, as an order-free key.

    A ``read`` row is one participant's own position, so its ``member`` is part of the key:
    a knot where three of the E20 operand's four recordings are undefined carries three read
    rows, not one. For every other kind the position is the effect's or the operand's own,
    and its ``member`` is not part of the identity (the comparison of that cell stays
    lenient where §5.5 does not fix it).
    """
    member = row["member"] if str(row["kind"]) == "read" else None
    return (
        str(row["effect_id"]),
        str(row["kind"]),
        row["knot_index"],
        row["side"],
        member,
    )


def _expected_nonvalue_rows(
    expected: _ExpectedEffects,
) -> dict[tuple[str, str, object, object, object], dict[str, object]]:
    """Every position whose scalar value is missing, as the recomputation sees it (§5.5)."""
    rows: dict[tuple[str, str, object, object, object], dict[str, object]] = {}
    for record in expected.records:
        effect_id = record.effect_id
        effect = record.effect
        for index, row in enumerate(effect.effects):
            depth = float(effect.knots_mm[index])
            if not row.defined:
                key = (effect_id, "effect-knot", index, None, None)
                rows[key] = {
                    "effect_id": effect_id,
                    "kind": "effect-knot",
                    "knot_index": index,
                    "depth_mm": depth,
                    "side": None,
                    "member": None,
                    "state": EffectState(row.state).value,
                    "reason": row.reason,
                }
            owned: dict[str, str] = {}
            for side in row.operands:
                for member in side.members:
                    owned.setdefault(member.label, side.name)
            for side in row.operands:
                if not side.defined:
                    key = (effect_id, "operand-knot", index, side.name, None)
                    rows[key] = {
                        "effect_id": effect_id,
                        "kind": "operand-knot",
                        "knot_index": index,
                        "depth_mm": depth,
                        "side": side.name,
                        "member": _offending_member(side),
                        "state": EffectState(side.state).value,
                        "reason": side.reason,
                    }
                for member in side.members:
                    if member.defined:
                        continue
                    key = (effect_id, "read", index, owned[member.label], member.label)
                    rows[key] = {
                        "effect_id": effect_id,
                        "kind": "read",
                        "knot_index": index,
                        "depth_mm": depth,
                        "side": owned[member.label],
                        "member": member.label,
                        "state": _read_state_text(member),
                        "reason": member.reason,
                    }
        if effect.shape.correlation is None:
            key = (effect_id, "shape", None, None, None)
            rows[key] = {
                "effect_id": effect_id,
                "kind": "shape",
                "knot_index": None,
                "depth_mm": None,
                "side": None,
                "member": None,
                "state": SHAPE_STATE,
                "reason": effect.shape.reason,
            }
    return rows


def _offending_member(side: OperandRead) -> str | None:
    """The member a mean-of-four operand's refusal names, or ``None`` for one recording."""
    members = side.members
    if side.kind != "mean-of-four":
        return None
    if side.state.value == EffectState.UNDEFINED_ALIGNMENT.value:
        for member in members:
            if not member.aligned:
                return str(member.label)
        return None
    for member in members:
        if not member.defined:
            return str(member.label)
    return None


def _read_state_text(read: ReadAligned) -> str:
    """One participant read's §8 table B text, the unaligned sentinel included."""
    if not read.aligned:
        return PARTICIPANT_STATE_CODES[UNALIGNED_READ_CODE]
    return MetricState(read.state).value


def _compare_nonvalue_counts(
    failures: _Failures,
    document: Mapping[str, object],
    wanted: Mapping[tuple[str, str, object, object, object], Mapping[str, object]],
) -> None:
    """``nonvalue_counts``: the totals by ``(state, kind)`` (§5.5)."""
    counts = document.get("nonvalue_counts")
    if not isinstance(counts, dict):
        failures.require(
            False, f"JSON nonvalue_counts: an object of totals, got {counts!r}"
        )
        return
    recomputed: dict[str, dict[str, int]] = {}
    for row in wanted.values():
        by_kind = recomputed.setdefault(str(row["state"]), {})
        by_kind[str(row["kind"])] = by_kind.get(str(row["kind"]), 0) + 1
    normalized: dict[str, dict[str, int]] = {}
    for state, by_kind in counts.items():
        if not isinstance(by_kind, dict):
            failures.require(
                False,
                f"JSON nonvalue_counts[{state!r}]: the totals are nested by kind, got "
                f"{by_kind!r}",
            )
            return
        normalized[str(state)] = {str(key): value for key, value in by_kind.items()}
    failures.equal("JSON nonvalue_counts", normalized, recomputed)


def _compare_repeats(
    failures: _Failures, document: Mapping[str, object], effects: SittingEffects
) -> None:
    """The descriptive repeat groups, member for member (§5.6)."""
    repeats = document.get("repeats")
    if not isinstance(repeats, list):
        failures.require(False, f"JSON repeats: a list of groups, got {repeats!r}")
        return
    wanted = [_repeat_group(group) for group in effects.repeats]
    found: list[Mapping[str, object]] = []
    for group in repeats:
        if not isinstance(group, dict) or sorted(group) != sorted(REPEAT_KEYS):
            failures.require(
                False,
                f"JSON repeats: every group carries exactly {list(REPEAT_KEYS)}, got "
                f"{sorted(group) if isinstance(group, dict) else group!r}",
            )
            return
        found.append(group)
    if len(found) != len(wanted):
        failures.require(
            False,
            f"JSON repeats: {len(found)} group(s) for the recomputation's {len(wanted)}",
        )
        return
    for group, want in zip(found, wanted, strict=True):
        key = f"{group.get('view')}/{group.get('metric')}/{group.get('condition')}"
        for field, value in want.items():
            if field == "members":
                continue
            failures.equal(f"JSON repeats[{key!r}].{field}", group.get(field), value)
        members = group.get("members")
        if not isinstance(members, list) or len(members) != len(want["members"]):
            failures.require(
                False,
                f"JSON repeats[{key!r}].members: {len(members) if isinstance(members, list) else members!r} member row(s) for the recomputation's {len(want['members'])}",
            )
            continue
        for member, wanted_member in zip(members, want["members"], strict=True):
            if not isinstance(member, dict) or sorted(member) != sorted(
                REPEAT_MEMBER_KEYS
            ):
                failures.require(
                    False,
                    f"JSON repeats[{key!r}].members: every member carries exactly "
                    f"{list(REPEAT_MEMBER_KEYS)}, got "
                    f"{sorted(member) if isinstance(member, dict) else member!r}",
                )
                continue
            for field, value in wanted_member.items():
                failures.equal(
                    f"JSON repeats[{key!r}].members[{member.get('label')!r}].{field}",
                    member.get(field),
                    value,
                )


def _repeat_group(group: object) -> dict[str, object]:
    """One recomputed repeat group as the §5.6 record."""
    members = [
        {
            "label": str(member.label),
            "order": int(member.order),
            "job": str(member.job),
            "value": member.value,
            "defined_count": int(member.defined_count),
            "state": None if member.state is None else MetricState(member.state).value,
            "reason": member.reason,
        }
        for member in group.members
    ]
    return {
        "condition": group.condition,
        "metric": MetricName(group.metric).value,
        "view": SparseView(group.view).value,
        "units": group.units,
        "knot_count": int(group.knot_count),
        "defined_members": int(group.defined_members),
        "min_value": group.min_value,
        "max_value": group.max_value,
        "spread": group.spread,
        "rule": group.rule,
        "statement": group.statement,
        "members": members,
    }


def _compare_artifacts(
    failures: _Failures, document: Mapping[str, object], expected_stem: str
) -> None:
    """The nested ``artifacts`` block: the sibling names and their digest cells (§5.7)."""
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        failures.require(False, f"JSON artifacts: an object, got {artifacts!r}")
        return
    failures.equal("JSON artifacts key set", sorted(artifacts), ["csv", "npz"])
    for kind, extension in _ARTIFACT_EXTENSIONS.items():
        if kind == "json":
            continue
        entry = artifacts.get(kind)
        if not isinstance(entry, dict):
            failures.require(
                False, f"JSON artifacts[{kind!r}]: an object, got {entry!r}"
            )
            continue
        failures.equal(
            f"JSON artifacts[{kind!r}] key set", sorted(entry), ["file", "sha256"]
        )
        failures.equal(
            f"JSON artifacts[{kind!r}].file",
            entry.get("file"),
            f"{expected_stem}{extension}",
        )
        digest = entry.get("sha256")
        failures.require(
            isinstance(digest, str)
            and digest.startswith(DIGEST_PREFIX)
            and _is_lower_hex64(digest[len(DIGEST_PREFIX) :]),
            f"JSON artifacts[{kind!r}].sha256: the digest is 'sha256:' + 64 lowercase hex, "
            f"got {digest!r}",
        )


def _is_lower_hex64(text: str) -> bool:
    """Whether a string is exactly 64 lowercase hexadecimal digits."""
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


# ── the digests, last (§5.7, §11.5) ────────────────────────────────────


def _verify_digests(
    failures: _Failures,
    *,
    document: Mapping[str, object],
    raw_npz: bytes | None,
    paths: Mapping[str, Path],
    expected_stem: str,
) -> None:
    """The NPZ's file bytes, the CSV's canonical LF bytes and the README's JSON digest."""
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        return
    if raw_npz is not None:
        entry = artifacts.get("npz")
        if isinstance(entry, dict):
            found = f"{DIGEST_PREFIX}{_sha256(raw_npz)}"
            failures.equal("the NPZ's file-byte digest", entry.get("sha256"), found)
    entry = artifacts.get("csv")
    if isinstance(entry, dict):
        failures.equal(
            "the CSV's canonical-LF digest",
            entry.get("sha256"),
            table_digest(paths["csv"]),
        )
    readme = paths["readme"]
    try:
        readme_text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        failures.require(False, f"{readme.name} cannot be read: {exc}")
        return
    bound = {
        "json": table_digest(paths["json"]),
        "csv": table_digest(paths["csv"]),
    }
    if raw_npz is not None:
        bound["npz"] = f"{DIGEST_PREFIX}{_sha256(raw_npz)}"
    # §7 binds the README's claims to every published file by digest — including the JSON's,
    # which is the chain's entry point. A README that quoted a stale or wrong NPZ/CSV digest
    # would pass a JSON-only check, so every file's digest must be present, and every
    # ``sha256:<hex>`` the README states must be one of them.
    for kind, digest in bound.items():
        failures.require(
            digest in readme_text,
            f"{readme.name}: the README does not carry the {kind.upper()} digest {digest}, "
            f"so the README → JSON → NPZ + CSV chain is not bound to {paths[kind].name}",
        )
    unbound = sorted(set(_DIGEST_TOKEN.findall(readme_text)) - set(bound.values()))
    failures.require(
        not unbound,
        f"{readme.name}: the README states the digest(s) {unbound}, which match none of the "
        f"files it binds; every digest it quotes is checked against the bytes on disk",
    )
    failures.require(
        f"{expected_stem}.json" in readme_text,
        f"{readme.name}: the README does not name the JSON file it binds "
        f"({expected_stem}.json)",
    )


def _sha256(raw: bytes) -> str:
    """The bare 64-hex lowercase SHA-256 of a byte string."""
    return hashlib.sha256(raw).hexdigest()
