"""Tests for SA5's cross-sitting descriptive agreement backend.

Contract: ``docs/dop3000/sa5-cross-sitting-agreement-prespec.md`` — two frozen quartets bound
by the v1 digest chain, a fixed ``live2 - live1`` orientation, a strict triple/``effect_id``
match, 72 typed in-memory comparisons with every §5 diagnostic, each side's §6 context quoted
beside them, the §7 ``comparison_state``/``label_state`` split, and the §6 repeat-context
mapping by exact achieved identity.

Pinned: the committed quartets' three-digest chains and 72 unique records in the frozen order
(a ``comparable`` pair carrying ``deferred-pending-review`` and the whole diagnostic set); the
§6 mapping on real data — ``E20`` selects the verified common-reference group, the corners and
the interaction are ``repeat-context-unavailable``, and ``e8``/``e64``/``e128`` are
``repeat-context-identity-unverifiable`` with **no numerical repeat range**, a run
``limitations`` entry, and a context state that never becomes a ``comparison_state`` or
``label_state``; the refusal gate (a tampered container/JSON/CSV/README, a third sitting, a
reversed orientation); and adversarial synthetic quartets (built through the real report
writer, then doctored at the typed-quartet seam) driving the §3 grid mismatch and the §5
typed-empties. The real-sitting tests assert structure, states and algebraic identities, never
a scientific agreement number as a result.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis import sparse_sa5_cross_sitting as x
from udv_echo_process.analysis import sparse_sa5_effects as fx
from udv_echo_process.analysis import sparse_sa5_report as report
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_sa5_bindings import bind_sitting
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName
from udv_echo_process.analysis.sparse_sa5_npz import MEMBER_DTYPES, EffectArrays

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "sparse-signal"
CORNER_KEY = "primary-comparison__mean__pitch_at_burst_4"
CORNER_CONTRAST = "pitch_at_burst_4"
MEAN, PRIMARY = MetricName.MEAN, SparseView.PRIMARY
#: The 16 effect keys whose whole comparison domain is empty on the committed quartets.
WHOLLY_UNDEFINED_METRIC = "recurrence-peak-lag"


@pytest.fixture(scope="module")
def published():
    return x.load_published_quartets(REPORT_DIR)


@pytest.fixture(scope="module")
def comparison(published):
    return x.compare_cross_sitting(*published)


def _corner(comparison):
    return comparison.record(PRIMARY, MEAN, CORNER_CONTRAST)


def test_published_quartets_verify_their_digest_chains(published) -> None:
    live1, live2 = published
    for side in (live1, live2):
        readme = (REPORT_DIR / f"{side.stem}.README.md").read_text("utf-8")
        assert side.digests["json"] in readme
        assert side.document["artifacts"]["npz"]["sha256"] == side.digests["npz"]
        assert side.document["artifacts"]["csv"]["sha256"] == side.digests["csv"]
        assert side.document["ok"] is True and all(side.document["checks"].values())
    assert live1.sitting == "live-1" and live2.sitting == "live-2"


def test_comparison_has_72_unique_records_in_the_frozen_order(comparison) -> None:
    keys = [record.effect_id for record in comparison.records]
    assert len(keys) == 72 and len(set(keys)) == 72
    assert keys[0] == CORNER_KEY
    assert comparison.comparison == "live2 - live1"
    assert comparison.checks["seventy_two_comparisons"] is True
    assert comparison.checks["no_output_artifact_written"] is True


def test_comparable_records_carry_a_deferred_label_and_diagnostics(comparison) -> None:
    comparable = [
        r
        for r in comparison.records
        if r.comparison_state is x.ComparisonState.COMPARABLE
    ]
    assert comparable
    for record in comparable:
        assert record.label_state == x.LABEL_DEFERRED
        assert record.diagnostics is not None
        assert record.comparison_state.value in x.COMPARISON_STATES
        assert record.diagnostics.defined_count >= 1


def test_a_wholly_undefined_metric_is_not_comparable(comparison) -> None:
    empty = [r for r in comparison.records if r.metric == WHOLLY_UNDEFINED_METRIC]
    assert len(empty) == 16
    for record in empty:
        assert record.comparison_state is x.ComparisonState.NOT_COMPARABLE
        assert record.comparison_reason == x.REASON_WHOLLY_UNDEFINED
        assert record.label_state is None and record.diagnostics is None


def test_real_corner_comparison_matches_the_specification(comparison) -> None:
    record = _corner(comparison)
    assert record.comparison_state is x.ComparisonState.COMPARABLE
    # A comparable pair names its established basis, never the absent resolvability rule: the
    # missing recurrence rule defers the label, not the comparison.
    assert record.comparison_reason == x.REASON_COMMON_BASIS
    assert record.comparison_reason != x.REASON_NO_RULE
    assert record.label_state == x.LABEL_DEFERRED
    assert record.grid == x.CORNER_GRID and len(record.knots) == record.knot_count
    assert record.support_mm is not None and record.support_mm[1] > record.support_mm[0]
    # Every published comparison knot lies inside both sides' support intersection (§3).
    low, high = record.support_mm
    assert all(low <= knot.depth_mm <= high for knot in record.knots)
    for knot in record.knots:
        if knot.defined:
            assert knot.difference == knot.value2 - knot.value1  # type: ignore[operator]
        else:
            assert knot.value1 is None and knot.value2 is None
    diag = record.diagnostics
    assert (
        diag.defined_count
        == diag.sign_count + diag.zero1_count + diag.zero2_count - diag.zero_count
    )
    assert (
        diag.positive_count + diag.negative_count + diag.zero_count
        == diag.defined_count
    )
    if diag.covered_depth_mm > 0.0:
        assert diag.signed_depth_average is not None and diag.rms_difference is not None
        assert diag.rms_difference >= abs(diag.signed_depth_average) - 1e-9


def test_repeat_context_mapping_is_real_and_honest(comparison) -> None:
    e8 = comparison.record(PRIMARY, MEAN, "E8_minus_E20")
    contexts = {c.operand: c for c in e8.context1.repeats}
    assert set(contexts) == {"e8", "E20"}
    assert contexts["E20"].state is x.RepeatContextState.SELECTED
    assert contexts["E20"].identity_verified is True
    assert contexts["E20"].members and contexts["E20"].min_value is not None
    assert contexts["e8"].state is x.RepeatContextState.UNVERIFIABLE
    assert contexts["e8"].identity_verified is False
    assert contexts["e8"].reason == x.REASON_REPEAT_UNVERIFIABLE
    assert contexts["e8"].members  # the named group is quoted, not silently dropped
    # Amended §6 policy: an unverifiable context publishes no numerical repeat range.
    assert (
        contexts["e8"].min_value,
        contexts["e8"].max_value,
        contexts["e8"].spread,
    ) == (
        None,
        None,
        None,
    )

    corner = _corner(comparison)
    states = {c.operand: c.state for c in corner.context1.repeats}
    assert set(states) == {"cc1", "cc3"}
    assert all(s is x.RepeatContextState.UNAVAILABLE for s in states.values())
    assert all(c.min_value is None for c in corner.context1.repeats)

    interaction = comparison.record(PRIMARY, MEAN, x.INTERACTION_NAME)
    assert {c.operand for c in interaction.context2.repeats} == {
        "cc1",
        "cc2",
        "cc3",
        "cc4",
    }
    assert all(
        c.state is x.RepeatContextState.UNAVAILABLE
        for c in interaction.context2.repeats
    )
    assert comparison.checks["repeat_context_identity_fully_established"] is False
    assert comparison.ok is True
    assert (
        comparison.checks["repeat_context_state_isolated_from_comparison_and_label"]
        is True
    )
    assert comparison.limitations and any("e8" in lim for lim in comparison.limitations)


def test_repeat_context_limitation_does_not_reassert_the_obsolete_gate(
    comparison,
) -> None:
    """The §6 identity gap is accepted ancillary context, never a §11.8 blocker (amended gate).

    Regression: the pre-amendment wording falsely gated the run — claiming §11.8 *cannot pass*
    until the anchor members' achieved conditions are published or the selection is pinned to
    job identity. The amended §11.8 accepts the identity-unverifiable entry with its numerical
    range omitted, so that claim must be gone while the operand set the verifier keys on stays.
    """
    text = " ".join(comparison.limitations)
    assert "cannot pass" not in text
    assert "until the anchor members' achieved conditions are published" not in text
    assert "pins the selection to job identity" not in text
    # The amended gate is satisfied by the typed entry with no numerical repeat range.
    assert "§11.8" in text and "satisfies the gate" in text
    assert "accepted ancillary context" in text
    assert "no numerical repeat range is reported" in text
    # The independent verifier's exact operand set is still named in the limitation.
    for operand in ("e8", "e64", "e128"):
        assert re.search(rf"\b{operand}\b", text)


def test_no_agreement_value_is_rendered_into_any_reason(comparison) -> None:
    for record in comparison.records:
        texts = [record.comparison_reason]
        for context in (*record.context1.repeats, *record.context2.repeats):
            texts.extend([context.reason, context.identity_basis])
        if record.diagnostics is None:
            continue
        diag = record.diagnostics
        texts += [
            diag.shape_reason,
            diag.peak_reason1,
            diag.peak_reason2,
            diag.peak_displacement_reason,
        ]
        for value in (
            diag.signed_depth_average,
            diag.rms_difference,
            diag.sign_agreement,
            diag.shape_correlation,
            diag.peak_displacement,
        ):
            if value is not None:
                token = format(float(value), ".10g")
                assert all(token not in text for text in texts), (
                    record.effect_id,
                    token,
                )


def test_published_quartets_are_byte_unchanged_after_a_run(published) -> None:
    def snapshot():
        return {
            name: hashlib.sha256((REPORT_DIR / name).read_bytes()).hexdigest()
            for name in sorted(p.name for p in REPORT_DIR.glob("sa5-live-*"))
        }

    before = snapshot()
    x.compare_cross_sitting(*x.load_published_quartets(REPORT_DIR))
    assert before == snapshot()
    assert published[0].pass_name == "sparse-mixer-live-1"
    assert published[1].pass_name == "sparse-mixer-live-2"


def write_side(artifacts: report.Sa5Artifacts, directory: Path) -> None:
    for name, payload in artifacts.files:
        (directory / name).write_bytes(payload)


def test_reversed_orientation_is_refused(published) -> None:
    live1, live2 = published
    with pytest.raises(x.SparseSa5CrossSittingError, match="fixed"):
        x.compare_cross_sitting(live2, live1)


def test_a_third_sitting_is_refused() -> None:
    with pytest.raises(x.SparseSa5CrossSittingError, match="reproducibility"):
        x.load_quartet(REPORT_DIR, "stage2-e20-e64")


@pytest.mark.parametrize("target", ["npz", "json", "csv", "README.md"])
def test_a_tampered_quartet_refuses(target: str) -> None:
    # A side whose bytes no longer reconcile with its chain is refused, against a scratch copy
    # so the committed tree stays untouched. A README's own digest is carried nowhere, so the
    # binding it can break is the JSON's: every digest token it states is corrupted.
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        for suffix in (".npz", ".json", ".csv", ".README.md"):
            shutil.copyfile(
                REPORT_DIR / f"sa5-live-1-effects{suffix}",
                directory / f"sa5-live-1-effects{suffix}",
            )
        path = directory / f"sa5-live-1-effects.{target}"
        if target == "README.md":
            text = re.sub(
                r"sha256:[0-9a-f]{64}", "sha256:" + "0" * 64, path.read_text("utf-8")
            )
            path.write_text(text, "utf-8")
        else:
            raw = bytearray(path.read_bytes())
            raw[len(raw) // 2] ^= 0x01
            path.write_bytes(bytes(raw))
        with pytest.raises(x.SparseSa5CrossSittingError):
            x.load_quartet(directory, "live-1")


SOUND_SPEED_MS = 1480.0
FIRST_GATE_MM = 10.138
SUPPORT_HIGH_MM = 98.938
FINE_PITCH_MM = clamp_resolution(0.617, SOUND_SPEED_MS)
COARSE_PITCH_MM, REFERENCE_PITCH_MM = 2.96, 1.85
DT_S, PROFILES, PERIOD_S = 0.02, 620, 0.5
PLAN = _SIT = "sparse-mixer-live-1"
_STEM = "sa5-live-1-effects"
#: label -> (job, order, burst, emissions, pitch, gates, mean-base, mean-slope); no anchors.
_SPEC = {
    "cc1": ("burst-4", 2, 4, 20, FINE_PITCH_MM, 145, 10.0, 1.0),
    "cc2": ("burst-18", 8, 18, 20, FINE_PITCH_MM, 145, 30.0, 0.5),
    "cc3": ("burst-4", 4, 4, 20, COARSE_PITCH_MM, 31, 12.0, 2.0),
    "cc4": ("burst-18", 10, 18, 20, COARSE_PITCH_MM, 31, 33.0, 0.5),
    "cr1": ("common-reference-1", 6, 10, 20, REFERENCE_PITCH_MM, 50, 5.0, 0.0),
    "cr2": ("common-reference-2", 12, 10, 20, REFERENCE_PITCH_MM, 50, 6.0, 0.0),
    "cr3": ("common-reference-3", 17, 10, 20, REFERENCE_PITCH_MM, 50, 7.0, 0.0),
    "cr4": ("common-reference-4", 22, 10, 20, REFERENCE_PITCH_MM, 50, 8.0, 0.0),
    "e8": ("emissions-8", 14, 10, 8, REFERENCE_PITCH_MM, 50, 10.0, 0.0),
    "e64": ("emissions-64", 19, 10, 64, REFERENCE_PITCH_MM, 50, 14.0, 0.0),
    "e128": ("emissions-128", 24, 10, 128, REFERENCE_PITCH_MM, 50, 22.0, 0.0),
}
_JOBS = ("burst-4", "burst-18", "emissions-8", "emissions-64", "emissions-128")
_ANCHOR_LABELS = ("ctrl-begin", "ctrl-mid", "ctrl-end")
PLAN_FINGERPRINT = hashlib.sha256(b"synthetic-sa5-plan").hexdigest()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _depths(pitch: float, gates: int) -> np.ndarray:
    return FIRST_GATE_MM + np.arange(gates, dtype=float) * pitch


def _row(label, job, order, burst, emissions, pitch, gates, *, control):
    depths = _depths(pitch, gates)
    inside = (depths >= FIRST_GATE_MM - 1e-9) & (depths <= SUPPORT_HIGH_MM + 1e-9)
    return {
        "relative_path": f"syn-{label}.BDD",
        "identity": f"syn-{label}",
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
        "supported_gates": int(np.count_nonzero(inside)),
        "window_s": 12.0,
        "is_control": "true" if control else "false",
        "source_sha256": _digest(f"src-{label}"),
        "plan": PLAN,
        "plan_fingerprint": PLAN_FINGERPRINT,
    }


def _point(label, job, order, burst, emissions, pitch, gates, base=0.0, slope=0.0):
    depths = _depths(pitch, gates)
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    means = np.asarray(
        [base + slope * (d - FIRST_GATE_MM) for d in depths], dtype=float
    )
    sine = np.sin(2.0 * np.pi * stamps / PERIOD_S)[:, None]
    return SimpleNamespace(
        values=means[None, :] + 4.0 * sine,
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


def _anchor_point(job, index, label):
    depths = _depths(REFERENCE_PITCH_MM, 50)
    return SimpleNamespace(
        values=np.tile(depths * 0.0 + float(40 + index), (PROFILES, 1)),
        time_s=np.arange(PROFILES, dtype=float) * DT_S,
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


def _synthetic_quartet() -> x.FrozenQuartet:
    rows, points = [], []
    for label, spec in _SPEC.items():
        rows.append(_row(label, *spec[:6], control=False))
        points.append(_point(label, *spec))
    for job in _JOBS:
        for index, label in enumerate(_ANCHOR_LABELS, start=1):
            rows.append(
                _row(label, job, index, 10, 20, REFERENCE_PITCH_MM, 50, control=True)
            )
            points.append(_anchor_point(job, index, label))
    binding = bind_sitting(rows, plan_name=PLAN)
    artifacts = report.build_sa5_artifacts(
        fx.measure_binding(binding, points, pass_name=PLAN),
        binding,
        sitting=_SIT,
        stem=_STEM,
        analysis_commit="test",
        generator_revision="test",
    )
    with tempfile.TemporaryDirectory() as scratch:
        write_side(artifacts, Path(scratch))
        return x.load_quartet(Path(scratch), "live-1")


@pytest.fixture(scope="module")
def synthetic() -> x.FrozenQuartet:
    return _synthetic_quartet()


def _arrays(effect_id, knots, effect, defined, state, participant_count=2):
    n, two, d = len(knots), (participant_count, len(knots)), MEMBER_DTYPES
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


def _doctor(quartet, key, *, arrays=None, **changes):
    """Return a copy with ``key``'s typed arrays and/or published record changed."""
    by_id = dict(quartet.by_id)
    by_id[key] = {**by_id[key], **changes}
    document = dict(quartet.document)
    document["effects"] = [
        ({**row, **changes} if row["effect_id"] == key else row)
        for row in document["effects"]
    ]
    replaced = {"arrays": arrays, "by_id": by_id, "document": document}
    return dataclasses.replace(
        quartet, **{k: v for k, v in replaced.items() if v is not None}
    )


