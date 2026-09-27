"""Focused synthetic-adversarial and real tests for SA5's within-sitting effect engine.

The contract under test is `docs/dop3000/sa5-sitting-effects-prespec.md`: seven oriented
contrasts plus the derived pitch x burst interaction, per ``(metric, view)``, measured on
one sitting at a time. What the tests pin:

- the engine measures **every declared endpoint**, its seven contrasts and the interaction,
  with one effect row per knot and the two frozen knot grids (the coarse corners' 31 native
  supported gates for the pitch/burst contrasts and the interaction, the reference ladder's
  supported depths for the emissions contrasts);
- the orientation is ``M(high) - M(low)`` and the interaction is
  ``[M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]``, re-derived from the *published* operand values;
- the E20 operand is the **exactly equal-weight** mean of ``cr1..cr4`` where all four define
  the metric, and is undefined with the offending member and its own reason where any member
  is undefined — never an available-case mean;
- alignment is WP3's nearest-native read (no interpolation), with the native depth used and
  its signed offset published, and no anchor enters an operand;
- the depth summaries are physically weighted, report the RMS and the sign fractions over
  defined nonzero knots, resolve the largest-absolute-effect tie to the shallower knot, and
  correlate the compared profiles only when both are nonconstant and supported;
- a decoded file whose digest or achieved settings disagree with the committed inventory
  refuses rather than being substituted in;
- the module publishes nothing and performs no cross-sitting arithmetic.

The synthetic fixtures are constructed so several quantities are hand-checkable exactly (a
constant-in-time sitting) or analytically (a linear depth profile); the two committed
mixer-enabled sittings are measured through the real decoder path at the end. No effect
*number* is asserted here as a scientific result: the real-sitting tests assert structure and
algebraic identities over the engine's own published operands.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from udv_echo_process.acquire.plan import clamp_resolution
from udv_echo_process.analysis import sparse_sa5_effects as fx
from udv_echo_process.analysis._sparse_view import SparseView
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES, PassRef
from udv_echo_process.analysis.sparse_sa5_bindings import bind_sitting
from udv_echo_process.analysis.sparse_sa5_metrics import MetricName, MetricState

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

#: The labels the synthetic sitting binds, with their planned job, order, burst, emissions
#: and grid, exactly as the frozen binding expects them.
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

#: Each operand's own depth profile: ``mean(z) = base + slope * (z - first)``. The four
#: corners give a sign-changing burst contrast and interaction; the reference runs give a
#: constant E20 side and a constant E8/E64/E128 effect.
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
PLAN_NAME = "sa5-synthetic"


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


def _trace(label: str, depths: np.ndarray, *, constant_in_time: bool) -> np.ndarray:
    """One recording's ``(profiles, gates)`` trace: the linear profile, plus a sine."""
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    means = np.asarray([_mean_at(label, float(depth)) for depth in depths], dtype=float)
    if constant_in_time:
        return np.tile(means, (PROFILES, 1))
    sine = np.sin(2.0 * np.pi * stamps / PERIOD_S)[:, None]
    return means[None, :] + 4.0 * sine


def _point(
    label: str, pitch: float, gates: int, *, constant_in_time: bool
) -> SimpleNamespace:
    depths = _depths(pitch, gates)
    values = _trace(label, depths, constant_in_time=constant_in_time)
    stamps = np.arange(PROFILES, dtype=float) * DT_S
    return SimpleNamespace(
        values=values,
        time_s=stamps,
        depths=depths,
        config=SimpleNamespace(
            resolution_mm=float(pitch),
            burst_length=next(spec[3] for spec in _OPERANDS if spec[0] == label),
            emissions_per_profile=next(
                spec[4] for spec in _OPERANDS if spec[0] == label
            ),
            pulse_repetition_freq_hz=1e6 / 600.0,
        ),
        source_sha256=_digest(f"src-{label}"),
        relative_path=f"syn-{label}.BDD",
        binding=SimpleNamespace(
            job=SimpleNamespace(
                job=next(spec[1] for spec in _OPERANDS if spec[0] == label)
            ),
            point=SimpleNamespace(label=label),
            order=next(spec[2] for spec in _OPERANDS if spec[0] == label),
        ),
    )


