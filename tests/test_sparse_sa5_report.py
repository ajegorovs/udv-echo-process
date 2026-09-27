"""Adversarial tests for SA5's one-sitting report writer.

The contract under test is ``docs/dop3000/sa5-effect-artifact-schema-proposal.md`` (accepted
v1): the four artifacts per sitting (§1), the 72-effect order and the effect id (§2), the
canonical NPZ container (§3–§4), the closed JSON field set, non-value rows and the digest
convention (§5), the 32-column scalar CSV (§6), the README's digest binding (§7), the two closed
code tables (§8) and the publication/refusal gate (§9).

What the tests pin:

- **synthetic sittings** (built here, measured through the real engine on hand-made recordings)
  exercise the serialization without decoding a committed dataset: the frozen 72-effect order,
  the participant row order per contrast shape, the closed CSV column set and its empty-scalar
  rule, the ``.17g`` rendering, the non-value rows and their states, and every mask/state/
  placeholder invariant the NPZ must carry;
- **both committed reproducibility sittings** are built and written to a scratch destination
  twice, and the four files are compared byte for byte — so the canonical byte rule is checked
  against real data, never against a regenerated tree;
- the **refusal gate**: a pass that is not a reproducibility sitting, a frozen or foreign
  destination, an existing SA5 file this run did not produce (partial, differing or non-file),
  an interrupted run's lock or stage file, and a stem rule applied to a foreign name.

No committed artifact is written: every publication in this file lands in ``tmp_path``. The
writer module is imported whole; no independent verifier is imported.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis import sparse_sa5_effects as fx
from udv_echo_process.analysis import sparse_sa5_report as report
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_passes import (
    COMMITTED_PASSES,
    PassRef,
    pass_by_name,
)
from udv_echo_process.analysis.sparse_sa5_bindings import bind_sitting
from udv_echo_process.analysis.sparse_sa5_effects import EffectState
from udv_echo_process.analysis.sparse_sa5_metrics import MetricState
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    MEMBER_SUFFIXES,
    PARTICIPANT_STATE_CODES,
    EffectArrays,
    decode_effect_npz,
    effect_member_names,
)
from udv_echo_process.models.base import ValueModel

SOUND_SPEED_MS = 1480.0
FIRST_GATE_MM = 10.138
SUPPORT_HIGH_MM = 98.938
FINE_PITCH_MM = clamp_resolution(0.617, SOUND_SPEED_MS)
COARSE_PITCH_MM = 2.96
REFERENCE_PITCH_MM = 1.85
FINE_GATES = 145
COARSE_GATES = 31
REFERENCE_GATES = 50
DT_S = 0.02
PROFILES = 620
PERIOD_S = 0.5

PLAN_NAME = "sa5-synthetic"
STEM = "sa5-synthetic-effects"

#: The seven CSV columns that carry text rather than a number; every other column is numeric.
TEXT_COLUMNS = ("sitting", "effect_id", "view", "metric", "contrast", "units", "grid")
NUMERIC_COLUMNS = tuple(
    column for column in report.CSV_COLUMNS if column not in TEXT_COLUMNS
)

#: The per-effect reductions that live **only** in the CSV (§6): the JSON never repeats them.
CSV_ONLY_COLUMNS = (
    "covered_depth_mm",
    "coverage_fraction",
    "max_abs_offset_mm",
    "signed_depth_average",
    "equal_knot_average",
    "rms_magnitude",
    "positive_fraction",
    "negative_fraction",
    "zero_fraction",
    "min_depth_mm",
    "max_abs_depth_mm",
    "correlation",
    "correlation_defined_count",
)

#: The labels the synthetic sitting binds, with job, order, burst, emissions, pitch and gates.
_OPERANDS: tuple[tuple[str, str, int, int, int, float, int], ...] = (
    ("cc1", "burst-4", 2, 4, 20, FINE_PITCH_MM, FINE_GATES),
    ("cc2", "burst-18", 8, 18, 20, FINE_PITCH_MM, FINE_GATES),
    ("cc3", "burst-4", 4, 4, 20, COARSE_PITCH_MM, COARSE_GATES),
    ("cc4", "burst-18", 10, 18, 20, COARSE_PITCH_MM, COARSE_GATES),
    ("cr1", "common-reference-1", 6, 10, 20, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("cr2", "common-reference-2", 12, 10, 20, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("cr3", "common-reference-3", 17, 10, 20, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("cr4", "common-reference-4", 22, 10, 20, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("e8", "emissions-8", 14, 10, 8, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("e64", "emissions-64", 19, 10, 64, REFERENCE_PITCH_MM, REFERENCE_GATES),
    ("e128", "emissions-128", 24, 10, 128, REFERENCE_PITCH_MM, REFERENCE_GATES),
)

#: ``mean(z) = base + slope * (z - first)`` per recording: a sign-changing interaction and a
#: constant E20 side.
_MEAN = {
    "cc1": (10.0, 1.0),
    "cc2": (30.0, 0.5),
    "cc3": (12.0, 2.0),
    "cc4": (33.0, 0.5),
    "cr1": (5.0, 0.0),
    "cr2": (6.0, 0.0),
    "cr3": (7.0, 0.0),
    "cr4": (8.0, 0.0),
    "e8": (10.0, 0.0),
    "e64": (14.0, 0.0),
    "e128": (22.0, 0.0),
}

_ANCHOR_LABELS = ("ctrl-begin", "ctrl-mid", "ctrl-end")
_JOBS = ("burst-4", "burst-18", "emissions-8", "emissions-64", "emissions-128")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PLAN_FINGERPRINT = _digest("synthetic-sa5-plan")


def _depths(pitch_mm: float, gates: int) -> np.ndarray:
    return FIRST_GATE_MM + np.arange(gates, dtype=float) * pitch_mm


def _supported_count(pitch_mm: float, gates: int) -> int:
    grid = _depths(pitch_mm, gates)
    return int(
        np.count_nonzero(
            (grid >= FIRST_GATE_MM - 1e-9) & (grid <= SUPPORT_HIGH_MM + 1e-9)
        )
    )


def _row(label, job, order, burst, emissions, pitch, gates, *, control):
    depths = _depths(pitch, gates)
    identity = f"syn-{label}"
    return {
        "relative_path": f"{identity}.BDD",
        "identity": identity,
        "requested_label": label,
        "job": job,
        "order": order,
        "burst_length": burst,
        "emissions_per_profile": emissions,
        "prf_period_us": 600.0,
        "resolution_mm": repr(float(pitch)),
        "gates": gates,
        "depth_min_mm": repr(float(depths[0])),
        "depth_max_mm": repr(float(depths[-1])),
        "supported_gates": _supported_count(pitch, gates),
        "window_s": 12.0,
        "is_control": "true" if control else "false",
        "source_sha256": _digest(f"src-{label}"),
        "plan": PLAN_NAME,
        "plan_fingerprint": PLAN_FINGERPRINT,
    }


def _mean_at(label: str, depth_mm: float) -> float:
    base, slope = _MEAN[label]
    return base + slope * (depth_mm - FIRST_GATE_MM)


def _point(label, pitch, gates, *, constant_in_time):
    depths = _depths(pitch, gates)
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    means = np.asarray([_mean_at(label, float(d)) for d in depths], dtype=float)
    if constant_in_time:
        values = np.tile(means, (PROFILES, 1))
    else:
        sine = np.sin(2.0 * np.pi * stamps / PERIOD_S)[:, None]
        values = means[None, :] + 4.0 * sine
    return SimpleNamespace(
        values=values,
        time_s=stamps,
        depths=depths,
        config=SimpleNamespace(
            resolution_mm=float(pitch),
            burst_length=next(s[3] for s in _OPERANDS if s[0] == label),
            emissions_per_profile=next(s[4] for s in _OPERANDS if s[0] == label),
            pulse_repetition_freq_hz=1e6 / 600.0,
        ),
        source_sha256=_digest(f"src-{label}"),
        relative_path=f"syn-{label}.BDD",
        binding=SimpleNamespace(
            job=SimpleNamespace(job=next(s[1] for s in _OPERANDS if s[0] == label)),
            point=SimpleNamespace(label=label),
            order=next(s[2] for s in _OPERANDS if s[0] == label),
        ),
    )


def _anchor_point(job, index, label):
    depths = _depths(REFERENCE_PITCH_MM, REFERENCE_GATES)
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    values = np.tile(depths * 0.0 + float(40 + index), (PROFILES, 1))
    return SimpleNamespace(
        values=values,
        time_s=stamps,
        depths=depths,
        config=SimpleNamespace(
            resolution_mm=REFERENCE_PITCH_MM,
            burst_length=10,
            emissions_per_profile=20,
            pulse_repetition_freq_hz=1e6 / 600.0,
        ),
        source_sha256=_digest(f"src-{job}-{label}-{index}"),
        relative_path=f"syn-{job}-{label}.BDD",
        binding=SimpleNamespace(
            job=SimpleNamespace(job=job),
            point=SimpleNamespace(label=label),
            order=index,
        ),
    )


def _synthetic_sitting(*, constant_in_time: bool = False):
    rows = [
        _row(label, job, order, burst, emissions, pitch, gates, control=False)
        for label, job, order, burst, emissions, pitch, gates in _OPERANDS
    ]
    points = [
        _point(label, pitch, gates, constant_in_time=constant_in_time)
        for label, _, _, _, _, pitch, gates in _OPERANDS
    ]
    for job in _JOBS:
        for index, label in enumerate(_ANCHOR_LABELS):
            rows.append(
                _row(
                    label,
                    job,
                    index + 1,
                    10,
                    20,
                    REFERENCE_PITCH_MM,
                    REFERENCE_GATES,
                    control=True,
                )
            )
            points.append(_anchor_point(job, index + 1, label))
    binding = bind_sitting(rows, plan_name=PLAN_NAME)
    return binding, points


def _build_synthetic(*, constant_in_time: bool = False):
    binding, points = _synthetic_sitting(constant_in_time=constant_in_time)
    effects = fx.measure_binding(binding, points, pass_name=PLAN_NAME)
    artifacts = report.build_sa5_artifacts(
        effects,
        binding,
        sitting=PLAN_NAME,
        stem=STEM,
        analysis_commit="test-commit",
        generator_revision="test-generator",
    )
    return artifacts, effects, binding


@pytest.fixture(scope="module")
def synthetic_artifacts():
    return _build_synthetic()


@pytest.fixture(scope="module")
def constant_artifacts():
    return _build_synthetic(constant_in_time=True)


def _members(artifacts):
    with zipfile.ZipFile(io.BytesIO(artifacts.npz)) as archive:
        return archive.namelist()


def _decoded(artifacts):
    shapes = {
        record["effect_id"]: (record["knot_count"], record["participant_count"])
        for record in artifacts.document()["effects"]
    }
    return {
        record.effect_id: record
        for record in decode_effect_npz(artifacts.npz, expected=shapes)
    }


def _csv_rows(artifacts):
    return list(csv.DictReader(io.StringIO(artifacts.csv.decode("utf-8"))))


# ── the frozen 72-effect order and the effect id (§2) ──────────────────


def test_effect_count_and_order_are_the_frozen_72() -> None:
    binding, points = _synthetic_sitting()
    effects = fx.measure_binding(binding, points, pass_name=PLAN_NAME)
    ordered = report.effect_records(effects)
    assert len(ordered) == report.EFFECT_COUNT == 72
    keys = [report.effect_id(item.view, item.metric, item.name) for item in ordered]
    assert len(set(keys)) == 72
    first = ordered[0]
    assert report.effect_id(first.view, first.metric, first.name) == (
        "primary-comparison__mean__pitch_at_burst_4"
    )
    assert ordered[7].name == "pitch_x_burst_interaction"
    assert ordered[8].name == "pitch_at_burst_4"
    assert ordered[-1].name == "pitch_x_burst_interaction"
    assert report.EFFECT_COUNT == report.NPZ_MEMBER_COUNT // len(MEMBER_SUFFIXES) == 72


def test_effect_id_joins_the_three_frozen_vocabularies() -> None:
    assert report.effect_id(
        SparseView.FULL_RECORD, "band_fraction", "E8_minus_E20"
    ) == ("full-record__band_fraction__E8_minus_E20")
    for bad in ("", "a__b"):
        with pytest.raises(report.SparseSa5ReportError):
            report.effect_id("view", bad, "c")
    with pytest.raises(report.SparseSa5ReportError):
        report.effect_id("view", "metric", "")


def test_sitting_stem_follows_the_committed_naming() -> None:
    assert report.sitting_stem("sparse-mixer-live-1") == "sa5-live-1-effects"
    assert report.sitting_stem("sparse-mixer-live-2") == "sa5-live-2-effects"
    for foreign in ("stage2-e20-e64", "sparse-mixer-", ""):
        with pytest.raises(report.SparseSa5ReportError):
            report.sitting_stem(foreign)


# ── the four products, from a synthetic sitting ────────────────────────


def test_the_four_products_are_the_closed_set(synthetic_artifacts) -> None:
    artifacts, effects, _binding = synthetic_artifacts
    assert effects.ok is True
    document = artifacts.document()
    assert document["schema"] == report.SCHEMA_ID
    assert document["ok"] is True
    assert set(document["checks"]) == set(report.ENGINE_CHECK_ORDER)
    assert set(document["artifact_checks"]) == set(report.ARTIFACT_CHECK_NAMES)
    assert all(document["checks"].values())
    assert all(document["artifact_checks"].values())
    assert len(document["effects"]) == 72
    assert len(document["npz_members"]) == report.NPZ_MEMBER_COUNT == 720
    assert len(document["provenance"]) == 11
    assert artifacts.names == (
        f"{STEM}.npz",
        f"{STEM}.csv",
        f"{STEM}.json",
        f"{STEM}.README.md",
    )
    assert artifacts.readme.decode("utf-8").startswith(report.README_TITLE_PREFIX)
    for name, payload in artifacts.files:
        assert isinstance(payload, bytes) and payload


# ── the record types (frozen value models, per AGENTS.md) ──────────────


def test_the_artifacts_record_is_a_frozen_extra_forbidden_value_model(
    synthetic_artifacts,
) -> None:
    """``Sa5Artifacts`` is a frozen ``ValueModel``, and its four products stay ``bytes``."""
    artifacts = synthetic_artifacts[0]
    assert isinstance(artifacts, ValueModel)
    for field in ("npz", "csv", "json", "readme"):
        assert type(getattr(artifacts, field)) is bytes
    assert artifacts.npz[:2] == b"PK", "the container is the ZIP the codec staged"
    with pytest.raises(ValidationError):
        artifacts.stem = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        report.Sa5Artifacts(
            sitting=artifacts.sitting,
            stem=artifacts.stem,
            npz=artifacts.npz,
            csv=artifacts.csv,
            json=artifacts.json,
            readme=artifacts.readme,
            unexpected="nope",
        )
    rebuilt = report.Sa5Artifacts(
        sitting=artifacts.sitting,
        stem=artifacts.stem,
        npz=artifacts.npz,
        csv=artifacts.csv,
        json=artifacts.json,
        readme=artifacts.readme,
    )
    assert rebuilt == artifacts
    assert rebuilt.names == artifacts.names
    assert rebuilt.npz == artifacts.npz and type(rebuilt.npz) is bytes


def test_the_effect_row_record_is_a_frozen_extra_forbidden_value_model(
    synthetic_artifacts,
) -> None:
    """The per-effect record is a frozen ``ValueModel``, not a dataclass."""
    _artifacts, effects, binding = synthetic_artifacts
    rows = report._build_effect_rows(effects, binding)
    assert len(rows) == report.EFFECT_COUNT == 72
    row = rows[0]
    assert isinstance(row, ValueModel)
    # The engine's typed result and the codec's array record are the identical objects.
    assert row.effect is report.effect_records(effects)[0]
    assert isinstance(row.record, EffectArrays)
    assert dict(row.cells)["effect_id"] == row.key
    with pytest.raises(ValidationError):
        row.key = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        report._EffectRows(
            effect=row.effect,
            key=row.key,
            grid=row.grid,
            participant_labels=row.participant_labels,
            record=row.record,
            cells=row.cells,
            nonvalue=row.nonvalue,
            unexpected="nope",
        )


def test_the_json_field_set_is_closed(synthetic_artifacts) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    assert set(artifacts.document()) == {
        "analysis_commit",
        "artifact_checks",
        "artifacts",
        "checks",
        "contrast_source",
        "control_labels",
        "effects",
        "generator_command",
        "generator_revision",
        "method",
        "nonvalue_counts",
        "nonvalue_rows",
        "npz_members",
        "ok",
        "plan",
        "plan_fingerprint",
        "provenance",
        "repeats",
        "schema",
        "sitting",
        "support_mm",
        "window_revolutions",
        "window_s",
    }
    assert artifacts.document()["generator_revision"] == "test-generator"
    assert artifacts.document()["analysis_commit"] == "test-commit"


def test_the_json_never_repeats_a_csv_only_scalar(synthetic_artifacts) -> None:
    """The per-effect scalar reductions have exactly one home: the CSV (§5, §6)."""
    artifacts, _effects, _binding = synthetic_artifacts
    body = json.dumps(artifacts.document(), sort_keys=True)
    for column in CSV_ONLY_COLUMNS:
        assert f'"{column}"' not in body, column


def test_the_npz_members_are_the_ten_closed_suffixes_of_every_effect(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    names = _members(artifacts)
    assert len(names) == report.NPZ_MEMBER_COUNT == 720
    assert names == sorted(names)
    expected = {
        name
        for effect in artifacts.document()["effects"]
        for name in effect_member_names(effect["effect_id"])
    }
    assert set(names) == expected
    assert artifacts.document()["npz_members"] == names


def test_every_npz_array_round_trips_with_the_mirrored_shape(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    decoded = _decoded(artifacts)
    assert len(decoded) == 72
    for effect in artifacts.document()["effects"]:
        record = decoded[effect["effect_id"]]
        assert record.shape.knot_count == effect["knot_count"]
        assert record.shape.participant_count == effect["participant_count"]
        assert record.shape.participant_count == len(effect["participants"])
        assert not record.knots_mm.flags.writeable
        assert np.isfinite(record.effect).all()
        assert np.array_equal(record.defined == 1, record.state == 0)


def test_participant_rows_are_the_declared_contract_order(synthetic_artifacts) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    document = artifacts.document()
    means = {
        effect["contrast"]: [p["label"] for p in effect["participants"]]
        for effect in document["effects"]
        if effect["view"] == "primary-comparison" and effect["metric"] == "mean"
    }
    # A corner two-sided contrast: the high operand then the low operand.
    assert means["pitch_at_burst_4"] == ["cc3", "cc1"]
    assert means["burst_at_coarse_pitch"] == ["cc4", "cc3"]
    # The E20 contrast: the single high recording then the four mean members in order.
    assert means["E8_minus_E20"] == ["e8", "cr1", "cr2", "cr3", "cr4"]
    # The interaction: the four corners in coefficient order.
    assert means["pitch_x_burst_interaction"] == ["cc1", "cc2", "cc3", "cc4"]
    assert all(
        participant["kind"] == "recording"
        for effect in document["effects"]
        for participant in effect["participants"]
    )
    assert [p["order"] for p in document["effects"][0]["participants"]] == [4, 2]
    assert [p["job"] for p in document["effects"][0]["participants"]] == [
        "burst-4",
        "burst-4",
    ]


def test_the_grid_label_follows_the_participating_recordings(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    first = {
        effect["contrast"]: effect["grid"]
        for effect in artifacts.document()["effects"][:8]
    }
    assert first["pitch_at_burst_4"] == "corner_knots"
    assert first["pitch_x_burst_interaction"] == "corner_knots"
    ladder = {
        effect["contrast"]: effect["grid"]
        for effect in artifacts.document()["effects"][32:40]
    }
    assert ladder["E8_minus_E20"] == "emissions_knots"
    assert ladder["E64_minus_E20"] == "emissions_knots"
    assert ladder["pitch_x_burst_interaction"] == "corner_knots"


# ── the CSV (§6) ───────────────────────────────────────────────────────


def test_the_csv_is_the_closed_32_columns_and_72_rows(synthetic_artifacts) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    rows = list(csv.reader(io.StringIO(artifacts.csv.decode("utf-8"))))
    assert tuple(rows[0]) == report.CSV_COLUMNS
    assert len(rows[0]) == 32
    assert len(rows) == 73
    document = artifacts.document()
    assert [row[1] for row in rows[1:]] == [e["effect_id"] for e in document["effects"]]
    assert artifacts.csv.decode("utf-8").endswith("\n")
    assert "\r" not in artifacts.csv.decode("utf-8")


def test_a_csv_float_is_the_17g_rendering_and_an_undefined_scalar_is_empty(
    synthetic_artifacts, constant_artifacts
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    for row in _csv_rows(artifacts):
        for column in NUMERIC_COLUMNS:
            cell = row[column]
            if cell == "":
                continue
            number = float(cell)
            assert cell == format(number, ".17g"), (column, cell)

    rows = _csv_rows(constant_artifacts[0])
    assert any(row[column] == "" for row in rows for column in NUMERIC_COLUMNS), (
        "a constant-in-time sitting refuses some scalars, carried as empty fields"
    )
    assert any(row["correlation"] == "" for row in rows)
    assert all(row["correlation"] != "0" for row in rows if row["correlation"] == "")


def test_the_csv_undefined_split_counts_match_the_npz_state_codes(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    decoded = _decoded(artifacts)
    for row in _csv_rows(artifacts):
        record = decoded[row["effect_id"]]
        states = np.asarray(record.state)
        assert int(row["knot_count"]) == record.knot_count
        assert int(row["defined_count"]) == int(np.count_nonzero(states == 0))
        assert int(row["undefined_count"]) == int(np.count_nonzero(states != 0))
        assert int(row["undefined_operand_count"]) == int(np.count_nonzero(states == 1))
        assert int(row["undefined_alignment_count"]) == int(
            np.count_nonzero(states == 2)
        )
        assert int(row["defined_count"]) + int(row["undefined_count"]) == int(
            row["knot_count"]
        )
        assert row["units"] == next(
            effect["units"]
            for effect in artifacts.document()["effects"]
            if effect["effect_id"] == row["effect_id"]
        )


# ── non-value rows and the code vocabulary (§5.5, §8) ──────────────────


def test_nonvalue_rows_are_the_missing_positions_and_count_consistently(
    constant_artifacts,
) -> None:
    document = constant_artifacts[0].document()
    rows = document["nonvalue_rows"]
    assert rows, "a constant-in-time sitting refuses recurrence and Φ, so rows exist"
    assert {row["kind"] for row in rows} <= set(report.NONVALUE_KINDS)
    allowed_states = set(EFFECT_STATE_CODES.values()) | set(
        PARTICIPANT_STATE_CODES.values()
    )
    allowed_states.add(report.UNDEFINED_SHAPE)
    assert {row["state"] for row in rows} <= allowed_states
    counts = document["nonvalue_counts"]
    total = sum(count for by_kind in counts.values() for count in by_kind.values())
    assert total == len(rows)
    counted = {
        (state, kind): count
        for state, by_kind in counts.items()
        for kind, count in by_kind.items()
    }
    seen: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["state"], row["kind"])
        seen[key] = seen.get(key, 0) + 1
    assert counted == seen
    for by_kind in counts.values():
        assert all(count > 0 for count in by_kind.values())


def test_every_nonvalue_position_corresponds_to_a_false_mask(
    constant_artifacts,
) -> None:
    """An effect-knot row needs a false effect mask; a read row needs a false participant mask."""
    artifacts, _effects, _binding = constant_artifacts
    decoded = _decoded(artifacts)
    labels = {
        effect["effect_id"]: [p["label"] for p in effect["participants"]]
        for effect in artifacts.document()["effects"]
    }
    checked = {"effect-knot": 0, "read": 0, "shape": 0}
    for row in artifacts.document()["nonvalue_rows"]:
        record = decoded[row["effect_id"]]
        index = row["knot_index"]
        if row["kind"] == "effect-knot":
            assert record.defined[index] == 0
            assert EFFECT_STATE_CODES[int(record.state[index])] == row["state"]
            assert row["side"] is None and row["member"] is None
            checked["effect-knot"] += 1
        elif row["kind"] == "operand-knot":
            assert record.defined[index] == 0
            assert row["side"] is not None and row["member"] is None
            assert row["depth_mm"] == pytest.approx(float(record.knots_mm[index]))
        elif row["kind"] == "read":
            slot = labels[row["effect_id"]].index(row["member"])
            assert record.participant_defined[slot, index] == 0
            assert (
                PARTICIPANT_STATE_CODES[int(record.participant_state[slot, index])]
                == (row["state"])
            )
            checked["read"] += 1
        else:
            assert row["kind"] == "shape"
            assert row["knot_index"] is None and row["depth_mm"] is None
            assert row["state"] == report.UNDEFINED_SHAPE
            checked["shape"] += 1
    assert checked["effect-knot"] and checked["read"]


def test_a_defined_measured_knot_is_not_a_nonvalue_row(synthetic_artifacts) -> None:
    """A defined effect knot is a value, never a non-value row."""
    artifacts, _effects, _binding = synthetic_artifacts
    decoded = _decoded(artifacts)
    for row in artifacts.document()["nonvalue_rows"]:
        if row["kind"] != "effect-knot":
            continue
        assert decoded[row["effect_id"]].defined[row["knot_index"]] == 0


def test_the_two_state_tables_are_the_backend_enums() -> None:
    assert report.STATE_MEANINGS["effect"] == tuple(
        (index, state.value) for index, state in enumerate(EffectState)
    )
    assert report.STATE_MEANINGS["participant"] == tuple(
        (index, state.value) for index, state in enumerate(MetricState)
    ) + ((6, "undefined-alignment"),)


def test_state_meanings_are_published_per_effect(synthetic_artifacts) -> None:
    for effect in synthetic_artifacts[0].document()["effects"]:
        meanings = effect["state_meanings"]
        assert [entry["code"] for entry in meanings["effect"]] == [0, 1, 2]
        assert [entry["code"] for entry in meanings["participant"]] == list(range(7))


# ── the digest chain (§5.7, §7) ────────────────────────────────────────


def test_the_digest_chain_binds_readme_to_json_to_npz_and_csv(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
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
    assert json_digest in readme
    assert npz_digest in readme and csv_digest in readme
    # A file never carries its own digest: the JSON does not bind itself.
    assert json_digest not in artifacts.json.decode("utf-8")


def test_the_readme_states_units_rules_views_and_the_no_go_list(
    synthetic_artifacts,
) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
    readme = artifacts.readme.decode("utf-8")
    for suffix in MEMBER_SUFFIXES:
        assert f"__{suffix}.npy" in readme
    for column in report.CSV_COLUMNS:
        assert f"`{column}`" in readme
    assert "trapezoidal" in readme
    assert "nearest NATIVE gate" in readme
    assert "primary comparison" in readme and "full record" in readme
    assert "cross-sitting" in readme
    for item in report.NO_GO_LIST:
        assert item in readme
    assert readme.endswith("\n")
    assert readme.count(report.README_TITLE_PREFIX) == 1
    assert report.regeneration_command(PLAN_NAME) in readme


def test_the_json_is_strict_and_lf_terminated(synthetic_artifacts) -> None:
    artifacts, _effects, _binding = synthetic_artifacts
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


# ── determinism ────────────────────────────────────────────────────────


def test_building_the_same_sitting_twice_is_byte_identical(synthetic_artifacts) -> None:
    first = synthetic_artifacts[0]
    second, _effects, _binding = _build_synthetic()
    assert first.npz == second.npz
    assert first.csv == second.csv
    assert first.json == second.json
    assert first.readme == second.readme


# ── publication and the refusal gate (§9) ──────────────────────────────


def test_writing_twice_into_one_destination_is_idempotent(
    synthetic_artifacts, tmp_path
) -> None:
    artifacts = synthetic_artifacts[0]
    report.write_sa5_artifacts(artifacts, tmp_path / "set")
    first = {name: (tmp_path / "set" / name).read_bytes() for name in artifacts.names}
    assert first == artifacts.payloads()
    report.write_sa5_artifacts(artifacts, tmp_path / "set")
    second = {name: (tmp_path / "set" / name).read_bytes() for name in artifacts.names}
    assert second == first
    leftovers = [
        p.name for p in (tmp_path / "set").iterdir() if p.name not in artifacts.names
    ]
    assert leftovers == [], "no lock or stage file survives a publication"


@pytest.mark.parametrize("existing", ["partial", "differing", "non-file"])
def test_an_existing_sa5_stem_this_run_did_not_produce_is_refused(
    synthetic_artifacts, tmp_path, existing
) -> None:
    artifacts = synthetic_artifacts[0]
    destination = tmp_path / "set"
    destination.mkdir()
    if existing == "partial":
        (destination / artifacts.npz_name).write_bytes(artifacts.npz)
    elif existing == "differing":
        for name, payload in artifacts.files:
            (destination / name).write_bytes(payload)
        (destination / artifacts.csv_name).write_bytes(b"not our table\n")
    else:
        (destination / artifacts.npz_name).mkdir()
    with pytest.raises(report.SparseSa5ReportError):
        report.write_sa5_artifacts(artifacts, destination)
    if existing == "differing":
        assert (destination / artifacts.csv_name).read_bytes() == b"not our table\n"
    if existing == "partial":
        assert (destination / artifacts.npz_name).exists()


def test_a_leftover_lock_or_stage_file_refuses(synthetic_artifacts, tmp_path) -> None:
    artifacts = synthetic_artifacts[0]
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / f".{artifacts.stem}.publish-lock").write_text("held", encoding="utf-8")
    with pytest.raises(report.SparseSa5ReportError, match="lock"):
        report.write_sa5_artifacts(artifacts, locked)

    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / f".{artifacts.npz_name}.abc123.tmp").write_bytes(b"half a container")
    with pytest.raises(report.SparseSa5ReportError, match="temporary"):
        report.write_sa5_artifacts(artifacts, stale)


def test_a_frozen_or_foreign_destination_is_refused(synthetic_artifacts) -> None:
    artifacts = synthetic_artifacts[0]
    for destination in (
        Path("reports/mixer-sensitivity-analysis"),
        Path("reports/sparse-mixer-live-1"),
        Path("reports/sparse-mixer-live-2"),
        Path("reports/stage2-e20-e64"),
        Path("reports"),
        Path("."),
    ):
        with pytest.raises(report.SparseSa5ReportError):
            report.write_sa5_artifacts(artifacts, destination)


def test_a_destination_that_is_a_file_is_refused(synthetic_artifacts, tmp_path) -> None:
    artifacts = synthetic_artifacts[0]
    target = tmp_path / "a-file"
    target.write_bytes(b"")
    with pytest.raises(report.SparseSa5ReportError, match="not a directory"):
        report.write_sa5_artifacts(artifacts, target)


def test_no_committed_artifact_is_touched_by_a_scratch_publication(
    synthetic_artifacts, tmp_path
) -> None:
    """A scratch publication leaves the frozen trees and the publish root byte-unchanged."""
    artifacts = synthetic_artifacts[0]
    frozen = (
        "reports/sparse-signal",
        "reports/sparse-mixer-live-1",
        "reports/sparse-mixer-live-2",
        "reports/mixer-sensitivity-analysis",
    )
    before = {
        tree: {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(tree).iterdir())
            if path.is_file()
        }
        for tree in frozen
    }
    report.write_sa5_artifacts(artifacts, tmp_path / "scratch")
    after = {
        tree: {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(tree).iterdir())
            if path.is_file()
        }
        for tree in frozen
    }
    assert after == before


# ── wrong pass ─────────────────────────────────────────────────────────


def test_a_campaign_or_a_non_reproducibility_pass_is_refused() -> None:
    campaign = pass_by_name("stage2-e20-e64")
    with pytest.raises(report.SparseSa5ReportError, match="not a sitting"):
        report.build_sa5_report(campaign)

    first_pass = pass_by_name("sparse-mixer-first-pass")
    with pytest.raises(
        report.SparseSa5ReportError, match="not a reproducibility sitting"
    ):
        report.build_sa5_report(first_pass)

    live_1 = pass_by_name("sparse-mixer-live-1")
    without_flag = PassRef(
        name=live_1.name,
        root=live_1.root,
        plan_path=live_1.plan_path,
        role=live_1.role,
        note="not flagged as a reproducibility sitting",
        period_law=live_1.period_law,
        in_frozen_design=live_1.in_frozen_design,
        report_dir=live_1.report_dir,
    )
    assert without_flag.is_reproducibility_sitting is False
    with pytest.raises(
        report.SparseSa5ReportError, match="not a reproducibility sitting"
    ):
        report.build_sa5_report(without_flag)


def test_a_pass_without_an_inventory_is_refused() -> None:
    live_1 = pass_by_name("sparse-mixer-live-1")
    no_inventory = PassRef(
        name=live_1.name,
        root=live_1.root,
        plan_path=live_1.plan_path,
        role=live_1.role,
        note="no inventory directory",
        period_law=live_1.period_law,
        in_frozen_design=live_1.in_frozen_design,
        report_dir=None,
        is_reproducibility_sitting=True,
    )
    with pytest.raises(report.SparseSa5ReportError):
        report.build_sa5_report(no_inventory)


def test_a_non_pass_ref_is_refused() -> None:
    with pytest.raises(report.SparseSa5ReportError, match="PassRef"):
        report.build_sa5_report("sparse-mixer-live-1")  # type: ignore[arg-type]


def test_build_refuses_a_mismatched_binding(synthetic_artifacts) -> None:
    _artifacts, effects, _binding = synthetic_artifacts
    other_plan = bind_sitting(
        [
            {
                **_row(*spec, control=False),
                "plan": "another-plan",
                "plan_fingerprint": _digest("x"),
            }
            for spec in _OPERANDS
        ],
        plan_name="another-plan",
    )
    with pytest.raises(report.SparseSa5ReportError, match="must be one sitting"):
        report.build_sa5_artifacts(
            effects,
            other_plan,
            sitting=PLAN_NAME,
            stem=STEM,
            analysis_commit="",
            generator_revision="",
        )


# ── both committed sittings, through the real reader path ──────────────

REAL_SITTINGS = tuple(ref for ref in COMMITTED_PASSES if ref.is_reproducibility_sitting)


@pytest.fixture(scope="module")
def real_measure():
    """One measured result and binding per committed reproducibility sitting, read once."""
    measured = {}
    for ref in REAL_SITTINGS:
        effects = fx.measure_sitting(ref)
        rows = tuple(
            csv.DictReader(
                (Path(ref.report_dir) / "points.csv")
                .read_text(encoding="utf-8")
                .splitlines()
            )
        )
        binding = bind_sitting(rows, plan_name=ref.name, support_mm=effects.support_mm)
        measured[ref.name] = (effects, binding)
    return measured


@pytest.fixture(scope="module")
def real_artifacts(real_measure):
    return {
        name: report.build_sa5_artifacts(
            effects, binding, sitting=name, stem=report.sitting_stem(name)
        )
        for name, (effects, binding) in real_measure.items()
    }


def test_both_committed_sittings_build_the_frozen_shape(real_artifacts) -> None:
    assert set(real_artifacts) == {"sparse-mixer-live-1", "sparse-mixer-live-2"}
    for name, artifacts in real_artifacts.items():
        document = artifacts.document()
        assert document["sitting"] == name
        assert document["ok"] is True
        assert len(document["effects"]) == 72
        assert len(document["npz_members"]) == 720
        assert document["plan"] == name
        rows = list(csv.reader(io.StringIO(artifacts.csv.decode("utf-8"))))
        assert tuple(rows[0]) == report.CSV_COLUMNS
        assert len(rows) == 73
        assert [row[0] for row in rows[1:]] == [name] * 72
        assert len(_decoded(artifacts)) == 72
        assert artifacts.npz_name == f"{report.sitting_stem(name)}.npz"


def test_a_real_sitting_is_byte_reproducible_into_scratch(
    real_artifacts, tmp_path
) -> None:
    artifacts = real_artifacts["sparse-mixer-live-1"]
    first = tmp_path / "one"
    second = tmp_path / "two"
    report.write_sa5_artifacts(artifacts, first)
    report.write_sa5_artifacts(artifacts, second)
    for name in artifacts.names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert {
        name: (first / name).read_bytes() for name in artifacts.names
    } == artifacts.payloads()
    assert sorted(p.name for p in first.iterdir()) == sorted(artifacts.names)


def test_build_sa5_report_on_a_real_pass_is_byte_identical(real_artifacts) -> None:
    ref = pass_by_name("sparse-mixer-live-1")
    again = report.build_sa5_report(ref)
    first = real_artifacts["sparse-mixer-live-1"]
    assert again.npz == first.npz
    assert again.csv == first.csv
    assert again.json == first.json
    assert again.readme == first.readme


def test_the_real_npz_round_trips_and_matches_the_published_mirror(
    real_artifacts,
) -> None:
    for artifacts in real_artifacts.values():
        document = artifacts.document()
        shapes = {
            effect["effect_id"]: (effect["knot_count"], effect["participant_count"])
            for effect in document["effects"]
        }
        decoded = {
            record.effect_id: record for record in decode_effect_npz(artifacts.npz)
        }
        assert set(decoded) == set(shapes)
        for key, record in decoded.items():
            assert (record.knot_count, record.participant_count) == shapes[key]
            assert np.all(np.diff(record.knots_mm) > 0.0)
            # The mask is one exactly at the defined code, and a placeholder is never a number.
            assert np.array_equal(record.defined == 1, record.state == 0)
            assert np.array_equal(
                record.participant_defined == 1, record.participant_state == 0
            )
            assert np.all(record.effect[record.state != 0] == 0.0)
            unaligned = record.participant_state == 6
            assert np.all(record.participant_gate_index[unaligned] == -1)
            assert np.all(record.participant_value[unaligned] == 0.0)


def test_a_real_sitting_publishes_the_engines_own_reductions(
    real_measure, real_artifacts
) -> None:
    """Every CSV reduction equals the engine's own typed value for the same effect."""
    for name, (effects, _binding) in real_measure.items():
        rows = {row["effect_id"]: row for row in _csv_rows(real_artifacts[name])}
        assert len(rows) == 72
        for effect in report.effect_records(effects):
            key = report.effect_id(effect.view, effect.metric, effect.name)
            row = rows[key]
            summary = effect.summary
            assert row["defined_count"] == str(summary.defined_count)
            assert row["knot_count"] == str(summary.knot_count)
            assert row["units"] == effect.units
            assert row["view"] == effect.view.value
            assert row["metric"] == effect.metric.value
            for column, value in (
                ("max_abs_offset_mm", effect.max_abs_offset_mm),
                ("covered_depth_mm", summary.covered_depth_mm),
                ("equal_knot_average", summary.equal_knot_average),
                ("rms_magnitude", summary.rms_magnitude),
                ("signed_depth_average", summary.signed_depth_average),
                ("correlation", effect.shape.correlation),
                ("support_low_mm", effect.support_mm[0]),
                ("half_pitch_mm", effect.half_pitch_mm),
            ):
                expected = "" if value is None else format(float(value), ".17g")
                assert row[column] == expected, (key, column)