def _doctor_effect(quartet, key, *, knots, effect, defined, state):
    arrays = dict(quartet.arrays)
    arrays[key] = _arrays(key, knots, effect, defined, state)
    return _doctor(quartet, key, arrays=arrays, knot_count=len(knots))


def _pair(*, knots, effect1, defined1, state1, effect2, defined2, state2):
    base = _synthetic_quartet()
    # The doctored knots span their own published support, so the §3 support intersection is
    # the full doctored grid: these cases exercise the §5/knot logic, not support narrowing.
    support = [float(knots.min()), float(knots.max())]
    left = _doctor(
        _doctor_effect(
            base,
            CORNER_KEY,
            knots=knots,
            effect=effect1,
            defined=defined1,
            state=state1,
        ),
        CORNER_KEY,
        support_mm=support,
    )
    right = _doctor(
        _doctor_effect(
            base,
            CORNER_KEY,
            knots=knots,
            effect=effect2,
            defined=defined2,
            state=state2,
        ),
        CORNER_KEY,
        support_mm=support,
    )
    return left, dataclasses.replace(
        right,
        sitting="live-2",
        pass_name="sparse-mixer-live-2",
    )


def _doctored(**arrays):
    """The single CORNER_CONTRAST record of a doctored synthetic pair."""
    return _corner(x.compare_cross_sitting(*_pair(**arrays)))


