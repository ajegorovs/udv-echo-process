"""Adversarial tests for SA5's operand and contrast *binding*, on both sittings.

The contract under test is `docs/dop3000/sa5-sitting-effects-prespec.md`'s seven oriented
contrasts, and the tests pin what binding means: the four ``cc*`` corners, the four
``cr1..cr4`` E20 members and the three single emissions points are resolved by planned
job, point label, acquisition order and decoded achieved condition; the declared 12 s
window, the common support and each group's native grid are re-derived; a wrong label,
job, order, setting, PRF, grid or window, a missing or duplicated operand, an anchor
offered as an operand and a shared source digest all refuse; and the module computes no
effect value at all.

Both *committed* sittings are bound — the same eleven operands and the same seven
contrasts, with each sitting's own plan, source digests and recordings — so the binding
is a property of the per-pass inventory and not of one hard-coded dataset.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from udv_echo_process.analysis import sparse_sa5_bindings as sa5

ROOT = Path(__file__).resolve().parent.parent
SITTINGS = ("sparse-mixer-live-1", "sparse-mixer-live-2")


def _rows(sitting: str) -> list[dict[str, str]]:
    """The committed per-pass inventory of one sitting, as ``points.csv`` rows."""
    with (ROOT / "reports" / sitting / "points.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(params=SITTINGS)
def sitting(request) -> str:
    return request.param


@pytest.fixture
def rows(sitting: str) -> list[dict[str, str]]:
    return _rows(sitting)


@pytest.fixture
def binding(sitting: str, rows):
    return sa5.bind_sitting(rows, plan_name=sitting)


def _with(rows, label: str, **cells) -> list[dict[str, str]]:
    """A copy of the rows with one labelled row's cells replaced."""
    out: list[dict[str, str]] = []
    hit = False
    for row in rows:
        if row["requested_label"] == label:
            row = {**row, **cells}
            hit = True
        out.append(row)
    assert hit, label
    return out


def _without(rows, label: str) -> list[dict[str, str]]:
    """A copy of the rows with one labelled row removed."""
    kept = [row for row in rows if row["requested_label"] != label]
    assert len(kept) == len(rows) - 1, label
    return kept


def _refuse(rows, sitting: str, match: str | None = None) -> str:
    """Bind ``rows`` expecting a refusal, and return the message."""
    with pytest.raises(sa5.Sa5BindingError) as raised:
        sa5.bind_sitting(rows, plan_name=sitting)
    message = str(raised.value)
    if match is not None:
        assert match in message, message
    return message


# ── the frozen contract, on both sittings ──────────────────────────────


def test_binds_the_frozen_operand_membership(binding) -> None:
    assert [row.label for row in binding.operands] == list(sa5.OPERAND_LABELS)
    assert [(r.label, r.job, r.order) for r in binding.corners] == [
        ("cc1", "burst-4", 2),
        ("cc2", "burst-18", 8),
        ("cc3", "burst-4", 4),
        ("cc4", "burst-18", 10),
    ]
    assert [(r.label, r.job, r.order) for r in binding.e20] == [
        ("cr1", "common-reference-1", 6),
        ("cr2", "common-reference-2", 12),
        ("cr3", "common-reference-3", 17),
        ("cr4", "common-reference-4", 22),
    ]
    assert [
        (r.label, r.job, r.order, r.emissions_per_profile) for r in binding.singles
    ] == [
        ("e8", "emissions-8", 14, 8),
        ("e64", "emissions-64", 19, 64),
        ("e128", "emissions-128", 24, 128),
    ]
    assert binding.by_label("cc3").job == "burst-4"
    assert binding.by_label("cr4").job == "common-reference-4"


def test_binds_the_declared_window_and_common_support(binding) -> None:
    assert binding.window_s == sa5.DESIGNED_WINDOW_S == 12.0
    assert binding.window_revolutions == 100
    assert binding.support_mm == (10.138, 98.938)
    for row in binding.operands:
        assert row.window_s == 12.0