def _anchor_point(job: str, index: int, label: str) -> SimpleNamespace:
    """One block-local anchor control: a reference-window recording of its own job."""
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


def _synthetic_sitting(*, constant_in_time: bool = False, cr4_constant: bool = False):
    """A complete synthetic sitting: its committed rows and its decoded recordings."""
    rows: list[dict[str, object]] = [
        _row(label, job, order, burst, emissions, pitch, gates, control=False)
        for label, job, order, burst, emissions, pitch, gates in _OPERANDS
    ]
    points: list[object] = []
    for label, job, order, burst, emissions, pitch, gates in _OPERANDS:
        const = constant_in_time or (cr4_constant and label == "cr4")
        points.append(_point(label, pitch, gates, constant_in_time=const))
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


@pytest.fixture(scope="module")
def constant_sitting():
    return _synthetic_sitting(constant_in_time=True)


@pytest.fixture(scope="module")
def sine_sitting():
    return _synthetic_sitting()


@pytest.fixture(scope="module")
def constant_result(constant_sitting):
    binding, points = constant_sitting
    return fx.measure_binding(binding, points, pass_name=PLAN_NAME)


@pytest.fixture(scope="module")
def sine_result(sine_sitting):
    binding, points = sine_sitting
    return fx.measure_binding(binding, points, pass_name=PLAN_NAME)


def _nearest(grid: np.ndarray, knot: float) -> float:
    return float(
        np.asarray(grid, dtype=float)[
            int(np.abs(np.asarray(grid, float) - knot).argmin())
        ]
    )


# ── every endpoint, every contrast, the frozen knot grids ──────────────


def test_the_engine_measures_every_declared_endpoint_and_all_seven_contrasts(
    sine_result,
) -> None:
    assert len(fx.ENDPOINTS) == 9
    assert [(e.metric, e.view) for e in sine_result.endpoints] == list(fx.ENDPOINTS)
    names = [
        "pitch_at_burst_4",
        "pitch_at_burst_18",
        "burst_at_fine_pitch",
        "burst_at_coarse_pitch",
        "E8_minus_E20",
        "E64_minus_E20",
        "E128_minus_E20",
    ]
    for endpoint in sine_result.endpoints:
        assert [c.name for c in endpoint.contrasts] == names
        assert endpoint.interaction.name == fx.INTERACTION_NAME
        for effect in (*endpoint.contrasts, endpoint.interaction):
            assert len(effect.effects) == len(effect.knots_mm)
            assert effect.summary.defined_count == sum(
                1 for row in effect.effects if row.defined
            )


def test_the_two_knot_grids_are_the_coarse_corners_and_the_reference_ladder(
    sine_result,
) -> None:
    endpoint = sine_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    for name in (
        "pitch_at_burst_4",
        "pitch_at_burst_18",
        "burst_at_fine_pitch",
        "burst_at_coarse_pitch",
    ):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert len(effect.knots_mm) == COARSE_GATES
        assert effect.knots_mm[0] == pytest.approx(FIRST_GATE_MM)
        assert effect.knots_mm[-1] == pytest.approx(SUPPORT_HIGH_MM)
    for name in ("E8_minus_E20", "E64_minus_E20", "E128_minus_E20"):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert len(effect.knots_mm) == 49
        assert effect.knots_mm[0] == pytest.approx(FIRST_GATE_MM)
        assert effect.knots_mm[-1] == pytest.approx(SUPPORT_HIGH_MM)
    assert len(endpoint.interaction.knots_mm) == COARSE_GATES


# ── orientation, exactness on the constant sitting ─────────────────────


