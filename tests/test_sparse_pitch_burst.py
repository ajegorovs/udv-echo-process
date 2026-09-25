"""Focused tests for WP3 — the sparse pass's 2x2 pitch x burst interaction.

The tests pin what this slice exists to state, and what it must not: the four corners
are read from the decoded recordings and re-checked against the plan's own declaration
(the burst-4 job holds ``cc1``/``cc3``, the burst-18 job ``cc2``/``cc4``); the corners
are aligned on the 2.96 mm measurement's own native knots by each corner's **nearest
native gate**, with the native depth and the offset published and a refusal above half
the coarse pitch; ``I(z)`` is recomputable per knot, its reduction signed, and the four
simple effects carry it as identities; every depth-resolved magnitude is screened
against WP2's depth-resolved endpoint and every scalar against WP2's depth-averaged one;
the two burst jobs' anchors are context and never cells; and a refusal writes nothing.

Every published number is recomputed here from the committed recordings through the
shared loader, so a change in the artefacts that does not survive the recordings fails.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_pitch_burst as spb
from udv_echo_process.analysis._native_grid import nearest_gate_indices
from udv_echo_process.analysis._sparse_pass import (
    decode_pass,
    gate_statistics,
    supported_gates,
    supported_mean_of,
)
from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    PLAN_PATH,
    REPORT_DIR,
    SparseIngestError,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "0123456789012345678901234567890123456789"


@pytest.fixture(scope="module")
def decoded():
    return decode_pass()


@pytest.fixture(scope="module")
def model():
    return spb.build_pitch_burst(analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def document(model):
    return spb.def_document(model)


@pytest.fixture(scope="module")
def floors(decoded):
    """**This pass's own** floors, as the slice reads them: from its WP1/WP2 documents."""
    return spb.load_pass_floors(REPORT_DIR, plan_fingerprint=decoded.plan_fingerprint)


def _seed(directory: Path, *names: str) -> Path:
    """A report directory seeded with this pass's own floor documents, byte for byte."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names or (spb.ANCHOR_FLOOR_DOC_NAME, spb.REFERENCE_FLOOR_DOC_NAME):
        (directory / name).write_bytes((REPORT_DIR / name).read_bytes())
    return directory


def _tamper(directory: Path, name: str, mutate) -> None:
    """One field of one published floor document, rewritten in place (never in reports/)."""
    path = directory / name
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


def _build(report_dir: Path):
    """WP3 on the committed pass, screening against the floors in ``report_dir``."""
    return spb.build_pitch_burst(
        ROOT / DATASET_ROOT,
        report_dir=report_dir,
        plan_path=ROOT / PLAN_PATH,
        analysis_commit=COMMIT,
    )


def _point(decoded, label: str):
    """One recording of the pass by its label, from the decoded pass itself."""
    matches = [
        point for point in decoded.points if str(point.binding.point.label) == label
    ]
    assert len(matches) == 1, label
    return matches[0]


def _anchor_point(decoded, job: str, label: str):
    """One block-local anchor of one job, from the decoded pass itself."""
    matches = [
        point
        for point in decoded.of_job(job)
        if str(point.binding.point.label) == label
    ]
    assert len(matches) == 1, (job, label)
    return matches[0]


def _corner_values(decoded, label: str) -> tuple[np.ndarray, np.ndarray]:
    """One corner's **native supported depths** and its per-gate window means.

    Recomputed from the recording through the shared loader, never from the artefacts.
    """
    point = _point(decoded, label)
    values = gate_statistics(
        point, window_s=decoded.window_s, support_mm=decoded.support_mm
    )[spb.STATISTIC]
    return supported_gates(point, decoded.support_mm), values


def _native_read(decoded, label: str, knots: np.ndarray) -> np.ndarray:
    """One corner read at its nearest native gate to every knot, recomputed here."""
    depths, values = _corner_values(decoded, label)
    return values[nearest_gate_indices(depths, knots)]


def _expanded_columns(model) -> dict[str, str]:
    """The document's column definitions with every ``cc*`` pattern expanded."""
    expanded: dict[str, str] = {}
    for name, text in spb.def_document(model)["columns"].items():
        if "cc*" in name:
            for label in spb.CORNER_LABELS:
                expanded[name.replace("cc*", label)] = text
        else:
            expanded[name] = text
    return expanded


# ── the corners, from the recordings and the plan ─────────────────────


def test_the_corner_to_job_to_condition_map_is_the_decoded_one(decoded, model) -> None:
    """The brief's mapping is verified, not trusted: cc1/cc3 in burst-4, cc2/cc4 in 18."""
    assert spb.CORNERS == (
        ("cc1", "burst-4", 0.617, 4),
        ("cc2", "burst-18", 0.617, 18),
        ("cc3", "burst-4", 2.96, 4),
        ("cc4", "burst-18", 2.96, 18),
    )
    for label, job, _pitch, burst in spb.CORNERS:
        point = _point(decoded, label)
        assert str(point.binding.job.job) == job
        assert int(point.config.burst_length) == burst
    # the decoded condition is the plan's own request, with the pitch ladder's snap
    for corner in model.corners:
        assert corner.pitch_requested_mm == corner.plan_resolution_mm
        assert corner.gates == corner.plan_gates
        assert corner.burst_length == corner.plan_burst_length
        assert corner.emissions_per_profile == corner.plan_emissions_per_profile
    assert [corner.label for corner in model.corners] == list(spb.CORNER_LABELS)
    assert {corner.emissions_per_profile for corner in model.corners} == {20}
    assert {corner.pitch_stored_mm for corner in model.corners} == {
        0.6166666666666667,
        2.96,
    }


