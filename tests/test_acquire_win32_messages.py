"""The moved message mechanics, pinned at their **new** module boundary.

``acquire/win32/messages.py`` owns the transport that Patch 3 moved out of ``driver.py``: the
bounded send, the posted held click, the text commit, the combo select and the combo read-back.
These tests drive that module directly, through the seams it takes as parameters (a transport, a
handle resolution, a post), so the *recipe* is pinned where it now lives as well as through the
facade (``tests/test_acquire_driver.py`` still drives ``Win32Actuator._set_text_commit`` and
``_click_hold`` with ``driver._post``/``driver._gui`` faked).

**No claim here is a device claim.** A message sequence that is asserted to be the committed one
is not evidence that the instrument still commits a field through it: that stays
*device-pending* (``docs/dop3000/device-verification.md``). What is pinned is that the
statements moved unchanged and that the order, the flags, the holds and the coordinate space are
the ones the live sessions paid for.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import NUMERIC_WRITE_RECIPE, PRESS_HOLD_MS
from udv_echo_process.acquire.win32 import messages

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL, PARENT = 9001, 9000


# --------------------------------------------------------------------------- the fake transport


class FakeUser32:
    """``user32`` as far as this module reaches it: the two message calls, recorded."""

    def __init__(self, answer: int = 0) -> None:
        self.answer = answer
        self.calls: list[tuple] = []

    def SendMessageTimeoutW(self, hwnd, msg, wp, lp, flags, timeout_ms, result) -> int:
        self.calls.append(("SendMessageTimeoutW", msg, wp, lp, flags, timeout_ms))
        result._obj.value = self.answer
        return 1

    def PostMessageW(self, hwnd, msg, wp, lp) -> int:
        self.calls.append(("PostMessageW", msg, wp, lp))
        return 1


class FakeGui:
    """``win32gui`` as far as the commit and the select reach it: ``GetParent``/``GetDlgCtrlID``."""

    def __init__(self, control_id: int = 7, parent: int = PARENT) -> None:
        self.control_id = control_id
        self.parent = parent
        self.calls: list[tuple] = []

    def GetParent(self, hwnd: int) -> int:
        self.calls.append(("GetParent", hwnd))
        return self.parent

    def GetDlgCtrlID(self, hwnd: int) -> int:
        self.calls.append(("GetDlgCtrlID", hwnd))
        return self.control_id


class Recorder:
    """One ordered log of what a gesture *did* — messages and sleeps in the order they happened."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def post(self, hwnd: int, msg: int, wp: int = 0, lp: int = 0) -> None:
        self.events.append(("post", msg, wp, lp))

    def sleep(self, seconds: float) -> None:
        self.events.append(("sleep", seconds))

    def messages(self) -> list[int]:
        return [event[1] for event in self.events if event[0] == "post"]


# ------------------------------------------------------------------------------- the transport


def test_the_send_is_bounded_and_never_a_plain_send() -> None:
    """``SendMessageTimeoutW`` with ``SMTO_ABORTIFHUNG`` and the measured timeout — nothing else.

    A plain ``SendMessage`` to a busy target thread blocks the caller indefinitely (docs/16 §1),
    which is why the recipe is this call and why the timeout and the flag are pinned: they are
    the difference between a bounded step and a hung run.
    """
    user32 = FakeUser32(answer=42)

    result = messages._send(CONTROL, messages.WM_GETTEXT, 1, 2, user32=lambda: user32)

    assert result == 42
    assert user32.calls == [
        (
            "SendMessageTimeoutW",
            messages.WM_GETTEXT,
            1,
            2,
            messages.SMTO_ABORTIFHUNG,
            messages.SEND_TIMEOUT_MS,
        )
    ]
    assert messages.SEND_TIMEOUT_MS == driver.SEND_TIMEOUT_MS  # the facade re-exports the one
    assert messages.SMTO_ABORTIFHUNG == driver.SMTO_ABORTIFHUNG


