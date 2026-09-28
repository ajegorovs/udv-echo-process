"""Acceptance and adversarial tests for SA5's **independent** cross-sitting verifier (§12).

The contract under test is ``docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`` §12:
a separate program that re-derives the committed cross-sitting artifact set from the **two
committed within-sitting quartets** and contradicts every claim the writer staged, without
reading the writer's staged values as its input and without calling the writer's orchestration
path.

What the tests pin:

- **acceptance** — a freshly staged writer set verifies against a *separate* source root: the
  frozen 72 comparisons, the 280-member container, the seven checks, the digests recomputed from
  the staged bytes, a missing file as a refusal, and the verifier reading the source root it is
  *given* rather than the repository's own;
- **adversarial, re-signed corruption** — every mutation is followed by a rewrite of the whole
  digest chain (cross NPZ/CSV → cross JSON → cross README), so the digests still *agree* with
  the corrupted bytes. Each refusal therefore comes from the independent recomputation (steps
  1–4), never from a digest check: an NPZ ``D`` and a signed-zero flip, a mask and a state code,
  a CSV scalar, a JSON ``comparison_reason``, a JSON context quotation, an injected non-value
  row, a state-conditional repeat range key, a dropped or mis-named ``limitations`` operand, and
  a JSON ``1`` standing in for a JSON ``true`` on a check verdict, a provenance verdict and a
  repeat context's ``identity_verified``;
- **the source quartet is re-verified, not trusted** — a tampered copy of a quartet is refused
  by the verifier's own chain check, a re-signed quartet swapped under the wrong sitting is
  refused by the fixed sitting identity, and a re-signed quartet whose effect row is malformed is
  refused as the verifier's own :class:`CrossVerificationError`;
- **the three seam properties** — the verifier module imports neither the writer nor the
  orchestrator, never imports or calls the models layer's ``repeat_contexts``/``side_context``
  (it assembles the §6 context itself), and its digest checks run *last*.

No committed artifact is written: every staged set lands in ``tmp_path``. The writer and the
orchestrator are imported here on purpose, to stage the fresh set; the verifier is the subject.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_sa5_cross_npz as npz_codec
from udv_echo_process.analysis import sparse_sa5_cross_report as w
from udv_echo_process.analysis import sparse_sa5_cross_sitting as x
from udv_echo_process.analysis import sparse_sa5_cross_verify as v
from udv_echo_process.analysis.sparse_sa5_cross_npz import (
    decode_cross_npz,
    encode_cross_npz,
)
from udv_echo_process.analysis.sparse_sa5_npz import EFFECT_STATE_CODES

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "reports" / "sparse-signal"

#: The corner comparison the doctored cases are aimed at: a comparable pair with a real domain.
CORNER = "primary-comparison__mean__pitch_at_burst_4"


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def artifacts():
    """A fresh writer set over the two committed quartets, built but never written to disk."""
    published = x.load_published_quartets(REPORT_DIR)
    comparison = x.compare_cross_sitting(*published)
    return w.build_cross_artifacts(
        comparison,
        source_dir=REPORT_DIR,
        analysis_commit="test-commit",
        generator_revision="test-generator",
    )


@pytest.fixture()
def staged(artifacts, tmp_path: Path) -> Path:
    """The four writer products staged in an isolated directory."""
    directory = tmp_path / "cross"
    directory.mkdir()
    for name, payload in artifacts.files:
        (directory / name).write_bytes(payload)
    return directory


@pytest.fixture(scope="module")
def source_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A **separate** source root: the two committed quartets copied out of the repository."""
    copy = tmp_path_factory.mktemp("source") / "sparse-signal"
    shutil.copytree(REPORT_DIR, copy)
    return copy


# ── digests, rehearsed the way the schema states them (§5.7) ───────────


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _canon(data: bytes) -> str:
    return _sha(data.replace(b"\r\n", b"\n"))


def _paths(directory: Path) -> dict[str, Path]:
    return {
        "npz": directory / f"{v.STEM}.npz",
        "csv": directory / f"{v.STEM}.csv",
        "json": directory / f"{v.STEM}.json",
        "readme": directory / f"{v.STEM}.README.md",
    }


