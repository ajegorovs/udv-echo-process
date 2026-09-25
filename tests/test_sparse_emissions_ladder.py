"""Focused tests for WP4 — the emissions ladder (E8/E20/E64/E128).

The tests pin the three things the WP4 request asked this slice to keep apart or to state:

- **the evidence is unequal and is published as such** — E20 is the four reference runs and
  its stated variation is their spread, while E8, E64 and E128 are one scientific recording
  each inside their own job's three block-local anchors. No averaged E20 profile exists, and
  the tests fail if one appears;
- **the two views use the views they are told to** — the velocity-stability numbers on the
  pass's designed 12 s window and the common support, the temporal numbers on the full
  retained record from each file's own stored per-profile time array, with the segmentation
  cut by physical *duration* rather than by profile count;
- **the floors are not mixed** — a per-gate difference is screened against WP2's
  depth-resolved endpoint, a depth-averaged difference against its depth-averaged endpoint,
  and a residual inside one job against that job's own anchor spread, **each of them the
  number the pass's own WP1 and WP2 artefacts publish** (``anchor-floor.json`` and
  ``reference-floor.json``) rather than a copy of another sitting's.

Everything is recomputed here from the committed recordings through the shared loader, and
the request's expected achieved periods are asserted against the measurements rather than
adopted. Nothing here mutates the repository.
"""

from __future__ import annotations

import csv
import io
import json
import math
import shutil
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import _floor_documents as fdp
from udv_echo_process.analysis import sparse_emissions_ladder as sel
from udv_echo_process.analysis._sparse_pass import (
    decode_pass,
    gate_statistics,
    supported_gates,
    supported_mean_of,
)
from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    DESIGNED_WINDOW_S,
    PLAN_PATH,
    REPORT_DIR,
    SparseIngestError,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"

E20_RUNS = ("cr1", "cr2", "cr3", "cr4")
SINGLE = {
    "E8": ("e8", "emissions-8"),
    "E64": ("e64", "emissions-64"),
    "E128": ("e128", "emissions-128"),
}


def _copy_dataset(tmp_path: Path) -> Path:
    """A private copy of the committed pass, so a test may break it."""
    target = tmp_path / "sparse-mixer-live-1"
    shutil.copytree(ROOT / DATASET_ROOT, target)
    return target


def _point(decoded, label: str):
    """One decoded recording of the pass, by its label."""
    return next(
        item for item in decoded.points if str(item.binding.point.label) == label
    )


def _block(decoded, label: str) -> np.ndarray:
    """One record's per-gate ``mean`` profile on the common support, by its label."""
    return _block_of(_point(decoded, label), decoded)


def _block_of(point, decoded) -> np.ndarray:
    """One decoded record's per-gate ``mean`` profile on the common support."""
    return gate_statistics(
        point, window_s=decoded.window_s, support_mm=decoded.support_mm
    )[sel.RESIDUAL_STATISTIC]


def _job_point(decoded, job: str, label: str):
    """One recording of one job, by its label: anchors repeat across jobs."""
    matches = [
        item for item in decoded.of_job(job) if str(item.binding.point.label) == label
    ]
    assert len(matches) == 1
    return matches[0]


def _curve(
    decoded, label: str, requested_depth_mm: float
) -> tuple[np.ndarray, np.ndarray]:
    """The full stored series at one depth and its autocorrelation, recomputed here."""
    point = _point(decoded, label)
    depths = supported_gates(point, decoded.support_mm)
    gate = int(np.argmin(np.abs(depths - requested_depth_mm)))
    series = np.asarray(point.values, dtype=float)[:, gate]
    centred = series - series.mean()
    acf = np.correlate(centred, centred, mode="full")[series.size - 1 :] / (
        series.size * float(np.mean(np.square(centred)))
    )
    return series, acf


@pytest.fixture(scope="module")
def decoded():
    return decode_pass()


