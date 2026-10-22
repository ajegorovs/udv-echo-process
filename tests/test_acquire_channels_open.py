"""Offline: ``ParametersSurface.open_channels_popup`` — the one geometry-derived stepped entry.

No desktop. The surface's binding, foreground, cursor and geometry seams are recorded fakes, so
the assertions are about the **sequence**: an already-readable popup is adopted with no movement,
an ``ABSENT`` screen is entered by the production planner and cursor owner (a park below the band,
then 4 px positions along the anchor's column), and the walk stops on the first readable popup —
never a hover, never a relative move, never a retry.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire import driver as _driver  # noqa: F401  (cycle break)
from udv_echo_process.acquire.udop import parameters
from udv_echo_process.acquire.ui.channels import ChannelsSurface
from udv_echo_process.acquire.ui.menu import (
    ENTRY_STEP_PX,
    MEASURED_BAR,
    Obstacle,
    approach_park,
    entry_checked_bound_s,
    entry_plan,
)
from udv_echo_process.acquire.ui.model import Rect

BAND = Rect(left=0, top=23, right=1920, bottom=55)
CLIENT = Rect(left=0, top=23, right=1920, bottom=1050)
SCREEN = Rect(left=0, top=0, right=1920, bottom=1080)

#: The measured geometry of ``channels-stepped-entry-live-03``: the Channels button is entry 8
#: of the ten-entry bar at (526, 28, 596, 53); the production park is (561, 68) and the run is
#: 7 positions of 4 px up the anchor's column, first entering the button at step 4 — (561, 52).
ANCHOR = Rect(left=526, top=28, right=596, bottom=53)
MEASURED_ANCHOR_INDEX = MEASURED_BAR.index("Channels")
MEASURED_LEFT = 526


def _row(cls: str, rect: Rect, hwnd: int) -> dict:
    return {
        "cls": cls,
        "left": rect.left,
        "top": rect.top,
        "w": rect.width,
        "h": rect.height,
        "hwnd": hwnd,
    }


def _button_rect(index: int) -> Rect:
    # The measured bar's own spacing: Channels starts at 526 as the eighth of ten entries.
    left = MEASURED_LEFT + 60 * (index - MEASURED_ANCHOR_INDEX)
    return Rect(left=left, top=28, right=left + 70, bottom=53)


def _roles() -> dict:
    return {
        "window": 4242,
        "client": (CLIENT.width, CLIENT.height),
        "origin": (CLIENT.left, CLIENT.top),
        "class_name": "TMain_Scr",
        "raw": [],
        "panels": [],
        "parent_of": {},
        "menu_band": _row("TSp_Panel", BAND, 9),
        "menu": {},
        "menu_buttons": [
            _row("TSp_Button", _button_rect(i), 1000 + i)
            for i in range(len(MEASURED_BAR))
        ],
    }


def _read(surface: ChannelsSurface, *, readable: bool = True):
    return SimpleNamespace(surface=surface, readable=readable, popup=None, refusals=())


class _Screen:
    """A desktop double: one position, one surface, and an enter-only flip.

    The measured application rule: the popup opens when the pointer **enters** the anchor's
    rect in a small step. A position outside the anchor carries nothing, and a single long jump
    into it is not the stepped gesture (``require_step`` models that boundary).
    """

    def __init__(
        self,
        start: tuple[int, int],
        *,
        open_surface: ChannelsSurface = ChannelsSurface.SETTINGS_POPUP,
        readable: bool = True,
        flip: bool = True,
        require_step: bool = True,
    ) -> None:
        self.position = tuple(start)
        self.surface = ChannelsSurface.ABSENT
        self.open_surface = open_surface
        self.readable = readable
        self.flip = flip
        self.require_step = require_step
        self.flip_at: tuple[int, int] | None = None

    def move(self, point: tuple[int, int]) -> tuple[int, int]:
        previous, self.position = self.position, tuple(point)
        if (
            self.flip
            and self.surface is ChannelsSurface.ABSENT
            and ANCHOR.contains_point(self.position)
            and (
                not self.require_step
                or abs(self.position[1] - previous[1]) <= ENTRY_STEP_PX
            )
        ):
            self.surface = self.open_surface
            self.flip_at = self.position
        return self.position

    def read(self):
        return _read(self.surface, readable=self.readable)


class _Surface(parameters.ParametersSurface):
    def __init__(self, screen: _Screen) -> None:
        self.roles = _roles()
        self.screen = screen
        self.cursor = screen.position
        self.parks: list[tuple[int, int]] = []
        self.plans: list[object] = []
        self.checked: list[int] = []
        self.notes: list[str] = []
        self.stepped_calls: list[dict] = []

    # -- dependencies -------------------------------------------------
    def verify_bound_target(self, expected):
        return expected

    def _require_foreground(self, hwnd: int) -> None:
        return None

    def _check_foreground(self, hwnd: int, class_name: str = "application") -> None:
        self.checked.append(hwnd)

    def _resolve(self) -> dict:
        return self.roles

    def _cursor_position(self) -> tuple[int, int]:
        return self.cursor

    def _screen_rect(self) -> Rect:
        return SCREEN

    def _move_real_cursor(self, point, *, what: str, why: str):
        self.parks.append((int(point[0]), int(point[1])))
        self.cursor = self.screen.move(point)
        return self.cursor

    def _move_real_cursor_stepped(
        self,
        plan,
        *,
        what: str,
        why: str,
        guard=None,
        checked_bound_s=None,
        observe=None,
    ):
        self.plans.append(plan)
        self.stepped_calls.append(
            {"what": what, "checked_bound_s": checked_bound_s, "why": why}
        )
        landed: list[tuple[int, int]] = []
        for point in plan.points:
            if guard is not None:
                guard()
            self.cursor = self.screen.move(point)
            landed.append(self.cursor)
            if observe is not None and observe(self.cursor):
                break
        return tuple(landed)

    def _hover_centre(
        self, *args, **kwargs
    ):  # pragma: no cover - must never be reached
        raise AssertionError("opening the Channels popup no longer hovers")

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def _post(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("opening the popup must not post a message")


def _open(surface: _Surface, *, timeout_s: float = 0.0):
    return surface.open_channels_popup(
        target=SimpleNamespace(hwnd=4242),
        read=surface.screen.read,
        timeout_s=timeout_s,
    )


# ------------------------------------------------------------------ adoption and the absent start


def test_an_already_readable_popup_is_adopted_without_movement():
    screen = _Screen((5, 900), open_surface=ChannelsSurface.SETTINGS_POPUP)
    screen.surface = ChannelsSurface.SETTINGS_POPUP
    surface = _Surface(screen)

    result = _open(surface)

    assert result.outcome is parameters.PopupOutcome.OPEN
    assert result.adopted is True
    assert result.point is None
    assert surface.parks == [] and surface.plans == []


def test_an_absent_screen_is_entered_by_the_derived_column_and_opened():
    surface = _Surface(_Screen((390, 600)))
    result = _open(surface, timeout_s=1.0)

    assert result.outcome is parameters.PopupOutcome.OPEN
    assert result.adopted is False
    # One park, then the production planner's positions — never a hover.
    assert surface.parks == [(561, 68)]
    assert len(surface.plans) == 1
    assert result.point == (561, 52)
    assert result.initial_cursor == (390, 600)
    assert result.pre_move["from"] == [390, 600]
    assert result.pre_move["to"] == [561, 68]
    assert result.pre_move["confirmed_surface"] == "absent"


def test_the_measured_geometry_enables_the_first_enter_on_step_four():
    """The real geometry boundary: 4 px column steps enter on step 4, a warp does not.

    The plan is the measured one — park (561, 68), 7 positions to the anchor centre (561, 40) —
    and the first position inside the anchor's rect (526, 28, 596, 53) is step 4 at (561, 52).
    A single jump from the park to the centre is 28 px, so it is not a step of this gesture and
    the enter-only model does not flip on it.
    """
    entry = entry_plan(
        anchor=ANCHOR,
        band=BAND,
        obstacles=[],
        client=CLIENT,
        screen=SCREEN,
    )
    assert entry.ok, entry.refusal
    plan = entry.plan
    assert plan.points == (
        (561, 64),
        (561, 60),
        (561, 56),
        (561, 52),
        (561, 48),
        (561, 44),
        (561, 40),
    )
    first_inside = next(
        index
        for index, point in enumerate(plan.points, start=1)
        if ANCHOR.contains_point(point)
    )
    assert first_inside == 4
    assert plan.points[3] == (561, 52)
    # Every step is 4 px and the direct park -> centre jump is 28 px: not this gesture.
    assert abs(plan.points[3][1] - plan.points[2][1]) == ENTRY_STEP_PX
    assert abs(ANCHOR.centre[1] - 68) == 28 > ENTRY_STEP_PX

    surface = _Surface(_Screen((561, 68)))
    result = _open(surface, timeout_s=1.0)

    assert result.outcome is parameters.PopupOutcome.OPEN
    assert result.entry["positions_requested"] == 7
    assert result.entry["positions_landed"] == [
        [561, 64],
        [561, 60],
        [561, 56],
        [561, 52],
    ]
    assert result.entry["first_flip"]["step"] == 4
    assert result.entry["first_flip"]["point"] == [561, 52]
    assert result.entry["positions_walked"] == 4  # nothing past the flip is visited


def test_a_direct_warp_into_the_anchor_is_not_this_gesture():
    screen = _Screen((561, 68), require_step=True)
    screen.move(ANCHOR.centre)  # a warp, not a 4 px step
    assert screen.surface is ChannelsSurface.ABSENT


# ------------------------------------------------------------------ the derived geometry refuses


def test_the_park_is_below_the_whole_band_on_the_anchors_own_column():
    park = approach_park(anchor=ANCHOR, band=BAND, client=CLIENT, screen=SCREEN)
    assert park.ok, park.clause
    assert park.point == (561, 68)
    assert park.point[0] == ANCHOR.centre[0]
    assert park.point[1] == BAND.bottom + 13


def test_an_obstacle_on_the_column_is_refused_before_anything_moves():
    hedge = Obstacle(name="Display", rect=Rect(left=540, top=30, right=590, bottom=40))
    entry = entry_plan(
        anchor=ANCHOR,
        band=BAND,
        obstacles=[hedge],
        client=CLIENT,
        screen=SCREEN,
    )
    assert not entry.ok
    assert "Display" in entry.refusal
    assert entry.plan is not None and entry.plan.points == ()


def test_a_client_with_no_room_below_the_band_is_refused_by_name():
    short = Rect(left=0, top=23, right=1920, bottom=55)
    park = approach_park(anchor=ANCHOR, band=BAND, client=short, screen=SCREEN)
    assert park.point is None
    assert "nothing is moved" in park.clause
    assert str(BAND.as_tuple()) in park.clause


def test_a_client_and_screen_with_no_overlap_are_refused():
    detached = Rect(left=5000, top=5000, right=6000, bottom=6000)
    park = approach_park(anchor=ANCHOR, band=BAND, client=detached, screen=SCREEN)
    assert park.point is None
    assert "do not overlap" in park.clause


def test_an_unprovable_entry_geometry_refuses_before_the_park():
    screen = _Screen((390, 600))
    surface = _Surface(screen)
    surface.roles = {**surface.roles, "client": (1920, 30)}  # no room below the band

    with pytest.raises(parameters.AcquisitionError) as refused:
        _open(surface)

    assert "bounded stepped entry cannot be derived" in str(refused.value)
    assert "nothing is moved" in str(refused.value)
    assert surface.parks == [] and surface.plans == []
    assert surface.last_channels_entry["ok"] is False
    assert surface.last_channels_entry["refusal"]


# ------------------------------------------------------------------ no retry, typed outcomes


def test_no_flip_walks_the_whole_plan_and_answers_unknown_without_a_second_path():
    surface = _Surface(_Screen((390, 600), flip=False))
    result = _open(surface)

    assert result.outcome is parameters.PopupOutcome.UNKNOWN
    assert len(surface.plans) == 1  # one path, never a retry
    assert surface.parks == [(561, 68)]  # one park, never a second
    assert result.entry["positions_walked"] == 7
    assert result.entry["first_flip"] is None
    assert result.entry["surfaces"] == ["absent"] * 7
    assert "actual elapsed" in result.clause
    assert "UNKNOWN" in result.clause


def test_an_unintended_surface_at_a_step_refuses_and_is_not_retried():
    surface = _Surface(_Screen((390, 600), open_surface=ChannelsSurface.WRONG_SURFACE))
    with pytest.raises(parameters.AcquisitionError) as refused:
        _open(surface)

    assert "stepped entry" in str(refused.value)
    assert "another surface was entered" in str(refused.value)
    assert len(surface.plans) == 1
    assert surface.parks == [(561, 68)]
    assert surface.checked  # identity + foreground were re-asserted per step


def test_a_guard_refusal_mid_path_keeps_the_partial_record():
    screen = _Screen((390, 600))
    surface = _Surface(screen)
    calls = {"n": 0}

    original = surface._check_foreground

    def failing_guard(hwnd: int, class_name: str = "application") -> None:
        calls["n"] += 1
        if calls["n"] >= 4:  # the park check, then steps 1-3
            raise RuntimeError("foreground changed mid-path")
        original(hwnd, class_name)

    surface._check_foreground = failing_guard

    with pytest.raises(parameters.AcquisitionError) as refused:
        _open(surface)

    assert "stopped after" in str(refused.value)
    assert "not retried" in str(refused.value)
    assert len(surface.last_channels_entry["positions_landed"]) == 2
    assert surface.last_channels_entry["error"].startswith("RuntimeError")
    assert len(surface.plans) == 1  # the path stopped, it was not restarted


# ------------------------------------------------------------------ unchanged surfaces


def test_the_generic_parameters_hover_has_no_entry_step():
    source = inspect.getsource(parameters.ParametersSurface._open_parameters_dialog)
    assert "entry_plan" not in source
    assert "approach_park" not in source
    assert "_park_off_anchor" not in source


def test_the_opener_posts_no_message_and_sends_no_relative_move():
    source = inspect.getsource(parameters.ParametersSurface.open_channels_popup)
    for forbidden in (
        "mouse_event",
        "PostMessage",
        "SendMessage",
        "WM_CLOSE",
        "keybd_event",
    ):
        assert forbidden not in source


def test_the_checked_bound_states_its_own_read_allowance():
    # 7 positions, the production 2 s interval budget, one 0.05 s popup read per position and
    # the production per-step work: the bound is not the interval budget alone.
    bound = entry_checked_bound_s(7)
    assert bound == pytest.approx(2.0 + 7 * (0.05 + 0.05), abs=1e-6)
    assert bound > 2.0