def _ones(n):
    return np.ones(n, dtype=np.uint8), np.zeros(n, dtype=np.uint8)


def test_a_mismatched_knot_set_is_grid_mismatch_pending_review() -> None:
    knots, values = np.asarray([10.0, 12.0, 14.0]), np.asarray([1.0, 2.0, 3.0])
    defined, zeros = _ones(3)
    same = {
        "effect1": values,
        "defined1": defined,
        "state1": zeros,
        "effect2": values,
        "defined2": defined,
        "state2": zeros,
    }
    left, _ = _pair(knots=knots, **same)
    _, right = _pair(knots=knots + 0.5, **same)
    record = _corner(x.compare_cross_sitting(left, right))
    assert record.comparison_state is x.ComparisonState.NOT_COMPARABLE
    assert record.comparison_reason == x.REASON_GRID and record.label_state is None


def test_a_units_mismatch_is_not_comparable(synthetic) -> None:
    right = dataclasses.replace(
        _doctor(synthetic, CORNER_KEY, units="seconds"),
        sitting="live-2",
        pass_name="sparse-mixer-live-2",
    )
    assert (
        _corner(x.compare_cross_sitting(synthetic, right)).comparison_reason
        == x.REASON_UNITS
    )


def test_a_missing_side_is_not_comparable(synthetic) -> None:
    right = dataclasses.replace(
        synthetic,
        by_id={k: v for k, v in synthetic.by_id.items() if k != CORNER_KEY},
        sitting="live-2",
        pass_name="sparse-mixer-live-2",
    )
    record = _corner(x.compare_cross_sitting(synthetic, right))
    assert record.comparison_state is x.ComparisonState.NOT_COMPARABLE
    assert record.comparison_reason.startswith(x.REASON_MISSING_SIDE)