def _restage(
    directory: Path,
    *,
    npz: bytes | None = None,
    csv: bytes | None = None,
    document: dict[str, object] | None = None,
) -> Path:
    """Write a set whose whole digest chain agrees with the (possibly corrupted) bytes.

    The cross NPZ and CSV digests are re-bound into the cross JSON, the JSON's own canonical-LF
    digest is re-bound into the README, and the README's stale tokens are replaced — so a
    refusal that follows is the recomputation's, never a digest's.
    """
    paths = _paths(directory)
    old_json = paths["json"].read_bytes()
    old_document = json.loads(old_json)
    raw_npz = paths["npz"].read_bytes() if npz is None else npz
    raw_csv = paths["csv"].read_bytes() if csv is None else csv
    body = old_document if document is None else document

    body["artifacts"]["npz"]["sha256"] = _sha(raw_npz)  # type: ignore[index]
    body["artifacts"]["csv"]["sha256"] = _canon(raw_csv)  # type: ignore[index]
    json_bytes = (
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    readme = paths["readme"].read_text("utf-8")
    for stale, fresh in (
        (old_document["artifacts"]["npz"]["sha256"], _sha(raw_npz)),
        (old_document["artifacts"]["csv"]["sha256"], _canon(raw_csv)),
        (_canon(old_json), _canon(json_bytes)),
    ):
        if stale != fresh:
            readme = readme.replace(stale, fresh)

    paths["npz"].write_bytes(raw_npz)
    paths["csv"].write_bytes(raw_csv)
    paths["json"].write_bytes(json_bytes)
    paths["readme"].write_text(readme, "utf-8")
    return directory


def _assert_the_digest_chain_agrees(directory: Path) -> None:
    """The corrupted set's digests *do* match its bytes — the point of a re-signed corruption."""
    paths = _paths(directory)
    document = json.loads(paths["json"].read_bytes())
    assert document["artifacts"]["npz"]["sha256"] == _sha(paths["npz"].read_bytes())
    assert document["artifacts"]["csv"]["sha256"] == _canon(paths["csv"].read_bytes())
    assert _canon(paths["json"].read_bytes()) in paths["readme"].read_text("utf-8")


def _revised_document(artifacts) -> dict[str, object]:
    """A mutable copy of the writer's own document, ready to be doctored."""
    return json.loads(artifacts.json.decode("utf-8"))


def _resign_source(directory: Path, stem: str, mutate) -> None:
    """Rewrite one source quartet's JSON and re-bind *its own* chain around the mutation.

    The source JSON's canonical-LF digest recorded in its README is refreshed, and its own
    ``artifacts`` bindings are left pointing at the unchanged NPZ/CSV, so a refusal that follows
    is the verifier's own source gate — never a stale digest. Only the mutation is new.
    """
    document = directory / f"{stem}.json"
    readme = directory / f"{stem}.README.md"
    old_bytes = document.read_bytes()
    old_digest = _canon(old_bytes)
    body = json.loads(old_bytes)
    mutate(body)
    new_bytes = (
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    document.write_bytes(new_bytes)
    readme.write_text(
        readme.read_text("utf-8").replace(old_digest, _canon(new_bytes)), "utf-8"
    )


# ── NPZ surgery at the container seam (§3, §4) ─────────────────────────


def _decoded(artifacts, npz: bytes) -> dict[str, object]:
    expected = {
        record["effect_id"]: record["comparison_knot_count"]
        for record in artifacts.document()["comparisons"]
        if record["comparison_knot_count"] is not None
    }
    return {
        record.effect_id: record for record in decode_cross_npz(npz, expected=expected)
    }


def _re_encoded(artifacts, npz: bytes, key: str, **updates: np.ndarray) -> bytes:
    records = _decoded(artifacts, npz)
    records[key] = records[key].model_copy(
        update={
            name: np.ascontiguousarray(value, dtype=value.dtype)
            for name, value in updates.items()
        }
    )
    return encode_cross_npz(list(records.values()))


def _rewrite_member(npz: bytes, member: str, array: np.ndarray) -> bytes:
    """Replace one member's raw NPY payload, leaving the canonical archive around it intact.

    The codec refuses a mask that contradicts the state codes and a placeholder that is not
    ``+0.0``, so a container whose mask and state disagree is only reachable by byte surgery —
    exactly the corruption a symmetric writer/verifier mistake would hide.
    """
    source = zipfile.ZipFile(io.BytesIO(npz))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        for name in sorted(source.namelist()):
            info = source.getinfo(name)
            payload = (
                npz_codec._npy_bytes(array) if name == member else source.read(name)
            )
            out.writestr(info, payload)
    return buffer.getvalue()


def _defined_position(record) -> int:
    assert (record.defined == 1).any(), (
        "the corner comparison carries a defined position"
    )
    return int(np.argmax(record.defined == 1))


def _refusal(directory: Path, source: Path, *needles: str) -> str:
    """The verifier's refusal for a set, with every ``needle`` present in the message."""
    with pytest.raises(v.CrossVerificationError) as excinfo:
        v.verify_cross_artifacts(directory, source)
    message = str(excinfo.value)
    for needle in needles:
        assert needle in message, message
    return message


# ── acceptance: a fresh writer set against a separate source root (§12) ─


def test_a_fresh_staged_writer_set_verifies_against_a_separate_source_root(
    artifacts, staged, source_root
) -> None:
    result = v.verify_cross_artifacts(staged, source_root)
    assert result.ok is True
    assert result.comparison == "live2 - live1"
    assert result.comparison_count == 72
    comparable = sum(
        1
        for record in artifacts.document()["comparisons"]
        if record["comparison_knot_count"] is not None
    )
    assert result.npz_member_count == comparable * 5
    assert set(result.checks) == {
        "source_quartet_chains_verified",
        "npz_arrays_match_the_recomputation",
        "csv_scalars_match_the_recomputation",
        "json_records_and_context_match_the_recomputation",
        "nonvalue_rows_match_the_recomputation",
        "structural_invariants_hold",
        "digests_match_the_staged_bytes",
    }
    assert all(result.checks.values())
    assert result.source_dir == source_root.resolve()
    assert result.artifact_dir == staged
    assert source_root != REPORT_DIR, "the source root under test is a separate tree"


def test_the_verification_publishes_the_digests_it_recomputed(
    staged, source_root
) -> None:
    result = v.verify_cross_artifacts(staged, source_root)
    paths = _paths(staged)
    assert result.digests == {
        "npz": _sha(paths["npz"].read_bytes()),
        "csv": _canon(paths["csv"].read_bytes()),
        "json": _canon(paths["json"].read_bytes()),
    }


def test_the_verifier_verifies_a_copy_of_the_source_root_not_the_repository(
    staged, source_root
) -> None:
    """The same staged set, read against the copy: identical verdict and identical digests."""
    assert v.verify_cross_artifacts(staged, source_root).digests == (
        v.verify_cross_artifacts(staged, REPORT_DIR).digests
    )


@pytest.mark.parametrize("missing", ["npz", "csv", "json", "readme"])
def test_a_missing_artifact_file_is_a_refusal(missing, staged, source_root) -> None:
    _paths(staged)[missing].unlink()
    _refusal(staged, source_root, "is missing")


# ── the source quartet is re-verified, not trusted (§12.1) ─────────────


def test_a_tampered_source_quartet_is_refused(staged, tmp_path) -> None:
    tampered = tmp_path / "source"
    shutil.copytree(REPORT_DIR, tampered)
    table = tampered / "sa5-live-1-effects.csv"
    table.write_bytes(table.read_bytes() + b"\n")
    _refusal(staged, tampered, "sa5-live-1-effects", "chain")


def test_a_source_quartet_with_a_broken_json_binding_is_refused(
    staged, tmp_path
) -> None:
    tampered = tmp_path / "source"
    shutil.copytree(REPORT_DIR, tampered)
    document = tampered / "sa5-live-2-effects.json"
    body = json.loads(document.read_bytes())
    body["artifacts"]["npz"]["sha256"] = "sha256:" + "0" * 64
    document.write_text(
        json.dumps(body, sort_keys=True, separators=(",", ":")), "utf-8"
    )
    _refusal(staged, tampered, "sa5-live-2-effects")


def test_a_quartet_swapped_under_the_wrong_sitting_is_refused(staged, tmp_path) -> None:
    """The source sitting identity is fixed: a re-signed quartet may not declare another sitting."""
    tampered = tmp_path / "source"
    shutil.copytree(REPORT_DIR, tampered)

    def swap(body: dict[str, object]) -> None:
        body["sitting"] = "sparse-mixer-live-2"

    _resign_source(tampered, "sa5-live-1-effects", swap)
    _refusal(
        staged,
        tampered,
        "sa5-live-1-effects",
        "sitting",
        "sparse-mixer-live-2",
        "sparse-mixer-live-1",
    )


def test_a_malformed_source_effect_row_is_wrapped_as_a_cross_verification_error(
    staged, tmp_path
) -> None:
    """A re-signed quartet whose effect row loses a required key refuses as the verifier's own error."""
    tampered = tmp_path / "source"
    shutil.copytree(REPORT_DIR, tampered)

    def drop(body: dict[str, object]) -> None:
        del body["effects"][0]["knot_count"]  # type: ignore[index]

    _resign_source(tampered, "sa5-live-1-effects", drop)
    _refusal(staged, tampered, "malformed effect row", "sa5-live-1-effects")


# ── adversarial: re-signed corruptions the recomputation must catch ────


def test_a_re_signed_npz_difference_corruption_is_refused(
    artifacts, staged, source_root
) -> None:
    record = _decoded(artifacts, artifacts.npz)[CORNER]
    position = _defined_position(record)
    difference = np.array(record.difference, copy=True)
    difference[position] = difference[position] + 1.0
    _restage(
        staged, npz=_re_encoded(artifacts, artifacts.npz, CORNER, difference=difference)
    )
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, CORNER, "member difference")


def test_a_re_signed_signed_zero_flip_is_refused(
    artifacts, staged, source_root
) -> None:
    record = _decoded(artifacts, artifacts.npz)[CORNER]
    position = _defined_position(record)
    difference = np.array(record.difference, copy=True)
    difference[position] = -0.0
    _restage(
        staged, npz=_re_encoded(artifacts, artifacts.npz, CORNER, difference=difference)
    )
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, CORNER, "member difference")