def test_orientation_is_high_minus_low_and_uses_the_native_gate_used(
    constant_result,
) -> None:
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    pairs = {
        "pitch_at_burst_4": ("cc3", "cc1"),
        "pitch_at_burst_18": ("cc4", "cc2"),
        "burst_at_fine_pitch": ("cc2", "cc1"),
        "burst_at_coarse_pitch": ("cc4", "cc3"),
    }
    for name, (high, low) in pairs.items():
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert effect.operand_names == (high, low)
        assert effect.coefficients == (1.0, -1.0)
        for row in effect.effects:
            assert row.defined
            high_read, low_read = row.operands
            assert high_read.name == high and low_read.name == low
            # Exact on a constant-in-time trace: the value is the linear profile at the
            # native gate actually read, and the effect is high minus low there.
            expected = _mean_at(high, high_read.members[0].depth_mm) - _mean_at(
                low, low_read.members[0].depth_mm
            )
            assert row.value == pytest.approx(expected, rel=0.0, abs=1e-9)
            assert row.value == pytest.approx(
                high_read.value - low_read.value, abs=1e-12
            )


def test_e20_is_the_exactly_equal_weight_mean_of_the_four_runs(constant_result) -> None:
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    for name, single in (
        ("E8_minus_E20", "e8"),
        ("E64_minus_E20", "e64"),
        ("E128_minus_E20", "e128"),
    ):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert effect.operand_names == (single, "E20")
        for row in effect.effects:
            single_read, e20 = row.operands
            assert single_read.kind == "recording"
            assert e20.kind == "mean-of-four"
            assert tuple(member.label for member in e20.members) == (
                "cr1",
                "cr2",
                "cr3",
                "cr4",
            )
            values = [member.value for member in e20.members]
            assert e20.value == sum(values) / 4
            # Each member is a distinct recording read at its own native gate, and the E20
            # mean's value is their arithmetic mean, not a rounded or weighted one.
            assert len({member.depth_mm for member in e20.members}) == 1
            assert e20.value == pytest.approx(
                sum(
                    _mean_at(label, e20.members[0].depth_mm)
                    for label in ("cr1", "cr2", "cr3", "cr4")
                )
                / 4,
                abs=1e-9,
            )
            assert row.value == pytest.approx(single_read.value - e20.value, abs=1e-12)


def test_interaction_recomputes_as_the_difference_of_differences(
    constant_result,
) -> None:
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    interaction = endpoint.interaction
    assert interaction.operand_names == ("cc1", "cc2", "cc3", "cc4")
    assert interaction.coefficients == (1.0, -1.0, -1.0, 1.0)
    for row in interaction.effects:
        cc1, cc2, cc3, cc4 = row.operands
        assert row.value == pytest.approx(
            (cc4.value - cc2.value) - (cc3.value - cc1.value), abs=1e-12
        )
        # Equally the simple-effect identity, rebuilt from the published contrasts.
    pitch_4 = next(c for c in endpoint.contrasts if c.name == "pitch_at_burst_4")
    pitch_18 = next(c for c in endpoint.contrasts if c.name == "pitch_at_burst_18")
    for index, row in enumerate(interaction.effects):
        assert row.value == pytest.approx(
            pitch_18.effects[index].value - pitch_4.effects[index].value, abs=1e-12
        )


def test_the_identity_holds_even_when_the_high_condition_was_acquired_first(
    constant_result,
) -> None:
    """Orientation is by condition, never by acquisition order.

    ``cc3`` (the high operand of the pitch-at-burst-4 contrast) has a later planned order
    than ``cc1``, and the E20 side of each emissions contrast is a mean of four runs acquired
    before the single emissions point. The signed effect follows ``M(high) - M(low)`` in every
    case, which the constants below re-derive from the decoded profile rather than the order.
    """
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    for name in (
        "pitch_at_burst_4",
        "pitch_at_burst_18",
        "burst_at_fine_pitch",
        "burst_at_coarse_pitch",
    ):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        for row in effect.effects:
            high = _mean_at(
                effect.operand_names[0], row.operands[0].members[0].depth_mm
            )
            low = _mean_at(effect.operand_names[1], row.operands[1].members[0].depth_mm)
            assert np.sign(row.value) == np.sign(high - low)


# ── alignment ──────────────────────────────────────────────────────────


