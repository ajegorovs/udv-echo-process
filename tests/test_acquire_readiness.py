"""The readiness guard: one error check, asked by every path that would act.

Measured 2026-10-26: a Delphi access-violation box sat in front of the application for an hour
while every menu call reported ``executed: 0`` and every run refused with a reason about the
foreground. The box is a **top-level** window, so no child census can see it — and the guard that
was added for it (`9b481d0`) lived in the sweep runner alone, so a single point, a preflight and a
bridge cycle could still be driven past a faulted application.

This module pins the two halves of closing that gap, both through the entry points a caller
actually uses:

- the **reader** — :meth:`driver.Win32Actuator.application_error` finds a top-level error box of
  *the target process* and never claims a clear screen it did not establish. Its Windows API is
  injected, and every assertion here is about the exact handles and process ids it asked, not about
  a caption a fake was scripted to give;
- the **guard** — the same optional-capability check refuses the UI point, the preflight and the
  bridge point *before* an overlay is answered, a channel is changed, a press is posted or a cycle
  is run, and it stays compatible with a double that has no such capability. Genuine absence and an
  *unreadable* capability are kept apart — a declared check that raises ``AttributeError`` while
  being looked up is a refusal, not a missing feature — and the bridge wrapper *declares* the
  capability it forwards, so guarding a wrapper answers in exactly the words the guard would use
  against the inner half. That last point is a defect this file now pins: through ``__getattr__``
  alone the wrapper declared nothing, so an offered capability that raised while being read reached
  a runner looking exactly like a legacy double's absence.

The runner's own use of the guard is pinned in ``test_acquire_application_error.py``, beside the
measurement it came from. No test here enumerates a real window or touches a real process.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_acquire_runner import (
    DURATION_S,
    FakeActuator,
    make_runner,
    point_for,
)
from udv_echo_process.acquire import bridge, driver
from udv_echo_process.acquire.actuator import ProcessMode, StripControl, StripState
from udv_echo_process.acquire.config import DEFAULT_CHANNEL, RecordSettings
from udv_echo_process.acquire.cycle import CycleReport, CycleStage
from udv_echo_process.acquire.runner import SweepRunner
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import RecordingSurface
from udv_echo_process.acquire.ui.readiness import (
    ERROR_NOT_CALLABLE,
    application_error_refusal,
)

#: The class of every message box on Windows, and the one the reader must recognise.
ERROR_BOX = "#32770"

#: The application's own main window, and two processes: the target's and somebody else's.
MAIN_WINDOW, A_BOX, A_FOREIGN_BOX, A_PANEL = 0x100, 0x110, 0x120, 0x130
APP_PID, OTHER_PID = 4242, 99

VIOLATION = (
    "Violation d'acces a l'adresse 007262A6 dans le module 'Udop607_4.exe'. "
    "Lecture de l'adresse 1004FFF8."
)


# --------------------------------------------------------------- the injected Windows API


class _Window:
    """One window as the API layer reports it: identity, class, visibility, text."""

    def __init__(
        self,
        hwnd: int,
        cls: str,
        *,
        visible: bool = True,
        text: str = "",
        children: tuple[_Window, ...] = (),
    ) -> None:
        self.hwnd = hwnd
        self.cls = cls
        self.visible = visible
        self.text = text
        self.children = children


class _FakeGui:
    """``win32gui``: every call is recorded with the handle it was made for.

    The point of recording *handles* rather than counting calls is the assertion the reader exists
    for — that a window of another process is never classified, and that a caption is only asked for
    once the window has been shown to be an error surface of the target.
    """

    def __init__(
        self,
        windows: list[_Window],
        *,
        alive: set[int] | None = None,
        enum_error: Exception | None = None,
    ) -> None:
        self.windows = windows
        self.alive = alive
        self.enum_error = enum_error
        self.enumerations = 0
        self.class_queries: list[int] = []
        self.visibility_queries: list[int] = []
        self.text_queries: list[int] = []
        self.child_queries: list[int] = []
        self.existence_queries: list[int] = []
        self._by_hwnd = {window.hwnd: window for window in windows}
        for window in windows:
            for child in window.children:
                self._by_hwnd[child.hwnd] = child

    def EnumWindows(self, callback: Any, param: Any) -> bool:
        self.enumerations += 1
        if self.enum_error is not None:
            raise self.enum_error
        for window in self.windows:
            if callback(window.hwnd, param) is False:
                break
        return True

    def GetClassName(self, hwnd: int) -> str:
        self.class_queries.append(hwnd)
        return self._by_hwnd[hwnd].cls

    def IsWindowVisible(self, hwnd: int) -> bool:
        self.visibility_queries.append(hwnd)
        return self._by_hwnd[hwnd].visible

    def GetWindowText(self, hwnd: int) -> str:
        self.text_queries.append(hwnd)
        return self._by_hwnd[hwnd].text

    def EnumChildWindows(self, hwnd: int, callback: Any, param: Any) -> bool:
        self.child_queries.append(hwnd)
        for child in self._by_hwnd[hwnd].children:
            if callback(child.hwnd, param) is False:
                break
        return True

    def IsWindow(self, hwnd: int) -> bool:
        """Whether the window still exists — ``None`` for "every handle stays valid"."""
        self.existence_queries.append(hwnd)
        return self.alive is None or hwnd in self.alive


class _FakeProcess:
    """``win32process``: the owning process of a handle, and the handles it refuses to answer for."""

    def __init__(
        self, pids: dict[int, int], *, failing: set[int] | None = None
    ) -> None:
        self.pids = dict(pids)
        self.failing = set(failing or ())
        self.queries: list[int] = []

    def GetWindowThreadProcessId(self, hwnd: int) -> tuple[int, int]:
        self.queries.append(hwnd)
        if hwnd in self.failing:
            raise OSError(f"window {hwnd:#x} is not a window this process can identify")
        return 0, self.pids[hwnd]


class _FakeUser32:
    """``user32``'s one bounded call, recorded with the bound it was given.

    This is the repository's existing send boundary — ``tests/test_acquire_driver.py`` fakes
    ``driver._user32`` the same way — so a caption a test scripts travels through the **production**
    path: ``driver._get_text`` → ``WM_GETTEXT`` → ``SendMessageTimeoutW`` with
    :data:`driver.SEND_TIMEOUT_MS` and ``SMTO_ABORTIFHUNG``. What the assertions below read is that
    query (the handle, the message and the bound), never a stub that simply answers text.
    """

    def __init__(self, bodies: dict[int, str] | None = None) -> None:
        self.bodies = dict(bodies or {})
        #: ``(handle, message, flags, timeout_ms)`` for every bounded send, in order.
        self.sends: list[tuple[int, int, int, int]] = []

    @property
    def text_queries(self) -> list[int]:
        """The handles a ``WM_GETTEXT`` was sent to."""
        return [
            handle
            for handle, msg, _flags, _timeout in self.sends
            if msg == driver.WM_GETTEXT
        ]

    def SendMessageTimeoutW(
        self,
        hwnd: object,
        msg: int,
        wp: int,
        lp: int,
        flags: int,
        timeout_ms: int,
        result: object,
    ) -> None:
        handle = int(hwnd.value) if isinstance(hwnd, ctypes.c_void_p) else int(hwnd)  # type: ignore[union-attr]
        self.sends.append((handle, msg, flags, timeout_ms))
        if msg != driver.WM_GETTEXT:
            return
        body = self.bodies.get(handle, "")
        if body:
            ctypes.memmove(lp, (body + "\x00").encode("utf-16-le"), 2 * (len(body) + 1))


class _Reader(driver.Win32Actuator):
    """The real reader: only the target window and the Windows API layer are injected.

    ``_main_hwnd`` is the one seam overridden — the window whose owning process is the target —
    because everything else the reader needs is handed in: ``_gui`` (enumerating and classifying)
    and ``win32process`` through the platform boundary. The caption read is the driver's own
    :meth:`_get_text`, so nothing about it is stubbed.
    """

    def __init__(self) -> None:
        super().__init__(channel=DEFAULT_CHANNEL)

    def _main_hwnd(self) -> int:
        return MAIN_WINDOW


class _Blind(_Reader):
    """A reader whose main window cannot be resolved at all.

    The bootstrap failure the guard must not read as a clear screen: a layout or window failure is a
    state nobody read, and the process a crash box belongs to cannot be established without it.
    """

    def _main_hwnd(self) -> int:
        raise AcquisitionError(
            "no visible TMain_Scr window — is UDOP on its startup screen?"
        )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    gui: _FakeGui,
    *,
    pids: dict[int, int],
    failing: set[int] | None = None,
    bodies: dict[int, str] | None = None,
) -> tuple[_FakeProcess, _FakeUser32]:
    """Give the driver this API layer: ``_gui``, ``_user32`` and ``win32process``.

    Both platform modules are injected at the seams the driver already has — ``driver._gui`` and
    ``driver._user32`` are how this repository's fakes have always scripted the window layer, and
    ``win32process`` is resolved inside ``application_error``, so replacing it in ``sys.modules`` is
    the same kind of boundary. No import of ``pywin32`` is needed, and the reader cannot reach a
    real window, process or desktop even on a host that has one.
    """
    process = _FakeProcess(pids, failing=failing)
    user32 = _FakeUser32(bodies)
    monkeypatch.setattr(driver, "_gui", lambda: (gui, None))
    monkeypatch.setattr(driver, "_user32", lambda: user32)
    monkeypatch.setitem(sys.modules, "win32process", process)
    return process, user32


# ------------------------------------------------------------------------- the reader itself


def test_the_error_box_of_the_target_process_is_read_and_no_other_process_is_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caption comes from the target's own box — and another process's box is never touched."""
    gui = _FakeGui(
        [
            _Window(A_BOX, ERROR_BOX, text=VIOLATION),
            _Window(A_FOREIGN_BOX, ERROR_BOX, text="another application's error"),
            _Window(A_PANEL, "TMain_Scr"),
        ]
    )
    process, user32 = _install(
        monkeypatch,
        gui,
        pids={
            MAIN_WINDOW: APP_PID,
            A_BOX: APP_PID,
            A_FOREIGN_BOX: OTHER_PID,
            A_PANEL: APP_PID,
        },
    )
    actuator = _Reader()

    answer = actuator.application_error()

    assert answer == VIOLATION
    assert gui.enumerations == 1, (
        "the top-level scan happens once, not once per candidate"
    )
    # The target is identified from the application's own window, before any candidate is read —
    # and the scan stops at the box: the refusal is the answer, so later windows are not asked.
    assert process.queries[:2] == [MAIN_WINDOW, A_BOX]
    assert A_FOREIGN_BOX not in gui.class_queries, (
        "another process's box was classified"
    )
    assert gui.class_queries == [A_BOX], "only the target's windows are classified"
    assert gui.visibility_queries == [A_BOX]
    assert gui.text_queries == [A_BOX]
    assert user32.sends == [], (
        "a caption the snapshot carries needs no query of its own"
    )