def test_binds_the_two_native_grids(binding) -> None:
    # The knot set is the coarse corners' own 31 native gates at 2.96 mm.
    assert len(binding.knot_depths_mm) == 31
    assert binding.knot_depths_mm[0] == 10.138
    assert binding.knot_depths_mm[-1] == 98.938
    # The emissions ladder is aligned on the reference window's own 50 gates at 1.85 mm.
    assert len(binding.emissions_depths_mm) == 50
    assert binding.emissions_depths_mm[0] == 10.138
    assert binding.emissions_depths_mm[-1] == pytest.approx(100.788, abs=1e-9)
    assert binding.corners[0].gates == binding.corners[1].gates == 145
    assert binding.corners[2].gates == binding.corners[3].gates == 31
    assert {row.gates for row in binding.e20 + binding.singles} == {50}
    # The fine corners share one grid; the coarse corners are the knot grid.
    assert binding.corners[0].resolution_mm == pytest.approx(0.6166666666666667)
    assert binding.corners[2].resolution_mm == 2.96


def test_the_seven_contrasts_are_oriented_high_minus_low(binding) -> None:
    assert [c.name for c in binding.contrasts] == list(sa5.CONTRAST_NAMES)
    by_name = {c.name: c for c in binding.contrasts}
    assert (
        by_name["pitch_at_burst_4"].high.members,
        by_name["pitch_at_burst_4"].low.members,
    ) == (
        ("cc3",),
        ("cc1",),
    )
    assert (
        by_name["pitch_at_burst_18"].high.members,
        by_name["pitch_at_burst_18"].low.members,
    ) == (
        ("cc4",),
        ("cc2",),
    )
    assert (
        by_name["burst_at_fine_pitch"].high.members,
        by_name["burst_at_fine_pitch"].low.members,
    ) == (
        ("cc2",),
        ("cc1",),
    )
    assert (
        by_name["burst_at_coarse_pitch"].high.members,
        by_name["burst_at_coarse_pitch"].low.members,
    ) == (
        ("cc4",),
        ("cc3",),
    )
    for name, high in (
        ("E8_minus_E20", "e8"),
        ("E64_minus_E20", "e64"),
        ("E128_minus_E20", "e128"),
    ):
        contrast = by_name[name]
        assert contrast.high.members == (high,)
        assert contrast.low is sa5.E20_OPERAND
        assert contrast.low.members == ("cr1", "cr2", "cr3", "cr4")
        assert contrast.low.kind == "mean-of-four"


def test_interaction_contract_is_the_difference_of_differences() -> None:
    weights = sa5.interaction_contributions()
    assert weights == {"cc1": 1.0, "cc2": -1.0, "cc3": -1.0, "cc4": 1.0}
    assert sa5.INTERACTION_EXPRESSION == "[M(cc4) - M(cc2)] - [M(cc3) - M(cc1)]"
    # Exactly the four corner labels carry a weight; no anchor and no emissions row does.
    assert set(weights) == set(sa5.CC_LABELS)
    # The weights reproduce [M(cc4) - M(cc2)] - [M(cc3) - M(cc1)] symbolically.
    cc1, cc2, cc3, cc4 = (weights[label] for label in sa5.CC_LABELS)
    pitch_4 = cc3 - cc1  # M(cc3) - M(cc1)
    pitch_18 = cc4 - cc2  # M(cc4) - M(cc2)
    assert [pitch_18, -pitch_4] == [cc4 - cc2, cc1 - cc3]
    assert (cc4 - cc2) - (cc3 - cc1) == cc4 - cc2 - cc3 + cc1


def test_anchors_are_excluded_from_every_operand(binding) -> None:
    assert all(not row.label.startswith(sa5.CONTROL_PREFIX) for row in binding.operands)
    assert all(row.is_control is False for row in binding.operands)
    assert all(not label.startswith(sa5.CONTROL_PREFIX) for label in sa5.OPERAND_LABELS)
    # The anchors exist in the sitting — they are context, and they are not operands.
    assert binding.control_labels == ("ctrl-begin", "ctrl-end", "ctrl-mid")
    assert binding.control_context == binding.control_labels


