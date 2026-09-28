"""Adversarial and synthetic tests for SA5's independent artifact verifier (§11).

The contract under test is `docs/dop3000/sa5-effect-artifact-schema-proposal.md` (accepted
v1): a *separate* program that does not read the writer's staged values as its input, decodes
the committed sources, recomputes the effects and summaries, compares them element-wise, and
checks the digests **last**. What the tests pin:

- a synthetically built, schema-correct quartet verifies, and the verification reports the
  counts and digests it read;
- the verifier refuses anything but exactly one mixer-enabled reproducibility sitting — the
  Stage-2 campaign is never reachable, one invocation never serves two sittings;
- an artifact is compared **against a recomputation**, not against itself: a container that
  is byte-canonical and §3-legal but carries a wrong number, the wrong mask or the wrong
  state is refused element-wise; a byte-drifted container is refused by the shared codec;
  a rounded CSV scalar, an empty field where a value belongs, a reordered or missing row, a
  wrong provenance digest, a shrunken member list, a missing or mis-stated non-value row, a
  wrong ``nonvalue_counts`` total, a flipped check, an extra field and a wrong digest are
  each refusals naming what disagreed;
- a bound operand whose decoded file does not reconcile with its inventory row (digest,
  settings) is refused by the verifier's own reconciliation, because an inventory row is not
  evidence until it is reconciled with the file it names;
- the digest check comes **last**: a wrong number with a matching digest is still wrong, and
  the README must carry the JSON's canonical-LF digest as the chain's entry point;
- the module never imports the report writer (a concurrent module is not a dependency).

The synthetic sitting is the same shape as the engine's own tests (an eleven-operand, nine-
endpoint sitting whose profiles are linear in depth), built here so the artifact quartet is
written **independently** of the verifier: the fixture serializes from the recomputed engine
result with its own NPZ/CSV/JSON builders, so a shared mistake between writer and verifier
cannot hide behind a shared helper.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis import sparse_sa5_verify as verify
from udv_echo_process.analysis._floor_documents import table_digest
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_passes import PassRef, PassRole, pass_by_name
from udv_echo_process.analysis.sparse_sa5_bindings import bind_sitting
from udv_echo_process.analysis.sparse_sa5_effects import (
    ENDPOINTS,
    INTERACTION_NAME,
    EffectState,
    measure_binding,
)
from udv_echo_process.analysis.sparse_sa5_metrics import MetricState
from udv_echo_process.analysis.sparse_sa5_npz import (
    EFFECT_STATE_CODES,
    MEMBER_DTYPES,
    MEMBER_SUFFIXES,
    PARTICIPANT_STATE_CODES,
    UNALIGNED_READ_CODE,
    EffectArrays,
    encode_effect_npz,
    member_name,
)

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
PLAN_NAME = "sparse-mixer-live-1"
STEM = "sa5-live-1-effects"

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

#: Each operand's own depth profile: ``mean(z) = base + slope * (z - first)``.
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

#: The verification entry point's pass ref: a mixer-enabled reproducibility sitting.
PASS_REF = PassRef(
    name=PLAN_NAME,
    root=Path("data") / PLAN_NAME,
    plan_path=Path("examples") / PLAN_NAME / "run-plan.json",
    role=PassRole.SITTING,
    note="synthetic reproducibility sitting for the verifier's tests",
    period_law="",
    in_frozen_design=True,
    is_reproducibility_sitting=True,
    report_dir=Path("reports") / PLAN_NAME,
)


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


def _row(
    label: str,
    job: str,
    order: int,
    burst: int,
    emissions: int,
    pitch: float,
    gates: int,
    *,
    control: bool,
) -> dict[str, object]:
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


def _point(
    label: str, pitch: float, gates: int, *, constant_in_time: bool
) -> SimpleNamespace:
    depths = _depths(pitch, gates)
    means = np.asarray([_mean_at(label, float(depth)) for depth in depths], dtype=float)
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    if constant_in_time:
        values = np.tile(means, (PROFILES, 1))
    else:
        sine = np.sin(2.0 * np.pi * stamps / PERIOD_S)[:, None]
        values = means[None, :] + 4.0 * sine
    burst = next(spec[3] for spec in _OPERANDS if spec[0] == label)
    emissions = next(spec[4] for spec in _OPERANDS if spec[0] == label)
    job = next(spec[1] for spec in _OPERANDS if spec[0] == label)
    order = next(spec[2] for spec in _OPERANDS if spec[0] == label)
    return SimpleNamespace(
        values=values,
        time_s=stamps,
        depths=depths,
        config=SimpleNamespace(
            resolution_mm=float(pitch),
            burst_length=burst,
            emissions_per_profile=emissions,
            pulse_repetition_freq_hz=1e6 / 600.0,
        ),
        source_sha256=_digest(f"src-{label}"),
        relative_path=f"syn-{label}.BDD",
        binding=SimpleNamespace(
            job=SimpleNamespace(job=job),
            point=SimpleNamespace(label=label),
            order=order,
        ),
    )


def _anchor_point(job: str, index: int, label: str) -> SimpleNamespace:
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


def _synthetic_sources(*, constant_in_time: bool = True) -> verify.Sa5Sources:
    """A complete synthetic sitting: its committed rows, its decoded recordings, its effects."""
    rows: list[dict[str, object]] = [
        _row(label, job, order, burst, emissions, pitch, gates, control=False)
        for label, job, order, burst, emissions, pitch, gates in _OPERANDS
    ]
    points: list[object] = [
        _point(label, pitch, gates, constant_in_time=constant_in_time)
        for label, job, order, burst, emissions, pitch, gates in _OPERANDS
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
    effects = measure_binding(binding, points, pass_name=PLAN_NAME)
    decoding = SimpleNamespace(
        points=tuple(points),
        support_mm=binding.support_mm,
        plan_fingerprint=PLAN_FINGERPRINT,
    )
    return verify.Sa5Sources(decoding=decoding, binding=binding, effects=effects)


# ── the fixture's own artifact builders (no writer import) ─────────────


_EFFECT_CODE = {
    EffectState.DEFINED: 0,
    EffectState.UNDEFINED_OPERAND: 1,
    EffectState.UNDEFINED_ALIGNMENT: 2,
}
_PARTICIPANT_CODE = {
    MetricState.DEFINED: 0,
    MetricState.DEFINED_ZERO_POWER: 1,
    MetricState.REFUSED_AXIS: 2,
    MetricState.UNDEFINED_CONSTANT_TRACE: 3,
    MetricState.UNDEFINED_NOT_SUPPORTED: 4,
    MetricState.UNDEFINED_NO_ESTIMATE: 5,
}


def _labels_for(binding, effect) -> tuple[str, ...]:
    if effect.name == INTERACTION_NAME:
        parts = [(row.label,) for row in binding.corners]
    else:
        spec = next(item for item in binding.contrasts if item.name == effect.name)
        parts = [spec.high.members, spec.low.members]
    labels: list[str] = []
    for members in parts:
        for label in members:
            if label not in labels:
                labels.append(label)
    return tuple(labels)


def _grid_for(binding, effect) -> str:
    corner_labels = {row.label for row in binding.corners}
    if effect.name == INTERACTION_NAME:
        return verify.CORNER_GRID
    spec = next(item for item in binding.contrasts if item.name == effect.name)
    labels = set(spec.high.members) | set(spec.low.members)
    return verify.CORNER_GRID if labels <= corner_labels else verify.EMISSIONS_GRID


def _arrays_by_id(sources) -> dict[str, dict[str, np.ndarray]]:
    """One writable array per member suffix per effect, in the schema's own dtypes."""
    binding = sources.binding
    by_id: dict[str, dict[str, np.ndarray]] = {}
    for metric, view in ENDPOINTS:
        endpoint = sources.effects.endpoint(metric, view)
        for effect in (*endpoint.contrasts, endpoint.interaction):
            effect_id = verify.effect_id_of(view, metric, effect.name)
            labels = _labels_for(binding, effect)
            knot_count = len(effect.knots_mm)
            participant_count = len(labels)
            slots: dict[str, np.ndarray] = {
                "knots_mm": np.asarray(effect.knots_mm, dtype=np.float64),
                "effect": np.asarray(
                    [
                        0.0 if row.value is None else float(row.value)
                        for row in effect.effects
                    ],
                    dtype=np.float64,
                ),
                "defined": np.asarray(
                    [1 if row.defined else 0 for row in effect.effects], dtype=np.uint8
                ),
                "state": np.asarray(
                    [_EFFECT_CODE[row.state] for row in effect.effects], dtype=np.uint8
                ),
                "participant_gate_index": np.full(
                    (participant_count, knot_count), -1, dtype=np.int32
                ),
                "participant_depth_mm": np.zeros(
                    (participant_count, knot_count), dtype=np.float64
                ),
                "participant_offset_mm": np.zeros(
                    (participant_count, knot_count), dtype=np.float64
                ),
                "participant_value": np.zeros(
                    (participant_count, knot_count), dtype=np.float64
                ),
                "participant_defined": np.zeros(
                    (participant_count, knot_count), dtype=np.uint8
                ),
                "participant_state": np.zeros(
                    (participant_count, knot_count), dtype=np.uint8
                ),
            }
            for index, row in enumerate(effect.effects):
                reads = {
                    member.label: member
                    for side in row.operands
                    for member in side.members
                }
                for position, label in enumerate(labels):
                    read = reads[label]
                    if not read.aligned:
                        slots["participant_state"][position, index] = (
                            UNALIGNED_READ_CODE
                        )
                    else:
                        slots["participant_state"][position, index] = _PARTICIPANT_CODE[
                            read.state
                        ]
                        slots["participant_gate_index"][position, index] = (
                            read.gate_index
                        )
                        slots["participant_depth_mm"][position, index] = read.depth_mm
                        slots["participant_offset_mm"][position, index] = read.offset_mm
                    if read.defined:
                        slots["participant_defined"][position, index] = 1
                        slots["participant_value"][position, index] = read.value
            by_id[effect_id] = slots
    return by_id