def test_alignment_reads_the_nearest_native_gate_and_publishes_the_offset(
    constant_result,
) -> None:
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    effect = next(c for c in endpoint.contrasts if c.name == "pitch_at_burst_4")
    coarse_grid = _depths(COARSE_PITCH_MM, COARSE_GATES)
    fine_grid = _depths(FINE_PITCH_MM, FINE_GATES)
    worst = 0.0
    for row in effect.effects:
        cc3, cc1 = row.operands
        assert cc3.members[0].depth_mm == pytest.approx(
            row.depth_mm
        )  # coarse: offset 0
        assert cc3.members[0].offset_mm == pytest.approx(0.0)
        assert cc3.members[0].gate_index == int(
            np.abs(coarse_grid - row.depth_mm).argmin()
        )
        # The fine corner is read at its own nearest native gate, never interpolated.
        assert cc1.members[0].gate_index == int(
            np.abs(fine_grid - row.depth_mm).argmin()
        )
        assert cc1.members[0].depth_mm == pytest.approx(
            _nearest(fine_grid, row.depth_mm)
        )
        assert cc1.members[0].depth_mm in set(fine_grid.tolist())
        assert cc1.members[0].offset_mm == pytest.approx(
            cc1.members[0].depth_mm - row.depth_mm, abs=1e-12
        )
        assert abs(cc1.members[0].offset_mm) <= FINE_PITCH_MM / 2 + 1e-9
        worst = max(worst, abs(cc1.members[0].offset_mm))
    assert effect.max_abs_offset_mm == pytest.approx(worst, abs=1e-12)
    assert effect.half_pitch_mm == pytest.approx(COARSE_PITCH_MM / 2)
    assert all(node in set(coarse_grid.tolist()) for node in effect.knots_mm)


def test_no_block_local_anchor_enters_any_operand_or_effect(sine_result) -> None:
    for endpoint in sine_result.endpoints:
        for effect in (*endpoint.contrasts, endpoint.interaction):
            for side in [op for row in effect.effects for op in row.operands]:
                assert not side.name.startswith("ctrl-")
                for member in side.members:
                    assert not member.label.startswith("ctrl-")
    assert sine_result.checks["no_block_local_anchor_enters_an_operand"] is True


# ── undefined members, refusals, correlation ───────────────────────────


def test_an_undefined_e20_member_leaves_the_operand_undefined_with_its_reason() -> None:
    binding, points = _synthetic_sitting(cr4_constant=True)
    result = fx.measure_binding(binding, points, pass_name=PLAN_NAME)
    # A constant-in-time cr4 defines no recurrence and no Φ fraction.
    for metric in (MetricName.RECURRENCE_1E_LAG, MetricName.PHI):
        endpoint = result.endpoint(metric, SparseView.PRIMARY)
        for name in ("E8_minus_E20", "E64_minus_E20", "E128_minus_E20"):
            effect = next(c for c in endpoint.contrasts if c.name == name)
            for row in effect.effects:
                e20 = row.operands[1]
                assert e20.kind == "mean-of-four"
                assert e20.state is fx.EffectState.UNDEFINED_OPERAND
                assert e20.value is None
                assert "cr4" in e20.reason
                assert row.state is fx.EffectState.UNDEFINED_OPERAND
                assert row.value is None
                # the offending member carries its own state on its own read
                cr4 = next(m for m in e20.members if m.label == "cr4")
                assert cr4.defined is False
    # The constant cr4 is a *defined zero* for the fluctuation scales, not a refusal.
    spread = result.endpoint(MetricName.STD, SparseView.PRIMARY)
    e8 = next(c for c in spread.contrasts if c.name == "E8_minus_E20")
    for row in e8.effects:
        assert row.defined
        cr4 = next(m for m in row.operands[1].members if m.label == "cr4")
        assert cr4.value == 0.0
        assert cr4.state is MetricState.DEFINED


