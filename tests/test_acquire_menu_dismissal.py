"""Offline: the shared real-cursor dismissal primitive and its one lifecycle owner.

No window, no cursor and no popup reach the desktop. The geometry cases are :class:`Rect`
arithmetic; the lifecycle cases drive ``ParametersSurface.dismiss_channels_popup`` through a
surface whose move, foreground, binding and screen seams are recorded fakes, so the assertions are
about the *sequence* — one move, no restore, no message, no second move — and not about a double.

The behaviour these lock in: one real-cursor move off the popup, followed by a bounded read that
only an observed ``ABSENT`` satisfies. It is **not** a measured close — ``recon/35_capture_probe.py``
establishes the hover-open and an entry press consuming the popup, and one live move-off attempt
read its point back exactly while the popup stayed up. The point is derived from live rectangles;
there is no ``(20, 400)`` and no topic press anywhere on this path.
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
    DISMISSAL_CLEARANCE_PX,
    MEASURED_BAR,
    dismissal_clause,
    dismissal_point,
)
from udv_echo_process.acquire.ui.model import Rect, UiNode

POPUP = Rect(left=169, top=55, right=401, bottom=250)
BAND = Rect(left=0, top=18, right=1200, bottom=48)
CLIENT = Rect(left=0, top=0, right=1280, bottom=1000)
SCREEN = Rect(left=0, top=0, right=1920, bottom=1080)


def _row(cls: str, rect: Rect, hwnd: int) -> dict:
    return {
        "cls": cls,
        "left": rect.left,
        "top": rect.top,
        "w": rect.width,
        "h": rect.height,
        "hwnd": hwnd,
    }


def _roles() -> dict:
    return {
        "window": 4242,
        "client": (CLIENT.width, CLIENT.height),
        "origin": (CLIENT.left, CLIENT.top),
        "class_name": "TSp_FormFrm",
        "raw": [],
        "panels": [],
        "parent_of": {},
        "menu_band": _row("TSp_Panel", BAND, 9),
        "menu": {},
        "menu_buttons": [
            _row(
                "TSp_Button",
                Rect(
                    left=60 + 55 * index,
                    top=20,
                    right=60 + 55 * index + 45,
                    bottom=44,
                ),
                1000 + index,
            )
            for index in range(len(MEASURED_BAR))
        ],
    }


def _reading(
    surface: ChannelsSurface = ChannelsSurface.SETTINGS_POPUP, popup: Rect = POPUP
):
    return SimpleNamespace(
        surface=surface,
        popup=UiNode(cls="TSp_Panel", rect=popup, hwnd=77),
        per_channel=SimpleNamespace(
            profiles=SimpleNamespace(text="50", value=50, hwnd=1, owner_hwnd=2),
            seconds=SimpleNamespace(text="2.01", value=2.01, hwnd=3, owner_hwnd=4),
        ),
        repeat=SimpleNamespace(text="2", value=2, hwnd=5, owner_hwnd=6),
        start_channel=SimpleNamespace(text="1", value=1, hwnd=7, owner_hwnd=8),
        apply_from=SimpleNamespace(text="1", value=1, hwnd=9, owner_hwnd=10),
    )


class _Surface(parameters.ParametersSurface):
    """A ``ParametersSurface`` with every desktop seam recorded and no transport at all."""

    def __init__(self, roles: dict | None = None, screen: Rect = SCREEN) -> None:
        self.roles = roles if roles is not None else _roles()
        self.screen = screen
        self.verified: list = []
        self.foreground: list[int] = []
        self.plans: list = []
        self.guards = 0
        self.position = (
            560,
            32,
        )  # the pointer the opener would have left on the anchor
        self.notes: list[str] = []

    def verify_bound_target(self, expected):
        self.verified.append(expected)
        return expected

    def _require_foreground(self, hwnd: int) -> None:
        self.foreground.append(hwnd)

    def _check_foreground(self, hwnd: int, class_name: str = "application") -> None:
        self.foreground.append(hwnd)

    def _resolve(self) -> dict:
        return self.roles

    def _screen_rect(self) -> Rect:
        return self.screen

    def _move_real_cursor(self, point, *, what, why):
        raise AssertionError(
            "the dismissal must walk the stepped primitive, not one warp"
        )

    def _move_real_cursor_stepped(self, plan, *, what, why, guard=None, **kwargs):
        self.plans.append(plan)
        landed = []
        for point in plan.points:
            self.guards += 1
            if guard is not None:
                guard()
            landed.append(point)
        return tuple(landed)

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def _cursor_position(self):
        return self.position

    def _restore_cursor(self, position):  # pragma: no cover - must never be reached
        raise AssertionError("the dismissal must not restore the operator's cursor")

    def _post(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the dismissal must not post a message")

    def _send(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the dismissal must not send a message")


# ------------------------------------------------------------------ the pure geometry


def test_dismissal_point_is_derived_and_clears_the_popup_and_the_menubar():
    point = dismissal_point(popup=POPUP, band=BAND, client=CLIENT, screen=SCREEN)
    assert point is not None
    x, y = point
    # Below the popup, on its centre line: the popup is 169..401 and its bottom is 250.
    assert (x, y) == (285, 263)
    assert not POPUP.contains_point(point)
    assert not BAND.contains_point(point)
    assert CLIENT.contains_point(point) and SCREEN.contains_point(point)
    # The archive's behavioural probe used a literal; this rule must never reproduce it.
    assert point != (20, 400)


def test_dismissal_point_prefers_a_side_when_the_client_has_no_room_below():
    short = Rect(left=0, top=0, right=1280, bottom=260)
    point = dismissal_point(popup=POPUP, band=BAND, client=short, screen=SCREEN)
    assert point is not None
    x, _y = point
    assert not POPUP.contains_point(point) and not BAND.contains_point(point)
    assert short.contains_point(point)
    assert x == POPUP.right + DISMISSAL_CLEARANCE_PX + 1


def test_dismissal_point_refuses_when_the_popup_leaves_no_pixel():
    huge = Rect(left=0, top=0, right=1280, bottom=1000)
    assert dismissal_point(popup=huge, band=BAND, client=CLIENT, screen=SCREEN) is None
    clause = dismissal_clause(popup=huge, band=BAND, client=CLIENT, screen=SCREEN)
    assert clause is not None
    assert "no point" in clause
    assert str(huge.as_tuple()) in clause
    assert str(BAND.as_tuple()) in clause


def test_dismissal_point_refuses_when_the_client_and_screen_do_not_overlap():
    detached = Rect(left=5000, top=5000, right=6000, bottom=6000)
    assert (
        dismissal_point(popup=POPUP, band=BAND, client=detached, screen=SCREEN) is None
    )
    clause = dismissal_clause(popup=POPUP, band=BAND, client=detached, screen=SCREEN)
    assert clause is not None and "do not overlap" in clause


# ------------------------------------------------------------------ the lifecycle owner


def _dismiss(surface: _Surface, reads, *, timeout_s: float = 0.0):
    iterator = iter(reads)
    calls: list[int] = []

    def read():
        calls.append(1)
        return next(iterator)

    target = SimpleNamespace(hwnd=4242)
    result = surface.dismiss_channels_popup(
        target=target, read=read, timeout_s=timeout_s
    )
    return result, calls


def test_lifecycle_moves_once_to_an_off_popup_point_and_reports_absent():
    surface = _Surface()
    result, calls = _dismiss(surface, [_reading(), _reading(ChannelsSurface.ABSENT)])

    assert result.outcome is parameters.DismissalOutcome.ABSENT
    assert result.surface_before == "settings_popup"
    assert result.surface_after == "absent"
    assert result.cursor_restored is False
    assert len(surface.plans) == 1
    plan = surface.plans[0]
    assert plan.ok, plan.refusal
    assert len(plan.points) > 1  # a stepped path, never a single warp
    assert plan.points[-1] == result.point == plan.goal
    assert result.steps == len(plan.points)
    assert result.path_s == plan.total_s
    assert plan.start == surface.position
    assert not POPUP.contains_point(result.point)
    assert not BAND.contains_point(result.point)
    assert CLIENT.contains_point(result.point)
    assert surface.verified and set(surface.foreground) == {4242}
    assert surface.guards == len(
        plan.points
    )  # binding + foreground re-asserted per step
    assert len(calls) == 2  # the caller's reading, then one post-path read


def test_lifecycle_accepts_the_clipped_multiplexer_on_surface():
    surface = _Surface()
    result, _ = _dismiss(
        surface,
        [
            _reading(ChannelsSurface.MULTIPLEXER_ON_ENTRY),
            _reading(ChannelsSurface.ABSENT),
        ],
    )
    assert result.outcome is parameters.DismissalOutcome.ABSENT
    assert result.surface_before == "multiplexer_on_entry"


def test_a_visible_fake_stays_typed_unknown_and_is_never_retried():
    surface = _Surface()
    result, calls = _dismiss(
        surface,
        [
            _reading(),
            _reading(ChannelsSurface.SETTINGS_POPUP),
            _reading(ChannelsSurface.SETTINGS_POPUP),
        ],
    )
    assert result.outcome is parameters.DismissalOutcome.UNKNOWN
    assert result.surface_after == "settings_popup"
    assert result.clause is not None and "UNKNOWN" in result.clause
    assert len(surface.plans) == 1  # no second path
    assert (
        len(calls) == 2
    )  # the caller's read, then the bounded read that ended the poll


def test_lifecycle_refuses_a_surface_that_is_not_the_channels_popup_before_moving():
    surface = _Surface()
    with pytest.raises(Exception) as refused:
        _dismiss(surface, [_reading(ChannelsSurface.ABSENT)])
    assert "refusing to dismiss" in str(refused.value)
    assert surface.plans == []


def test_lifecycle_refuses_a_reading_without_a_popup_rect_before_moving():
    surface = _Surface()
    reading = _reading()
    reading.popup = UiNode(cls="TSp_Panel", rect=None, hwnd=77)
    with pytest.raises(Exception) as refused:
        _dismiss(surface, [reading])
    assert "no popup panel rect" in str(refused.value)
    assert surface.plans == []


def test_lifecycle_refuses_a_resolved_root_that_is_not_the_bound_target():
    roles = _roles()
    roles["window"] = 999
    surface = _Surface(roles=roles)
    with pytest.raises(Exception) as refused:
        _dismiss(surface, [_reading(), _reading(ChannelsSurface.ABSENT)])
    assert "not the run's bound target" in str(refused.value)
    assert surface.plans == []


def test_lifecycle_refuses_a_start_outside_the_walkable_bounds_before_walking():
    surface = _Surface()
    surface.position = (-50, -50)  # as if the pointer were off the application's client
    with pytest.raises(Exception) as refused:
        _dismiss(surface, [_reading(), _reading(ChannelsSurface.ABSENT)])
    assert "cannot be derived" in str(refused.value)
    assert surface.plans == []


def test_a_mid_path_readback_refusal_propagates_and_is_never_reported_as_absent():
    class _Failing(_Surface):
        def _move_real_cursor_stepped(self, plan, *, what, why, guard=None, **kwargs):
            self.plans.append(plan)
            raise RuntimeError(
                "step 3 of 13 requested (300, 200) and the cursor read back (300, 199)"
            )

    surface = _Failing()
    with pytest.raises(RuntimeError) as refused:
        _dismiss(surface, [_reading(), _reading(ChannelsSurface.ABSENT)])
    assert "read back" in str(refused.value)
    assert len(surface.plans) == 1  # the path stopped; it was not restarted


def test_lifecycle_refuses_geometry_that_leaves_no_point_before_moving():
    surface = _Surface()
    with pytest.raises(Exception) as refused:
        _dismiss(
            surface,
            [_reading(popup=CLIENT), _reading(ChannelsSurface.ABSENT)],
        )
    assert "no point" in str(refused.value)
    assert surface.plans == []


# ------------------------------------------------------------------ no message path


def test_the_dismissal_path_contains_no_post_and_no_entry_press():
    for function in (
        parameters.ParametersSurface.dismiss_channels_popup,
        dismissal_point,
        dismissal_clause,
    ):
        source = inspect.getsource(function)
        assert "PostMessage" not in source
        assert "_click_hold" not in source
        assert "_press_entry" not in source