def test_source_identity_is_bound_and_distinct(binding) -> None:
    digests = [row.source_sha256 for row in binding.operands]
    assert len(set(digests)) == len(digests) == 11
    assert all(len(d) == 64 and d == d.lower() for d in digests)
    for row in binding.operands:
        assert row.identity.endswith(f"-{row.label}")
        assert row.relative_path.startswith(row.identity)
        assert row.plan == binding.plan
        assert len(row.plan_fingerprint) == 64


def test_achieved_settings_match_the_prespec(binding) -> None:
    for row in binding.corners:
        assert row.emissions_per_profile == 20 and row.prf_us == 600.0
        assert row.burst_length in (4, 18)
    for row in binding.e20:
        assert (row.burst_length, row.emissions_per_profile) == (10, 20)
        assert row.gates == 50 and row.resolution_mm == pytest.approx(1.85)
    for row in binding.singles:
        assert row.burst_length == 10 and row.prf_us == 600.0
        assert row.resolution_mm == pytest.approx(1.85)
    assert {row.emissions_per_profile for row in binding.singles} == {8, 64, 128}


def test_both_sittings_share_one_contract(rows) -> None:
    """The labels, jobs, orders and achieved settings are identical across sittings."""

    def signature(binding):
        return [
            (
                r.label,
                r.job,
                r.order,
                r.burst_length,
                r.emissions_per_profile,
                round(r.resolution_mm, 9),
                r.gates,
                r.supported_gates,
            )
            for r in binding.operands
        ]

    live1 = sa5.bind_sitting(_rows(SITTINGS[0]), plan_name=SITTINGS[0])
    live2 = sa5.bind_sitting(_rows(SITTINGS[1]), plan_name=SITTINGS[1])
    assert signature(live1) == signature(live2)
    assert live1.plan != live2.plan
    assert live1.plan_fingerprint != live2.plan_fingerprint
    assert {r.source_sha256 for r in live1.operands} != {
        r.source_sha256 for r in live2.operands
    }


def test_binding_is_independent_of_row_order(binding, rows) -> None:
    shuffled = list(reversed(rows))
    again = sa5.bind_sitting(shuffled, plan_name=binding.plan)
    assert [r.relative_path for r in again.operands] == [
        r.relative_path for r in binding.operands
    ]


# ── refusals: membership, order and identity ───────────────────────────


def test_a_wrong_label_refuses(rows, sitting) -> None:
    assert "cc1" in _refuse(_with(rows, "cc1", requested_label="ccX"), sitting)


def test_a_wrong_job_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cc1", job="burst-18"), sitting, match="job")


def test_a_wrong_acquisition_order_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cc2", order="9"), sitting, match="acquisition order")
    # The reversed order (a neighbour's planned order) refuses as well.
    _refuse(_with(rows, "cc4", order="8"), sitting, match="acquisition order")


def test_a_missing_single_emissions_point_refuses(rows, sitting) -> None:
    assert "e128" in _refuse(_without(rows, "e128"), sitting)


def test_a_missing_e20_member_refuses(rows, sitting) -> None:
    assert "cr3" in _refuse(_without(rows, "cr3"), sitting)


def test_a_missing_corner_refuses(rows, sitting) -> None:
    assert "cc3" in _refuse(_without(rows, "cc3"), sitting)


def test_a_duplicated_operand_label_refuses(rows, sitting) -> None:
    _refuse(
        _with(rows, "cc3", requested_label="cc1", identity="x-cc1"),
        sitting,
        match="more than one",
    )


def test_an_anchor_offered_as_an_operand_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cc1", is_control="true"), sitting, match="anchor")


def test_a_shared_source_digest_refuses(rows, sitting) -> None:
    cr1 = next(r for r in rows if r["requested_label"] == "cr1")
    _refuse(
        _with(rows, "cr3", source_sha256=cr1["source_sha256"]),
        sitting,
        match="source digest",
    )


def test_an_empty_or_malformed_digest_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "e8", source_sha256=""), sitting, match="digest")
    _refuse(_with(rows, "e8", source_sha256="deadbeef"), sitting, match="digest")


