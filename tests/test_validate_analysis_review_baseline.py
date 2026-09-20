"""Focused tests for the review-correction baseline freeze gate.

Plan ``docs/dop3000/existing-sweep-analysis-plan.md`` §8.3 item 1: before any
correction lands, the current report tree is frozen as the comparison baseline.
``tools/validate_analysis_review_baseline.py`` is that gate and
``reports/mixer-sensitivity-analysis/review-correction-baseline.json`` is the
record it checks. The 24 recorded items are the 22 generated report artefacts —
each with the generator module and revision that produced it — plus the two
hand-written documents, ``decision-table.md`` and ``README.md``.

What the tests pin:

- the committed record is complete and *true* of the committed tree (every
  recorded SHA-256 equals the file's bytes, every generator names a real module
  and the revision its own provenance document records);
- ``--check-current`` fails on any drift, so the freeze is a gate and not a note;
- ``--check-final`` demands a correction id and a replacement hash for every
  changed item and reports the corrections still pending — it never invents a
  mapping, which is why it must fail today, before R1-R9 have landed;
- the recorded gate commands and their raw results are present and green.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

#: Repository root, from this file's own location (``tests/`` is one level down).
REPO = Path(__file__).resolve().parents[1]

#: The gate under test.
TOOL_PATH = REPO / "tools" / "validate_analysis_review_baseline.py"

#: The baseline record the gate reads.
RECORD_PATH = REPO / "reports" / "mixer-sensitivity-analysis" / "review-correction-baseline.json"

#: The focused gate command the record must carry, and the file it names.
FOCUSED_TEST_FILE = "tests/test_validate_analysis_review_baseline.py"


def _load_tool():
    """Import the gate module from ``tools/`` (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("validate_analysis_review_baseline", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    assert TOOL_PATH.is_file(), f"the gate module is missing: {TOOL_PATH}"
    return _load_tool()


@pytest.fixture(scope="module")
def baseline(tool):
    """The committed record, parsed through the gate's own schema."""
    assert RECORD_PATH.is_file(), f"the baseline record is missing: {RECORD_PATH}"
    document = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    return tool.parse_baseline(document)


@pytest.fixture(scope="module")
def document():
    """The committed record as raw JSON, for the assertions about its own text."""
    assert RECORD_PATH.is_file(), f"the baseline record is missing: {RECORD_PATH}"
    return json.loads(RECORD_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# synthetic records: what the schema and the two check modes refuse
# --------------------------------------------------------------------------- #


def _synthetic_tree(tool, root: Path, *, gate_names=None, mangle=None):
    """Write a small, self-consistent baseline plus the tree it describes.

    One provenance item (``qc-summary.json``) carries the revision every other
    generated item cites, exactly as the real record's axis provenance documents
    do for the CSV/figure pairs. ``mangle`` may edit the document before it is
    parsed; the files on disk stay as written.
    """
    report = root / "reports" / "mixer-sensitivity-analysis"
    report.mkdir(parents=True, exist_ok=True)
    generator = root / "src" / "udv_echo_process" / "analysis" / "synthetic.py"
    generator.parent.mkdir(parents=True, exist_ok=True)
    generator.write_text('"""A stand-in for a real axis generator."""\n', encoding="utf-8")
    generator_path = "src/udv_echo_process/analysis/synthetic.py"
    revision = "abc1234"
    provenance = {"analysis_commit": revision}
    (report / "qc-summary.json").write_text(json.dumps(provenance) + "\n", encoding="utf-8")

    items = []
    for index in range(tool.GENERATED_ITEM_COUNT - 1):
        name = f"artefact-{index:02d}.csv"
        (report / name).write_text(f"row,{index}\n", encoding="utf-8")
        items.append(
            {
                "path": name,
                "role": tool.GENERATED_ROLE,
                "generator": generator_path,
                "generator_revision": revision,
                "generator_command": (
                    ".venv/Scripts/python.exe -m udv_echo_process.cli synthetic"
                    " --analysis-commit abc1234"
                ),
                "revision_source": "qc-summary.json",
                "sha256": None,
                "correction": None,
                "replacement_sha256": None,
            }
        )
    items.append(
        {
            "path": "qc-summary.json",
            "role": tool.GENERATED_ROLE,
            "generator": generator_path,
            "generator_revision": revision,
            "generator_command": (
                    ".venv/Scripts/python.exe -m udv_echo_process.cli synthetic"
                    " --analysis-commit abc1234"
                ),
            "revision_source": "qc-summary.json",
            "sha256": None,
            "correction": None,
            "replacement_sha256": None,
        }
    )
    for name in tool.HAND_WRITTEN_PATHS:
        (report / name).write_text(f"# {name}\n", encoding="utf-8")
        items.append(
            {
                "path": name,
                "role": tool.HAND_WRITTEN_ROLE,
                "generator": None,
                "generator_revision": None,
                "generator_command": None,
                "revision_source": None,
                "sha256": None,
                "correction": None,
                "replacement_sha256": None,
            }
        )

    for item in items:
        item["sha256"] = tool.sha256_id(report / item["path"])

    gates = []
    for name in gate_names if gate_names is not None else tool.REQUIRED_GATES:
        gates.append(
            {
                "name": name,
                "command": tool.GATE_COMMANDS[name],
                "exit_code": 0,
                "raw_result": "synthetic",
            }
        )

    document = {
        "baseline": tool.BASELINE_KIND,
        "plan": "docs/dop3000/existing-sweep-analysis-plan.md §8.3 item 1",
        "report_dir": "reports/mixer-sensitivity-analysis",
        "captured": {"head": "0" * 40, "branch": "analysis/existing-sweep-plan", "utc": "synthetic"},
        "items": items,
        "corrections": [
            {"id": cid, "title": f"ruling {cid}", "status": "pending", "mapped_items": []}
            for cid in tool.CORRECTION_IDS
        ],
        "gates": gates,
    }
    if mangle is not None:
        mangle(document, report)
    return document, report


# --------------------------------------------------------------------------- #
# the committed record
# --------------------------------------------------------------------------- #


def test_record_is_the_24_item_baseline(baseline):
    """22 generated artefacts plus the two hand-written documents."""
    assert len(baseline.items) == 24
    generated = [item for item in baseline.items if item.role == "generated-artifact"]
    hand_written = [item for item in baseline.items if item.role == "hand-written"]
    assert len(generated) == 22
    assert [item.path for item in hand_written] == ["decision-table.md", "README.md"]


def test_recorded_hashes_are_the_captured_commit_bytes(tool, baseline):
    """Every frozen SHA-256 equals the bytes at the recorded baseline commit.

    The live worktree is expected to diverge as R1-R9 land; checking it here would
    make the full suite permanently red after the first correction. ``--check-current``
    remains the explicit command for asking whether the worktree is still unchanged.
    """
    assert baseline.report_dir == "reports/mixer-sensitivity-analysis"
    mismatched = {}
    for item in baseline.items:
        repository_path = f"{baseline.report_dir}/{item.path}"
        completed = subprocess.run(
            ["git", "show", f"{baseline.captured_head}:{repository_path}"],
            cwd=REPO,
            check=False,
            capture_output=True,
        )
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
        captured_hashes = {
            f"sha256:{hashlib.sha256(completed.stdout).hexdigest()}",
            # The baseline was captured from worktree bytes on Windows with
            # core.autocrlf=true. Markdown has no eol attribute in this tree,
            # so its historical checkout is CRLF although the Git blob is LF.
            f"sha256:{hashlib.sha256(completed.stdout.replace(bytes((10,)), bytes((13, 10)))).hexdigest()}",
        }
        if item.sha256 not in captured_hashes:
            mismatched[item.path] = (item.sha256, sorted(captured_hashes))
    assert mismatched == {}


def test_generated_items_name_a_generator_and_a_revision(tool, baseline):
    """Each generated artefact cites a real module and its provenance revision."""
    for item in baseline.items:
        if item.role != tool.GENERATED_ROLE:
            assert item.generator is None and item.generator_revision is None
            continue
        assert (REPO / item.generator).is_file(), item.path
        assert tool.GENERATOR_REVISION_RE.fullmatch(item.generator_revision or ""), item.path
        source = REPO / baseline.report_dir / item.revision_source
        assert source.is_file(), item.path
        recorded = json.loads(source.read_text(encoding="utf-8"))
        assert recorded["analysis_commit"] == item.generator_revision, item.path
        assert any(other.path == item.revision_source for other in baseline.items), item.path


def test_records_the_module_that_actually_writes_each_artifact(tool, baseline):
    """The recorded generator per artefact is the module whose CLI writes it."""
    expected = {
        "src/udv_echo_process/analysis/sweep_inventory.py": {
            "manifest.csv",
            "qc-summary.json",
        },
        "src/udv_echo_process/analysis/reference_repeat.py": {
            "reference-repeat.csv",
            "reference-repeat.provenance.json",
            "figures/reference-repeat.png",
        },
        "src/udv_echo_process/analysis/resolution_ladder.py": {
            "resolution-levels.csv",
            "resolution-pairs.csv",
            "resolution-ladder.provenance.json",
            "figures/resolution-ladder.png",
        },
        "src/udv_echo_process/analysis/burst_ladder.py": {
            "burst-levels.csv",
            "burst-pairs.csv",
            "burst-ladder.provenance.json",
            "figures/burst-ladder.png",
        },
        "src/udv_echo_process/analysis/prf_ladder.py": {
            "prf-levels.csv",
            "prf-pairs.csv",
            "prf-ladder.provenance.json",
            "figures/prf-ladder.png",
        },
        "src/udv_echo_process/analysis/gain_power_screen.py": {
            "gain-power-levels.csv",
            "gain-power-pairs.csv",
            "gain-power-depths.csv",
            "gain-power-screen.provenance.json",
            "figures/gain-power-screen.png",
        },
    }
    recorded: dict[str, set[str]] = {}
    for item in baseline.items:
        if item.role != tool.GENERATED_ROLE:
            continue
        recorded.setdefault(item.generator, set()).add(item.path)
        assert item.generator_revision in item.generator_command, item.path
    assert recorded == expected


def test_main_requires_a_mode(tool):
    with pytest.raises(SystemExit) as excinfo:
        tool.main([])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        tool.main(["--check-current", "--check-final"])
    assert excinfo.value.code == 2


def test_check_final_reports_the_pending_corrections(tool, baseline):
    """R1-R9 are all unlanded at freeze time: the mode must say so, not guess."""
    problems = tool.check_final(baseline)
    assert problems
    text = "\n".join(problems)
    for correction_id in tool.CORRECTION_IDS:
        assert correction_id in text
    assert all(item.correction is None for item in baseline.items)
    assert all(item.replacement_sha256 is None for item in baseline.items)


def test_main_check_final_is_non_zero_while_pending(tool, capsys):
    assert tool.main(["--check-final"]) == 1
    captured = capsys.readouterr()
    assert "R1" in captured.out + captured.err


# --------------------------------------------------------------------------- #
# schema refusal
# --------------------------------------------------------------------------- #


def test_parse_accepts_a_consistent_synthetic_record(tool, tmp_path):
    document, _ = _synthetic_tree(tool, tmp_path)
    baseline = tool.parse_baseline(document)
    assert len(baseline.items) == 24
    assert tool.check_current(baseline, root=tmp_path) == []


def test_parse_rejects_a_short_record(tool, tmp_path):
    def mangle(document, report):
        document["items"] = document["items"][:-1]

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    with pytest.raises(tool.BaselineError):
        tool.parse_baseline(document)


def test_parse_rejects_a_moved_hand_written_document(tool, tmp_path):
    def mangle(document, report):
        for item in document["items"]:
            if item["path"] == "README.md":
                item["role"] = "generated-artifact"

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    with pytest.raises(tool.BaselineError):
        tool.parse_baseline(document)


def test_parse_rejects_an_unknown_correction_id(tool, tmp_path):
    def mangle(document, report):
        document["corrections"][0]["id"] = "R99"

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    with pytest.raises(tool.BaselineError):
        tool.parse_baseline(document)


def test_parse_rejects_a_malformed_hash(tool, tmp_path):
    def mangle(document, report):
        document["items"][0]["sha256"] = document["items"][0]["sha256"].upper()

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    with pytest.raises(tool.BaselineError):
        tool.parse_baseline(document)


# --------------------------------------------------------------------------- #
# drift detection
# --------------------------------------------------------------------------- #


def test_check_current_flags_a_changed_artifact(tool, tmp_path):
    document, report = _synthetic_tree(tool, tmp_path)
    baseline = tool.parse_baseline(document)
    (report / "artefact-00.csv").write_text("regenerated\n", encoding="utf-8")
    problems = tool.check_current(baseline, root=tmp_path)
    assert any("artefact-00.csv" in problem for problem in problems)


def test_check_current_flags_a_missing_artifact(tool, tmp_path):
    document, report = _synthetic_tree(tool, tmp_path)
    baseline = tool.parse_baseline(document)
    (report / "artefact-01.csv").unlink()
    problems = tool.check_current(baseline, root=tmp_path)
    assert any("artefact-01.csv" in problem for problem in problems)


def test_check_current_requires_the_recorded_gate_results(tool, tmp_path):
    document, _ = _synthetic_tree(tool, tmp_path, gate_names=("lint",))
    baseline = tool.parse_baseline(document)
    problems = tool.check_current(baseline, root=tmp_path)
    assert any("focused-tests" in problem for problem in problems)
    assert any("full-tests" in problem for problem in problems)


def test_check_current_flags_a_failed_gate(tool, tmp_path):
    def mangle(document, report):
        document["gates"][0]["exit_code"] = 1

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    baseline = tool.parse_baseline(document)
    problems = tool.check_current(baseline, root=tmp_path)
    assert any("focused-tests" in problem for problem in problems)


def test_check_current_flags_a_stale_gate_command(tool, tmp_path):
    def mangle(document, report):
        document["gates"][0]["command"] = ".venv/Scripts/python.exe -m pytest -q"

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    baseline = tool.parse_baseline(document)
    problems = tool.check_current(baseline, root=tmp_path)
    assert any(
        "focused-tests" in problem and "command" in problem for problem in problems
    )


# --------------------------------------------------------------------------- #
# rebinding: --check-final
# --------------------------------------------------------------------------- #


def test_check_final_demands_a_mapping_for_a_changed_item(tool, tmp_path):
    document, report = _synthetic_tree(tool, tmp_path)
    baseline = tool.parse_baseline(document)
    (report / "artefact-00.csv").write_text("regenerated\n", encoding="utf-8")
    problems = tool.check_final(baseline, root=tmp_path)
    assert any(
        "artefact-00.csv" in problem and "correction" in problem for problem in problems
    )


def test_check_final_demands_the_replacement_hash_too(tool, tmp_path):
    def mangle(document, report):
        document["items"][0]["correction"] = "R5"

    document, report = _synthetic_tree(tool, tmp_path, mangle=mangle)
    baseline = tool.parse_baseline(document)
    (report / "artefact-00.csv").write_text("regenerated\n", encoding="utf-8")
    problems = tool.check_final(baseline, root=tmp_path)
    assert any("artefact-00.csv" in problem for problem in problems)


def test_check_final_accepts_a_mapped_replacement(tool, tmp_path):
    document, report = _synthetic_tree(tool, tmp_path)
    (report / "artefact-00.csv").write_text("regenerated\n", encoding="utf-8")
    replacement = tool.sha256_id(report / "artefact-00.csv")
    for item in document["items"]:
        if item["path"] == "artefact-00.csv":
            item["correction"] = "R5"
            item["replacement_sha256"] = replacement
    for correction in document["corrections"]:
        if correction["id"] == "R5":
            correction["status"] = "recorded"
            correction["mapped_items"] = ["artefact-00.csv"]
    baseline = tool.parse_baseline(document)
    problems = tool.check_final(baseline, root=tmp_path)
    assert not [problem for problem in problems if "artefact-00.csv" in problem]


def test_check_final_rejects_a_replacement_of_an_unchanged_item(tool, tmp_path):
    def mangle(document, report):
        document["items"][0]["replacement_sha256"] = "sha256:" + "0" * 64

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    baseline = tool.parse_baseline(document)
    problems = tool.check_final(baseline, root=tmp_path)
    assert any("artefact-00.csv" in problem for problem in problems)


def test_check_final_rejects_a_recorded_correction_without_replacements(tool, tmp_path):
    def mangle(document, report):
        document["corrections"][0]["status"] = "recorded"

    document, _ = _synthetic_tree(tool, tmp_path, mangle=mangle)
    baseline = tool.parse_baseline(document)
    problems = tool.check_final(baseline, root=tmp_path)
    assert any("R1" in problem for problem in problems)
