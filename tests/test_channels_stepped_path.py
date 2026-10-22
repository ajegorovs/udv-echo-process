"""Offline: the stepped-path planner's bounds, endpoints and refusals — no window, no cursor.

Every case here calls the exact pure function the production dismissal walks
(``udv_echo_process.acquire.ui.menu.stepped_path``). The live run is not executed
by this file; what is checked is that the path can never exceed its derived bounds, can never land
on another menubar entry, and refuses (rather than silently widening a step) when a geometry cannot
satisfy them.
"""

from __future__ import annotations

import itertools
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire.ui import menu as stepped
from udv_echo_process.acquire.ui.menu import MEASURED_BAR, dismissal_point
from udv_echo_process.acquire.ui.model import Rect

BOUNDS = Rect(left=0, top=0, right=1920, bottom=1080)


def _gaps(plan) -> list[float]:
    """Distance between consecutive walked positions, starting from the plan's own start."""
    points = [plan.start, *plan.points]
    return [math.dist(a, b) for a, b in itertools.pairwise(points)]


def test_every_step_is_within_the_forty_pixel_resolution():
    plan = stepped.stepped_path(start=(100, 100), goal=(420, 500), bounds=BOUNDS)
    assert plan.ok, plan.refusal
    # One pixel of integer-rounding slack per axis; the path is never a 40+ px jump plus more.
    assert max(_gaps(plan)) <= stepped.MAX_STEP_PX + 1.0


def test_endpoints_are_exact_and_the_start_is_not_repeated():
    plan = stepped.stepped_path(start=(100, 100), goal=(417, 503), bounds=BOUNDS)
    assert plan.ok, plan.refusal
    assert plan.points[-1] == (417, 503)
    assert plan.start == (100, 100)
    assert plan.points[0] != plan.start


def test_the_path_is_monotone_towards_the_goal():
    plan = stepped.stepped_path(start=(10, 10), goal=(350, 250), bounds=BOUNDS)
    assert plan.ok, plan.refusal
    remaining = [math.dist(point, plan.goal) for point in [plan.start, *plan.points]]
    assert remaining == sorted(remaining, reverse=True)


def test_interval_and_total_are_derived_and_within_the_two_second_bound():
    plan = stepped.stepped_path(start=(561, 40), goal=(722, 494), bounds=BOUNDS)
    assert plan.ok, plan.refusal
    assert len(plan.points) == math.ceil(plan.distance_px / stepped.MAX_STEP_PX)
    assert plan.interval_s <= stepped.MAX_INTERVAL_S
    assert plan.total_s <= stepped.MAX_PATH_SECONDS
    assert plan.interval_s == stepped.step_interval_s(len(plan.points))


def test_zero_distance_is_one_position_at_the_goal():
    plan = stepped.stepped_path(start=(300, 300), goal=(300, 300), bounds=BOUNDS)
    assert plan.ok, plan.refusal
    assert plan.points == ((300, 300),)
    assert plan.distance_px == 0.0


def test_a_step_larger_than_the_measured_resolution_is_refused():
    plan = stepped.stepped_path(
        start=(100, 100),
        goal=(400, 100),
        bounds=BOUNDS,
        step_px=stepped.MAX_STEP_PX + 1,
    )
    assert not plan.ok
    assert "40" in plan.refusal and "refused rather than walked" in plan.refusal


def test_a_non_positive_step_is_refused():
    for step_px in (0, -5):
        plan = stepped.stepped_path(
            start=(1, 1), goal=(50, 1), bounds=BOUNDS, step_px=step_px
        )
        assert not plan.ok


def test_a_goal_outside_the_walkable_bounds_is_refused():
    plan = stepped.stepped_path(start=(100, 100), goal=(2500, 100), bounds=BOUNDS)
    assert not plan.ok
    assert "goal" in plan.refusal and "outside" in plan.refusal


def test_a_start_outside_the_walkable_bounds_is_refused():
    plan = stepped.stepped_path(start=(-40, 100), goal=(100, 100), bounds=BOUNDS)
    assert not plan.ok
    assert "start" in plan.refusal