def test_a_target_modal_with_no_readable_text_still_blocks_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable caption is not a clear screen: the box is reported, with a truthful fallback."""
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text="")])
    _process, user32 = _install(
        monkeypatch, gui, pids={MAIN_WINDOW: APP_PID, A_BOX: APP_PID}
    )
    actuator = _Reader()

    answer = actuator.application_error()

    assert answer is not None, "an unreadable error box was reported as no error at all"
    assert answer.strip(), "the refusal must carry something an operator can read"
    assert "could not be read" in answer
    # The caption was asked for — by the driver's own bounded query, not by a stub.
    assert user32.text_queries == [A_BOX]
    assert (
        A_BOX,
        driver.WM_GETTEXT,
        driver.SMTO_ABORTIFHUNG,
        driver.SEND_TIMEOUT_MS,
    ) in (user32.sends), user32.sends


def test_a_caption_the_snapshot_does_not_carry_is_read_through_the_query_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GetWindowText`` answers nothing for these widgets; the box's own text is read by message."""
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text="")])
    # ``GetWindowText`` answers nothing — the documented behaviour for another process's control —
    # and the box's own text arrives through ``WM_GETTEXT`` instead.
    _process, user32 = _install(
        monkeypatch,
        gui,
        pids={MAIN_WINDOW: APP_PID, A_BOX: APP_PID},
        bodies={A_BOX: "Erreur: violation d'acces a l'adresse 007262A6"},
    )
    actuator = _Reader()

    answer = actuator.application_error()

    assert answer is not None and "007262A6" in answer, answer
    assert user32.text_queries == [A_BOX]
    _handle, message, flags, timeout_ms = next(
        send for send in user32.sends if send[0] == A_BOX
    )
    assert message == driver.WM_GETTEXT
    assert flags == driver.SMTO_ABORTIFHUNG, "the send must abort on a hung target"
    assert timeout_ms == driver.SEND_TIMEOUT_MS, (
        f"the query ran with an unbounded/default timeout: {timeout_ms}"
    )