def test_zero_covered_depth_gives_empty_integral() -> None:
    knots = np.asarray([10.0, 12.0, 14.0, 16.0])
    defined = np.asarray([1, 0, 1, 0], dtype=np.uint8)
    state = np.asarray([0, 1, 0, 1], dtype=np.uint8)
    effect = np.asarray([1.0, 0.0, 3.0, 0.0])
    diag = _doctored(
        knots=knots,
        effect1=effect,
        defined1=defined,
        state1=state,
        effect2=effect + 1.0,
        defined2=defined,
        state2=state,
    ).diagnostics
    assert diag is not None and diag.defined_count == 2 and diag.covered_depth_mm == 0.0
    assert diag.signed_depth_average is None and diag.rms_difference is None


def _supported_pair(*, knots, effect1, effect2, support1, support2):
    """A synthetic CORNER pair with equal knots but each side's own published support (§3)."""
    base = _synthetic_quartet()
    defined, state = _ones(len(knots))
    left = _doctor(
        _doctor_effect(
            base, CORNER_KEY, knots=knots, effect=effect1, defined=defined, state=state
        ),
        CORNER_KEY,
        support_mm=list(support1),
    )
    right = _doctor(
        _doctor_effect(
            base, CORNER_KEY, knots=knots, effect=effect2, defined=defined, state=state
        ),
        CORNER_KEY,
        support_mm=list(support2),
    )
    return left, dataclasses.replace(
        right, sitting="live-2", pass_name="sparse-mixer-live-2"
    )


