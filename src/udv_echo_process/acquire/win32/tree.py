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

from udv_echo_process.acquire.ui.model import UiNode
from udv_echo_process.acquire.win32 import _acquisition_error
from udv_echo_process.acquire.win32.cursor import _gui

__all__ = [
    "_children_of",
    "_descendants_of",
    "_hidden_panels",
    "_is_visible",
    "_main_hwnd",
    "_visible_children",
    "ui_nodes",
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