def test_a_box_whose_caption_is_only_in_a_child_is_read_from_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caption can be a static child of the box, so the box's children are read too."""
    label = _Window(0x111, "Static", text="")
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text="", children=(label,))])
    _process, user32 = _install(
        monkeypatch,
        gui,
        pids={MAIN_WINDOW: APP_PID, A_BOX: APP_PID},
        bodies={0x111: VIOLATION},
    )
    actuator = _Reader()

    answer = actuator.application_error()

    assert answer is not None and "007262A6" in answer, answer
    assert gui.child_queries == [A_BOX]
    # ``GetWindowText`` cannot read another process's control, so the child's body came from the
    # same bounded ``WM_GETTEXT`` — asserted at the child's own handle, with its bound.
    assert (
        0x111,
        driver.WM_GETTEXT,
        driver.SMTO_ABORTIFHUNG,
        driver.SEND_TIMEOUT_MS,
    ) in (user32.sends), user32.sends


def test_a_window_that_no_longer_exists_is_not_an_unreadable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handle that vanished mid-scan is a race, not a fault: it shows nothing and is skipped."""
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text=VIOLATION)], alive=set())
    _install(monkeypatch, gui, pids={MAIN_WINDOW: APP_PID}, failing={A_BOX})
    actuator = _Reader()

    assert actuator.application_error() is None
    assert gui.existence_queries == [A_BOX]


def test_a_window_that_still_exists_but_cannot_be_identified_is_not_a_clear_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old reader swallowed this and answered ``None`` — which claims a state nobody read."""
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text=VIOLATION)], alive={A_BOX})
    _install(monkeypatch, gui, pids={MAIN_WINDOW: APP_PID}, failing={A_BOX})
    actuator = _Reader()

    with pytest.raises(RuntimeError, match="could not"):
        actuator.application_error()


def test_other_processes_and_non_error_surfaces_are_a_clear_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is up: no caption is asked for, and a foreign box does not make this one up."""
    gui = _FakeGui(
        [
            _Window(A_FOREIGN_BOX, ERROR_BOX, text="another application's error"),
            _Window(A_PANEL, "TMain_Scr"),
        ]
    )
    _install(
        monkeypatch,
        gui,
        pids={MAIN_WINDOW: APP_PID, A_FOREIGN_BOX: OTHER_PID, A_PANEL: APP_PID},
    )
    actuator = _Reader()

    assert actuator.application_error() is None
    assert gui.text_queries == [], "no caption is read when nothing is an error surface"
    assert gui.class_queries == [A_PANEL]


def test_an_error_box_that_is_not_showing_is_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hidden message box is a window, not a state the operator can see."""
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, visible=False, text=VIOLATION)])
    _install(monkeypatch, gui, pids={MAIN_WINDOW: APP_PID, A_BOX: APP_PID})
    actuator = _Reader()

    assert actuator.application_error() is None
    assert gui.text_queries == []


def test_a_scan_that_cannot_be_made_is_not_a_clear_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed enumeration is raised, never answered as ``None``."""
    gui = _FakeGui([], enum_error=OSError("the window station refused the enumeration"))
    _install(monkeypatch, gui, pids={MAIN_WINDOW: APP_PID})
    actuator = _Reader()

    with pytest.raises(OSError, match="refused the enumeration"):
        actuator.application_error()


def test_a_main_window_that_cannot_be_resolved_is_not_a_clear_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bootstrap failure: no target window means no target process means no clear answer.

    This is the state a broken layout leaves behind, and reading it as ``None`` would let a crash
    box outrank nothing because the window it belongs to could not be found.
    """
    gui = _FakeGui([_Window(A_BOX, ERROR_BOX, text=VIOLATION)])
    _install(monkeypatch, gui, pids={MAIN_WINDOW: APP_PID, A_BOX: APP_PID})
    actuator = _Blind()

    with pytest.raises(AcquisitionError, match="startup screen"):
        actuator.application_error()