def test_a_constant_trace_refuses_the_recurrence_and_the_phi_endpoints(
    constant_result,
) -> None:
    for endpoint in constant_result.endpoints:
        if endpoint.metric in (
            MetricName.RECURRENCE_1E_LAG,
            MetricName.RECURRENCE_PEAK_LAG,
        ):
            for effect in (*endpoint.contrasts, endpoint.interaction):
                for row in effect.effects:
                    assert not row.defined
                    assert row.state is fx.EffectState.UNDEFINED_OPERAND
                    assert row.value is None
        if endpoint.metric is MetricName.PHI:
            zero_power_reads = 0
            for effect in (*endpoint.contrasts, endpoint.interaction):
                for row in effect.effects:
                    for side in row.operands:
                        for read in side.members:
                            if read.state is MetricState.DEFINED_ZERO_POWER:
                                assert read.value is None
                                zero_power_reads += 1
                        if side.state is not fx.EffectState.DEFINED:
                            assert row.state is fx.EffectState.UNDEFINED_OPERAND
                            assert row.value is None
            # The zero-power refusal is exercised: a constant gate is a measurement whose
            # fraction is undefined (0/0), and it leaves the effect undefined with a reason.
            assert zero_power_reads > 0


def test_a_constant_compared_profile_has_no_correlation(constant_result) -> None:
    endpoint = constant_result.endpoint(MetricName.STD, SparseView.PRIMARY)
    effect = next(c for c in endpoint.contrasts if c.name == "burst_at_coarse_pitch")
    assert effect.shape.correlation is None
    assert "constant" in effect.shape.reason
    assert endpoint.interaction.shape.correlation is None
    assert "difference of differences" in endpoint.interaction.shape.reason
    # A varying mean profile does define a correlation.
    mean = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    varying = next(c for c in mean.contrasts if c.name == "burst_at_coarse_pitch")
    assert varying.shape.correlation is not None
    assert varying.shape.defined is True


# ── the depth summaries ────────────────────────────────────────────────


def test_the_depth_summary_is_physically_weighted_and_reports_its_signs(
    constant_result,
) -> None:
    endpoint = constant_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    effect = next(c for c in endpoint.contrasts if c.name == "burst_at_coarse_pitch")
    knots = np.asarray(effect.knots_mm, dtype=float)
    values = np.asarray([row.value for row in effect.effects], dtype=float)
    gaps = np.diff(knots)
    weights = np.empty(knots.size)
    weights[0] = gaps[0] / 2
    weights[-1] = gaps[-1] / 2
    weights[1:-1] = (gaps[:-1] + gaps[1:]) / 2
    summary = effect.summary
    assert summary.defined_count == knots.size
    assert summary.signed_depth_average == pytest.approx(
        float(np.sum(weights * values) / weights.sum()), abs=1e-12
    )
    assert summary.equal_knot_average == pytest.approx(
        float(np.mean(values)), abs=1e-12
    )
    assert summary.rms_magnitude == pytest.approx(
        float(np.sqrt(np.sum(weights * values**2) / weights.sum())), abs=1e-9
    )
    # The burst contrast at the coarse pitch changes sign over depth.
    assert 0.0 < summary.positive_fraction < 1.0
    assert summary.positive_fraction + summary.negative_fraction == pytest.approx(1.0)
    assert summary.min_value <= summary.signed_depth_average <= summary.max_value
    assert summary.max_abs_value == pytest.approx(abs(values).max(), abs=1e-12)


def test_the_largest_absolute_effect_resolves_a_tie_to_the_shallower_depth() -> None:
    """The documented tie rule, exercised directly on a hand-made effect profile."""

    def side(value):
        return fx.OperandRead(
            name="x",
            kind="recording",
            members=(
                fx.ReadAligned(
                    label="x",
                    gate_index=0,
                    depth_mm=10.0,
                    offset_mm=0.0,
                    value=value,
                    state=MetricState.DEFINED,
                    reason="r",
                ),
            ),
            value=value,
            state=fx.EffectState.DEFINED,
            reason="r",
        )

    rows = tuple(
        fx.KnotEffect(
            knot_index=index,
            depth_mm=depth,
            operands=(side(value), side(0.0)),
            state=fx.EffectState.DEFINED,
            value=value,
            reason="r",
        )
        for index, (depth, value) in enumerate([(10.0, 5.0), (20.0, -5.0), (30.0, 1.0)])
    )
    summary = fx._summarise(
        metric=MetricName.MEAN,
        view=SparseView.PRIMARY,
        units="mm/s",
        knots=(10.0, 20.0, 30.0),
        effects=rows,
    )
    assert summary.max_abs_value == pytest.approx(5.0)
    assert summary.max_abs_depth_mm == pytest.approx(10.0)
    assert summary.max_value == pytest.approx(5.0)
    assert summary.min_value == pytest.approx(-5.0)
    assert summary.positive_fraction == pytest.approx(2 / 3)
    assert summary.negative_fraction == pytest.approx(1 / 3)


