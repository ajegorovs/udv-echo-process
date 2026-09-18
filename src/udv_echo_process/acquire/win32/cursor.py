"""The cursor, the clip and the foreground window — the real-desktop half.

Layer 3 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5): the
**mechanics** that touch the operator's real cursor, moved out of
:mod:`udv_echo_process.acquire.driver` verbatim. This is also where the package's one lazy
handle resolution lives (:func:`_gui`, :func:`_user32`) — one function each, moved whole
rather than split, because :func:`_user32` binds the message *and* cursor signatures with the
argument types that keep a 64-bit ``lParam`` from being truncated. ``ctypes.windll`` and
``win32gui`` are touched **only inside those two functions**, so every module in this package
imports on a host with no Windows and no ``pywin32``.

Three properties are load-bearing, each paid for once in the lab:

1. **An open popup clips the cursor.** This application calls ``ClipCursor`` while its blocking
   popups are up (docs/dop3000/udop-automation.md §6), and a ``SetCursorPos`` outside that
   rectangle is *silently clamped to its edge* rather than refused — which is what parked a
   live run's cursor in the open menu's bottom-left corner. So the clip is read before every
   real move (:func:`_clip_rect`), released when the target lies outside it
   (:func:`_release_clip`), and named in the failure when a move still does not take
   (:func:`_move_real_cursor`).
2. **The operator's cursor comes back** (:func:`_restore_cursor`) — *through the same rule*: a
   clip that does not contain the operator's own position is released before the restore, so a
   restore can never be trapped inside a popup's rectangle. It runs from a ``finally`` and
   raises nothing: masking the real failure would be worse than a cursor left where it is.
3. **Hover only works on an active window.** Measured live 2026-09-17: with a console window in
   front, the same gesture that had opened the menubar minutes earlier opened nothing, and the
   failure was indistinguishable from "this gesture does not work". The foreground window is
   therefore a named precondition (:func:`_require_foreground`), asked and re-asked before the
   cursor moves.

**What this module may not know.** No UDOP surface, no menubar name, no parameter, no store
path. The one step that needs the real cursor is the hover, and it is told *what* it is
hovering and *why* by its caller (:func:`_hover_centre` takes ``what``/``why``), because the
sentence a failure is reported with belongs to the facade. The clip test itself is a pure
predicate and is **passed in** (``inside``) rather than imported: this package imports no
interpreter — not ``acquire.ui``, not ``campaign``, not ``runner``, not ``verify`` — and the
one exception it raises is the facade's own ``AcquisitionError``, resolved inside the raise by
:func:`~udv_echo_process.acquire.win32._acquisition_error` so the class keeps its identity
without this package importing ``driver`` at module level.

**The seam.** Every function that needs the desktop takes its transport as a keyword-only
parameter (``gui``, ``user32``, ``note``, ``inside``) — a parameter passed instead of read from
the caller's module globals — and every step composed of other steps takes the *callable* it
should use (``clip``/``release``/``read_position`` for the two real-cursor bodies,
``foreground``/``activate`` for the precondition, ``move`` for the hover). That is what keeps
the facade's own methods in the chain: ``driver.py`` hands over its ``_gui``/``_user32`` and
its ``_clip_rect``/``_release_clip``/``_cursor_position``/``_foreground_window``/
``_activate_window``/``_move_real_cursor``, so a fake that overrides any of them is still
overriding what runs, and a test that fakes ``driver._user32`` is still faking the transport
the whole chain uses. The facade imports every name below back into its own namespace, so
``driver._CursorPoint``, ``driver._clip_rect``, ``driver._hover_centre`` and the rest still
resolve.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from functools import lru_cache

from udv_echo_process.acquire.win32 import _acquisition_error

__all__ = [
    "MOUSEEVENTF_MOVE",
    "_CURSOR_SETTLE_S",
    "_FOREGROUND_POLL_S",
    "_FOREGROUND_WAIT_S",
    "_HOVER_MOVE_DX",
    "_HOVER_MOVE_DY",
    "_HOVER_OPEN_S",
    "_HOVER_SETTLE_S",
    "_ClipRect",
    "_CursorPoint",
    "_activate_window",
    "_clip_rect",
    "_cursor_position",
    "_foreground_window",
    "_gui",
    "_hover_centre",
    "_move_real_cursor",
    "_release_clip",
    "_require_foreground",
    "_restore_cursor",
    "_thread_of",
    "_user32",
]

#: ``mouse_event``'s move flag and the reference recipe's nudge: a ``SetCursorPos`` jump
#: alone can be missed by the application's menu loop, the relative move is what it sees.
MOUSEEVENTF_MOVE = 0x0001
_HOVER_MOVE_DX, _HOVER_MOVE_DY = 2, 0
#: The real-cursor hover the menubar needs, copied from the recipe that opened this menu
#: (``SetCursorPos`` / ``sleep(0.3)`` / ``mouse_event(MOUSEEVENTF_MOVE, 2, 0, ..)`` /
#: ``sleep(1.0)``): the settle after the jump, the second settle before the popup is
#: polled for, and the settle after the cursor is put back.
_HOVER_SETTLE_S, _HOVER_OPEN_S, _CURSOR_SETTLE_S = 0.3, 1.0, 0.05
#: How long to keep re-reading the foreground window after asking Windows to activate the
#: application, and how often: this application answers a hover **only** while it is
#: active, so the hover waits for the activation to take instead of hovering into a window
#: that will ignore it (measured live 2026-09-17, `recon/53`).
_FOREGROUND_WAIT_S, _FOREGROUND_POLL_S = 1.0, 0.05


class _CursorPoint(ctypes.Structure):
    """``POINT`` for ``GetCursorPos``/``SetCursorPos``.

    Declared here rather than imported from ``ctypes.wintypes``: that module is not
    importable on a host without Windows headers, and this module has to import
    cleanly anywhere (the ``ctypes`` description is portable).
    """

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _ClipRect(ctypes.Structure):
    """``RECT`` for ``GetClipCursor`` — the rectangle the cursor is confined to.

    An empty rectangle (``right <= left`` or ``bottom <= top``) is *no clip*: on a
    desktop that is not clipped ``GetClipCursor`` answers the screen rectangle, which
    contains every point the driver ever asks for. Declared here rather than imported
    from ``ctypes.wintypes`` for the same reason as :class:`_CursorPoint`.
    """

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@lru_cache(maxsize=1)
def _gui():
    """``(win32gui, win32con)`` — loaded inside a function so the module imports anywhere."""
    import win32con
    import win32gui

    return win32gui, win32con


@lru_cache(maxsize=1)
def _user32():
    """``user32`` with its message and cursor signatures bound once.

    ``ctypes.windll`` only exists on Windows, so it is touched here — never at import
    time — and the argument types are declared so a 64-bit ``lParam`` (a buffer address)
    is not truncated.
    """
    u32 = ctypes.windll.user32  # type: ignore[attr-defined]
    u32.SendMessageTimeoutW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    )
    u32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    u32.PostMessageW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )
    u32.PostMessageW.restype = ctypes.c_ssize_t
    # The real-cursor gesture the menubar needs (``SetCursorPos`` + ``mouse_event``,
    # with the read-back that proves the jump took). ``mouse_event``'s ``dwExtraInfo``
    # is a ``ULONG_PTR``, so ``c_size_t``; its restype is ``None``.
    u32.GetCursorPos.argtypes = (ctypes.POINTER(_CursorPoint),)
    u32.GetCursorPos.restype = ctypes.c_int
    u32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    u32.SetCursorPos.restype = ctypes.c_int
    u32.mouse_event.argtypes = (
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_size_t,
    )
    u32.mouse_event.restype = None
    # The cursor *clip*: this application confines the pointer while its blocking popups
    # are up (docs/dop3000/udop-automation.md §6), and ``SetCursorPos`` to a point outside
    # that rectangle is silently clamped to the clip's edge — which is what parked a live
    # run's cursor in the open menu's bottom-left corner. ``ClipCursor(NULL)`` releases
    # the clip, so it is declared with a void pointer (only ``None`` is ever passed).
    u32.GetClipCursor.argtypes = (ctypes.POINTER(_ClipRect),)
    u32.GetClipCursor.restype = ctypes.c_int
    u32.ClipCursor.argtypes = (ctypes.c_void_p,)
    u32.ClipCursor.restype = ctypes.c_int
    return u32


def _clip_rect(*, user32=_user32) -> tuple[int, int, int, int] | None:
    """The rectangle the cursor is currently confined to, or ``None`` for no clip.

    This application sets ``ClipCursor`` while its blocking popups are up
    (docs/dop3000/udop-automation.md §6), and a ``SetCursorPos`` outside that
    rectangle is silently clamped to its edge — which is what parked a live run's
    cursor in the open menu's bottom-left corner and then made a menubar hover
    impossible. Read before every real move, and again when a move refuses, so the
    clip is a *named* fact rather than a guess.

    An empty rectangle, a failed read and a host without the call all answer ``None``:
    an unreadable clip is not evidence of a locked desktop, and the move's own
    read-back stays the authority.
    """
    rect = _ClipRect()
    try:
        if not user32().GetClipCursor(ctypes.byref(rect)):
            return None
    except Exception:  # noqa: BLE001 - no readable clip; the read-back still decides
        return None
    box = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    return None if box[2] <= box[0] or box[3] <= box[1] else box


def _release_clip(*, user32=_user32) -> bool:
    """``ClipCursor(NULL)``: drop the application's own confinement of the cursor.

    Called only when the driver is about to move the cursor somewhere the clip forbids
    (a move, or a restore) — never as a matter of course, so an open dialog keeps the
    clip it wants. A release that fails is not raised here: the caller's read-back and
    its failure message are what report it, naming the clip it could not clear.
    """
    try:
        user32().ClipCursor(None)
    except Exception:  # noqa: BLE001 - reported by the caller's failure, not hidden
        return False
    return True


def _cursor_position(*, user32=_user32) -> tuple[int, int]:
    """The operator's cursor position, in screen coordinates.

    Read before any real move, so the move can be undone
    (:func:`_restore_cursor`). An unreadable position is refused rather than
    ignored: a cursor moved with no way back is the operator's cursor taken, and
    that is worse than a failed point.
    """
    point = _CursorPoint()
    if not user32().GetCursorPos(ctypes.byref(point)):
        raise _acquisition_error()(
            "the cursor position could not be read, so the real-cursor hover this "
            "menubar needs would move the operator's cursor with no way back"
        )
    return int(point.x), int(point.y)


def _restore_cursor(
    position: tuple[int, int],
    *,
    note: Callable[[str], None],
    inside: Callable[[tuple[int, int, int, int], tuple[int, int]], bool],
    clip: Callable[..., tuple[int, int, int, int] | None],
    release: Callable[..., bool],
    read_position: Callable[..., tuple[int, int]],
    user32=_user32,
) -> None:
    """Put the operator's cursor back where :func:`_cursor_position` found it.

    **Not into a clip.** This application confines the pointer while its popups are up,
    and a restore is a ``SetCursorPos`` like any other: restored from inside a popup's
    clip, it is silently clamped to the clip's edge — the live run's cursor was put
    back "at" its own position and landed in the open menu's bottom-left corner. So a
    clip that does not *contain* the operator's position is released with
    ``ClipCursor(NULL)`` before the restore; a clip that already contains it is left
    alone, because the restore cannot be trapped by it and an open dialog is entitled
    to the clip it set.

    ``inside`` is the edge-inclusive clip test and ``note`` the facade's diagnostic
    sink: both are passed in, so this package imports no interpreter and raises nothing.

    Nothing here is raised: this runs from a ``finally``, and masking the real failure
    would be worse than a cursor left where it is. When a clip *was* up, the restore is
    read back and an unfaithful one is recorded instead.
    """
    point = (int(position[0]), int(position[1]))
    clip_now = clip()
    if clip_now is not None and not inside(clip_now, point):
        note(
            f"the operator's cursor at {point} lies outside the clip {clip_now} this "
            "application set on its popup; released the clip (ClipCursor(NULL)) so "
            "the restore is not trapped inside that rectangle"
        )
        release()
    user32().SetCursorPos(*point)
    time.sleep(_CURSOR_SETTLE_S)
    if clip_now is None:
        return
    try:
        landed = read_position()
    except _acquisition_error() as exc:
        note(f"the cursor restore could not be read back: {exc}")
        return
    if landed != point:
        note(
            f"the operator's cursor is at {landed} after the restore rather than "
            f"{point}: a second clip {clip()} is up — this runs on the "
            "operator's desktop, so their cursor may have to be put back by hand"
        )


def _move_real_cursor(
    point: tuple[int, int],
    *,
    what: str,
    why: str,
    note: Callable[[str], None],
    inside: Callable[[tuple[int, int, int, int], tuple[int, int]], bool],
    clip: Callable[..., tuple[int, int, int, int] | None],
    release: Callable[..., bool],
    read_position: Callable[..., tuple[int, int]],
    user32=_user32,
) -> tuple[int, int]:
    """Move the **real** cursor onto ``point``, clearing any clip that traps it.

    This application clips the cursor on its blocking popups, so a move is never just
    ``SetCursorPos``: the clip is read first and, when ``point`` lies outside it,
    released — a clip clamps the move to its edge instead of refusing it, which looks
    exactly like a cursor that "would not move". A move that still does not take is
    released and retried once for the same reason. Only then is a failure raised, and
    it **names the clip rectangle and the target point**; a failure with no clip up is
    the locked-or-unattended-desktop case, which is named as such — attributing a
    clamp to a locked desktop is what sent the live run looking in the wrong place.
    """
    x, y = int(point[0]), int(point[1])
    target = (x, y)
    u32 = user32()
    clip_now = clip()
    if clip_now is not None and not inside(clip_now, target):
        note(
            f"the cursor is clipped to {clip_now} (this application clips it on its "
            f"popups) and {target} lies outside that rectangle; released the clip "
            "with ClipCursor(NULL) so the move is not clamped to the popup's edge"
        )
        release()
    u32.SetCursorPos(x, y)
    time.sleep(_HOVER_SETTLE_S)
    if read_position() == target:
        return target
    # The move did not take. If a clip is up it is the cause — the application can set
    # it again between the read above and the move — so release and try once more.
    clip_now = clip()
    if clip_now is not None:
        release()
        u32.SetCursorPos(x, y)
        time.sleep(_HOVER_SETTLE_S)
        if read_position() == target:
            return target
        clip_now = clip()
    if clip_now is not None:
        raise _acquisition_error()(
            f"the cursor would not move onto {what} at {target}: the application "
            f"clips the cursor to {clip_now} and the point lies outside that rectangle, "
            "so SetCursorPos is clamped to the clip's edge; releasing the clip "
            "(ClipCursor(NULL)) did not free it either, so this is the application's "
            "own popup clamp — not a locked or unattended desktop, which reports a "
            "move that never happened rather than one clamped to a rectangle"
        )
    raise _acquisition_error()(
        f"the cursor would not move onto {what} at {target}: no cursor clip is set, "
        f"so a locked or unattended desktop refused SetCursorPos — {why}"
    )


def _foreground_window(*, user32=_user32) -> int:
    """The foreground window's handle — the menubar hover's **precondition**.

    Read through the facade's own method so a fake can script a window sitting in front:
    a precondition that cannot be scripted cannot be tested, and this one is invisible
    from the control tree (measured live 2026-09-17: `recon/53`).
    """
    return user32().GetForegroundWindow()


def _thread_of(hwnd: int, *, user32=_user32) -> int:
    """The thread that owns ``hwnd``.

    ``win32process.GetWindowThreadProcessId`` is ``pywin32``'s home for this call and
    returns ``(threadId, processId)`` — **thread first**, despite the name — but the
    driver reaches Windows through ``ctypes`` here, so bringing a window forward needs
    no extra import and works wherever the message layer does.
    """
    owner = ctypes.c_ulong()
    user32().GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
    return int(owner.value)


def _activate_window(hwnd: int, *, user32=_user32) -> None:
    """Ask Windows to make ``hwnd`` the foreground window.

    The documented route, because ``SetForegroundWindow`` returns 0 from a process the
    user is not interacting with (the foreground lock): attach our thread's input to the
    current foreground thread, ask, detach. Returns regardless — what the call *did* is
    checked by reading the foreground window back, never by trusting the return value.
    """
    u32 = user32()
    front = u32.GetForegroundWindow()
    target_thread = _thread_of(hwnd, user32=user32)
    front_thread = _thread_of(front, user32=user32) if front else 0
    attached = bool(front_thread) and front_thread != target_thread
    try:
        if attached:
            u32.AttachThreadInput(front_thread, target_thread, True)
        u32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    finally:
        if attached:
            u32.AttachThreadInput(front_thread, target_thread, False)


def _require_foreground(
    hwnd: int,
    class_name: str,
    *,
    foreground: Callable[[], int],
    activate: Callable[[int], None],
    gui=_gui,
) -> None:
    """Assert the application is the **foreground** window before hovering it.

    **Measured live 2026-09-17:** with a console window in front — the scheduled task's
    own ``cmd.exe``, the one route that can reach this desktop from a session-0 shell —
    the application reported ``is_foreground=False, has_focus=False``; the driver then
    moved the real cursor onto the ``Parameters`` button and **no popup appeared**,
    while the identical gesture had opened it minutes earlier with the operator having
    just clicked inside the application. An inactive window ignores hover: its first
    mouse event activates it and the menu opens only on the *second*. The failure was
    therefore indistinguishable from "this gesture does not work" and cost a live slot,
    which is exactly what a named precondition is for.

    So: the window is brought forward (:func:`_activate_window`) and the foreground window
    is re-read; if it is still not this one, the run **refuses**, naming what is in front.
    This is the one place the driver takes the user's focus, and it does it on purpose —
    the menubar is hover-driven, so the application must be the active window for the
    step to mean anything.
    """
    if foreground() == hwnd:
        return
    activate(hwnd)
    deadline = time.monotonic() + _FOREGROUND_WAIT_S
    while time.monotonic() < deadline:
        if foreground() == hwnd:
            return
        time.sleep(_FOREGROUND_POLL_S)
    win32gui, _ = gui()
    front = foreground()
    try:
        front_cls = win32gui.GetClassName(front) if front else "none"
    except Exception:  # noqa: BLE001
        front_cls = "unknown"
    raise _acquisition_error()(
        f"the {class_name} window is not the foreground window, so its menubar "
        f"cannot be hovered: the foreground window is {front:#x} ({front_cls!r}) and "
        f"activating {hwnd:#x} did not take it within {_FOREGROUND_WAIT_S:.1f} s — "
        "Windows' foreground lock refuses a request from a process the user is not "
        "interacting with. This application ignores a hover while it is inactive (its "
        "first mouse event only activates it), so the run stops here rather than "
        "hovering into a window that cannot answer. Bring the application to the front "
        "— and stop anything that steals it, such as a console window opened by the "
        "launcher — then re-run"
    )


def _hover_centre(
    hwnd: int,
    *,
    what: str,
    why: str,
    move: Callable[..., tuple[int, int]],
    gui=_gui,
    user32=_user32,
) -> tuple[int, int]:
    """Hover ``hwnd`` with the **real** cursor; return the screen point hovered.

    The menubar is the one control in this application that posted messages cannot
    drive: a posted ``WM_MOUSEMOVE`` opened nothing, and a posted press held for
    :data:`~udv_echo_process.acquire.actuator.PRESS_HOLD_MS` opened nothing either (two
    live runs, both aborting safely with nothing pressed), while the same button opened
    its menu under the operator's real cursor in ``recon/41_burst_sampling_volume.py``.
    This copies that gesture exactly, in that order: the control's centre in **screen**
    coordinates (``win32gui.GetWindowRect``), ``SetCursorPos``, the recipe's 0.3 s
    settle, one ``mouse_event`` relative move of :data:`_HOVER_MOVE_DX` px, then the
    recipe's 1.0 s settle before the caller polls for the popup.

    The cursor now sits on the control, so the caller puts it back with
    :func:`~udv_echo_process.acquire.driver.Win32Actuator._restore_cursor` — this runs on
    the operator's interactive desktop. The move itself goes through the caller's own
    ``move`` (the facade's :func:`~udv_echo_process.acquire.driver.Win32Actuator._move_real_cursor`),
    so the clip this application sets on an open popup cannot clamp the cursor short of
    the button and be mistaken for a locked desktop: the menubar button is *outside* any
    open popup's clip, which is precisely the move the live run could not make. ``what``
    and ``why`` are the caller's own words for the control and for why nothing is posted
    to it — this module names no UDOP surface.
    """
    win32gui, _ = gui()
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    x, y = (left + right) // 2, (top + bottom) // 2
    move((x, y), what=what, why=why)
    user32().mouse_event(MOUSEEVENTF_MOVE, _HOVER_MOVE_DX, _HOVER_MOVE_DY, 0, 0)
    time.sleep(_HOVER_OPEN_S)
    return x, y
