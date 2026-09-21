"""Focused tests for WP5 — the Stage-2 decision synthesis.

WP5 measures nothing, so its tests are about two things only: that it **reads** the frozen
slices rather than declaring their numbers itself, and that it **refuses** to publish a
decision built on a missing, failed or self-contradictory slice. The reviewer's own
requirements are pinned too: the seven questions, the plan's four verdict words, the
``not detected`` / ``not resolvable`` distinction, D1 outside the Stage-2 scope, and a
recommendation that is small and run-level rather than a dense sweep.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from udv_echo_process.analysis import sparse_decision_synthesis as sds

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"
REPORT_DIR = ROOT / "reports" / "sparse-mixer-live-1"
COMMITTED_NAMES = ("decision-table.csv", "decision-table.json", "decision-table.md")

QUESTIONS = {
    "pitch_x_burst_interaction",
    "e8_versus_e20",
    "e64_versus_e20",
    "e128_versus_e64",
    "prf",
    "dense_second_pass",
    "sensitivity_d1",
}


@pytest.fixture(scope="module")
def model():
    return sds.build_decision_synthesis(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(model):
    return sds.def_document(model)


@pytest.fixture(scope="module")
def slice_documents():
    """Every frozen slice's own document, read from the directory that slice lives in."""
    documents = {}
    for name, filename, _, directory in sds.SLICES:
        location = Path(directory) if directory else REPORT_DIR
        documents[name] = json.loads((location / filename).read_text(encoding="utf-8"))
    return documents


def _copy_report(tmp_path: Path, name: str | None = None, document: dict | None = None):
    """A copy of the committed report directory, optionally with one slice replaced."""
    import shutil

    target = tmp_path / "report"
    shutil.copytree(REPORT_DIR, target)
    if name is not None and document is not None:
        (target / name).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    elif name is not None:
        (target / name).unlink()
    return target


# ── what it reads ──────────────────────────────────────────────────────


def test_the_frozen_slices_are_read_with_their_digests_and_revisions(
    model,
) -> None:
    assert [ref.name for ref in model.slices] == ["WP0", "WP1", "WP2", "WP3", "WP4", "stage2"]
    for ref in model.slices:
        assert ref.ok is True
        assert ref.checks_passed == ref.checks_total > 0
        assert ref.recorded_revision, ref.name
        directory = Path(sds.REPORT_DIR)
        if ref.name == "stage2":
            directory = Path("reports/stage2-e20-e64")
        elif not Path(directory / ref.path).exists():
            directory = Path(sds.REPORT_DIR)
        digest = sds.hashlib.sha256((directory / ref.path.split("/")[-1]).read_bytes())
        assert ref.sha256 == digest.hexdigest(), ref.name


def test_every_floor_is_the_source_slices_own_number(model, slice_documents) -> None:
    by_name = {floor.name: floor for floor in model.floors}
    wp1 = {job["job"]: job for job in slice_documents["WP1"]["jobs"]}
    assert by_name["between-run reference, depth-resolved"].value_mm_s == pytest.approx(
        slice_documents["WP2"]["floor"]["depth_resolved"]["value_mm_s"], rel=1e-12
    )
    assert by_name["between-run reference, depth-averaged"].value_mm_s == pytest.approx(
        slice_documents["WP2"]["floor"]["depth_averaged"]["value_mm_s"], rel=1e-12
    )
    assert by_name["burst-4 job's own anchor spread"].value_mm_s == pytest.approx(
        wp1["burst-4"]["spread"]["mean"], rel=1e-12
    )
    assert by_name["burst-18 job's own anchor spread"].value_mm_s == pytest.approx(
        wp1["burst-18"]["spread"]["mean"], rel=1e-12
    )
    for floor in model.floors:
        assert floor.source_slice in {"WP1", "WP2", "stage2"}


def test_the_quoted_effects_are_the_slices_own_numbers(model, slice_documents) -> None:
    wp3 = slice_documents["WP3"]
    wp4 = slice_documents["WP4"]
    assert model.row("pitch_x_burst_interaction").observed_effect_mm_s == pytest.approx(
        wp3["interaction"]["scalar_reduction_mm_s"], rel=1e-12
    )
    stage2 = slice_documents["stage2"]
    assert model.row("e64_versus_e20").observed_effect_mm_s == pytest.approx(
        max(abs(float(contrast["oriented_mm_s"])) for contrast in stage2["contrasts"]),
        rel=1e-12,
    )
    assert model.row("e128_versus_e64").observed_effect_mm_s == pytest.approx(
        wp4["steps"][2]["mean_difference_min_mm_s"], rel=1e-12
    )


