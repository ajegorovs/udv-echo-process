"""Offline: the jump-vs-stepped seam — the production stepped primitive, and the warp it leaves alone.

No desktop: a fake ``user32`` records every ``SetCursorPos``. These cases are the seam the live
prototype settled: a stepped plan must produce **one position per step, in order**, while the
existing single-warp ``_move_real_cursor`` must keep its own behaviour for every other consumer.
A refused plan must move nothing, and a landing that does not read back must stop the path rather
than be retried.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire.ui.menu import PathPlan, Rect, stepped_path
from udv_echo_process.acquire.win32 import cursor

BOUNDS = Rect(left=0, top=0, right=1920, bottom=1080)


class _User32:
    """The two calls the cursor layer makes, with a scriptable landing."""

    def __init__(self, *, land_exactly: bool = True) -> None:
        self.calls: list[tuple[int, int]] = []
        self.position = (0, 0)
        self.land_exactly = land_exactly

    def SetCursorPos(self, x: int, y: int) -> int:
        self.calls.append((int(x), int(y)))
        self.position = (int(x), int(y)) if self.land_exactly else (int(x), int(y) - 1)
        return 1

    def mouse_event(self, *args) -> None:  # pragma: no cover - must never be reached
        raise AssertionError("the stepped path must not send a relative move nudge")


def _walk(plan, fake: _User32, *, guard=None, notes=None):
    return cursor._move_real_cursor_stepped(
        plan,
        what="the off-popup point",
        why="a bounded stepped path",
        note=(notes if notes is not None else []).append,
        inside=lambda clip, point: True,
        clip=lambda: None,
        release=lambda: True,
        read_position=lambda: fake.position,
        guard=guard or (lambda: None),
        sleep=lambda _seconds: None,
        user32=lambda: fake,
    )


def test_a_stepped_path_issues_every_position_in_order_and_no_nudge():
    plan = stepped_path(start=(560, 32), goal=(300, 400), bounds=BOUNDS)
    assert plan.ok and len(plan.points) > 1
    fake = _User32()
    landed = _walk(plan, fake)

    assert fake.calls == [tuple(point) for point in plan.points]
    assert landed == tuple(plan.points)
    assert len(fake.calls) == len(plan.points) > 1


def test_the_per_step_guard_runs_before_every_move():
    plan = stepped_path(start=(100, 100), goal=(300, 300), bounds=BOUNDS)
    assert plan.ok
    fake = _User32()
    guards: list[int] = []

    def guard() -> None:
        guards.append(len(fake.calls))

    _walk(plan, fake, guard=guard)
    assert guards == list(range(len(plan.points)))


def test_a_refused_plan_moves_nothing():
    plan = PathPlan(
        start=(0, 0),
        goal=(10, 10),
        points=(),
        interval_s=0.0,
        distance_px=0.0,
        step_px=40,
        refusal="needs more positions than the bound allows",
    )
    fake = _User32()
    with pytest.raises(Exception) as refused:
        _walk(plan, fake)
    assert "not derived" in str(refused.value)
    assert fake.calls == []


def test_a_readback_mismatch_stops_the_path_and_is_not_retried():
    plan = stepped_path(start=(100, 100), goal=(300, 300), bounds=BOUNDS)
    fake = _User32(land_exactly=False)
    with pytest.raises(Exception) as refused:
        _walk(plan, fake)
    assert "step 1 of" in str(refused.value)
    assert "read back" in str(refused.value)
    assert len(fake.calls) == 1  # the remaining positions were not visited


def test_the_single_warp_move_is_unchanged_for_other_consumers():
    """The existing ``_move_real_cursor`` still performs exactly one ``SetCursorPos``."""
    fake = _User32()
    point = cursor._move_real_cursor(
        (400, 300),
        what="the Parameters button",
        why="the existing hover",
        note=[].append,
        inside=lambda clip, p: True,
        clip=lambda: None,
        release=lambda: True,
        read_position=lambda: fake.position,
        user32=lambda: fake,
    )
    assert point == (400, 300)
    assert fake.calls == [(400, 300)]


def test_the_stepped_primitive_sends_no_message_and_no_relative_move():
    source = inspect.getsource(cursor._move_real_cursor_stepped)
    assert "mouse_event(" not in source
    assert "PostMessage" not in source
    assert "SendMessage" not in source


def test_the_checked_bound_stops_the_path_before_the_next_move_and_names_actual_and_planned():
    from udv_echo_process.acquire.driver import AcquisitionError

    plan = stepped_path(start=(0, 0), goal=(160, 0), bounds=BOUNDS, step_px=40)
    assert plan.ok and len(plan.points) == 4
    fake = _User32()
    ticks = iter(
        [0.0, 0.0, 0.0, 5.0, 5.0]
    )  # first move lands, second check is over the bound

    with pytest.raises(AcquisitionError) as stopped:
        cursor._move_real_cursor_stepped(
            plan,
            what="the off-popup point",
            why="a bounded stepped path",
            note=[].append,
            inside=lambda clip, point: True,
            clip=lambda: None,
            release=lambda: True,
            read_position=lambda: fake.position,
            sleep=lambda _seconds: None,
            clock=lambda: next(ticks),
            checked_bound_s=1.0,
            user32=lambda: fake,
        )

    assert len(fake.calls) == 2
    message = str(stopped.value)
    assert "checked bound" in message and "rather than a hard deadline" in message
    assert "1.000 s checked" in message and "planned interval budget" in message
    assert "2 step(s) were completed" in message
