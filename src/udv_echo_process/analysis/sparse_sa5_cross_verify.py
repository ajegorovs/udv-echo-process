"""SA5's **independent verifier** of the cross-sitting agreement artifacts (§12).

``docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`` (§12) fixes an independent
program that re-derives the committed cross-sitting artifact set from the **two committed
within-sitting quartets** and contradicts every claim the writer staged, without reading the
writer's staged values as its input. This module is that program and nothing else.

It never imports the writer (:mod:`sparse_sa5_cross_report`) and never calls the writer's
orchestration path (:func:`~udv_echo_process.analysis.sparse_sa5_cross_sitting.compare_cross_sitting`
/ :func:`~udv_echo_process.analysis.sparse_sa5_cross_sitting.compare_published`). It also never
imports or calls the models layer (:mod:`sparse_sa5_cross_models`), whose ``repeat_contexts`` and
``side_context`` the writer and the orchestration path build every context quotation through: the
§6 mapping and the side quotation are assembled here, from the quartets' own published bytes, so a
context-assembly mistake cannot be shared through one orchestration path (§12). It resolves the
72 frozen ``(view, metric, contrast)`` keys itself, recomputes each comparison through the pure
cross-core primitives, and only then compares the recomputation against the staged bytes:

1. re-verify both source chains from the published bytes — for each side, README -> JSON ->
   NPZ/CSV, recomputing the JSON canonical-LF digest, the NPZ file-byte digest and the CSV
   canonical-LF digest independently of the cross JSON's ``provenance``;
2. recompute every comparison through the frozen rules — exact triple/``effect_id`` match, the
   grid-vs-contrast function, the two sides' support intersection and the native comparison
   knots inside it, ``D``, the common-defined mask and the state pair, and every ``Diagnostics``
   scalar and each ``comparison_state``/``comparison_reason``/``label_state``;
3. compare element-wise: every NPZ member, every CSV scalar, every comparison record's identity
   and states, every non-value row, and each side's context quotation against that side's own
   committed CSV cell;
4. check the invariants the writer could get wrong silently (the mask-vs-state identity, the
   placeholder-signed-zero rule, strictly increasing knots, knots inside ``support_mm``, the
   ``(Kc,)`` shape, ``shape_defined_count == defined_count == |D|``, the member set, the
   state-conditional repeat range keys, the two separated axes, the ancillary repeat-identity
   check, and the two source quartets' byte-unchangedness); and
5. check the **digests last** — the cross NPZ and CSV against the cross JSON, then the cross
   JSON's canonical-LF digest against the cross README. A matching digest over wrong numbers is
   still wrong, so steps 1-4 must pass on their own.

The verifier publishes nothing, writes no file, and performs no new comparison arithmetic of its
own: every number it holds is either recomputed by the frozen core or quoted from the source
quartets' own digest-bound bytes.
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

from udv_echo_process.analysis import sparse_sa5_cross_core as core
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_sa5_bindings import (
    CONTRASTS,
    CORNERS,
    E20_MEMBERS,
)
from udv_echo_process.analysis.sparse_sa5_cross_core import Diagnostics
from udv_echo_process.analysis.sparse_sa5_cross_npz import (
    CROSS_MEMBER_SUFFIXES,
    CrossArrays,
    CrossNpzContainerError,
    CrossNpzSchemaError,
    cross_member_names,
    decode_cross_npz,
)
from udv_echo_process.analysis.sparse_sa5_effects import (
    ENDPOINTS,
    INTERACTION_NAME,
    METHOD,
    WEIGHTING_RULE,
)
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    decode_effect_npz,
)

__all__ = [
    "ARTIFACT_CHECK_NAMES",
    "CHECK_ORDER",
    "CSV_COLUMNS",
    "DIGEST_PREFIX",
    "ORIENTATION",
    "REPORT_DIR",
    "SCHEMA",
    "SOURCE_DIR",
    "STEM",
    "CrossVerification",
    "CrossVerificationError",
    "frozen_keys",
    "verify_cross_artifacts",
]

#: The cross schema's closed id the JSON must carry (§5.1).
SCHEMA = "sa5-cross-sitting/v1"

#: The cross artifact set's stem and the four file suffixes (§1).
STEM = "sa5-cross-sitting"
_SOURCE_EXTENSIONS: Mapping[str, str] = {
    "npz": ".npz",
    "csv": ".csv",
    "json": ".json",
    "readme": ".README.md",
}

#: The plan's publish root, the default source the two quartets are read from (§1). It is anchored
#: at the repository root, never the working directory.
REPORT_DIR = Path("reports/sparse-signal")
SOURCE_DIR = REPORT_DIR

#: The one fixed orientation, and the two reproducibility sitting names (§1).
ORIENTATION = "live2 - live1"
LIVE1, LIVE2 = "live-1", "live-2"
_SITTING_STEM: Mapping[str, str] = {
    LIVE1: "sa5-live-1-effects",
    LIVE2: "sa5-live-2-effects",
}

#: The fixed pass name each reproducibility sitting's quartet must declare (§1). A quartet whose
#: JSON names a different sitting is refused: a side is bound to its declared identity, never
#: swapped in silently under the other sitting's stem.
_PASS_NAME: Mapping[str, str] = {
    LIVE1: "sparse-mixer-live-1",
    LIVE2: "sparse-mixer-live-2",
}

#: The digest prefix every published digest carries (§5.7).
DIGEST_PREFIX = "sha256:"

#: A ``sha256:<64 hex>`` digest token, as the cross README states it.
_DIGEST_TOKEN = re.compile(r"sha256:[0-9a-f]{64}")

#: The CSV's closed column set, in order (§6) — one row per comparison, 72 rows.
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

#: The comparison-reduction columns that must live **only** in the CSV (§5, §6). No other column
#: name may appear as a JSON key.
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

#: The closed key set of one §5.4 ``RepeatContext`` (plus the state-conditional range keys).
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

#: The comparison's own nine check names, in the §5.2 order.
CHECK_ORDER: tuple[str, ...] = (
    "no_output_artifact_written",
    "fixed_orientation_live2_minus_live1",
    "seventy_two_comparisons",
    "every_effect_id_resolves_in_both_sittings",
    "comparison_and_label_states_kept_separate",
    "no_label_but_deferred_pending_review_is_written",
    "no_recurrence_verdict",
    "repeat_context_identity_fully_established",
    "repeat_context_state_isolated_from_comparison_and_label",
)

#: The schema-level six artifact checks of §5.2.
ARTIFACT_CHECK_NAMES: tuple[str, ...] = (
    "npz_members_are_the_closed_set",
    "every_comparison_position_carries_its_mask_and_state",
    "comparison_rows_are_the_frozen_order",
    "no_comparison_scalar_lives_outside_the_csv",
    "source_quartets_are_byte_unchanged",
    "digests_match_the_staged_bytes",
)

#: The ancillary repeat-identity check, which does **not** enter ``ok`` (§10).
ANCILLARY_CHECK = "repeat_context_identity_fully_established"

#: The three non-value position kinds (§5.6).
NONVALUE_KINDS: tuple[str, ...] = ("shape", "peak", "peak-displacement")

#: The JSON-only non-value state label for a refused profile correlation (§5.6).
UNDEFINED_SHAPE = "undefined-shape"

#: Table A of §5.4, published once, taken from the codec's own closed table.
STATE_MEANINGS: tuple[tuple[int, str], ...] = tuple(sorted(EFFECT_STATE_CODES.items()))

#: The corner-knot label set, so the grid-vs-contrast function is stated here, not inherited from
#: the orchestration path (§2).
_CORNER_LABELS = frozenset(row.label for row in CORNERS)

#: The one recurrence label v1 writes on a comparable pair (§5.2, §5.3).
LABEL_DEFERRED = "deferred-pending-review"

# ── the §6 repeat context, assembled here from the frozen quartets (§5.4, §12) ───────
#
# The writer and the orchestration path build every context quotation through
# :mod:`sparse_sa5_cross_models`. §12 requires this verifier to assemble the *same* quotations
# itself from the quartets' own published bytes, so the §6 mapping and its three states are
# transcribed here and the models layer is never imported or called: a context-assembly mistake
# cannot be shared through one orchestration path. The mapping table, the clauses, the state
# tokens and the quoted basis/reason texts are the frozen contract, not the backend's choice.

#: The three §6 repeat-context states (§5.4).
REPEAT_STATE_SELECTED = "selected"
REPEAT_STATE_UNAVAILABLE = "repeat-context-unavailable"
REPEAT_STATE_UNVERIFIABLE = "repeat-context-identity-unverifiable"

#: The three §6 clause kinds of §5.4.
_CLAUSE_UNAVAILABLE = "unavailable"
_CLAUSE_COMMON_REFERENCE = "common-reference"
_CLAUSE_ANCHOR = "block-local-anchor"

#: The two closed §6 reason tokens a typed-empty context carries (§5.4).
_REASON_REPEAT_UNAVAILABLE = (
    "no-published-repeat-group-matches-the-operand-whole-condition"
)
_REASON_REPEAT_UNVERIFIABLE = (
    "anchor-members-whole-achieved-condition-is-not-published-in-the-quartet"
)
_REASON_SELECTED = (
    "the operand and every group member are the same published recordings with the same "
    "achieved condition"
)

#: The three identity-basis texts the §5.4 record quotes verbatim.
_BASIS_UNAVAILABLE = (
    "the prespec fixes no published repeat group for this operand: its own stored window is "
    "not the reference window every published group records"
)
_BASIS_SELECTED = (
    "the group's members are the operand's own published members, whose whole achieved "
    "conditions appear in the provenance rows"
)
_BASIS_ANCHOR = (
    "the prespec names this operand's job anchor group, but the group's members are ctrl-* rows "
    "published only in `repeats`, which carry no achieved-condition fields; whole-condition "
    "identity is not establishable from the frozen quartet, and job/label is never substituted "
    "for it"
)

#: §6's explicit ``(contrast, operand, clause, job)`` mapping, transcribed verbatim from the
#: prespec table: the four corners are ``unavailable``; each emissions contrast names its anchor
#: operand (``block-local-anchor``) and then ``E20`` (``common-reference``); the interaction's
#: four corners are ``unavailable``. The order fixes the order of the published ``repeats``.
_REPEAT_CLAUSES: tuple[tuple[str, str, str, str], ...] = (
    ("pitch_at_burst_4", "cc1", _CLAUSE_UNAVAILABLE, ""),
    ("pitch_at_burst_4", "cc3", _CLAUSE_UNAVAILABLE, ""),
    ("pitch_at_burst_18", "cc2", _CLAUSE_UNAVAILABLE, ""),
    ("pitch_at_burst_18", "cc4", _CLAUSE_UNAVAILABLE, ""),
    ("burst_at_fine_pitch", "cc1", _CLAUSE_UNAVAILABLE, ""),
    ("burst_at_fine_pitch", "cc2", _CLAUSE_UNAVAILABLE, ""),
    ("burst_at_coarse_pitch", "cc3", _CLAUSE_UNAVAILABLE, ""),
    ("burst_at_coarse_pitch", "cc4", _CLAUSE_UNAVAILABLE, ""),
    ("E8_minus_E20", "e8", _CLAUSE_ANCHOR, "emissions-8"),
    ("E8_minus_E20", "E20", _CLAUSE_COMMON_REFERENCE, ""),
    ("E64_minus_E20", "e64", _CLAUSE_ANCHOR, "emissions-64"),
    ("E64_minus_E20", "E20", _CLAUSE_COMMON_REFERENCE, ""),
    ("E128_minus_E20", "e128", _CLAUSE_ANCHOR, "emissions-128"),
    ("E128_minus_E20", "E20", _CLAUSE_COMMON_REFERENCE, ""),
    (INTERACTION_NAME, "cc1", _CLAUSE_UNAVAILABLE, ""),
    (INTERACTION_NAME, "cc2", _CLAUSE_UNAVAILABLE, ""),
    (INTERACTION_NAME, "cc3", _CLAUSE_UNAVAILABLE, ""),
    (INTERACTION_NAME, "cc4", _CLAUSE_UNAVAILABLE, ""),
)

#: Every operand label the §6 mapping can name — the universe a ``limitations`` entry must draw
#: its identity-unverifiable operands from, exactly (§5.4, §10).
_ALL_OPERANDS: tuple[str, ...] = tuple(sorted({row[1] for row in _REPEAT_CLAUSES}))

#: The published common-reference labels (``cr1..cr4``), from the frozen binding (§6).
_E20_LABELS = tuple(member.label for member in E20_MEMBERS)


def _grid_of(contrast: str) -> str:
    """``corner_knots``/``emissions_knots`` — a function of the contrast, not a choice (§2)."""
    if contrast == INTERACTION_NAME:
        return "corner_knots"
    for spec in CONTRASTS:
        if spec.name == contrast:
            members = set(spec.high.members) | set(spec.low.members)
            return "corner_knots" if members <= _CORNER_LABELS else "emissions_knots"
    raise CrossVerificationError(
        f"{contrast!r} is not one of the frozen contrasts or the interaction"
    )


def frozen_keys() -> tuple[tuple[MetricName, SparseView, str], ...]:
    """The 72 keys in the frozen order: endpoint, then contrast, then interaction (§2)."""
    keys: list[tuple[MetricName, SparseView, str]] = []
    for metric, view in ENDPOINTS:
        keys.extend((metric, view, spec.name) for spec in CONTRASTS)
        keys.append((metric, view, INTERACTION_NAME))
    return tuple(keys)


_FROZEN_KEYS = frozen_keys()


class CrossVerificationError(ValueError):
    """The cross-sitting artifacts are not the recomputed ones, or cannot be verified.

    Raised for a missing or unreadable file, a broken source digest chain, a recomputation that
    refuses, or any disagreement between the staged bytes and the independent recomputation. The
    message lists **every** disagreement found, not the first.
    """


class CrossVerification(NamedTuple):
    """What one successful verification established, with the digests it read."""

    artifact_dir: Path
    source_dir: Path
    comparison: str
    comparison_count: int
    npz_member_count: int
    checks: Mapping[str, bool]
    digests: Mapping[str, str]

    @property
    def ok(self) -> bool:
        """True exactly when every verification check holds."""
        return all(self.checks.values())


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

    def boolean(self, what: str, found: object, expected: bool) -> bool:
        """Record a disagreement unless a JSON boolean is exactly ``true``/``false`` (§5).

        A JSON ``1``/``0`` is not a JSON boolean: ``1 == True`` in Python, so a plain equality
        would accept an integer where the schema fixes a boolean type. The type is checked first.
        """
        return self.require(
            type(found) is bool and found == expected,
            f"{what}: a JSON boolean {expected!r}, got {found!r} "
            f"({type(found).__name__})",
        )


# ── digests and paths ──────────────────────────────────────────────────


def _file_digest(data: bytes) -> str:
    """``sha256:`` over **exact** bytes (the container's digest, §5.7)."""
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def _canonical_digest(data: bytes) -> str:
    """``sha256:`` over canonical-LF **text** bytes (the JSON and CSV digest, §5.7)."""
    return _file_digest(data.replace(b"\r\n", b"\n"))


def _repository_root() -> Path:
    """The checkout this module is part of, from its own location (four levels up)."""
    return Path(__file__).resolve().parents[3]


def _anchor(path: Path) -> Path:
    """Anchor a possibly-relative path at the repository root, never the working directory."""
    candidate = Path(path)
    return candidate if candidate.is_absolute() else _repository_root() / candidate


def _read_bytes(path: Path, where: str) -> bytes:
    """One published file's exact bytes, or a refusal naming it."""
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise CrossVerificationError(
            f"cannot read the published {where} {path}: {exc}"
        ) from exc


# ── one side's independently verified quartet ──────────────────────────


class _Side(NamedTuple):
    """One source quartet, its chain re-verified and its bytes decoded by this verifier."""

    sitting: str
    stem: str
    pass_name: str
    plan: str
    plan_fingerprint: str
    digests: Mapping[str, str]
    document: Mapping[str, object]
    arrays: Mapping[str, object]
    csv_rows: Mapping[str, Mapping[str, str]]
    by_id: Mapping[str, Mapping[str, object]]

    def provenance(self) -> dict[str, object]:
        """The §5.4 ``SideProvenance`` record this side must be quoted as."""
        return {
            "sitting": self.sitting,
            "pass_name": self.pass_name,
            "plan": self.plan,
            "plan_fingerprint": self.plan_fingerprint,
            "stem": self.stem,
            "json_sha256": self.digests["json"],
            "npz_sha256": self.digests["npz"],
            "csv_sha256": self.digests["csv"],
            "checks_ok": bool(all(self.document["checks"].values())),  # type: ignore[union-attr]
            "artifact_checks_ok": bool(  # type: ignore[union-attr]
                all(self.document["artifact_checks"].values())
            ),
        }


def _parse_csv(data: bytes) -> Mapping[str, Mapping[str, str]]:
    """The published source CSV parsed by effect id, refusing a header or row drift."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CrossVerificationError(f"the source CSV is not UTF-8 ({exc})") from exc
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or "effect_id" not in rows[0]:
        raise CrossVerificationError("the source CSV carries no effect_id header")
    header = tuple(rows[0])
    parsed: dict[str, Mapping[str, str]] = {}
    for row in rows[1:]:
        if len(row) != len(header):
            raise CrossVerificationError("a source CSV row drifts from its header")
        cells = dict(zip(header, row, strict=True))
        if cells["effect_id"] in parsed:
            raise CrossVerificationError(
                f"the source CSV carries the effect id {cells['effect_id']!r} twice"
            )
        parsed[cells["effect_id"]] = cells
    return parsed


def _load_side(directory: Path, sitting: str) -> _Side:
    """Read one published side and re-verify its whole digest chain independently (§12.1)."""
    stem = _SITTING_STEM[sitting]
    json_bytes = _read_bytes(directory / f"{stem}.json", "JSON")
    npz_bytes = _read_bytes(directory / f"{stem}.npz", "container")
    csv_bytes = _read_bytes(directory / f"{stem}.csv", "table")
    try:
        readme = _read_bytes(directory / f"{stem}.README.md", "README").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CrossVerificationError(
            f"{stem}.README.md is not UTF-8 text: {exc}"
        ) from exc
    try:
        document = json.loads(json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CrossVerificationError(
            f"{stem}.json is not readable JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise CrossVerificationError(f"{stem}.json is not a JSON object")
    if document.get("schema") != "sa5-within-sitting-effects/v1":
        raise CrossVerificationError(
            f"{stem}.json names the schema {document.get('schema')!r}, not the v1 within-sitting id"
        )
    # §1: the quartet's own declared sitting is fixed, not whatever a swapped file claims.
    declared = document.get("sitting")
    if declared != _PASS_NAME[sitting]:
        raise CrossVerificationError(
            f"{stem}.json names the sitting {declared!r}, not the fixed "
            f"{_PASS_NAME[sitting]!r} of {sitting!r}: a side is bound to its declared sitting, "
            "never to a quartet swapped under this stem"
        )
    digests = {
        "json": _canonical_digest(json_bytes),
        "npz": _file_digest(npz_bytes),
        "csv": _canonical_digest(csv_bytes),
    }
    if digests["json"] not in readme:
        raise CrossVerificationError(
            f"{stem}: the README does not bind the document's canonical-LF digest "
            f"{digests['json']}, so the chain is broken"
        )
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CrossVerificationError(f"{stem}.json publishes no artifacts object")
    for kind, name in (("npz", f"{stem}.npz"), ("csv", f"{stem}.csv")):
        entry = artifacts.get(kind)
        if not isinstance(entry, dict) or entry.get("file") != name:
            raise CrossVerificationError(
                f"{stem}.json does not bind the {kind} file {name!r}"
            )
        if entry.get("sha256") != digests[kind]:
            raise CrossVerificationError(
                f"{stem}: the JSON records {entry.get('sha256')!r} for {name}, the published "
                f"bytes hash to {digests[kind]!r}: the chain is broken"
            )
        if name not in readme:
            raise CrossVerificationError(f"{stem}: the README does not name {name}")
    if document.get("ok") is not True:
        raise CrossVerificationError(
            f"{stem}.json is not ok, so the side is not a usable input"
        )
    for field in ("checks", "artifact_checks"):
        verdicts = document.get(field)
        if not isinstance(verdicts, dict) or not all(verdicts.values()):
            raise CrossVerificationError(f"{stem}.json's own {field} do not all hold")

    effects = document.get("effects")
    if not isinstance(effects, list):
        raise CrossVerificationError(f"{stem}.json publishes no effects list")
    shapes: dict[str, tuple[int, int]] = {}
    by_id: dict[str, Mapping[str, object]] = {}
    try:
        for record in effects:
            if not isinstance(record, dict):
                raise CrossVerificationError(
                    f"{stem}.json carries a non-object effect row"
                )
            key = str(record.get("effect_id"))
            if key in by_id:
                raise CrossVerificationError(
                    f"{stem}.json carries the effect id {key!r} twice"
                )
            by_id[key] = record
            shapes[key] = (
                int(record["knot_count"]),
                int(record["participant_count"]),
            )
    except CrossVerificationError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise CrossVerificationError(
            f"{stem}.json carries a malformed effect row: {exc}"
        ) from exc
    try:
        arrays = {
            r.effect_id: r for r in decode_effect_npz(npz_bytes, expected=dict(shapes))
        }
    except ValueError as exc:
        raise CrossVerificationError(
            f"{stem}: the container is refused: {exc}"
        ) from exc
    if set(arrays) != set(by_id):
        raise CrossVerificationError(
            f"{stem}: the container's effect set is not the document's"
        )
    csv_rows = _parse_csv(csv_bytes)
    if set(csv_rows) != set(by_id):
        raise CrossVerificationError(
            f"{stem}: the CSV's effect set is not the document's"
        )
    return _Side(
        sitting=sitting,
        stem=stem,
        pass_name=_PASS_NAME[sitting],
        plan=str(document.get("plan", "")),
        plan_fingerprint=str(document.get("plan_fingerprint", "")),
        digests=digests,
        document=document,
        arrays=arrays,
        csv_rows=csv_rows,
        by_id=by_id,
    )


# ── the recomputed comparison (§12.2) ──────────────────────────────────


class _ExpectedComparison(NamedTuple):
    """One comparison as the independent recomputation says it must appear in all three files."""

    effect_id: str
    record: Mapping[str, object]
    cells: Mapping[str, object]
    arrays: CrossArrays | None
    diagnostics: Diagnostics | None
    nonvalue: tuple[Mapping[str, object], ...]
    support: tuple[float, float] | None
    context1: Mapping[str, object]
    context2: Mapping[str, object]


def _resolve(
    side: _Side,
    metric: MetricName,
    view: SparseView,
    contrast: str,
    failures: _Failures,
) -> Mapping[str, object] | None:
    """The one published record for a key, resolved by exact triple match, never by parsing."""
    wanted = f"{view.value}__{metric.value}__{contrast}"
    matches = [
        record
        for record in side.by_id.values()
        if record.get("view") == view.value
        and record.get("metric") == metric.value
        and record.get("contrast") == contrast
    ]
    if len(matches) > 1:
        raise CrossVerificationError(
            f"{side.stem}: the key {wanted!r} resolves to {len(matches)} records"
        )
    if not matches:
        return None
    if matches[0].get("effect_id") != wanted:
        failures.require(
            False,
            f"{side.stem}: the record for {wanted!r} carries the effect id "
            f"{matches[0].get('effect_id')!r}, which disagrees with the resolved triple",
        )
    return matches[0]


def _cross_arrays(
    effect_id: str, rows: Sequence[object], knots: np.ndarray
) -> CrossArrays:
    """One comparable record's five §3 arrays, built from the recomputed knot rows (§9)."""
    knots_mm = np.asarray(knots, dtype="<f8")
    count = int(knots_mm.shape[0])
    difference = np.zeros(count, dtype="<f8")
    defined = np.zeros(count, dtype="<u1")
    state1 = np.zeros(count, dtype="<u1")
    state2 = np.zeros(count, dtype="<u1")
    for index, knot in enumerate(rows):
        state1[index] = knot.state1_code  # type: ignore[attr-defined]
        state2[index] = knot.state2_code  # type: ignore[attr-defined]
        if not knot.defined:  # type: ignore[attr-defined]
            continue
        defined[index] = 1
        difference[index] = float(knot.difference)  # type: ignore[attr-defined]
    return CrossArrays(
        effect_id=effect_id,
        comparison_knot_count=count,
        knots_mm=knots_mm,
        difference=difference,
        defined=defined,
        state1=state1,
        state2=state2,
    )


def _num_or_none(
    cells: Mapping[str, str], column: str, cast: type = float
) -> float | int | None:
    """One quoted side-CSV scalar, or ``None`` for the empty field (§5.4)."""
    text = cells.get(column, "")
    return None if text == "" else cast(text)


def _one_group(
    matches: Sequence[Mapping[str, object]], what: str, stem: str
) -> Mapping[str, object]:
    """Exactly one located repeat group, or a refusal: a publication defect is never narrowed."""
    if len(matches) != 1:
        raise CrossVerificationError(
            f"{stem}: the §6 mapping names {what}, but the side's published repeats carry "
            f"{len(matches)} such group(s): a publication defect, never a silently narrowed mapping"
        )
    return matches[0]


def _repeat_member_document(row: Mapping[str, object]) -> dict[str, object]:
    """One quoted repeat member, read from the side's own published row (§5.4)."""
    value = row.get("value")
    state = row.get("state")
    return {
        "label": str(row["label"]),
        "order": int(row["order"]),  # type: ignore[arg-type]
        "job": str(row["job"]),
        "value": None if value is None else float(value),  # type: ignore[arg-type]
        "defined_count": int(row["defined_count"]),  # type: ignore[arg-type]
        "state": None if state is None else str(state),
        "reason": str(row["reason"]),
    }


def _repeat_document(
    operand: str, clause: str, state: str, group: Mapping[str, object] | None
) -> dict[str, object]:
    """One §5.4 ``RepeatContext`` record, its range keys state-conditional (A1).

    ``unavailable`` quotes its typed-empty reason and carries nothing else; ``unverifiable``
    quotes the named group's own members and condition but **no** numerical range; ``selected``
    proves whole-condition identity and carries the group's range.
    """
    if state == REPEAT_STATE_UNAVAILABLE:
        return {
            "operand": operand,
            "clause": clause,
            "state": state,
            "group_condition": None,
            "members": [],
            "identity_verified": False,
            "identity_basis": _BASIS_UNAVAILABLE,
            "reason": _REASON_REPEAT_UNAVAILABLE,
        }
    assert group is not None
    if state == REPEAT_STATE_SELECTED:
        basis, reason = _BASIS_SELECTED, _REASON_SELECTED
    else:
        basis, reason = _BASIS_ANCHOR, _REASON_REPEAT_UNVERIFIABLE
    selected = state == REPEAT_STATE_SELECTED
    document: dict[str, object] = {
        "operand": operand,
        "clause": clause,
        "state": state,
        "group_condition": str(group["condition"]),
        "members": [
            _repeat_member_document(row)
            for row in group["members"]  # type: ignore[union-attr]
        ],
        "identity_verified": selected,
        "identity_basis": basis,
        "reason": reason,
    }
    if selected:
        spread = group.get("spread")
        document["min_value"] = float(group["min_value"])  # type: ignore[arg-type]
        document["max_value"] = float(group["max_value"])  # type: ignore[arg-type]
        document["spread"] = None if spread is None else float(spread)  # type: ignore[arg-type]
    return document


def _repeat_contexts(
    side: _Side, contrast: str, metric: str, view: str
) -> tuple[Mapping[str, object], ...]:
    """One side's §6 repeat contexts, assembled here from its own published JSON (§5.4, §12).

    The §6 mapping is transcribed in this module and never obtained from the models layer, so a
    context-assembly mistake is not shared with the writer through one orchestration path.
    """
    document = side.document
    repeats = document.get("repeats")
    if not isinstance(repeats, list):
        raise CrossVerificationError(f"{side.stem}.json publishes no repeats list")
    groups = [
        group
        for group in repeats
        if isinstance(group, dict)
        and group.get("metric") == metric
        and group.get("view") == view
    ]
    provenance = document.get("provenance")
    if not isinstance(provenance, list):
        raise CrossVerificationError(f"{side.stem}.json publishes no provenance list")
    published = {str(row["label"]): row for row in provenance if isinstance(row, dict)}

    contexts: list[Mapping[str, object]] = []
    for entry_contrast, operand, clause, job in _REPEAT_CLAUSES:
        if entry_contrast != contrast:
            continue
        if clause == _CLAUSE_UNAVAILABLE:
            contexts.append(
                _repeat_document(operand, clause, REPEAT_STATE_UNAVAILABLE, group=None)
            )
        elif clause == _CLAUSE_COMMON_REFERENCE:
            group = _one_group(
                [
                    candidate
                    for candidate in groups
                    if tuple(
                        str(member["label"])
                        for member in candidate["members"]  # type: ignore[union-attr]
                    )
                    == _E20_LABELS
                ],
                f"the common-reference group ({list(_E20_LABELS)})",
                side.stem,
            )
            for row in group["members"]:  # type: ignore[union-attr]
                label = str(row["label"])
                row_published = published.get(label)
                if row_published is None:
                    raise CrossVerificationError(
                        f"{side.stem}: the common-reference group names {label!r}, not a "
                        "published provenance row, so its achieved condition cannot be read"
                    )
                if str(row["job"]) != str(row_published["job"]) or int(
                    row["order"]
                ) != int(row_published["order"]):
                    raise CrossVerificationError(
                        f"{side.stem}: the common-reference group's {label!r} row is not the "
                        "published provenance row of the same job and order"
                    )
            contexts.append(
                _repeat_document(operand, clause, REPEAT_STATE_SELECTED, group)
            )
        else:  # block-local anchor: ctrl-* rows carry no achieved-condition fields
            group = _one_group(
                [
                    candidate
                    for candidate in groups
                    if candidate.get("members")
                    and all(
                        str(member["job"]) == job
                        and str(member["label"]).startswith("ctrl-")
                        for member in candidate["members"]  # type: ignore[union-attr]
                    )
                ],
                f"the block-local anchor group of job {job!r}",
                side.stem,
            )
            contexts.append(
                _repeat_document(operand, clause, REPEAT_STATE_UNVERIFIABLE, group)
            )
    return tuple(contexts)


def _context_document(
    side: _Side, key: str, contrast: str, metric: str, view: str
) -> Mapping[str, object]:
    """One side's §5.4 context quotation, assembled here from its own digest-bound CSV and JSON."""
    cells = side.csv_rows.get(key, {})
    return {
        "sitting": side.sitting,
        "units": cells.get("units") or None,
        "rms_magnitude": _num_or_none(cells, "rms_magnitude"),
        "signed_depth_average": _num_or_none(cells, "signed_depth_average"),
        "equal_knot_average": _num_or_none(cells, "equal_knot_average"),
        "max_abs_value": _num_or_none(cells, "max_abs_value"),
        "max_abs_depth_mm": _num_or_none(cells, "max_abs_depth_mm"),
        "covered_depth_mm": _num_or_none(cells, "covered_depth_mm"),
        "coverage_fraction": _num_or_none(cells, "coverage_fraction"),
        "defined_count": _num_or_none(cells, "defined_count", int),
        "undefined_alignment_count": _num_or_none(
            cells, "undefined_alignment_count", int
        ),
        "undefined_operand_count": _num_or_none(cells, "undefined_operand_count", int),
        "knot_count": _num_or_none(cells, "knot_count", int),
        "repeats": list(_repeat_contexts(side, contrast, metric, view)),
    }


def _nonvalue_rows(
    effect_id: str, diagnostics: Diagnostics | None
) -> tuple[Mapping[str, object], ...]:
    """The typed-empty rows of one comparable comparison, in the fixed §5.6 order (§5.6)."""
    if diagnostics is None:
        return ()
    rows: list[Mapping[str, object]] = []
    if diagnostics.shape_correlation is None:
        rows.append(
            {
                "effect_id": effect_id,
                "kind": "shape",
                "side": None,
                "state": UNDEFINED_SHAPE,
                "reason": diagnostics.shape_reason,
            }
        )
    for side, localized, reason in (
        (LIVE1, diagnostics.peak_localized1, diagnostics.peak_reason1),
        (LIVE2, diagnostics.peak_localized2, diagnostics.peak_reason2),
    ):
        if not localized:
            rows.append(
                {
                    "effect_id": effect_id,
                    "kind": "peak",
                    "side": side,
                    "state": reason,
                    "reason": reason,
                }
            )
    if diagnostics.peak_displacement is None:
        rows.append(
            {
                "effect_id": effect_id,
                "kind": "peak-displacement",
                "side": None,
                "state": diagnostics.peak_displacement_reason,
                "reason": diagnostics.peak_displacement_reason,
            }
        )
    return tuple(rows)


def _expected_comparison(
    metric: MetricName,
    view: SparseView,
    contrast: str,
    left: _Side,
    right: _Side,
    failures: _Failures,
) -> _ExpectedComparison:
    """Recompute one comparison through the frozen rules, never through the orchestrator."""
    key = f"{view.value}__{metric.value}__{contrast}"
    left_record = _resolve(left, metric, view, contrast, failures)
    right_record = _resolve(right, metric, view, contrast, failures)
    present = right_record or left_record or {}
    grid, units = present.get("grid"), present.get("units")
    knot_count, participant_count = (
        present.get("knot_count"),
        present.get("participant_count"),
    )

    state: str
    reason: str
    label: str | None = None
    support: tuple[float, float] | None = None
    arrays: CrossArrays | None = None
    diagnostics: Diagnostics | None = None

    if left_record is None or right_record is None:
        missing = LIVE1 if left_record is None else LIVE2
        state = "not comparable"
        reason = (
            f"side-effect-not-published: the effect is not published on {missing}, so the "
            "pair is not matched"
        )
    elif left_record.get("effect_id") != right_record.get("effect_id"):
        state, reason = "not comparable", "effect-id-mismatch"
    else:
        expected_grid = _grid_of(contrast)
        state, reason = "not comparable", ""
        for record in (left_record, right_record):
            if record.get("grid") != expected_grid:
                reason = "grid-mismatch-pending-review"
                break
            if record.get("units") != left_record.get("units"):
                reason = "units-mismatch"
                break
        else:
            structural = (
                "metric",
                "view",
                "contrast",
                "grid",
                "units",
                "knot_count",
                "participant_count",
            )
            if any(left_record.get(f) != right_record.get(f) for f in structural):
                reason = "triple-mismatch"
            else:
                reason = ""
        if not reason:
            left_arrays, right_arrays = left.arrays[key], right.arrays[key]
            if not core.native_knots_match(left_arrays, right_arrays):  # type: ignore[arg-type]
                reason = "grid-mismatch-pending-review"
        if not reason:
            support = (
                max(
                    float(left_record["support_mm"][0]),  # type: ignore[index]
                    float(right_record["support_mm"][0]),  # type: ignore[index]
                ),
                min(
                    float(left_record["support_mm"][1]),  # type: ignore[index]
                    float(right_record["support_mm"][1]),  # type: ignore[index]
                ),
            )
            if support[1] <= support[0]:
                reason = "empty-common-support"
                support = None
        if not reason:
            within = core.within_support(  # type: ignore[arg-type]
                right.arrays[key].knots_mm, support
            )
            if not bool(within.any()):
                reason = "empty-common-support"
                support = None
            else:
                left_restricted = core.restrict(left.arrays[key], within)  # type: ignore[arg-type]
                right_restricted = core.restrict(right.arrays[key], within)  # type: ignore[arg-type]
                knots = np.asarray(right_restricted.knots_mm, dtype=float)
                rows, definition = core.knot_comparison(
                    knots, left_restricted, right_restricted
                )
                if not bool(definition.any()):
                    reason = "side-wholly-undefined"
                    support = None
                else:
                    diagnostics = core.comparison_diagnostics(
                        rows, definition, left_restricted, right_restricted
                    )
                    arrays = _cross_arrays(key, rows, knots)
                    state, reason, label = (
                        "comparable",
                        "common-basis-established",
                        LABEL_DEFERRED,
                    )

    context1 = _context_document(left, key, contrast, metric.value, view.value)
    context2 = _context_document(right, key, contrast, metric.value, view.value)
    record: dict[str, object] = {
        "effect_id": key,
        "view": view.value,
        "metric": metric.value,
        "contrast": contrast,
        "grid": None if grid is None else str(grid),
        "units": None if units is None else str(units),
        "knot_count": None if knot_count is None else int(knot_count),  # type: ignore[arg-type]
        "comparison_knot_count": (
            None if arrays is None else int(arrays.comparison_knot_count)
        ),
        "participant_count": (
            None if participant_count is None else int(participant_count)  # type: ignore[arg-type]
        ),
        "support_mm": None
        if support is None
        else [float(support[0]), float(support[1])],
        "comparison_state": state,
        "comparison_reason": reason,
        "label_state": label,
        "context1": context1,
        "context2": context2,
    }
    diag = diagnostics
    cells: dict[str, object] = {
        "effect_id": key,
        "view": view.value,
        "metric": metric.value,
        "contrast": contrast,
        "units": record["units"],
        "grid": record["grid"],
        "knot_count": record["knot_count"],
        "comparison_knot_count": record["comparison_knot_count"],
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
    return _ExpectedComparison(
        effect_id=key,
        record=record,
        cells=cells,
        arrays=arrays,
        diagnostics=diagnostics,
        nonvalue=_nonvalue_rows(key, diagnostics),
        support=support,
        context1=context1,
        context2=context2,
    )


def _expected_comparisons(
    sides: Mapping[str, _Side], failures: _Failures
) -> tuple[_ExpectedComparison, ...]:
    """Recompute the whole frozen 72-comparison set for the ``live2 - live1`` orientation."""
    left, right = sides[LIVE1], sides[LIVE2]
    return tuple(
        _expected_comparison(metric, view, contrast, left, right, failures)
        for metric, view, contrast in _FROZEN_KEYS
    )


# ── the CSV layer (§6, §12.3) ──────────────────────────────────────────


def _cell_text(value: object, *, boolean: bool) -> str:
    """One CSV cell text: a boolean token, an int as itself, a float by ``.17g``, ``None`` empty."""
    if value is None:
        return ""
    if boolean:
        if type(value) is not bool:
            raise CrossVerificationError(
                f"a CSV boolean cell is a bool or the empty field, got {value!r}"
            )
        return "true" if value else "false"
    if isinstance(value, bool):
        raise CrossVerificationError("a CSV numeric cell is never a boolean")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, str):
        return value
    raise CrossVerificationError(
        f"a CSV cell is a number or text, got {type(value).__name__}"
    )


def _read_cross_csv(path: Path, failures: _Failures) -> list[dict[str, str]]:
    """The cross CSV's parsed rows, or a recorded refusal."""
    raw = _read_bytes(path, "cross CSV")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        failures.require(False, f"{path.name} is not valid UTF-8: {exc}")
        return []
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        failures.require(False, f"{path.name}: the CSV carries no header row")
        return []
    if tuple(rows[0]) != CSV_COLUMNS:
        failures.require(
            False,
            f"{path.name}: the header is not the closed §6 column set in order; the file has "
            f"{rows[0]}",
        )
        return []
    parsed: list[dict[str, str]] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(CSV_COLUMNS):
            failures.require(
                False,
                f"{path.name} row {number}: {len(row)} cell(s) for {len(CSV_COLUMNS)} columns",
            )
            continue
        parsed.append(dict(zip(CSV_COLUMNS, row, strict=True)))
    if not parsed:
        failures.require(False, f"{path.name}: the CSV carries no data row")
    return parsed


def _compare_csv(
    failures: _Failures,
    expected: tuple[_ExpectedComparison, ...],
    rows: list[dict[str, str]],
) -> None:
    """Every CSV cell against the recomputed comparison, in the frozen order (§6)."""
    if not rows:
        return
    wanted = [item.effect_id for item in expected]
    found = [row["effect_id"] for row in rows]
    if found != wanted:
        failures.require(
            False,
            f"the CSV's rows are not the §2 comparison order ({len(found)} row(s) for "
            f"{len(wanted)} comparison(s))",
        )
        return
    for item, row in zip(expected, rows, strict=True):
        for column in CSV_COLUMNS:
            want = _cell_text(item.cells[column], boolean=column in BOOLEAN_COLUMNS)
            failures.equal(f"{item.effect_id} CSV {column}", row[column], want)


# ── the NPZ layer (§3, §4, §12.3-§12.4) ────────────────────────────────


def _array_diff(found: np.ndarray, expected: np.ndarray) -> str | None:
    """A sentence describing the first difference (signed zeros included), or ``None``."""
    if found.dtype != expected.dtype:
        return f"dtype {found.dtype.str} against the recomputed {expected.dtype.str}"
    if found.shape != expected.shape:
        return f"shape {found.shape} against the recomputed {expected.shape}"
    equal = found == expected
    if not bool(np.all(equal)):
        flat = np.argwhere(~equal)
        position = tuple(int(v) for v in flat[0])
        return (
            f"{int(flat.shape[0])} of {found.size} position(s) differ; the first is at "
            f"{position}: {found[position].item()!r} against {expected[position].item()!r}"
        )
    if np.issubdtype(found.dtype, np.floating):
        signs = np.signbit(found)
        want_signs = np.signbit(expected)
        if not bool(np.array_equal(signs, want_signs)):
            flat = np.argwhere(signs != want_signs)
            position = tuple(int(v) for v in flat[0])
            return (
                f"the signed-zero bits differ at {int(flat.shape[0])} position(s); the first is "
                f"at {position}: {found[position].item()!r} against {expected[position].item()!r}"
            )
    return None


def _compare_npz(
    failures: _Failures,
    expected: tuple[_ExpectedComparison, ...],
    records: tuple[CrossArrays, ...],
) -> None:
    """Every decoded NPZ array against the recomputed comparison, member by member (§3, §9)."""
    by_id = {item.effect_id: item for item in expected if item.arrays is not None}
    found = {record.effect_id for record in records}
    missing = sorted(set(by_id) - found)
    extra = sorted(found - set(by_id))
    failures.require(
        not missing,
        f"the container carries no member for the comparable comparison(s) {missing} the "
        "recomputation produced",
    )
    failures.require(
        not extra,
        f"the container carries member(s) for {extra} the recomputation never made comparable",
    )
    for record in records:
        want = by_id.get(record.effect_id)
        if want is None:
            continue
        assert want.arrays is not None
        if record.comparison_knot_count != want.arrays.comparison_knot_count:
            failures.require(
                False,
                f"{record.effect_id}: the container declares Kc={record.comparison_knot_count}, "
                f"the recomputation has Kc={want.arrays.comparison_knot_count}",
            )
        # §12.4: the mask is 1 exactly where both state codes are 0, and a -0.0 occupies a
        # defined position only.
        defined = record.defined == 1
        common = (record.state1 == 0) & (record.state2 == 0)
        failures.require(
            bool(np.array_equal(defined, common)),
            f"{record.effect_id}: the defined mask is not 1 exactly where both sides' state "
            "code is 0",
        )
        if bool((record.defined != 1).any()):
            undefined_values = record.difference[record.defined != 1]
            failures.require(
                bool(np.all(undefined_values == 0.0))
                and not bool(np.any(np.signbit(undefined_values))),
                f"{record.effect_id}: an undefined position does not carry the +0.0 placeholder",
            )
        if record.comparison_knot_count > 1:
            failures.require(
                bool((np.diff(record.knots_mm) > 0.0).all()),
                f"{record.effect_id}: knots_mm is not strictly increasing",
            )
        if want.support is not None:
            knots = np.asarray(record.knots_mm, dtype=float)
            failures.require(
                bool(
                    (knots >= want.support[0]).all()
                    and (knots <= want.support[1]).all()
                ),
                f"{record.effect_id}: a comparison knot lies outside support_mm "
                f"{list(want.support)}",
            )
        for suffix in CROSS_MEMBER_SUFFIXES:
            mine = getattr(record, suffix)
            theirs = getattr(want.arrays, suffix)
            detail = _array_diff(mine, theirs)
            failures.require(
                detail is None,
                f"{record.effect_id} member {suffix}: {detail}",
            )
        # §6: the second defined count is not serialized; the recomputed Diagnostics must satisfy
        # shape_defined_count == defined_count == |D|.
        assert want.diagnostics is not None
        failures.equal(
            f"{record.effect_id} defined_count",
            int(np.count_nonzero(defined)),
            want.diagnostics.defined_count,
        )
        failures.require(
            want.diagnostics.shape_defined_count == want.diagnostics.defined_count,
            f"{record.effect_id}: the recomputed Diagnostics has "
            f"shape_defined_count={want.diagnostics.shape_defined_count} and "
            f"defined_count={want.diagnostics.defined_count}, which must be equal",
        )


# ── the JSON layer (§5, §12.3-§12.4) ───────────────────────────────────


def _read_cross_json(
    path: Path, failures: _Failures
) -> tuple[bytes | None, object | None]:
    """The JSON's exact bytes and its parsed document, or a recorded refusal."""
    raw = _read_bytes(path, "cross JSON")
    try:
        text = raw.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        failures.require(False, f"{path.name} is not strict JSON: {exc}")
        return raw, None
    try:
        canonical = (
            json.dumps(
                document,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        )
    except ValueError as exc:
        failures.require(
            False,
            f"{path.name} carries a non-finite number, and §5 fixes strict JSON with "
            f"allow_nan=False: {exc}",
        )
        return raw, None
    failures.require(
        raw == canonical.encode("utf-8"),
        f"{path.name}: the bytes are not the §5 canonical strict JSON (UTF-8, ensure_ascii, "
        "sort_keys, ','/':' separators, one trailing newline): re-serializing does not "
        "reproduce the file",
    )
    return raw, document


def _compare_json(
    failures: _Failures,
    expected: tuple[_ExpectedComparison, ...],
    sides: Mapping[str, _Side],
    document: Mapping[str, object],
    json_text: str,
) -> None:
    """The JSON structure, provenance, context quotations and non-value rows (§5)."""
    if sorted(document) != sorted(JSON_FIELDS):
        failures.require(
            False,
            "the JSON field set is closed: missing "
            f"{sorted(JSON_FIELDS - set(document))}, unexpected "
            f"{sorted(set(document) - JSON_FIELDS)}",
        )
    failures.equal("JSON schema", document.get("schema"), SCHEMA)
    failures.equal("JSON comparison", document.get("comparison"), ORIENTATION)
    failures.equal("JSON sitting1", document.get("sitting1"), LIVE1)
    failures.equal("JSON sitting2", document.get("sitting2"), LIVE2)
    failures.equal(
        "JSON weighting_rule", document.get("weighting_rule"), WEIGHTING_RULE
    )
    failures.equal("JSON method", document.get("method"), METHOD)
    for key in ("analysis_commit", "generator_revision", "generator_command"):
        failures.require(
            isinstance(document.get(key), str) and bool(document.get(key)),
            f"JSON {key}: a non-empty string, got {document.get(key)!r}",
        )
    command = document.get("generator_command")
    if isinstance(command, str) and command:
        failures.require(
            "udv_echo_process.analysis.sparse_sa5_cross_report" in command,
            f"JSON generator_command {command!r} does not name the cross-sitting writer module",
        )
    for column in REDUCTION_ONLY_COLUMNS:
        failures.require(
            f'"{column}":' not in json_text,
            f"JSON: the comparison reduction {column!r} must live only in the CSV, but a key "
            "of that name appears in the JSON",
        )

    _compare_state_meanings(failures, document)
    _compare_checks(failures, document, expected, sides)
    _compare_provenance(failures, document, sides)
    _compare_comparisons(failures, document, expected, sides)
    _compare_members(failures, document, expected)
    _compare_nonvalue_rows(failures, document, expected)
    _compare_artifacts_object(failures, document)


def _compare_state_meanings(
    failures: _Failures, document: Mapping[str, object]
) -> None:
    """The published table A: ``{"effect": [{code, text}, ...]}`` (§5.4)."""
    meanings = document.get("state_meanings")
    if not isinstance(meanings, Mapping) or sorted(meanings) != ["effect"]:
        failures.require(
            False,
            f"JSON state_meanings: exactly the 'effect' code space, got {meanings!r}",
        )
        return
    rows = meanings["effect"]
    expected = [{"code": code, "text": text} for code, text in STATE_MEANINGS]
    failures.equal("JSON state_meanings.effect", rows, expected)


def _compare_checks(
    failures: _Failures,
    document: Mapping[str, object],
    expected: tuple[_ExpectedComparison, ...],
    sides: Mapping[str, _Side],
) -> None:
    """The nine run checks and the six artifact checks (§5.2, §10)."""
    checks = document.get("checks")
    if isinstance(checks, dict):
        failures.equal("JSON checks key set", sorted(checks), sorted(CHECK_ORDER))
        for name in CHECK_ORDER:
            if name == ANCILLARY_CHECK:
                continue
            if name in checks:
                failures.boolean(f"JSON checks[{name!r}]", checks[name], True)
    else:
        failures.require(False, f"JSON checks: an object of verdicts, got {checks!r}")

    unverifiable = _unverifiable_operands(expected)
    expected_ancillary = not unverifiable
    if isinstance(checks, dict) and ANCILLARY_CHECK in checks:
        failures.boolean(
            f"JSON checks[{ANCILLARY_CHECK!r}]",
            checks[ANCILLARY_CHECK],
            expected_ancillary,
        )

    artifact_checks = document.get("artifact_checks")
    if isinstance(artifact_checks, dict):
        failures.equal(
            "JSON artifact_checks key set",
            sorted(artifact_checks),
            sorted(ARTIFACT_CHECK_NAMES),
        )
        for name in ARTIFACT_CHECK_NAMES:
            if name in artifact_checks:
                failures.boolean(
                    f"JSON artifact_checks[{name!r}]", artifact_checks[name], True
                )
    else:
        failures.require(
            False,
            f"JSON artifact_checks: an object of verdicts, got {artifact_checks!r}",
        )

    ok = document.get("ok")
    failures.require(isinstance(ok, bool), f"JSON ok: a boolean, got {ok!r}")
    if isinstance(checks, dict) and isinstance(artifact_checks, dict):
        structural = all(
            value for name, value in checks.items() if name != ANCILLARY_CHECK
        ) and all(artifact_checks.values())
        failures.boolean("JSON ok", ok, bool(structural))
    _compare_limitations(failures, document, expected)


def _compare_limitations(
    failures: _Failures,
    document: Mapping[str, object],
    expected: tuple[_ExpectedComparison, ...],
) -> None:
    """``limitations`` names **exactly** the identity-unverifiable operands the recomputation holds.

    §10 records a limitation exactly when some operand's recomputed §6 context is
    ``repeat-context-identity-unverifiable``. The operand set the published text names must equal
    that recomputed set — no operand dropped, none invented, and no limitation at all when the
    recomputation proves every context.
    """
    limitations = document.get("limitations")
    if not isinstance(limitations, list) or not all(
        isinstance(item, str) and item for item in limitations
    ):
        failures.require(
            False, f"JSON limitations: a list of non-empty strings, got {limitations!r}"
        )
        return
    unverifiable = list(_unverifiable_operands(expected))
    text = " ".join(limitations)
    named = sorted(code for code in _ALL_OPERANDS if code in text)
    failures.equal("JSON limitations operand set", named, unverifiable)
    failures.require(
        bool(limitations) == bool(unverifiable),
        f"JSON limitations: {len(limitations)} entr(ies) for "
        f"{len(unverifiable)} identity-unverifiable operand(s)",
    )


def _unverifiable_operands(
    expected: tuple[_ExpectedComparison, ...],
) -> tuple[str, ...]:
    """The operands whose recomputed repeat context is ``repeat-context-identity-unverifiable``."""
    operands: set[str] = set()
    for item in expected:
        for context in (*item.context1["repeats"], *item.context2["repeats"]):  # type: ignore[union-attr]
            if context["state"] == REPEAT_STATE_UNVERIFIABLE:
                operands.add(str(context["operand"]))
    return tuple(sorted(operands))


def _compare_provenance(
    failures: _Failures, document: Mapping[str, object], sides: Mapping[str, _Side]
) -> None:
    """The two sides' §5.4 provenance records, against the independently re-verified chains."""
    provenance = document.get("provenance")
    if not isinstance(provenance, dict) or sorted(provenance) != sorted((LIVE1, LIVE2)):
        failures.require(
            False,
            f"JSON provenance: an object keyed {[LIVE1, LIVE2]}, got {provenance!r}",
        )
        return
    for sitting in (LIVE1, LIVE2):
        row = provenance.get(sitting)
        if not isinstance(row, dict):
            failures.require(
                False, f"JSON provenance[{sitting!r}]: an object, got {row!r}"
            )
            continue
        want = sides[sitting].provenance()
        failures.equal(
            f"JSON provenance[{sitting!r}] key set",
            sorted(row),
            sorted(SIDE_PROVENANCE_FIELDS),
        )
        for key in sorted(SIDE_PROVENANCE_FIELDS):
            if key in ("checks_ok", "artifact_checks_ok"):
                failures.boolean(
                    f"JSON provenance[{sitting!r}].{key}", row.get(key), want[key]
                )
            else:
                failures.equal(
                    f"JSON provenance[{sitting!r}].{key}", row.get(key), want[key]
                )


def _compare_comparisons(
    failures: _Failures,
    document: Mapping[str, object],
    expected: tuple[_ExpectedComparison, ...],
    sides: Mapping[str, _Side],
) -> None:
    """The 72 comparison records: frozen order, closed keys, recomputed identity and context."""
    comparisons = document.get("comparisons")
    if not isinstance(comparisons, list):
        failures.require(
            False, f"JSON comparisons: a list of records, got {comparisons!r}"
        )
        return
    wanted = [item.effect_id for item in expected]
    found = [
        record.get("effect_id") if isinstance(record, dict) else None
        for record in comparisons
    ]
    if found != wanted:
        failures.require(
            False,
            f"JSON comparisons: the {len(found)} record(s) are not the §2 frozen order of "
            f"{len(wanted)}; the first disagreement is at position "
            f"{next((i for i, (a, b) in enumerate(zip(found, wanted)) if a != b), min(len(found), len(wanted)))}",
        )
        return
    for record, item in zip(comparisons, expected, strict=True):
        assert isinstance(record, dict)
        if sorted(record) != sorted(COMPARISON_FIELDS):
            failures.require(
                False,
                f"JSON comparisons[{item.effect_id!r}]: the key set is closed; it carries "
                f"{sorted(set(record) - COMPARISON_FIELDS)} unexpectedly and is missing "
                f"{sorted(COMPARISON_FIELDS - set(record))}",
            )
            continue
        for key, value in item.record.items():
            failures.equal(
                f"JSON comparisons[{item.effect_id!r}].{key}", record.get(key), value
            )
        _compare_context(
            failures,
            item.effect_id,
            LIVE1,
            record.get("context1"),
            item.context1,
            sides[LIVE1],
        )
        _compare_context(
            failures,
            item.effect_id,
            LIVE2,
            record.get("context2"),
            item.context2,
            sides[LIVE2],
        )


def _compare_context(
    failures: _Failures,
    effect_id: str,
    sitting: str,
    found: object,
    expected: Mapping[str, object],
    side: _Side,
) -> None:
    """One side's §5.4 context quotation: closed keys, the recomputed record and the CSV cell."""
    where = f"JSON comparisons[{effect_id!r}].context{1 if sitting == LIVE1 else 2}"
    if not isinstance(found, dict):
        failures.require(False, f"{where}: an object, got {found!r}")
        return
    if sorted(found) != sorted(SIDE_CONTEXT_FIELDS):
        failures.require(
            False,
            f"{where}: the key set is closed; it carries "
            f"{sorted(set(found) - SIDE_CONTEXT_FIELDS)} unexpectedly and is missing "
            f"{sorted(SIDE_CONTEXT_FIELDS - set(found))}",
        )
        return
    for key in sorted(SIDE_CONTEXT_FIELDS):
        failures.equal(f"{where}.{key}", found.get(key), expected[key])
    # §12.3: every quoted scalar must equal the side's own committed CSV cell exactly.
    cells = side.csv_rows[effect_id]
    for column in _CONTEXT_CSV_COLUMNS:
        failures.equal(
            f"{where} quotation of the {side.stem} CSV cell {column!r}",
            _csv_cell_as_json(found.get(column)),
            _csv_cell_as_json(_parse_cell(cells.get(column, ""), column)),
        )
    _compare_context_repeats(failures, where, found.get("repeats"), expected["repeats"])


#: The side-context scalars that are quotations of the side's own CSV cells (§5.4).
_CONTEXT_CSV_COLUMNS: tuple[str, ...] = (
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
)

_INT_CONTEXT_COLUMNS = frozenset(
    (
        "defined_count",
        "undefined_alignment_count",
        "undefined_operand_count",
        "knot_count",
    )
)


def _parse_cell(text: str, column: str) -> object:
    """One side CSV cell as the JSON value it is quoted to: ``None``, an int or a float."""
    if text == "":
        return None
    if column in _INT_CONTEXT_COLUMNS:
        return int(text)
    return float(text)


def _csv_cell_as_json(value: object) -> object:
    """Normalize a context value and a CSV cell to one comparable form."""
    return value


def _compare_context_repeats(
    failures: _Failures, where: str, found: object, expected: object
) -> None:
    """The repeat contexts of one side, key for key, with the state-conditional range keys."""
    if not isinstance(found, list) or not isinstance(expected, list):
        failures.require(False, f"{where}.repeats: a list of contexts, got {found!r}")
        return
    if len(found) != len(expected):
        failures.require(
            False,
            f"{where}.repeats: {len(found)} context(s) for the recomputation's {len(expected)}",
        )
        return
    for index, (item, want) in enumerate(zip(found, expected, strict=True)):
        key = f"{where}.repeats[{index}]"
        if not isinstance(item, dict):
            failures.require(False, f"{key}: an object, got {item!r}")
            continue
        selected = want["state"] == REPEAT_STATE_SELECTED
        allowed = REPEAT_FIELDS | (
            frozenset(REPEAT_RANGE_KEYS) if selected else frozenset()
        )
        if sorted(item) != sorted(allowed):
            failures.require(
                False,
                f"{key}: the key set is closed and its range keys are state-conditional "
                f"(state={want['state']!r}); it carries "
                f"{sorted(set(item) - allowed)} unexpectedly and is missing "
                f"{sorted(allowed - set(item))}",
            )
            continue
        for field in sorted(allowed):
            if field == "identity_verified":
                failures.boolean(f"{key}.{field}", item.get(field), want[field])
            else:
                failures.equal(f"{key}.{field}", item.get(field), want[field])
        _compare_repeat_members(failures, key, item.get("members"), want["members"])


def _compare_repeat_members(
    failures: _Failures, where: str, found: object, expected: object
) -> None:
    """One repeat context's quoted members (label/order/job/value/state/reason)."""
    if not isinstance(found, list) or not isinstance(expected, list):
        failures.require(False, f"{where}.members: a list of members, got {found!r}")
        return
    if len(found) != len(expected):
        failures.require(
            False,
            f"{where}.members: {len(found)} member(s) for the recomputation's {len(expected)}",
        )
        return
    for index, (member, want) in enumerate(zip(found, expected, strict=True)):
        if not isinstance(member, dict) or sorted(member) != sorted(
            REPEAT_MEMBER_FIELDS
        ):
            failures.require(
                False,
                f"{where}.members[{index}]: exactly {sorted(REPEAT_MEMBER_FIELDS)}, got "
                f"{sorted(member) if isinstance(member, dict) else member!r}",
            )
            continue
        for field in sorted(REPEAT_MEMBER_FIELDS):
            failures.equal(
                f"{where}.members[{index}].{field}", member.get(field), want[field]
            )


def _compare_members(
    failures: _Failures,
    document: Mapping[str, object],
    expected: tuple[_ExpectedComparison, ...],
) -> None:
    """``npz_members`` equals the closed member set of the comparable comparisons (§5.5)."""
    members = document.get("npz_members")
    if not isinstance(members, list):
        failures.require(False, f"JSON npz_members: a list of names, got {members!r}")
        return
    wanted = sorted(
        name
        for item in expected
        if item.arrays is not None
        for name in cross_member_names(item.effect_id)
    )
    failures.equal("JSON npz_members", members, wanted)
    duplicates = sorted({name for name in members if members.count(name) > 1})
    failures.require(
        not duplicates,
        f"JSON npz_members: the name(s) {duplicates} appear more than once",
    )


def _compare_nonvalue_rows(
    failures: _Failures,
    document: Mapping[str, object],
    expected: tuple[_ExpectedComparison, ...],
) -> None:
    """The typed-empty rows and their counts, in the fixed §5.6 order."""
    rows = document.get("nonvalue_rows")
    if not isinstance(rows, list):
        failures.require(False, f"JSON nonvalue_rows: a list of rows, got {rows!r}")
        return
    wanted = [dict(row) for item in expected for row in item.nonvalue]
    found = []
    for row in rows:
        if not isinstance(row, dict):
            failures.require(
                False, f"JSON nonvalue_rows: a row is an object, got {row!r}"
            )
            continue
        if row.get("kind") not in NONVALUE_KINDS:
            failures.require(
                False,
                f"JSON nonvalue_rows: the kind {row.get('kind')!r} is not one of "
                f"{list(NONVALUE_KINDS)}",
            )
            continue
        found.append(row)
    failures.equal("JSON nonvalue_rows", found, wanted)
    # A non-comparable comparison contributes no non-value row (§5.6).
    nonvalue_ids = {str(row.get("effect_id")) for row in found}
    for item in expected:
        if item.arrays is None and item.effect_id in nonvalue_ids:
            failures.require(
                False,
                f"JSON nonvalue_rows: the not comparable comparison {item.effect_id!r} carries "
                "a non-value row",
            )
    _compare_nonvalue_counts(failures, document, wanted)


def _compare_nonvalue_counts(
    failures: _Failures,
    document: Mapping[str, object],
    wanted: Sequence[Mapping[str, object]],
) -> None:
    """``nonvalue_counts``: the totals by ``(state, kind)`` (§5.6)."""
    counts = document.get("nonvalue_counts")
    if not isinstance(counts, dict):
        failures.require(
            False, f"JSON nonvalue_counts: an object of totals, got {counts!r}"
        )
        return
    recomputed: dict[str, dict[str, int]] = {}
    for row in wanted:
        by_kind = recomputed.setdefault(str(row["state"]), {})
        by_kind[str(row["kind"])] = by_kind.get(str(row["kind"]), 0) + 1
    recomputed = {
        state: dict(sorted(by_kind.items()))
        for state, by_kind in sorted(recomputed.items())
    }
    failures.equal("JSON nonvalue_counts", counts, recomputed)


def _compare_artifacts_object(
    failures: _Failures, document: Mapping[str, object]
) -> None:
    """The recorded NPZ/CSV digests are ``sha256:`` tokens naming the sibling files (§5.7)."""
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        failures.require(False, f"JSON artifacts: an object, got {artifacts!r}")
        return
    failures.equal("JSON artifacts key set", sorted(artifacts), ["csv", "npz"])
    for kind, name in (("npz", f"{STEM}.npz"), ("csv", f"{STEM}.csv")):
        entry = artifacts.get(kind)
        if not isinstance(entry, dict) or sorted(entry) != ["file", "sha256"]:
            failures.require(
                False, f"JSON artifacts[{kind!r}]: a file/sha256 pair, got {entry!r}"
            )
            continue
        failures.equal(f"JSON artifacts[{kind!r}].file", entry.get("file"), name)
        failures.require(
            isinstance(entry.get("sha256"), str)
            and entry["sha256"].startswith(DIGEST_PREFIX),
            f"JSON artifacts[{kind!r}].sha256: a {DIGEST_PREFIX} token, got "
            f"{entry.get('sha256')!r}",
        )


# ── the entry point ────────────────────────────────────────────────────


def verify_cross_artifacts(
    artifact_dir: Path,
    source_dir: Path = SOURCE_DIR,
    *,
    stem: str = STEM,
) -> CrossVerification:
    """Verify the cross-sitting artifact set against an independent recomputation (§12).

    Args:
        artifact_dir: the directory the four cross files live in.
        source_dir: the directory the two committed source quartets are read from; defaults to
            the plan's publish root, anchored at the repository root.
        stem: the cross artifact stem (§1).

    Returns:
        :class:`CrossVerification` — the checks that held, the digests read and the counts of
        the compared rows.

    Raises:
        CrossVerificationError: for a missing or unreadable file, a broken source digest chain,
            a recomputation that refuses, or any disagreement between the staged bytes and the
            independent recomputation. All disagreements are listed.
    """
    directory = Path(artifact_dir)
    source = _anchor(source_dir)
    cross_paths = {
        kind: directory / f"{stem}{extension}"
        for kind, extension in _SOURCE_EXTENSIONS.items()
    }
    for kind, path in cross_paths.items():
        if not path.is_file():
            raise CrossVerificationError(
                f"the published cross {kind} file {path} is missing; a verification compares "
                "all four files, and an absent one is a refusal"
            )

    sides = {sitting: _load_side(source, sitting) for sitting in (LIVE1, LIVE2)}
    failures = _Failures(str(directory))
    try:
        expected = _expected_comparisons(sides, failures)
    except CrossVerificationError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise CrossVerificationError(
            f"the independent recomputation is not itself a valid comparison set: {exc}"
        ) from exc
    if len(expected) != 72 or len({item.effect_id for item in expected}) != 72:
        raise CrossVerificationError(
            "the recomputation did not produce the frozen 72 unique comparison keys"
        )

    raw_npz = _read_bytes(cross_paths["npz"], "cross container")
    expected_shapes: dict[str, int | None] = {
        item.effect_id: (
            None if item.arrays is None else item.arrays.comparison_knot_count
        )
        for item in expected
    }
    records: tuple[CrossArrays, ...] = ()
    try:
        records = decode_cross_npz(raw_npz, expected=expected_shapes)
    except (CrossNpzContainerError, CrossNpzSchemaError) as exc:
        failures.require(
            False,
            f"{cross_paths['npz'].name} is not a canonical §3/§4 container: {exc}",
        )
    if records:
        _compare_npz(failures, expected, records)

    rows = _read_cross_csv(cross_paths["csv"], failures)
    _compare_csv(failures, expected, rows)

    json_bytes = _read_bytes(cross_paths["json"], "cross JSON")
    _, document = _read_cross_json(cross_paths["json"], failures)
    digests: dict[str, str] = {}
    if isinstance(document, dict):
        _compare_json(
            failures,
            expected,
            sides,
            document,
            json_bytes.decode("utf-8", errors="replace"),
        )
        digests = _verify_digests(
            failures,
            document=document,
            raw_npz=raw_npz,
            csv_bytes=cross_paths["csv"].read_bytes(),
            json_bytes=json_bytes,
            readme_bytes=cross_paths["readme"].read_bytes(),
            sides=sides,
        )

    if failures.items:
        listed = "\n".join(f"  - {item}" for item in failures.items)
        raise CrossVerificationError(
            f"the cross-sitting artifacts disagree with the independent recomputation in "
            f"{len(failures.items)} place(s):\n{listed}"
        )
    return CrossVerification(
        artifact_dir=directory,
        source_dir=source,
        comparison=ORIENTATION,
        comparison_count=len(expected),
        npz_member_count=len(records) * len(CROSS_MEMBER_SUFFIXES),
        checks={
            "source_quartet_chains_verified": True,
            "npz_arrays_match_the_recomputation": True,
            "csv_scalars_match_the_recomputation": True,
            "json_records_and_context_match_the_recomputation": True,
            "nonvalue_rows_match_the_recomputation": True,
            "structural_invariants_hold": True,
            "digests_match_the_staged_bytes": True,
        },
        digests=digests,
    )


def _verify_digests(
    failures: _Failures,
    *,
    document: Mapping[str, object],
    raw_npz: bytes,
    csv_bytes: bytes,
    json_bytes: bytes,
    readme_bytes: bytes,
    sides: Mapping[str, _Side],
) -> dict[str, str]:
    """Check the digests last: NPZ + CSV → JSON → README (§12.5)."""
    npz_digest = _file_digest(raw_npz)
    csv_digest = _canonical_digest(csv_bytes)
    json_digest = _canonical_digest(json_bytes)
    artifacts = document.get("artifacts")
    if isinstance(artifacts, dict):
        npz_entry = artifacts.get("npz")
        csv_entry = artifacts.get("csv")
        if isinstance(npz_entry, dict):
            failures.equal(
                "cross JSON artifacts.npz.sha256", npz_entry.get("sha256"), npz_digest
            )
        if isinstance(csv_entry, dict):
            failures.equal(
                "cross JSON artifacts.csv.sha256", csv_entry.get("sha256"), csv_digest
            )
    readme = readme_bytes.decode("utf-8", errors="replace")
    failures.require(
        json_digest in readme,
        f"the cross README does not bind the cross JSON's canonical-LF digest {json_digest}",
    )
    failures.require(
        f"{STEM}.npz" in readme,
        f"the cross README does not name {STEM}.npz",
    )
    failures.require(
        f"{STEM}.csv" in readme,
        f"the cross README does not name {STEM}.csv",
    )
    # Every digest token the README states must be one the verifier recomputed itself: the three
    # cross-digest tokens, or one of the two source quartets' own three digests (§7 binds the two
    # source chains in the README as well). A wrong or foreign token is a broken binding.
    known = {npz_digest, csv_digest, json_digest}
    for side in sides.values():
        expected = side.provenance()
        for key in ("json_sha256", "npz_sha256", "csv_sha256"):
            token = str(expected[key])
            known.add(token)
            failures.require(
                token in readme,
                f"the cross README does not bind the {side.sitting} source digest {key} "
                f"{token}",
            )
    stated = sorted(set(_DIGEST_TOKEN.findall(readme)))
    unknown = [token for token in stated if token not in known]
    failures.require(
        not unknown,
        f"the cross README states the digest token(s) {unknown}, which are not digests of the "
        "staged bytes or of the two source quartets",
    )
    return {"npz": npz_digest, "csv": csv_digest, "json": json_digest}
