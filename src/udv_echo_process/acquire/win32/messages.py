"""The message transport: bounded sends, the posted gestures, and the write recipes.

Layer 3 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5): the
**mechanics** that put a message on the operator's desktop, and nothing that decides what to
send. Moved out of :mod:`udv_echo_process.acquire.driver` verbatim — these bodies are ports of
the verified ``recon`` recipes, so they are moved and never re-derived:

- **every send is bounded** (:func:`_send`, ``SendMessageTimeoutW`` +
  :data:`SMTO_ABORTIFHUNG`): a plain ``SendMessage`` to a busy target thread blocks the caller
  indefinitely (docs/16 §1), so there is no such call in this package;
- **a press is held** (:func:`_click_hold`): ``WM_LBUTTONDOWN`` with ``MK_LBUTTON`` —
  :data:`~udv_echo_process.acquire.actuator.PRESS_HOLD_MS` — ``WM_LBUTTONUP``, with ``lParam``
  in the control's **client** coordinates, on the control's own handle. An instant down/up in
  the same millisecond is ignored by the strip, which is the whole reason the press is not a
  click;
- **a write is committed** (:func:`_set_text_commit`): ``WM_SETTEXT`` alone changes a control's
  text while the application keeps its own value, so the ``EN_CHANGE`` command and the
  ``VK_RETURN`` key event follow it — the committed order of
  :data:`~udv_echo_process.acquire.actuator.NUMERIC_WRITE_RECIPE`, compared at the bottom of
  this module so the port cannot drift from it;
- **a combo commits on its change notification** (:func:`_combo_select`): ``CB_SETCURSEL`` plus
  a ``WM_COMMAND``/``CBN_SELCHANGE`` notification, and deliberately **no** key event — a key
  event on this path would re-trigger whatever the Enter handler does;
- the combo **read-back** (:func:`_combo_index`, :func:`_combo_items`) and the id bookkeeping
  (:func:`_control_id`: the id only ever as the low word of ``WM_COMMAND``, never as an
  identity — ids change on every launch).

**What this module may not know.** No UDOP parameter, no strip view or role, no
``Operating parameters`` field, no campaign, no store path: a mechanic here takes a handle and a
value. Nothing in this package imports ``acquire.ui``, ``campaign``, ``runner`` or ``verify``,
and nothing here reads a caption — every ``TSp_*`` widget in this application is caption-less.

**The seam, and why every body takes one.** ``ctypes.windll`` and ``win32gui`` are touched
**only inside functions** — :func:`~udv_echo_process.acquire.win32.cursor._user32` and ``_gui``,
which this module imports from :mod:`~udv_echo_process.acquire.win32.cursor`: one lazy handle
resolution, moved whole rather than split. So importing this module on a host with no Windows
and no ``pywin32`` loads neither. Each function that needs a transport takes it as a
keyword-only **parameter** (defaulting to this package's own laziness) instead of reaching for
the caller's module global: ``driver.py`` hands over its own ``_gui``/``_user32``/``_post`` (and
the calling method for ``send``), which is what keeps every caller and every test that fakes
those names on the facade working while the bodies underneath moved.

The facade (:mod:`udv_echo_process.acquire.driver`) imports every name below back into its own
namespace, so ``driver._send``, ``driver.WM_LBUTTONDOWN``, ``driver._click_hold`` and the rest
still resolve (``docs/dop3000/acquisition-architecture.md`` §5, *compatibility first*).
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable

from udv_echo_process.acquire.actuator import (
    NUMERIC_WRITE_RECIPE,
    PRESS_HOLD_MS,
)
from udv_echo_process.acquire.win32.cursor import _gui, _user32

__all__ = [
    "CBN_SELCHANGE",
    "CB_GETCOUNT",
    "CB_GETCURSEL",
    "CB_GETLBTEXT",
    "CB_SETCURSEL",
    "EN_CHANGE",
    "MK_LBUTTON",
    "SEND_TIMEOUT_MS",
    "SMTO_ABORTIFHUNG",
    "VK_RETURN",
    "WM_COMMAND",
    "WM_GETTEXT",
    "WM_KEYDOWN",
    "WM_KEYUP",
    "WM_LBUTTONDOWN",
    "WM_LBUTTONUP",
    "WM_MOUSEMOVE",
    "WM_SETTEXT",
    "_CLICK_SETTLE_S",
    "_COMBO_NONE_ABOVE",
    "_COMBO_SETTLE_S",
    "_COMMIT_RECIPE",
    "_TEXT_COMMIT_SETTLE_S",
    "_TEXT_SETTLE_S",
    "_VK_RETURN_DOWN_LPARAM",
    "_VK_RETURN_UP_LPARAM",
    "_click_hold",
    "_combo_index",
    "_combo_items",
    "_combo_select",
    "_control_id",
    "_get_text",
    "_post",
    "_send",
    "_set_text_commit",
]

WM_SETTEXT, WM_GETTEXT, WM_COMMAND = 0x000C, 0x000D, 0x0111
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0201, 0x0202, 0x0001
#: Deliberately **unused**: this application's menubar ignores posted messages — a
#: posted move opened nothing (and so did a posted press), while the same button opened
#: its menu under the *real* cursor hover
#: (:func:`~udv_echo_process.acquire.win32.cursor._hover_centre`) — so nothing here sends
#: this. It is named so the tests can assert that no move is posted while a menu is being
#: opened.
WM_MOUSEMOVE = 0x0200
EN_CHANGE, CBN_SELCHANGE, CB_SETCURSEL = 0x0300, 0x0001, 0x014E
#: Combo *read-back* messages: the selected index, the item count, one item's text.
CB_GETCOUNT, CB_GETCURSEL, CB_GETLBTEXT = 0x0146, 0x0147, 0x0148
VK_RETURN, SMTO_ABORTIFHUNG = 0x0D, 0x0002
#: A `CB_GETCURSEL`/`CB_GETCOUNT` answer above this is not an index or a count: the
#: value comes back through an unsigned ``LRESULT``, so ``CB_ERR`` (-1) arrives as a
#: huge number. Treating it as "no selection" is the only safe reading.
_COMBO_NONE_ABOVE = 0xFFFF

#: Every send is bounded; a hung target returns instead of blocking (docs/16 §1).
SEND_TIMEOUT_MS = 2000
#: The key-event lParams the verified recipe used (scan code / transition packed).
_VK_RETURN_DOWN_LPARAM, _VK_RETURN_UP_LPARAM = 0x001C0001, 0xC01C0001

#: What :func:`_set_text_commit` sends, in order — compared below so the
#: port cannot drift from the committed recipe.
_COMMIT_RECIPE = (
    "WM_SETTEXT",
    "WM_COMMAND(EN_CHANGE)",
    "WM_KEYDOWN(VK_RETURN)",
    "WM_KEYUP(VK_RETURN)",
)
assert _COMMIT_RECIPE == tuple(NUMERIC_WRITE_RECIPE), (
    "NUMERIC_WRITE_RECIPE changed; the driver must follow the committed recipe"
)

#: Settle times from the reference script — they are what make the recipes reliable (a
#: command posted in the same millisecond as the text is lost).
_TEXT_SETTLE_S, _TEXT_COMMIT_SETTLE_S = 0.08, 0.25
#: A combo *change notification* needs the reference's own settle before the selection is
#: read back (``recon/41_burst_sampling_volume.py``: ``CB_SETCURSEL`` + ``CBN_SELCHANGE``,
#: then ``time.sleep(0.8)``). The channel is decided on this path and a write can silently
#: not apply, so it is the reference's 0.8 s, not the shorter text-write settle.
_COMBO_SETTLE_S = 0.8
#: The settle after a held press. ``driver.py`` keeps the overlay/poll settles next to the
#: loops that use them; this one belongs to the gesture below.
_CLICK_SETTLE_S = 0.35


def _send(
    hwnd: int,
    msg: int,
    wp: int = 0,
    lp: int = 0,
    timeout_ms: int = SEND_TIMEOUT_MS,
    *,
    user32=_user32,
) -> int:
    """``SendMessageTimeoutW``, never a plain ``SendMessage``.

    A busy target thread blocks ``SendMessage`` forever; this returns 0 on hang or
    timeout. ``lp`` may be a ctypes buffer address (``WM_SETTEXT``/``WM_GETTEXT``).
    """
    result = ctypes.c_size_t(0)
    user32().SendMessageTimeoutW(
        ctypes.c_void_p(hwnd),
        msg,
        wp,
        lp,
        SMTO_ABORTIFHUNG,
        timeout_ms,
        ctypes.byref(result),
    )
    return int(result.value)


def _post(hwnd: int, msg: int, wp: int = 0, lp: int = 0, *, user32=_user32) -> None:
    """Post a message (key events and ``WM_COMMAND`` are posted, as verified)."""
    user32().PostMessageW(ctypes.c_void_p(hwnd), msg, wp, lp)


def _get_text(hwnd: int, *, send: Callable[..., int] = _send) -> str:
    """The control's own text (``WM_GETTEXT``, bounded)."""
    buf = ctypes.create_unicode_buffer(256)
    send(hwnd, WM_GETTEXT, 256, ctypes.addressof(buf))
    return buf.value