def test_no_row_carries_a_number_the_slices_do_not(model) -> None:
    """Every numeric claim in the table traces to one of the three effects above."""
    by_key = {row.key: row for row in model.rows}
    numeric = {
        round(row.observed_effect_mm_s, 12)
        for row in model.rows
        if row.observed_effect_mm_s is not None
    }
    assert numeric == {
        round(by_key[key].observed_effect_mm_s, 12)
        for key in (
            "pitch_x_burst_interaction",
            "e8_versus_e20",
            "e64_versus_e20",
            "e128_versus_e64",
        )
    }
    for row in model.rows:
        if row.floor_mm_s is not None:
            assert any(
                abs(row.floor_mm_s - floor.value_mm_s) < 1e-9 for floor in model.floors
            ), row.key


# ── the reviewer's requirements ────────────────────────────────────────


def test_the_seven_questions_and_the_plans_four_verdict_words(model) -> None:
    assert {row.key for row in model.rows} == QUESTIONS
    assert len(model.rows) == 7
    assert {row.verdict for row in model.rows} <= set(sds.VERDICTS)
    assert sds.VERDICTS == ("keep", "defer", "replace", "requires diagnostic")
    # every word is used by these seven rows, and each row's class is one of the four
    assert {row.verdict for row in model.rows} == set(sds.VERDICTS)
    assert {row.decision_class for row in model.rows} <= set(sds.DECISION_CLASSES)


def test_the_not_detected_and_not_resolvable_classes_are_both_present_and_distinct(
    model,
) -> None:
    classes = {row.key: row.decision_class for row in model.rows}
    assert classes["pitch_x_burst_interaction"] == "not resolvable with this design"
    assert classes["e64_versus_e20"] == "not detected at this design's floors"
    assert classes["e128_versus_e64"] == "not detected at this design's floors"
    assert classes["sensitivity_d1"] == "not measured"
    assert classes["prf"] == "measured and resolved"
    # and the separability limitation is stated as such, never as absence
    interaction = model.row("pitch_x_burst_interaction")
    assert "NOT evidence that the interaction is absent" in interaction.interpretation
    assert "limitation of separability" in interaction.interpretation


def test_the_interaction_row_uses_the_depth_averaged_endpoint(model) -> None:
    row = model.row("pitch_x_burst_interaction")
    averaged = next(
        floor for floor in model.floors if floor.endpoint.startswith("depth-averaged")
    )
    resolved = next(
        floor for floor in model.floors if floor.endpoint.startswith("depth-resolved")
    )
    assert row.floor_mm_s == pytest.approx(averaged.value_mm_s, rel=1e-12)
    assert row.floor_mm_s != pytest.approx(resolved.value_mm_s, rel=1e-12)
    assert (
        abs(row.observed_effect_mm_s) > averaged.value_mm_s
    )  # exceeds the scalar floor
    assert abs(row.observed_effect_mm_s) < min(
        floor.value_mm_s
        for floor in model.floors
        if floor.endpoint == "block-local anchor spread inside one job"
        and floor.name.startswith("burst")
    )


def test_the_e64_row_reads_the_campaign_and_records_what_it_said_before(
    model, slice_documents
) -> None:
    """The one row this follow-up moves, with the state it moved from still on the record."""
    row = model.row("e64_versus_e20")
    stage2 = slice_documents["stage2"]
    assert row.verdict == "replace"
    assert row.decision_class == "not detected at this design's floors"
    assert row.floor_mm_s == pytest.approx(stage2["screening_floor_mm_s"], rel=1e-12)
    assert row.floor_mm_s != pytest.approx(4.235, rel=1e-6)  # never the earlier pass's screen
    # the observed effect is the campaign's largest |contrast|, and it is inside the floor
    assert row.observed_effect_mm_s == pytest.approx(
        max(abs(float(c["oriented_mm_s"])) for c in stage2["contrasts"]), rel=1e-12
    )
    assert abs(row.observed_effect_mm_s) < row.floor_mm_s
    assert "not detected" in row.interpretation.lower()
    assert "not the same as absent" in row.interpretation
    assert "do not spend further acquisition effort on emissions 64" in row.interpretation
    # the prior state is quoted, so a revised decision can be audited
    assert row.prior_state is not None
    assert "not resolvable with this pass's design" in row.prior_state
    assert "defer" in row.prior_state