def test_a_real_provenance_row_names_its_committed_source(real_artifacts) -> None:
    for name, artifacts in real_artifacts.items():
        provenance = artifacts.document()["provenance"]
        assert [row["label"] for row in provenance] == [
            "cc1",
            "cc2",
            "cc3",
            "cc4",
            "cr1",
            "cr2",
            "cr3",
            "cr4",
            "e8",
            "e64",
            "e128",
        ]
        for row in provenance:
            assert row["plan"] == name
            assert len(row["source_sha256"]) == 64
            assert row["relative_path"].startswith(row["identity"])


def test_the_writer_imports_no_verifier() -> None:
    source = Path(report.__file__).read_text(encoding="utf-8")
    for forbidden in ("verifier", "verify_sa5"):
        assert forbidden not in source, forbidden
    assert not [name for name in dir(report) if name.startswith("verify")]


# ── the runnable command (regeneration_command / report_main) ──────────


def test_the_regeneration_command_is_the_runnable_cli_form() -> None:
    """The published command is the module-invoked verb, never an inline ``python -c``."""
    assert report.regeneration_command("sparse-mixer-live-1") == (
        "python -m udv_echo_process.cli sparse-sa5-report --sitting sparse-mixer-live-1"
    )
    assert report.regeneration_command("sparse-mixer-live-2").endswith(
        "--sitting sparse-mixer-live-2"
    )
    assert "python -c" not in report.regeneration_command("sparse-mixer-live-1")