def _container(by_id: dict[str, dict[str, np.ndarray]]) -> bytes:
    records = [
        EffectArrays(
            effect_id=effect_id,
            knot_count=int(slots["knots_mm"].shape[0]),
            participant_count=int(slots["participant_gate_index"].shape[0]),
            **{
                suffix: np.ascontiguousarray(slots[suffix], dtype=MEMBER_DTYPES[suffix])
                for suffix in MEMBER_SUFFIXES
            },
        )
        for effect_id, slots in by_id.items()
    ]
    return encode_effect_npz(records)


def _records(binding, effects):
    """The schema order of the sitting's effects, as ``(metric, view, effect)`` triples."""
    for metric, view in ENDPOINTS:
        endpoint = effects.endpoint(metric, view)
        for effect in (*endpoint.contrasts, endpoint.interaction):
            yield metric, view, effect


def _expected_effect_ids(sources) -> list[str]:
    return [
        verify.effect_id_of(view, metric, effect.name)
        for metric, view, effect in _records(sources.binding, sources.effects)
    ]


def _render(cell: object) -> str:
    """The §6 rendering of one CSV cell: the empty field, a round-trip float, or text."""
    if cell is None:
        return ""
    if isinstance(cell, bool):
        return str(cell)
    if isinstance(cell, (int, np.integer)):
        return str(int(cell))
    if isinstance(cell, (float, np.floating)):
        return format(float(cell), ".17g")
    return str(cell)


