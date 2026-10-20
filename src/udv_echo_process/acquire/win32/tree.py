"""The control tree: enumerating the window, its children and their visibility.

Layer 3 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5): the
**mechanics** of looking at a window, moved out of
:mod:`udv_echo_process.acquire.driver` verbatim. Nothing here decides what a control *means* —
which surface is up, which button is which — and nothing here presses anything: the rows these
functions return are the raw material the resolver binds roles against and the pure
interpreters under :mod:`udv_echo_process.acquire.ui` read.

Two rules are structural, and both were paid for live:

1. **Presence is not visibility.** This application pre-creates the ``Parameters`` popup panel
   in its control tree with ``IsWindowVisible == False`` and only *shows* it on the menubar
   hover, so :func:`_visible_children` filters and :func:`_hidden_panels` names what the filter
   left out (:func:`_is_visible` is the single question both ask). Pressing at a pre-created
   panel's rect puts coordinates into empty screen, which is what a live run did.
2. **A rect belongs to the moment it was read.** The strip is draggable and morphs
   (``98x40`` → ``352x40`` → ``413x123``), so a row is a reading: rows are diagnostics and the
   *visible* projection is what may be bound, never a captured rectangle bound as a constant.

:func:`_main_hwnd` finds the application window itself (the largest visible window of the
resolved class), :func:`_children_of` answers "whose parent is this handle" **from the resolve's
own tree** rather than by re-enumerating the window, and :func:`_descendants_of` walks live
one level past the resolver's direct children — the ``Operating parameters`` dialog states its
table one level in, and a read built on the direct children sees a dialog with no table at all.

**The one ``acquire/ui`` import, and why it is a *type* only.** :func:`ui_nodes` projects these
rows onto :class:`~udv_echo_process.acquire.ui.model.UiNode` — one call per row into the
projection the model itself uses, with no rule of its own: no rectangle is re-read, no surface
is classified, no DOP name appears. That is the whole dependency (the ``win32/`` → ``ui/``
direction the architecture document allows for node normalization and nothing else), and it is
one-way: ``ui/model.py`` does not import this package.

**The seam.** Every function takes the ``win32gui`` handle resolution it needs as a keyword-only
parameter (``gui``, defaulting to this package's own lazily resolved
:func:`~udv_echo_process.acquire.win32.cursor._gui`), so ``driver.py`` can hand over the name
every existing caller and test fakes while the bodies underneath moved, and so the module
imports on a host with no Windows and no ``pywin32`` (no enumeration, no ``FindWindow`` and no
``ctypes.windll`` load happens at import time). The one exception raised here is the facade's
own ``AcquisitionError``, resolved inside the raise by
:func:`~udv_echo_process.acquire.win32._acquisition_error`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.ui.model import UiNode
from udv_echo_process.acquire.win32 import _acquisition_error
from udv_echo_process.acquire.win32.cursor import _gui, _owner_of

__all__ = [
    "_children_of",
    "_descendants_of",
    "_hidden_panels",
    "_is_visible",
    "_main_hwnd",
    "_visible_children",
    "target_mismatch",
    "ui_nodes",
    "validate_target",
    "window_target",
]


def _visible_children(win: int, *, gui=_gui) -> list[dict]:
    """Every visible descendant with a real area, in screen coordinates."""
    win32gui, _ = gui()
    out: list[dict] = []

    def cb(h, _lparam):
        try:
            if win32gui.IsWindowVisible(h):
                left, top, right, bottom = win32gui.GetWindowRect(h)
                if right - left >= 2 and bottom - top >= 2:
                    out.append(
                        {
                            "hwnd": h,
                            "cls": win32gui.GetClassName(h),
                            "text": win32gui.GetWindowText(h),
                            "rect": (left, top, right, bottom),
                            "left": left,
                            "top": top,
                            "w": right - left,
                            "h": bottom - top,
                            "id": win32gui.GetDlgCtrlID(h),
                        }
                    )
        except Exception:  # noqa: BLE001, S110
            pass
        return True

    win32gui.EnumChildWindows(win, cb, None)
    return out


def _is_visible(hwnd: int, *, gui=_gui) -> bool:
    """``IsWindowVisible`` for one handle — presence is **not** visibility.

    This application pre-creates the ``Parameters`` popup panel in its control tree and
    shows it on the hover, so a control can be *present* and reported by an enumeration
    that ignores visibility while nothing is painted at its rect. Pressing there puts the
    coordinates into empty screen — which is exactly what a live run did. An unreadable
    answer is ``False``: only a positive ``True`` is accepted as proof.
    """
    win32gui, _ = gui()
    try:
        return bool(win32gui.IsWindowVisible(hwnd))
    except Exception:  # noqa: BLE001 - an unreadable answer is not a positive one
        return False


def _hidden_panels(win: int, *, gui=_gui) -> list[dict]:
    """Every ``TSp_Panel`` in the window's tree that is **not** visible, in the tree.

    The companion to :func:`_visible_children`: the same walk without the visibility
    filter, so a pre-created panel can be *named* in a refusal instead of being mistaken
    for the open menu (the live failure of the previous fix cycle). Nothing here is ever
    pressed — a hidden panel is evidence, not a target.
    """
    win32gui, _ = gui()
    out: list[dict] = []

    def cb(h, _lparam):
        try:
            hidden = not win32gui.IsWindowVisible(h)
            if win32gui.GetClassName(h) == "TSp_Panel" and hidden:
                left, top, right, bottom = win32gui.GetWindowRect(h)
                out.append(
                    {
                        "hwnd": h,
                        "cls": "TSp_Panel",
                        "rect": (left, top, right, bottom),
                        "left": left,
                        "top": top,
                        "w": right - left,
                        "h": bottom - top,
                        "id": win32gui.GetDlgCtrlID(h),
                    }
                )
        except Exception:  # noqa: BLE001, S110
            pass
        return True

    win32gui.EnumChildWindows(win, cb, None)
    return out


def _main_hwnd(class_name: str, *, gui=_gui) -> int:
    """Handle of the visible main window (largest if several exist)."""
    win32gui, _ = gui()
    found: list[tuple[int, int]] = []

    def cb(h, _lparam):
        try:
            if win32gui.GetClassName(h) == class_name and win32gui.IsWindowVisible(h):
                left, top, right, bottom = win32gui.GetWindowRect(h)
                found.append(((right - left) * (bottom - top), h))
        except Exception:  # noqa: BLE001, S110
            pass
        return True

    win32gui.EnumWindows(cb, None)
    if not found:
        raise _acquisition_error()(
            f"no visible {class_name} window — is UDOP on its startup screen?"
        )
    return max(found)[1]


def window_target(
    hwnd: int,
    class_name: str,
    *,
    gui=_gui,
    owner=_owner_of,
) -> WindowTarget:
    """Identify one caller-chosen window, or refuse naming why it cannot be a target.

    This is identification, not selection: the caller observed the handle (for example
    ``screen_fingerprint().hwnd``) and that observation is the authority. A handle is
    refused when it is gone, when it now answers another class, when no process owns it,
    or when it is not visible — the same four facts :func:`target_mismatch` re-checks
    before every operation. Neither a non-largest window nor a non-foreground one is
    refused: refusing those would reintroduce the selector this seam replaces.
    """
    try:
        win32gui, _ = gui()
    except Exception as exc:
        raise _acquisition_error()(f"could not verify target identity: {exc}") from exc
    if not _is_window(win32gui, hwnd):
        raise _acquisition_error()(_gone_clause(hwnd, class_name))
    try:
        actual = win32gui.GetClassName(hwnd)
    except Exception:  # noqa: BLE001 - a handle that cannot answer is gone
        raise _acquisition_error()(_gone_clause(hwnd, class_name)) from None
    if actual != class_name:
        raise _acquisition_error()(_class_clause(hwnd, class_name, actual))
    try:
        thread_id, process_id = owner(hwnd)
    except Exception as exc:
        raise _acquisition_error()(f"could not verify target identity: {exc}") from exc
    if not _complete_owner(thread_id, process_id):
        raise _acquisition_error()(
            f"the window {hex(hwnd)} has no owning thread/process — Windows returned "
            f"thread {thread_id}, pid {process_id}; refusing to drive an incomplete identity"
        )
    if not _is_visible(hwnd, gui=lambda: (win32gui, None)):
        raise _acquisition_error()(_hidden_clause(hwnd))
    return WindowTarget(
        hwnd=hwnd,
        thread_id=thread_id,
        process_id=process_id,
        class_name=class_name,
    )


def validate_target(
    target: WindowTarget,
    *,
    class_name: str | None = None,
    gui=_gui,
    owner=_owner_of,
) -> WindowTarget:
    """Check a record already in hand against the window it names; never re-identify it.

    This is the constructor's question, and it is the opposite of :func:`window_target`:
    ``window_target(hwnd)`` **captures** the identity a handle has now (the explicit
    ``bind_target`` route), whereas this function takes an identity recorded at an earlier
    moment and refuses when the handle no longer answers with it. The record is returned
    unchanged on success, so the caller keeps the evidence it supplied rather than silently
    adopting whatever process owns the handle at construction time.

    Refusal is total: a class that differs from the record (or from ``class_name``, the class
    this driver was constructed for), a zero/partial owning thread or process in the record,
    an owner read that raises, and any answer :func:`target_mismatch` names all raise
    :class:`AcquisitionError`. There is no fallback enumeration and no rebind.
    """
    if class_name is not None and target.class_name != class_name:
        raise _acquisition_error()(
            f"the recorded target window {hex(target.hwnd)} was recorded as class "
            f"{target.class_name!r}, but this driver drives {class_name!r} — refusing to "
            "reinterpret the record as a different window"
        )
    if not _complete_owner(target.thread_id, target.process_id):
        raise _acquisition_error()(
            f"the recorded target window {hex(target.hwnd)} carries no owning identity "
            f"(thread {target.thread_id}, pid {target.process_id}) — a record must hold the "
            "thread/process read when the window was chosen; bind_target captures it"
        )
    try:
        clause = target_mismatch(target, gui=gui, owner=owner)
    except Exception as exc:  # an unverifiable record is not a valid one
        raise _acquisition_error()(
            f"could not verify the recorded target window {hex(target.hwnd)} "
            f"({target.class_name}): {exc} — refusing to trust an identity that cannot be "
            "read"
        ) from exc
    if clause is not None:
        raise _acquisition_error()(clause)
    return target


def target_mismatch(
    target: WindowTarget,
    *,
    gui=_gui,
    owner=_owner_of,
) -> str | None:
    """Why ``target`` may no longer be driven, or ``None`` when it still may.

    The root-resolve check: role-map resolution uses this question. It does not
    revalidate individual child handles before every message or gesture. It returns
    a refusal clause so the caller can keep the facade's own error type.

    The check cannot see a handle recycled *within the same process* to another window of
    the same class owned by the same thread; that limit is stated on
    :class:`~udv_echo_process.acquire.actuator.WindowTarget` and is not claimed closed.
    """
    try:
        win32gui, _ = gui()
    except Exception as exc:  # noqa: BLE001 - boundary failure is a refusal clause
        return f"could not verify target identity: {exc}"
    if not _is_window(win32gui, target.hwnd):
        return _gone_clause(target.hwnd, target.class_name)
    try:
        actual = win32gui.GetClassName(target.hwnd)
    except Exception:  # noqa: BLE001 - a handle that cannot answer is gone
        return _gone_clause(target.hwnd, target.class_name)
    if actual != target.class_name:
        return _class_clause(target.hwnd, target.class_name, actual)
    try:
        thread_id, process_id = owner(target.hwnd)
    except Exception as exc:  # noqa: BLE001 - boundary failure is a refusal clause
        return f"could not verify target identity: {exc}"
    if not _complete_owner(thread_id, process_id):
        return f"the bound target has no complete owning identity (thread {thread_id}, pid {process_id})"
    if (thread_id, process_id) != (target.thread_id, target.process_id):
        return (
            f"the bound target window {hex(target.hwnd)} is now owned by pid {process_id}"
            f"/thread {thread_id}, not pid {target.process_id}/thread {target.thread_id} "
            "— the handle was recycled by another process; nothing was pressed"
        )
    if not _is_visible(target.hwnd, gui=lambda: (win32gui, None)):
        return _hidden_clause(target.hwnd)
    return None


def _complete_owner(thread_id: int, process_id: int) -> bool:
    return thread_id > 0 and process_id > 0


def _is_window(win32gui, hwnd: int) -> bool:
    """``IsWindow`` as a predicate: an unreadable answer is "gone", never "present"."""
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:  # noqa: BLE001
        return False


def _gone_clause(hwnd: int, class_name: str) -> str:
    return (
        f"the bound target window {hex(hwnd)} ({class_name}) no longer exists — UDOP was "
        "closed or restarted; re-bind to the window the driver should drive"
    )


def _class_clause(hwnd: int, class_name: str, actual: str) -> str:
    return (
        f"the bound target window {hex(hwnd)} is now class {actual!r}, not {class_name!r} "
        "— the handle was recycled; refusing to drive a different window"
    )


def _hidden_clause(hwnd: int) -> str:
    return (
        f"the bound target window {hex(hwnd)} is not visible — refusing to read a hidden "
        "target"
    )


def _children_of(parent: int, roles: dict, *, gui=_gui) -> list[dict]:
    """The already-enumerated children whose parent is ``parent``."""
    win32gui, _ = gui()
    return [k for k in roles["raw"] if win32gui.GetParent(k["hwnd"]) == parent]


def _descendants_of(hwnd: int, *, gui=_gui) -> list[dict]:
    """Every descendant of ``hwnd``, walked live — because the dialog's values are one level in.

    The resolver's own ``raw`` list stops at the **direct** children of a panel, and this
    dialog states nothing at that level: measured on the running application 2026-09-18, the
    ``Operating parameters`` dialog's 21 direct children are its 15 ``TSp_Value_Button``
    widgets, its header and its bottom buttons, and *no* control among them carries a value —
    each field's text lives in the ``TSp_Edit``/``TComboBox`` **inside** its value button. A
    read built on the resolver's children therefore sees a dialog with no table at all, which
    is exactly how it failed on the live application the first time, so the table is walked
    here instead.

    Rows carry what the rest of the driver's rows carry (class, rect, handle); the text is read
    separately by whoever needs it, through the same ``WM_GETTEXT`` reader as everywhere else.
    """
    win32gui, _ = gui()
    rows: list[dict] = []
    stack = [hwnd]
    while stack:
        parent = stack.pop()
        child = win32gui.GetWindow(parent, 5)  # GW_CHILD
        while child:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(child)
                rows.append(
                    {
                        "hwnd": child,
                        "cls": win32gui.GetClassName(child),
                        "left": left,
                        "top": top,
                        "w": right - left,
                        "h": bottom - top,
                    }
                )
                stack.append(child)
            except win32gui.error:  # a control that died mid-walk is not a failed read
                pass
            child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def ui_nodes(rows: Iterable[Mapping]) -> tuple[UiNode, ...]:
    """These rows as the normalized :mod:`udv_echo_process.acquire.ui.model` projection.

    The ``win32/`` → ``ui/`` direction the target layout allows for **node normalization and
    nothing else**, and it is deliberately thin: one call per row into
    :meth:`~udv_echo_process.acquire.ui.model.UiNode.from_row`, the projection the model itself
    uses, so no rectangle is parsed twice, no rule lives here and no DOP word appears. It adds
    no second path onto the model — the one place a *role map* is projected is
    ``ScreenObservation.from_roles``; this is the per-row half of that same projection, offered
    here because the enumeration is here.

    The enumeration functions above stay the row shape the resolver binds against (raw rows are
    diagnostics — invariant 5): this is the normalized form a *pure* interpreter reads, and it
    is what ``tests/test_acquire_win32_tree.py`` pins. It has no production caller yet — the
    live workflow layer that consumes it is the next patch's — and it is exported rather than
    inlined so that boundary is one name.
    """
    return tuple(UiNode.from_row(row) for row in rows)