# ── descriptive repeats ────────────────────────────────────────────────


def test_repeats_name_their_members_and_orders_and_stay_descriptive(
    sine_result,
) -> None:
    endpoint_repeats = [
        group
        for group in sine_result.repeats
        if group.metric is MetricName.MEAN and group.view is SparseView.PRIMARY
    ]
    conditions = {group.condition for group in endpoint_repeats}
    assert any("common-reference condition" in condition for condition in conditions)
    assert any("block-local anchor controls" in condition for condition in conditions)
    reference = next(
        group
        for group in endpoint_repeats
        if "common-reference condition" in group.condition
    )
    assert [(m.label, m.order, m.job) for m in reference.members] == [
        ("cr1", 6, "common-reference-1"),
        ("cr2", 12, "common-reference-2"),
        ("cr3", 17, "common-reference-3"),
        ("cr4", 22, "common-reference-4"),
    ]
    assert reference.spread == pytest.approx(reference.max_value - reference.min_value)
    # A job's own anchors are three recordings of one achieved condition, in order.
    anchors = [
        group
        for group in endpoint_repeats
        if "block-local anchor controls" in group.condition
    ]
    assert len(anchors) == len(_JOBS)
    for group in anchors:
        assert [member.label for member in group.members] == list(_ANCHOR_LABELS)
        assert [member.order for member in group.members] == [1, 2, 3]
    assert "descriptive" in reference.rule
    assert "never a threshold" in reference.rule
    assert sine_result.checks["repeats_name_their_members_and_orders"] is True


# ── the inventory must be bound to the decoded source ──────────────────


def test_a_decoded_digest_that_is_not_the_inventory_digest_refuses() -> None:
    binding, points = _synthetic_sitting()
    points = list(points)
    points[0] = SimpleNamespace(
        **{**vars(points[0]), "source_sha256": _digest("someone-else")}
    )
    with pytest.raises(fx.SparseSa5EffectsError, match="substituted"):
        fx.measure_binding(binding, points, pass_name=PLAN_NAME)


def test_a_decoded_setting_that_is_not_the_inventory_setting_refuses() -> None:
    binding, points = _synthetic_sitting()
    points = list(points)
    broken = vars(points[0]).copy()
    broken["config"] = SimpleNamespace(
        resolution_mm=broken["config"].resolution_mm,
        burst_length=int(broken["config"].burst_length) + 1,
        emissions_per_profile=broken["config"].emissions_per_profile,
        pulse_repetition_freq_hz=broken["config"].pulse_repetition_freq_hz,
    )
    points[0] = SimpleNamespace(**broken)
    with pytest.raises(fx.SparseSa5EffectsError, match="burst"):
        fx.measure_binding(binding, points, pass_name=PLAN_NAME)


def test_a_missing_decoded_operand_refuses() -> None:
    binding, points = _synthetic_sitting()
    with pytest.raises(fx.SparseSa5EffectsError, match="cc3"):
        fx.measure_binding(
            binding,
            [p for p in points if not p.relative_path.startswith("syn-cc3")],
            pass_name=PLAN_NAME,
        )


# ── no publication, no cross-sitting arithmetic ────────────────────────


