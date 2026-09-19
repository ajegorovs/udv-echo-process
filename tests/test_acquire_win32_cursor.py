"""The moved cursor and foreground mechanics, pinned at their new module boundary.

``acquire/win32/cursor.py`` owns the real-desktop half Patch 3 moved out of ``driver.py``: the
clip (``GetClipCursor``/``ClipCursor(NULL)``), the operator's cursor and its restore, the real
move the menubar hover needs, and the foreground precondition. These tests drive the module
directly through the seams it takes (a transport, the clip/position helpers, the diagnostic sink,
the clip test), with a ``user32`` whose cursor is a pair of integers — so the gesture can be read
back as a list of calls without touching anyone's desktop.

``tests/test_acquire_driver.py`` still drives the same rules through ``Win32Actuator`` with
``driver._user32`` faked; what is added here is that the rules are pinned where they now live,
and that the facade is what hands the chain its pieces.

**No claim here is a device claim.** A move that is asserted to be released from a clip is not
evidence that the instrument's popup clip behaves the same way on the day: that is
*device-pending* (``docs/dop3000/device-verification.md``).
"""

from __future__ import annotations

import ctypes
import functools
import time

import pytest

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.win32 import cursor

OPERATOR = (1234, 567)
BUTTON = 5001


# -------------------------------------------------------------------------------- the fake desktop


class FakeUser32:
    """``user32`` with a clip and a two-integer cursor — and no message calls at all.

    A missing ``SendMessageTimeoutW``/``PostMessageW`` is the point: an ``AttributeError`` is
    what says a gesture reached for messages it must not send.
    """

    def __init__(
        self,
        position: tuple[int, int] = OPERATOR,
        clip: tuple[int, int, int, int] | None = None,
        *,
        stubborn: bool = False,
        clamp: bool = True,
    ) -> None:
        self.position = tuple(position)
        self.clip = None if clip is None else tuple(clip)
        self.stubborn = stubborn
        self.clamp = clamp
        self.calls: list[tuple] = []

    def GetCursorPos(self, pointer) -> int:
        self.calls.append(("GetCursorPos",))
        point = ctypes.cast(pointer, ctypes.POINTER(cursor._CursorPoint)).contents
        point.x, point.y = self.position  # type: ignore[assignment]
        return 1

    def SetCursorPos(self, x: int, y: int) -> int:
        self.calls.append(("SetCursorPos", int(x), int(y)))
        if self.clip is None or not self.clamp:
            self.position = (int(x), int(y))
        else:
            left, top, right, bottom = self.clip
            self.position = (
                min(max(int(x), left), right),
                min(max(int(y), top), bottom),
            )
        return 1

    def GetClipCursor(self, pointer) -> int:
        self.calls.append(("GetClipCursor",))
        if self.clip is None:
            return 0
        rect = ctypes.cast(pointer, ctypes.POINTER(cursor._ClipRect)).contents
        rect.left, rect.top, rect.right, rect.bottom = self.clip  # type: ignore[assignment]
        return 1

    def ClipCursor(self, pointer) -> int:
        self.calls.append(("ClipCursor", None if pointer is None else "rect"))
        if self.stubborn:
            return 0
        self.clip = None
        return 1

    def mouse_event(self, flags, dx, dy, _data, _extra) -> None:
        self.calls.append(("mouse_event", flags, dx, dy))


def seams(user32: FakeUser32) -> dict:
    """What ``Win32Actuator`` hands the module: its own clip/position helpers over this transport."""
    transport = lambda: user32
    return {
        "clip": functools.partial(cursor._clip_rect, user32=transport),
        "release": functools.partial(cursor._release_clip, user32=transport),
        "read_position": functools.partial(cursor._cursor_position, user32=transport),
        "user32": transport,
    }


# ----------------------------------------------------------------------------------- the clip read


def test_an_empty_or_unreadable_clip_is_no_clip() -> None:
    """``GetClipCursor`` answering the screen rectangle, or nothing at all, is *not* a clip.

    An empty rectangle means the desktop is not clipped, and a host that cannot answer is not
    evidence of a locked desktop: the move's own read-back stays the authority.
    """
    assert cursor._clip_rect(user32=lambda: FakeUser32(clip=None)) is None
    assert cursor._clip_rect(user32=lambda: FakeUser32(clip=(10, 10, 10, 10))) is None

    class NoClipCall:
        def __getattr__(self, name: str):
            raise AssertionError(f"the clip read reached user32.{name}")

    assert cursor._clip_rect(user32=lambda: NoClipCall()) is None
    assert cursor._clip_rect(user32=lambda: FakeUser32(clip=(0, 0, 1920, 1080))) == (
        0,
        0,
        1920,
        1080,
    )