def _csv_cells(sources) -> list[dict[str, object]]:
    binding = sources.binding
    rows: list[dict[str, object]] = []
    for metric, view, effect in _records(binding, sources.effects):
        effect_id = verify.effect_id_of(view, metric, effect.name)
        summary = effect.summary
        shape = effect.shape
        rows.append(
            {
                "sitting": binding.plan,
                "effect_id": effect_id,
                "view": view.value,
                "metric": metric.value,
                "contrast": effect.name,
                "units": effect.units,
                "grid": _grid_for(binding, effect),
                "knot_count": summary.knot_count,
                "defined_count": summary.defined_count,
                "undefined_count": summary.undefined_count,
                "undefined_alignment_count": sum(
                    1
                    for row in effect.effects
                    if row.state is EffectState.UNDEFINED_ALIGNMENT
                ),
                "undefined_operand_count": sum(
                    1
                    for row in effect.effects
                    if row.state is EffectState.UNDEFINED_OPERAND
                ),
                "covered_depth_mm": summary.covered_depth_mm,
                "coverage_fraction": summary.coverage_fraction,
                "support_low_mm": effect.support_mm[0],
                "support_high_mm": effect.support_mm[1],
                "half_pitch_mm": effect.half_pitch_mm,
                "max_abs_offset_mm": effect.max_abs_offset_mm,
                "signed_depth_average": summary.signed_depth_average,
                "equal_knot_average": summary.equal_knot_average,
                "rms_magnitude": summary.rms_magnitude,
                "positive_fraction": summary.positive_fraction,
                "negative_fraction": summary.negative_fraction,
                "zero_fraction": summary.zero_fraction,
                "min_value": summary.min_value,
                "min_depth_mm": summary.min_depth_mm,
                "max_value": summary.max_value,
                "max_depth_mm": summary.max_depth_mm,
                "max_abs_value": summary.max_abs_value,
                "max_abs_depth_mm": summary.max_abs_depth_mm,
                "correlation": shape.correlation,
                "correlation_defined_count": shape.defined_count,
            }
        )
    return rows


def _csv_text(sources) -> str:
    lines = [",".join(verify.CSV_COLUMNS)]
    for cells in _csv_cells(sources):
        lines.append(",".join(_render(cells[column]) for column in verify.CSV_COLUMNS))
    return "\n".join(lines) + "\n"


def _provenance(binding) -> list[dict[str, object]]:
    return [
        {key: getattr(row, key) for key in verify.PROVENANCE_KEYS}
        for row in binding.operands
    ]


def _state_meanings() -> dict[str, dict[str, str]]:
    return {
        "effect": {str(code): text for code, text in EFFECT_STATE_CODES.items()},
        "participant": {
            str(code): text for code, text in PARTICIPANT_STATE_CODES.items()
        },
    }


def _as_writer_state_meanings(
    meanings: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, int | str]]]:
    """The same two spaces in the writer's own rendering: a list of ``{code, text}`` rows.

    The committed artifact renders ``state_meanings`` as lists (``sparse_sa5_report`` builds
    them from ``sorted(...)``), so the schema's list form is what a real artifact carries and
    the adversarial cases are built from it.
    """
    return {
        space: [{"code": int(code), "text": text} for code, text in codes.items()]
        for space, codes in meanings.items()
    }


def _effect_records(sources) -> list[dict[str, object]]:
    binding = sources.binding
    records: list[dict[str, object]] = []
    for metric, view, effect in _records(binding, sources.effects):
        effect_id = verify.effect_id_of(view, metric, effect.name)
        labels = _labels_for(binding, effect)
        records.append(
            {
                "effect_id": effect_id,
                "view": view.value,
                "metric": metric.value,
                "contrast": effect.name,
                "expression": effect.expression,
                "reduction": effect.reduction,
                "units": effect.units,
                "grid": _grid_for(binding, effect),
                "knot_count": len(effect.knots_mm),
                "participant_count": len(labels),
                "operand_names": list(effect.operand_names),
                "operands": [
                    {
                        "name": side.name,
                        "kind": side.kind,
                        "members": [member.label for member in side.members],
                    }
                    for side in effect.effects[0].operands
                ],
                "coefficients": list(effect.coefficients),
                "participants": [
                    {
                        "label": label,
                        "job": binding.by_label(label).job,
                        "order": binding.by_label(label).order,
                        "kind": "recording",
                    }
                    for label in labels
                ],
                "support_mm": list(effect.support_mm),
                "half_pitch_mm": effect.half_pitch_mm,
                "alignment_rule": effect.alignment_rule,
                "state_meanings": _state_meanings(),
            }
        )
    return records