# ------------------------------------------------------------------- the guard, UI point


class _SurfaceProbe(RecordingSurface):
    """The recording surface on its own — the UI route's single-point entry point.

    Every collaborator the cycle would reach is a stub that **records itself**, so "refused before
    it acted" is asserted by the order of what was asked rather than by inspecting an application
    afterwards. The layout, the channel, the overlay answer, the strip and the press all raise,
    because a refused cycle must reach none of them; the recovery's own collaborators answer, so a
    run that *does* proceed reports its own failure rather than collapsing in the fake.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []

    def layout_note(self, *, expected_mode: object = None) -> str | None:
        self.asked.append("layout_note")
        raise AssertionError(
            "the cycle went on past the readiness check: it reached the layout"
        )

    def ensure_channel(self) -> int:
        self.asked.append("ensure_channel")
        raise AssertionError("the cycle changed the measurement channel")

    def answer_overlay(self) -> object:
        self.asked.append("answer_overlay")
        raise AssertionError("the cycle answered an overlay")

    def strip_state(self) -> object:
        self.asked.append("strip_state")
        raise AssertionError("the cycle reached the strip")

    def press(self, control: object) -> None:
        self.asked.append(f"press:{control!r}")
        raise AssertionError("the cycle pressed")

    def _note(self, message: str) -> None:
        self.asked.append(f"note:{message}")

    def _peek_overlay(self) -> object:
        self.asked.append("_peek_overlay")
        return None

    def __getattr__(self, name: str) -> Any:
        if name == "application_error":
            # This double genuinely has no such capability — the shape a legacy fake has.
            raise AttributeError(name)
        raise AssertionError(f"the cycle reached {name!r}")


class _UiPoint(_SurfaceProbe):
    """The same surface with the capability offered, answering what the test scripts."""

    def __init__(self, answer: object) -> None:
        super().__init__()
        self.answer = answer

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer  # type: ignore[return-value]


@pytest.mark.parametrize(
    ("answer", "fragment"),
    [
        (VIOLATION, "showing an error"),
        (RuntimeError("the window station refused"), "could not be read"),
        (42, "not a clear screen"),
        ("", "empty"),
        ("   ", "empty"),
    ],
    ids=[
        "error-box",
        "raising-check",
        "malformed-answer",
        "empty-answer",
        "blank-answer",
    ],
)
def test_the_ui_point_refuses_before_it_answers_an_overlay_or_presses(
    answer: object, fragment: str
) -> None:
    """Every unusable answer is a named refusal, and the cycle touches nothing else."""
    point = _UiPoint(answer)

    with pytest.raises(AcquisitionError) as raised:
        point.record_and_store(
            "ui-01", 0.5, Path("capture"), expected_mode=ProcessMode.INSTRUMENT
        )

    assert fragment in str(raised.value), str(raised.value)
    assert point.asked == ["application_error"]


def test_the_ui_points_try_form_returns_the_refusal_instead_of_raising() -> None:
    """``try_record_and_store`` keeps its ``(False, reason)`` shape — no new exception path."""
    point = _UiPoint(VIOLATION)

    ok, reason = point.try_record_and_store(
        "ui-01", 0.5, Path("capture"), expected_mode=ProcessMode.INSTRUMENT
    )

    assert ok is False
    assert "showing an error" in str(reason)
    assert "007262A6" in str(reason), (
        "the box's own text is carried, as the runner's is"
    )
    assert point.asked == ["application_error"]


def test_a_clear_check_lets_the_ui_point_proceed() -> None:
    """A capability that answers *clear* is not a refusal: the cycle goes on to its first step."""
    point = _UiPoint(None)

    with pytest.raises(AcquisitionError) as raised:
        point.record_and_store(
            "ui-01", 0.5, Path("capture"), expected_mode=ProcessMode.INSTRUMENT
        )

    # The point fails on the fake's own first step, which is the proof it was allowed to start.
    assert point.asked[:2] == ["application_error", "layout_note"], point.asked
    assert "unexpected failure" in str(raised.value), str(raised.value)


def test_a_surface_without_the_capability_is_not_refused_for_that() -> None:
    """The check is a capability of the Windows actuator; its absence is not an error state."""
    point = _SurfaceProbe()
    assert not hasattr(point, "application_error")

    with pytest.raises(AcquisitionError) as raised:
        point.record_and_store(
            "ui-01", 0.5, Path("capture"), expected_mode=ProcessMode.INSTRUMENT
        )

    assert point.asked[:1] == ["layout_note"], point.asked
    assert "error state" not in str(raised.value), str(raised.value)


def test_a_fault_raised_inside_the_hold_is_named_as_an_error() -> None:
    """The hold polls the error state as well as the view.

    A fault that lands *during* a recording stops the strip moving, and the old reading — "the
    recording stopped on its own" — sends an operator looking at the instrument instead of at the
    application. The guard's sentence is the honest one, and it is asked *before* the strip is read.
    """

    class _Hold(RecordingSurface):
        """A hold whose recording is live and whose application faults on the second look."""

        def __init__(self) -> None:
            self.answers: list[str | None] = [None, VIOLATION]
            self.asked: list[str] = []

        def application_error(self) -> str | None:
            self.asked.append("application_error")
            return self.answers.pop(0) if self.answers else None

        def _peek_overlay(self) -> object:
            self.asked.append("_peek_overlay")
            return None

        def strip_state(self) -> object:
            self.asked.append("strip_state")
            # The one-button row: a recording in progress.
            return StripState(button_count=1)

    point = _Hold()

    with pytest.raises(AcquisitionError, match="showing an error"):
        point.hold_recording(1.0)

    assert point.asked == [
        "application_error",
        "_peek_overlay",
        "strip_state",
        "application_error",
    ], point.asked


# ------------------------------------------------------------------- the guard, preflight


class _Preflight(driver.Win32Actuator):
    """The facade's preflight over one answered check and a strip that must not be reached."""

    def __init__(self, answer: object) -> None:
        super().__init__(channel=DEFAULT_CHANNEL)
        self.answer = answer
        self.asked: list[str] = []

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer  # type: ignore[return-value]

    def strip_state(self):  # the fake's own answer is never needed
        self.asked.append("strip_state")
        raise AssertionError("the preflight read the strip past a faulted application")

    def press(self, control: object) -> None:
        self.asked.append(f"press:{control!r}")
        raise AssertionError("the preflight pressed past a faulted application")