def test_a_re_signed_mask_corruption_is_refused(artifacts, staged, source_root) -> None:
    record = _decoded(artifacts, artifacts.npz)[CORNER]
    defined = np.array(record.defined, copy=True)
    defined[_defined_position(record)] = 0
    npz = _rewrite_member(
        artifacts.npz,
        npz_codec.cross_member_name(CORNER, "defined"),
        np.ascontiguousarray(defined, dtype=defined.dtype),
    )
    _restage(staged, npz=npz)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, CORNER)


def test_a_re_signed_state_code_is_refused(artifacts, staged, source_root) -> None:
    """A state code doctored *consistently* with its mask: a legal container, a wrong state."""
    record = _decoded(artifacts, artifacts.npz)[CORNER]
    position = _defined_position(record)
    other = min(set(EFFECT_STATE_CODES) - {0})
    defined = np.array(record.defined, copy=True)
    state1 = np.array(record.state1, copy=True)
    difference = np.array(record.difference, copy=True)
    defined[position] = 0
    state1[position] = other
    difference[position] = 0.0
    npz = artifacts.npz
    for member, array in (
        ("defined", defined),
        ("state1", state1),
        ("difference", difference),
    ):
        npz = _rewrite_member(
            npz,
            npz_codec.cross_member_name(CORNER, member),
            np.ascontiguousarray(array, dtype=array.dtype),
        )
    _restage(staged, npz=npz)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, CORNER, "member state1")