def test_a_corner_whose_decoded_condition_moved_is_refused(decoded) -> None:
    """The map is a check, not a comment: a corner at another pitch refuses by name.

    The fabrication is the *configuration* of a fixture, validated through the model's
    own validator; the recording's measured values are untouched.
    """
    victim = _point(decoded, "cc1")
    wrong = type(victim.config).model_validate(
        {**victim.config.model_dump(), "resolution_mm": 1.85, "n_gates": 50}
    )
    mutated = decoded._replace(
        points=tuple(
            victim._replace(config=wrong) if point is victim else point
            for point in decoded.points
        )
    )
    with pytest.raises(spb.PitchBurstError, match="cc1"):
        spb.measure(mutated, analysis_commit=COMMIT, plan_path=ROOT / PLAN_PATH)


def test_a_corner_that_is_missing_from_its_job_is_refused(decoded) -> None:
    without = decoded._replace(
        points=tuple(
            point for point in decoded.points if point is not _point(decoded, "cc4")
        )
    )
    with pytest.raises(spb.PitchBurstError, match="expected exactly"):
        spb.measure(without, analysis_commit=COMMIT, plan_path=ROOT / PLAN_PATH)


# ── the knots, and the alignment ──────────────────────────────────────


def test_the_knots_are_the_coarse_measurements_own_native_gates(decoded, model) -> None:
    coarse = [
        supported_gates(_point(decoded, label), decoded.support_mm)
        for label in spb.KNOT_LABELS
    ]
    assert np.array_equal(coarse[0], coarse[1])
    published = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    assert np.array_equal(published, coarse[0])
    assert published.size == model.knot_count == len(model.knots) == 31
    assert float(np.diff(published).mean()) == pytest.approx(
        spb.COARSE_PITCH_MM, rel=1e-9
    )
    assert [row.depth_mm for row in model.knots] == list(published)
    for row in model.knots:
        for label in spb.KNOT_LABELS:
            assert row.offset_mm[label] == 0.0
            assert row.native_mm[label] == row.depth_mm
    assert model.knot_source == spb.KNOT_LABELS


def test_every_knot_value_is_a_native_gate_read_of_its_own_corner(
    decoded, model
) -> None:
    knots = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    for label in spb.CORNER_LABELS:
        depths = _corner_values(decoded, label)[0]
        expected = _native_read(decoded, label, knots)
        native = np.asarray([row.native_mm[label] for row in model.knots], dtype=float)
        offsets = np.asarray([row.offset_mm[label] for row in model.knots], dtype=float)
        values = np.asarray(
            [row.corner_mm_s[label] for row in model.knots], dtype=float
        )
        assert np.allclose(native - knots, offsets, rtol=0.0, atol=1e-12)
        assert np.allclose(values, expected, rtol=0.0, atol=1e-12)
        for depth in native:
            assert float(np.abs(depths - depth).min()) == 0.0
        assert np.allclose(
            getattr(model.depth_resolved, label), expected, rtol=0.0, atol=0.0
        )
        assert np.abs(offsets).max() <= 0.5 * model.knot_pitch_mm + spb.TOLERANCE


def test_the_largest_offset_is_published_and_inside_half_the_coarse_pitch(
    model,
) -> None:
    worst_value = max(
        abs(row.offset_mm[label]) for row in model.knots for label in spb.CORNER_LABELS
    )
    assert model.max_abs_offset_mm == pytest.approx(worst_value, rel=1e-12)
    assert model.max_abs_offset_mm == pytest.approx(0.246667, abs=5e-7)
    assert model.max_abs_offset_mm < model.half_coarse_pitch_mm
    assert model.half_coarse_pitch_mm == pytest.approx(
        spb.HALF_COARSE_PITCH_MM, rel=1e-9
    )
    worst_row = model.knots[model.max_abs_offset_knot]
    assert abs(worst_row.offset_mm[model.max_abs_offset_label]) == pytest.approx(
        model.max_abs_offset_mm, rel=1e-12
    )
    assert model.max_abs_offset_depth_mm == worst_row.depth_mm


def test_the_half_pitch_refusal_fires_on_a_fabricated_pair_of_grids() -> None:
    """A coarse knot the grid cannot reach inside the limit refuses, naming the offset."""
    fine = np.array([10.0, 10.2, 10.4, 10.6, 10.8, 11.0])
    values = np.arange(fine.size, dtype=float)
    with pytest.raises(spb.PitchBurstError, match="half the coarse pitch"):
        spb.align_corner(
            "cc1", fine, values, np.array([10.0, 12.5]), half_pitch_mm=1.48
        )
    # … and the same pair passes when the knots are inside the limit's reach
    aligned = spb.align_corner(
        "cc1", fine, values, np.array([10.0, 11.0]), half_pitch_mm=1.48
    )
    assert np.array_equal(aligned.native_mm, np.array([10.0, 11.0]))
    assert np.array_equal(aligned.offset_mm, np.zeros(2))
    assert np.array_equal(aligned.values_mm_s, np.array([0.0, 5.0]))
    # an offset inside the limit is used, not refused: the pair straddles 12.0 and 14.0
    edge = spb.align_corner(
        "cc3",
        np.array([10.0, 12.96]),
        np.array([1.0, 2.0]),
        np.array([12.0, 14.0]),
        half_pitch_mm=1.48,
    )
    assert np.abs(edge.offset_mm).max() == pytest.approx(1.04, abs=1e-12)
    assert np.array_equal(edge.values_mm_s, np.array([2.0, 2.0]))


