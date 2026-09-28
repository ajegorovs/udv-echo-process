"""Adversarial tests for SA5's cross-sitting report writer.

The contract under test is ``docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md``: the
four artifacts of §1, the frozen 72-comparison order and the effect id (§2), the canonical NPZ
container (§3-§4), the closed JSON field set, the typed states, the non-value rows, the
conditional repeat-context range and the digest convention (§5), the 30-column scalar CSV (§6),
the README's digest binding (§7), the boolean/signed-zero rules (§8-§9), the structural-vs-
ancillary ``ok`` rule (§10) and the publication/refusal gate (§11).

What the tests pin:

- **the real committed quartets** are compared and serialized without writing a byte into the
  repository: the frozen 72 rows, the 30 closed CSV columns, the 280-member container, the
  closed JSON key sets, the two source chains, the digest chain and byte-determinism;
- **doctored typed quartets** (the real ones, changed at the codec seam) drive the signed-zero
  rule, the three non-value kinds, a wholly-undefined pair, the conditional repeat-context
  range and the source-byte-unchanged refusal;
- the **refusal gate**: a wrong orientation, a ``not resolvable`` row, a false artifact check,
  a tampered source quartet, and the destination/ownership/lock/stage refusals.

No committed artifact is written: every publication lands in ``tmp_path``. The writer module is
imported whole; no independent verifier is imported.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis import sparse_sa5_cross_report as w
from udv_echo_process.analysis import sparse_sa5_cross_sitting as x
from udv_echo_process.analysis.sparse_sa5_cross_input import (
    LIVE1,
    LIVE2,
    ORIENTATION,
    SITTING_NAMES,
    comparison_keys,
)
from udv_echo_process.analysis.sparse_sa5_cross_models import ComparisonState
from udv_echo_process.analysis.sparse_sa5_cross_npz import (
    CROSS_MEMBER_SUFFIXES,
    CrossNpzError,
    cross_member_names,
    decode_cross_npz,
)
from udv_echo_process.analysis.sparse_sa5_npz import MEMBER_DTYPES, EffectArrays

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "sparse-signal"
CORNER_KEY = "primary-comparison__mean__pitch_at_burst_4"
CORNER_CONTRAST = "pitch_at_burst_4"
MEAN, PRIMARY = "mean", "primary-comparison"


@pytest.fixture(scope="module")
def published():
    return x.load_published_quartets(REPORT_DIR)


@pytest.fixture(scope="module")
def comparison(published):
    return x.compare_cross_sitting(*published)


@pytest.fixture(scope="module")
def artifacts(comparison):
    return w.build_cross_artifacts(
        comparison,
        source_dir=REPORT_DIR,
        analysis_commit="test-commit",
        generator_revision="test-generator",
    )


def _comparable_keys(comp) -> dict[str, int]:
    return {
        record.effect_id: len(record.knots_mm)
        for record in comp.records
        if record.comparison_state is ComparisonState.COMPARABLE
    }


def _decoded(artifacts):
    document = artifacts.document()
    expected = {
        record["effect_id"]: record["comparison_knot_count"]
        for record in document["comparisons"]
        if record["comparison_knot_count"] is not None
    }
    return {
        record.effect_id: record
        for record in decode_cross_npz(artifacts.npz, expected=expected)
    }


def _csv_rows(artifacts):
    return list(csv.DictReader(io.StringIO(artifacts.csv.decode("utf-8"))))


# ── doctoring the real quartets at the typed seam ──────────────────────


def _arrays(effect_id, knots, effect, defined, state, participant_count=2):
    two, n, d = (participant_count, len(knots)), len(knots), MEMBER_DTYPES
    return EffectArrays(
        effect_id=effect_id,
        knot_count=n,
        participant_count=participant_count,
        knots_mm=np.ascontiguousarray(knots, dtype=d["knots_mm"]),
        effect=np.ascontiguousarray(effect, dtype=d["effect"]),
        defined=np.ascontiguousarray(defined, dtype=d["defined"]),
        state=np.ascontiguousarray(state, dtype=d["state"]),
        participant_gate_index=np.full(two, -1, dtype=d["participant_gate_index"]),
        participant_depth_mm=np.zeros(two, dtype=d["participant_depth_mm"]),
        participant_offset_mm=np.zeros(two, dtype=d["participant_offset_mm"]),
        participant_value=np.zeros(two, dtype=d["participant_value"]),
        participant_defined=np.zeros(two, dtype=d["participant_defined"]),
        participant_state=np.full(two, 6, dtype=d["participant_state"]),
    )


def _doctor(quartet, key, *, arrays=None, support=None):
    by_id = dict(quartet.by_id)
    document = dict(quartet.document)
    changes = {}
    if arrays is not None:
        changes["knot_count"] = arrays[key].knot_count
    if support is not None:
        changes["support_mm"] = list(support)
    by_id[key] = {**by_id[key], **changes}
    document["effects"] = [
        ({**row, **changes} if row["effect_id"] == key else row)
        for row in quartet.document["effects"]
    ]
    replaced = {"arrays": arrays, "by_id": by_id, "document": document}
    return dataclasses.replace(
        quartet, **{k: v for k, v in replaced.items() if v is not None}
    )


def _side(quartet, key, *, knots, effect, defined, state, support):
    arrays = dict(quartet.arrays)
    arrays[key] = _arrays(key, knots, effect, defined, state)
    return _doctor(quartet, key, arrays=arrays, support=support)


def _ones(n):
    return np.ones(n, dtype=np.uint8), np.zeros(n, dtype=np.uint8)


def _doctored(
    published, *, knots, effect1, defined1, state1, effect2, defined2, state2
):
    """A doctored ``(left, right)`` pair over one corner key, spanning its own support."""
    support = (float(np.min(knots)), float(np.max(knots)))
    left, right = published
    left = _side(
        left,
        CORNER_KEY,
        knots=knots,
        effect=effect1,
        defined=defined1,
        state=state1,
        support=support,
    )
    right = _side(
        right,
        CORNER_KEY,
        knots=knots,
        effect=effect2,
        defined=defined2,
        state=state2,
        support=support,
    )
    return left, right


def _corner(comp):
    return comp.record(PRIMARY, MEAN, CORNER_CONTRAST)


# ── the frozen shape and the closed schema ─────────────────────────────


def test_the_comparison_set_is_the_frozen_72_and_the_json_is_closed(artifacts) -> None:
    document = artifacts.document()
    assert document["schema"] == w.SCHEMA_ID == "sa5-cross-sitting/v1"
    assert document["ok"] is True
    assert document["comparison"] == ORIENTATION == "live2 - live1"
    assert (
        (document["sitting1"], document["sitting2"]) == SITTING_NAMES == (LIVE1, LIVE2)
    )
    assert document["analysis_commit"] == "test-commit"
    assert document["generator_revision"] == "test-generator"
    assert set(document) == w.JSON_FIELDS
    assert set(document["checks"]) == set(w.CHECK_ORDER)
    assert set(document["artifact_checks"]) == set(w.ARTIFACT_CHECK_NAMES)
    assert all(document["artifact_checks"].values())
    assert all(
        held
        for name, held in document["checks"].items()
        if name != "repeat_context_identity_fully_established"
    )
    # The ancillary repeat-identity check is published false and does not make `ok` false (§10).
    assert document["checks"]["repeat_context_identity_fully_established"] is False
    assert len(document["comparisons"]) == 72
    assert [c["effect_id"] for c in document["comparisons"]] == [
        x.effect_id(view, metric, contrast)
        for metric, view, contrast in comparison_keys()
    ]
    for record in document["comparisons"]:
        assert set(record) == w.COMPARISON_FIELDS
        assert set(record["context1"]) == w.SIDE_CONTEXT_FIELDS
        assert set(record["context2"]) == w.SIDE_CONTEXT_FIELDS
        assert record["comparison_state"] in (list(x.COMPARISON_STATES)[:2])
    assert set(document["provenance"]) == {LIVE1, LIVE2}
    for provenance in document["provenance"].values():
        assert set(provenance) == w.SIDE_PROVENANCE_FIELDS
    assert document["state_meanings"] == {
        "effect": [{"code": code, "text": text} for code, text in w.STATE_MEANINGS]
    }


def test_the_npz_members_are_the_five_suffixes_of_every_comparable(artifacts) -> None:
    document = artifacts.document()
    comparable = [
        record
        for record in document["comparisons"]
        if record["comparison_knot_count"] is not None
    ]
    expected = sorted(
        name
        for record in comparable
        for name in cross_member_names(record["effect_id"])
    )
    assert len(comparable) == 56
    assert document["npz_members"] == expected
    assert len(expected) == 56 * len(CROSS_MEMBER_SUFFIXES) == 280
    decoded = _decoded(artifacts)
    assert set(decoded) == {record["effect_id"] for record in comparable}
    for record in comparable:
        array = decoded[record["effect_id"]]
        assert array.comparison_knot_count == record["comparison_knot_count"]
        assert array.knots_mm.shape == (record["comparison_knot_count"],)
        assert not array.knots_mm.flags.writeable


def test_every_npz_position_carries_its_mask_state_and_placeholder(artifacts) -> None:
    for array in _decoded(artifacts).values():
        assert np.array_equal(
            array.defined == 1, (array.state1 == 0) & (array.state2 == 0)
        )
        assert np.isfinite(array.knots_mm).all() and np.isfinite(array.difference).all()
        assert np.all(np.diff(array.knots_mm) > 0.0)
        undefined = array.defined != 1
        assert np.all(array.difference[undefined] == 0.0)
        assert not np.any(np.signbit(array.difference[undefined]))


def test_the_csv_is_the_closed_30_columns_and_the_frozen_order(artifacts) -> None:
    rows = list(csv.reader(io.StringIO(artifacts.csv.decode("utf-8"))))
    assert tuple(rows[0]) == w.CSV_COLUMNS
    assert len(rows[0]) == 30
    assert len(rows) == 73
    assert [row[0] for row in rows[1:]] == [
        record["effect_id"] for record in artifacts.document()["comparisons"]
    ]
    text = artifacts.csv.decode("utf-8")
    assert text.endswith("\n") and "\r" not in text


def test_a_csv_float_is_the_17g_rendering_and_an_empty_scalar_is_empty(
    artifacts,
) -> None:
    text_columns = {"effect_id", "view", "metric", "contrast", "units", "grid"}
    for row in _csv_rows(artifacts):
        for column, cell in row.items():
            if column in text_columns or column in w.BOOLEAN_COLUMNS or cell == "":
                continue
            assert cell == format(float(cell), ".17g"), (column, cell)
    # A not-comparable row keeps its known identity cells and leaves every reduction empty.
    empty = [row for row in _csv_rows(artifacts) if row["comparison_knot_count"] == ""]
    assert empty
    for row in empty:
        assert row["effect_id"] and row["view"] and row["metric"] and row["contrast"]
        for column in (
            "defined_count",
            "sign_count",
            "shape_correlation",
            "peak1_value",
            "peak_displacement",
        ):
            assert row[column] == ""
        for column in w.BOOLEAN_COLUMNS:
            assert row[column] == ""


def test_a_csv_boolean_is_the_lowercase_token(artifacts) -> None:
    tokens = set()
    for row in _csv_rows(artifacts):
        for column in w.BOOLEAN_COLUMNS:
            tokens.add(row[column])
    assert tokens <= {"", "true", "false"}
    assert "true" in tokens or "false" in tokens


def test_the_json_never_repeats_a_comparison_reduction(artifacts) -> None:
    body = json.dumps(artifacts.document(), sort_keys=True)
    for column in w.REDUCTION_ONLY_COLUMNS:
        assert f'"{column}":' not in body, column
    assert w._no_comparison_scalar_in_json(body) is True
    assert w._no_comparison_scalar_in_json('{"sign_count":1}') is False


def test_the_json_is_strict_and_lf_terminated(artifacts) -> None:
    text = artifacts.json.decode("utf-8")
    assert "\r" not in text
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert (
        text
        == json.dumps(
            json.loads(text),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    assert "NaN" not in text and "Infinity" not in text


def test_the_digest_chain_binds_readme_to_json_to_npz_and_csv(artifacts) -> None:
    document = artifacts.document()
    npz_digest = "sha256:" + hashlib.sha256(artifacts.npz).hexdigest()
    csv_digest = (
        "sha256:" + hashlib.sha256(artifacts.csv.replace(b"\r\n", b"\n")).hexdigest()
    )
    json_digest = (
        "sha256:" + hashlib.sha256(artifacts.json.replace(b"\r\n", b"\n")).hexdigest()
    )
    assert document["artifacts"]["npz"] == {
        "file": artifacts.npz_name,
        "sha256": npz_digest,
    }
    assert document["artifacts"]["csv"] == {
        "file": artifacts.csv_name,
        "sha256": csv_digest,
    }
    readme = artifacts.readme.decode("utf-8")
    assert json_digest in readme and npz_digest in readme and csv_digest in readme
    # A file never carries its own digest.
    assert json_digest not in artifacts.json.decode("utf-8")
    assert artifacts.npz[:2] == b"PK"


def test_the_npz_digest_is_the_exact_bytes_never_crlf_normalised(artifacts) -> None:
    assert w._file_digest(artifacts.npz) == (
        "sha256:" + hashlib.sha256(artifacts.npz).hexdigest()
    )
    for payload in (artifacts.csv, artifacts.json):
        assert w._canonical_digest(payload) == (
            "sha256:" + hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest()
        )


def test_the_readme_records_both_source_chains_and_the_orientation(artifacts) -> None:
    readme = artifacts.readme.decode("utf-8")
    document = artifacts.document()
    assert readme.startswith(w.README_TITLE_PREFIX)
    assert "live2 - live1" in readme
    for provenance in document["provenance"].values():
        assert provenance["stem"] in readme
        assert provenance["json_sha256"] in readme
        assert provenance["npz_sha256"] in readme
        assert provenance["csv_sha256"] in readme
    for column in w.CSV_COLUMNS:
        assert f"`{column}`" in readme
    for suffix in CROSS_MEMBER_SUFFIXES:
        assert f"__{suffix}.npy" in readme
    assert "trapezoidal" in readme
    assert "repeat-context-identity-unverifiable" in readme
    assert "deferred-pending-review" in readme
    for item in w.NO_GO_LIST:
        assert item in readme
    assert readme.endswith("\n") and readme.count(w.README_TITLE_PREFIX) == 1


def test_the_document_publishes_the_runnable_generator_command(artifacts) -> None:
    assert w.regeneration_command() == (
        "python -m udv_echo_process.analysis.sparse_sa5_cross_report "
        "--report-dir reports/sparse-signal"
    )
    assert "python -c" not in w.regeneration_command()
    assert artifacts.document()["generator_command"] == w.regeneration_command()


def test_the_readme_reproduce_command_writes_outside_the_committed_root(
    artifacts,
) -> None:
    """`generator_command` records the committed root; the README reproduce adds SA5_SCRATCH."""
    readme = artifacts.readme.decode("utf-8")
    assert '--report-dir "$SA5_SCRATCH"' in readme
    assert artifacts.document()["generator_command"] == w.regeneration_command()
    assert w.regeneration_command().endswith("--report-dir reports/sparse-signal")


def test_building_twice_is_byte_identical(comparison) -> None:
    first = w.build_cross_artifacts(comparison, source_dir=REPORT_DIR)
    second = w.build_cross_artifacts(comparison, source_dir=REPORT_DIR)
    assert first.files == second.files


def test_the_artifacts_record_is_a_frozen_value_model(artifacts) -> None:
    assert isinstance(artifacts, w.ValueModel)
    for field in ("npz", "csv", "json", "readme"):
        assert type(getattr(artifacts, field)) is bytes
    with pytest.raises(ValidationError):
        artifacts.stem = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        w.CrossArtifacts(
            stem=artifacts.stem,
            npz=artifacts.npz,
            csv=artifacts.csv,
            json=artifacts.json,
            readme=artifacts.readme,
            unexpected="nope",
        )


def test_the_writer_imports_no_verifier() -> None:
    source = Path(w.__file__).read_text(encoding="utf-8")
    for forbidden in ("verifier", "cross_verify", "verify_sa5"):
        assert forbidden not in source, forbidden
    assert not [name for name in dir(w) if name.startswith("verify")]


# ── adversarial: signed zeros, typed-empties, conditional context ──────


def test_a_negative_zero_difference_is_preserved_and_counts_as_zero(published) -> None:
    knots = np.array([10.0, 12.0])
    defined, state = _ones(2)
    left, right = _doctored(
        published,
        knots=knots,
        effect1=np.array([0.0, 2.0]),
        defined1=defined,
        state1=state,
        effect2=np.array([-0.0, 5.0]),
        defined2=defined,
        state2=state,
    )
    comp = x.compare_cross_sitting(left, right)
    assert _corner(comp).knots[0].difference == 0.0
    assert np.signbit(_corner(comp).knots[0].difference)

    artifacts = w.build_cross_artifacts(
        comp, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    record = _decoded(artifacts)[CORNER_KEY]
    assert float(record.difference[0]) == 0.0 and np.signbit(record.difference[0])
    assert record.defined[0] == 1
    row = next(item for item in _csv_rows(artifacts) if item["effect_id"] == CORNER_KEY)
    assert row["zero_count"] == "1" and row["negative_count"] == "0"


def test_a_refused_shape_and_an_unlocalized_peak_write_the_three_nonvalue_kinds(
    published,
) -> None:
    knots = np.array([10.0, 12.0, 14.0])
    defined, state = _ones(3)
    left, right = _doctored(
        published,
        knots=knots,
        effect1=np.array([5.0, 5.0, 5.0]),
        defined1=defined,
        state1=state,
        effect2=np.array([1.0, 9.0, 2.0]),
        defined2=defined,
        state2=state,
    )
    comp = x.compare_cross_sitting(left, right)
    artifacts = w.build_cross_artifacts(
        comp, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    document = artifacts.document()
    rows = [row for row in document["nonvalue_rows"] if row["effect_id"] == CORNER_KEY]
    assert [row["kind"] for row in rows] == ["shape", "peak", "peak-displacement"]
    assert rows[0]["state"] == w.UNDEFINED_SHAPE and rows[0]["side"] is None
    assert rows[1]["side"] == "live-1"
    assert rows[1]["state"] == rows[1]["reason"]
    assert rows[2]["side"] is None
    for row in rows:
        assert set(row) == {"effect_id", "kind", "side", "state", "reason"}
    counts = document["nonvalue_counts"]
    total = sum(count for by_kind in counts.values() for count in by_kind.values())
    assert total == len(document["nonvalue_rows"])
    assert counts[rows[1]["state"]]["peak"] >= 1
    csv_row = next(
        item for item in _csv_rows(artifacts) if item["effect_id"] == CORNER_KEY
    )
    assert csv_row["shape_correlation"] == ""
    assert csv_row["peak_displacement"] == "" and csv_row["peaks_coincide"] == ""
    assert csv_row["peak_localized1"] == "false"


def test_a_wholly_undefined_pair_has_no_member_no_nonvalue_row_and_a_null_knot_count(
    published,
) -> None:
    knots = np.array([10.0, 12.0, 14.0])
    undefined = np.zeros(3, dtype=np.uint8)
    operand = np.ones(3, dtype=np.uint8)
    left, right = _doctored(
        published,
        knots=knots,
        effect1=np.zeros(3),
        defined1=undefined,
        state1=operand,
        effect2=np.zeros(3),
        defined2=undefined,
        state2=operand,
    )
    comp = x.compare_cross_sitting(left, right)
    record = _corner(comp)
    assert record.comparison_state is ComparisonState.NOT_COMPARABLE
    assert record.comparison_reason == x.REASON_WHOLLY_UNDEFINED

    artifacts = w.build_cross_artifacts(
        comp, source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )
    document = artifacts.document()
    json_record = next(
        item for item in document["comparisons"] if item["effect_id"] == CORNER_KEY
    )
    assert json_record["comparison_knot_count"] is None
    assert json_record["support_mm"] is None and json_record["label_state"] is None
    assert not any(
        name.startswith(f"{CORNER_KEY}__") for name in document["npz_members"]
    )
    assert CORNER_KEY not in _decoded(artifacts)
    assert not [
        row for row in document["nonvalue_rows"] if row["effect_id"] == CORNER_KEY
    ]


def test_the_repeat_context_range_keys_are_conditional(artifacts) -> None:
    document = artifacts.document()
    by_operand = {}
    for record in document["comparisons"]:
        if record["contrast"] != "E8_minus_E20" or record["metric"] != "mean":
            continue
        for side in ("context1", "context2"):
            for context in record[side]["repeats"]:
                by_operand.setdefault(context["operand"], []).append(context)
    for contexts in by_operand.values():
        for context in contexts:
            present = [key for key in w.REPEAT_RANGE_KEYS if key in context]
            if context["state"] == "selected":
                assert context["identity_verified"] is True
                assert present == list(w.REPEAT_RANGE_KEYS)
            else:
                assert context["identity_verified"] is False
                assert present == []
            assert set(context) == w.REPEAT_FIELDS | set(present)
    assert by_operand["E20"][0]["state"] == "selected"
    assert by_operand["e8"][0]["state"] == "repeat-context-identity-unverifiable"


# ── adversarial: the gate refuses rather than publishing ───────────────


def test_a_not_resolvable_row_is_refused() -> None:
    record = SimpleNamespace(
        effect_id="a__b__c", comparison_state=ComparisonState.NOT_RESOLVABLE
    )
    with pytest.raises(w.SparseSa5CrossReportError, match="not resolvable"):
        w._require_record(record)


def test_a_not_comparable_row_carrying_a_label_is_refused() -> None:
    """The non-comparable state gate: `comparison_state` and `label_state` stay separate (§5.3.1)."""
    record = SimpleNamespace(
        effect_id="a__b__c",
        comparison_state=ComparisonState.NOT_COMPARABLE,
        label_state="deferred-pending-review",
    )
    with pytest.raises(w.SparseSa5CrossReportError, match="label_state"):
        w._require_record(record)


def test_a_state_outside_the_closed_vocabulary_is_refused() -> None:
    record = SimpleNamespace(
        effect_id="a__b__c",
        comparison_state=SimpleNamespace(value="maybe-comparable"),
        label_state=None,
    )
    with pytest.raises(w.SparseSa5CrossReportError, match="closed vocabulary"):
        w._require_record(record)


def test_only_the_ancillary_check_may_be_false(comparison) -> None:
    """`repeat_context_identity_fully_established` is false yet `ok` is true (§10)."""
    assert comparison.checks[w.ANCILLARY_CHECK] is False
    assert comparison.ok is True


def test_a_false_structural_check_fails_closed(comparison) -> None:
    """A structural check that is false refuses the run — no `ok: false` is ever published."""
    broken = comparison.model_copy(
        update={"checks": {**comparison.checks, "seventy_two_comparisons": False}}
    )
    assert broken.ok is False
    with pytest.raises(w.SparseSa5CrossReportError, match="structural gate"):
        w.build_cross_artifacts(broken, source_dir=REPORT_DIR)


def test_a_codec_encode_refusal_is_wrapped_as_a_report_refusal(
    comparison, monkeypatch
) -> None:
    def refuse(_records):
        raise CrossNpzError("a (0,) member is a refused artifact")

    monkeypatch.setattr(w, "encode_cross_npz", refuse)
    with pytest.raises(w.SparseSa5CrossReportError, match="codec refuses"):
        w.build_cross_artifacts(comparison, source_dir=REPORT_DIR)


def test_a_container_decode_refusal_fails_the_artifact_check(
    comparison, monkeypatch
) -> None:
    def refuse(*_args, **_kwargs):
        raise CrossNpzError("not the canonical §4 container")

    monkeypatch.setattr(w, "decode_cross_npz", refuse)
    with pytest.raises(w.SparseSa5CrossReportError, match="artifact checks"):
        w.build_cross_artifacts(comparison, source_dir=REPORT_DIR)


def test_a_wrong_orientation_is_refused(comparison) -> None:
    flipped = comparison.model_copy(update={"comparison": "live1 - live2"})
    with pytest.raises(w.SparseSa5CrossReportError, match="orientation"):
        w.build_cross_artifacts(flipped, source_dir=REPORT_DIR)


def test_a_tampered_source_quartet_is_refused(comparison, tmp_path) -> None:
    for stem in ("sa5-live-1-effects", "sa5-live-2-effects"):
        for suffix in (".npz", ".json", ".csv", ".README.md"):
            (tmp_path / f"{stem}{suffix}").write_bytes(
                (REPORT_DIR / f"{stem}{suffix}").read_bytes()
            )
    # Untampered, the same directory is a valid source.
    w.build_cross_artifacts(comparison, source_dir=tmp_path)
    target = tmp_path / "sa5-live-1-effects.csv"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(w.SparseSa5CrossReportError, match="artifact checks"):
        w.build_cross_artifacts(comparison, source_dir=tmp_path)


def test_a_missing_source_quartet_is_refused(comparison, tmp_path) -> None:
    with pytest.raises(w.SparseSa5CrossReportError, match="artifact checks"):
        w.build_cross_artifacts(comparison, source_dir=tmp_path)


def test_the_source_check_is_computed_not_trusted(artifacts) -> None:
    document = artifacts.document()
    assert document["artifact_checks"]["source_quartets_are_byte_unchanged"] is True
    # A provenance token that does not name the published bytes turns the check false.
    for provenance in document["provenance"].values():
        assert provenance["npz_sha256"].startswith("sha256:")


# ── publication and the refusal gate (§11) ─────────────────────────────


@pytest.fixture(scope="module")
def scratch_artifacts():
    return w.build_cross_report(
        source_dir=REPORT_DIR, analysis_commit="t", generator_revision="t"
    )


def test_writing_twice_into_one_destination_is_idempotent(
    scratch_artifacts, tmp_path
) -> None:
    destination = tmp_path / "set"
    w.write_cross_artifacts(scratch_artifacts, destination)
    first = {
        name: (destination / name).read_bytes() for name in scratch_artifacts.names
    }
    assert first == scratch_artifacts.payloads()
    w.write_cross_artifacts(scratch_artifacts, destination)
    assert {
        name: (destination / name).read_bytes() for name in scratch_artifacts.names
    } == first
    leftovers = [
        path.name
        for path in destination.iterdir()
        if path.name not in scratch_artifacts.names
    ]
    assert leftovers == [], "no lock or stage file survives a publication"


def test_a_concurrent_publication_is_judged_under_the_lock(
    scratch_artifacts, tmp_path, monkeypatch
) -> None:
    destination = tmp_path / "race"
    marker = b"another run's file\n"
    real_acquire = w._acquire_lock

    def racing_acquire(directory, stem):
        lock = real_acquire(directory, stem)
        for name, _payload in scratch_artifacts.files:
            (directory / name).write_bytes(marker)
        return lock

    monkeypatch.setattr(w, "_acquire_lock", racing_acquire)
    with pytest.raises(w.SparseSa5CrossReportError, match="did not produce"):
        w.write_cross_artifacts(scratch_artifacts, destination)
    for name, _payload in scratch_artifacts.files:
        assert (destination / name).read_bytes() == marker
    assert not (destination / f".{scratch_artifacts.stem}.publish-lock").exists()


@pytest.mark.parametrize("existing", ["partial", "differing", "non-file"])
def test_an_existing_set_this_run_did_not_produce_is_refused(
    scratch_artifacts, tmp_path, existing
) -> None:
    destination = tmp_path / "set"
    destination.mkdir()
    if existing == "partial":
        (destination / scratch_artifacts.npz_name).write_bytes(scratch_artifacts.npz)
    elif existing == "differing":
        for name, payload in scratch_artifacts.files:
            (destination / name).write_bytes(payload)
        (destination / scratch_artifacts.csv_name).write_bytes(b"not our table\n")
    else:
        (destination / scratch_artifacts.npz_name).mkdir()
    with pytest.raises(w.SparseSa5CrossReportError):
        w.write_cross_artifacts(scratch_artifacts, destination)
    if existing == "differing":
        assert (
            destination / scratch_artifacts.csv_name
        ).read_bytes() == b"not our table\n"


@pytest.mark.parametrize(
    "name",
    ["sa5-cross-sitting.notes", "sa5-cross-sitting", "sa5-cross-sitting.csv.bak"],
)
def test_an_unrelated_sibling_bearing_the_stem_is_refused(
    scratch_artifacts, tmp_path, name
) -> None:
    """A name sharing the stem but not one of the four is an unrelated file (§11)."""
    destination = tmp_path / "set"
    destination.mkdir()
    sibling = destination / name
    sibling.write_bytes(b"an unrelated file\n")
    with pytest.raises(w.SparseSa5CrossReportError, match="cross stem"):
        w.write_cross_artifacts(scratch_artifacts, destination)
    assert sibling.read_bytes() == b"an unrelated file\n"
    assert not any((destination / item).exists() for item in scratch_artifacts.names)
    assert not (destination / f".{scratch_artifacts.stem}.publish-lock").exists()


def test_a_leftover_lock_or_stage_file_refuses(scratch_artifacts, tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / f".{scratch_artifacts.stem}.publish-lock").write_text(
        "held", encoding="utf-8"
    )
    with pytest.raises(w.SparseSa5CrossReportError, match="lock"):
        w.write_cross_artifacts(scratch_artifacts, locked)

    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / f".{scratch_artifacts.npz_name}.abc123.tmp").write_bytes(
        b"half a container"
    )
    with pytest.raises(w.SparseSa5CrossReportError, match="temporary"):
        w.write_cross_artifacts(scratch_artifacts, stale)


def test_a_frozen_or_foreign_destination_is_refused(scratch_artifacts) -> None:
    for destination in (
        Path("reports/mixer-sensitivity-analysis"),
        Path("reports/sparse-mixer-live-1"),
        Path("reports/sparse-mixer-live-2"),
        Path("reports/stage2-e20-e64"),
        Path("reports"),
        Path("."),
    ):
        with pytest.raises(w.SparseSa5CrossReportError):
            w.write_cross_artifacts(scratch_artifacts, destination)


def test_a_relative_frozen_name_is_anchored_not_resolved_against_the_cwd(
    scratch_artifacts, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    scratch = tmp_path / "reports" / "mixer-sensitivity-analysis"
    w.write_cross_artifacts(scratch_artifacts, scratch)
    assert sorted(path.name for path in scratch.iterdir()) == sorted(
        scratch_artifacts.names
    )
    frozen = w._repository_root() / "reports" / "mixer-sensitivity-analysis"
    with pytest.raises(w.SparseSa5CrossReportError):
        w.write_cross_artifacts(scratch_artifacts, frozen)


def test_no_committed_artifact_is_touched_by_a_scratch_publication(
    scratch_artifacts, tmp_path
) -> None:
    trees = (
        REPORT_DIR,
        Path("reports/sparse-mixer-live-1"),
        Path("reports/sparse-mixer-live-2"),
        Path("reports/mixer-sensitivity-analysis"),
    )
    before = {
        str(tree): {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(tree.iterdir())
            if path.is_file()
        }
        for tree in trees
    }
    w.write_cross_artifacts(scratch_artifacts, tmp_path / "scratch")
    after = {
        str(tree): {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(tree.iterdir())
            if path.is_file()
        }
        for tree in trees
    }
    assert after == before


def test_the_reported_sides_never_stage_a_frozen_quartet_name(
    scratch_artifacts,
) -> None:
    for name in scratch_artifacts.names:
        assert name.startswith("sa5-cross-sitting.")
        assert "sa5-live-" not in name


# ── the runnable command ───────────────────────────────────────────────


def test_cross_report_main_publishes_into_scratch(tmp_path, capsys) -> None:
    destination = tmp_path / "cli"
    with pytest.raises(SystemExit) as raised:
        w.cross_report_main(
            [
                "--report-dir",
                str(destination),
                "--analysis-commit",
                "t",
                "--generator-revision",
                "t",
            ]
        )
    assert raised.value.code == 0
    assert sorted(path.name for path in destination.iterdir()) == sorted(
        f"sa5-cross-sitting{suffix}"
        for suffix in (".npz", ".csv", ".json", ".README.md")
    )
    assert "all pass" in capsys.readouterr().out


def test_cross_report_main_reads_the_fixed_source_not_the_output_dir(
    tmp_path, monkeypatch
) -> None:
    seen: list[Path] = []
    real_load = w.load_published_quartets

    def recording_load(directory=w.SOURCE_DIR):
        seen.append(Path(directory))
        return real_load(directory)

    monkeypatch.setattr(w, "load_published_quartets", recording_load)
    destination = tmp_path / "scratch"
    with pytest.raises(SystemExit) as raised:
        w.cross_report_main(["--report-dir", str(destination)])
    assert raised.value.code == 0
    assert seen == [w._repository_root() / w.SOURCE_DIR]
    assert (destination / f"{w.STEM}.npz").is_file()


def test_cross_report_main_refuses_when_the_gate_fails(monkeypatch, capsys) -> None:
    def _boom(**_kwargs):
        raise w.SparseSa5CrossReportError("stop before any byte is written")

    monkeypatch.setattr(w, "build_cross_report", _boom)
    with pytest.raises(SystemExit) as raised:
        w.cross_report_main(["--report-dir", "reports/sparse-signal"])
    assert raised.value.code == 1
    assert "udv-sa5-cross-report:" in capsys.readouterr().err


def test_cross_report_main_exits_nonzero_on_a_foreign_stem_sibling(
    tmp_path, capsys
) -> None:
    """A real publication refusal reaches the CLI as exit 1, not an escaping exception."""
    destination = tmp_path / "cli"
    destination.mkdir()
    (destination / "sa5-cross-sitting.notes").write_bytes(b"stray\n")
    with pytest.raises(SystemExit) as raised:
        w.cross_report_main(["--report-dir", str(destination)])
    assert raised.value.code == 1
    assert "cross stem" in capsys.readouterr().err
    assert not (destination / f"{w.STEM}.npz").exists()


def test_the_source_root_is_fixed_and_distinct_from_an_output_redirect() -> None:
    assert w.SOURCE_DIR == w.REPORT_DIR == Path("reports/sparse-signal")
    assert w.build_cross_report.__defaults__ is None  # keyword-only
    assert w.build_cross_report.__kwdefaults__["source_dir"] is None