def _nonvalue_rows(sources) -> list[dict[str, object]]:
    """The fixture's own missing-value rows: one per position whose scalar is absent."""
    rows: list[dict[str, object]] = []
    binding = sources.binding
    for metric, view, effect in _records(binding, sources.effects):
        effect_id = verify.effect_id_of(view, metric, effect.name)
        for index, row in enumerate(effect.effects):
            depth = float(effect.knots_mm[index])
            if not row.defined:
                rows.append(
                    {
                        "effect_id": effect_id,
                        "kind": "effect-knot",
                        "knot_index": index,
                        "depth_mm": depth,
                        "side": None,
                        "member": None,
                        "state": row.state.value,
                        "reason": row.reason,
                    }
                )
            owned = {
                member.label: side.name
                for side in row.operands
                for member in side.members
            }
            for side in row.operands:
                if side.defined:
                    continue
                rows.append(
                    {
                        "effect_id": effect_id,
                        "kind": "operand-knot",
                        "knot_index": index,
                        "depth_mm": depth,
                        "side": side.name,
                        "member": None,
                        "state": side.state.value,
                        "reason": side.reason,
                    }
                )
                for member in side.members:
                    if member.defined:
                        continue
                    rows.append(
                        {
                            "effect_id": effect_id,
                            "kind": "read",
                            "knot_index": index,
                            "depth_mm": depth,
                            "side": owned[member.label],
                            "member": member.label,
                            "state": (
                                member.state.value
                                if member.aligned
                                else "undefined-alignment"
                            ),
                            "reason": member.reason,
                        }
                    )
        if effect.shape.correlation is None:
            rows.append(
                {
                    "effect_id": effect_id,
                    "kind": "shape",
                    "knot_index": None,
                    "depth_mm": None,
                    "side": None,
                    "member": None,
                    "state": "undefined-shape",
                    "reason": effect.shape.reason,
                }
            )
    return rows