# ── the interaction, from the recordings ──────────────────────────────


def test_the_interaction_recomputes_from_the_recordings_and_reduces_to_its_mean(
    decoded, model
) -> None:
    knots = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    reads = {label: _native_read(decoded, label, knots) for label in spb.CORNER_LABELS}
    interaction = (reads["cc2"] - reads["cc4"]) - (reads["cc1"] - reads["cc3"])
    published = np.asarray(model.depth_resolved.interaction, dtype=float)
    assert np.allclose(published, interaction, rtol=0.0, atol=1e-12)
    assert model.interaction_reduction_mm_s == pytest.approx(
        float(np.mean(interaction)), rel=1e-12, abs=1e-15
    )
    assert model.interaction_reduction_mm_s == pytest.approx(-7.922469, abs=5e-7)
    assert model.interaction_reduction_mm_s < 0.0, "the sign is published, not dropped"
    for row in model.knots:
        assert row.interaction_mm_s == pytest.approx(
            (row.corner_mm_s["cc2"] - row.corner_mm_s["cc4"])
            - (row.corner_mm_s["cc1"] - row.corner_mm_s["cc3"]),
            rel=1e-12,
            abs=1e-15,
        )


def test_the_interaction_extremes_are_the_published_knots(decoded, model) -> None:
    knots = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    reads = {label: _native_read(decoded, label, knots) for label in spb.CORNER_LABELS}
    interaction = (reads["cc2"] - reads["cc4"]) - (reads["cc1"] - reads["cc3"])
    lowest = int(np.argmin(interaction))
    highest = int(np.argmax(interaction))
    assert model.interaction_min_mm_s == pytest.approx(
        float(interaction[lowest]), rel=1e-12
    )
    assert model.interaction_min_depth_mm == pytest.approx(float(knots[lowest]))
    assert model.interaction_max_mm_s == pytest.approx(
        float(interaction[highest]), rel=1e-12
    )
    assert model.interaction_max_depth_mm == pytest.approx(float(knots[highest]))
    assert model.interaction_max_abs_mm_s == pytest.approx(
        float(np.abs(interaction).max()), rel=1e-12
    )
    assert model.interaction_min_mm_s == pytest.approx(-21.743077, abs=5e-7)
    assert model.interaction_min_depth_mm == pytest.approx(45.658, abs=5e-4)
    assert model.interaction_max_mm_s == pytest.approx(7.614788, abs=5e-7)
    assert model.interaction_max_depth_mm == pytest.approx(60.458, abs=5e-4)
    assert model.interaction_max_abs_mm_s == model.interaction_min_mm_s * -1.0


def test_the_four_simple_effects_recompute_and_carry_the_interaction(
    decoded, model
) -> None:
    knots = np.asarray(model.depth_resolved.knots_mm, dtype=float)
    reads = {label: _native_read(decoded, label, knots) for label in spb.CORNER_LABELS}
    expected = {
        "pitch_at_burst_4": reads["cc3"] - reads["cc1"],
        "pitch_at_burst_18": reads["cc4"] - reads["cc2"],
        "burst_at_pitch_0617": reads["cc2"] - reads["cc1"],
        "burst_at_pitch_296": reads["cc4"] - reads["cc3"],
    }
    assert {contrast.name for contrast in model.contrasts} == set(expected)
    for contrast in model.contrasts:
        values = expected[contrast.name]
        assert np.allclose(
            getattr(model.depth_resolved, contrast.name), values, rtol=0.0, atol=1e-12
        )
        assert contrast.mean_mm_s == pytest.approx(
            float(np.mean(values)), rel=1e-12, abs=1e-15
        )
        assert contrast.max_abs_mm_s == pytest.approx(
            float(np.abs(values).max()), rel=1e-12
        )
        assert contrast.min_mm_s == pytest.approx(float(values.min()), rel=1e-12)
        assert contrast.max_mm_s == pytest.approx(float(values.max()), rel=1e-12)
        assert knots[int(np.argmin(values))] == pytest.approx(contrast.min_depth_mm)
        assert knots[int(np.argmax(np.abs(values)))] == pytest.approx(
            contrast.max_abs_depth_mm
        )
    interaction = np.asarray(model.depth_resolved.interaction, dtype=float)
    for first, second in (
        ("burst_at_pitch_0617", "burst_at_pitch_296"),
        ("pitch_at_burst_4", "pitch_at_burst_18"),
    ):
        assert np.allclose(
            expected[first] - expected[second], interaction, rtol=0.0, atol=1e-12
        )
    assert model.contrasts[0].mean_mm_s == pytest.approx(-5.787428, abs=5e-7)
    assert model.contrasts[1].mean_mm_s == pytest.approx(2.135041, abs=5e-7)
    assert model.contrasts[2].mean_mm_s == pytest.approx(-4.372658, abs=5e-7)
    assert model.contrasts[3].mean_mm_s == pytest.approx(3.549811, abs=5e-7)


# ── the anchors are context, never cells ──────────────────────────────