def test_the_click_is_posted_and_held_between_down_and_up() -> None:
    """``WM_LBUTTONDOWN`` + ``MK_LBUTTON`` -> the hold -> ``WM_LBUTTONUP``, client coordinates.

    The strip's own A/B (live 2026-09-17 22:01): an instant down/up in the same millisecond is
    ignored, the *hold* is the gesture. ``lParam`` is the control's **client** centre, and the
    two messages go to the control's own handle — never to the panel, never to the menubar.
    """
    recorder = Recorder()
    original_sleep = time.sleep

    class Gui:
        @staticmethod
        def GetClientRect(_hwnd: int) -> tuple[int, int, int, int]:
            return (0, 0, 85, 20)  # the live Record button's size

        @staticmethod
        def ClientToScreen(_hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
            return (547 + point[0], 487 + point[1])  # its live position

    try:
        time.sleep = lambda seconds: recorder.events.append(("sleep", seconds))  # type: ignore[assignment]
        screen = messages._click_hold(
            CONTROL, post=recorder.post, gui=lambda: (Gui, None)
        )
    finally:
        time.sleep = original_sleep  # type: ignore[assignment]

    assert recorder.messages() == [messages.WM_LBUTTONDOWN, messages.WM_LBUTTONUP]
    down = recorder.events[0]
    up = recorder.events[2]
    assert down[2] == messages.MK_LBUTTON
    assert up[2] == 0
    assert down[3] == up[3] == ((20 // 2 & 0xFFFF) << 16) | (85 // 2)  # the client centre
    assert recorder.events[1] == ("sleep", PRESS_HOLD_MS / 1000.0)  # the hold, in the middle
    assert recorder.events[3] == ("sleep", messages._CLICK_SETTLE_S)
    # The screen point is read *before* the down message and travels back as a diagnostic only.
    assert screen == (547 + 85 // 2, 487 + 20 // 2)


def test_the_text_commit_is_the_committed_recipe_in_order() -> None:
    """``WM_SETTEXT`` -> ``EN_CHANGE`` -> ``VK_RETURN`` down/up, with the reference's settles.

    ``WM_SETTEXT`` alone changes the control's text while the application keeps its own value,
    so the command and the key event are the commit (docs/14 §4, docs/16 §12a). The sequence is
    asserted against :data:`NUMERIC_WRITE_RECIPE` itself: a fourth send, a dropped key event or a
    reordered pair fails here.
    """
    recorder = Recorder()
    gui = FakeGui(control_id=7)
    sent: list[tuple] = []

    def send(hwnd: int, msg: int, wp: int = 0, lp: int = 0, timeout_ms: int = 0) -> int:
        sent.append((hwnd, msg, wp, ctypes.wstring_at(lp) if lp else ""))
        return 1

    sleeps: list[float] = []
    original_sleep = time.sleep
    try:
        time.sleep = sleeps.append  # type: ignore[assignment]
        messages._set_text_commit(
            CONTROL, "1250", post=recorder.post, send=send, gui=lambda: (gui, None)
        )
    finally:
        time.sleep = original_sleep  # type: ignore[assignment]

    assert sent == [(CONTROL, messages.WM_SETTEXT, 0, "1250")]
    assert recorder.events[0] == ("post", messages.WM_COMMAND, (messages.EN_CHANGE << 16) | 7, CONTROL)
    assert recorder.messages()[1:] == [messages.WM_KEYDOWN, messages.WM_KEYUP]
    assert [event[2] for event in recorder.events if event[0] == "post"][1:] == [
        messages.VK_RETURN,
        messages.VK_RETURN,
    ]
    assert [event[3] for event in recorder.events if event[0] == "post"][1:] == [
        messages._VK_RETURN_DOWN_LPARAM,
        messages._VK_RETURN_UP_LPARAM,
    ]
    assert sleeps == [messages._TEXT_SETTLE_S, messages._TEXT_SETTLE_S, messages._TEXT_COMMIT_SETTLE_S]
    assert messages._COMMIT_RECIPE == NUMERIC_WRITE_RECIPE  # the port cannot drift
    assert gui.calls == [("GetParent", CONTROL), ("GetDlgCtrlID", CONTROL)]


def test_the_text_commit_uses_the_parent_the_caller_states() -> None:
    """A stated parent is never re-read: the dialog's field knows its own dialog."""
    recorder = Recorder()
    gui = FakeGui()

    messages._set_text_commit(
        CONTROL,
        0,  # type: ignore[arg-type]  # a stated parent, so nothing is derived
        PARENT,
        post=recorder.post,
        send=lambda *args, **kwargs: 1,
        gui=lambda: (gui, None),
    )

    assert ("GetParent", CONTROL) not in gui.calls


def test_the_combo_notification_carries_the_id_and_no_enter() -> None:
    """``CB_SETCURSEL`` + ``WM_COMMAND``/``CBN_SELCHANGE`` — and deliberately no key event.

    A combo commits on its change notification; a key event here would re-trigger whatever the
    Enter handler does, and this is the path that decides the measurement channel.
    """
    recorder = Recorder()
    gui = FakeGui(control_id=11)
    sent: list[tuple] = []
    sleeps: list[float] = []
    original_sleep = time.sleep
    try:
        time.sleep = sleeps.append  # type: ignore[assignment]
        messages._combo_select(
            CONTROL,
            4,
            post=recorder.post,
            send=lambda hwnd, msg, wp=0, lp=0, timeout_ms=0: sent.append((hwnd, msg, wp)) or 1,
            gui=lambda: (gui, None),
        )
    finally:
        time.sleep = original_sleep  # type: ignore[assignment]

    assert sent == [(CONTROL, messages.CB_SETCURSEL, 4)]
    assert recorder.events[0] == (
        "post",
        messages.WM_COMMAND,
        (messages.CBN_SELCHANGE << 16) | 11,
        CONTROL,
    )  # the control id is the low word, the notification the high one
    assert messages.WM_KEYDOWN not in recorder.messages()
    assert messages.WM_KEYUP not in recorder.messages()
    assert sleeps == [messages._TEXT_SETTLE_S, messages._COMBO_SETTLE_S]


def test_an_unsigned_err_reads_as_no_selection_and_a_nonsense_count_as_no_items() -> None:
    """``CB_ERR`` arrives as a huge unsigned result: treating it as an index is the trap."""
    no_selection = 0xFFFF_FFFF_FFFF_FFFF
    assert messages._combo_index(CONTROL, send=lambda *a, **k: no_selection) == -1
    assert messages._combo_index(CONTROL, send=lambda *a, **k: 3) == 3
    assert messages._combo_items(CONTROL, send=lambda *a, **k: no_selection) == ()
    assert messages._combo_items(CONTROL, send=lambda *a, **k: 0) == ()
    assert messages._combo_items(CONTROL, send=lambda *a, **k: 2) == ("", "")


def test_the_read_back_asks_the_control_and_not_the_tree() -> None:
    """The combo's own answers: the index, the count, and one item read per index."""
    asked: list[tuple] = []
    items = ("1", "2", "10")

    def send(hwnd: int, msg: int, wp: int = 0, lp: int = 0, timeout_ms: int = 0) -> int:
        asked.append((msg, wp))
        if msg == messages.CB_GETCOUNT:
            return len(items)
        if msg == messages.CB_GETLBTEXT:
            ctypes.memmove(lp, (items[wp] + "\x00").encode("utf-16-le"), 2 * (len(items[wp]) + 1))
            return len(items[wp])
        return 0

    assert messages._combo_items(CONTROL, send=send) == items
    assert asked == [
        (messages.CB_GETCOUNT, 0),
        (messages.CB_GETLBTEXT, 0),
        (messages.CB_GETLBTEXT, 1),
        (messages.CB_GETLBTEXT, 2),
    ]


# ----------------------------------------------------------------- the facade hands over its seams


def test_the_facade_hands_the_moved_mechanic_its_own_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """``driver._post``/``driver._gui`` are still what a press goes through.

    This is the whole compatibility mechanism of Patch 3: the bodies moved, the seams did not —
    a fake that patches the names on the facade is still faking what the mechanic uses.
    """
    posted: list[tuple] = []
    sleeps: list[float] = []
    monkeypatch.setattr(driver, "_post", lambda hwnd, msg, wp=0, lp=0: posted.append((hwnd, msg, wp, lp)))
    monkeypatch.setattr(time, "sleep", sleeps.append)

    class Gui:
        @staticmethod
        def GetClientRect(_hwnd: int) -> tuple[int, int, int, int]:
            return (0, 0, 10, 10)

        @staticmethod
        def ClientToScreen(_hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
            return point

    monkeypatch.setattr(driver, "_gui", lambda: (Gui, None))
    actuator = driver.Win32Actuator(channel=1)

    actuator._click_hold(CONTROL)

    assert [(hwnd, msg) for hwnd, msg, _wp, _lp in posted] == [
        (CONTROL, driver.WM_LBUTTONDOWN),
        (CONTROL, driver.WM_LBUTTONUP),
    ]
    assert actuator.last_press_screen == (5, 5)  # the diagnostic the delegate keeps


def test_the_driver_re_exports_the_moved_names_the_callers_use() -> None:
    """Compatibility is an identity, not a copy: ``driver.X is win32.<module>.X``."""
    assert driver._send is messages._send
    assert driver._post is messages._post
    assert driver._click_hold is messages._click_hold
    assert driver._set_text_commit is messages._set_text_commit
    assert driver._combo_select is messages._combo_select
    assert driver._combo_index is messages._combo_index
    assert driver._combo_items is messages._combo_items
    assert driver._control_id is messages._control_id
    assert driver._get_text is messages._get_text
    for name in ("WM_LBUTTONDOWN", "WM_LBUTTONUP", "MK_LBUTTON", "SEND_TIMEOUT_MS", "CB_GETCURSEL"):
        assert getattr(driver, name) == getattr(messages, name)


# ------------------------------------------------------------------------------ the platform seam


#: The child interpreter that asks the question this host cannot answer: it imports the package
#: with ``ctypes.windll`` trapped and the ``win32*``/``pywinauto`` extensions unavailable.
_IMPORT_SAFETY_SCRIPT = textwrap.dedent(
    """
    import sys, ctypes

    class Trap:
        def __getattr__(self, name):
            raise AssertionError(f"ctypes.windll.{name} was touched at import time")

    ctypes.windll = Trap()

    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {"win32gui", "win32con", "win32process", "pywinauto"}:
                raise ModuleNotFoundError(f"no {name} on this host")
            return None

    sys.meta_path.insert(0, Blocker())

    import udv_echo_process.acquire as acquire
    import udv_echo_process.acquire.driver as driver
    import udv_echo_process.acquire.win32.cursor as cursor
    import udv_echo_process.acquire.win32.messages as messages
    import udv_echo_process.acquire.win32.tree as tree

    actuator = driver.Win32Actuator()
    assert actuator.channel >= 1
    assert driver.channel_items()[0] == "1"
    assert driver._COMMIT_RECIPE == acquire.NUMERIC_WRITE_RECIPE
    assert driver._click_hold is messages._click_hold
    assert driver._gui is cursor._gui
    assert driver._visible_children is tree._visible_children
    assert callable(cursor._user32) and callable(tree._main_hwnd)
    print("imported")
    """
)


def test_the_package_imports_with_no_windows_and_no_pywin32() -> None:
    """A host without Windows (no ``ctypes.windll``) and without ``pywin32`` imports this package.

    The contract ``acquire/__init__.py`` documents. ``ctypes.windll`` is replaced with a trap and
    the ``win32*`` extensions are blocked, so any import-time ``windll`` load, ``FindWindow`` or
    other ``user32`` call — and any ``win32gui`` import outside a function — fails loudly in a
    child interpreter, which is the only way to ask the question the host cannot answer.
    """
    done = subprocess.run(
        [sys.executable, "-c", _IMPORT_SAFETY_SCRIPT],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "imported" in done.stdout