def _nonvalue_counts(rows: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        by_kind = counts.setdefault(str(row["state"]), {})
        kind = str(row["kind"])
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return counts


def _repeat_records(sources) -> list[dict[str, object]]:
    return [
        {
            "condition": group.condition,
            "metric": group.metric.value,
            "view": group.view.value,
            "units": group.units,
            "knot_count": group.knot_count,
            "defined_members": group.defined_members,
            "min_value": group.min_value,
            "max_value": group.max_value,
            "spread": group.spread,
            "rule": group.rule,
            "statement": group.statement,
            "members": [
                {
                    "label": member.label,
                    "order": member.order,
                    "job": member.job,
                    "value": member.value,
                    "defined_count": member.defined_count,
                    "state": None if member.state is None else member.state.value,
                    "reason": member.reason,
                }
                for member in group.members
            ],
        }
        for group in sources.effects.repeats
    ]


def _document(
    sources, *, npz_digest: str, csv_digest: str, stem: str = STEM
) -> dict[str, object]:
    binding = sources.binding
    nonvalue = _nonvalue_rows(sources)
    return {
        "schema": verify.SCHEMA,
        "ok": True,
        "checks": dict(sources.effects.checks),
        "artifact_checks": {name: True for name in verify.ARTIFACT_CHECKS},
        "analysis_commit": "0" * 40,
        "generator_revision": "synthetic-fixture",
        "generator_command": (
            "python -m udv_echo_process.analysis.sparse_sa5_report "
            f"--sitting {PLAN_NAME}"
        ),
        "sitting": binding.plan,
        "plan": binding.plan,
        "plan_fingerprint": binding.plan_fingerprint,
        "window_s": binding.window_s,
        "window_revolutions": binding.window_revolutions,
        "support_mm": list(binding.support_mm),
        "method": sources.effects.method,
        "contrast_source": sources.effects.contrast_source,
        "provenance": _provenance(binding),
        "control_labels": list(binding.control_labels),
        "artifacts": {
            "npz": {"file": f"{stem}.npz", "sha256": npz_digest},
            "csv": {"file": f"{stem}.csv", "sha256": csv_digest},
        },
        "effects": _effect_records(sources),
        "npz_members": sorted(
            member_name(effect_id, suffix)
            for effect_id in _expected_effect_ids(sources)
            for suffix in MEMBER_SUFFIXES
        ),
        "nonvalue_rows": nonvalue,
        "nonvalue_counts": _nonvalue_counts(nonvalue),
        "repeats": _repeat_records(sources),
    }


def _dump(document: object) -> str:
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def _readme_text(paths: dict[str, Path]) -> str:
    """The fixture's own README: it names the three bound files and states each digest (§7).

    §7 binds the README's claims to every published file by digest — the JSON's, the NPZ's and
    the CSV's — so the fixture emits all three, as the committed artifact does, and never a bare
    64-hex source digest that a reader could mistake for a file digest.
    """
    stem = paths["json"].name[: -len(".json")]
    npz = (
        f"{verify.DIGEST_PREFIX}{hashlib.sha256(paths['npz'].read_bytes()).hexdigest()}"
    )
    return (
        f"# {stem}\n\n"
        f"The bound files are {stem}.npz, {stem}.csv and {stem}.json.\n\n"
        f"- {stem}.npz {npz}\n"
        f"- {stem}.csv {table_digest(paths['csv'])}\n"
        f"- {stem}.json {table_digest(paths['json'])}\n"
    )


def write_artifacts(directory: Path, sources, *, stem: str = STEM) -> dict[str, Path]:
    """Write the fixture's own schema-correct quartet and return the four paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = verify.artifact_paths(directory, stem)
    raw_npz = _container(_arrays_by_id(sources))
    paths["npz"].write_bytes(raw_npz)
    paths["csv"].write_text(_csv_text(sources), encoding="utf-8", newline="")
    document = _document(
        sources,
        npz_digest=f"{verify.DIGEST_PREFIX}{hashlib.sha256(raw_npz).hexdigest()}",
        csv_digest=table_digest(paths["csv"]),
        stem=stem,
    )
    paths["json"].write_text(_dump(document), encoding="utf-8", newline="")
    paths["readme"].write_text(_readme_text(paths), encoding="utf-8")
    return paths


def load_document(paths: dict[str, Path]) -> dict[str, object]:
    return json.loads(paths["json"].read_text(encoding="utf-8"))


def rewrap(paths: dict[str, Path], document: object) -> None:
    """Write a mutated document back in the §5 canonical form, README re-bound."""
    paths["json"].write_text(_dump(document), encoding="utf-8", newline="")
    paths["readme"].write_text(_readme_text(paths), encoding="utf-8")


@pytest.fixture(scope="module")
def sources() -> verify.Sa5Sources:
    return _synthetic_sources()


def run_verification(monkeypatch, sources, directory: Path, *, stem: str = STEM):
    monkeypatch.setattr(verify, "recompute_sa5_sources", lambda *a, **k: sources)
    return verify.verify_sa5_artifacts(
        PASS_REF, artifact_dir=Path(directory), stem=stem
    )


# ── the happy path ─────────────────────────────────────────────────────


def test_a_schema_correct_artifact_quartet_verifies(tmp_path, monkeypatch, sources):
    write_artifacts(tmp_path, sources)
    result = run_verification(monkeypatch, sources, tmp_path)
    assert result.ok
    assert result.sitting == PLAN_NAME
    assert result.stem == STEM
    assert result.effect_count == 72
    assert result.csv_rows == 72
    assert result.digests["npz"].startswith("sha256:")
    assert (tmp_path / f"{STEM}.npz").read_bytes()


def test_a_refused_recomputation_is_never_verified(tmp_path, monkeypatch, sources):
    """No independent number means no verification: the artifact is not its own witness."""
    from udv_echo_process.analysis.sparse_inventory import SparseIngestError

    write_artifacts(tmp_path, sources)

    def refuse(*args, **kwargs):
        raise SparseIngestError("the committed sources do not bind")

    monkeypatch.setattr(verify, "recompute_sa5_sources", refuse)
    with pytest.raises(verify.Sa5VerificationError, match="cannot be recomputed"):
        verify.verify_sa5_artifacts(PASS_REF, artifact_dir=tmp_path, stem=STEM)


@pytest.mark.parametrize(
    "name",
    ["stage2-e20-e64", "sparse-mixer-first-pass", "sparse-mixer-live-2"],
)
def test_only_one_reproducibility_sitting_is_ever_verified(tmp_path, monkeypatch, name):
    """Stage-2 and a dataset with no published effects are refused before any file read."""
    other = PassRef(
        name=name,
        root=Path("data") / name,
        plan_path=Path("examples") / name / "run-plan.json",
        role=PassRole.CAMPAIGN if name == "stage2-e20-e64" else PassRole.SITTING,
        note="a pass the SA5 effect schema does not reach",
        period_law="",
        in_frozen_design=name != "stage2-e20-e64",
        is_reproducibility_sitting=False,
        report_dir=Path("reports") / name,
    )
    with pytest.raises(verify.Sa5VerificationError):
        verify.verify_sa5_artifacts(other, artifact_dir=tmp_path)


def test_a_stranger_stem_is_refused(tmp_path, monkeypatch, sources):
    write_artifacts(tmp_path, sources)
    with pytest.raises(verify.Sa5VerificationError, match="artifact stem"):
        run_verification(monkeypatch, sources, tmp_path, stem="sa5-live-2-effects")


def test_a_missing_file_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    paths["readme"].unlink()
    with pytest.raises(verify.Sa5VerificationError, match="README"):
        run_verification(monkeypatch, sources, tmp_path)


# ── the NPZ layer ──────────────────────────────────────────────────────


def test_a_byte_drifted_container_is_refused_by_the_codec(
    tmp_path, monkeypatch, sources
):
    paths = write_artifacts(tmp_path, sources)
    raw = bytearray(paths["npz"].read_bytes())
    raw[-1] ^= 0xFF
    paths["npz"].write_bytes(bytes(raw))
    with pytest.raises(verify.Sa5VerificationError, match="canonical §3/§4"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_canonical_but_wrong_number_is_refused_element_wise(
    tmp_path, monkeypatch, sources
):
    """A §3-legal container with a wrong value is still wrong: the arrays are compared."""
    by_id = _arrays_by_id(sources)
    effect_id = next(iter(by_id))
    by_id[effect_id]["effect"][0] += 1.0
    paths = write_artifacts(tmp_path, sources)
    paths["npz"].write_bytes(_container(by_id))
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    message = str(excinfo.value)
    assert member_name(effect_id, "effect") in message
    assert "position(s) differ" in message


def test_a_canonical_but_wrong_mask_is_refused_element_wise(
    tmp_path, monkeypatch, sources
):
    by_id = _arrays_by_id(sources)
    target = next(
        (
            (effect_id, slots)
            for effect_id, slots in by_id.items()
            if 0 in slots["defined"]
        ),
        None,
    )
    assert target is not None, "the fixture must carry an undefined knot"
    effect_id, slots = target
    index = int(np.flatnonzero(slots["defined"] == 0)[0])
    slots["defined"][index] = 1
    slots["state"][index] = 0
    paths = write_artifacts(tmp_path, sources)
    paths["npz"].write_bytes(_container(by_id))
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    message = str(excinfo.value)
    assert member_name(effect_id, "defined") in message
    assert member_name(effect_id, "state") in message


def _drop_member(raw: bytes, drop: str) -> bytes:
    """Re-lay the canonical container without one member, keeping every other header."""
    source = zipfile.ZipFile(io.BytesIO(raw))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as target:
        for info in source.infolist():
            if info.filename == drop:
                continue
            mirror = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            mirror.compress_type = info.compress_type
            mirror.external_attr = info.external_attr
            mirror.internal_attr = info.internal_attr
            mirror.create_system = info.create_system
            target.writestr(mirror, source.read(info))
    return buffer.getvalue()


def test_a_container_that_drops_a_member_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    effect_id = _expected_effect_ids(sources)[0]
    paths["npz"].write_bytes(
        _drop_member(
            paths["npz"].read_bytes(), member_name(effect_id, "participant_value")
        )
    )
    with pytest.raises(verify.Sa5VerificationError, match="missing member"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_json_member_list_that_shrinks_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["npz_members"] = list(document["npz_members"])[:-1]
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="npz_members"):
        run_verification(monkeypatch, sources, tmp_path)


# ── the CSV layer ──────────────────────────────────────────────────────


def test_a_wrong_csv_scalar_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    lines = paths["csv"].read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    column = header.index("signed_depth_average")
    row = lines[1].split(",")
    assert row[column] != ""
    row[column] = _render(float(row[column]) + 1.0)
    lines[1] = ",".join(row)
    paths["csv"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    with pytest.raises(verify.Sa5VerificationError, match="signed_depth_average"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_rounded_csv_scalar_is_refused(tmp_path, monkeypatch, sources):
    """The generator publishes ``.17g``: a display-rounded cell is not the same number."""
    paths = write_artifacts(tmp_path, sources)
    lines = paths["csv"].read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    column = header.index("rms_magnitude")
    mutated = False
    for index in range(1, len(lines)):
        row = lines[index].split(",")
        if row[column] == "":
            continue
        rounded = format(float(row[column]), ".6g")
        if float(rounded) == float(row[column]):
            continue
        row[column] = rounded
        lines[index] = ",".join(row)
        mutated = True
        break
    assert mutated, "the fixture must carry a scalar a display rounding would change"
    paths["csv"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    with pytest.raises(verify.Sa5VerificationError, match="rms_magnitude"):
        run_verification(monkeypatch, sources, tmp_path)


def test_an_empty_csv_field_where_a_value_belongs_is_refused(
    tmp_path, monkeypatch, sources
):
    paths = write_artifacts(tmp_path, sources)
    lines = paths["csv"].read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    column = header.index("equal_knot_average")
    row = lines[1].split(",")
    assert row[column] != ""
    row[column] = ""
    lines[1] = ",".join(row)
    paths["csv"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    with pytest.raises(verify.Sa5VerificationError, match="equal_knot_average"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_reordered_csv_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    lines = paths["csv"].read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    paths["csv"].write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    with pytest.raises(verify.Sa5VerificationError, match="effect order"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_closed_csv_header_is_enforced(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    text = paths["csv"].read_text(encoding="utf-8")
    paths["csv"].write_text(
        text.replace("sitting,", "sitting,extra,", 1), encoding="utf-8", newline=""
    )
    with pytest.raises(verify.Sa5VerificationError, match="closed"):
        run_verification(monkeypatch, sources, tmp_path)


# ── the JSON layer ─────────────────────────────────────────────────────


def test_a_wrong_provenance_digest_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["provenance"][0]["source_sha256"] = "0" * 64
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    assert "provenance['cc1'].source_sha256" in str(excinfo.value)


def test_an_extra_field_is_a_schema_change(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["extra"] = 1
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="unexpected \\['extra'\\]"):
        run_verification(monkeypatch, sources, tmp_path)


def test_an_extra_effect_field_is_a_schema_change(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["effects"][0]["max_abs_offset_mm"] = 0.0
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="max_abs_offset_mm"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_mirrored_shape_count_that_disagrees_is_refused(
    tmp_path, monkeypatch, sources
):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["effects"][0]["knot_count"] += 1
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="knot_count"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_flipped_check_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["checks"]["window_is_the_declared_primary"] = False
    document["ok"] = False
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    assert "window_is_the_declared_primary" in str(excinfo.value)


def test_a_missing_nonvalue_row_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    assert document["nonvalue_rows"], "the fixture must carry missing-value positions"
    dropped = document["nonvalue_rows"].pop()
    document["nonvalue_counts"] = _nonvalue_counts(document["nonvalue_rows"])
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="missing position"):
        run_verification(monkeypatch, sources, tmp_path)
    del dropped


def test_a_mis_stated_nonvalue_row_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    row = next(r for r in document["nonvalue_rows"] if r["kind"] == "read")
    row["state"] = "refused-axis"
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    assert "nonvalue_rows" in str(excinfo.value)
    assert "reason" in str(excinfo.value) or "state" in str(excinfo.value)


def test_wrong_nonvalue_counts_are_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    state = next(iter(document["nonvalue_counts"]))
    kind = next(iter(document["nonvalue_counts"][state]))
    document["nonvalue_counts"][state][kind] += 1
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="nonvalue_counts"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_sitting_that_names_the_other_sitting_is_refused(
    tmp_path, monkeypatch, sources
):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["sitting"] = "sparse-mixer-live-2"
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="JSON sitting"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_non_canonical_json_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    text = paths["json"].read_text(encoding="utf-8")
    paths["json"].write_text(text.replace("{", "{ ", 1), encoding="utf-8", newline="")
    with pytest.raises(verify.Sa5VerificationError, match="canonical strict JSON"):
        run_verification(monkeypatch, sources, tmp_path)


# ── the tightened gaps: typed refusals, code spaces, bindings ──────────


def test_a_json_carrying_a_non_finite_number_is_a_typed_refusal(
    tmp_path, monkeypatch, sources
):
    """``json.loads`` accepts the bare ``NaN`` token; §5's ``allow_nan=False`` must refuse it.

    The refusal must be the verifier's own typed error, not the bare ``ValueError`` a
    re-serialization raises, because a verifier that raises an untyped error has no message a
    reader can act on.
    """
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["window_s"] = float("nan")
    paths["json"].write_text(
        json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=True,
        )
        + "\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(verify.Sa5VerificationError, match="non-finite"):
        run_verification(monkeypatch, sources, tmp_path)


def test_state_meanings_missing_an_effect_code_is_refused(
    tmp_path, monkeypatch, sources
):
    """Code ``1`` carries ``undefined-operand``: a content-only scan would let it be dropped."""
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    for record in document["effects"]:
        listed = _as_writer_state_meanings(record["state_meanings"])
        listed["effect"] = [row for row in listed["effect"] if row["code"] != 1]
        record["state_meanings"] = listed
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="state_meanings"):
        run_verification(monkeypatch, sources, tmp_path)


def test_state_meanings_with_the_two_code_spaces_swapped_is_refused(
    tmp_path, monkeypatch, sources
):
    """Codes ``1`` and ``2`` differ between the spaces: a swapped nesting is not §8.

    Built in the writer's list rendering, where a content-only scan that keyed nothing could
    not tell the two spaces apart at all.
    """
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    for record in document["effects"]:
        listed = _as_writer_state_meanings(record["state_meanings"])
        record["state_meanings"] = {
            "effect": listed["participant"],
            "participant": listed["effect"],
        }
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="state_meanings"):
        run_verification(monkeypatch, sources, tmp_path)


def test_both_state_meanings_renderings_are_accepted(tmp_path, monkeypatch, sources):
    """§5.3 fixes the §8 vocabulary, not its rendering: the writer's list form is read too."""
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    for record in document["effects"]:
        meanings = record["state_meanings"]
        meanings["effect"] = [
            {"code": int(code), "text": text}
            for code, text in meanings["effect"].items()
        ]
        meanings["participant"] = [
            {"code": int(code), "text": text}
            for code, text in meanings["participant"].items()
        ]
    rewrap(paths, document)
    result = run_verification(monkeypatch, sources, tmp_path)
    assert result.ok


def test_a_generator_command_that_does_not_name_the_sitting_is_refused(
    tmp_path, monkeypatch, sources
):
    """The command is deterministic: it must name the sitting it regenerates."""
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["generator_command"] = "python -m some.other.generator"
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="generator_command"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_foreign_generator_that_merely_names_the_sitting_is_refused(
    tmp_path, monkeypatch, sources
):
    """A matching sitting token does not make a foreign command reproducible."""
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["generator_command"] = (
        "python -m some.other.generator --sitting sparse-mixer-live-1"
    )
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError, match="generator_command"):
        run_verification(monkeypatch, sources, tmp_path)


