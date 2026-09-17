"""Tests for the ported sweep planning math — ``acquire/plan.py`` (+ ``config``).

Table-driven on purpose: the numbers in the tables are the *measured* ones from
the recon project, so a change to the arithmetic that silently moves a plan
fails here rather than at the rig.

Sources of the expected values:

- the resolution ladder, its snapping and its top rung — docs/08 §1 (a 122-point
  scan at c = 1500 m/s: rungs are exact multiples of 0.125 mm, snapping is
  nearest-rung, the ladder clamps at 15.000 mm);
- the gate range 4..1000 — docs/08 §2;
- the ``gates x pitch ~ 100 mm`` plan table — docs/16 §12 (c = 1460, first gate
  5 mm as assumed there) and the two *validated* points — docs/16 §14a
  (c = 1460, first gate 2 mm, 805 and 403 gates both landing on 100 mm);
- the depth budget ``P_max = c x T_prf / 2`` — docs/08 §3 (150 mm at 200 us,
  93.75 mm at 125 us, hence "a 100 mm window needs T_prf >= 134 us");
- the profile count and the block cap — docs/16 §15 item 3 and §15b (a point is
  defined in seconds; ``profiles = T / period`` is derived and must fit the cap,
  or the block wraps and the stored file covers only its last
  ``cap x period`` seconds while still decoding as valid).
"""

from __future__ import annotations

import pytest

from udv_echo_process.acquire.config import (
    AcquisitionLimits,
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
from udv_echo_process.acquire.plan import (
    GATE_DRIFT_NOTE,
    SweepDefinition,
    assert_window_fits,
    clamp_resolution,
    depth_mm,
    fits_depth_budget,
    gate_drift,
    gates_for_depth,
    max_usable_depth_mm,
    nearest_rung_index,
    plan_point,
    plan_sweep,
    profiles_for_duration,
    resolution_for_rung,
    rung_mm,
    window_fits,
)

# --------------------------------------------------------------------- ladder


@pytest.mark.parametrize(
    ("sound_speed_ms", "expected_rung_mm"),
    [
        (1460.0, 0.12166666666666667),  # the rig's sound speed in the sweep logs
        (1500.0, 0.125),  # the simulated default: 0.125 mm per rung
        (2740.0, 0.22833333333333333),  # the echo fixtures' c
    ],
)
def test_rung_is_sound_speed_over_12000(
    sound_speed_ms: float, expected_rung_mm: float
) -> None:
    assert rung_mm(sound_speed_ms) == pytest.approx(expected_rung_mm)


def test_rung_rejects_a_nonpositive_sound_speed() -> None:
    with pytest.raises(ValueError, match="sound_speed_ms"):
        rung_mm(0.0)


@pytest.mark.parametrize(
    ("index", "expected_mm"),
    [(0, 0.125), (1, 0.25), (6, 0.875), (7, 1.0), (119, 15.0)],
)
def test_resolution_for_rung_is_the_read_back_formula(
    index: int, expected_mm: float
) -> None:
    """``(index + 1) x c / 12000`` — word 10 is the 0-based index (docs/16 §12a)."""
    assert resolution_for_rung(index, 1500.0) == pytest.approx(expected_mm)


@pytest.mark.parametrize("index", [-1, 120, 1000])
def test_resolution_for_rung_rejects_an_index_off_the_ladder(index: int) -> None:
    with pytest.raises(ValueError, match="rung index"):
        resolution_for_rung(index, 1500.0)


def test_ladder_tops_out_at_sound_speed_over_100() -> None:
    """120 rungs: the top rung is ``c / 100`` mm (docs/08 §1)."""
    limits = AcquisitionLimits()
    assert limits.max_resolution_mm(1500.0) == pytest.approx(15.0)
    assert limits.max_resolution_mm(1460.0) == pytest.approx(14.6)
    assert resolution_for_rung(119, 1500.0) == pytest.approx(
        limits.max_resolution_mm(1500.0)
    )


@pytest.mark.parametrize(
    ("requested_mm", "expected_index", "expected_mm"),
    [
        (0.05, 0, 0.125),  # below the finest rung -> clamped up
        (0.18, 0, 0.125),  # midpoint between rung 0 and rung 1 is 0.1875
        (0.19, 1, 0.25),
        (0.31, 1, 0.25),
        (0.32, 2, 0.375),  # midpoint between rung 1 and rung 2 is 0.3125
        (0.44, 3, 0.5),
        (0.55, 3, 0.5),
        (0.93, 6, 0.875),  # midpoint between rung 6 and rung 7 is 0.9375
        (0.94, 7, 1.0),
        (20.0, 119, 15.0),  # above the top -> clamped down
    ],
)
def test_snapping_is_nearest_rung_and_clamps(
    requested_mm: float, expected_index: int, expected_mm: float
) -> None:
    assert nearest_rung_index(requested_mm, 1500.0) == expected_index
    assert clamp_resolution(requested_mm, 1500.0) == pytest.approx(expected_mm)


def test_snapping_rejects_a_nonpositive_request() -> None:
    with pytest.raises(ValueError, match="resolution_mm"):
        nearest_rung_index(0.0, 1500.0)


def test_snapping_follows_a_non_default_ladder() -> None:
    """A narrower real-unit surface is expressed by overriding the limits."""
    narrow = AcquisitionLimits(max_rung_index=1)
    assert resolution_for_rung(1, 1500.0, limits=narrow) == pytest.approx(0.25)
    assert clamp_resolution(5.0, 1500.0, limits=narrow) == pytest.approx(0.25)


# ---------------------------------------------------------------- gate count


@pytest.mark.parametrize(
    ("key", "expected_resolution_mm", "expected_gates", "expected_depth_mm"),
    [
        (1, 0.121667, 781, 100.022),
        (2, 0.243333, 390, 99.9),
        (4, 0.486667, 195, 99.9),
        (8, 0.973333, 98, 100.387),
        (10, 1.216667, 78, 99.9),
        (20, 2.433333, 39, 99.9),
    ],
)
def test_plan_table_matches_the_recon_plan(
    key: int,
    expected_resolution_mm: float,
    expected_gates: int,
    expected_depth_mm: float,
) -> None:
    """docs/16 §12: c = 1460 m/s, target 100 mm, first gate 5 mm."""
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=5.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(key,),
    )
    parameters = plan_point(key, definition).parameters
    assert parameters.resolution_mm == pytest.approx(expected_resolution_mm)
    assert parameters.gates == expected_gates
    assert plan_point(key, definition).expected_depth_mm == pytest.approx(
        expected_depth_mm
    )


