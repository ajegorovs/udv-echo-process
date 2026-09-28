"""SA5 cross-sitting input/binding layer — the frozen quartets, orientation and exact match.

This module is the **input** of the between-sitting slice and nothing else: it turns the two
published quartets into digest-verified, read-only inputs, fixes the orientation, states ``grid``
as a function of the contrast, names the frozen 72 keys in their frozen order, and resolves a key
strictly — the exact equality of a published effect's ``(view, metric, contrast)`` triple *and* of
its resolved ``effect_id`` (never parsed).

What it refuses, and by which rule
----------------------------------
A side outside the two reproducibility sittings, a missing/unreadable file, a broken digest chain
(README ↛ JSON, JSON ↛ NPZ/CSV), a side that is not ``ok`` or whose own checks do not re-assert
true, a container the codec refuses, a duplicated effect id, and any disagreement between the
container/CSV effect set and the document's. A broken chain is refused, never repaired.

What it never does
------------------
It performs no comparison arithmetic and re-derives no within-sitting value: everything here is
read from the digest-bound bytes. It does not know the §5 quantities, the §6 repeat context or the
run's typed records — those live above it — and it never imports them back.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from udv_echo_process.analysis._floor_documents import DIGEST_PREFIX
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_sa5_bindings import CONTRASTS, CORNERS
from udv_echo_process.analysis.sparse_sa5_cross_models import (
    SideProvenance,
    SparseSa5CrossSittingError,
    effect_id,
)
from udv_echo_process.analysis.sparse_sa5_effects import ENDPOINTS, INTERACTION_NAME
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.analysis.sparse_sa5_npz import EffectArrays, decode_effect_npz

__all__ = [
    "CORNER_GRID",
    "EMISSIONS_GRID",
    "LIVE1",
    "LIVE2",
    "ORIENTATION",
    "REPORT_DIR",
    "SCHEMA_ID",
    "SITTING_NAMES",
    "FrozenQuartet",
    "comparison_keys",
    "effect_id",
    "expected_grid",
    "load_published_quartets",
    "load_quartet",
    "resolve_effect",
]

SCHEMA_ID = "sa5-within-sitting-effects/v1"
CORNER_GRID = "corner_knots"
EMISSIONS_GRID = "emissions_knots"
REPORT_DIR = Path("reports/sparse-signal")

LIVE1, LIVE2 = "live-1", "live-2"
SITTING_NAMES: tuple[str, str] = (LIVE1, LIVE2)
ORIENTATION = "live2 - live1"
_LABEL_STEM: Mapping[str, str] = {
    LIVE1: "sa5-live-1-effects",
    LIVE2: "sa5-live-2-effects",
}
_PASS_NAME: Mapping[str, str] = {
    LIVE1: "sparse-mixer-live-1",
    LIVE2: "sparse-mixer-live-2",
}

_CORNER_LABELS = frozenset(row.label for row in CORNERS)
#: ``corner_knots``/``emissions_knots`` as a *function of the contrast* (§2), precomputed.
_GRID_BY_CONTRAST: Mapping[str, str] = {
    **{
        spec.name: (
            CORNER_GRID
            if set(spec.high.members) | set(spec.low.members) <= _CORNER_LABELS
            else EMISSIONS_GRID
        )
        for spec in CONTRASTS
    },
    INTERACTION_NAME: CORNER_GRID,
}


def _fail(message: str) -> SparseSa5CrossSittingError:
    """One refusal message, as this slice's error."""
    return SparseSa5CrossSittingError(message)


def expected_grid(contrast: str) -> str:
    """``corner_knots``/``emissions_knots`` — a function of the contrast, not a choice (§2)."""
    try:
        return _GRID_BY_CONTRAST[contrast]
    except KeyError as exc:
        raise SparseSa5CrossSittingError(
            f"{contrast!r} is not one of the frozen contrasts or the interaction"
        ) from exc