def test_a_narrower_published_support_excludes_endpoints_from_every_diagnostic() -> (
    None
):
    # Equal native grids on both sides, but the published support intersection (11, 17) is
    # narrower than the grid (10..18): the two end knots are not comparison knots. An endpoint
    # is given a wildly different value in the two runs, so any influence on the defined count,
    # L, D̄, RMS(D), A_sign, the shape correlation, an extremum or a peak would show up.
    knots = np.asarray([10.0, 12.0, 14.0, 16.0, 18.0])
    domain_left = np.asarray([1.0, 2.0, 4.0])
    domain_right = (
        2.0 * domain_left + 1.0
    )  # 3, 5, 9: an exact linear map, Pearson r = 1.

    def run(ends1, ends2):
        left, right = _supported_pair(
            knots=knots,
            effect1=np.concatenate([ends1[:1], domain_left, ends1[1:]]),
            effect2=np.concatenate([ends2[:1], domain_right, ends2[1:]]),
            support1=(10.0, 18.0),
            support2=(11.0, 17.0),
        )
        return _corner(x.compare_cross_sitting(left, right))

    first = run((999.0, -999.0), (123.0, 456.0))
    doctored = run((-1000.0, 1000.0), (0.5, -0.5))

    assert first.comparison_state is x.ComparisonState.COMPARABLE
    assert first.comparison_reason == x.REASON_COMMON_BASIS
    assert first.support_mm == (11.0, 17.0)
    # The comparison knots are exactly the native knots inside the intersection.
    assert first.knots_mm == (12.0, 14.0, 16.0)
    assert tuple(knot.depth_mm for knot in first.knots) == (12.0, 14.0, 16.0)

    diag = first.diagnostics
    assert diag is not None and diag.defined_count == 3
    assert diag.covered_depth_mm == pytest.approx(
        4.0
    )  # L over [12, 16], not the full span
    assert diag.signed_depth_average == pytest.approx(3.25)  # D = [2, 3, 5]
    assert diag.rms_difference == pytest.approx((47.0 / 4.0) ** 0.5)
    assert diag.sign_count == 3 and diag.sign_agreement == pytest.approx(1.0)
    assert (
        diag.positive_count == 3 and diag.negative_count == 0 and diag.zero_count == 0
    )
    assert diag.zero1_count == 0 and diag.zero2_count == 0
    assert diag.shape_correlation == pytest.approx(1.0)
    # The extrema are the domain's, never the excluded endpoints' (999 etc.).
    assert diag.peak1_value == pytest.approx(4.0) and diag.peak1_depth == 16.0
    assert diag.peak2_value == pytest.approx(9.0) and diag.peak2_depth == 16.0
    assert diag.peak_displacement == 0.0 and diag.peaks_coincide is True

    # Changing only the excluded endpoints changes nothing at all.
    assert (
        doctored.knots_mm == first.knots_mm and doctored.support_mm == first.support_mm
    )
    assert doctored.diagnostics == first.diagnostics