@pytest.mark.parametrize(
    ("key", "expected_resolution_mm", "expected_text", "expected_gates"),
    [
        (1, 0.121667, "0.122", 805),  # the validated finest-rung point
        (2, 0.243333, "0.243", 403),  # the validated second-rung point
    ],
)
def test_plan_is_clamped_and_displayed_for_the_validated_points(
    key: int,
    expected_resolution_mm: float,
    expected_text: str,
    expected_gates: int,
) -> None:
    """docs/16 §14a: c = 1460, first gate 2 mm, both points landing on 100 mm."""
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(key,),
    )
    parameters = plan_point(key, definition).parameters
    assert parameters.resolution_mm == pytest.approx(expected_resolution_mm)
    assert parameters.gates == expected_gates
    # The sidebar shows 3 decimals; the app's rounding is not a failed write.
    assert parameters.resolution_text == expected_text


def test_gate_count_is_clamped_into_the_accepted_range() -> None:
    """4..1000 measured (docs/08 §2); 1001 is clamped to 1000."""
    limits = AcquisitionLimits()
    assert gates_for_depth(0.5, 0.4, 0.121667) == limits.min_gates
    assert gates_for_depth(2000.0, 2.0, 0.121667) == limits.max_gates
    assert limits.clamp_gates(1001) == 1000
    assert limits.clamp_gates(3) == 4


def test_gate_count_rejects_an_impossible_window() -> None:
    with pytest.raises(ValueError, match="must exceed"):
        gates_for_depth(5.0, 5.0, 0.121667)
    with pytest.raises(ValueError, match="resolution_mm"):
        gates_for_depth(100.0, 2.0, 0.0)


def test_depth_law_is_first_gate_plus_gates_times_resolution() -> None:
    """Verified twice against the app's own derived depth (docs/13 §1)."""
    assert depth_mm(2.0, 100, 0.25) == pytest.approx(27.0)
    assert depth_mm(5.0, 37, 0.25) == pytest.approx(14.25)
    assert depth_mm(2.0, 805, rung_mm(1460.0)) == pytest.approx(99.941667, abs=1e-6)