@pytest.mark.parametrize(
    ("answer", "fragment"),
    [
        (VIOLATION, "showing an error"),
        (RuntimeError("the window station refused"), "could not be read"),
        (object(), "not a clear screen"),
    ],
    ids=["error-box", "raising-check", "malformed-answer"],
)
def test_the_preflight_refuses_before_it_reads_the_strip_or_presses(
    answer: object, fragment: str
) -> None:
    """The preflight runs a whole cycle; on a faulted application it must run none of it."""
    actuator = _Preflight(answer)

    with pytest.raises(AcquisitionError) as raised:
        actuator.preflight(0.05)

    assert fragment in str(raised.value), str(raised.value)
    assert actuator.asked == ["application_error"]


def test_the_preflight_runs_when_the_check_is_clear() -> None:
    """Compatibility: a clear answer is not a refusal, and the sequence starts where it always did."""
    actuator = _Preflight(None)

    with pytest.raises(AssertionError, match="read the strip"):
        actuator.preflight(0.05)
    assert actuator.asked == ["application_error", "strip_state"]


# --------------------------------------------------------------------- the guard, bridge


class _BridgeInner:
    """The GUI half the bridge delegates to: it is showing an error and records what else is asked."""

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer  # type: ignore[return-value]

    def process_mode_note(self, expected: object) -> str | None:
        self.asked.append("process_mode_note")
        raise AssertionError(
            "the bridge read the process mode past a faulted application"
        )


class _Cycle:
    """A supplied cycle that must not run."""

    def __init__(self) -> None:
        self.calls = 0

    def try_record_and_store(
        self, *args: object, **kwargs: object
    ) -> tuple[bool, Path | str]:
        self.calls += 1
        raise AssertionError("the bridge ran its cycle past a faulted application")


def test_the_bridge_point_refuses_before_it_reads_the_mode_or_runs_a_cycle(
    tmp_path: Path,
) -> None:
    """The check outranks the table, the mode read and the cycle — and needs none of them."""
    inner = _BridgeInner(VIOLATION)
    cycle = _Cycle()
    # No table and no dispatch at all: only the readiness check can answer this call.
    actuator = bridge.BridgeActuator(inner=inner, cycle=cycle)

    ok, reason = actuator.try_record_and_store(
        "bridge-01", 0.5, tmp_path, expected_mode=ProcessMode.INSTRUMENT
    )

    assert ok is False
    assert "showing an error" in str(reason), str(reason)
    assert "007262A6" in str(reason)
    assert cycle.calls == 0
    assert inner.asked == ["application_error"]


def test_the_bridges_raising_form_carries_the_same_refusal(tmp_path: Path) -> None:
    """``record_and_store`` raises what ``try_record_and_store`` returns, unchanged."""
    inner = _BridgeInner(RuntimeError("the window station refused"))
    cycle = _Cycle()
    actuator = bridge.BridgeActuator(inner=inner, cycle=cycle)

    with pytest.raises(bridge.BridgeRefused) as raised:
        actuator.record_and_store(
            "bridge-01", 0.5, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )

    assert "could not be read" in str(raised.value)
    assert cycle.calls == 0


def test_a_bridge_inner_without_the_capability_is_not_refused_for_that(
    tmp_path: Path,
) -> None:
    """A legacy or pure double keeps its own verdict: absence is not an error state."""

    class _Inner:
        def process_mode_note(self, expected: object) -> str | None:
            return None

    actuator = bridge.BridgeActuator(inner=_Inner())

    ok, reason = actuator.try_record_and_store(
        "bridge-01", 0.5, tmp_path, expected_mode=ProcessMode.INSTRUMENT
    )

    assert ok is False
    assert reason == "bridge_runner_not_configured", (
        f"absence of the check was read as an error: {reason}"
    )


# ------------------------------------------------------- the capability rule, asked directly


class _UnreadableDeclaration:
    """An offered capability that a declared property cannot answer.

    The hazardous shape: the name exists on the class, so ``getattr`` raises ``AttributeError`` from
    inside the descriptor — which a lookup that only catches ``AttributeError`` would read as "this
    double has no such capability".
    """

    @property
    def application_error(self) -> str | None:
        raise AttributeError("the reader's own state is not available")