def test_the_e128_row_carries_its_cost_and_the_e8_row_its_advantage(model) -> None:
    e128 = model.row("e128_versus_e64")
    assert e128.verdict == "replace"
    assert "no depth-averaged improvement" in e128.interpretation
    assert "cost" in e128.interpretation
    e8 = model.row("e8_versus_e20")
    assert e8.verdict == "keep"
    assert "no stability loss is detected" in e8.interpretation
    assert "bandwidth" in e8.interpretation


def test_d1_is_outside_the_stage_2_scope_and_requires_a_diagnostic(model) -> None:
    row = model.row("sensitivity_d1")
    assert row.scope == sds.OUTSIDE_SCOPE
    assert row.verdict == "requires diagnostic"
    assert row.floor_mm_s is None
    assert "echo/energy" in row.evidence or "echo or energy" in row.evidence
    assert "not measured" in row.evidence.lower()


def test_the_dense_pass_is_refused_rather_than_deferred_for_time(model) -> None:
    row = model.row("dense_second_pass")
    assert row.verdict != "keep"
    assert "reproduce these floors" in row.interpretation
    assert any("dense second pass" in text for text in model.campaign.refused)


def test_the_five_gate_questions_are_answered_in_the_plans_order(model) -> None:
    assert [answer.order for answer in model.answers] == [1, 2, 3, 4, 5]
    assert "which axes can be collapsed or fixed" in model.answers[0].question
    assert "which interactions matter" in model.answers[1].question
    assert "which levels are redundant" in model.answers[2].question
    assert "denser second acquisition" in model.answers[3].question
    assert "which small set of new conditions" in model.answers[4].question
    # the gate's own answers, as the plan demands them
    assert "not collapsed" in model.answers[0].answer
    assert "pitch x burst" in model.answers[1].answer
    assert (
        "E128" in model.answers[2].answer and "not redundant" in model.answers[2].answer
    )
    assert "not as a dense pass" in model.answers[3].answer
    assert (
        "the one bounded set this pass recommended was the eight-job Stage-2 campaign"
        in model.answers[4].answer
    )
    assert "It has since been run" in model.answers[4].answer
    assert (
        "No further emissions acquisition is currently recommended"
        in model.answers[4].answer
    )
    # the answer quotes the campaign's own sequence, in its own order - the whole sequence, so
    # a second copy of it cannot drift back to the pre-counterbalancing design unnoticed
    answer = model.answers[4].answer
    assert ", ".join(model.campaign.sequence) in answer
    assert [name for name in model.campaign.sequence if name in answer] == list(
        model.campaign.sequence
    )
    assert "E20-A, E64-A, E20-B" not in answer
    for name in model.campaign.sequence:
        assert answer.count(name) == 1, name