def _control_id(hwnd: int, *, gui=_gui) -> int:
    """The id only as the field *inside* ``WM_COMMAND`` — never as an identity."""
    win32gui, _ = gui()
    cid = win32gui.GetDlgCtrlID(hwnd)
    return ctypes.c_short(cid).value if cid > 32767 else cid


def _set_text_commit(
    hwnd: int,
    text: str,
    parent: int | None = None,
    *,
    send: Callable[..., int] = _send,
    post: Callable[..., None] = _post,
    gui=_gui,
) -> None:
    """Write ``text`` and **commit** it: the recipe in ``NUMERIC_WRITE_RECIPE``.

    ``WM_SETTEXT`` alone changes the control's text while the application keeps its
    own value; the ``EN_CHANGE`` command and the ``VK_RETURN`` key event are what make
    the model take the new value (docs/14 §4, docs/16 §12a).
    """
    win32gui, _ = gui()
    if parent is None:
        parent = win32gui.GetParent(hwnd)
    buf = ctypes.create_unicode_buffer(text)
    send(hwnd, WM_SETTEXT, 0, ctypes.addressof(buf))
    time.sleep(_TEXT_SETTLE_S)
    post(
        parent,
        WM_COMMAND,
        (EN_CHANGE << 16) | (_control_id(hwnd, gui=gui) & 0xFFFF),
        hwnd,
    )
    time.sleep(_TEXT_SETTLE_S)
    post(hwnd, WM_KEYDOWN, VK_RETURN, _VK_RETURN_DOWN_LPARAM)
    post(hwnd, WM_KEYUP, VK_RETURN, _VK_RETURN_UP_LPARAM)
    time.sleep(_TEXT_COMMIT_SETTLE_S)