def test_the_anchor_recordings_never_enter_the_interaction(decoded, model) -> None:
    """Double every anchor of both jobs: I(z) must not move by one ulp."""
    anchors = {
        str(point.binding.point.label)
        for point in decoded.points
        if str(point.binding.point.label).startswith(spb.CONTROL_PREFIX)
    }
    assert anchors == {"ctrl-begin", "ctrl-mid", "ctrl-end"}
    mutated = decoded._replace(
        points=tuple(
            point._replace(values=np.asarray(point.values, dtype=float) * 2.0)
            if str(point.binding.point.label).startswith(spb.CONTROL_PREFIX)
            else point
            for point in decoded.points
        )
    )
    moved = spb.measure(mutated, analysis_commit=COMMIT, plan_path=ROOT / PLAN_PATH)
    assert np.array_equal(
        np.asarray(moved.depth_resolved.interaction, dtype=float),
        np.asarray(model.depth_resolved.interaction, dtype=float),
    )
    assert moved.interaction_reduction_mm_s == model.interaction_reduction_mm_s
    assert [row.interaction_mm_s for row in moved.knots] == [
        row.interaction_mm_s for row in model.knots
    ]
    # … and the anchors are still read, for the context they are published as
    for before, after in zip(model.jobs, moved.jobs, strict=True):
        assert after.anchor_floor_mm_s == pytest.approx(
            2.0 * before.anchor_floor_mm_s, rel=1e-12
        )


def test_each_job_publishes_its_own_anchors_beside_the_corners(
    decoded, model, floors
) -> None:
    for context in model.jobs:
        assert [anchor.label for anchor in context.anchors] == [
            label for label, _ in spb.ANCHORS
        ]
        assert [anchor.short for anchor in context.anchors] == ["B", "M", "E"]
        point = _anchor_point(decoded, context.job, context.anchors[0].label)
        assert str(point.binding.job.job) == context.job
        scalars = [
            supported_mean_of(
                _anchor_point(decoded, context.job, anchor.label),
                window_s=decoded.window_s,
                support_mm=decoded.support_mm,
                name=spb.STATISTIC,
            )
            for anchor in context.anchors
        ]
        for anchor, value in zip(context.anchors, scalars, strict=True):
            assert anchor.mean_mm_s == pytest.approx(value, rel=1e-12, abs=1e-15)
        assert context.anchor_floor_mm_s == pytest.approx(
            max(scalars) - min(scalars), rel=1e-12
        )
        assert round(context.anchor_floor_mm_s, spb.FLOOR_DECIMALS) == pytest.approx(
            floors.anchor_floors_mm_s[context.job], rel=1e-12
        )
        assert context.structure.startswith("B") and context.structure.endswith("E")
    for corner in model.corners:
        context = next(item for item in model.jobs if item.job == corner.job)
        assert corner.anchor_floor_mm_s == context.anchor_floor_mm_s
        assert corner.between in (
            ("ctrl-begin", "ctrl-mid"),
            ("ctrl-mid", "ctrl-end"),
        )
        assert corner.note.endswith("neither enters I(z)")


# ── the floors, and the conservative reading ──────────────────────────


def test_the_floors_are_the_frozen_slices_numbers_with_distinct_endpoints(
    document, model
) -> None:
    floors = document["floors"]
    assert model.depth_resolved_floor_mm_s == 14.603
    assert model.depth_resolved_floor_depth_mm == 21.238
    assert model.depth_averaged_floor_mm_s == 4.235
    assert model.anchor_floors_mm_s == {"burst-4": 9.646, "burst-18": 11.980}
    assert floors["depth_resolved"]["value_mm_s"] == 14.603
    assert floors["depth_averaged"]["value_mm_s"] == 4.235
    assert floors["anchor_guards"]["value_mm_s"] == {
        "burst-4": 9.646,
        "burst-18": 11.980,
    }
    # … and every one of them is this pass's own document's number, at the precision
    # this slice publishes: the slice declares no floor of its own
    anchors = json.loads(
        (REPORT_DIR / spb.ANCHOR_FLOOR_DOC_NAME).read_text(encoding="utf-8")
    )
    spreads = {job["job"]: job["spread"]["mean"] for job in anchors["jobs"]}
    reference = json.loads(
        (REPORT_DIR / spb.REFERENCE_FLOOR_DOC_NAME).read_text(encoding="utf-8")
    )
    for job in spb.JOBS:
        assert model.anchor_floors_mm_s[job] == round(spreads[job], spb.FLOOR_DECIMALS)
    assert model.depth_resolved_floor_mm_s == round(
        reference["floor"]["depth_resolved"]["value_mm_s"], spb.FLOOR_DECIMALS
    )
    assert model.depth_resolved_floor_depth_mm == round(
        reference["floor"]["depth_resolved"]["depth_mm"], spb.FLOOR_DECIMALS
    )
    assert model.depth_averaged_floor_mm_s == round(
        reference["floor"]["depth_averaged"]["value_mm_s"], spb.FLOOR_DECIMALS
    )
    assert model.depth_resolved_floor_pair == tuple(
        reference["floor"]["depth_resolved"]["pair"]
    )
    assert "per-knot" in floors["depth_resolved"]["applies_to"]
    assert "mean over the knots" in floors["depth_averaged"]["applies_to"]
    assert "Never applied to a scalar" in floors["depth_resolved"]["applies_to"]
    assert (
        "Never applied to a per-knot magnitude"
        in (floors["depth_averaged"]["applies_to"])
    )
    assert "never" in floors["never_mixed"].lower()
    assert "WP2" in floors["depth_resolved"]["source"]
    assert "WP1" in floors["anchor_guards"]["source"]
    assert model.depth_resolved_floor_mm_s > model.depth_averaged_floor_mm_s