def test_the_recommendation_samples_both_levels_in_one_campaign(model) -> None:
    """The review's correction: an emissions-64-only top-up is not enough.

    Comparing new emissions-64 runs with this pass's emissions-20 runs would separate them
    by a campaign as well as by an emission level, so the recommendation samples both
    levels alternately inside one campaign and refuses the one-sided design by name.
    """
    campaign = model.campaign
    # the block is history: it was recommended, and it has been acquired
    assert campaign.execution is not None
    assert campaign.recommended is False
    assert campaign.recommended is (campaign.execution is None)
    assert campaign.recordings == 8
    assert campaign.sequence == (
        "E20-A",
        "E64-A",
        "E64-B",
        "E20-B",
        "E20-C",
        "E64-C",
        "E64-D",
        "E20-D",
    )
    assert len(campaign.sequence) == campaign.recordings
    assert sum(name.startswith("E20") for name in campaign.sequence) == 4
    assert sum(name.startswith("E64") for name in campaign.sequence) == 4
    # four pairs, each holding one of each level, so slow drift is shared
    pairs = [
        (campaign.sequence[index], campaign.sequence[index + 1])
        for index in range(0, len(campaign.sequence), 2)
    ]
    assert len(pairs) == 4
    assert all({first[:3], second[:3]} == {"E20", "E64"} for first, second in pairs)
    # and the within-pair order is counterbalanced: the level that leads alternates
    assert [first[:3] for first, _ in pairs] == ["E20", "E64", "E20", "E64"]
    assert len(campaign.conditions) == 2
    assert "emissions 20" in campaign.conditions[0]
    assert "emissions 64" in campaign.conditions[1]
    for setting in ("1.850 mm", "50 gates", "burst 10", "PRF 600 us"):
        assert setting in campaign.conditions[0], setting
        assert setting in campaign.conditions[1], setting
    assert len(campaign.buys) >= 4
    assert any(
        "contemporaneous" in text or "inside one campaign" in text
        for text in campaign.buys
    )
    # the pair design is a design decision, published with the set
    assert "part of the design" in campaign.pair_design
    assert "counterbalanced" in campaign.pair_design
    assert "one campaign block, not two" in campaign.pair_design
    assert "oriented as E64 minus E20" in campaign.pair_design
    assert "no acquisition-layer change" in campaign.pair_design
    assert any("emissions-64-only" in text for text in campaign.refused)
    assert any("4.235" in text for text in campaign.refused)
    assert any("dense second pass" in text for text in campaign.refused)
    assert len(campaign.refused) >= 4


def test_the_acceptance_criterion_is_stated_in_advance_and_is_contemporaneous(
    model,
) -> None:
    """What the Stage-2 campaign must report, and the only two decisions allowed."""
    acceptance = model.campaign.acceptance
    for required in (
        "the four emissions-20 observations",
        "the four emissions-64 observations",
        "each level's own run-to-run spread",
        "the four adjacent paired E64-to-E20 contrasts individually and oriented E64 minus E20",
        "the full cross-run range as context",
        "measured inside that campaign",
    ):
        assert required in acceptance, required
    assert "Resolved difference" in acceptance
    assert (
        "consistently larger than the contemporaneous between-run variation"
        in acceptance
    )
    assert "Unresolved overlap" in acceptance
    # the correction: the new block is not screened against this pass's floor
    assert "one side of the 4.235 mm/s between-run floor" not in acceptance
    assert "this pass's floor kept as context" in " ".join(model.campaign.refused)


def test_the_verdict_replace_is_a_cost_decision_not_a_superiority_claim(model) -> None:
    """`replace` on E128 means stop acquiring it here, not that E64 is proven better."""
    row = next(row for row in model.rows if row.key == "e128_versus_e64")
    assert row.verdict == "replace"
    assert (
        "do not spend further acquisition effort on emissions 128 in this design"
        in (row.interpretation)
    )
    assert "scientifically proven superior" in row.interpretation
    assert "cost, not effect" in row.interpretation


def test_the_e64_row_now_overturns_on_replication_not_on_one_more_recording(model) -> None:
    """After the campaign ran, the measurement that would overturn the row is a harder one."""
    row = next(row for row in model.rows if row.key == "e64_versus_e20")
    assert "exceeds a contemporaneous campaign's own floor" in row.overturning_measurement
    assert "consistent direction" in row.overturning_measurement
    assert "more runs per level inside one campaign" in row.overturning_measurement
    assert "A single extra pair would not do it" in row.overturning_measurement