@pytest.fixture(scope="module")
def ladder():
    return sel.build_emissions_ladder(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(ladder):
    return sel.def_document(ladder)


# ── the shared views are the frozen table's own ───────────────────────


def test_the_loader_uses_the_wp0_window_and_support(decoded) -> None:
    assert decoded.window_s == DESIGNED_WINDOW_S == 12.0
    assert decoded.window_revolutions == 100
    assert decoded.support_mm[0] == pytest.approx(10.138, rel=1e-12)
    assert decoded.support_mm[1] == pytest.approx(98.938, rel=1e-9)
    assert len(decoded.points) == 26


# ── the four levels, and the evidence each one rests on ───────────────


def test_every_level_carries_its_declared_condition_and_its_own_recording(
    ladder, decoded
) -> None:
    assert [level.level for level in ladder.levels] == list(sel.LEVEL_ORDER)
    for level in ladder.levels:
        assert level.condition == sel.DECLARED_CONDITIONS[level.level]
        assert level.emissions_per_profile == int(
            sel.DECLARED_CONDITIONS[level.level]["emissions_per_profile"]
        )
        labels = [row.label for row in ladder.records if row.level == level.level]
        assert labels == list(level.records)
        for label in labels:
            point = _point(decoded, label)
            assert point.binding.job.job in level.jobs
            assert int(point.config.burst_length) == 10
            assert (
                int(point.config.emissions_per_profile) == level.emissions_per_profile
            )
            # the references are the reference *condition*; the others are the job's own
            assert float(point.config.resolution_mm) == pytest.approx(1.85, rel=1e-9)
            assert int(point.values.shape[1]) == sel.REFERENCE_WINDOW[1] == 50


def test_the_evidence_counts_are_one_four_one_one_and_are_published(
    ladder, decoded
) -> None:
    counts = {level.level: len(level.records) for level in ladder.levels}
    assert counts == {"E8": 1, "E20": 4, "E64": 1, "E128": 1}
    assert tuple(ladder.levels[1].records) == E20_RUNS
    assert len(set(ladder.levels[1].jobs)) == 4
    for level, (label, job) in SINGLE.items():
        published = next(item for item in ladder.levels if item.level == level)
        assert published.records == (label,)
        assert published.jobs == (job,)
        assert published.evidence == sel.EVIDENCE_SINGLE
        assert published.anchor_labels == sel.ANCHOR_LABELS
        point = _point(decoded, label)
        assert int(point.binding.order) > 0
    assert ladder.levels[1].evidence == sel.EVIDENCE_FOUR_RUNS
    assert ladder.levels[1].anchor_labels == ()
    # the four runs are four distinct recordings in the pass's own order
    orders = [
        _point(decoded, label).binding.order for label in ladder.levels[1].records
    ]
    assert orders == sorted(orders)
    assert len(set(orders)) == 4


def test_every_record_measures_one_shared_native_gate_grid(ladder, decoded) -> None:
    depths = supported_gates(_point(decoded, "e8"), decoded.support_mm)
    assert depths.size == 49  # the 1.85 mm window's last gate falls outside the support
    assert ladder.records[0].supported_gates == 49
    assert ladder.levels[0].records[0] == "e8"
    assert ladder.depth_resolved.depths_mm.size == 49
    assert float(ladder.depth_resolved.depths_mm[0]) == pytest.approx(10.138, rel=1e-9)
    assert float(ladder.depth_resolved.depths_mm[-1]) == pytest.approx(98.938, rel=1e-9)
    for label in ("e8", *E20_RUNS, "e64", "e128"):
        grid = supported_gates(_point(decoded, label), decoded.support_mm)
        assert np.array_equal(grid, depths)


def test_the_five_statistics_are_recomputed_from_the_recordings(
    ladder, decoded, document
) -> None:
    for row in ladder.records:
        recomputed = {
            name: supported_mean_of(
                _point(decoded, row.label),
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=name,
            )
            for name in sel.STATISTICS
        }
        for name, value in recomputed.items():
            assert row.statistics[name] == pytest.approx(value, rel=1e-12, abs=1e-15)
        assert row.supported_gates == 49
        assert row.profiles_full == int(_point(decoded, row.label).values.shape[0])
    # the level does not carry a second, averaged set of statistics
    assert not any("e20" in key.lower() for key in document["depth_resolved"])
    assert "statistics" not in document["levels"][1]
    for value in document["depth_resolved"].values():
        assert len(value) == 49


# ── E20 is four runs, never one averaged profile ──────────────────────


def test_e20_is_kept_as_four_runs_with_no_averaged_profile(ladder, document) -> None:
    keys = tuple(sel.DepthResolved.model_fields)
    assert not any("e20" in key.lower() for key in keys)
    assert all(not key.startswith("mean") for key in keys)
    for run in E20_RUNS:
        assert run in keys
    assert not any(
        key.startswith("mean") or "average" in key for key in document["depth_resolved"]
    )
    # the four run profiles are four different arrays, not one repeated
    profiles = [
        np.asarray(getattr(ladder.depth_resolved, run), dtype=float) for run in E20_RUNS
    ]
    assert len({profile.tobytes() for profile in profiles}) == 4
    # and the level's own variation is a spread over them, not a mean of them
    level = next(item for item in ladder.levels if item.level == "E20")
    means = [row.statistics["mean"] for row in ladder.records if row.level == "E20"]
    assert len(means) == 4
    assert level.stated_variation_mm_s == pytest.approx(
        max(means) - min(means), rel=1e-12
    )
    # a spread, not a mean of the runs: the two happen to differ on this pass
    assert abs(level.stated_variation_mm_s - float(np.mean(means))) > 1e-9
    assert level.stated_variation_kind.startswith("between-run")


def test_the_e20_variation_is_wp2s_own_between_run_floor(ladder, decoded) -> None:
    """The spread over the four runs is the number WP2 published, recomputed here."""
    means = [
        supported_mean_of(
            _point(decoded, label),
            window_s=decoded.window_s,
            support_mm=decoded.support_mm,
            name=sel.RESIDUAL_STATISTIC,
        )
        for label in E20_RUNS
    ]
    spread = max(means) - min(means)
    level = next(item for item in ladder.levels if item.level == "E20")
    assert level.stated_variation_mm_s == pytest.approx(spread, rel=1e-12)
    floor = next(
        item for item in ladder.floors if item.name == "reference_depth_averaged"
    )
    assert floor.published_mm_s == pytest.approx(spread, abs=1e-3)
    assert floor.recomputed_mm_s == pytest.approx(spread, rel=1e-12)


def test_the_single_levels_state_their_own_jobs_anchor_spread(ladder, decoded) -> None:
    for level_name, (_, job) in SINGLE.items():
        level = next(item for item in ladder.levels if item.level == level_name)
        anchors = [
            supported_mean_of(
                point,
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=sel.RESIDUAL_STATISTIC,
            )
            for point in decoded.of_job(job)
            if str(point.binding.point.label) in sel.ANCHOR_LABELS
        ]
        assert len(anchors) == 3
        assert level.stated_variation_mm_s == pytest.approx(
            max(anchors) - min(anchors), rel=1e-12
        )
        assert level.stated_variation_mm_s == pytest.approx(
            sel.published_job_floor(ladder.published_floors, job).published_mm_s,
            abs=1e-3,
        )
        assert level.stated_variation_kind.startswith("within-job")


# ── the consecutive-level differences ─────────────────────────────────


def test_the_consecutive_differences_are_depth_resolved_and_recomputed(
    ladder, decoded
) -> None:
    assert len(ladder.differences) == 9
    for row in ladder.differences:
        difference = _block(decoded, row.left_label) - _block(decoded, row.right_label)
        worst = int(np.argmax(np.abs(difference)))
        depths = supported_gates(_point(decoded, row.left_label), decoded.support_mm)
        assert row.mean_difference_mm_s == pytest.approx(
            float(np.mean(difference)), rel=1e-12, abs=1e-15
        )
        assert row.extreme_signed_mm_s == pytest.approx(
            float(difference[worst]), rel=1e-12, abs=1e-15
        )
        assert row.extreme_abs_mm_s == pytest.approx(
            float(abs(difference[worst])), rel=1e-12, abs=1e-15
        )
        assert row.extreme_depth_mm == pytest.approx(float(depths[worst]), rel=1e-12)
        assert row.knots_positive == int(np.count_nonzero(difference > 0.0))
        assert row.knots_negative == int(np.count_nonzero(difference < 0.0))
        assert row.knots_positive + row.knots_negative == row.gates == 49
        # the published array is the array the row's numbers came from
        key = f"{row.left_label}_minus_{row.right_label}"
        assert np.allclose(
            getattr(ladder.depth_resolved, key), difference, rtol=0, atol=0
        )


def test_each_step_reduces_over_the_run_resolved_differences(ladder) -> None:
    assert [(step.left_level, step.right_level) for step in ladder.steps] == list(
        sel.DIFFERENCE_STEPS
    )
    assert [step.differences for step in ladder.steps] == [4, 4, 1]
    for step in ladder.steps:
        rows = [
            row
            for row in ladder.differences
            if (row.left_level, row.right_level) == (step.left_level, step.right_level)
        ]
        assert len(rows) == step.differences
        worst = max(rows, key=lambda row: row.extreme_abs_mm_s)
        assert step.extreme_abs_mm_s == pytest.approx(worst.extreme_abs_mm_s, rel=1e-12)
        assert step.extreme_signed_mm_s == pytest.approx(
            worst.extreme_signed_mm_s, rel=1e-12
        )
        assert step.extreme_depth_mm == pytest.approx(worst.extreme_depth_mm, rel=1e-12)
        assert (step.extreme_left_label, step.extreme_right_label) == (
            worst.left_label,
            worst.right_label,
        )
        assert step.mean_difference_min_mm_s == pytest.approx(
            min(row.mean_difference_mm_s for row in rows), rel=1e-12
        )
        assert step.mean_difference_max_mm_s == pytest.approx(
            max(row.mean_difference_mm_s for row in rows), rel=1e-12
        )
        if sel.E20_LEVEL in (step.left_level, step.right_level):
            assert "four runs" in step.note
            assert all(
                row.right_label in E20_RUNS or row.left_label in E20_RUNS
                for row in rows
            )


def test_the_step_mean_differences_are_screened_against_the_depth_averaged_endpoint(
    ladder,
) -> None:
    """The depth-averaged step differences sit within the campaign's four-run spread."""
    floor = next(
        item for item in ladder.floors if item.name == "reference_depth_averaged"
    )
    assert floor.depth_mm is None
    assert floor.applies_to.startswith("every depth-averaged comparison")
    for step in ladder.steps:
        spread = step.mean_difference_max_mm_s - step.mean_difference_min_mm_s
        if step.differences == 4 and sel.E20_LEVEL in (
            step.left_level,
            step.right_level,
        ):
            # a constant offset cannot change a spread: the four-run spread survives
            assert spread == pytest.approx(floor.recomputed_mm_s, rel=1e-9, abs=1e-9)
        assert abs(step.mean_difference_max_mm_s) < 2.0 * floor.published_mm_s


# ── the single rows inside their own anchors ──────────────────────────


def test_each_single_level_is_recomputed_against_both_bracketing_anchors(
    ladder, decoded
) -> None:
    assert len(ladder.brackets) == 6
    for row in ladder.brackets:
        point = _point(decoded, row.label)
        assert point.binding.job.job == row.job
        assert row.anchor in sel.BRACKET_ANCHORS
        anchor = _job_point(decoded, row.job, row.anchor)
        # the row sits inside its bracket: begin before it, mid after it
        begin = _job_point(decoded, row.job, sel.BRACKET_ANCHORS[0])
        mid = _job_point(decoded, row.job, sel.BRACKET_ANCHORS[1])
        assert (
            int(begin.binding.order) < int(point.binding.order) < int(mid.binding.order)
        )
        assert (anchor.binding.order < point.binding.order) is (
            row.anchor == sel.BRACKET_ANCHORS[0]
        )
        residual = _block_of(point, decoded) - _block_of(anchor, decoded)
        worst = int(np.argmax(np.abs(residual)))
        depths = supported_gates(point, decoded.support_mm)
        assert row.residual_mean_mm_s == pytest.approx(
            float(np.mean(residual)), rel=1e-12, abs=1e-15
        )
        assert row.residual_extreme_signed_mm_s == pytest.approx(
            float(residual[worst]), rel=1e-12, abs=1e-15
        )
        assert row.residual_extreme_abs_mm_s == pytest.approx(
            float(abs(residual[worst])), rel=1e-12, abs=1e-15
        )
        assert row.residual_extreme_depth_mm == pytest.approx(
            float(depths[worst]), rel=1e-12
        )
        assert row.knots_positive == int(np.count_nonzero(residual > 0.0))
        assert (
            row.job_anchor_floor_mm_s
            == sel.published_job_floor(ladder.published_floors, row.job).published_mm_s
        )
        assert "not a realization of the reference condition" in row.anchor_kind
        # the depth-resolved residual the figure and the document draw
        key = f"{row.label}_minus_{row.anchor.replace('-', '_')}"
        assert np.allclose(
            getattr(ladder.depth_resolved, key), residual, rtol=0, atol=0
        )


def test_a_depth_averaged_residual_hides_local_structure(ladder) -> None:
    for row in ladder.brackets:
        assert row.residual_extreme_abs_mm_s > 2.0 * abs(row.residual_mean_mm_s)


# ── the e128 observation ──────────────────────────────────────────────


def test_the_e128_observation_is_recomputed_depth_resolved(
    ladder, decoded, document
) -> None:
    published = ladder.e128_observation
    begin = _block(decoded, "e128") - _block_of(
        _job_point(decoded, "emissions-128", "ctrl-begin"), decoded
    )
    mid = _block(decoded, "e128") - _block_of(
        _job_point(decoded, "emissions-128", "ctrl-mid"), decoded
    )
    depths = supported_gates(_point(decoded, "e128"), decoded.support_mm)
    assert published.residual_mean_vs_begin_mm_s == pytest.approx(
        float(np.mean(begin)), rel=1e-12, abs=1e-15
    )
    assert published.residual_mean_vs_mid_mm_s == pytest.approx(
        float(np.mean(mid)), rel=1e-12, abs=1e-15
    )
    assert published.residual_mean_vs_begin_mm_s > 0.0
    assert published.residual_mean_vs_mid_mm_s > 0.0
    worst_begin = int(np.argmax(np.abs(begin)))
    worst_mid = int(np.argmax(np.abs(mid)))
    assert published.extreme_vs_begin_signed_mm_s == pytest.approx(
        float(begin[worst_begin]), rel=1e-12, abs=1e-15
    )
    assert published.extreme_vs_begin_depth_mm == pytest.approx(
        float(depths[worst_begin]), rel=1e-12
    )
    assert published.extreme_vs_mid_signed_mm_s == pytest.approx(
        float(mid[worst_mid]), rel=1e-12, abs=1e-15
    )
    assert published.extreme_vs_mid_depth_mm == pytest.approx(
        float(depths[worst_mid]), rel=1e-12
    )
    assert published.knots_positive_vs_begin == int(np.count_nonzero(begin > 0.0))
    assert published.knots_positive_vs_mid == int(np.count_nonzero(mid > 0.0))
    # it is not one gate: a contiguous same-sign region carries it
    assert published.longest_positive_run_knots_vs_begin >= 5
    assert published.longest_positive_run_knots_vs_mid >= 5
    low, high = published.longest_positive_run_span_mm_vs_begin
    assert published.longest_positive_run_knots_vs_begin == int(
        np.count_nonzero(
            (depths >= low - 1e-9) & (depths <= high + 1e-9) & (begin > 0.0)
        )
    )
    span_low, span_high = published.same_sign_region_around_extreme_mm_vs_begin
    assert span_low <= published.extreme_vs_begin_depth_mm <= span_high
    assert published.top_three_knots_share_of_absolute_sum < 0.25
    # the floors it sits with, and the reading that keeps it non-causal
    assert (
        published.job_anchor_floor_mm_s
        == sel.published_job_floor(
            ladder.published_floors, "emissions-128"
        ).published_mm_s
    )
    assert published.ratio_to_job_anchor_floor_vs_begin == pytest.approx(
        abs(published.residual_mean_vs_begin_mm_s) / published.job_anchor_floor_mm_s,
        rel=1e-12,
    )
    assert published.ratio_to_depth_resolved_floor_vs_begin == pytest.approx(
        published.extreme_vs_begin_abs_mm_s
        / ladder.published_floors.depth_resolved.published_mm_s,
        rel=1e-12,
    )
    reading = document["e128_observation"]["reading"]
    assert "not evidence that E128 caused a change" in reading
    assert "one realization" in reading
    assert document["e128_observation"]["label"] == "e128"


# ── the floors: both endpoints, and which one applies where ───────────


def test_the_floors_are_stated_with_both_endpoints_and_reproduced_by_this_build(
    ladder, decoded
) -> None:
    assert len(ladder.floors) == 5
    depth_resolved = next(
        item for item in ladder.floors if item.name == "reference_depth_resolved"
    )
    averaged = next(
        item for item in ladder.floors if item.name == "reference_depth_averaged"
    )
    assert depth_resolved.depth_mm is not None
    assert averaged.depth_mm is None
    assert "per-gate" in depth_resolved.endpoint
    assert "unweighted mean" in averaged.endpoint
    # the depth-resolved endpoint is the largest per-gate difference over the six pairs
    blocks = [_block(decoded, label) for label in E20_RUNS]
    worst = 0.0
    worst_depth = 0.0
    depths = supported_gates(_point(decoded, "cr1"), decoded.support_mm)
    for index, left in enumerate(blocks):
        for right in blocks[index + 1 :]:
            difference = left - right
            gate = int(np.argmax(np.abs(difference)))
            if float(abs(difference[gate])) > worst:
                worst = float(abs(difference[gate]))
                worst_depth = float(depths[gate])
    assert depth_resolved.recomputed_mm_s == pytest.approx(worst, rel=1e-12)
    assert depth_resolved.depth_mm == pytest.approx(worst_depth, rel=1e-12)
    # the depth it recomputes is the depth this pass's own WP2 document states
    assert depth_resolved.depth_mm == pytest.approx(
        ladder.published_floors.depth_resolved.depth_mm, abs=1e-3
    )
    for floor in ladder.floors:
        assert floor.published_mm_s == pytest.approx(
            floor.recomputed_mm_s, abs=sel.FLOOR_PUBLISHED_TOLERANCE_MM_S
        )
        assert floor.source and floor.applies_to and floor.endpoint
        assert floor.statistic == sel.RESIDUAL_STATISTIC
        assert floor.unit == "mm/s"
    for level_name, (_, job) in SINGLE.items():
        floor = next(
            item
            for item in ladder.floors
            if item.name == f"job_anchors_{level_name.lower()}"
        )
        assert floor.published_mm_s == pytest.approx(
            sel.published_job_floor(ladder.published_floors, job).published_mm_s,
            rel=1e-12,
        )
        assert "inside one job" in floor.applies_to


def test_the_document_says_which_endpoint_applies_where(document) -> None:
    rule = document["floors"]["rule"]
    assert "depth-resolved endpoint" in rule
    assert "depth-averaged endpoint" in rule
    assert "that job's own anchor spread" in rule
    assert "do not bound drift" in rule


#: What a *different* sitting's artefacts would publish for this pass's own recordings: the
#: number one thousandth off the recomputation, in the only direction the published rounding
#: leaves room for — so every one of them varies with the pass, every one of them stays
#: inside ``FLOOR_PUBLISHED_TOLERANCE_MM_S``, and every one of them differs from the number
#: the committed first-pass artefact carries (14.603 / 4.235 / 1.521 / 2.829 / 3.304).
OTHER_PASSES_PUBLISHED: dict[str, float] = {
    "reference_depth_resolved": 14.604,
    "reference_depth_averaged": 4.234,
    "emissions-8": 1.522,
    "emissions-64": 2.828,
    "emissions-128": 3.305,
}

#: The two artefacts this pass's own floors are published in, named as WP1 and WP2 write
#: them: stated independently here so that a test can build a report directory before the
#: slice under test is asked anything.
ANCHOR_FLOOR_DOC = "anchor-floor.json"
REFERENCE_FLOOR_DOC = "reference-floor.json"

#: The decimals WP1 and WP2 publish a floor to, stated independently here so that what this
#: file expects is never read back out of the module it is testing.
PUBLISHED_FLOOR_DECIMALS = 3

#: The same floors, far enough away that no recomputation reproduces them: a document whose
#: own gate passed but whose numbers are another campaign's. The offset is taken at the
#: published precision, so what these stand for is exactly what the artefact would state.
DISAGREEING_PUBLISHED: dict[str, float] = {
    name: round(value + 0.5, PUBLISHED_FLOOR_DECIMALS)
    for name, value in OTHER_PASSES_PUBLISHED.items()
}


def _table_blocks(path: Path) -> list[list[dict[str, str]]]:
    """A published table's blocks, one per header."""
    text = path.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))
    return [
        list(csv.DictReader(block.splitlines()))
        for block in text.split("\n\n")
        if block.strip()
    ]