# -------------------------------------------------------------- depth budget


@pytest.mark.parametrize(
    ("sound_speed_ms", "prf_us", "expected_mm"),
    [(1500.0, 200.0, 150.0), (1500.0, 125.0, 93.75), (1500.0, 134.0, 100.5)],
)
def test_max_usable_depth_is_the_unambiguous_reach(
    sound_speed_ms: float, prf_us: float, expected_mm: float
) -> None:
    """``P_max = c x T_prf / 2`` with PRF as a period in us (docs/08 §3)."""
    assert max_usable_depth_mm(sound_speed_ms, prf_us) == pytest.approx(expected_mm)


def test_depth_budget_rejects_a_nonpositive_prf() -> None:
    with pytest.raises(ValueError, match="prf_us"):
        max_usable_depth_mm(1500.0, 0.0)


def test_depth_budget_decides_whether_a_window_fits() -> None:
    """At 125 us a 100 mm window does not fit: 93.75 mm is the reach."""
    at_200 = ParameterSet(
        sound_speed_ms=1500.0, first_gate_mm=2.0, resolution_mm=1.0, gates=98,
        prf_us=200.0,
    )
    at_125 = ParameterSet(
        sound_speed_ms=1500.0, first_gate_mm=2.0, resolution_mm=1.0, gates=98,
        prf_us=125.0,
    )
    assert fits_depth_budget(at_200) is True
    assert fits_depth_budget(at_125) is False
    # One gate too many at 200 us: 152 mm > 150 mm, which is the silent trim.
    too_many = ParameterSet(
        sound_speed_ms=1500.0, first_gate_mm=2.0, resolution_mm=15.0, gates=10,
        prf_us=200.0,
    )
    assert fits_depth_budget(too_many) is False


def test_depth_budget_needs_the_prf_period() -> None:
    """Without the period the budget is unknown: refuse, do not guess."""
    parameters = ParameterSet(
        sound_speed_ms=1500.0, first_gate_mm=2.0, resolution_mm=1.0, gates=98
    )
    with pytest.raises(ValueError, match="prf_us"):
        fits_depth_budget(parameters)


@pytest.mark.parametrize(
    ("requested", "readback", "expected_drift"),
    [
        (805, 474, 0.4111801242236025),  # the wrong write order's silent trim
        (403, 403, 0.0),
        (100, 200, -1.0),  # the app raised the count instead
    ],
)
def test_gate_drift_measures_the_read_back_move(
    requested: int, readback: int, expected_drift: float
) -> None:
    assert gate_drift(requested, readback) == pytest.approx(expected_drift)


@pytest.mark.parametrize(
    ("requested", "readback", "expected_clamped"),
    [(805, 474, True), (403, 403, False), (805, 750, True), (805, 790, False)],
)
def test_gate_drift_note_threshold(
    requested: int, readback: int, expected_clamped: bool
) -> None:
    """The reference implementation noted a move beyond 5 % of the request."""
    assert (
        abs(gate_drift(requested, readback)) > GATE_DRIFT_NOTE
    ) is expected_clamped


def test_gate_drift_rejects_a_nonpositive_request() -> None:
    with pytest.raises(ValueError, match="requested_gates"):
        gate_drift(0, 10)


# ------------------------------------------------- profiles and the block cap


@pytest.mark.parametrize(
    ("duration_s", "period_s", "expected_profiles"),
    [
        (1.5, 0.0212, 71),  # 1.5 s at the measured 21.2 ms period
        (4.0, 0.0212, 189),
        (6.0, 0.0212, 284),
        (5.0, 0.01, 500),
        (5.0, 0.011, 455),  # rounds up: a cap check must not undershoot
    ],
)
def test_profiles_are_derived_from_the_window_and_the_period(
    duration_s: float, period_s: float, expected_profiles: int
) -> None:
    assert profiles_for_duration(duration_s, period_s) == expected_profiles


@pytest.mark.parametrize(
    ("duration_s", "period_s"), [(0.0, 0.02), (-1.0, 0.02), (1.0, 0.0), (1.0, -0.1)]
)
def test_profiles_reject_a_nonpositive_input(duration_s: float, period_s: float) -> None:
    with pytest.raises(ValueError):
        profiles_for_duration(duration_s, period_s)