def test_an_empty_bounds_rectangle_is_refused():
    empty = Rect(left=10, top=10, right=10, bottom=10)
    plan = stepped.stepped_path(start=(10, 10), goal=(10, 10), bounds=empty)
    assert not plan.ok
    assert "empty" in plan.refusal


def test_a_position_inside_another_menubar_entry_is_refused_by_name():
    blocker = stepped.Obstacle(
        name="Plot", rect=Rect(left=280, top=180, right=320, bottom=220)
    )
    plan = stepped.stepped_path(
        start=(300, 300),
        goal=(300, 100),
        bounds=BOUNDS,
        obstacles=[blocker],
        step_px=20,
    )
    assert not plan.ok
    assert "Plot" in plan.refusal
    assert "refused" in plan.refusal


def test_the_start_position_may_sit_inside_an_entry_and_is_not_refused():
    # The pointer already rests on the anchor; demanding a different first move would be a
    # different (and less safe) experiment, so index 0 is exempt from the obstacle rule.
    anchor = stepped.Obstacle(
        name="Channels", rect=Rect(left=90, top=20, right=160, bottom=44)
    )
    plan = stepped.stepped_path(
        start=(125, 32), goal=(125, 400), bounds=BOUNDS, obstacles=[anchor]
    )
    assert plan.ok, plan.refusal


def test_a_path_beyond_the_position_bound_is_refused():
    plan = stepped.stepped_path(
        start=(0, 0),
        goal=(4100, 0),
        bounds=Rect(left=0, top=0, right=5000, bottom=5000),
    )
    assert not plan.ok
    assert "positions" in plan.refusal
    assert str(stepped.MAX_STEPS) in plan.refusal


def test_a_path_that_cannot_fit_the_time_bound_is_refused_rather_than_sped_up():
    plan = stepped.stepped_path(
        start=(0, 0),
        goal=(1200, 0),
        bounds=Rect(left=0, top=0, right=2000, bottom=1000),
        max_seconds=0.5,
    )
    assert not plan.ok
    assert "0.5" in plan.refusal


def test_step_interval_derivation_matches_the_floor_and_cap():
    assert stepped.step_interval_s(13) == stepped.MAX_INTERVAL_S
    assert stepped.step_interval_s(stepped.MAX_STEPS) == stepped.MIN_INTERVAL_S
    assert stepped.step_interval_s(stepped.MAX_STEPS + 1) == 0.0


def test_production_off_point_is_reachable_by_a_bounded_path_that_avoids_other_entries():
    """The live geometry shape: popup under the band, off-points below/right/left/above it."""
    popup = Rect(left=926, top=55, right=1319, bottom=481)
    band = Rect(left=0, top=20, right=1920, bottom=44)
    client = Rect(left=0, top=0, right=1920, bottom=1080)
    screen = Rect(left=0, top=0, right=1920, bottom=1080)
    goal = dismissal_point(popup=popup, band=band, client=client, screen=screen)
    assert goal is not None

    anchor_left = 521  # the measured Channels entry
    obstacles = [
        stepped.Obstacle(
            name=name,
            rect=Rect(
                left=100 + 60 * index, top=20, right=100 + 60 * index + 50, bottom=44
            ),
        )
        for index, name in enumerate(MEASURED_BAR)
        if name != "Channels"
    ]
    plan = stepped.stepped_path(
        start=(anchor_left + 25, 32), goal=goal, bounds=client, obstacles=obstacles
    )
    assert plan.ok, plan.refusal
    for point in plan.points:
        for obstacle in obstacles:
            assert not obstacle.rect.contains_point(point)
    assert plan.total_s <= stepped.MAX_PATH_SECONDS


def test_the_plan_is_pure_and_repeatable():
    first = stepped.stepped_path(start=(50, 50), goal=(350, 350), bounds=BOUNDS)
    second = stepped.stepped_path(start=(50, 50), goal=(350, 350), bounds=BOUNDS)
    assert first == second


def test_a_refused_plan_carries_no_positions():
    plan = stepped.stepped_path(start=(100, 100), goal=(2500, 100), bounds=BOUNDS)
    assert plan.points == ()
    assert plan.total_s == 0.0