# ------------------------------------------------------------------------ the real cursor move


def test_a_clip_that_traps_the_move_is_released_before_the_move_and_named() -> None:
    """The live hazard: outside the clip, ``SetCursorPos`` is clamped to the edge — release first.

    The popup this application opens clips the cursor to its own rectangle, and the menubar
    button lies outside it; without the release the move lands on the popup's edge and looks
    like a cursor that "would not move".
    """
    popup = (169, 55, 401, 250)
    user32 = FakeUser32(clip=popup)
    notes: list[str] = []

    landed = cursor._move_real_cursor(
        (150, 220),
        what="the 'Parameters' button",
        why="nothing is posted to this menubar",
        note=notes.append,
        inside=driver._point_in_rect,
        **seams(user32),
    )

    assert landed == (150, 220)
    assert [call[0] for call in user32.calls[:4]] == [
        "GetClipCursor",
        "ClipCursor",
        "SetCursorPos",
        "GetCursorPos",
    ]
    assert user32.calls[1] == ("ClipCursor", None)  # released *before* the move
    assert user32.position == (150, 220)  # not clamped to the popup's edge
    assert any(str(popup) in note and "released the clip" in note for note in notes)


def test_a_clip_that_cannot_be_released_is_named_with_the_point_it_refused() -> None:
    """A stubborn clip is the application's own clamp — never reported as a locked desktop.

    Both explanations end a run, and they have different remedies: misattributing the clamp sent
    a live run looking at the wrong thing.
    """
    popup = (1200, 900, 1400, 1000)
    user32 = FakeUser32(clip=popup, stubborn=True)

    with pytest.raises(driver.AcquisitionError) as excinfo:
        cursor._move_real_cursor(
            (150, 220),
            what="the 'Parameters' button",
            why="nothing is posted to this menubar",
            note=lambda _message: None,
            inside=driver._point_in_rect,
            **seams(user32),
        )

    reason = str(excinfo.value)
    assert str(popup) in reason and "(150, 220)" in reason  # the clip and the target
    assert "not a locked or unattended desktop" in reason
    assert user32.calls.count(("ClipCursor", None)) == 2  # released and retried once
    assert user32.calls.count(("SetCursorPos", 150, 220)) == 2


def test_a_move_that_does_not_take_with_no_clip_names_the_locked_desktop() -> None:
    """The other branch, by name: nothing is clipped, so the desktop is what refused."""
    user32 = FakeUser32(clamp=False)
    user32.clip = None

    def refuse(x: int, y: int) -> int:
        user32.calls.append(("SetCursorPos", int(x), int(y)))
        return 0  # the cursor went nowhere

    user32.SetCursorPos = refuse  # type: ignore[method-assign]

    with pytest.raises(driver.AcquisitionError) as excinfo:
        cursor._move_real_cursor(
            (150, 220),
            what="the 'Parameters' button",
            why="this menubar answers nothing else",
            note=lambda _message: None,
            inside=driver._point_in_rect,
            **seams(user32),
        )

    reason = str(excinfo.value)
    assert "no cursor clip is set" in reason
    assert "locked or unattended desktop" in reason
    assert "this menubar answers nothing else" in reason  # the caller's own sentence
    assert "ClipCursor" not in [call[0] for call in user32.calls]


# ------------------------------------------------------------------------- the cursor that comes back


def test_the_operator_s_cursor_goes_back_only_after_the_clip_is_released() -> None:
    """The live run's own failure: a restore clamped into the popup's bottom-left corner."""
    popup = (169, 55, 401, 250)
    user32 = FakeUser32(position=OPERATOR, clip=popup)
    notes: list[str] = []

    cursor._restore_cursor(
        OPERATOR, note=notes.append, inside=driver._point_in_rect, **seams(user32)
    )

    assert [call[0] for call in user32.calls[:4]] == [
        "GetClipCursor",
        "ClipCursor",
        "SetCursorPos",
        "GetCursorPos",
    ]
    assert user32.position == OPERATOR  # not clamped to the popup's edge
    assert user32.clip is None
    assert any("released the clip" in note for note in notes)
    assert not any("after the restore" in note for note in notes)