def _combo_select(
    hwnd: int,
    index: int,
    parent: int | None = None,
    *,
    send: Callable[..., int] = _send,
    post: Callable[..., None] = _post,
    gui=_gui,
) -> None:
    """Select a combo entry: ``CB_SETCURSEL`` + ``CBN_SELCHANGE``, **no Enter**.

    A combo commits on the change notification; a key event here would re-trigger
    whatever the Enter handler does. The settle after the notification is the
    reference's own :data:`_COMBO_SETTLE_S` (0.8 s) — the shorter text-write settle
    was never proven on this path, and this is the path that decides the channel.
    """
    win32gui, _ = gui()
    if parent is None:
        parent = win32gui.GetParent(hwnd)
    send(hwnd, CB_SETCURSEL, index, 0)
    time.sleep(_TEXT_SETTLE_S)
    post(
        parent,
        WM_COMMAND,
        (CBN_SELCHANGE << 16) | (_control_id(hwnd, gui=gui) & 0xFFFF),
        hwnd,
    )
    time.sleep(_COMBO_SETTLE_S)


def _click_hold(
    hwnd: int,
    hold_ms: int = PRESS_HOLD_MS,
    *,
    post: Callable[..., None] = _post,
    gui=_gui,
) -> tuple[int, int] | None:
    """Press and **hold** a control: down, ``hold_ms``, up.

    An instant down/up in the same millisecond is ignored by the strip (that is
    exactly what every early attempt sent, docs/16 §1). ``lParam`` is in the target's
    client coordinates, so the centre comes from ``GetClientRect`` and is converted to
    screen only so a failure can be reported in real screen terms.

    Returns the screen point the press was aimed at — ``None`` when the application
    would not say (the caller keeps it as a diagnostic and never as a binding). The
    read happens *before* the down message, in the same order it always has.
    """
    win32gui, _ = gui()
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    x, y = (right - left) // 2, (bottom - top) // 2
    try:
        press_screen = win32gui.ClientToScreen(hwnd, (x, y))
    except Exception:  # noqa: BLE001 - diagnostic only
        press_screen = None
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(max(0, int(hold_ms)) / 1000.0)
    post(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(_CLICK_SETTLE_S)
    return press_screen


def _combo_index(hwnd: int, *, send: Callable[..., int] = _send) -> int:
    """The combo's selected index, or ``-1`` when it has no selection.

    ``CB_GETCURSEL`` answers ``CB_ERR`` (-1) through an unsigned result, so a
    value above :data:`_COMBO_NONE_ABOVE` means *no selection*, never a huge
    index. This is the control's own belief, which is why it is never the only
    read-back (:meth:`~udv_echo_process.acquire.driver.Win32Actuator._channel_readback`).
    """
    raw = send(hwnd, CB_GETCURSEL, 0, 0)
    return -1 if raw > _COMBO_NONE_ABOVE else raw


def _combo_items(hwnd: int, *, send: Callable[..., int] = _send) -> tuple[str, ...]:
    """Every item the combo holds, in order (``CB_GETCOUNT`` + ``CB_GETLBTEXT``).

    The item *list* is how the channel combo is identified, so it is read rather
    than assumed; a nonsense count is an empty list, not a spin.
    """
    count = send(hwnd, CB_GETCOUNT, 0, 0)
    if count <= 0 or count > _COMBO_NONE_ABOVE:
        return ()
    items: list[str] = []
    for index in range(count):
        buf = ctypes.create_unicode_buffer(64)
        send(hwnd, CB_GETLBTEXT, index, ctypes.addressof(buf))
        items.append(buf.value)
    return tuple(items)