def test_the_e64_row_cites_the_campaign_slice_and_no_other_row_moved(
    model, slice_documents
) -> None:
    """The follow-up's whole point: one row reads the campaign, the other six are untouched."""
    row = model.row("e64_versus_e20")
    assert "pairs.json#contrasts" in row.evidence_refs
    assert any("pairs.json" in ref for ref in row.evidence_refs)
    stage2 = next(ref for ref in model.slices if ref.name == "stage2")
    assert stage2.ok and stage2.checks_passed == stage2.checks_total
    assert stage2.recorded_revision == slice_documents["stage2"]["analysis_commit"]
    assert stage2.path == "pairs.json"

    # two rows moved: the E64-vs-E20 row, which now reads the campaign, and the dense-pass
    # row, whose "measure this next" claim the campaign has since answered. The other five
    # keep both their verdicts and an empty prior state.
    unchanged = {
        "pitch_x_burst_interaction": ("defer", "not resolvable with this design"),
        "e8_versus_e20": ("keep", "not detected at this design's floors"),
        "e128_versus_e64": ("replace", "not detected at this design's floors"),
        "prf": ("keep", "measured and resolved"),
        "sensitivity_d1": ("requires diagnostic", "not measured"),
    }
    for key, (verdict, decision_class) in unchanged.items():
        other = model.row(key)
        assert (other.verdict, other.decision_class) == (verdict, decision_class), key
        assert other.prior_state is None, key
    dense = model.row("dense_second_pass")
    assert (dense.verdict, dense.decision_class) == ("defer", "not resolvable with this design")
    assert dense.prior_state is not None
    assert "E20 against E64" in dense.prior_state


def test_the_campaign_is_recorded_as_executed_with_the_numbers_it_returned(model) -> None:
    """The recommendation is no longer pending, and the block says what it returned."""
    execution = model.campaign.execution
    assert execution is not None
    assert execution.dataset == "data/stage2-e20-e64"
    assert execution.plan == "stage2-e20-e64"
    assert execution.jobs == model.campaign.recordings == 8
    assert "unresolved overlap" in execution.outcome
    assert set(execution.contrast_mm_s) == set("ABCD")
    assert execution.scalar_floor_mm_s > execution.depth_floor_mm_s * 0
    assert "inside" in execution.note and "per-gate floor" in execution.note


# ── the artefacts and the refusals ─────────────────────────────────────


def test_the_dense_pass_row_describes_the_set_it_actually_recommends(model) -> None:
    """The row must not describe the earlier pointwise surface's automation.

    The block the row once pointed to changed neither resolution nor gates - eight run-level
    jobs at the reference window's own settings, its one varying run-wide value set by the
    operator and verified by the compile's read-back - and it has since been acquired, so the
    row now describes it in the past tense and points at no future work.
    """
    row = next(row for row in model.rows if row.key == "dense_second_pass")
    assert row.verdict == "defer"
    assert "has been acquired and analysed" in row.automation
    assert "Nothing about that block is future work" in row.automation
    assert row.prior_state is not None
    assert "emissions per profile" in row.automation
    assert "set by the operator" in row.automation
    assert "verified by the compile's read-back" in row.automation
    assert "writes only resolution and gates" not in row.automation
    assert "addressed by the bounded paired block rather than by density" in row.interpretation
    assert "did not detect a stable emissions-64 benefit" in row.interpretation


def test_the_csv_is_the_column_contract(model) -> None:
    raw = (REPORT_DIR / sds.CSV_NAME).read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    lines = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    assert list(lines[0].keys()) == list(sds.CSV_COLUMNS)
    assert sds.CSV_COLUMNS[-1] == "prior_state"
    assert len(lines) == len(model.rows) == 7
    assert {row["verdict"] for row in lines} == set(sds.VERDICTS)
    for row in lines:
        assert row["decision_class"] in sds.DECISION_CLASSES
        assert row["interpretation"] and row["overturning_measurement"]
        assert " " in row["applicable_floor"]  # a floor is described, not just numbered


def test_the_two_new_floors_are_the_campaign_slices_own_numbers(
    model, slice_documents
) -> None:
    stage2 = slice_documents["stage2"]
    scalar = next(
        floor for floor in model.floors if floor.name == "the Stage-2 campaign's own scalar floor"
    )
    per_gate = next(
        floor for floor in model.floors if floor.name == "the Stage-2 campaign's own per-gate floor"
    )
    assert scalar.value_mm_s == pytest.approx(stage2["screening_floor_mm_s"], rel=1e-12)
    assert per_gate.value_mm_s == pytest.approx(stage2["depth_resolved_floor_mm_s"], rel=1e-12)
    assert scalar.source_slice == per_gate.source_slice == "stage2"
    assert not scalar.endpoint.startswith(("depth-resolved", "depth-averaged"))
    assert not per_gate.endpoint.startswith(("depth-resolved", "depth-averaged"))