def test_window_fits_the_cap_or_wraps() -> None:
    """A 1.5 s point fits a 10000-profile cap; a 6 s point does not fit 100."""
    assert window_fits(1.5, 0.0212, 10_000) is True
    assert window_fits(6.0, 0.0212, 100) is False
    assert assert_window_fits(1.5, 0.0212, 10_000) == 71


def test_assert_window_fits_explains_the_ring_that_would_cover_the_window() -> None:
    """docs/16 §15b: the block wraps, so the point would silently be shorter."""
    with pytest.raises(ValueError) as excinfo:
        assert_window_fits(6.0, 0.0212, 100)
    message = str(excinfo.value)
    assert "284 profiles" in message
    assert "100" in message
    assert "2.120 s" in message  # cap x period: what the file would really cover


# ------------------------------------------------------------ whole sweep plan


def test_plan_sweep_expands_the_rung_list_in_order() -> None:
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(1, 2, 4, 8, 10, 20),
        prf_us=200.0,
    )
    points = plan_sweep(definition)
    assert [point.key for point in points] == [1, 2, 4, 8, 10, 20]
    # k is the 1-based rung index, so the file reports res_idx = k - 1.
    assert [point.rung_index for point in points] == [0, 1, 3, 7, 9, 19]
    assert points[0].parameters.gates == 805
    assert points[0].expected_profiles(0.0212) == 189
    assert all(point.duration_s == 4.0 for point in points)


def test_plan_sweep_rejects_a_point_the_app_would_silently_trim() -> None:
    """Plan-time, not discovery-time: a 100 mm window needs T_prf >= 134 us."""
    too_deep = SweepDefinition(
        sound_speed_ms=1500.0,
        first_gate_mm=2.0,
        target_depth_mm=140.0,
        duration_s=2.0,
        rungs=(1,),
        prf_us=125.0,
    )
    with pytest.raises(ValueError, match="depth budget"):
        plan_sweep(too_deep)


def test_plan_sweep_skips_the_budget_check_without_a_prf() -> None:
    definition = SweepDefinition(
        sound_speed_ms=1500.0,
        first_gate_mm=2.0,
        target_depth_mm=400.0,
        duration_s=2.0,
        rungs=(1,),
    )
    assert plan_sweep(definition)[0].parameters.prf_us is None


def test_plan_sweep_carries_the_covariates_it_was_given() -> None:
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(1,),
        prf_us=333.0,
        emissions_per_profile=44,
        burst_length=2,
    )
    parameters = plan_sweep(definition)[0].parameters
    assert parameters.prf_us == 333.0
    assert parameters.emissions_per_profile == 44
    assert parameters.burst_length == 2


@pytest.mark.parametrize(
    "rungs",
    [(), (0,), (-1, 1), (1, 1)],
)
def test_sweep_definition_rejects_a_bad_rung_list(rungs: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        SweepDefinition(
            sound_speed_ms=1460.0,
            first_gate_mm=2.0,
            target_depth_mm=100.0,
            duration_s=4.0,
            rungs=rungs,
        )


def test_sweep_definition_rejects_a_window_that_cannot_exist() -> None:
    with pytest.raises(ValueError, match="target_depth_mm"):
        SweepDefinition(
            sound_speed_ms=1460.0,
            first_gate_mm=2.0,
            target_depth_mm=2.0,
            duration_s=4.0,
            rungs=(1,),
        )


def test_rung_above_the_ladder_is_refused_not_clamped() -> None:
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(1,),
        limits=AcquisitionLimits(max_rung_index=1),
    )
    with pytest.raises(ValueError, match="ladder"):
        plan_point(3, definition)


def test_sweep_definition_exposes_its_rung() -> None:
    definition = SweepDefinition(
        sound_speed_ms=1500.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=1.5,
        rungs=(1,),
    )
    assert definition.rung_mm == pytest.approx(0.125)


# ------------------------------------------------------- the value objects


def test_parameter_set_depth_and_display_text() -> None:
    parameters = ParameterSet(
        sound_speed_ms=1460.0, first_gate_mm=2.0, resolution_mm=0.121667, gates=805
    )
    assert parameters.depth_mm == pytest.approx(99.941935, abs=1e-6)
    assert parameters.resolution_text == "0.122"