def test_the_module_publishes_nothing_and_does_no_cross_sitting_arithmetic() -> None:
    source = Path(fx.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "write_text",
        ".write(",
        "open(",
        "json.dump",
        "csv.writer",
        "to_csv",
    ):
        assert forbidden not in source, forbidden
    for name in dir(fx):
        if name.startswith("_"):
            continue
        assert not name.startswith(
            ("agree", "compare", "publish", "write", "report")
        ), name
    assert not hasattr(fx.SittingEffects, "agreement")
    assert set(fx.measure_sitting.__annotations__) - {"return"} == {
        "pass_ref",
        "dataset_root",
        "plan_path",
        "report_dir",
        "low_hz",
        "max_lag_s",
    }


def test_a_pass_without_an_inventory_directory_refuses() -> None:
    ref = PassRef(
        name="sparse-mixer-live-1",
        root=Path("data/sparse-mixer-live-1"),
        plan_path=Path("examples/sparse-mixer-live-1/run-plan.json"),
        role=COMMITTED_PASSES[1].role,
        note="no inventory directory",
        period_law="",
        in_frozen_design=True,
        report_dir=None,
    )
    with pytest.raises(fx.SparseSa5EffectsError, match="inventory directory"):
        fx.measure_sitting(ref)


# ── both committed sittings, through the real reader path ──────────────

REAL_SITTINGS = tuple(ref for ref in COMMITTED_PASSES if ref.is_reproducibility_sitting)


@pytest.fixture(scope="module", params=REAL_SITTINGS, ids=lambda ref: ref.name)
def real_result(request):
    return fx.measure_sitting(request.param)


def test_both_committed_sittings_measure_every_endpoint(real_result) -> None:
    result = real_result
    assert result.ok is True
    assert all(result.checks.values())
    assert len(result.endpoints) == len(fx.ENDPOINTS) == 9
    assert [(e.metric, e.view) for e in result.endpoints] == list(fx.ENDPOINTS)
    assert result.window_s == 12.0
    assert result.plan in ("sparse-mixer-live-1", "sparse-mixer-live-2")
    for endpoint in result.endpoints:
        assert len(endpoint.contrasts) == 7
        for effect in (*endpoint.contrasts, endpoint.interaction):
            assert len(effect.effects) == len(effect.knots_mm)
            for row in effect.effects:
                if row.defined:
                    assert row.value is not None and np.isfinite(row.value)
                else:
                    assert row.value is None
                    assert row.state in (
                        fx.EffectState.UNDEFINED_OPERAND,
                        fx.EffectState.UNDEFINED_ALIGNMENT,
                    )
            assert effect.summary.defined_count + effect.summary.undefined_count == len(
                effect.knots_mm
            )


def test_the_real_knot_grids_are_the_frozen_ones(real_result) -> None:
    endpoint = real_result.endpoint(MetricName.MEAN, SparseView.PRIMARY)
    for name in (
        "pitch_at_burst_4",
        "pitch_at_burst_18",
        "burst_at_fine_pitch",
        "burst_at_coarse_pitch",
    ):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert len(effect.knots_mm) == 31
        assert effect.knots_mm[0] == pytest.approx(10.138)
        assert effect.knots_mm[-1] == pytest.approx(98.938)
        assert effect.max_abs_offset_mm <= effect.half_pitch_mm + 1e-9
    for name in ("E8_minus_E20", "E64_minus_E20", "E128_minus_E20"):
        effect = next(c for c in endpoint.contrasts if c.name == name)
        assert len(effect.knots_mm) == 49
        assert effect.max_abs_offset_mm == pytest.approx(0.0)


def test_real_effects_recompute_from_their_published_operands(real_result) -> None:
    for endpoint in real_result.endpoints:
        for effect in endpoint.contrasts:
            for row in effect.effects:
                if not row.defined:
                    continue
                high, low = row.operands
                assert row.value == pytest.approx(high.value - low.value, abs=1e-12)
                if low.kind == "mean-of-four":
                    values = [member.value for member in low.members]
                    assert all(value is not None for value in values)
                    assert low.value == sum(values) / 4
        for row in endpoint.interaction.effects:
            if not row.defined:
                continue
            cc1, cc2, cc3, cc4 = row.operands
            assert row.value == pytest.approx(
                (cc4.value - cc2.value) - (cc3.value - cc1.value), abs=1e-12
            )