def test_a_clip_that_cannot_trap_the_restore_is_left_alone() -> None:
    """A dialog is entitled to confine the cursor to itself: a containing clip is not fought."""
    clip = (100, 100, 2000, 2000)
    user32 = FakeUser32(position=OPERATOR, clip=clip)

    cursor._restore_cursor(
        OPERATOR, note=lambda _message: None, inside=driver._point_in_rect, **seams(user32)
    )

    assert [call[0] for call in user32.calls[:2]] == ["GetClipCursor", "SetCursorPos"]
    assert user32.clip == clip  # untouched
    assert user32.position == OPERATOR


def test_an_unreadable_cursor_is_refused_rather_than_taken() -> None:
    """A cursor that cannot be read cannot be put back, and that is worse than a failed point."""
    user32 = FakeUser32()

    def refuse(_pointer) -> int:
        return 0

    user32.GetCursorPos = refuse  # type: ignore[method-assign]

    with pytest.raises(driver.AcquisitionError, match="no way back"):
        cursor._cursor_position(user32=lambda: user32)


def test_a_restore_that_did_not_land_is_recorded_and_never_raised() -> None:
    """It runs from a ``finally``: masking the real failure would be worse than a stray cursor."""
    clip = (0, 0, 5000, 5000)
    user32 = FakeUser32(position=(1, 2), clip=clip)
    notes: list[str] = []

    def land_elsewhere(x: int, y: int) -> int:
        user32.calls.append(("SetCursorPos", int(x), int(y)))
        user32.position = (9, 9)  # a second clip (or the application) moved it back
        return 1

    user32.SetCursorPos = land_elsewhere  # type: ignore[method-assign]

    cursor._restore_cursor(
        OPERATOR, note=notes.append, inside=driver._point_in_rect, **seams(user32)
    )

    assert any("after the restore" in note and "(9, 9)" in note for note in notes)


# ------------------------------------------------------------------------------------ the hover


class FakeMenuBarGui:
    """``win32gui`` as far as the hover is concerned: the button's screen rectangle."""

    @staticmethod
    def GetWindowRect(_hwnd: int) -> tuple[int, int, int, int]:
        return (100, 200, 200, 240)


def test_the_hover_is_the_recipe_s_gesture_and_returns_the_centre(monkeypatch) -> None:
    """``SetCursorPos`` onto the centre, the settle, one relative ``mouse_event``, the settle."""
    user32 = FakeUser32(position=(7, 11))
    moved: list[tuple] = []
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    point = cursor._hover_centre(
        BUTTON,
        what="the 'Parameters' button",
        why="this menubar answers nothing else, so nothing is posted to it",
        move=lambda position, **kwargs: moved.append((position, kwargs)) or position,
        gui=lambda: (FakeMenuBarGui, None),
        user32=lambda: user32,
    )

    assert point == (150, 220)  # the button's centre, in screen coordinates
    assert moved == [
        (
            (150, 220),
            {
                "what": "the 'Parameters' button",
                "why": "this menubar answers nothing else, so nothing is posted to it",
            },
        )
    ]
    assert user32.calls == [
        ("mouse_event", cursor.MOUSEEVENTF_MOVE, cursor._HOVER_MOVE_DX, cursor._HOVER_MOVE_DY)
    ]


def test_the_hover_names_no_surface_and_presses_nothing() -> None:
    """The words the step is reported with are the caller's; the gesture posts no message.

    ``mock_user32`` deliberately has no ``PostMessageW``: an ``AttributeError`` is what a posted
    press on this path would look like, which is the one thing the menubar is known to ignore.
    """
    user32 = FakeUser32()
    asked: list[tuple] = []

    def move(position: tuple[int, int], **kwargs: object) -> tuple[int, int]:
        asked.append((position, kwargs))
        return position

    cursor._hover_centre(
        BUTTON,
        what="the control at (204, 40)",
        why="nothing is posted to it",
        move=move,
        gui=lambda: (FakeMenuBarGui, None),
        user32=lambda: user32,
    )

    assert asked[0][1] == {"what": "the control at (204, 40)", "why": "nothing is posted to it"}
    assert "Parameters" not in asked[0][1]["what"]  # no UDOP surface name lives in this package
    assert [call[0] for call in user32.calls] == ["mouse_event"]


# ----------------------------------------------------------------------- the foreground precondition