def test_a_re_signed_csv_scalar_corruption_is_refused(staged, source_root) -> None:
    lines = _paths(staged)["csv"].read_bytes().decode("utf-8").splitlines()
    columns = lines[0].split(",")
    column = columns.index("rms_difference")
    cells = lines[1].split(",")
    cells[column] = str(float(cells[column]) + 1.0)
    lines[1] = ",".join(cells)
    _restage(staged, csv=("\n".join(lines) + "\n").encode("utf-8"))
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "CSV rms_difference")


def test_a_re_signed_json_comparison_reason_is_refused(
    artifacts, staged, source_root
) -> None:
    document = _revised_document(artifacts)
    record = document["comparisons"][3]
    assert record["comparison_reason"] != "not-comparable"
    record["comparison_reason"] = "not-comparable"
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, record["effect_id"], "comparison_reason")


def test_a_re_signed_json_context_quotation_is_refused(
    artifacts, staged, source_root
) -> None:
    document = _revised_document(artifacts)
    comparison = document["comparisons"][0]
    context = comparison["context1"]
    context["signed_depth_average"] = context["signed_depth_average"] + 1.0
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, comparison["effect_id"], "context1")


def test_a_re_signed_json_nonvalue_row_is_refused(
    artifacts, staged, source_root
) -> None:
    document = _revised_document(artifacts)
    assert document["nonvalue_rows"] == [], (
        "the committed pair produces no typed-empty row"
    )
    document["nonvalue_rows"] = [
        {
            "effect_id": CORNER,
            "kind": "shape",
            "side": None,
            "state": "undefined-shape",
            "reason": "a row the recomputation never produced",
        }
    ]
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "nonvalue_rows")


def test_a_re_signed_repeat_range_key_is_refused(
    artifacts, staged, source_root
) -> None:
    """A range key on a non-selected repeat context: the keys are state-conditional (§5.4)."""
    document = _revised_document(artifacts)
    comparison = document["comparisons"][0]
    repeats = comparison["context1"]["repeats"]
    assert repeats, "the corner context quotes at least one repeat operand"
    for context in repeats:
        assert context["state"] != "selected", (
            "the committed repeats are all non-selected"
        )
    repeats[0][v.REPEAT_RANGE_KEYS[0]] = 0.0
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "repeats[0]")