def test_a_single_common_knot_still_has_a_maximum_but_no_localized_peak() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = (
        np.asarray([0, 1, 0], dtype=np.uint8),
        np.asarray([1, 0, 1], dtype=np.uint8),
    )
    diag = _doctored(
        knots=knots,
        effect1=np.asarray([0.0, -7.0, 0.0]),
        defined1=defined,
        state1=state,
        effect2=np.asarray([0.0, 3.0, 0.0]),
        defined2=defined,
        state2=state,
    ).diagnostics
    assert diag is not None and diag.defined_count == 1
    assert diag.covered_depth_mm == 0.0 and diag.signed_depth_average is None
    assert diag.peak1_value == 7.0 and diag.peak2_value == 3.0
    assert diag.peak_localized1 is False and diag.peak_localized2 is False
    assert diag.peak_reason1 == x.REASON_INSUFFICIENT_DEPTH
    assert diag.peak_displacement is None and diag.peaks_coincide is None


def test_a_constant_absolute_profile_has_no_localized_peak() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = _ones(3)
    diag = _doctored(
        knots=knots,
        effect1=np.asarray([5.0, 5.0, 5.0]),
        defined1=defined,
        state1=state,
        effect2=np.asarray([1.0, 9.0, 2.0]),
        defined2=defined,
        state2=state,
    ).diagnostics
    assert diag is not None
    assert (
        diag.peak_localized1 is False and diag.peak_reason1 == x.REASON_CONSTANT_PROFILE
    )
    assert diag.peak1_value == 5.0  # the numerical maximum survives
    assert diag.peak_localized2 is True
    assert diag.peak_displacement is None and diag.peaks_coincide is None