def test_the_document_publishes_the_runnable_generator_command(
    synthetic_artifacts,
) -> None:
    document = synthetic_artifacts[0].document()
    assert document["generator_command"] == report.regeneration_command(PLAN_NAME)


def test_report_main_refuses_a_campaign_and_an_unknown_sitting(
    tmp_path, capsys
) -> None:
    """A campaign, the first pass and an unknown name are each refused, writing nothing."""
    destination = tmp_path / "scratch"
    for name in ("stage2-e20-e64", "sparse-mixer-first-pass", "no-such-pass"):
        with pytest.raises(SystemExit) as raised:
            report.report_main(["--sitting", name, "--report-dir", str(destination)])
        assert raised.value.code == 1
        assert not destination.exists(), "a refusal never stages a byte"
        assert "udv-sparse-sa5-report:" in capsys.readouterr().err


def test_report_main_publishes_a_committed_sitting_into_scratch(
    real_artifacts, tmp_path, monkeypatch, capsys
) -> None:
    """``report_main`` resolves the sitting name, publishes its four files and exits 0."""
    expected = real_artifacts["sparse-mixer-live-1"]
    seen: list[PassRef] = []

    def _build(pass_ref, **_kwargs):
        seen.append(pass_ref)
        return expected

    monkeypatch.setattr(report, "build_sa5_report", _build)
    destination = tmp_path / "cli"
    with pytest.raises(SystemExit) as raised:
        report.report_main(
            ["--sitting", "sparse-mixer-live-1", "--report-dir", str(destination)]
        )
    assert raised.value.code == 0
    assert seen == [pass_by_name("sparse-mixer-live-1")]
    assert sorted(path.name for path in destination.iterdir()) == sorted(expected.names)
    for name, payload in expected.files:
        assert (destination / name).read_bytes() == payload
    assert "all pass" in capsys.readouterr().out


def test_report_main_defaults_to_the_plans_publish_root(monkeypatch) -> None:
    """Without ``--report-dir`` the destination is the plan's designated root."""
    seen: list[Path] = []

    def _write(_pass_ref, destination, **_kwargs):
        seen.append(Path(destination))
        raise report.SparseSa5ReportError("stop before any byte is written")

    monkeypatch.setattr(report, "write_sa5_report", _write)
    with pytest.raises(SystemExit) as raised:
        report.report_main(["--sitting", "sparse-mixer-live-1"])
    assert raised.value.code == 1
    assert seen == [report.REPORT_DIR]
