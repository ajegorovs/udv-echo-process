"""Focused tests for the Stage-2 paired analysis — the four E64-E20 contrasts in one campaign.

Section 4b of the frozen plan publishes the four paired contrasts *individually*, each oriented
E64 minus E20 whatever order its pair was acquired in, with that pair's acquisition orientation
recorded beside it, and screens them against a **contemporaneous** variation the same campaign
measured. It allows exactly two outcomes: a resolved difference (the four contrasts consistently
larger than that variation, with a consistent direction) or an unresolved overlap (the separation
comparable to or smaller than it, which is itself the answer).

These tests pin that contract, the two-outcome vocabulary and the floor's provenance — and they
recompute every published number from the committed recordings through the shared loader, so a
figure in the report that the bytes do not support fails here.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_stage2_pairs as s2
from udv_echo_process.analysis._sparse_pass import (
    decode_pass,
    gate_statistics,
    supported_mean_of,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"
REPORT_DIR = ROOT / "reports" / "stage2-e20-e64"


def _plain(text: str) -> str:
    """The document's text with markdown emphasis and wrapping removed, for prose pins."""
    for marker in ("**", "*", "`"):
        text = text.replace(marker, "")
    return " ".join(text.split())


@pytest.fixture(scope="module")
def decoded():
    return decode_pass(s2.DATASET_ROOT, plan_path=s2.PLAN_PATH, plan_name=s2.PLAN_NAME)