def test_sign_agreement_excludes_zeros_from_numerator_and_denominator() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = _ones(3)
    diag = _doctored(
        knots=knots,
        effect1=np.asarray([0.0, 2.0, 4.0]),
        defined1=defined,
        state1=state,
        effect2=np.asarray([1.0, 5.0, 9.0]),
        defined2=defined,
        state2=state,
    ).diagnostics
    assert diag is not None
    # S = {knot 1, knot 2}: knot 0 has E1 == 0 and is excluded from both parts. D = [1, 3, 5]
    # over a 4 mm span: L = 4, Dbar = 3.0, RMS = sqrt(11), and E2 = 2 E1 + 1.
    assert diag.sign_count == 2 and diag.zero1_count == 1 and diag.zero2_count == 0
    assert diag.sign_agreement == 1.0
    assert diag.covered_depth_mm == 4.0
    assert diag.signed_depth_average == pytest.approx(3.0)
    assert diag.rms_difference == pytest.approx(11.0**0.5)
    assert (
        diag.positive_count == 3 and diag.negative_count == 0 and diag.zero_count == 0
    )
    assert diag.shape_correlation == pytest.approx(1.0)
    assert diag.peak_displacement == 0.0 and diag.peaks_coincide is True


def test_sign_agreement_is_empty_when_no_knot_has_two_signs() -> None:
    knots = np.asarray([10.0, 12.0, 14.0])
    defined, state = _ones(3)
    diag = _doctored(
        knots=knots,
        effect1=np.zeros(3),
        defined1=defined,
        state1=state,
        effect2=np.asarray([1.0, 2.0, 3.0]),
        defined2=defined,
        state2=state,
    ).diagnostics
    assert diag is not None
    assert (
        diag.sign_count == 0 and diag.sign_agreement is None and diag.zero1_count == 3
    )


def _empty_side(sitting):
    return x.SideContext(
        sitting=sitting,
        units=None,
        rms_magnitude=None,
        signed_depth_average=None,
        equal_knot_average=None,
        max_abs_value=None,
        max_abs_depth_mm=None,
        covered_depth_mm=None,
        coverage_fraction=None,
        defined_count=None,
        undefined_alignment_count=None,
        undefined_operand_count=None,
        knot_count=None,
        repeats=(),
    )


def test_a_non_comparable_pair_carries_no_label_state() -> None:
    with pytest.raises(ValidationError):
        x.EffectComparison(
            effect_id="a__b__c",
            view="primary-comparison",
            metric="mean",
            contrast="c",
            grid=None,
            units=None,
            knot_count=None,
            participant_count=None,
            comparison_state=x.ComparisonState.NOT_COMPARABLE,
            comparison_reason="x",
            label_state=x.LABEL_DEFERRED,
            support_mm=None,
            knots_mm=(),
            knots=(),
            diagnostics=None,
            context1=_empty_side("live-1"),
            context2=_empty_side("live-2"),
        )