def _canonical_digest(data: bytes) -> str:
    """``sha256:`` over canonical-LF bytes; containers hash their exact bytes (§5.7)."""
    return DIGEST_PREFIX + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenQuartet:
    """One side's published quartet, digest-verified and read into arrays and scalars.

    ``document`` is the parsed JSON, ``arrays`` the decoded NPZ profiles by ``effect_id``,
    ``csv_rows`` the parsed scalar rows by ``effect_id`` and ``digests`` the three recomputed
    ``sha256:`` tokens. Everything here is read-only and never re-measured.
    """

    sitting: str
    pass_name: str
    plan: str
    plan_fingerprint: str
    stem: str
    digests: Mapping[str, str]
    document: Mapping[str, object]
    arrays: Mapping[str, EffectArrays]
    csv_rows: Mapping[str, Mapping[str, str]]
    by_id: Mapping[str, Mapping[str, object]]

    def provenance(self) -> SideProvenance:
        """The §10 per-side provenance row this quartet carries."""
        checks = self.document["checks"]
        artifacts = self.document["artifact_checks"]
        return SideProvenance(
            sitting=self.sitting,
            pass_name=self.pass_name,
            plan=self.plan,
            plan_fingerprint=self.plan_fingerprint,
            stem=self.stem,
            json_sha256=self.digests["json"],
            npz_sha256=self.digests["npz"],
            csv_sha256=self.digests["csv"],
            checks_ok=bool(all(checks.values())),  # type: ignore[arg-type]
            artifact_checks_ok=bool(all(artifacts.values())),  # type: ignore[arg-type]
        )


def _read_bytes(path: Path, where: str) -> bytes:
    """One published file's exact bytes, or a refusal naming it."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _fail(
            f"cannot read the published {where} {path}: {exc}; the comparison binds the frozen "
            "quartet by its own bytes"
        ) from exc


def _parse_csv(data: bytes) -> Mapping[str, Mapping[str, str]]:
    """The published CSV parsed by effect id, refusing a header or row drift."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _fail(
            f"the published CSV is not UTF-8 ({exc}); §6 fixes it as UTF-8"
        ) from exc
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise _fail("the published CSV carries no header row")
    header = tuple(rows[0])
    if "effect_id" not in header:
        raise _fail(f"the published CSV header {header} carries no effect_id key")
    parsed: dict[str, Mapping[str, str]] = {}
    for row in rows[1:]:
        if len(row) != len(header):
            raise _fail(
                f"a published CSV row carries {len(row)} cell(s) for {len(header)} columns"
            )
        cells = dict(zip(header, row, strict=True))
        if cells["effect_id"] in parsed:
            raise _fail(
                f"the published CSV carries the effect id {cells['effect_id']!r} twice"
            )
        parsed[cells["effect_id"]] = cells
    return parsed