def test_a_re_signed_limitations_omission_is_refused(
    artifacts, staged, source_root
) -> None:
    """§10: the limitation naming the identity-unverifiable operands may not be dropped."""
    document = _revised_document(artifacts)
    assert document["limitations"], (
        "the committed pair records the identity-unverifiable operands"
    )
    document["limitations"] = []
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "limitations")


def test_a_re_signed_limitations_entry_naming_a_wrong_operand_is_refused(
    artifacts, staged, source_root
) -> None:
    """The limitation names *exactly* the recomputed identity-unverifiable operand set."""
    document = _revised_document(artifacts)
    document["limitations"] = [document["limitations"][0] + " cc1"]
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "limitations", "operand set")


def test_a_re_signed_non_boolean_check_verdict_is_refused(
    artifacts, staged, source_root
) -> None:
    """A JSON ``1`` is not a JSON ``true``: the boolean type is enforced, not merely equality."""
    document = _revised_document(artifacts)
    assert document["checks"]["no_recurrence_verdict"] is True
    document["checks"]["no_recurrence_verdict"] = 1
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "no_recurrence_verdict", "JSON boolean")


def test_a_re_signed_non_boolean_provenance_verdict_is_refused(
    artifacts, staged, source_root
) -> None:
    """``checks_ok``/``artifact_checks_ok`` are JSON booleans, not ``0``/``1`` integers."""
    document = _revised_document(artifacts)
    row = document["provenance"]["live-1"]
    assert row["checks_ok"] is True
    row["checks_ok"] = 1
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(staged, source_root, "checks_ok", "JSON boolean")


def test_a_re_signed_non_boolean_identity_verified_is_refused(
    artifacts, staged, source_root
) -> None:
    """The quoted ``identity_verified`` is a JSON boolean, checked by the verifier's own context."""
    document = _revised_document(artifacts)
    located = next(
        (
            (comparison, context)
            for comparison in document["comparisons"]
            for context in comparison["context1"]["repeats"]
            if context["state"] == "selected"
        ),
        None,
    )
    assert located is not None, "the committed pair quotes a selected repeat context"
    comparison, context = located
    context["identity_verified"] = 1
    _restage(staged, document=document)
    _assert_the_digest_chain_agrees(staged)
    _refusal(
        staged,
        source_root,
        comparison["effect_id"],
        "identity_verified",
        "JSON boolean",
    )


# ── the two seam properties (§12) ──────────────────────────────────────


def test_the_verifier_imports_neither_the_writer_nor_the_orchestrator() -> None:
    module = Path(inspect.getfile(v))
    tree = ast.parse(module.read_text("utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "sparse_sa5_cross_report",
        "sparse_sa5_cross_sitting",
    }
    assert not [name for name in imported if name.rsplit(".", 1)[-1] in forbidden]

    # …and the same holds at runtime, where a docstring that *names* them cannot help: the
    # verifier's own import graph never pulls in the writer or the orchestrator.
    probe = (
        "import sys;"
        "import udv_echo_process.analysis.sparse_sa5_cross_verify;"
        "leaked = sorted(m for m in sys.modules if m.endswith("
        "('sparse_sa5_cross_report', 'sparse_sa5_cross_sitting')));"
        "print(','.join(leaked))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == ""


def test_the_digest_checks_run_last() -> None:
    source = inspect.getsource(v.verify_cross_artifacts)
    digest_check = source.index("_verify_digests(")
    for recomputation in ("_compare_npz(", "_compare_csv(", "_compare_json("):
        assert source.index(recomputation) < digest_check, (
            f"{recomputation} must run before the digest checks (§12.5)"
        )


def test_the_verifier_assembles_context_without_the_models_layer() -> None:
    """§12: the §6 context is assembled here, never obtained from ``sparse_sa5_cross_models``.

    The writer and the orchestration path build every context quotation through the models
    layer's ``repeat_contexts``/``side_context``; the verifier must not import or call either,
    or a context-assembly mistake would be shared through one orchestration path.
    """
    module = Path(inspect.getfile(v))
    tree = ast.parse(module.read_text("utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Attribute):
                called.add(target.attr)
            elif isinstance(target, ast.Name):
                called.add(target.id)
    assert "sparse_sa5_cross_models" not in imported
    assert not called & {"repeat_contexts", "side_context"}

    # …and at runtime the verifier's own import graph never pulls the models layer in.
    probe = (
        "import sys;"
        "import udv_echo_process.analysis.sparse_sa5_cross_verify;"
        "print(any("
        "m.rsplit('.', 1)[-1] == 'sparse_sa5_cross_models' for m in sys.modules))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "False"