def test_the_precondition_asks_the_facade_and_activates_through_it() -> None:
    """Both steps are the caller's own methods: a fake that scripts the foreground is honoured."""
    activations: list[int] = []
    foreground = [0xC0DE, 0xC0DE, BUTTON]

    cursor._require_foreground(
        BUTTON,
        "TMain_Scr",
        foreground=lambda: foreground.pop(0),
        activate=activations.append,
        gui=lambda: (FakeMenuBarGui, None),
    )

    assert activations == [BUTTON]  # asked for the foreground exactly once
    assert foreground == []  # and read back until it took


def test_the_precondition_refuses_naming_what_is_in_front(monkeypatch) -> None:
    """Measured live 2026-09-17: an inactive window ignores hover, and the failure looks like a
    broken gesture — so it is a named precondition, and the refusal names the window in front."""
    monkeypatch.setattr(cursor, "_FOREGROUND_WAIT_S", 0.0)  # the wait expires immediately
    monkeypatch.setattr(cursor, "_FOREGROUND_POLL_S", 0.0)

    class Gui:
        @staticmethod
        def GetClassName(_hwnd: int) -> str:
            return "ConsoleWindowClass"

    with pytest.raises(driver.AcquisitionError) as excinfo:
        cursor._require_foreground(
            BUTTON,
            "TMain_Scr",
            foreground=lambda: 0xC0DE,
            activate=lambda _hwnd: None,  # the foreground lock refuses it
            gui=lambda: (Gui, None),
        )

    reason = str(excinfo.value)
    assert "TMain_Scr" in reason  # the class the caller is looking for
    assert "0xc0de" in reason and "ConsoleWindowClass" in reason  # what is in front
    assert "foreground lock" in reason


def test_activating_a_window_attaches_to_the_thread_that_owns_it_and_detaches() -> None:
    """``SetForegroundWindow`` from a background process is refused unless the input is attached."""
    class User32:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def GetForegroundWindow(self) -> int:
            return 0xC0DE

        def GetWindowThreadProcessId(self, hwnd, owner) -> None:
            owner._obj.value = 111 if hwnd.value == 0xC0DE else 222  # the front window, the app

        def AttachThreadInput(self, one: int, other: int, attach: bool) -> int:
            self.calls.append(("AttachThreadInput", one, other, attach))
            return 1

        def SetForegroundWindow(self, hwnd) -> int:
            self.calls.append(("SetForegroundWindow", hwnd.value))
            return 1

    user32 = User32()
    cursor._activate_window(BUTTON, user32=lambda: user32)

    assert user32.calls == [
        ("AttachThreadInput", 111, 222, True),
        ("SetForegroundWindow", BUTTON),
        ("AttachThreadInput", 111, 222, False),
    ]


# ------------------------------------------------------------------ the facade still owns the seams


def test_the_facade_re_exports_the_moved_cursor_names() -> None:
    """``driver.X is win32.cursor.X`` — the compatibility import, as an identity."""
    assert driver._cursor_position is cursor._cursor_position
    assert driver._restore_cursor is cursor._restore_cursor
    assert driver._move_real_cursor is cursor._move_real_cursor
    assert driver._hover_centre is cursor._hover_centre
    assert driver._require_foreground is cursor._require_foreground
    assert driver._activate_window is cursor._activate_window
    assert driver._thread_of is cursor._thread_of
    assert driver._clip_rect is cursor._clip_rect
    assert driver._release_clip is cursor._release_clip
    assert driver._gui is cursor._gui
    assert driver._user32 is cursor._user32
    assert driver._CursorPoint is cursor._CursorPoint
    assert driver._ClipRect is cursor._ClipRect


def test_the_facade_hands_the_chain_its_own_methods(monkeypatch) -> None:
    """The three helpers the restore is composed of are the **facade's**, not the module's.

    A driver subclass that overrides ``_cursor_position`` — as this repository's fakes do — is
    still the thing asked where the operator's cursor is.
    """
    asked: list[str] = []
    user32 = FakeUser32(position=OPERATOR, clip=None)
    monkeypatch.setattr(driver, "_user32", lambda: user32)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    actuator = driver.Win32Actuator(channel=1)
    monkeypatch.setattr(
        actuator, "_cursor_position", lambda: asked.append("read") or OPERATOR
    )
    monkeypatch.setattr(actuator, "_clip_rect", lambda: asked.append("clip") or None)

    actuator._restore_cursor(OPERATOR)

    assert asked == ["clip"]  # the deictic helpers were consulted, the module's were not
    assert user32.position == OPERATOR