def load_quartet(directory: Path, sitting: str) -> FrozenQuartet:
    """Read one published side and verify its whole digest chain, or refuse by name.

    Raises:
        SparseSa5CrossSittingError: for a wrong name, a missing file, a broken digest chain
            (README ↛ JSON, JSON ↛ NPZ/CSV), a side not ``ok``/checked, or a refused container.
    """
    if sitting not in SITTING_NAMES:
        raise _fail(
            f"{sitting!r} is not one of the two reproducibility sittings {SITTING_NAMES}; a "
            "third sitting, a campaign or a path is never bound as an input quartet"
        )
    root = Path(directory)
    stem = _LABEL_STEM[sitting]
    json_bytes = _read_bytes(root / f"{stem}.json", "JSON")
    npz_bytes = _read_bytes(root / f"{stem}.npz", "container")
    csv_bytes = _read_bytes(root / f"{stem}.csv", "table")
    readme = _read_bytes(root / f"{stem}.README.md", "README").decode("utf-8")

    document = json.loads(json_bytes.decode("utf-8"))
    if not isinstance(document, dict):
        raise _fail(f"{stem}.json is not a JSON object")
    if document.get("schema") != SCHEMA_ID:
        raise _fail(
            f"{stem}.json names the schema {document.get('schema')!r}, not {SCHEMA_ID!r}"
        )
    if document.get("sitting") != _PASS_NAME[sitting]:
        raise _fail(
            f"{stem}.json names the sitting {document.get('sitting')!r}, not "
            f"{_PASS_NAME[sitting]!r}"
        )
    digests = {
        "json": _canonical_digest(json_bytes),
        "npz": DIGEST_PREFIX + hashlib.sha256(npz_bytes).hexdigest(),
        "csv": _canonical_digest(csv_bytes),
    }
    if digests["json"] not in readme:
        raise _fail(
            f"{stem}: the README does not bind the document's canonical-LF digest "
            f"{digests['json']}, so the chain is broken"
        )
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, dict):
        raise _fail(f"{stem}.json publishes no artifacts object")
    for kind, name in (("npz", f"{stem}.npz"), ("csv", f"{stem}.csv")):
        entry = artifacts.get(kind)
        if not isinstance(entry, dict) or entry.get("file") != name:
            raise _fail(f"{stem}.json does not bind the {kind} file {name!r}")
        if entry.get("sha256") != digests[kind]:
            raise _fail(
                f"{stem}: the JSON records {entry.get('sha256')!r} for {name}, the published "
                f"bytes hash to {digests[kind]!r}: the quartet is refused, not repaired"
            )
        if name not in readme:
            raise _fail(
                f"{stem}: the README does not name {name}, so the chain is incomplete"
            )
    if document.get("ok") is not True:
        raise _fail(f"{stem}.json is not ok, so the side is not a usable input")
    for field in ("checks", "artifact_checks"):
        verdicts = document.get(field)
        if not isinstance(verdicts, dict) or not all(verdicts.values()):
            raise _fail(
                f"{stem}.json's own {field} do not all hold; an input is not usable until its "
                "own checks re-assert true"
            )

    effects = document.get("effects")
    if not isinstance(effects, list):
        raise _fail(f"{stem}.json publishes no effects list")
    shapes: dict[str, tuple[int, int]] = {}
    by_id: dict[str, Mapping[str, object]] = {}
    for record in effects:
        if not isinstance(record, dict):
            raise _fail(f"{stem}.json carries a non-object effect row")
        key = str(record.get("effect_id"))
        if key in by_id:
            raise _fail(f"{stem}.json carries the effect id {key!r} twice")
        by_id[key] = record
        shapes[key] = (int(record["knot_count"]), int(record["participant_count"]))
    arrays = {r.effect_id: r for r in decode_effect_npz(npz_bytes, expected=shapes)}
    if set(arrays) != set(by_id):
        raise _fail(f"{stem}: the container's effect set is not the document's")
    csv_rows = _parse_csv(csv_bytes)
    if set(csv_rows) != set(by_id):
        raise _fail(f"{stem}: the CSV's effect set is not the document's")
    return FrozenQuartet(
        sitting=sitting,
        pass_name=_PASS_NAME[sitting],
        plan=str(document.get("plan", "")),
        plan_fingerprint=str(document.get("plan_fingerprint", "")),
        stem=stem,
        digests=digests,
        document=document,
        arrays=arrays,
        csv_rows=csv_rows,
        by_id=by_id,
    )


def load_published_quartets(
    report_dir: Path = REPORT_DIR,
) -> tuple[FrozenQuartet, FrozenQuartet]:
    """Load and digest-verify both published quartets, ``(live-1, live-2)``."""
    return load_quartet(report_dir, LIVE1), load_quartet(report_dir, LIVE2)


def resolve_effect(
    side: FrozenQuartet, metric: MetricName, view: SparseView, contrast: str
) -> Mapping[str, object] | None:
    """The one published record for a key, or ``None`` when the side does not carry it.

    The triple is resolved through the side's own published ``effects`` rows and never by parsing
    the ``effect_id`` string; a resolution that disagrees with the joined id is a refusal.
    """
    wanted = effect_id(view, metric, contrast)
    matches = [
        record
        for record in side.by_id.values()
        if record.get("view") == view.value
        and record.get("metric") == metric.value
        and record.get("contrast") == contrast
    ]
    if len(matches) > 1:
        raise _fail(
            f"{side.stem}: the key {wanted!r} resolves to {len(matches)} records"
        )
    if not matches:
        return None
    if matches[0].get("effect_id") != wanted:
        raise _fail(
            f"{side.stem}: the record for {wanted!r} carries the effect id "
            f"{matches[0].get('effect_id')!r}, which disagrees with the resolved triple"
        )
    return matches[0]


def comparison_keys() -> tuple[tuple[MetricName, SparseView, str], ...]:
    """The 72 keys in the frozen order: endpoint, then contrast, then interaction."""
    keys: list[tuple[MetricName, SparseView, str]] = []
    for metric, view in ENDPOINTS:
        keys.extend((metric, view, spec.name) for spec in CONTRASTS)
        keys.append((metric, view, INTERACTION_NAME))
    return tuple(keys)