FORBIDDEN_FUTURE_STATE = (
    "Only that second limitation is worth spending recordings on",
    "only it is worth measuring again",
    "Nothing else is recommended, and the acceptance",
    "is what should be measured next",
    "the recommended block changes neither resolution nor gates",
    "E128 is replaced by E64 on cost",
)


def test_no_stale_future_state_survives_once_the_campaign_has_run(model, document) -> None:
    """The review's pin: after execution exists, nothing may still read as a pending plan."""
    assert model.campaign.execution is not None
    prose = " ".join(
        (
            *(answer.answer for answer in model.answers),
            model.campaign.justification,
            model.campaign.pair_design,
            model.row("dense_second_pass").interpretation,
            model.row("dense_second_pass").automation,
            model.row("dense_second_pass").observed_effect,
            model.row("dense_second_pass").overturning_measurement,
            model.row("e64_versus_e20").interpretation,
        )
    )
    for forbidden in FORBIDDEN_FUTURE_STATE:
        assert forbidden not in prose, forbidden
    rendered = json.dumps(document)
    for forbidden in FORBIDDEN_FUTURE_STATE:
        assert forbidden not in rendered, forbidden


def test_the_prose_states_that_nothing_further_is_recommended() -> None:
    prose = (REPORT_DIR / sds.MD_NAME).read_text(encoding="utf-8")
    assert "What was recommended, what it returned, and what is refused" in prose
    assert "No further acquisition is recommended from this workstream" in prose
    assert "No further emissions acquisition is currently recommended" in prose
    # the pre-campaign heading must not be the one a reader sees
    assert "## What is recommended next, and what is refused" not in prose
    # and the completed block is named as completed, not as pending
    assert "this block was this pass's one recommendation, and it has been acquired" in prose


def test_the_committed_table_records_a_real_generator_revision() -> None:
    """The committed artefacts must not carry a test's placeholder revision.

    This is the check that catches a test writing into the report directory it reads:
    the artefacts would still regenerate consistently, so only the recorded revision
    shows that the published pair was produced by a test run.
    """
    document = json.loads((REPORT_DIR / sds.DOC_NAME).read_text(encoding="utf-8"))
    recorded = str(document["analysis_commit"])
    assert recorded, "the committed decision document records no revision"
    assert recorded != COMMIT, (
        "the committed decision table records the test suite's placeholder revision, "
        "which means a test wrote into reports/"
    )
    assert len(recorded) >= 7 and all(
        character in "0123456789abcdef" for character in recorded
    ), recorded


def test_the_document_carries_the_slices_the_definitions_and_the_gate(
    model, document
) -> None:
    assert document["ok"] is True
    assert all(document["checks"].values())
    assert len(document["checks"]) == len(model.checks)
    assert len(model.checks) >= 15
    assert set(document["slices"]) == {ref.name for ref in model.slices}
    assert all(entry["recorded_revision"] for entry in document["slices"].values())
    assert (
        "not resolvable with this design" in document["definitions"]["decision_class"]
    )
    assert "NOT evidence of absence" in document["definitions"]["decision_class"]
    assert "measures nothing" in document["definitions"]["no_measurement_here"]
    assert document["table"] == sds.CSV_NAME
    assert document["campaign"]["recordings"] == 8
    assert document["campaign"]["sequence"] == list(model.campaign.sequence)
    assert document["analysis_commit"] == COMMIT