@pytest.mark.parametrize(
    "fields",
    [
        {"sound_speed_ms": 0.0, "first_gate_mm": 2.0, "resolution_mm": 0.12,
         "gates": 805},
        {"sound_speed_ms": 1460.0, "first_gate_mm": -1.0, "resolution_mm": 0.12,
         "gates": 805},
        {"sound_speed_ms": 1460.0, "first_gate_mm": 2.0, "resolution_mm": 0.0,
         "gates": 805},
        {"sound_speed_ms": 1460.0, "first_gate_mm": 2.0, "resolution_mm": 0.12,
         "gates": 0},
        {"sound_speed_ms": 1460.0, "first_gate_mm": 2.0, "resolution_mm": 0.12,
         "gates": 805, "prf_us": 0.0},
    ],
)
def test_parameter_set_rejects_impossible_values(fields: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        ParameterSet(**fields)


def test_parameter_set_is_frozen_and_forbids_extra_fields() -> None:
    parameters = ParameterSet(
        sound_speed_ms=1460.0, first_gate_mm=2.0, resolution_mm=0.121667, gates=805
    )
    with pytest.raises(ValueError):
        parameters.gates = 474  # type: ignore[misc]
    with pytest.raises(ValueError):
        ParameterSet(
            sound_speed_ms=1460.0,
            first_gate_mm=2.0,
            resolution_mm=0.121667,
            gates=805,
            sound_speed=1460.0,  # type: ignore[call-arg]
        )


def test_parameter_set_round_trips_through_json() -> None:
    parameters = ParameterSet(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        resolution_mm=0.121667,
        gates=805,
        prf_us=200.0,
    )
    assert ParameterSet.model_validate_json(parameters.model_dump_json()) == parameters


def test_limits_reject_an_inverted_gate_range() -> None:
    with pytest.raises(ValueError, match="min_gates"):
        AcquisitionLimits(min_gates=10, max_gates=4)


def test_limits_reject_a_nonpositive_rung_divisor() -> None:
    with pytest.raises(ValueError):
        AcquisitionLimits(rung_divisor=0.0)


def test_record_settings_name_every_point_uniquely() -> None:
    """docs/16 §12b: a repeat name raises the overwrite warning."""
    settings = RecordSettings(name_prefix="sw100")
    assert settings.point_name(1, "20260917T161738") == "sw100-k1-20260917T161738"
    assert settings.next_name(1, "161738", ()) == "sw100-k1-161738"
    assert (
        settings.next_name(1, "161738", {"sw100-k1-161738"}) == "sw100-k1-161738b"
    )
    assert (
        settings.next_name(
            1, "161738", {"sw100-k1-161738", "sw100-k1-161738b"}
        )
        == "sw100-k1-161738bb"
    )


def test_record_settings_rejects_an_empty_stamp_or_prefix() -> None:
    settings = RecordSettings(name_prefix="sw100")
    with pytest.raises(ValueError, match="stamp"):
        settings.point_name(1, "")
    with pytest.raises(ValueError):
        RecordSettings(name_prefix="")
    with pytest.raises(ValueError, match="whitespace"):
        RecordSettings(name_prefix="sw100 ")


def test_record_settings_defaults_state_the_cap_explicitly() -> None:
    settings = RecordSettings(name_prefix="sw100")
    assert settings.capture_dir == "capture"
    assert settings.max_profiles_per_block == 1_000_000
    with pytest.raises(ValueError):
        RecordSettings(name_prefix="sw100", max_profiles_per_block=0)


@pytest.mark.parametrize(
    ("target_s", "achieved_s", "expected"),
    [
        (0.0212, 0.0212, True),
        (1.0, 1.05, True),
        (1.0, 1.2, False),
        (None, 0.0212, False),  # an unmeasured target is not "fine"
        (0.0212, None, False),
    ],
)
def test_profile_timing_tolerance(
    target_s: float | None, achieved_s: float | None, expected: bool
) -> None:
    timing = ProfileTiming(target_s=target_s, achieved_s=achieved_s)
    assert timing.within_tolerance(0.1) is expected


def test_profile_timing_rejects_a_negative_tolerance() -> None:
    with pytest.raises(ValueError, match="rtol"):
        ProfileTiming(target_s=1.0, achieved_s=1.0).within_tolerance(-0.1)


@pytest.mark.parametrize("field", ["target_s", "achieved_s"])
def test_profile_timing_rejects_a_nonpositive_period(field: str) -> None:
    with pytest.raises(ValueError):
        ProfileTiming(**{field: 0.0})