def _write_table(path: Path, blocks: list[list[dict[str, str]]]) -> None:
    """Write a table back, one block per header, in the shape the slice publishes."""
    parts = []
    for block in blocks:
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(block[0]))
        writer.writeheader()
        writer.writerows(block)
        parts.append(out.getvalue().rstrip("\n"))
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8", newline="")


def _copy_published_pair(destination: Path) -> None:
    """This pass's WP1 and WP2 documents *and the tables they are authenticated against*.

    The two halves travel together: a document is read only with the table its own
    ``table_sha256`` covers, so a directory holding just the JSON cannot be read at all.
    """
    destination.mkdir(parents=True, exist_ok=True)
    for name in (ANCHOR_FLOOR_DOC, REFERENCE_FLOOR_DOC):
        shutil.copyfile(ROOT / REPORT_DIR / name, destination / name)
        table = Path(name).with_suffix(".csv").name
        shutil.copyfile(ROOT / REPORT_DIR / table, destination / table)


def _move_published_floors(report: Path, published: Mapping[str, float]) -> None:
    """Republish the named floors: the documents **and** the tables they are checked against.

    A document whose number its own table does not carry is refused — that is the point of the
    mutation tests below — so a test that wants this slice to screen against different floors
    has to move both halves, which is what a republish of WP1 or WP2 would do. An endpoint is a
    *reduction* of the pair table, so moving one moves the worst pair's row and pushes the
    others below it, leaving the pair both documents already name the worst one.
    """
    anchors_path = report / ANCHOR_FLOOR_DOC
    anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
    jobs = {str(entry["job"]) for entry in anchors["jobs"]}
    moved = {job: value for job, value in published.items() if job in jobs}
    for entry in anchors["jobs"]:
        if str(entry["job"]) in moved:
            entry["spread"][sel.RESIDUAL_STATISTIC] = moved[str(entry["job"])]
    anchors_table = anchors_path.with_suffix(".csv")
    blocks = _table_blocks(anchors_table)
    blocks[0] = [
        {**row, "value": repr(moved[row["job"]])}
        if row["job"] in moved
        and row["statistic"] == sel.RESIDUAL_STATISTIC
        and row["quantity"] == "anchor_range"
        else row
        for row in blocks[0]
    ]
    _write_table(anchors_table, blocks)
    anchors["table_sha256"] = fdp.table_digest(anchors_table)
    anchors_path.write_text(
        json.dumps(anchors, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )

    reference_path = report / REFERENCE_FLOOR_DOC
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    floor = reference["floor"]
    resolved = published["reference_depth_resolved"]
    averaged = published["reference_depth_averaged"]
    resolved_pair = tuple(floor["depth_resolved"]["pair"])
    averaged_pair = tuple(floor["depth_averaged"]["pair"])
    reference_table = reference_path.with_suffix(".csv")
    blocks = _table_blocks(reference_table)
    pairs = []
    for row in blocks[-1]:
        pair = (row["left"], row["right"])
        if pair == resolved_pair:
            row = {**row, "max_abs_difference_mm_s": repr(resolved)}
        elif abs(float(row["max_abs_difference_mm_s"])) >= resolved:
            row = {**row, "max_abs_difference_mm_s": repr(resolved / 2)}
        if pair == averaged_pair:
            row = {**row, "mean_difference_mm_s": repr(-averaged)}
        elif abs(float(row["mean_difference_mm_s"])) >= averaged:
            row = {**row, "mean_difference_mm_s": repr(-averaged / 2)}
        pairs.append(row)
    _write_table(reference_table, [*blocks[:-1], pairs])
    floor["depth_resolved"]["value_mm_s"] = resolved
    floor["depth_averaged"]["value_mm_s"] = averaged
    reference["table_sha256"] = fdp.table_digest(reference_table)
    reference_path.write_text(
        json.dumps(reference, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


def _re_published_artefacts(
    tmp_path: Path,
    published: Mapping[str, float] | None = None,
    *,
    fingerprint: str | None = None,
    where: str = "reports",
) -> Path:
    """A report directory holding a re-published copy of this pass's WP1/WP2 artefacts.

    The committed documents are copied beside their tables, with their floor numbers rewritten
    **in both halves**, so a test can tell what the slice **adopts from them** apart from what
    it recomputes from the recordings while the pair stays one a generating run could have
    published. ``fingerprint`` replaces the pass identity both documents state.
    """
    report = tmp_path / where
    _copy_published_pair(report)
    if published is not None:
        _move_published_floors(report, published)
    if fingerprint is not None:
        for name in (ANCHOR_FLOOR_DOC, REFERENCE_FLOOR_DOC):
            path = report / name
            document = json.loads(path.read_text(encoding="utf-8"))
            document["plan_fingerprint"] = fingerprint
            path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="",
            )
    return report


def test_the_reader_keeps_the_artefacts_own_numbers_beside_the_published_ones(
    decoded,
) -> None:
    """The numbers are the documents' own, at the decimals the floors publish to."""
    floors = sel.read_published_floors(
        plan_name=str(decoded.plan.plan), plan_fingerprint=decoded.plan_fingerprint
    )
    anchors = json.loads(
        (ROOT / REPORT_DIR / ANCHOR_FLOOR_DOC).read_text(encoding="utf-8")
    )["jobs"]
    reference = json.loads(
        (ROOT / REPORT_DIR / REFERENCE_FLOOR_DOC).read_text(encoding="utf-8")
    )["floor"]
    assert floors.directory == REPORT_DIR.as_posix()
    assert sel.ANCHOR_FLOOR_DOC == ANCHOR_FLOOR_DOC
    assert sel.REFERENCE_FLOOR_DOC == REFERENCE_FLOOR_DOC
    assert sel.PUBLISHED_FLOOR_DECIMALS == PUBLISHED_FLOOR_DECIMALS
    assert floors.documents == (ANCHOR_FLOOR_DOC, REFERENCE_FLOOR_DOC)
    assert floors.plan_fingerprint == decoded.plan_fingerprint
    assert floors.depth_resolved.value_mm_s == reference["depth_resolved"]["value_mm_s"]
    assert floors.depth_resolved.published_mm_s == round(
        reference["depth_resolved"]["value_mm_s"], PUBLISHED_FLOOR_DECIMALS
    )
    assert floors.depth_resolved.pair == tuple(reference["depth_resolved"]["pair"])
    assert floors.depth_resolved.depth_mm == reference["depth_resolved"]["depth_mm"]
    assert floors.depth_averaged.value_mm_s == reference["depth_averaged"]["value_mm_s"]
    assert floors.depth_averaged.pair == tuple(reference["depth_averaged"]["pair"])
    assert {floor.job: floor.value_mm_s for floor in floors.job_anchors} == {
        entry["job"]: entry["spread"][sel.RESIDUAL_STATISTIC] for entry in anchors
    }
    # the published column is the artefact's number at the published precision: the
    # committed first-pass document carries 14.603170079597177 and publishes 14.603
    assert floors.depth_resolved.value_mm_s != floors.depth_resolved.published_mm_s
    assert floors.depth_resolved.published_mm_s == 14.603


def test_the_published_floors_come_from_this_passes_own_artefacts(tmp_path) -> None:
    """The five rows carry what this pass's own WP1/WP2 documents state, not a copy."""
    report = _re_published_artefacts(tmp_path, OTHER_PASSES_PUBLISHED)
    # the committed documents copied verbatim: the pass's own floors and nothing else
    plain = _re_published_artefacts(tmp_path, where="plain")
    for directory in (report, plain):
        sel.write_emissions_ladder(
            ROOT / DATASET_ROOT,
            directory,
            plan_path=ROOT / PLAN_PATH,
            analysis_commit=COMMIT,
        )
    document = json.loads((report / sel.DOC_NAME).read_text(encoding="utf-8"))
    committed = json.loads((plain / sel.DOC_NAME).read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in document["floors"]["bindings"]}
    before = {row["name"]: row for row in committed["floors"]["bindings"]}
    assert rows["reference_depth_resolved"]["published_mm_s"] == 14.604
    assert rows["reference_depth_averaged"]["published_mm_s"] == 4.234
    for level_name, (_, job) in SINGLE.items():
        name = f"job_anchors_{level_name.lower()}"
        assert rows[name]["published_mm_s"] == OTHER_PASSES_PUBLISHED[job]
        assert rows[name]["published_mm_s"] != before[name]["published_mm_s"]
    # the recomputation beside them is still this pass's own recordings
    assert [row["recomputed_mm_s"] for row in document["floors"]["bindings"]] == [
        row["recomputed_mm_s"] for row in committed["floors"]["bindings"]
    ]
    # and the adopted numbers are the ones the reading, the table and the prose carry
    assert document["e128_observation"]["job_anchor_floor_mm_s"] == 3.305
    table = (report / sel.CSV_NAME).read_text(encoding="utf-8")
    brackets = csv.DictReader(table.split("\n\n")[2].splitlines())
    assert {
        row["job_anchor_floor_mm_s"] for row in brackets if row["level"] == "E8"
    } == {"1.522"}
    markdown = (report / sel.MD_NAME).read_text(encoding="utf-8")
    assert "14.604 mm/s at" in markdown
    assert "3.305 mm/s (emissions-128)" in markdown
    # every one of them is inside the published rounding, so the gate still holds
    assert (
        document["checks"]["floors_are_stated_with_both_endpoints_and_reproduce"]
        is True
    )
    assert document["ok"] is True


def test_the_command_publishes_this_passes_own_floors(tmp_path) -> None:
    """The written document carries the pass's own published numbers, not this module's."""
    report = _re_published_artefacts(tmp_path, OTHER_PASSES_PUBLISHED)
    with pytest.raises(SystemExit) as accepted:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(report),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert accepted.value.code == 0
    document = json.loads((report / sel.DOC_NAME).read_text(encoding="utf-8"))
    published = {
        row["name"]: row["published_mm_s"] for row in document["floors"]["bindings"]
    }
    assert published["reference_depth_resolved"] == 14.604
    assert published["reference_depth_averaged"] == 4.234
    assert published["job_anchors_e8"] == 1.522
    assert published["job_anchors_e64"] == 2.828
    assert published["job_anchors_e128"] == 3.305
    assert document["ok"] is True


def test_a_published_floor_the_recordings_do_not_reproduce_fails_the_gate(
    tmp_path, capsys
) -> None:
    """A document that disagrees with the recordings is published as a disagreement."""
    report = _re_published_artefacts(tmp_path, DISAGREEING_PUBLISHED)
    with pytest.raises(SystemExit) as refused:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(report),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert refused.value.code == 1
    assert "floors_are_stated_with_both_endpoints_and_reproduce" in (
        capsys.readouterr().err
    )
    document = json.loads((report / sel.DOC_NAME).read_text(encoding="utf-8"))
    assert [row["published_mm_s"] for row in document["floors"]["bindings"]] == [
        DISAGREEING_PUBLISHED["reference_depth_resolved"],
        DISAGREEING_PUBLISHED["reference_depth_averaged"],
        DISAGREEING_PUBLISHED["emissions-8"],
        DISAGREEING_PUBLISHED["emissions-64"],
        DISAGREEING_PUBLISHED["emissions-128"],
    ]
    assert (
        document["checks"]["floors_are_stated_with_both_endpoints_and_reproduce"]
        is False
    )
    assert document["ok"] is False


def test_another_passes_published_floors_are_refused_by_name(tmp_path) -> None:
    """A document another sitting wrote is refused, never adopted."""
    report = _re_published_artefacts(tmp_path, fingerprint="0" * 64)
    with pytest.raises(SystemExit) as refused:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(report),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert refused.value.code == 1
    assert not (report / sel.CSV_NAME).exists()
    assert not (report / sel.DOC_NAME).exists()
    with pytest.raises(sel.EmissionsLadderError, match="must be this pass's own"):
        sel.build_emissions_ladder(report_dir=report, analysis_commit=COMMIT)


def test_a_report_directory_without_this_passes_floors_is_refused_by_name(
    tmp_path,
) -> None:
    """The pass's own numbers are required, not defaulted to and not invented.

    No fallback reaches into the pass's committed directory: a run that writes elsewhere
    and finds no floors there refuses, so the numbers recorded in one directory can never
    be the ones that decided another directory's outcome.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit) as refused:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(empty),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert refused.value.code == 1
    assert not (empty / sel.CSV_NAME).exists()
    with pytest.raises(sel.EmissionsLadderError, match="anchor-floor.json is missing"):
        sel.build_emissions_ladder(report_dir=empty, analysis_commit=COMMIT)
    # one of the two documents is not enough either
    half = tmp_path / "half"
    half.mkdir()
    shutil.copyfile(ROOT / REPORT_DIR / ANCHOR_FLOOR_DOC, half / ANCHOR_FLOOR_DOC)
    with pytest.raises(
        sel.EmissionsLadderError, match="reference-floor.json is missing"
    ):
        sel.build_emissions_ladder(report_dir=half, analysis_commit=COMMIT)


# ── the temporal view: the achieved grid, from the stored timestamps ──


def test_the_achieved_periods_come_from_the_stored_timestamps(ladder, decoded) -> None:
    assert len(ladder.temporal) == 7
    for row in ladder.temporal:
        stamps = np.asarray(_point(decoded, row.label).time_s, dtype=float)
        intervals = np.diff(stamps)
        assert row.profiles == stamps.size
        assert row.median_interval_s == pytest.approx(
            float(np.median(intervals)), rel=1e-12, abs=1e-15
        )
        assert row.mean_interval_s == pytest.approx(
            float(np.mean(intervals)), rel=1e-12, abs=1e-15
        )
        assert row.achieved_period_s == pytest.approx(row.median_interval_s, rel=1e-12)
        assert row.record_duration_s == pytest.approx(
            float(stamps[-1] - stamps[0]), rel=1e-12
        )
        assert row.first_block_start_s == pytest.approx(float(stamps[0]), rel=1e-12)
        # the retired planning law is a different number at every level
        assert not math.isclose(
            row.achieved_period_s,
            row.emissions_times_prf_s + sel.RETIRED_PERIOD_TRANSFER_S,
            rel_tol=0.0,
            abs_tol=1e-9,
        )


def test_the_request_expected_periods_are_matched_by_the_measurements(ladder) -> None:
    """The WP4 request's four expected periods, checked rather than adopted."""
    measured = {row.label: row.achieved_period_s for row in ladder.temporal}
    for prediction in ladder.predictions:
        assert prediction.expected_period_s == sel.EXPECTED_PERIOD_S[prediction.level]
        assert prediction.expected_rate_hz == sel.EXPECTED_RATE_HZ[prediction.level]
        assert prediction.period_tolerance_s == sel.PERIOD_EXPECTATION_TOLERANCE_S
        assert prediction.rate_tolerance_hz == sel.RATE_EXPECTATION_TOLERANCE_HZ
        assert prediction.agrees is True
        assert abs(prediction.period_difference_s) <= (
            sel.PERIOD_EXPECTATION_TOLERANCE_S
        )
        assert abs(prediction.rate_difference_hz) <= sel.RATE_EXPECTATION_TOLERANCE_HZ
        level_rows = [row for row in ladder.temporal if row.level == prediction.level]
        assert prediction.records_compared == len(level_rows)
        for row in level_rows:
            assert measured[row.label] == pytest.approx(
                prediction.measured_period_s, rel=1e-12
            )
    # the levels' own rates are the reciprocal of the measured periods
    assert ladder.predictions[0].measured_rate_hz == pytest.approx(
        1.0 / measured["e8"], rel=1e-12
    )


def test_the_rate_nyquist_and_resolution_arithmetic_holds(ladder) -> None:
    for row in ladder.temporal:
        assert row.profile_rate_hz == pytest.approx(
            1.0 / row.achieved_period_s, rel=1e-12
        )
        assert row.nyquist_hz == pytest.approx(0.5 * row.profile_rate_hz, rel=1e-12)
        assert row.frequency_resolution_hz == pytest.approx(
            1.0 / row.record_duration_s, rel=1e-12
        )
        assert row.fixed_overhead_s == pytest.approx(
            row.achieved_period_s - row.emissions_times_prf_s, rel=1e-12
        )
        assert row.fixed_overhead_s > 0.0
        # the intercept is not the transfer term: it is 16 PRF terms plus the transfer
        assert row.internal_emission_s == pytest.approx(16 * 600e-6, rel=1e-12)
        assert row.transfer_term_s == pytest.approx(
            row.fixed_overhead_s - row.internal_emission_s, rel=1e-12
        )
    # the emissions term is the declared one: emissions x 600 us, from the record itself
    emissions = {row.label: row.emissions_per_profile for row in ladder.records}
    for row in ladder.temporal:
        assert row.emissions_times_prf_s == pytest.approx(
            emissions[row.label] * 600e-6, rel=1e-9
        )
        assert row.fixed_overhead_s == pytest.approx(
            row.achieved_period_s - emissions[row.label] * 600e-6, rel=1e-12
        )
        assert row.transfer_term_s == pytest.approx(
            row.fixed_overhead_s - 16 * 600e-6, rel=1e-12
        )
    rates = [row.profile_rate_hz for row in ladder.temporal]
    nyquists = [row.nyquist_hz for row in ladder.temporal]
    assert rates[0] > rates[1] > rates[5] > rates[6]
    assert nyquists[0] > nyquists[1] > nyquists[5] > nyquists[6]


def test_the_segmentation_is_by_physical_duration_with_equal_blocks(
    ladder, decoded
) -> None:
    for row in ladder.temporal:
        stamps = np.asarray(_point(decoded, row.label).time_s, dtype=float)
        span = float(stamps[-1] - stamps[0])
        blocks = int(span // sel.BLOCK_DURATION_S)
        assert row.block_duration_s == sel.BLOCK_DURATION_S == 2.0
        assert row.blocks == blocks == 6
        bounds = list(row.block_bounds_s)
        assert len(bounds) == blocks + 1
        assert bounds[0] == pytest.approx(float(stamps[0]), rel=1e-12)
        for index in range(blocks):
            assert bounds[index + 1] - bounds[index] == pytest.approx(
                sel.BLOCK_DURATION_S, rel=1e-12
            )
        counts = [
            int(
                np.count_nonzero(
                    (stamps >= bounds[index]) & (stamps < bounds[index + 1])
                )
            )
            for index in range(blocks)
        ]
        # equal physical durations, so the counts can differ by at most one profile
        assert max(counts) - min(counts) <= 1
        assert row.profiles_per_block_median == int(np.median(counts))
        assert row.profiles_per_block_min == min(counts)
        assert row.profiles_per_block_max == max(counts)
        assert row.last_block_start_s == pytest.approx(bounds[-2], rel=1e-12)
        # the blocks are equal in duration though the profile counts differ
        assert sum(counts) < row.profiles


def test_the_bandwidth_price_falls_with_emissions(ladder) -> None:
    per_level = {
        level: next(
            row for row in ladder.temporal if row.label == label
        ).profiles_per_block_median
        for level, (label, _) in SINGLE.items()
    }
    per_level["E20"] = next(
        row for row in ladder.temporal if row.label == "cr1"
    ).profiles_per_block_median
    assert per_level["E8"] > per_level["E20"] > per_level["E64"] > per_level["E128"]
    # the four reference runs agree with each other on the block count
    assert (
        len(
            {
                next(
                    row for row in ladder.temporal if row.label == run
                ).profiles_per_block_median
                for run in E20_RUNS
            }
        )
        == 1
    )


# ── the autocorrelation, on the full record ───────────────────────────


def test_the_autocorrelation_is_recomputed_on_the_full_record(ladder, decoded) -> None:
    assert len(ladder.acf) == 21
    for row in ladder.acf:
        series, acf = _curve(decoded, row.label, row.requested_depth_mm)
        assert row.profiles == series.size
        assert row.profiles == next(
            record.profiles_full
            for record in ladder.records
            if record.label == row.label
        )
        assert row.lag1_autocorrelation == pytest.approx(float(acf[1]), rel=1e-12)
        assert row.series_mean_mm_s == pytest.approx(float(np.mean(series)), rel=1e-12)
        assert row.series_std_mm_s == pytest.approx(float(np.std(series)), rel=1e-12)
        below = np.flatnonzero(np.abs(acf[1:]) < sel.ACF_HALF_LEVEL)
        if below.size:
            assert row.reaches_half is True
            assert row.first_lag_below_half == int(below[0] + 1)
        else:
            assert row.reaches_half is False
            assert row.first_lag_below_half == acf.size - 1
        period = next(
            item.achieved_period_s
            for item in ladder.temporal
            if item.label == row.label
        )
        assert row.first_lag_below_half_s == pytest.approx(
            row.first_lag_below_half * period, rel=1e-12
        )
    # the curves the figure draws cover the stated span, on each record's own grid
    for row in ladder.temporal:
        curve = np.asarray(getattr(ladder.acf_curves, f"acf_{row.label}"), dtype=float)
        expected = max(1, round(sel.ACF_MAX_LAG_S / row.achieved_period_s))
        assert curve.size == min(expected, row.profiles - 1)
        assert np.all(np.abs(curve) <= 1.0 + 1e-9)
    # the three stated depths resolve to distinct native gates on the shared grid
    assert len({row.depth_mm for row in ladder.acf if row.label == "e8"}) == 3
    assert ladder.acf[0].requested_depth_mm == sel.ACF_DEPTHS_MM[0]


# ── the artefacts ─────────────────────────────────────────────────────


def test_the_csv_is_five_blocks_with_their_own_column_contract(ladder) -> None:
    text = (REPORT_DIR / sel.CSV_NAME).read_text(encoding="utf-8")
    raw = (REPORT_DIR / sel.CSV_NAME).read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    blocks = [block for block in text.split("\n\n") if block.strip()]
    assert len(blocks) == 5
    headers = [block.splitlines()[0] for block in blocks]
    assert headers[0] == ",".join(sel.LEVEL_COLUMNS)
    assert headers[1] == ",".join(sel.DIFFERENCE_COLUMNS)
    assert headers[2] == ",".join(sel.BRACKET_COLUMNS)
    assert headers[3] == ",".join(sel.TEMPORAL_COLUMNS)
    assert headers[4] == ",".join(sel.ACF_COLUMNS)
    row_counts = [len(list(csv.DictReader(block.splitlines()))) for block in blocks]
    assert row_counts == [
        len(ladder.records) * len(sel.STATISTICS),
        len(ladder.differences),
        len(ladder.brackets),
        len(ladder.temporal),
        len(ladder.acf),
    ]
    assert row_counts == [35, 9, 6, 7, 21]
    level_rows = list(csv.DictReader(blocks[0].splitlines()))
    assert {(row["level"], row["label"]) for row in level_rows} == {
        (record.level, record.label) for record in ladder.records
    }
    assert {row["statistic"] for row in level_rows} == set(sel.STATISTICS)
    time_rows = list(csv.DictReader(blocks[3].splitlines()))
    published = {row["label"]: row for row in time_rows}
    for row in ladder.temporal:
        assert float(published[row.label]["achieved_period_s"]) == pytest.approx(
            row.achieved_period_s, rel=1e-11
        )
        assert float(published[row.label]["nyquist_hz"]) == pytest.approx(
            row.nyquist_hz, rel=1e-11
        )
        assert float(
            published[row.label]["profiles_per_block_median"]
        ) == pytest.approx(float(row.profiles_per_block_median), rel=1e-11)
    assert text.count("\n") == len(text.splitlines())


def test_the_document_carries_the_evidence_the_floors_the_predictions_and_the_gate(
    document, ladder
) -> None:
    assert document["analysis_commit"] == COMMIT
    assert document["ok"] is True
    assert set(document["checks"]) == set(ladder.checks)
    assert all(document["checks"].values())
    assert document["table"] == sel.CSV_NAME
    assert document["table_rows"] == 35 + 9 + 6 + 7 + 21
    assert document["view_2_temporal_cost"]["segment_duration_s"] == (
        sel.BLOCK_DURATION_S
    )
    assert len(document["evidence"]["levels"]) == 4
    assert len(document["floors"]["bindings"]) == 5
    assert len(document["predictions"]) == 4
    assert all(row["agrees"] for row in document["predictions"])
    assert len(document["not_here"]) == len(sel.NOT_HERE) >= 6
    assert "unequal evidence" in document["evidence"]["caveat"]
    assert "never mixed" in document["floors"]["rule"]
    assert "refused" in document["view_2_temporal_cost"]["retired_planning_law"]
    assert document["view_2_temporal_cost"]["segment_duration_s"] == 2.0
    assert document["view_1_velocity_stability"]["window_s"] == DESIGNED_WINDOW_S
    assert len(document["depth_resolved"]) == 23
    for level in document["levels"]:
        assert level["evidence"] and level["stated_variation_mm_s"] > 0.0


def test_the_markdown_prose_carries_the_reading_and_the_caveats(ladder) -> None:
    text = (REPORT_DIR / sel.MD_NAME).read_text(encoding="utf-8")
    plain = " ".join(text.replace("**", "").replace("`", "").split())
    assert "one scientific recording each" in plain
    assert "four runs" in plain
    assert "no averaged E20 profile" in plain
    assert "not evidence that E128 caused a change" in plain
    assert "which endpoint applies where" in plain
    assert "What is deliberately not here" in plain
    assert "no confidence interval" in plain or "not confidence intervals" in plain
    # the four expected periods are published beside the measured ones
    for prediction in ladder.predictions:
        assert f"{prediction.expected_period_s * 1e3:.1f}" in plain
        assert f"{prediction.measured_rate_hz:.3f}" in plain
    # the level-to-evidence table agrees with the model it summarises
    cells: dict[str, list[str]] = {}
    in_table = False
    for line in text.splitlines():
        if line.startswith("| level | emissions | records | jobs |"):
            in_table = True
            continue
        if in_table and not line.startswith("|"):
            break
        if in_table:
            row = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(row) == 7 and row[0] in ("E8", "E20", "E64", "E128"):
                cells[row[0]] = row
    assert set(cells) == {"E8", "E20", "E64", "E128"}
    for level in ladder.levels:
        assert cells[level.level][1] == str(level.emissions_per_profile)
        assert cells[level.level][2] == ", ".join(level.records)
        assert cells[level.level][3] == ", ".join(level.jobs)
        assert cells[level.level][4] == str(len(level.records))
        assert cells[level.level][5] == f"{level.stated_variation_mm_s:.3f}"


def test_the_command_writes_the_same_bytes_twice_including_both_figures(
    tmp_path,
) -> None:
    first = _re_published_artefacts(tmp_path, where="a")
    second = _re_published_artefacts(tmp_path, where="b")
    for directory in (first, second):
        sel.write_emissions_ladder(
            ROOT / DATASET_ROOT,
            directory,
            plan_path=ROOT / PLAN_PATH,
            analysis_commit=COMMIT,
        )
    for name in (sel.CSV_NAME, sel.DOC_NAME, sel.MD_NAME):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    # the CSV and the figures carry no revision, so the committed copies match too
    assert (first / sel.CSV_NAME).read_bytes() == (
        REPORT_DIR / sel.CSV_NAME
    ).read_bytes()
    for name in (sel.STABILITY_FIGURE, sel.TEMPORAL_FIGURE):
        a = (first / sel.FIGURES_DIRNAME / name).read_bytes()
        b = (second / sel.FIGURES_DIRNAME / name).read_bytes()
        assert a == b
        assert a.startswith(b"\x89PNG\r\n\x1a\n")
        assert a == (REPORT_DIR / sel.FIGURES_DIRNAME / name).read_bytes()


def test_the_committed_artefacts_are_reproducible_with_the_recorded_revision(
    tmp_path, monkeypatch
) -> None:
    """The committed set regenerates byte for byte from the revision it records."""
    monkeypatch.chdir(ROOT)
    recorded = json.loads((REPORT_DIR / sel.DOC_NAME).read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    assert recorded
    _copy_published_pair(tmp_path)
    sel.write_emissions_ladder(
        DATASET_ROOT,
        tmp_path,
        plan_path=PLAN_PATH,
        analysis_commit=recorded,
    )
    for name in (sel.CSV_NAME, sel.DOC_NAME, sel.MD_NAME):
        committed = (REPORT_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert (tmp_path / name).read_bytes() == committed
    for name in (sel.STABILITY_FIGURE, sel.TEMPORAL_FIGURE):
        assert (tmp_path / sel.FIGURES_DIRNAME / name).read_bytes() == (
            REPORT_DIR / sel.FIGURES_DIRNAME / name
        ).read_bytes()


# ── the refusals ──────────────────────────────────────────────────────


def test_a_record_without_a_stored_time_array_is_refused_by_name(
    tmp_path, monkeypatch
) -> None:
    """The retired planning expectation is never a substitute for a timestamp."""
    real = decode_pass()
    for broken_value, expected in (
        (None, "no per-profile time array"),
        (np.zeros(0, dtype=float), "stored profile timestamps"),
    ):
        points = tuple(
            point._replace(time_s=broken_value)
            if str(point.binding.point.label) == "e8"
            else point
            for point in real.points
        )
        broken = real._replace(points=points)

        def _refuse(*args, _broken=broken, **kwargs):
            return _broken

        monkeypatch.setattr(sel, "decode_pass", _refuse)
        with pytest.raises(sel.EmissionsLadderError, match=expected):
            sel.build_emissions_ladder(analysis_commit=COMMIT)
        report = tmp_path / f"reports-{expected[:4]}"
        with pytest.raises(SparseIngestError):
            sel.write_emissions_ladder(
                ROOT / DATASET_ROOT,
                report,
                plan_path=ROOT / PLAN_PATH,
                analysis_commit=COMMIT,
            )
        assert not (report / sel.CSV_NAME).exists()
        assert not (report / sel.DOC_NAME).exists()
        assert not (report / sel.FIGURES_DIRNAME).exists()


def test_a_record_at_another_levels_condition_or_job_is_refused(decoded) -> None:
    """A level is measured from the recording the ladder declares, and only that one."""
    e64 = _point(decoded, "e64")
    with pytest.raises(sel.EmissionsLadderError, match="declared condition"):
        sel._require_record("E128", "e64", "emissions-64", e64, decoded)
    with pytest.raises(sel.EmissionsLadderError, match="the level's source"):
        sel._require_record("E64", "e64", "emissions-8", e64, decoded)
    with pytest.raises(sel.EmissionsLadderError, match="asked for"):
        sel._require_record("E64", "e8", "emissions-64", e64, decoded)


def test_a_broken_dataset_is_refused_and_writes_no_half_artefact(tmp_path) -> None:
    dataset = _copy_dataset(tmp_path)
    (dataset / "sparse-mixer-live-1-emissions-8.jsonl").write_text("", encoding="utf-8")
    report = tmp_path / "reports"
    with pytest.raises(SparseIngestError):
        sel.write_emissions_ladder(
            dataset, report, plan_path=ROOT / PLAN_PATH, analysis_commit=COMMIT
        )
    assert not (report / sel.CSV_NAME).exists()
    assert not (report / sel.DOC_NAME).exists()
    assert not (report / sel.MD_NAME).exists()
    assert not (report / sel.FIGURES_DIRNAME).exists()


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_root(
    tmp_path, capsys
) -> None:
    reports = tmp_path / "reports"
    _copy_published_pair(reports)
    with pytest.raises(SystemExit) as accepted:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                (ROOT / DATASET_ROOT).as_posix(),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(tmp_path / "reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert accepted.value.code == 0
    printed = capsys.readouterr().out
    assert "checks  : all pass" in printed
    assert (tmp_path / "reports" / sel.CSV_NAME).is_file()
    assert (tmp_path / "reports" / sel.FIGURES_DIRNAME / sel.STABILITY_FIGURE).is_file()

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as refused:
        sel.emissions_ladder_main(
            [
                "--dataset-root",
                str(broken),
                "--plan-path",
                (ROOT / PLAN_PATH).as_posix(),
                "--report-dir",
                str(tmp_path / "broken-reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert refused.value.code == 1
    assert "udv-sparse-emissions-ladder:" in capsys.readouterr().err
    assert not (tmp_path / "broken-reports" / sel.CSV_NAME).exists()


# ── the review's interpretation pins ─────────────────────────────────


def _plain(text: str) -> str:
    """The report with markdown emphasis and wrapping removed, for prose pins."""
    for marker in ("**", "*", "`"):
        text = text.replace(marker, "")
    return " ".join(text.split())


def test_the_e20_to_e64_step_is_reported_as_straddling_the_floor(ladder) -> None:
    """The review's defect: a 6.405 mm/s span was called smaller than 4.235 mm/s."""
    step = ladder.steps[1]
    assert abs(step.mean_difference_min_mm_s) > 4.235  # the number the report denied
    floor = ladder.published_floors.depth_averaged.published_mm_s
    assert abs(step.mean_difference_min_mm_s) > floor
    assert abs(step.mean_difference_max_mm_s) < floor

    doc = _plain((REPORT_DIR / sel.MD_NAME).read_text(encoding="utf-8"))
    assert "smaller in magnitude" not in doc
    reading = doc[doc.index("The depth-averaged steps") :]
    bubble = reading[reading.index("E20->E64") : reading.index("E64->E128")]
    assert "straddles" in bubble
    assert "some of the four E20" in bubble
    assert "suggestive against E20 and unresolved by this pass" in bubble
    e64_to_e128 = reading[reading.index("E64->E128") :]
    assert "within" in e64_to_e128[:400]


def test_the_intercept_is_named_and_decomposed_not_called_the_transfer_term(
    ladder, document
) -> None:
    """The review's defect: the fixed intercept was labelled the transfer term."""
    rows = ladder.temporal
    assert all(
        row.fixed_overhead_s
        == pytest.approx(row.achieved_period_s - row.emissions_times_prf_s)
        for row in rows
    )
    assert all(row.internal_emission_s == pytest.approx(16 * 600e-6) for row in rows)
    assert all(
        row.transfer_term_s == pytest.approx(row.fixed_overhead_s - 16 * 600e-6)
        for row in rows
    )
    # the intercept is constant at 10.400 ms; the transfer term proper is ~0.800 ms
    assert {round(row.fixed_overhead_s * 1e3, 3) for row in rows} == {10.4}
    assert {round(row.transfer_term_s * 1e3, 3) for row in rows} == {0.8}

    definitions = document["definitions"]
    assert "NOT the transfer term" in definitions["fixed_overhead_s"]
    assert "16 PRF terms" in definitions["fixed_overhead_s"]
    assert "internal_emission_s" in definitions["fixed_overhead_s"]
    assert "16 x prf" in definitions["internal_emission_s"]
    assert "minus internal_emission_s" in definitions["transfer_term_s"]

    prose = _plain((REPORT_DIR / sel.MD_NAME).read_text(encoding="utf-8"))
    assert "fixed overhead" in prose.lower()
    assert "fixed overhead / intercept = 10.4" not in prose  # no invented notation
    assert "transfer term proper" in prose or "transfer term (`achieved" in prose


def test_the_autocorrelation_reading_reports_both_units_with_the_right_direction(
    ladder,
) -> None:
    """The review's defect: the physical-time direction was stated backwards."""
    at_gate = {
        row.label: row
        for row in ladder.acf
        if row.requested_depth_mm == sel.ACF_DEPTHS_MM[0]
    }
    # the fact the sentence must follow: larger first-lag time = slower decorrelation
    assert (
        at_gate["e128"].first_lag_below_half_s > at_gate["e8"].first_lag_below_half_s
    ), "the physical-time direction the report must state"
    assert (
        at_gate["e64"].first_lag_below_half_s > at_gate["e128"].first_lag_below_half_s
    ), "the non-monotonicity the report must not smooth over"
    assert at_gate["e8"].first_lag_below_half > at_gate["e128"].first_lag_below_half

    doc = _plain((REPORT_DIR / sel.MD_NAME).read_text(encoding="utf-8"))
    reading = doc[doc.index("Two readings, reported independently") :]
    assert "decorrelate faster" not in reading
    assert "survives longer" in reading
    assert f"{at_gate['e8'].first_lag_below_half_s:.3f} s at e8" in reading
    assert f"{at_gate['e128'].first_lag_below_half_s:.3f} s at e128" in reading
    assert "slower" in reading
    # the two units are reported independently, and the non-monotonicity is named
    assert "In profile lags" in reading
    assert "not monotone" in reading
    assert f"{at_gate['e64'].first_lag_below_half_s:.3f} s" in reading
    assert "rather than as one ordering" in reading


# ── the document and its table are read as one pair, or not at all ───


def test_a_published_floor_edited_in_the_document_alone_is_refused(tmp_path) -> None:
    """The digest ties the document to its table; the table ties the *number* back.

    An edited ``anchor-floor.json`` keeps a valid ``table_sha256`` — the table did not move —
    so the digest on its own would let a floor the recordings never measured become the one
    this slice screens with. The reader takes the number only while the authenticated table
    carries the same one, so the pair has to be moved together or not at all.
    """
    document_only = tmp_path / "document-only"
    _copy_published_pair(document_only)
    path = document_only / ANCHOR_FLOOR_DOC
    document = json.loads(path.read_text(encoding="utf-8"))
    document["jobs"][0]["spread"][sel.RESIDUAL_STATISTIC] = 99.0
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(
        sel.EmissionsLadderError, match="the authenticated table carries"
    ):
        sel.read_published_floors(
            document_only,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(document_only),
        )

    endpoint_only = tmp_path / "endpoint-only"
    _copy_published_pair(endpoint_only)
    path = endpoint_only / REFERENCE_FLOOR_DOC
    document = json.loads(path.read_text(encoding="utf-8"))
    document["floor"]["depth_averaged"]["value_mm_s"] = 99.0
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(
        sel.EmissionsLadderError, match="the authenticated table carries"
    ):
        sel.read_published_floors(
            endpoint_only,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(endpoint_only),
        )

    pair_only = tmp_path / "pair-only"
    _copy_published_pair(pair_only)
    path = pair_only / REFERENCE_FLOOR_DOC
    document = json.loads(path.read_text(encoding="utf-8"))
    document["floor"]["depth_resolved"]["pair"] = ["cr1", "cr4"]
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(sel.EmissionsLadderError, match="the pair"):
        sel.read_published_floors(
            pair_only,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(pair_only),
        )


def test_a_published_table_edited_alone_is_refused(tmp_path) -> None:
    """Editing the table alone is caught by the digest the document publishes for it."""
    moved = tmp_path / "moved"
    _copy_published_pair(moved)
    table = moved / Path(ANCHOR_FLOOR_DOC).with_suffix(".csv")
    blocks = _table_blocks(table)
    blocks[0] = [
        {**row, "value": "1.0"}
        if row["statistic"] == sel.RESIDUAL_STATISTIC
        and row["quantity"] == "anchor_range"
        else row
        for row in blocks[0]
    ]
    _write_table(table, blocks)
    with pytest.raises(sel.EmissionsLadderError, match="hashes to"):
        sel.read_published_floors(
            moved,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(moved),
        )

    emptied = tmp_path / "emptied"
    _copy_published_pair(emptied)
    (emptied / Path(REFERENCE_FLOOR_DOC).with_suffix(".csv")).write_text(
        "", encoding="utf-8"
    )
    with pytest.raises(sel.EmissionsLadderError, match="hashes to"):
        sel.read_published_floors(
            emptied,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(emptied),
        )

    tableless = tmp_path / "tableless"
    _copy_published_pair(tableless)
    (tableless / Path(ANCHOR_FLOOR_DOC).with_suffix(".csv")).unlink()
    with pytest.raises(sel.EmissionsLadderError, match="anchor-floor.csv"):
        sel.read_published_floors(
            tableless,
            plan_name="sparse-mixer-live-1",
            plan_fingerprint=_fingerprint(tableless),
        )


def _fingerprint(report: Path) -> str:
    """The pass identity the documents in one directory state."""
    document = json.loads((report / ANCHOR_FLOOR_DOC).read_text(encoding="utf-8"))
    return str(document["plan_fingerprint"])