def test_an_identity_that_is_not_the_label_refuses(rows, sitting) -> None:
    _refuse(
        _with(rows, "cr2", identity="sparse2-common-reference-2-cr9"),
        sitting,
        match="label",
    )
    _refuse(
        _with(rows, "cr2", relative_path="elsewhere/other.BDD"),
        sitting,
        match="identity",
    )


def test_a_row_from_another_plan_refuses(rows, sitting) -> None:
    other = (
        "sparse-mixer-live-2"
        if sitting == "sparse-mixer-live-1"
        else "sparse-mixer-live-1"
    )
    _refuse(_with(rows, "e64", plan=other), sitting, match="plan")


# ── refusals: achieved settings, PRF, grid and window ──────────────────


def test_a_wrong_burst_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "e128", burst_length="4"), sitting, match="burst")


def test_a_wrong_emissions_level_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "e64", emissions_per_profile="32"), sitting, match="emissions")


def test_a_wrong_prf_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "e8", prf_period_us="500"), sitting, match="PRF")


def test_a_wrong_stored_pitch_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cc1", resolution_mm="1.85"), sitting, match="pitch")


def test_a_wrong_gate_count_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cc3", gates="145"), sitting, match="gates")


def test_a_wrong_window_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "e8", window_s="11.5"), sitting, match="window")


def test_a_grid_that_is_not_the_group_grid_refuses(rows, sitting) -> None:
    # A corner off its own ladder rung refuses at the achieved-setting check.
    _refuse(_with(rows, "cc4", resolution_mm="2.0"), sitting, match="pitch")
    # A last gate inconsistent with first gate + pitch * (gates - 1) refuses.
    _refuse(_with(rows, "cc4", depth_max_mm="100.788"), sitting, match="gate")
    # An emissions member off the reference window's grid refuses.
    _refuse(_with(rows, "e64", depth_max_mm="98.938"), sitting, match="grid")


def test_two_operands_that_do_not_share_one_grid_refuse() -> None:
    """The group-grid guard itself: a member on another native grid refuses alignment."""
    rows = _rows(SITTINGS[0])
    cr1 = sa5.operand_row(next(r for r in rows if r["requested_label"] == "cr1"))
    cr2 = sa5.operand_row(
        {
            **next(r for r in rows if r["requested_label"] == "cr2"),
            "resolution_mm": "2.0",
            "depth_max_mm": "199.0",
        }
    )
    with pytest.raises(sa5.Sa5BindingError, match="grid"):
        sa5._require_same_grid([cr1, cr2], what="the emissions ladder", where="x")


def test_a_wrong_supported_gate_count_refuses(rows, sitting) -> None:
    _refuse(_with(rows, "cr1", supported_gates="50"), sitting, match="supported")


def test_a_plan_name_that_disagrees_with_the_rows_refuses(rows, sitting) -> None:
    other = SITTINGS[1] if sitting == SITTINGS[0] else SITTINGS[0]
    with pytest.raises(sa5.Sa5BindingError, match="plan"):
        sa5.bind_sitting(rows, plan_name=other)


# ── no effect computation ──────────────────────────────────────────────


def test_the_module_computes_no_effect_value() -> None:
    """The binding carries no metric, profile or statistic — it binds operands only.

    A guard on the source itself: the shared per-gate reducers an effect would be built
    from must not be imported or called here, and no bound row exposes a value.
    """
    source = Path(sa5.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "gate_metrics",
        "supported_mean_of",
        "gate_statistics",
        "reference_repeat",
    ):
        assert forbidden not in source, forbidden
    # No bound field is a measurement, and the binding exposes no measured number.
    assert not set(sa5.OperandRow._fields) & {
        "mean",
        "mean_mm_s",
        "rms",
        "iqr",
        "value",
        "profile",
    }
    assert not hasattr(sa5.SittingBinding, "effect")
    assert not hasattr(sa5.SittingBinding, "measure")
    assert not any(
        name.startswith("measure") or name.endswith("_mm_s")
        for name in dir(sa5)
        if not name.startswith("__")
    )