def test_the_floor_counts_are_recomputed_and_the_shares_are_published(
    document, model
) -> None:
    magnitude = np.abs(np.asarray(model.depth_resolved.interaction, dtype=float))
    assert model.knots_above_depth_resolved_floor == int(
        np.count_nonzero(magnitude > model.depth_resolved_floor_mm_s)
    )
    assert model.knots_above_depth_resolved_floor == 9
    for job, floor in model.anchor_floors_mm_s.items():
        assert model.knots_above_anchor_floor[job] == int(
            np.count_nonzero(magnitude > floor)
        )
    assert model.knots_above_anchor_floor == {"burst-4": 14, "burst-18": 10}
    assert model.anchor_floor_shares == pytest.approx(
        {"burst-4": 14 / 31, "burst-18": 10 / 31}, rel=1e-12
    )
    reading = document["conservative_reading"]
    assert reading["knot_count"] == model.knot_count == 31
    assert reading["knots_above_anchor_floor"] == {"burst-4": 14, "burst-18": 10}
    assert reading["knots_above_anchor_floor_share"] == pytest.approx(
        {"burst-4": 14 / 31, "burst-18": 10 / 31}, rel=1e-12
    )
    assert reading["knots_above_depth_resolved_floor"] == 9
    assert reading["resolvable_below_mm_s"] == [9.646, 11.980]
    assert reading["resolvable_below_mm_s"] == sorted(model.anchor_floors_mm_s.values())
    assert "~10-12 mm/s" in reading["statement"]
    assert "not resolvable" in reading["statement"]
    assert "neither outcome proves an axis effect" in reading["statement"]


# ── the artefacts ─────────────────────────────────────────────────────


def test_the_csv_is_the_column_contract_and_carries_the_knots(decoded, model) -> None:
    raw = (REPORT_DIR / spb.CSV_NAME).read_bytes()
    assert raw.endswith(b"\n") and b"\r\n" not in raw
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    assert tuple(rows[0]) == tuple(spb.CSV_COLUMNS)
    assert len(rows) == model.knot_count == len(model.knots) == 31
    for row, published in zip(rows, model.knots, strict=True):
        assert int(row["knot"]) == published.knot
        assert float(row["depth_mm"]) == pytest.approx(published.depth_mm, rel=1e-12)
        assert float(row["interaction_mm_s"]) == pytest.approx(
            published.interaction_mm_s, rel=1e-11
        )
        for label in spb.CORNER_LABELS:
            assert float(row[f"{label}_native_mm"]) == pytest.approx(
                published.native_mm[label], rel=1e-11
            )
            assert float(row[f"{label}_offset_mm"]) == pytest.approx(
                published.offset_mm[label], rel=1e-11, abs=1e-12
            )
            assert float(row[f"{label}_mm_s"]) == pytest.approx(
                published.corner_mm_s[label], rel=1e-11
            )
    # the first row's cell values are those recordings' own native reads at 10.138 mm
    first = rows[0]
    knot = np.asarray([float(first["depth_mm"])], dtype=float)
    for label in spb.CORNER_LABELS:
        assert float(first[f"{label}_mm_s"]) == pytest.approx(
            _native_read(decoded, label, knot)[0], rel=1e-11
        )
    assert set(_expanded_columns(model)) == set(spb.CSV_COLUMNS)


def test_the_json_checks_are_named_and_all_hold(document, model) -> None:
    required = {
        "four_corners_present",
        "corner_conditions_are_the_plans_declared_pitch_and_burst",
        "knots_are_the_coarse_grids_native_supported_gates",
        "no_alignment_offset_beyond_half_the_coarse_pitch",
        "interaction_recomputes_from_the_published_corner_profiles",
        "anchors_excluded_from_the_interaction",
        "engine_revision_recorded",
    }
    assert required <= set(model.checks)
    assert all(model.checks.values()), [
        name for name, ok in model.checks.items() if not ok
    ]
    assert model.ok is True
    assert set(document["checks"]) == set(model.checks)
    assert all(document["checks"].values())
    assert document["ok"] is True
    assert document["analysis_commit"] == COMMIT
    assert document["table_rows"] == model.knot_count
    committed = json.loads((REPORT_DIR / spb.DOC_NAME).read_text(encoding="utf-8"))
    assert committed["table_sha256"] == (
        "sha256:" + hashlib.sha256((REPORT_DIR / spb.CSV_NAME).read_bytes()).hexdigest()
    )
    assert document["alignment"]["knot_count"] == 31
    assert "no interpolation" in document["alignment"]["rule"]
    assert "nearest NATIVE gate" in document["alignment"]["rule"]
    assert "manufacture structure" in document["alignment"]["why_no_interpolation"]
    assert "half the coarse pitch (1.48 mm)" in document["alignment"]["refusal"]
    assert document["interaction"]["identities"] == [
        "I(z) = [cc2 - cc4] - [cc1 - cc3] per knot",
        "I(z) = burst_at_pitch_0617(z) - burst_at_pitch_296(z)",
        "I(z) = pitch_at_burst_4(z) - pitch_at_burst_18(z)",
    ]
    assert set(document["definitions"]) == set(spb.definitions(model))
    assert len(document["interaction"]["per_knot"]) == 31
    assert all(block["role"].startswith("context only") for block in document["blocks"])