def test_two_builds_are_byte_identical_and_the_committed_pair_reproduces(
    tmp_path, monkeypatch
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for directory in (first, second):
        sds.write_decision_synthesis(
            REPORT_DIR, output_dir=directory, analysis_commit=COMMIT
        )
    for name in (sds.CSV_NAME, sds.DOC_NAME, sds.MD_NAME):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name

    monkeypatch.chdir(ROOT)
    recorded = json.loads((REPORT_DIR / sds.DOC_NAME).read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    third = tmp_path / "c"
    sds.write_decision_synthesis(REPORT_DIR, output_dir=third, analysis_commit=recorded)
    for name in (sds.CSV_NAME, sds.DOC_NAME, sds.MD_NAME):
        committed = (REPORT_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert (third / name).read_bytes() == committed, name


def test_a_missing_slice_is_refused_by_name(tmp_path) -> None:
    report = _copy_report(tmp_path, "pitch-burst.json")
    with pytest.raises(sds.DecisionSynthesisError, match="missing"):
        sds.build_decision_synthesis(report_dir=report, analysis_commit=COMMIT)


def test_a_slice_that_failed_its_own_gate_is_refused(tmp_path, slice_documents) -> None:
    document = json.loads(json.dumps(slice_documents["WP2"]))
    key = min(document["checks"])
    document["checks"][key] = False
    report = _copy_report(tmp_path, "reference-floor.json", document)
    with pytest.raises(sds.DecisionSynthesisError, match="did not hold its own gate"):
        sds.build_decision_synthesis(report_dir=report, analysis_commit=COMMIT)


def test_slices_that_disagree_about_a_floor_are_refused(
    tmp_path, slice_documents
) -> None:
    document = json.loads(json.dumps(slice_documents["WP3"]))
    document["floors"]["depth_averaged"]["value_mm_s"] = 5.5
    report = _copy_report(tmp_path, "pitch-burst.json", document)
    with pytest.raises(sds.DecisionSynthesisError, match="disagree about a floor"):
        sds.build_decision_synthesis(report_dir=report, analysis_commit=COMMIT)


def test_a_refusal_writes_nothing(tmp_path, slice_documents) -> None:
    document = json.loads(json.dumps(slice_documents["WP1"]))
    document["analysis_commit"] = ""
    report = _copy_report(tmp_path, "anchor-floor.json", document)
    before = {
        name: (report / name).read_bytes()
        for name in (sds.CSV_NAME, sds.DOC_NAME, sds.MD_NAME)
        if (report / name).exists()
    }
    with pytest.raises(sds.DecisionSynthesisError, match="no generator revision"):
        sds.write_decision_synthesis(report, output_dir=report, analysis_commit=COMMIT)
    # a refusal leaves whatever is already published untouched - it writes nothing new
    for name, content in before.items():
        assert (report / name).read_bytes() == content, name
    assert not (report / "half-written.tmp").exists()


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_report_dir(
    tmp_path, capsys, monkeypatch
) -> None:
    from udv_echo_process.cli import _COMMANDS

    assert "sparse-decision" in _COMMANDS
    published = {name: (REPORT_DIR / name).read_bytes() for name in COMMITTED_NAMES}
    output = tmp_path / "out"
    with pytest.raises(SystemExit) as exit_code:
        sds.decision_main(
            [
                "--report-dir",
                REPORT_DIR.as_posix(),
                "--output-dir",
                str(output),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert exit_code.value.code == 0
    assert "checks  : all pass" in capsys.readouterr().out
    assert (output / sds.CSV_NAME).is_file() and (output / sds.MD_NAME).is_file()
    # the command must never write into the report it reads unless it is told to
    for name, content in published.items():
        assert (REPORT_DIR / name).read_bytes() == content, name

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as failed:
        sds.decision_main(
            [
                "--report-dir",
                str(broken),
                "--output-dir",
                str(tmp_path / "broken-out"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert failed.value.code == 1
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "broken-out" / sds.CSV_NAME).exists()


def test_the_prose_carries_the_answers_the_table_and_the_campaign() -> None:
    doc = " ".join((REPORT_DIR / sds.MD_NAME).read_text(encoding="utf-8").split())
    for answer in (
        "1. which axes can be collapsed or fixed?",
        "2. which interactions matter?",
        "3. which levels are redundant?",
        "4. is a denser second acquisition justified at all?",
        "5. if it is, which small set of new conditions, and what does each buy?",
    ):
        assert answer in doc, answer
    assert "## The decision table" in doc
    assert "The set, in acquisition order" in doc
    assert "`E20-A` -> `E64-A`" in doc
    assert "`E64-D`" in doc
    assert "8 run-level jobs" in doc
    assert "the one bounded set this pass recommended was the eight-job Stage-2 campaign" in doc
    assert "Acceptance criterion, stated in advance" in doc
    assert "Refused, on this pass's own evidence" in doc
    assert "No new measurement" in doc
    assert "No broad sweep" in doc
    assert "`replace`" in doc and "`requires diagnostic`" in doc