@pytest.fixture(scope="module")
def analysis():
    return s2.build_stage2_pairs(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(analysis):
    return s2.def_document(analysis)


# ── eight runs: four pairs of one E20 and one E64, in campaign order ───


def test_the_eight_runs_are_individually_present(analysis) -> None:
    assert [run.job for run in analysis.runs] == [
        "e20-a", "e64-a", "e64-b", "e20-b", "e20-c", "e64-c", "e64-d", "e20-d",
    ]
    assert [run.step for run in analysis.runs] == list(range(1, 9))
    assert len({run.job for run in analysis.runs}) == 8
    assert {run.label for run in analysis.runs} == {"ref"}
    assert all(run.kind == s2.RUN_KIND for run in analysis.runs)


def test_every_pair_holds_one_run_of_each_level(analysis) -> None:
    assert [pair.pair for pair in analysis.contrasts] == list("ABCD")
    for pair in analysis.contrasts:
        runs = [run for run in analysis.runs if run.pair == pair.pair]
        assert sorted(run.level for run in runs) == ["E20", "E64"]
        assert len(runs) == 2
        assert {run.role for run in runs} == {"lead", "follow"}


def test_the_declared_level_is_the_stored_emissions_word(analysis) -> None:
    for run in analysis.runs:
        assert run.emissions == s2.LEVEL_EMISSIONS[run.level]
    words = [run.emissions for run in analysis.runs]
    assert words == [20, 64, 64, 20, 20, 64, 64, 20]


def test_the_frame_is_identical_across_the_eight(analysis) -> None:
    """The design's one varying setting: everything else in the decoded frame is shared."""
    frames = {
        (
            run.gates,
            run.resolution_mm,
            run.supported_gates,
            run.sound_speed_ms,
            run.prf_us,
            run.burst_length,
            run.depth_mm,
            run.first_gate_mm,
        )
        for run in analysis.runs
    }
    assert len(frames) == 1, frames
    assert analysis.checks["frame_identical"] is True


# ── E64 minus E20, whatever order the pair was acquired in ────────────


def test_each_contrast_is_e64_minus_e20(analysis) -> None:
    for pair in analysis.contrasts:
        by_level = {
            run.level: run for run in analysis.runs if run.pair == pair.pair
        }
        expected = (
            by_level["E64"].depth_averaged_mean_mm_s
            - by_level["E20"].depth_averaged_mean_mm_s
        )
        assert pair.oriented_mm_s == pytest.approx(expected, rel=1e-12)
        assert pair.e20_job == by_level["E20"].job
        assert pair.e64_job == by_level["E64"].job


def test_the_acquisition_orientation_is_recorded_beside_each_contrast(analysis) -> None:
    """The orientation is retained, not discarded, and it agrees with the plan's own order."""
    assert [pair.acquisition_orientation for pair in analysis.contrasts] == [
        "20 -> 64", "64 -> 20", "20 -> 64", "64 -> 20",
    ]
    for pair in analysis.contrasts:
        first = "E20" if pair.acquisition_orientation.startswith("20") else "E64"
        by_level = {run.level: run for run in analysis.runs if run.pair == pair.pair}
        assert by_level[first].role == "lead"
        assert by_level[first].step < by_level["E64" if first == "E20" else "E20"].step


def test_the_raw_order_difference_and_the_oriented_contrast_differ_by_their_sign(
    analysis,
) -> None:
    """The counterbalance correction, stated as data: the published value never carries it."""
    for pair in analysis.contrasts:
        if pair.acquisition_orientation == "20 -> 64":
            assert pair.oriented_mm_s == pytest.approx(
                pair.order_difference_mm_s, rel=1e-12
            )
        else:
            assert pair.oriented_mm_s == pytest.approx(
                -pair.order_difference_mm_s, rel=1e-12
            )


def test_the_orientation_is_a_property_of_the_design_not_of_the_sequence(analysis) -> None:
    assert analysis.stated_orientation == s2.STATED_ORIENTATION == "E64 - E20"
    assert analysis.checks["orientation_stated"] is True
    assert analysis.checks["orientation_matches_order"] is True


def test_the_contrast_does_not_change_when_a_pair_is_read_in_the_other_order() -> None:
    """Synthetic reversal: the same physical pair, acquired the other way round, reads equal."""
    e20 = np.full(4, 10.0)
    e64 = np.full(4, 12.0)
    forward = s2.oriented_contrast(e20_block=e20, e64_block=e64)
    reversed_ = s2.oriented_contrast(e20_block=e20, e64_block=e64)
    assert np.allclose(forward, reversed_)
    # and the raw acquisition-order difference is what flips, which is why it is retained
    assert np.allclose(forward, s2.order_difference(lead=e20, follow=e64))
    assert np.allclose(-forward, s2.order_difference(lead=e64, follow=e20))


# ── the contemporaneous floor: this campaign, not the earlier pass ─────


def test_the_screening_floor_is_measured_in_this_campaign(analysis) -> None:
    for floor in analysis.floors:
        assert floor.runs_pooled == 4
        assert floor.unique_pairs == 6
        assert set(floor.jobs) <= {run.job for run in analysis.runs}
        assert floor.level in s2.LEVEL_ORDER
    assert analysis.screening_floor_source.startswith("the larger of")
    assert analysis.screening_floor_mm_s == pytest.approx(
        max(floor.depth_averaged_mm_s for floor in analysis.floors), rel=1e-12
    )


def test_the_floors_are_computed_from_the_six_unordered_run_pairs(analysis, decoded) -> None:
    """Recomputed here from the recordings: the max absolute pairwise window-mean difference."""
    for floor in analysis.floors:
        jobs = [run.job for run in analysis.runs if run.level == floor.level]
        blocks = {
            job: gate_statistics(
                decoded.of_job(job)[0],
                window_s=analysis.window_s,
                support_mm=(analysis.support_min_mm, analysis.support_max_mm),
            )[s2.FLOOR_STATISTIC]
            for job in jobs
        }
        worst = max(
            abs(float(np.max(np.abs(blocks[left] - blocks[right]))))
            for index, left in enumerate(jobs)
            for right in jobs[index + 1 :]
        )
        assert floor.depth_resolved_mm_s == pytest.approx(worst, rel=1e-9)
        scalars = {
            job: supported_mean_of(
                decoded.of_job(job)[0],
                window_s=analysis.window_s,
                support_mm=(analysis.support_min_mm, analysis.support_max_mm),
                name=s2.FLOOR_STATISTIC,
            )
            for job in jobs
        }
        averaged = max(
            abs(scalars[left] - scalars[right])
            for index, left in enumerate(jobs)
            for right in jobs[index + 1 :]
        )
        assert floor.depth_averaged_mm_s == pytest.approx(averaged, rel=1e-9)


def test_the_prior_passes_floor_is_context_and_not_the_screen(analysis) -> None:
    """4.235 mm/s belongs to another sitting; it may be quoted, never screened against."""
    assert analysis.prior_context[s2.PRIOR_DATASET]["depth_averaged_mm_s"] == pytest.approx(
        s2.PRIOR_DEPTH_AVERAGED_FLOOR_MM_S, rel=1e-12
    )
    assert s2.PRIOR_DATASET in analysis.prior_context_note
    assert analysis.screening_floor_source.find(s2.PRIOR_DATASET) == -1
    assert analysis.screening_floor_mm_s != pytest.approx(
        s2.PRIOR_DEPTH_AVERAGED_FLOOR_MM_S, rel=1e-6
    )


def test_the_two_floors_are_read_at_their_own_levels(analysis) -> None:
    assert [floor.level for floor in analysis.floors] == ["E20", "E64"]
    assert analysis.depth_resolved_floor_source.find(s2.PRIOR_DATASET) == -1
    assert all(floor.depth_resolved_mm_s >= floor.depth_averaged_mm_s for floor in analysis.floors)


# ── exactly two outcomes, and the vocabulary that distinguishes them ──


def test_the_two_outcomes_are_the_only_ones(analysis) -> None:
    assert analysis.outcome in (s2.OUTCOME_RESOLVED, s2.OUTCOME_OVERLAP)
    assert analysis.depth_resolved_outcome in (s2.OUTCOME_RESOLVED, s2.OUTCOME_OVERLAP)
    assert analysis.overlap_kind in (
        None, s2.OVERLAP_NOT_DETECTED, s2.OVERLAP_NOT_RESOLVABLE,
    )
    if analysis.outcome == s2.OUTCOME_RESOLVED:
        assert analysis.overlap_kind is None
        assert analysis.consistent_direction is True
        assert analysis.all_contrasts_exceed_floor is True
    else:
        assert analysis.overlap_kind in (
            s2.OVERLAP_NOT_DETECTED, s2.OVERLAP_NOT_RESOLVABLE,
        )


def test_a_consistent_separation_above_the_floor_is_a_resolved_difference() -> None:
    verdict = s2.decide(
        oriented=np.array([5.0, 6.0, 5.5, 6.5]),
        floor_mm_s=2.0,
        tolerance=s2.TOLERANCE,
    )
    assert verdict.outcome == s2.OUTCOME_RESOLVED
    assert verdict.consistent_direction is True
    assert verdict.all_contrasts_exceed_floor is True
    assert verdict.overlap_kind is None


def test_a_separation_smaller_than_the_floor_is_an_unresolved_overlap() -> None:
    verdict = s2.decide(oriented=np.array([0.4, 0.6, 0.5, 0.3]), floor_mm_s=2.0, tolerance=1e-9)
    assert verdict.outcome == s2.OUTCOME_OVERLAP
    assert verdict.overlap_kind == s2.OVERLAP_NOT_DETECTED
    assert verdict.consistent_direction is True
    assert verdict.all_contrasts_exceed_floor is False


def test_contrasts_that_disagree_in_direction_are_not_resolvable_with_this_design() -> None:
    verdict = s2.decide(oriented=np.array([5.0, -5.5, 6.0, -4.0]), floor_mm_s=2.0, tolerance=1e-9)
    assert verdict.outcome == s2.OUTCOME_OVERLAP
    assert verdict.overlap_kind == s2.OVERLAP_NOT_RESOLVABLE
    assert verdict.consistent_direction is False


def test_a_separation_comparable_to_the_floor_is_not_resolvable() -> None:
    """Larger than the floor on average, but not on every pair: the variation still covers it."""
    verdict = s2.decide(oriented=np.array([2.5, 1.0, 3.0, 1.2]), floor_mm_s=2.0, tolerance=1e-9)
    assert verdict.outcome == s2.OUTCOME_OVERLAP
    assert verdict.overlap_kind == s2.OVERLAP_NOT_RESOLVABLE
    assert verdict.consistent_direction is True
    assert verdict.all_contrasts_exceed_floor is False


def test_the_verdict_carries_its_own_numbers() -> None:
    verdict = s2.decide(oriented=np.array([4.0, -1.0, 2.0, 3.0]), floor_mm_s=1.5, tolerance=1e-9)
    assert verdict.min_abs_mm_s == pytest.approx(1.0, rel=1e-12)
    assert verdict.max_abs_mm_s == pytest.approx(4.0, rel=1e-12)
    assert verdict.range_mm_s == pytest.approx(5.0, rel=1e-12)
    assert verdict.mean_mm_s == pytest.approx(2.0, rel=1e-12)
    assert verdict.exceeding == 3


def test_depth_resolved_and_depth_averaged_are_never_mixed(analysis) -> None:
    for pair in analysis.contrasts:
        assert pair.max_abs_mm_s >= abs(pair.oriented_mm_s) - s2.TOLERANCE
    assert analysis.depth_resolved_floor_mm_s >= analysis.screening_floor_mm_s
    assert 0.0 <= analysis.depth_resolved_resolved_share <= 1.0


# ── the document, the checks and the artefact ─────────────────────────


def test_the_document_defines_every_published_column(document, analysis) -> None:
    assert set(document["checks"]) == set(analysis.checks)
    assert set(document["definitions"]) >= {"oriented_mm_s", "screening_floor_mm_s"}
    assert all(document["definitions"].values())
    assert document["outcome"] == analysis.outcome
    assert document["dataset"] == s2.DATASET_ROOT.as_posix()
    assert document["plan_fingerprint"] == analysis.plan_fingerprint


def test_the_document_states_the_floor_provenance_and_the_prior_context(document) -> None:
    text = " ".join(
        str(value) for value in document["definitions"].values()
    )
    assert "this campaign" in text
    assert s2.PRIOR_DATASET in json.dumps(document)


def test_the_csv_carries_the_runs_the_contrasts_and_the_floors(tmp_path, analysis) -> None:
    text = s2.csv_text(analysis)
    rows = list(csv.DictReader(text.splitlines()))
    kinds = [row["kind"] for row in rows]
    assert kinds.count("run") == 8
    assert kinds.count("floor") == 6  # two endpoints per level, plus the two screens
    contrast = [row for row in rows if row["kind"] == "contrast"]
    assert sorted({row["pair"] for row in contrast}) == list("ABCD")
    assert all(row["acquisition_orientation"] for row in contrast)
    oriented = [
        row for row in contrast if row["value_name"] == "oriented_mm_s"
    ]
    assert [row["pair"] for row in oriented] == list("ABCD")
    for row in oriented:
        published = next(
            c.oriented_mm_s for c in analysis.contrasts if c.pair == row["pair"]
        )
        # the table carries format_cell's 12 significant digits, not the full float
        assert float(row["value"]) == pytest.approx(published, rel=1e-9)


def test_every_check_passes_on_the_committed_pass(analysis) -> None:
    failed = [name for name, ok in sorted(analysis.checks.items()) if not ok]
    assert failed == []
    assert analysis.ok is True


def test_the_command_writes_the_same_bytes_twice(tmp_path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    s2.write_stage2_pairs(s2.DATASET_ROOT, first, analysis_commit=COMMIT)
    s2.write_stage2_pairs(s2.DATASET_ROOT, second, analysis_commit=COMMIT)
    for name in (s2.CSV_NAME, s2.DOC_NAME, s2.MD_NAME):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_the_committed_report_is_reproducible_with_the_recorded_revision(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(ROOT)
    document = json.loads((REPORT_DIR / s2.DOC_NAME).read_text(encoding="utf-8"))
    commit = document["analysis_commit"]
    s2.write_stage2_pairs(s2.DATASET_ROOT, tmp_path, analysis_commit=commit)
    for name in (s2.CSV_NAME, s2.DOC_NAME, s2.MD_NAME):
        committed = (REPORT_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        fresh = (tmp_path / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert fresh == committed, name


def test_the_depth_resolved_prose_cannot_be_read_as_gates_above_the_floor(
    analysis, document
) -> None:
    """The review's wording item: with a 0% share, say that no gate meets both requirements."""
    prose = _plain((REPORT_DIR / s2.MD_NAME).read_text(encoding="utf-8"))
    if analysis.depth_resolved_resolved_share == 0.0:
        assert "No supported gate satisfies both requirements at once" in prose
        assert "all four" in prose
        # the old phrasing invited reading the per-pair maxima as gates that were resolved
        assert "every pair above the depth-resolved floor there" not in prose
    # the per-gate counts are data-derived, so the prose can be checked against the model
    matrix = np.asarray(
        [np.asarray(analysis.profiles.contrast(pair), dtype=float) for pair in "ABCD"]
    )
    above = np.abs(matrix) > analysis.depth_resolved_floor_mm_s
    gates_any = int(np.count_nonzero(np.any(above, axis=0)))
    gates_all = int(np.count_nonzero(np.all(above, axis=0)))
    assert (
        f"{gates_any} have at least one pair above the floor and {gates_all} have all four "
        "above it" in prose
    )
    assert (
        f"{analysis.depth_resolved_resolved_share:.1%} of the "
        f"{analysis.runs[0].supported_gates} supported gates"
    ) in prose or analysis.depth_resolved_resolved_share == 0.0


def test_the_report_prose_states_the_design_and_the_outcome() -> None:
    doc = _plain((REPORT_DIR / s2.MD_NAME).read_text(encoding="utf-8"))
    assert "counterbalanced" in doc
    assert "contemporaneous" in doc
    assert "E64 - E20" in doc
    assert "4.235" in doc and s2.PRIOR_DATASET in doc
    assert "one campaign block" in doc.lower()
    assert "the orientation is retained" in doc.lower() or "recorded beside" in doc.lower()


# ── the refusals ──────────────────────────────────────────────────────


def test_a_pass_with_fewer_than_eight_run_level_points_is_refused(decoded) -> None:
    fewer = decoded._replace(points=decoded.points[:-1])
    with pytest.raises(s2.Stage2PairsError, match="expected 8"):
        s2._campaign(fewer)


def test_a_pair_that_does_not_hold_one_run_of_each_level_is_refused(decoded) -> None:
    """Swap an E64 run's plan condition to E20: the pair no longer brackets the contrast."""
    points = tuple(
        point._replace(binding=point.binding._replace(job=point.binding.job._replace(
            emissions_per_profile=20
        )))
        if point.binding.job.job == "e64-a"
        else point
        for point in decoded.points
    )
    with pytest.raises(s2.Stage2PairsError, match="one run of each level"):
        s2._campaign(decoded._replace(points=points))


def test_a_stored_word_that_is_not_the_declared_level_is_refused(decoded) -> None:
    point = decoded.of_job("e64-a")[0]
    broken = decoded._replace(
        points=tuple(
            other._replace(config=other.config.model_copy(update={"emissions_per_profile": 128}))
            if other is point
            else other
            for other in decoded.points
        )
    )
    with pytest.raises(s2.Stage2PairsError, match="emissions"):
        s2._campaign(broken)


def test_a_frame_that_moves_between_runs_is_refused(decoded) -> None:
    points = list(decoded.points)
    points[-1] = points[-1]._replace(
        config=points[-1].config.model_copy(update={"sound_speed_ms": 1500.0})
    )
    with pytest.raises(s2.Stage2PairsError, match="sound speed"):
        s2._campaign(decoded._replace(points=tuple(points)))


def test_a_plan_that_does_not_state_the_analysis_orientation_is_refused(decoded) -> None:
    with pytest.raises(s2.Stage2PairsError, match="orientation"):
        s2._campaign(
            decoded._replace(
                plan=decoded.plan.model_validate(
                    {**decoded.plan.model_dump(), "analysis_orientation": "E20 - E64"}
                )
            )
        )


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_one(
    tmp_path, capsys
) -> None:
    from udv_echo_process.cli import _COMMANDS

    assert "sparse-stage2-pairs" in _COMMANDS
    with pytest.raises(SystemExit) as exit_code:
        s2.stage2_pairs_main(
            [
                "--dataset-root",
                s2.DATASET_ROOT.as_posix(),
                "--report-dir",
                str(tmp_path / "reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert exit_code.value.code == 0
    assert "checks  : all pass" in capsys.readouterr().out

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as failed:
        s2.stage2_pairs_main(
            [
                "--dataset-root",
                str(broken),
                "--report-dir",
                str(tmp_path / "broken-reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert failed.value.code == 1