def test_a_declared_capability_that_cannot_be_read_is_a_refusal_not_an_absence() -> (
    None
):
    refusal = application_error_refusal(_UnreadableDeclaration())

    assert refusal is not None, (
        "a declared but unreadable check was read as no capability"
    )
    assert "could not be read" in refusal, refusal
    assert "declaration could not be read" in refusal, refusal


def test_a_declared_none_capability_is_named_not_callable_not_credited_as_clear() -> (
    None
):
    """``None`` is the guard's word for a clear screen, so a declared ``None`` must be refused.

    Distinct from absence (nothing declared) and from a getter that succeeds and answers ``None``:
    here the *lookup* answered, and what it answered cannot be called.
    """
    direct = application_error_refusal(_DeclaredNoneInner())
    wrapped = application_error_refusal(
        bridge.BridgeActuator(inner=_DeclaredNoneInner())
    )
    expected = ERROR_NOT_CALLABLE.format(kind="NoneType")

    assert direct == expected, direct
    assert wrapped == expected, wrapped
    assert "ErrorStateUnreadable" not in (wrapped or ""), (
        f"the cause was wrapped a second time: {wrapped}"
    )


def test_the_bridge_delegation_is_asked_through_so_a_guard_cannot_skip_the_inner_half() -> (
    None
):
    """A wrapper's capability is its inner half's — the runner guarding the wrapper sees it."""
    inner = _BridgeInner(VIOLATION)
    actuator = bridge.BridgeActuator(inner=inner, cycle=_Cycle())

    refusal = application_error_refusal(actuator)

    assert refusal is not None and VIOLATION in refusal, refusal
    assert inner.asked == ["application_error"]


# ------------------------------------- the wrapper's own boundary, against every shape


class _PlainInner:
    """A legacy inner half: no ``application_error`` capability at all."""


class _NonCallableInner:
    """An inner half that offers the name and not a check."""

    application_error = "not a check"  # type: ignore[assignment]


class _DeclaredNoneInner:
    """An inner half that *declares* the capability and binds it to ``None``.

    The lookup answers, so this is not the absence case: ``None`` is the guard's own word for a
    clear screen, and crediting a declared ``None`` as clear would let a broken check pass as a
    clean one. It is an offered capability that cannot be called.
    """

    application_error = None  # type: ignore[assignment]


class _UnreadableDeclaration:
    """An inner half whose *declared* capability raises while it is being read.

    The defect this file now pins: read directly it is an offered capability that cannot be read,
    but through a ``__getattr__``-only wrapper it used to look exactly like ``_PlainInner``.
    """

    @property
    def application_error(self) -> str | None:
        raise AttributeError("the offered reader cannot be resolved")


def _answering_inner(answer: object) -> object:
    """An inner half whose capability answers ``answer``, raising it when it is an exception."""

    class _Inner:
        def application_error(self) -> object:
            if isinstance(answer, BaseException):
                raise answer
            return answer

    return _Inner()


#: Every shape the capability can be offered in; the unusable ones must *refuse*, not answer.
CAPABILITY_SHAPES = [
    pytest.param(_PlainInner(), id="absent"),
    pytest.param(_answering_inner(None), id="clear"),
    pytest.param(_answering_inner(VIOLATION), id="error-box"),
    pytest.param(_answering_inner(""), id="empty-answer"),
    pytest.param(_answering_inner(42), id="malformed-answer"),
    pytest.param(_NonCallableInner(), id="non-callable"),
    pytest.param(_DeclaredNoneInner(), id="declared-none"),
    pytest.param(
        _answering_inner(RuntimeError("the window station refused")), id="raising-check"
    ),
    pytest.param(_UnreadableDeclaration(), id="unreadable-declaration"),
]
UNUSABLE_SHAPES = {
    "empty-answer",
    "malformed-answer",
    "non-callable",
    "declared-none",
    "raising-check",
    "unreadable-declaration",
}


#: The calls a point takes that change the application. A refusal must leave every one of them
#: unmade; a read is not in this set, because reading what the screen says is not configuring it.
MUTATING = {
    "write_parameter",
    "apply_point",
    "ensure_channel",
    "answer_overlay",
    "press",
    "press_dialog",
    "try_record_and_store",
    "record_and_store",
}


@pytest.mark.parametrize("inner", CAPABILITY_SHAPES)
def test_the_wrapper_answers_the_guard_in_exactly_the_words_the_inner_half_gets(
    inner: object, request: pytest.FixtureRequest
) -> None:
    """One cause, one sentence — whichever half the guard is asked about.

    Equality is the whole assertion, and it is not vacuous for the unusable shapes: each must
    refuse, and the wrapper must refuse in the *same words* the direct half does — no second
    sentence wrapped around the cause, and no shape collapsing into "no capability here".
    """
    direct = application_error_refusal(inner)
    wrapped = application_error_refusal(bridge.BridgeActuator(inner=inner))

    assert wrapped == direct, (direct, wrapped)
    if request.node.callspec.id in UNUSABLE_SHAPES:
        assert direct is not None and "could not be read" in direct, direct
        assert wrapped is not None, "the wrapper let an unusable capability look absent"


def test_a_wrapped_unreadable_capability_refuses_where_the_wrapper_used_to_look_clean() -> (
    None
):
    """The reproduced defect, named: ``direct`` refused and ``wrapped`` answered ``None``."""
    inner = _UnreadableDeclaration()

    direct = application_error_refusal(inner)
    refusal = application_error_refusal(bridge.BridgeActuator(inner=inner))

    assert direct is not None and "could not be read" in direct, direct
    assert refusal == direct, (direct, refusal)
    assert "ErrorStateUnreadable" not in (refusal or ""), (
        f"the cause was wrapped a second time: {refusal}"
    )