def test_the_document_states_the_table_the_rule_the_floors_and_what_is_not_here(
    model,
) -> None:
    text = (REPORT_DIR / spb.MD_NAME).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "| pitch (mm) | burst 4 | burst 18 |" in text
    for corner in model.corners:
        assert f"`{corner.label}`" in text
        assert f"{corner.scalar_mean_native_mm_s:.3f}" in text
    assert "nearest native gate" in text
    assert "No interpolation, no resampling, no fit" in text
    assert "Fail-closed" in text
    assert f"{model.interaction_reduction_mm_s:+.3f}" in text
    assert f"{model.interaction_max_abs_mm_s:.3f}" in text
    assert "14.603" in text and "4.235" in text
    assert "9.646" in text and "11.980" in text
    assert "~10-12 mm/s" in text
    assert "not resolvable in this pass" in text
    assert "## What is deliberately not here" in text
    for clause in (
        "No causation claim",
        "The anchors are not cells",
        "No claim below ~10-12 mm/s",
        "No new acquisition",
    ):
        assert clause in text


def test_two_builds_write_the_same_bytes(tmp_path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for directory in (first, second):
        _seed(directory)
        spb.write_pitch_burst(
            ROOT / DATASET_ROOT,
            directory,
            plan_path=ROOT / PLAN_PATH,
            analysis_commit=COMMIT,
        )
    for name in (spb.CSV_NAME, spb.DOC_NAME, spb.MD_NAME):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    figure_a = (first / spb.FIGURES_DIRNAME / spb.FIGURE_NAME).read_bytes()
    figure_b = (second / spb.FIGURES_DIRNAME / spb.FIGURE_NAME).read_bytes()
    assert figure_a == figure_b
    assert figure_a.startswith(b"\x89PNG\r\n\x1a\n")


def test_the_committed_artefacts_are_reproducible_with_the_recorded_revision(
    tmp_path, monkeypatch
) -> None:
    """The committed slice regenerates byte for byte from the revision it records."""
    monkeypatch.chdir(ROOT)
    recorded = json.loads((REPORT_DIR / spb.DOC_NAME).read_text(encoding="utf-8"))[
        "analysis_commit"
    ]
    assert recorded
    _seed(tmp_path)
    spb.write_pitch_burst(
        DATASET_ROOT, tmp_path, plan_path=PLAN_PATH, analysis_commit=recorded
    )
    for name in (spb.CSV_NAME, spb.DOC_NAME, spb.MD_NAME):
        committed = (REPORT_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert (tmp_path / name).read_bytes() == committed
    committed_figure = (REPORT_DIR / spb.FIGURES_DIRNAME / spb.FIGURE_NAME).read_bytes()
    assert (tmp_path / spb.FIGURES_DIRNAME / spb.FIGURE_NAME).read_bytes() == (
        committed_figure
    )


# ── the command ───────────────────────────────────────────────────────


def test_the_command_exits_zero_on_the_pass_and_one_on_a_broken_one(
    tmp_path, capsys
) -> None:
    _seed(tmp_path / "reports")
    with pytest.raises(SystemExit) as success:
        spb.pitch_burst_main(
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
    assert success.value.code == 0
    printed = capsys.readouterr().out
    assert "checks  : all pass" in printed
    assert "anchor guards burst-18 11.980, burst-4 9.646 mm/s" in printed, (
        "the printed floors are this pass's own WP1 numbers"
    )
    assert str(tmp_path / "reports" / spb.CSV_NAME) in printed
    assert str(tmp_path / "reports" / spb.MD_NAME) in printed
    assert "largest offset" in printed
    assert (tmp_path / "reports" / spb.FIGURES_DIRNAME / spb.FIGURE_NAME).is_file()

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SystemExit) as failed:
        spb.pitch_burst_main(
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
    assert failed.value.code == 1
    assert "udv-sparse-pitch-burst:" in capsys.readouterr().err
    for name in (spb.CSV_NAME, spb.DOC_NAME, spb.MD_NAME, spb.FIGURES_DIRNAME):
        assert not (tmp_path / "broken-reports" / name).exists()


def test_the_command_refuses_a_report_dir_without_this_passs_own_floors(
    tmp_path, capsys
) -> None:
    """The pass's own floors are an input, not a default: absent, the command refuses."""
    report = tmp_path / "reports"
    report.mkdir()
    with pytest.raises(SystemExit) as refused:
        spb.pitch_burst_main(
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
    message = capsys.readouterr().err
    assert "anchor-floor.json" in message
    assert "udv-sparse-pitch-burst:" in message
    for name in (spb.CSV_NAME, spb.DOC_NAME, spb.MD_NAME, spb.FIGURES_DIRNAME):
        assert not (report / name).exists()


def test_a_refusal_writes_no_half_artefact(tmp_path, decoded) -> None:
    without = decoded._replace(
        points=tuple(
            point for point in decoded.points if point is not _point(decoded, "cc4")
        )
    )
    report = tmp_path / "reports"
    with pytest.raises(spb.PitchBurstError):
        spb.measure(without, analysis_commit=COMMIT, plan_path=ROOT / PLAN_PATH)
    assert not (report / spb.CSV_NAME).exists()
    with pytest.raises(spb.PitchBurstError, match="no generator revision"):
        spb.measure(decoded, analysis_commit="   ")
    with pytest.raises(SparseIngestError):
        spb.build_pitch_burst(ROOT / "data" / "not-a-pass", analysis_commit=COMMIT)


# ── the review's interpretation pins ─────────────────────────────────


def _plain(text: str) -> str:
    """The report with markdown emphasis and wrapping removed, for prose pins."""
    for marker in ("**", "*", "`"):
        text = text.replace(marker, "")
    return " ".join(text.split())


def test_the_scalar_interaction_is_screened_against_the_depth_averaged_endpoint(
    model,
) -> None:
    """The review's defect: a scalar was compared with the depth-resolved endpoint.

    A scalar and a per-knot magnitude are different quantities, so the scalar's bullet
    must carry the 4.235 mm/s floor, must say it *exceeds* it, and must not quote the
    depth-resolved endpoint's own value at all.
    """
    doc = _plain((REPORT_DIR / spb.MD_NAME).read_text(encoding="utf-8"))
    magnitude = abs(model.interaction_reduction_mm_s)
    assert model.depth_averaged_floor_mm_s == pytest.approx(4.235, abs=1e-9)
    assert magnitude > model.depth_averaged_floor_mm_s  # the headline correction

    # the scalar bullet: the depth-averaged floor, the exceedance and its factor
    bullet = next(
        sentence
        for sentence in doc.split("- ")
        if sentence.startswith("The scalar reduction")
    )
    assert f"{model.depth_averaged_floor_mm_s:.3f}" in bullet
    assert "exceeds" in bullet
    assert f"{magnitude / model.depth_averaged_floor_mm_s:.2f}" in bullet
    assert f"{model.depth_resolved_floor_mm_s:.3f}" not in bullet, (
        "the scalar bullet must not quote the depth-resolved endpoint"
    )

    # the per-knot bullet keeps the depth-resolved endpoint, where it belongs
    per_knot = next(
        sentence
        for sentence in doc.split("- ")
        if "depth-resolved endpoint" in sentence and "|I(z)|" in sentence
    )
    assert f"{model.depth_resolved_floor_mm_s:.3f}" in per_knot
    assert f"{model.knots_above_depth_resolved_floor} of {model.knot_count}" in per_knot

    # and the conservative guard is still stated, with both anchor spreads
    guard = next(
        sentence for sentence in doc.split("- ") if sentence.startswith("It stays")
    )
    for job, floor in model.anchor_floors_mm_s.items():
        assert f"{floor:.3f}" in guard, job
    assert magnitude < min(model.anchor_floors_mm_s.values())


def test_the_reports_reading_states_both_sides_of_the_scalar_comparison(model) -> None:
    doc = _plain((REPORT_DIR / spb.MD_NAME).read_text(encoding="utf-8"))
    reading = doc[doc.index("So the honest reading of this pass") :]
    assert "exceeds the campaign's own between-run reference floor" in reading
    assert "sits inside the anchors' own movement" in reading
    assert "Neither proves" in reading


# ── the floors are this pass's own, never another sitting's ──────────


def test_the_floors_are_the_passs_own_documents_at_their_published_precision(
    tmp_path,
) -> None:
    """A floor the document carries is the floor this artefact screens against.

    The anchors are the sharp case: the gate recomputes the spread from the recordings,
    so a documented guard the recordings do not reproduce is a *failed check*, not a
    number quietly ignored - which is exactly what a hard-coded floor did to every pass
    that was not the one the constant was measured on.
    """
    report = _seed(tmp_path / "reports")

    def move_the_burst_four_guard(document):
        for job in document["jobs"]:
            if job["job"] == "burst-4":
                job["spread"]["mean"] = 4.3214321

    _tamper(report, spb.ANCHOR_FLOOR_DOC_NAME, move_the_burst_four_guard)
    _tamper(
        report,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["floor"]["depth_averaged"].update(
            {"value_mm_s": 1.2349876, "pair": ["cr1", "cr2"]}
        ),
    )
    model = _build(report)
    assert model.anchor_floors_mm_s == {"burst-4": 4.321, "burst-18": 11.98}
    assert model.depth_averaged_floor_mm_s == 1.235
    assert model.depth_resolved_floor_mm_s == 14.603
    assert "cr1-cr2" in model.depth_averaged_floor_source
    assert "cr3-cr4" in model.depth_resolved_floor_source
    # the recordings' own spread is 9.6459…, so the documented 4.321 is not reproduced
    assert model.checks["anchor_floors_reproduce_wp1"] is False
    assert model.ok is False


def test_the_prose_band_and_the_definitions_carry_this_passs_own_floors(
    tmp_path,
) -> None:
    """Nothing in the words is left at another sitting's numbers either."""
    report = _seed(tmp_path / "reports")

    def move_the_burst_four_guard(document):
        for job in document["jobs"]:
            if job["job"] == "burst-4":
                job["spread"]["mean"] = 4.3214321

    _tamper(report, spb.ANCHOR_FLOOR_DOC_NAME, move_the_burst_four_guard)
    model = _build(report)
    assert spb._band(model) == "~4-12 mm/s"
    document = spb.def_document(model)
    guard = document["definitions"]["anchor_guard"]
    assert "4.321 mm/s at burst 4" in guard
    assert "11.980 mm/s at burst 18" in guard
    endpoint = document["definitions"]["depth_resolved_floor"]
    assert "14.603 mm/s at 21.238 mm" in endpoint
    assert "from the cr3-cr4 pair" in endpoint
    assert (
        document["conservative_reading"]["resolvable_below_mm_s"]
        == sorted(model.anchor_floors_mm_s.values())
        == [4.321, 11.98]
    )
    assert "~4-12 mm/s" in document["conservative_reading"]["statement"]


def test_a_floor_document_from_another_pass_is_refused_by_name(
    tmp_path, decoded
) -> None:
    """One pass's floors are not another's: the plan fingerprint is the pass identity."""
    report = _seed(tmp_path / "reports")
    _tamper(
        report,
        spb.ANCHOR_FLOOR_DOC_NAME,
        lambda document: document.update({"plan_fingerprint": "f" * 64}),
    )
    with pytest.raises(spb.PitchBurstError, match="another pass"):
        spb.load_pass_floors(report, plan_fingerprint=decoded.plan_fingerprint)
    with pytest.raises(spb.PitchBurstError, match="another pass"):
        _build(report)


def test_a_missing_or_unreadable_floor_document_is_refused_by_name(
    tmp_path, decoded
) -> None:
    empty = tmp_path / "reports"
    empty.mkdir()
    with pytest.raises(spb.PitchBurstError, match="anchor-floor.json"):
        spb.load_pass_floors(empty, plan_fingerprint=decoded.plan_fingerprint)
    with pytest.raises(spb.PitchBurstError, match="anchor-floor.json"):
        _build(empty)
    anchors_only = _seed(tmp_path / "anchors-only", spb.ANCHOR_FLOOR_DOC_NAME)
    with pytest.raises(spb.PitchBurstError, match="reference-floor.json"):
        spb.load_pass_floors(anchors_only, plan_fingerprint=decoded.plan_fingerprint)
    unreadable = _seed(tmp_path / "unreadable")
    (unreadable / spb.REFERENCE_FLOOR_DOC_NAME).write_text(
        "{ not json", encoding="utf-8"
    )
    with pytest.raises(spb.PitchBurstError, match="not a readable JSON document"):
        spb.load_pass_floors(unreadable, plan_fingerprint=decoded.plan_fingerprint)


def test_a_floor_document_that_did_not_hold_its_own_gate_is_refused(
    tmp_path, decoded
) -> None:
    """A floor is evidence only from a slice whose own gate passed, and it is traceable."""
    failed_gate = _seed(tmp_path / "failed")
    _tamper(
        failed_gate,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["checks"].update({"four_runs": False}),
    )
    with pytest.raises(spb.PitchBurstError, match="did not pass its own gate"):
        spb.load_pass_floors(failed_gate, plan_fingerprint=decoded.plan_fingerprint)
    undigested = _seed(tmp_path / "undigested")
    _tamper(
        undigested,
        spb.ANCHOR_FLOOR_DOC_NAME,
        lambda document: document.pop("table_sha256"),
    )
    with pytest.raises(spb.PitchBurstError, match="table_sha256"):
        spb.load_pass_floors(undigested, plan_fingerprint=decoded.plan_fingerprint)


def test_the_endpoints_gate_keeps_the_endpoints_distinct_and_inside_the_support(
    tmp_path,
) -> None:
    """The endpoints are compared with the document *and* with the recordings' support."""
    outside = _seed(tmp_path / "outside")
    _tamper(
        outside,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["floor"]["depth_resolved"].update(
            {"depth_mm": 199.0}
        ),
    )
    model = _build(outside)
    assert model.depth_resolved_floor_depth_mm == 199.0
    assert model.checks["the_two_screening_endpoints_are_kept_apart"] is False
    assert model.ok is False
    swapped = _seed(tmp_path / "swapped")
    _tamper(
        swapped,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["floor"]["depth_resolved"].update(
            {"value_mm_s": 1.0}
        ),
    )
    assert _build(swapped).checks["the_two_screening_endpoints_are_kept_apart"] is False


def test_the_reading_reports_this_passs_own_screening_outcome(tmp_path) -> None:
    """Both branches of the scalar comparison, decided by the pass's own floors.

    The reduction here is 7.922 mm/s, so the same recordings must be reported as
    exceeding a 1.234 mm/s endpoint and as *not* exceeding a 20.0 mm/s one: prose that
    asserts the exceedance whatever the numbers is prose that cannot be wrong, which is
    the same defect as a floor that cannot be another sitting's.
    """
    above = _seed(tmp_path / "above")
    _tamper(
        above,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["floor"]["depth_averaged"].update(
            {"value_mm_s": 1.234}
        ),
    )
    below = _seed(tmp_path / "below")
    _tamper(
        below,
        spb.REFERENCE_FLOOR_DOC_NAME,
        lambda document: document["floor"]["depth_averaged"].update(
            {"value_mm_s": 20.0}
        ),
    )
    readings = {}
    for name, report in (("above", above), ("below", below)):
        spb.write_pitch_burst(
            ROOT / DATASET_ROOT,
            report,
            plan_path=ROOT / PLAN_PATH,
            analysis_commit=COMMIT,
        )
        readings[name] = " ".join(
            (report / spb.MD_NAME).read_text(encoding="utf-8").split()
        )
    bullet = next(
        sentence
        for sentence in readings["above"].split("- ")
        if sentence.startswith("The scalar reduction")
    )
    assert "**exceeds**" in bullet
    assert "1.234 mm/s" in bullet
    assert "by a factor of 6.42." in bullet
    other = next(
        sentence
        for sentence in readings["below"].split("- ")
        if sentence.startswith("The scalar reduction")
    )
    assert "**does not exceed**" in other
    assert "20.000 mm/s" in other
    assert "0.40 of this pass's own" in other
    assert "**exceeds**" not in other
    assert (
        "does not exceed the campaign's own between-run reference floor"
        in readings["below"]
    )
    assert "exceeds the campaign's own between-run reference floor" in readings["above"]