def test_an_inventory_plan_fingerprint_unlike_the_decoded_plan_is_refused(
    tmp_path, monkeypatch, sources
):
    """§11.1: points.csv's plan identity is reconciled with the plan it was decoded from."""
    tampered = verify.Sa5Sources(
        decoding=SimpleNamespace(
            points=sources.decoding.points,
            support_mm=sources.binding.support_mm,
            plan_fingerprint="0" * 64,
        ),
        binding=sources.binding,
        effects=sources.effects,
    )
    write_artifacts(tmp_path, sources)
    with pytest.raises(verify.Sa5VerificationError, match="plan fingerprint"):
        run_verification(monkeypatch, tampered, tmp_path)


def test_a_csv_that_is_not_utf8_is_refused_as_utf8(tmp_path, monkeypatch, sources):
    """§6 fixes the CSV as UTF-8: an invalid byte is refused, never replaced with U+FFFD."""
    paths = write_artifacts(tmp_path, sources)
    raw = paths["csv"].read_bytes()
    paths["csv"].write_bytes(raw + b"\xff\xfe\n")
    with pytest.raises(verify.Sa5VerificationError, match="UTF-8"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_readme_that_mislabels_a_digest_it_binds_is_refused(
    tmp_path, monkeypatch, sources
):
    """A README digest that matches no published file is refused, not ignored."""
    paths = write_artifacts(tmp_path, sources)
    text = paths["readme"].read_text(encoding="utf-8")
    paths["readme"].write_text(
        text + f"\n- {STEM}.npz sha256:{'a' * 64}\n", encoding="utf-8"
    )
    with pytest.raises(verify.Sa5VerificationError, match="README"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_readme_that_binds_only_the_json_digest_is_refused(
    tmp_path, monkeypatch, sources
):
    """§7 binds the README to every published file: the NPZ and CSV digests are required."""
    paths = write_artifacts(tmp_path, sources)
    json_digest = table_digest(paths["json"])
    paths["readme"].write_text(
        f"# {STEM}\n\nThe bound file is {STEM}.json, digest {json_digest}.\n",
        encoding="utf-8",
    )
    with pytest.raises(verify.Sa5VerificationError, match="README"):
        run_verification(monkeypatch, sources, tmp_path)


# ── the reconciliation and the digests, last ───────────────────────────


def test_an_unreconciled_operand_digest_is_refused(tmp_path, monkeypatch, sources):
    """§11.1: the inventory row is checked against the decoded file, not trusted."""
    updated = list(sources.decoding.points)
    for index, point in enumerate(updated):
        if point.binding.point.label == "cc3":
            updated[index] = SimpleNamespace(
                **{
                    **vars(point),
                    "source_sha256": _digest("a-substituted-recording"),
                }
            )
    tampered = verify.Sa5Sources(
        decoding=SimpleNamespace(
            points=tuple(updated),
            support_mm=sources.binding.support_mm,
            plan_fingerprint=PLAN_FINGERPRINT,
        ),
        binding=sources.binding,
        effects=sources.effects,
    )
    write_artifacts(tmp_path, sources)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, tampered, tmp_path)
    message = str(excinfo.value)
    assert "operand 'cc3' source_sha256" in message
    assert "relative_path" not in message


def test_the_readme_must_bind_the_json_digest(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    paths["readme"].write_text("# unrelated\n", encoding="utf-8")
    with pytest.raises(verify.Sa5VerificationError, match="README"):
        run_verification(monkeypatch, sources, tmp_path)


def test_a_wrong_npz_digest_is_refused(tmp_path, monkeypatch, sources):
    paths = write_artifacts(tmp_path, sources)
    document = load_document(paths)
    document["artifacts"]["npz"]["sha256"] = "sha256:" + "0" * 64
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    assert "NPZ's file-byte digest" in str(excinfo.value)


def test_a_matching_digest_over_a_wrong_number_is_still_refused(
    tmp_path, monkeypatch, sources
):
    """The digest is the last check, never the whole verification (§11.5)."""
    by_id = _arrays_by_id(sources)
    effect_id = next(iter(by_id))
    by_id[effect_id]["participant_value"][0, 0] += 0.5
    paths = write_artifacts(tmp_path, sources)
    raw_npz = _container(by_id)
    paths["npz"].write_bytes(raw_npz)
    document = load_document(paths)
    digest = f"{verify.DIGEST_PREFIX}{hashlib.sha256(raw_npz).hexdigest()}"
    document["artifacts"]["npz"]["sha256"] = digest
    rewrap(paths, document)
    with pytest.raises(verify.Sa5VerificationError) as excinfo:
        run_verification(monkeypatch, sources, tmp_path)
    message = str(excinfo.value)
    assert member_name(effect_id, "participant_value") in message
    assert "position(s) differ" in message
    assert "digest" not in message


def test_the_verifier_never_imports_the_report_writer():
    import ast

    source = Path(verify.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = (
        f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )
    assert all("sparse_sa5_report" not in module for module in imports)
    direct_imports = (
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert all("sparse_sa5_report" not in name for name in direct_imports)


def test_the_fixture_sitting_carries_the_documented_effect_count(sources):
    assert len(ENDPOINTS) == 9
    assert len(_expected_effect_ids(sources)) == 72
    assert len(set(_expected_effect_ids(sources))) == 72
    states = {
        int(code)
        for slots in _arrays_by_id(sources).values()
        for code in slots["state"]
    }
    assert states <= set(EFFECT_STATE_CODES)
    participant_states = {
        int(code)
        for slots in _arrays_by_id(sources).values()
        for code in slots["participant_state"].ravel()
    }
    assert participant_states <= set(PARTICIPANT_STATE_CODES)
    assert SparseView.PRIMARY.value in next(iter(_arrays_by_id(sources)))


# ── the committed sources, recomputed through the real loader ──────────


@pytest.fixture(scope="module")
def committed_sources() -> verify.Sa5Sources:
    """One committed sitting's effects, recomputed through the real decode/bind/measure path."""
    ref = pass_by_name("sparse-mixer-live-1")
    return verify.recompute_sa5_sources(
        ref,
        root=Path(ref.root),
        plan_path=Path(ref.plan_path),
        directory=Path(ref.report_dir),
    )


def test_the_committed_sitting_recomputes_from_its_own_sources(committed_sources):
    """§11.1–§11.2 on the committed data: decode, bind and measure, not the writer's files."""
    binding = committed_sources.binding
    effects = committed_sources.effects
    assert binding.plan == "sparse-mixer-live-1"
    assert len(binding.operands) == 11
    assert all(effects.checks.values())
    ids = _expected_effect_ids(committed_sources)
    assert len(ids) == len(set(ids)) == 72
    assert all(record.startswith("primary-comparison__") for record in ids[:24])


def test_the_publish_root_is_derived_beside_the_pass_reports():
    ref = pass_by_name("sparse-mixer-live-1")
    assert verify.artifact_dir_of(ref) == Path("reports/sparse-signal")


def test_a_sitting_with_unpublished_artifacts_is_never_verified(tmp_path, monkeypatch):
    """No file set means no verification: the refusal names the missing file."""
    ref = pass_by_name("sparse-mixer-live-1")

    def never(*args, **kwargs):  # pragma: no cover - the file check comes first
        raise AssertionError(
            "a missing artifact must be refused before any recomputation"
        )

    monkeypatch.setattr(verify, "recompute_sa5_sources", never)
    with pytest.raises(verify.Sa5VerificationError, match="is missing"):
        verify.verify_sa5_artifacts(ref, artifact_dir=tmp_path)