def test_a_wrapped_legacy_inner_half_is_absent_rather_than_refused() -> None:
    """Compatibility, at the wrapper: an inner half with no capability is not an error state."""
    assert application_error_refusal(bridge.BridgeActuator(inner=_PlainInner())) is None


class _UnreadableRunnerInner(FakeActuator):
    """The GUI half a bridge wraps for a runner, offering a capability that cannot be read.

    The two reads a point takes *before* the guard — the layout note and the process mode — are
    recorded, so the test can show both that the point started and that it went no further.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        self.asked: list[str] = []

    def layout_note(self) -> str | None:
        self.asked.append("layout_note")
        return super().layout_note()

    def process_mode_note(self, expected: ProcessMode) -> str | None:
        self.asked.append("process_mode_note")
        return super().process_mode_note(expected)

    @property
    def application_error(self) -> str | None:
        raise AttributeError("the offered reader cannot be resolved")


def test_a_runner_refuses_a_wrapped_point_before_any_configuration(
    tmp_path: Path,
) -> None:
    """The hazard the defect created: a point configured and recorded while the guard saw nothing."""
    directory = tmp_path / "capture"
    directory.mkdir()
    inner = _UnreadableRunnerInner(directory)
    engine = SweepRunner(
        bridge.BridgeActuator(inner=inner),
        RecordSettings(name_prefix="sw100"),
        directory,
        expected_mode=ProcessMode.INSTRUMENT,
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "could not be read" in (outcome.reason or ""), outcome.reason
    assert "declaration could not be read" in (outcome.reason or ""), outcome.reason
    # The point barely began: the runner's own early check is the first thing it asks, so not even
    # the layout or the process mode was read (``asked`` records exactly those two), and nothing was
    # configured, no channel was changed, no overlay was answered, no press was posted and no cycle
    # ran. (The action log also carries the runner's *diagnostic* read-back of where the application
    # was left, which is not configuration.)
    assert inner.asked == [], inner.asked
    acted = [call for call in inner.calls if call[0] in MUTATING]
    assert acted == [], (
        f"the point configured or acted before the guard refused: {acted}"
    )


# ------------------------------------------- the refusal, at the boundaries it must outrank


class _HoldFault(RecordingSurface):
    """A UI point whose application is clear until the recording is running, then faults.

    Every step records itself. Pressing is *recorded* rather than refused here, because the question
    this double exists for is whether the cycle's own recovery presses after the refusal.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.presses: list[StripControl] = []
        self.notes: list[str] = []
        self.recording = False

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        return VIOLATION if self.recording else None

    def layout_note(self, *, expected_mode: object = None) -> str | None:
        self.asked.append("layout_note")
        return None

    def strip_state(self) -> StripState:
        # One button is the recording row; three are the stopped row.
        return StripState(button_count=1 if self.recording else 3)

    def answer_overlay(self) -> None:
        self.asked.append("answer_overlay")

    def press(self, control: StripControl) -> None:
        self.asked.append(f"press:{control.value}")
        self.presses.append(control)
        if control is StripControl.RECORD:
            self.recording = True
        elif control is StripControl.STOP:
            self.recording = False

    def _peek_overlay(self) -> None:
        self.asked.append("_peek_overlay")

    def _note(self, message: str) -> None:
        self.notes.append(message)


def test_a_fault_during_the_hold_is_refused_without_a_speculative_stop() -> None:
    """The joined defect: the hold's refusal led the *recovery* to answer overlays and press Stop.

    Recovery is only safe on a screen the guard can still read. On a faulted one it must leave the
    application alone — the state is unverified and the modal loop filters every message it would
    act with — and say so, while the caller's own refusal is what reaches the surface.
    """
    point = _HoldFault()

    with pytest.raises(AcquisitionError) as raised:
        point.record_and_store(
            "hold-01",
            0.05,
            Path("capture"),
            expected_mode=ProcessMode.INSTRUMENT,
            verify_channel=False,
        )

    # The cause is the error box, unchanged — not a sentence about recovery.
    assert "showing an error" in str(raised.value), str(raised.value)
    assert "007262A6" in str(raised.value)
    # No speculative stop, no overlay answered: the recording is left running and unverified.
    assert point.presses == [StripControl.RECORD], point.presses
    assert "answer_overlay" not in point.asked, point.asked
    assert any("recovery was skipped" in note for note in point.notes), point.notes


class _TransientBox(RecordingSurface):
    """A point whose box is up *during the hold* and gone by the time recovery would look.

    The composition the per-call refusal exists for: a fresh sample at recovery time is clear, the
    strip is still recording, and the legacy recovery would therefore answer overlays and stop the
    recording — on the strength of a screen that already cost this point its data.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.presses: list[StripControl] = []
        self.notes: list[str] = []
        self.recording = False
        #: One answer per look: clear on entry, the box during the hold, then clear again.
        self.answers: list[str | None] = [None, VIOLATION]

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        if self.answers:
            return self.answers.pop(0)
        return None

    def layout_note(self, *, expected_mode: object = None) -> str | None:
        self.asked.append("layout_note")
        return None

    def strip_state(self) -> StripState:
        self.asked.append("strip_state")
        return StripState(button_count=1 if self.recording else 3)

    def answer_overlay(self) -> None:
        self.asked.append("answer_overlay")

    def press(self, control: StripControl) -> None:
        self.asked.append(f"press:{control.value}")
        self.presses.append(control)
        if control is StripControl.RECORD:
            self.recording = True
        elif control is StripControl.STOP:
            self.recording = False

    def _peek_overlay(self) -> object:
        self.asked.append("_peek_overlay")
        return None

    def _note(self, message: str) -> None:
        self.notes.append(message)


def test_a_box_that_has_gone_by_recovery_still_forbids_a_speculative_stop() -> None:
    """The transient case: a clear sample at recovery time must not licence recovery's mutations."""
    point = _TransientBox()

    with pytest.raises(AcquisitionError) as raised:
        point.record_and_store(
            "transient-01",
            0.02,
            Path("capture"),
            expected_mode=ProcessMode.INSTRUMENT,
            verify_channel=False,
        )

    # The original readiness cause, unchanged and once.
    assert "showing an error" in str(raised.value), str(raised.value)
    assert "007262A6" in str(raised.value)
    # Nothing was answered, and only the Record press of the cycle itself exists: no Stop.
    assert point.presses == [StripControl.RECORD], point.presses
    assert "answer_overlay" not in point.asked, point.asked
    # Recovery was skipped and said so, rather than running on a screen that had since cleared.
    assert any("recovery was skipped" in note for note in point.notes), point.notes
    # It was skipped *before sampling*: the third look would have answered "clear".
    assert point.asked.count("application_error") == 2, point.asked


class _ClearButRecording(_HoldFault):
    """The same surface with a **clear** check: the legacy recovery still stops a recording."""

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        return None

    def layout_note(self, *, expected_mode: object = None) -> str | None:
        self.asked.append("layout_note")
        return "a leftover recording is up"

    def strip_state(self) -> StripState:
        return StripState(button_count=1)  # still recording, whatever the check says


def test_recovery_still_stops_a_leftover_recording_when_the_check_is_clear() -> None:
    """Compatibility: a clear screen keeps the recovery this package has always had."""
    point = _ClearButRecording()

    with pytest.raises(AcquisitionError):
        point.record_and_store(
            "hold-02",
            0.05,
            Path("capture"),
            expected_mode=ProcessMode.INSTRUMENT,
            verify_channel=False,
        )

    assert point.presses == [StripControl.STOP], point.presses
    assert any("a recording was left running" in note for note in point.notes), (
        point.notes
    )


class _ErrorBeforeLayout(FakeActuator):
    """An actuator showing an error *and* whose layout and mode reads fail.

    The failing reads are the point: a runner that asked them first would refuse the point for a
    layout nobody could read, and send an operator to the wrong place.
    """

    def __init__(self, directory: Path, **kwargs: object) -> None:
        super().__init__(directory, **kwargs)
        self.asked: list[str] = []

    def application_error(self) -> str | None:
        self.asked.append("application_error")
        return VIOLATION

    def layout_note(self) -> str | None:
        self.asked.append("layout_note")
        raise AssertionError("the layout was read past a faulted application")

    def process_mode_note(self, expected: ProcessMode) -> str | None:
        self.asked.append("process_mode_note")
        raise AssertionError("the process mode was read past a faulted application")


def test_a_known_error_outranks_a_failing_layout_and_mode_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner refuses for the box, before the target reads that would blame the wrong thing."""
    fake, engine, _log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=_ErrorBeforeLayout
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "showing an error" in (outcome.reason or ""), outcome.reason
    assert "layout" not in (outcome.reason or ""), outcome.reason
    assert fake.asked == ["application_error"], fake.asked
    acted = [call for call in fake.calls if call[0] in MUTATING]
    assert acted == [], (
        f"the point configured or acted before the guard refused: {acted}"
    )


class _StaticTable:
    """A bridge table measured on the build the test pretends the application is."""

    image_sha256 = "0" * 64


class _ReportingCycle:
    """A supplied cycle that stores a file and reports what it did, so a report is left behind."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_report: CycleReport | None = None

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: object = None,
    ) -> tuple[bool, Path | str]:
        self.calls += 1
        path = Path(directory) / f"{name}.BDD"
        path.write_bytes(b"BDD" + bytes(8))
        self.last_report = CycleReport(
            name=name, stage=CycleStage.STORE, stored=True, streams=1
        )
        return True, path


class _ReportThenErrorInner:
    """A GUI half that answers the mode, and starts clear before being scripted to fault."""

    def __init__(self) -> None:
        self.error: str | None = None

    def process_mode_note(self, expected: object) -> str | None:
        return None

    def application_error(self) -> str | None:
        return self.error


def test_a_readiness_refusal_clears_the_previous_cycles_report_and_reruns_nothing(
    tmp_path: Path,
) -> None:
    """A refused point leaves no evidence behind that belongs to the point before it."""
    cycle = _ReportingCycle()
    inner = _ReportThenErrorInner()
    actuator = bridge.BridgeActuator(inner=inner, cycle=cycle, table=_StaticTable())

    first_ok, first = actuator.try_record_and_store(
        "stale-01", 0.5, tmp_path, expected_mode=ProcessMode.INSTRUMENT
    )

    assert first_ok is True, first
    assert actuator.last_cycle_report is not None
    assert actuator.cycle_report_problem is None

    inner.error = VIOLATION
    ok, reason = actuator.try_record_and_store(
        "stale-02", 0.5, tmp_path, expected_mode=ProcessMode.INSTRUMENT
    )

    assert ok is False
    assert "showing an error" in str(reason), reason
    assert actuator.last_cycle_report is None, (
        "the previous invocation's report survived a refusal that ran no cycle"
    )
    assert actuator.cycle_report_problem is None, "a stale diagnostic was left behind"
    assert cycle.calls == 1, "the cycle ran for a point the guard refused"
