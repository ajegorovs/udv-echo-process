"""Drive the running UDOP application over Win32 messages: the live actuator.

This is the Windows half of :mod:`udv_echo_process.acquire` — the implementation that
satisfies :class:`~udv_echo_process.acquire.actuator.Actuator`. Everything here is a
*port* of three verified reference scripts, not a redesign: ``recon/udop_roles.py``
(resolving controls by class + position — never by control id, because ids change on
every launch: 43/43 classes at the same positions, 1/43 ids in common — and never by a
screen coordinate stated in logic), ``recon/40_sweep_depth100.py`` (the cycle:
``set_text_commit``, ``click_hold``, ``strip_view``, ``wait_view``, ``overlay_guard``,
``overwrite_warning``, ``record_stop_store``, ``get_text``, ``children_of``) and
``recon/41_burst_sampling_volume.py`` (the menubar: the popup opens on a **real-cursor
hover** — ``SetCursorPos`` onto the button's centre plus one ``mouse_event`` move, the
gesture that recipe opened this menu with — and its entries are ordered by their screen
``top`` before one is chosen — enumeration order is not screen order).

Three properties are load-bearing, each paid for once in the lab:

1. **Every send is bounded** (``SendMessageTimeoutW`` + ``SMTO_ABORTIFHUNG``): a plain
   ``SendMessage`` to a busy target thread blocks the caller indefinitely. Key and
   command events are *posted*.
2. **A strip press is held** (:data:`…actuator.PRESS_HOLD_MS`) and **a numeric write is
   committed** with the key event — ``WM_SETTEXT`` alone changes the control's text
   while the application keeps its own value.
3. **An overlay is checked before every press** (posted clicks ignore modality), and
   nothing here ``WM_CLOSE``\\ s a popup: an open popup is reported through
   :meth:`Win32Actuator.layout_note` and the run refuses to start instead.

``ctypes.windll`` and ``win32gui``/``win32con`` are touched **only inside functions**
(:func:`_user32`, :func:`_gui`), so this module imports cleanly on any host.
``pywinauto``, ``watchdog`` and ``PIL`` are not dependencies of this file.

Two further rules are enforced inside the cycle, both of them about *not measuring
something other than the point*:

4. **The measurement channel is verified before every point** (:meth:`Win32Actuator.ensure_channel`).
   It is one knob (:class:`~udv_echo_process.acquire.config.ChannelSetting`); the
   driver selects it in ``Parameters → Operating parameters`` and reads the
   selection back **from the dialog** — index *and* text — then re-opens the
   dialog to confirm the application kept it. A wrong channel produces a file
   that decodes as a valid point and is not the point (docs/16 §12, the channel
   trap), so a selection that cannot be verified fails the point instead.
5. **The Store dialog's ``Working directory`` is asserted, never assumed**
   (:meth:`Win32Actuator._ensure_working_directory`). The field decides where the
   point lands; if it differs from the directory the caller expects, it is written
   and read back, and an unresolved mismatch fails the point naming both paths.
   Watching a folder the application is not writing to surfaces as a false
   "no file appeared" failure (docs/16 §12b).

The menubar is the one step posted messages cannot drive at all: this application's
menubar ignores them (a posted move opened nothing, and neither did a posted press held
for :data:`…actuator.PRESS_HOLD_MS` — two live runs, both aborted safely with nothing
pressed), while the same button opened its menu under the operator's real cursor in
``recon/41_burst_sampling_volume.py``. That gesture moves the cursor, so it is gated:
``allow_real_input=False`` refuses the menubar step **by name** for an unattended or
locked-desktop run and never falls back to a posted message (which is known not to open
this menu).

The popup that hover opens is read **structurally**, because no control in this
application carries a caption: ``GetWindowText`` answers an empty string for every
``TSp_*`` widget — the live read of the open menu shows its overlay panel and its three
entries all caption-less — so an entry can never be found by a title. Matching one was
the live bug. Instead:

* the **overlay** is the panel that became visible when the menubar was hovered (the
  panel set is snapshotted first; the reference's own predicate, ``left == 169 and
  h > 120`` on the panel it read live at ``(169, 55, 401, 250)``, is the fallback when
  that diff is ambiguous);
* the **entries** are the ``TSp_Button`` widgets lying inside that overlay, ordered by
  screen ``top`` — enumeration order is *not* screen order — and the first is
  ``Operating parameters`` (entries at top 61, 95, 130);
* the **dialog** an entry opened is identified by its content: only the operating dialog
  holds the channel combo, and a dialog that does not hold it is closed with its LEFT
  button before the next entry by screen order is pressed. Its default button is never
  pressed — on the wrong dialog that button is what would commit the wrong dialog's
  values, and the wrong dialog is exactly the one that has not been identified yet.
"""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    DIALOG_ONLY_PARAMETERS,
    NUMERIC_WRITE_RECIPE,
    PARAM_COLUMN_ORDER,
    PRESS_HOLD_MS,
    STARTABLE_VIEWS,
    STORE_TIMEOUT_S,
    VIEW_TIMEOUT_S,
    Actuator,
    DialogControl,
    OverlayKind,
    ParamRole,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    ordered_writes,
    overlay_answer,
)
from udv_echo_process.acquire.config import (
    MAX_CHANNEL,
    MIN_CHANNEL,
    ChannelSetting,
    ParameterSet,
)

__all__ = ["AcquisitionError", "Win32Actuator", "channel_items", "same_directory"]

MAIN_CLASS = "TMain_Scr"
#: The menu bar's buttons, left -> right (``recon/udop_roles.py``).
MENU_ORDER: tuple[str, ...] = (
    "File",
    "Preferences",
    "Parameters",
    "Compute",
    "Cursors",
    "Filters",
    "Tools",
    "Channels",
    "UDV mode",
    "Display",
    "Help",
)
#: The left column's combo boxes, top -> bottom.
COMBO_ORDER: tuple[str, ...] = ("Sensitivity", "Emitting power")
#: The clean measurement screen's fingerprint (two independent launches); anything else
#: means a popup, a dialog or a simulator screen is up.
EXPECTED_CONTROL_COUNT = 43
EXPECTED_PANEL_COUNT = 4

WM_SETTEXT, WM_GETTEXT, WM_COMMAND = 0x000C, 0x000D, 0x0111
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0201, 0x0202, 0x0001
#: Deliberately **unused**: this application's menubar ignores posted messages — a
#: posted move opened nothing (and so did a posted press), while the same button opened
#: its menu under the *real* cursor hover (:meth:`Win32Actuator._hover_centre`) — so
#: nothing here sends this. It is named so the tests can assert that no move is posted
#: while a menu is being opened.
WM_MOUSEMOVE = 0x0200
EN_CHANGE, CBN_SELCHANGE, CB_SETCURSEL = 0x0300, 0x0001, 0x014E
#: Combo *read-back* messages: the selected index, the item count, one item's text.
CB_GETCOUNT, CB_GETCURSEL, CB_GETLBTEXT = 0x0146, 0x0147, 0x0148
VK_RETURN, SMTO_ABORTIFHUNG = 0x0D, 0x0002
#: A `CB_GETCURSEL`/`CB_GETCOUNT` answer above this is not an index or a count: the
#: value comes back through an unsigned ``LRESULT``, so ``CB_ERR`` (-1) arrives as a
#: huge number. Treating it as "no selection" is the only safe reading.
_COMBO_NONE_ABOVE = 0xFFFF
#: The menubar button, and the popup entry the channel lives behind — that entry being a
#: *name used in messages only*: this application's widgets carry no captions, so nothing
#: here matches a control against it (see the module docstring).
PARAMETERS_MENU = "Parameters"
PARAMETERS_ENTRY = "Operating parameters"
#: The popup overlay's own geometry, as read live off the open menu: a caption-less
#: ``TSp_Panel`` at ``(169, 55, 401, 250)`` — 195 px tall — with its entries at screen
#: tops 61, 95 and 130. This rect is the **fallback** identity only (the primary one is
#: the panel that was not visible before the hover), and it is the reference's own
#: predicate, ``left == 169 and h > 120`` (``recon/41_burst_sampling_volume.py``).
_OVERLAY_LEFT, _OVERLAY_MIN_H = 169, 120
#: How many popup entries are tried, and how long one entry's press is given to produce a
#: dialog before the real-click fallback and the next entry. Both are bounded: a
#: misidentified overlay must never turn the entry loop into a walk across the menubar.
#: The reference polled the dialog at 0.5 s and found it on its first poll, so one entry's
#: press is not given the popup's whole window.
_MAX_ENTRY_ATTEMPTS, _ENTRY_DIALOG_TIMEOUT_S = 4, 2.0
#: How long the popup, the dialog and a selection read-back are given, and the cadence
#: they are polled at — the reference recipe's own numbers (``while time.time() - t0 < 8:
#: time.sleep(0.5)``, ``recon/41_burst_sampling_volume.py``), not a longer window.
_MENU_TIMEOUT_S, _MENU_POLL_S = 8.0, 0.5
#: The real-cursor hover the menubar needs, copied from the recipe that opened this menu
#: (``SetCursorPos`` / ``sleep(0.3)`` / ``mouse_event(MOUSEEVENTF_MOVE, 2, 0, ..)`` /
#: ``sleep(1.0)``): the settle after the jump, the second settle before the popup is
#: polled for, and the settle after the cursor is put back.
_HOVER_SETTLE_S, _HOVER_OPEN_S, _CURSOR_SETTLE_S = 0.3, 1.0, 0.05
#: ``mouse_event``'s move flag and the recipe's nudge: a ``SetCursorPos`` jump alone can
#: be missed by the application's menu loop, the relative move is what it sees.
MOUSEEVENTF_MOVE = 0x0001
#: The button flags: used by the one *real* click this driver makes — the fallback for a
#: popup entry that ignores the posted press (:meth:`Win32Actuator._real_click_centre`).
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
_HOVER_MOVE_DX, _HOVER_MOVE_DY = 2, 0
#: Every send is bounded; a hung target returns instead of blocking (docs/16 §1).
SEND_TIMEOUT_MS = 2000
#: The key-event lParams the verified recipe used (scan code / transition packed).
_VK_RETURN_DOWN_LPARAM, _VK_RETURN_UP_LPARAM = 0x001C0001, 0xC01C0001

#: What :meth:`Win32Actuator._set_text_commit` sends, in order — compared below so the
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
_CLICK_SETTLE_S, _OVERLAY_SETTLE_S, _POLL_S = 0.35, 0.8, 0.4


class AcquisitionError(RuntimeError):
    """The cycle could not be completed; nothing was stored under this point's name."""


class _CursorPoint(ctypes.Structure):
    """``POINT`` for ``GetCursorPos``/``SetCursorPos``.

    Declared here rather than imported from ``ctypes.wintypes``: that module is not
    importable on a host without Windows headers, and this module has to import
    cleanly anywhere (the ``ctypes`` description is portable).
    """

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@lru_cache(maxsize=1)
def _gui():
    """``(win32gui, win32con)`` — loaded inside a function so the module imports anywhere."""
    import win32con
    import win32gui

    return win32gui, win32con


@lru_cache(maxsize=1)
def _user32():
    """``user32`` with its message signatures bound once.

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
    return u32


def _send(
    hwnd: int, msg: int, wp: int = 0, lp: int = 0, timeout_ms: int = SEND_TIMEOUT_MS
) -> int:
    """``SendMessageTimeoutW``, never a plain ``SendMessage``.

    A busy target thread blocks ``SendMessage`` forever; this returns 0 on hang or
    timeout. ``lp`` may be a ctypes buffer address (``WM_SETTEXT``/``WM_GETTEXT``).
    """
    result = ctypes.c_size_t(0)
    _user32().SendMessageTimeoutW(
        ctypes.c_void_p(hwnd),
        msg,
        wp,
        lp,
        SMTO_ABORTIFHUNG,
        timeout_ms,
        ctypes.byref(result),
    )
    return int(result.value)


def _post(hwnd: int, msg: int, wp: int = 0, lp: int = 0) -> None:
    """Post a message (key events and ``WM_COMMAND`` are posted, as verified)."""
    _user32().PostMessageW(ctypes.c_void_p(hwnd), msg, wp, lp)


def _visible_children(win: int) -> list[dict]:
    """Every visible descendant with a real area, in screen coordinates."""
    win32gui, _ = _gui()
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


def _inside(panel: dict | None, k: dict) -> bool:
    """True when ``k``'s centre lies inside ``panel``'s rect."""
    if panel is None:
        return False
    cx, cy = k["left"] + k["w"] // 2, k["top"] + k["h"] // 2
    return (
        panel["left"] <= cx <= panel["left"] + panel["w"]
        and panel["top"] <= cy <= panel["top"] + panel["h"]
    )


def _bottom_row(panel: dict, kids: Sequence[dict], margin: int = 70) -> list[dict]:
    """The panel's own bottom button row, left -> right.

    A dialog's button pair is identified by sitting in the panel's last ``margin``
    pixels — never by title and never by a rect stated in logic.
    """
    floor = panel["top"] + panel["h"] - margin
    return sorted(
        (k for k in kids if k["cls"] == "TSp_Button" and k["top"] > floor),
        key=lambda k: k["left"],
    )


def _strip_row(panel: dict, kids: Sequence[dict]) -> list[dict]:
    """The strip's top-row buttons, left -> right.

    Two buttons the panel never paints sit *below* the panel's own rect; requiring a
    button's centre to lie inside the panel excludes them. Width is never an identity —
    134 vs 138 px is too close — so the row is sorted by ``left`` and addressed by index
    (:func:`…actuator.press_index`) (docs/16 §7, §10).
    """
    panel_bottom, band = panel["top"] + panel["h"], panel["top"] + 30
    return sorted(
        (
            k
            for k in kids
            if k["cls"] == "TSp_Button"
            and k["top"] < band
            and (k["top"] + k["h"] // 2) < panel_bottom
        ),
        key=lambda k: k["left"],
    )


def channel_items() -> tuple[str, ...]:
    """The channel combo's items, as the application shows them: ``'1'``..``'10'``.

    Derived from the one range (:data:`…config.MIN_CHANNEL`/:data:`…config.MAX_CHANNEL`),
    never listed again: a second copy of the channel list is exactly the parallel
    constant this module must not have.
    """
    return tuple(str(n) for n in range(MIN_CHANNEL, MAX_CHANNEL + 1))


def _entry_buttons(overlay: dict, kids: Sequence[dict]) -> list[dict]:
    """The overlay's entries: every ``TSp_Button`` lying inside it, **screen order**.

    Geometry is the only identity available: this application's widgets carry no captions
    (``GetWindowText`` is empty on every ``TSp_*`` widget), so a title can never find an
    entry — that was the live bug. The entries are the buttons whose centre lies inside
    the overlay's rect, ordered by screen ``top`` and then ``left``, because enumeration
    order is *not* screen order: the reference pressed ``Default parameters`` the once it
    trusted it (``recon/41_burst_sampling_volume.py``, docs/16 §13a). The **first** in
    this order is ``Operating parameters``.
    """
    return sorted(
        (k for k in kids if k["cls"] == "TSp_Button" and _inside(overlay, k)),
        key=lambda k: (k["top"], k["left"]),
    )


def _descendants(roles: Mapping, root: int) -> list[dict]:
    """Every already-resolved control inside ``root``, breadth first.

    The tree comes from the resolution's own parent map, so this walks the *same*
    snapshot the roles were resolved from instead of re-enumerating the window.
    """
    by_parent: dict[int, list[dict]] = {}
    for node in roles["raw"]:
        by_parent.setdefault(roles["parent_of"].get(node["hwnd"], 0), []).append(node)
    out: list[dict] = []
    queue = list(by_parent.get(root, []))
    while queue:
        node = queue.pop(0)
        out.append(node)
        queue.extend(by_parent.get(node["hwnd"], []))
    return out


def _ancestors(roles: Mapping, hwnd: int) -> list[dict]:
    """The chain from ``hwnd`` up to (and including) the topmost control below the window.

    Used as *identity*: "nested inside a ``TSp_Value_Button``" is a property of this
    chain, and the chain's last element is the panel that owns the control.
    """
    index = {node["hwnd"]: node for node in roles["raw"]}
    chain: list[dict] = []
    node = index.get(hwnd)
    while node is not None:
        chain.append(node)
        node = index.get(roles["parent_of"].get(node["hwnd"]))
    return chain


def same_directory(shown: str, expected: str | Path) -> bool:
    """True when the dialog's ``Working directory`` text names ``expected``.

    Compared on the *resolved* path, never on the two strings: the application
    renders the path in its own normal form (case, trailing separator, its own
    contraction), and a cosmetic difference must not fail a point — while a real
    difference must never pass as one. An empty or unreadable value is *not* a
    match: "no path shown" is not "the path I expected".
    """
    text = (shown or "").strip().strip('"').strip()
    if not text:
        return False
    try:
        return os.path.normcase(str(Path(text).resolve())) == os.path.normcase(
            str(Path(expected).resolve())
        )
    except (OSError, ValueError):
        return False


class Win32Actuator:
    """The live :class:`Actuator`: UDOP driven over posted Win32 messages.

    Bindings are re-resolved from scratch on every call — the strip panel is draggable
    and morphs (``98x40`` -> ``352x40`` -> ``413x123``), so a cached handle or rect would
    go stale on the first press.
    """

    def __init__(
        self,
        class_name: str = MAIN_CLASS,
        *,
        channel: int | None = None,
        note_sink: Callable[[str], None] | None = None,
        allow_real_input: bool = True,
    ) -> None:
        """``channel`` is the measurement channel — the one knob.

        ``None`` takes it from :class:`~udv_echo_process.acquire.config.ChannelSetting`
        (explicit here > ``UDV_CHANNEL`` > the default), so retargeting the whole run is
        an environment variable and nothing else. The value is validated on construction,
        not at the first press.

        ``allow_real_input`` gates the one step posted messages cannot drive: the
        menubar. ``True`` (the default) hovers the ``Parameters`` button with the
        operator's real cursor and puts the cursor back; ``False`` refuses that step
        with a named :class:`AcquisitionError` **before anything is moved**, for
        unattended or locked-desktop runs. It never falls back to the posted press —
        that press is known not to open this menu.
        """
        self._class_name = class_name
        self._channel_setting = (
            ChannelSetting() if channel is None else ChannelSetting(channel=channel)
        )
        self._note_sink = note_sink
        self._allow_real_input = bool(allow_real_input)
        #: Diagnostics only — never used as a binding.
        self.last_roles: dict | None = None
        self.last_press_screen: tuple[int, int] | None = None
        #: The screen point the last real-cursor hover used (diagnostics only).
        self.last_hover_screen: tuple[int, int] | None = None
        #: The screen point the last real-cursor *entry click* used (diagnostics only).
        self.last_entry_click_screen: tuple[int, int] | None = None
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ plumbing

    def _note(self, message: str) -> None:
        self.warnings.append(message)
        if self._note_sink is not None:
            self._note_sink(message)

    def _send(
        self,
        hwnd: int,
        msg: int,
        wp: int = 0,
        lp: int = 0,
        timeout_ms: int = SEND_TIMEOUT_MS,
    ) -> int:
        """Bounded send; see :func:`_send`."""
        return _send(hwnd, msg, wp, lp, timeout_ms)

    def _get_text(self, hwnd: int) -> str:
        """The control's own text (``WM_GETTEXT``, bounded)."""
        buf = ctypes.create_unicode_buffer(256)
        self._send(hwnd, WM_GETTEXT, 256, ctypes.addressof(buf))
        return buf.value

    def _control_id(self, hwnd: int) -> int:
        """The id only as the field *inside* ``WM_COMMAND`` — never as an identity."""
        win32gui, _ = _gui()
        cid = win32gui.GetDlgCtrlID(hwnd)
        return ctypes.c_short(cid).value if cid > 32767 else cid

    def _set_text_commit(self, hwnd: int, text: str, parent: int | None = None) -> None:
        """Write ``text`` and **commit** it: the recipe in ``NUMERIC_WRITE_RECIPE``.

        ``WM_SETTEXT`` alone changes the control's text while the application keeps its
        own value; the ``EN_CHANGE`` command and the ``VK_RETURN`` key event are what make
        the model take the new value (docs/14 §4, docs/16 §12a).
        """
        win32gui, _ = _gui()
        if parent is None:
            parent = win32gui.GetParent(hwnd)
        buf = ctypes.create_unicode_buffer(text)
        self._send(hwnd, WM_SETTEXT, 0, ctypes.addressof(buf))
        time.sleep(_TEXT_SETTLE_S)
        _post(
            parent,
            WM_COMMAND,
            (EN_CHANGE << 16) | (self._control_id(hwnd) & 0xFFFF),
            hwnd,
        )
        time.sleep(_TEXT_SETTLE_S)
        _post(hwnd, WM_KEYDOWN, VK_RETURN, _VK_RETURN_DOWN_LPARAM)
        _post(hwnd, WM_KEYUP, VK_RETURN, _VK_RETURN_UP_LPARAM)
        time.sleep(_TEXT_COMMIT_SETTLE_S)

    def _combo_select(self, hwnd: int, index: int, parent: int | None = None) -> None:
        """Select a combo entry: ``CB_SETCURSEL`` + ``CBN_SELCHANGE``, **no Enter**.

        A combo commits on the change notification; a key event here would re-trigger
        whatever the Enter handler does.
        """
        win32gui, _ = _gui()
        if parent is None:
            parent = win32gui.GetParent(hwnd)
        self._send(hwnd, CB_SETCURSEL, index, 0)
        time.sleep(_TEXT_SETTLE_S)
        _post(
            parent,
            WM_COMMAND,
            (CBN_SELCHANGE << 16) | (self._control_id(hwnd) & 0xFFFF),
            hwnd,
        )
        time.sleep(_TEXT_COMMIT_SETTLE_S)

    def _click_hold(self, hwnd: int, hold_ms: int = PRESS_HOLD_MS) -> None:
        """Press and **hold** a control: down, ``hold_ms``, up.

        An instant down/up in the same millisecond is ignored by the strip (that is
        exactly what every early attempt sent, docs/16 §1). ``lParam`` is in the target's
        client coordinates, so the centre comes from ``GetClientRect`` and is converted to
        screen only so a failure can be reported in real screen terms.
        """
        win32gui, _ = _gui()
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        x, y = (right - left) // 2, (bottom - top) // 2
        try:
            self.last_press_screen = win32gui.ClientToScreen(hwnd, (x, y))
        except Exception:  # noqa: BLE001 - diagnostic only
            self.last_press_screen = None
        lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
        _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(max(0, int(hold_ms)) / 1000.0)
        _post(hwnd, WM_LBUTTONUP, 0, lp)
        time.sleep(_CLICK_SETTLE_S)

    def _cursor_position(self) -> tuple[int, int]:
        """The operator's cursor position, in screen coordinates.

        Read before any real move, so the move can be undone
        (:meth:`_restore_cursor`). An unreadable position is refused rather than
        ignored: a cursor moved with no way back is the operator's cursor taken, and
        that is worse than a failed point.
        """
        point = _CursorPoint()
        if not _user32().GetCursorPos(ctypes.byref(point)):
            raise AcquisitionError(
                "the cursor position could not be read, so the real-cursor hover this "
                "menubar needs would move the operator's cursor with no way back"
            )
        return int(point.x), int(point.y)

    def _restore_cursor(self, position: tuple[int, int]) -> None:
        """Put the operator's cursor back where :meth:`_cursor_position` found it."""
        _user32().SetCursorPos(int(position[0]), int(position[1]))
        time.sleep(_CURSOR_SETTLE_S)

    def _hover_centre(self, hwnd: int) -> tuple[int, int]:
        """Hover ``hwnd`` with the **real** cursor; return the screen point hovered.

        The menubar is the one control in this application that posted messages cannot
        drive: a posted ``WM_MOUSEMOVE`` opened nothing, and a posted press held for
        :data:`…actuator.PRESS_HOLD_MS` opened nothing either (two live runs, both
        aborting safely with nothing pressed), while the same button opened its menu
        under the operator's real cursor in ``recon/41_burst_sampling_volume.py``. This
        copies that gesture exactly, in that order: the control's centre in **screen**
        coordinates (:meth:`win32gui.GetWindowRect`), ``SetCursorPos``, the recipe's
        0.3 s settle, one ``mouse_event`` relative move of :data:`_HOVER_MOVE_DX` px,
        then the recipe's 1.0 s settle before the caller polls for the popup.

        The cursor now sits on the control, so the caller puts it back with
        :meth:`_restore_cursor` — this runs on the operator's interactive desktop. A
        ``SetCursorPos`` that did not take (a locked or unattended desktop silently
        refuses it) is raised here by name: the menu would then open for no one, and
        the popup poll would report the wrong cause eight seconds later.
        """
        win32gui, _ = _gui()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        x, y = (left + right) // 2, (top + bottom) // 2
        u32 = _user32()
        u32.SetCursorPos(x, y)
        time.sleep(_HOVER_SETTLE_S)
        if self._cursor_position() != (x, y):
            raise AcquisitionError(
                f"the cursor would not move onto the {PARAMETERS_MENU!r} button at "
                f"({x}, {y}): a locked or unattended desktop refuses SetCursorPos, and "
                "this menubar answers nothing else"
            )
        u32.mouse_event(MOUSEEVENTF_MOVE, _HOVER_MOVE_DX, _HOVER_MOVE_DY, 0, 0)
        time.sleep(_HOVER_OPEN_S)
        self.last_hover_screen = (x, y)
        return x, y

    def _real_click_centre(self, hwnd: int) -> tuple[int, int]:
        """Click ``hwnd``'s centre with the **real** cursor; return the point clicked.

        The fallback for a popup entry that ignores the posted press
        (:meth:`_press_entry`): a popup entry answers posted presses in every run so far,
        but a menu that has to be *opened* by a real hover may also want to be *taken* by
        a real click, and a real click is the only other gesture this driver has. It is
        gated exactly like the hover: the caller only reaches this with
        ``allow_real_input``, and the cursor is put back by
        :meth:`_open_parameters_dialog`'s ``finally`` whatever happens here.

        A ``SetCursorPos`` that did not take (a locked or unattended desktop refuses it
        silently) is raised by name, as in :meth:`_hover_centre`: clicking where the
        cursor is *not* would press whatever is there.
        """
        win32gui, _ = _gui()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        x, y = (left + right) // 2, (top + bottom) // 2
        u32 = _user32()
        u32.SetCursorPos(x, y)
        time.sleep(_HOVER_SETTLE_S)
        if self._cursor_position() != (x, y):
            raise AcquisitionError(
                f"the cursor would not move onto the popup entry at ({x}, {y}): a locked "
                "or unattended desktop refuses SetCursorPos, and clicking where the "
                "cursor is not would press whatever is there"
            )
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(max(0, int(PRESS_HOLD_MS)) / 1000.0)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(_CLICK_SETTLE_S)
        self.last_entry_click_screen = (x, y)
        return x, y

    # ------------------------------------------------------------------ binding

    def _main_hwnd(self) -> int:
        """Handle of the visible main window (largest if several exist)."""
        win32gui, _ = _gui()
        found: list[tuple[int, int]] = []

        def cb(h, _lparam):
            try:
                if win32gui.GetClassName(
                    h
                ) == self._class_name and win32gui.IsWindowVisible(h):
                    left, top, right, bottom = win32gui.GetWindowRect(h)
                    found.append(((right - left) * (bottom - top), h))
            except Exception:  # noqa: BLE001, S110
                pass
            return True

        win32gui.EnumWindows(cb, None)
        if not found:
            raise AcquisitionError(
                f"no visible {self._class_name} window — is UDOP on its startup screen?"
            )
        return max(found)[1]

    @staticmethod
    def _children_of(parent: int, roles: dict) -> list[dict]:
        """The already-enumerated children whose parent is ``parent``."""
        win32gui, _ = _gui()
        return [k for k in roles["raw"] if win32gui.GetParent(k["hwnd"]) == parent]

    def _param_rows(
        self, left_panel: dict | None, kids: Sequence[dict], children_of
    ) -> list[dict]:
        """The parameter column's value fields, top -> bottom, each with its inner edit.

        A field's identity is its position in this fixed order, never its id: the
        ``TSp_Value_Button`` widgets in the left panel, ordered by ``top``, each holding a
        ``TSp_Edit``/``TEdit`` (docs/16 §12, ``recon/udop_roles.py``).
        """
        if left_panel is None:
            return []
        rows: list[dict] = []
        for button in sorted(
            (
                k
                for k in kids
                if k["cls"] == "TSp_Value_Button" and _inside(left_panel, k)
            ),
            key=lambda k: k["top"],
        ):
            inner = sorted(children_of(button["hwnd"]), key=lambda k: k["left"])
            edit = next((c for c in inner if c["cls"] in ("TSp_Edit", "TEdit")), None)
            if edit is not None:
                rows.append({"button": button, "edit": edit})
        if len(rows) >= len(PARAM_COLUMN_ORDER):
            return rows
        # Fallback: plain edits inside the column's rect, in the same fixed order.
        flat = [
            {"button": None, "edit": k}
            for k in sorted(
                (
                    k
                    for k in kids
                    if k["cls"] in ("TSp_Edit", "TEdit") and _inside(left_panel, k)
                ),
                key=lambda k: k["top"],
            )
        ]
        return flat if len(flat) > len(rows) else rows

    def _resolve(self) -> dict:
        """Map roles to live controls, the way ``udop_roles.resolve()`` does.

        Class + position inside the client area only: the layout fingerprint, the panel
        list, the menu bar, the parameter column, the combos, the strip panel (by its
        buttons' position in the plot area, then by its own button row) and the open-popup
        flag. Nothing keys on a control id and nothing on a screen coordinate in logic.
        """
        win32gui, _ = _gui()
        win = self._main_hwnd()
        kids = _visible_children(win)
        _l, _t, cw, ch = win32gui.GetClientRect(
            win
        )  # GetClientRect is always (0,0,w,h)
        ox, oy = win32gui.ClientToScreen(win, (0, 0))  # the client's screen origin
        parent_of = win32gui.GetParent

        def children_of(p: int) -> list[dict]:
            return [k for k in kids if win32gui.GetParent(k["hwnd"]) == p]

        roles: dict = {
            "window": win,
            "client": (cw, ch),
            "origin": (ox, oy),
            "raw": kids,
            # The resolved tree, so "nested inside X" is a property of the snapshot
            # rather than another enumeration of the window.
            "parent_of": {k["hwnd"]: parent_of(k["hwnd"]) for k in kids},
        }

        # --- panels -------------------------------------------------------------------
        # Every cluster sits inside its own TSp_Panel, and the panels are ordered
        # top-to-bottom deterministically: group by parent panel, never by fractions of the
        # window (the strip sits at a fixed client y whether the client is 819 or 1027 px
        # tall, so a percentage cut moves relative to it as the window is resized).
        panels = sorted(
            (
                k
                for k in kids
                if k["cls"] == "TSp_Panel" and parent_of(k["hwnd"]) == win
            ),
            key=lambda k: k["top"],
        )
        roles["panels"] = panels
        index_of = {k["hwnd"]: i for i, k in enumerate(panels)}
        buttons = [k for k in kids if k["cls"] == "TSp_Button"]
        host_count = {
            i: sum(1 for b in buttons if index_of.get(parent_of(b["hwnd"])) == i)
            for i in range(len(panels))
        }
        plot = next((k for k in kids if k["cls"] == "TDop_Plot"), None)
        menu_idx = 0 if panels else None
        status_idx = (len(panels) - 1) if len(panels) > 1 else None

        # --- panels that are dialogs, not the measurement layout ------------------------
        # A dialog is a panel owning a real edit plus a TSp_Browse button, wherever the
        # operator dragged it. One with TSp_Value_Button children is the values dialog
        # (`Record settings`); one without them is the Store dialog. Detected structurally,
        # so the file-exists warning and the store dialog are never confused.
        value_dialogs: set[int] = set()
        browse_dialogs: set[int] = set()
        for p in panels:
            direct = children_of(p["hwnd"])
            has_edit = any(k["cls"] in ("TEdit", "TSp_Edit") for k in direct)
            if not (has_edit and any(k["cls"] == "TSp_Browse" for k in direct)):
                continue
            if any(k["cls"] == "TSp_Value_Button" for k in direct):
                value_dialogs.add(p["hwnd"])
            else:
                browse_dialogs.add(p["hwnd"])
        roles["value_dialogs"], roles["browse_dialogs"] = value_dialogs, browse_dialogs
        dialog_panels = value_dialogs | browse_dialogs

        # --- the recording strip --------------------------------------------------------
        # The strip is the button panel in the MIDDLE of the plot area. "The panel with the
        # most buttons" is wrong the moment a popup is open: an open menu is itself a panel
        # full of buttons near the menu bar, and it wins that vote.
        def strip_score(i: int) -> float | None:
            if not host_count.get(i):
                return None
            if plot is None:
                return float(host_count[i])
            band = [b for b in buttons if index_of.get(parent_of(b["hwnd"])) == i]
            centre_y = sum(b["top"] + b["h"] / 2 for b in band) / len(band)
            frac = (centre_y - plot["top"]) / max(1, plot["h"])
            return frac if 0.30 <= frac <= 0.70 else None

        scored = {
            i: s
            for i in range(len(panels))
            if i not in (menu_idx, status_idx)
            and panels[i]["hwnd"] not in dialog_panels
            and (s := strip_score(i)) is not None
        }
        rec_idx = max(scored, key=lambda i: host_count[i]) if scored else None
        strip_panel = panels[rec_idx] if rec_idx is not None else None
        if strip_panel is not None and not any(
            k["cls"] == "TSp_Button" for k in children_of(strip_panel["hwnd"])
        ):
            strip_panel = None
        if strip_panel is None:
            # Fallback: a short panel (not the menu, not the status bar, not a dialog) that
            # directly owns strip buttons.
            strip_panel = max(
                (
                    p
                    for i, p in enumerate(panels)
                    if i not in (menu_idx, status_idx)
                    and p["hwnd"] not in dialog_panels
                    and p["h"] <= 200
                    and host_count.get(i)
                ),
                key=lambda p: p["h"],
                default=None,
            )
        roles["strip_panel"] = strip_panel
        roles["open_popup"] = any(
            i not in (menu_idx, status_idx, rec_idx)
            and host_count.get(i)
            and panels[i]["hwnd"] not in dialog_panels
            for i in range(len(panels))
        )

        # --- menu bar --------------------------------------------------------------------
        roles["menu"] = {}
        ordered_menu = sorted(
            (b for b in buttons if index_of.get(parent_of(b["hwnd"])) == menu_idx),
            key=lambda b: b["left"],
        )
        for i, k in enumerate(ordered_menu):
            if i < len(MENU_ORDER):
                roles["menu"][MENU_ORDER[i]] = k

        # --- the left parameter column ----------------------------------------------------
        # The column is the tall panel whose *client-relative* left is 0 (`left == 0` in the
        # reference); fall back to the tallest panel that is neither the menu bar nor the
        # status bar.
        candidates = [
            p
            for i, p in enumerate(panels)
            if i not in (menu_idx, status_idx) and p["hwnd"] not in dialog_panels
        ]
        left_panel = next(
            (p for p in candidates if (p["left"] - ox) == 0 and p["h"] > 500), None
        ) or max(candidates, key=lambda p: p["h"], default=None)
        roles["left_panel"] = left_panel
        rows = self._param_rows(left_panel, kids, children_of)
        roles["param_rows"] = rows
        roles["params"] = {
            PARAM_COLUMN_ORDER[i]: row
            for i, row in enumerate(rows[: len(PARAM_COLUMN_ORDER)])
        }
        roles["combos"] = dict(
            zip(
                COMBO_ORDER,
                sorted(
                    (
                        k
                        for k in kids
                        if k["cls"] == "TComboBox" and _inside(left_panel, k)
                    ),
                    key=lambda k: k["top"],
                ),
            )
        )
        roles["plot"] = plot

        # --- the strip's own structure, and the layout fingerprint -------------------------
        strip_kids = children_of(strip_panel["hwnd"]) if strip_panel is not None else []
        row = _strip_row(strip_panel, strip_kids) if strip_panel is not None else []
        roles["strip_row"] = row
        roles["state"] = classify_strip_view(
            len(row), any(k["cls"] == "TSp_Sliding_Bar" for k in strip_kids)
        ).value
        roles["layout_expected"] = (
            len(kids) == EXPECTED_CONTROL_COUNT and len(panels) == EXPECTED_PANEL_COUNT
        )
        if not roles["layout_expected"]:
            roles["layout_note"] = (
                f"{len(kids)} visible controls in {len(panels)} panels; the clean measurement "
                f"screen has {EXPECTED_CONTROL_COUNT} in {EXPECTED_PANEL_COUNT}"
            )
        self.last_roles = roles
        return roles

    def _has_slider(self, roles: dict, panel: dict | None) -> bool:
        """True when the strip panel owns a ``TSp_Sliding_Bar`` — the store view's mark."""
        if panel is None:
            return False
        return any(
            k["cls"] == "TSp_Sliding_Bar"
            for k in self._children_of(panel["hwnd"], roles)
        )

    def _state_of(self, roles: dict) -> StripState:
        """The strip state implied by an already-resolved role map."""
        panel = roles["strip_panel"]
        # `slider_max` (the selected block's profile count) is deliberately left unset: the
        # reference never read the slider's range, and guessing is worse than None.
        return StripState(
            button_count=len(roles["strip_row"]),
            has_slider=self._has_slider(roles, panel),
            slider_max=None,
        )

    def _find_overlay(self, roles: dict | None = None):
        """Find an overlay panel: not a known layout panel, owning its own dialog row.

        Returns ``(kind, panel, kids)`` or ``None``. A warning is a panel with a bottom
        button pair; the Store dialog is the panel owning a ``TSp_Browse`` and edits but
        none of the values dialog's ``TSp_Value_Button`` children. The app reuses one
        geometry for all its warnings, so structure is the only discriminator
        (docs/16 §8, §12b).
        """
        roles = roles if roles is not None else self._resolve()
        known: set[int] = set()
        for key in ("menu", "combos"):
            known.update(k["hwnd"] for k in (roles.get(key) or {}).values())
        known.update(
            row["edit"]["hwnd"]
            for row in (roles.get("param_rows") or [])
            if row.get("edit")
        )
        known.update(roles["value_dialogs"])
        if roles.get("left_panel") is not None:
            known.add(roles["left_panel"]["hwnd"])
        if roles.get("strip_panel") is not None:
            known.add(roles["strip_panel"]["hwnd"])
        if roles.get("panels"):
            known.add(roles["panels"][0]["hwnd"])  # the menu bar's own panel
            known.add(roles["panels"][-1]["hwnd"])  # the status bar's
        for panel in roles["panels"]:
            if panel["hwnd"] in known:
                continue
            kids = self._children_of(panel["hwnd"], roles)
            if any(k["cls"] == "TSp_Browse" for k in kids) and any(
                k["cls"] in ("TEdit", "TSp_Edit") for k in kids
            ):
                return (OverlayKind.STORE_DIALOG, panel, kids)
            if _bottom_row(panel, kids) and panel["w"] > 250 and panel["h"] > 90:
                return (OverlayKind.WARNING, panel, kids)
        return None

    def _peek_overlay(self) -> OverlayKind | None:
        """Which overlay is up, without answering it."""
        found = self._find_overlay()
        return None if found is None else found[0]

    def _require_store_dialog(self) -> tuple[dict, list[dict]]:
        """The Store dialog panel and its children, or a failure."""
        found = self._find_overlay()
        if found is None or found[0] is not OverlayKind.STORE_DIALOG:
            raise AcquisitionError("the Store dialog is not up")
        return found[1], self._children_of(found[1]["hwnd"], self._resolve())

    def _dialog_button(
        self,
        panel: dict,
        kids: Sequence[dict],
        which: DialogControl,
        hold_ms: int = PRESS_HOLD_MS,
    ) -> dict:
        """Press one end of a dialog's bottom pair (never by title, never by rect)."""
        row = _bottom_row(panel, kids)
        if not row:
            raise AcquisitionError(
                f"no bottom button row in the panel at {panel['rect'][:2]}"
            )
        if which is DialogControl.CONFIRM and len(row) < 2:
            raise AcquisitionError("the dialog's bottom row has no confirm button")
        target = row[0] if which is DialogControl.SAFE else row[-1]
        self._click_hold(target["hwnd"], hold_ms)
        return target

    # -------------------------------------------------- the measurement channel

    @property
    def channel(self) -> int:
        """The measurement channel this driver is bound to (the single knob)."""
        return self._channel_setting.channel

    def _combo_index(self, hwnd: int) -> int:
        """The combo's selected index, or ``-1`` when it has no selection.

        ``CB_GETCURSEL`` answers ``CB_ERR`` (-1) through an unsigned result, so a
        value above :data:`_COMBO_NONE_ABOVE` means *no selection*, never a huge
        index. This is the control's own belief, which is why it is never the only
        read-back (:meth:`_channel_readback`).
        """
        raw = self._send(hwnd, CB_GETCURSEL, 0, 0)
        return -1 if raw > _COMBO_NONE_ABOVE else raw

    def _combo_items(self, hwnd: int) -> tuple[str, ...]:
        """Every item the combo holds, in order (``CB_GETCOUNT`` + ``CB_GETLBTEXT``).

        The item *list* is how the channel combo is identified, so it is read rather
        than assumed; a nonsense count is an empty list, not a spin.
        """
        count = self._send(hwnd, CB_GETCOUNT, 0, 0)
        if count <= 0 or count > _COMBO_NONE_ABOVE:
            return ()
        items: list[str] = []
        for index in range(count):
            buf = ctypes.create_unicode_buffer(64)
            self._send(hwnd, CB_GETLBTEXT, index, ctypes.addressof(buf))
            items.append(buf.value)
        return tuple(items)

    def _parameters_panels(self, roles: Mapping | None = None) -> list[dict]:
        """The panels that are value dialogs — they own ``TSp_Value_Button`` children.

        ``Operating parameters`` and ``Record settings`` are the same *kind* of panel,
        and the sidebar's parameter column owns ``TSp_Value_Button`` fields too, so the
        column is excluded **by identity** (the resolved ``left_panel``), never by
        position or by a title.
        """
        roles = self._resolve() if roles is None else roles
        left = roles.get("left_panel")
        out: list[dict] = []
        for panel in roles.get("panels") or []:
            if left is not None and panel["hwnd"] == left["hwnd"]:
                continue
            direct = [
                k
                for k in roles["raw"]
                if roles["parent_of"].get(k["hwnd"]) == panel["hwnd"]
            ]
            if any(k["cls"] == "TSp_Value_Button" for k in direct):
                out.append(panel)
        return out

    def _channel_combo(self, panel: dict, roles: Mapping | None = None) -> tuple[dict, int]:
        """The channel combo inside ``panel``: ``(combo, its parent's hwnd)``.

        Identity, exactly as the running application was probed: a ``TComboBox``
        reached *through* a ``TSp_Value_Button`` whose items are the application's
        channels, ``'1'``..``'10'``. Never an id (ids change on every launch), never a
        screen coordinate stated in logic, and never "the first combo" — the item list
        *is* the identity. Two matches are an ambiguity, not a choice to make.

        This is also how the *dialog* is identified on the way in
        (:meth:`_open_parameters_dialog`): among the dialogs this application can open
        from the same popup, the operating one is the one this method answers for. No
        caption takes part in it — there are none to read.
        """
        roles = self._resolve() if roles is None else roles
        wanted = channel_items()
        matches: list[tuple[dict, int]] = []
        for node in _descendants(roles, panel["hwnd"]):
            if node["cls"] != "TComboBox":
                continue
            chain = _ancestors(roles, node["hwnd"])
            if not any(a["cls"] == "TSp_Value_Button" for a in chain):
                continue
            if self._combo_items(node["hwnd"]) == wanted:
                parent = roles["parent_of"].get(node["hwnd"])
                matches.append((node, 0 if parent is None else parent))
        if not matches:
            raise AcquisitionError(
                f"no channel combo in the dialog at {panel['rect'][:2]}: the measurement "
                f"channel lives in a TComboBox nested in a TSp_Value_Button whose items "
                f"are {list(wanted)}, and nothing in this dialog lists them"
            )
        if len(matches) > 1:
            raise AcquisitionError(
                f"{len(matches)} combos in the dialog at {panel['rect'][:2]} list "
                f"{list(wanted)}; the channel combo is ambiguous, so nothing is selected"
            )
        return matches[0]

    def _channel_readback(self, combo: dict) -> tuple[int, str]:
        """The dialog's own statement of the channel: the combo's index **and** text.

        Both, because either alone lies: ``CB_GETCURSEL`` reports only what the control
        believes, and a combo's painted text has been seen to keep showing the previous
        entry after a write (docs/16 §2). A read-back that does not name the configured
        channel is a selection that did not take.
        """
        return self._combo_index(combo["hwnd"]), self._get_text(combo["hwnd"])

    def _channel_matches(self, index: int, text: str) -> bool:
        """True when a dialog read-back names the configured channel exactly."""
        wanted = self._channel_setting
        return index == wanted.combo_index and text.strip() == str(wanted.channel)

    def _panel_map(self, roles: Mapping | None = None) -> dict[int, dict]:
        """Every visible ``TSp_Panel`` right now, by handle.

        The panels are re-read, never remembered: the popup is a panel the application
        shows and hides, so the snapshot taken before the hover is only worth anything
        compared with a *fresh* one. Nothing here is keyed on a caption — these widgets
        have none (see the module docstring).
        """
        roles = self._resolve() if roles is None else roles
        return {k["hwnd"]: k for k in roles["raw"] if k["cls"] == "TSp_Panel"}

    def _poll_parameters_overlay(self, before: Mapping[int, dict]) -> dict:
        """The ``Parameters`` popup overlay: the panel that appeared on the hover.

        Identified by **appearance**, because a caption can never identify it: every
        caption-less ``TSp_*`` widget in this application answers ``GetWindowText`` with
        the empty string, so the overlay is the ``TSp_Panel`` that is visible now and was
        **not** in the ``before`` snapshot taken just before the menubar was hovered.

        When the diff is ambiguous — more than one new panel, or none yet — the reference
        recipe's own predicate decides (``recon/41_burst_sampling_volume.py``:
        ``left == 169 and h > 120``, the panel it read live at ``(169, 55, 401, 250)``;
        the popup is reused or re-shown by some menus, and then it was visible before the
        second hover and the diff alone would find nothing). Polled, never assumed: the
        recipe waited the same way and the popup takes a moment to paint. A popup that
        has shown neither within :data:`_MENU_TIMEOUT_S` is reported by name.
        """
        deadline = time.monotonic() + _MENU_TIMEOUT_S
        while True:
            panels = self._panel_map()
            fresh = [p for hwnd, p in panels.items() if hwnd not in before]
            if len(fresh) == 1:
                return fresh[0]
            recorded = sorted(
                (
                    p
                    for p in panels.values()
                    if p["left"] == _OVERLAY_LEFT and p["h"] > _OVERLAY_MIN_H
                ),
                key=lambda p: p["top"],
            )
            if recorded:
                return recorded[0]
            if time.monotonic() >= deadline:
                break
            time.sleep(_MENU_POLL_S)
        raise AcquisitionError(
            f"the {PARAMETERS_MENU!r} popup did not appear within {_MENU_TIMEOUT_S:.0f} s "
            f"of its hover, so no {PARAMETERS_ENTRY!r} entry could be pressed: no panel "
            "became visible that was not visible before the hover, and none matched the "
            "overlay the live application paints"
        )

    def _poll_dialog(self, timeout_s: float) -> dict | None:
        """The dialog panel that is up, or ``None`` when none appeared in ``timeout_s``.

        A dialog here is a panel owning ``TSp_Value_Button`` fields — the same structure
        for every dialog this application opens (:meth:`_parameters_panels`), which is
        why it is found rather than named. ``None`` is a fact to report, not to paper
        over: the caller falls back to a real click or tries the next entry.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            panels = self._parameters_panels()
            if panels:
                return panels[0]  # the panels are resolved top-to-bottom
            if time.monotonic() >= deadline:
                return None
            time.sleep(_MENU_POLL_S)

    def _press_entry(self, entry: dict) -> dict | None:
        """Press one popup entry; return the dialog it opened, or ``None``.

        The press is the posted **held** press popup entries answer (:meth:`_click_hold`).
        If no dialog follows it, the same entry is clicked with the operator's real cursor
        (:meth:`_real_click_centre`) — a menu that had to be opened by a real hover may
        also want to be taken by a real click, and that is the only other gesture this
        driver has; it is gated by ``allow_real_input`` exactly like the hover.

        Nothing here presses anything *inside* a dialog: which dialog opened is the
        caller's question, and it answers it by content.
        """
        self._click_hold(entry["hwnd"])
        panel = self._poll_dialog(_ENTRY_DIALOG_TIMEOUT_S)
        if panel is None and self._allow_real_input:
            self._note(
                f"the posted press on the popup entry at {entry['rect'][:2]} opened no "
                "dialog; repeating it with the real cursor"
            )
            self._real_click_centre(entry["hwnd"])
            panel = self._poll_dialog(_ENTRY_DIALOG_TIMEOUT_S)
        return panel

    def _close_wrong_dialog(self, panel: dict) -> None:
        """Close a dialog that is not the operating one with its **LEFT** button.

        Never its right-hand/default button: on a parameters dialog that button *accepts*
        the dialog's values, and this is precisely the dialog whose identity is not yet
        established — a default parameters dialog's Accept is a change nobody asked for.
        The leftmost button of the bottom row is ``Cancel`` on every dialog this
        application paints (:func:`_bottom_row`, :data:`…actuator.DialogControl.SAFE`).
        A close that does not resolve is noted, never raised through: the caller still has
        entries to try, and the bounded loop is what keeps that safe.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
            self._note(
                f"a dialog without the channel combo was up at {panel['rect'][:2]}; closed "
                "it with its left button — never its default button"
            )
        except AcquisitionError as exc:
            self._note(f"a dialog without the channel combo could not be closed: {exc}")

    def _open_parameters_dialog(self) -> dict:
        """Open ``Parameters → Operating parameters`` and return the dialog's panel.

        The dialog is a modal overlay reached through the menubar — not a sidebar
        control, and not a top-level window (``EnumWindows`` finds nothing: the app's
        dialogs are child panels, docs/16 §6).

        Nothing on this path matches a control by its caption, and nothing can: this
        application's widgets are caption-less (``GetWindowText`` is empty for all of them
        — the live read of the open popup showed the overlay panel and its three entries
        with empty captions), which is why a title lookup found no entry at all. What
        identifies each thing instead:

        1. the **overlay** is the panel that became visible on the hover
           (:meth:`_poll_parameters_overlay`, with the reference's ``left == 169 and
           h > 120`` rect as the fallback when the appearance diff is ambiguous);
        2. the **entries** are the ``TSp_Button`` widgets lying inside that overlay,
           ordered by screen ``top`` — the first is ``Operating parameters``
           (:func:`_entry_buttons`; enumeration order is not screen order);
        3. the **dialog** is the one whose content says so: only the operating dialog
           holds the channel combo (:meth:`_channel_combo` — a ``TComboBox`` reached
           through a ``TSp_Value_Button`` listing ``'1'``..``'10'``). An entry whose
           dialog does not hold it is tried past: that dialog is closed with its **left**
           button (:meth:`_close_wrong_dialog`, never its Accept, which on a parameters
           dialog is what would commit whatever it holds), and the next entry by screen
           order is pressed. A bounded number of entries is tried; when none yields the
           operating dialog the failure is raised by name.

        The menu is opened by **hovering the menubar button with the operator's real
        cursor** (:meth:`_hover_centre`): this application's menubar ignores posted
        messages — a posted ``WM_MOUSEMOVE`` opened nothing and so did a posted press
        held for :data:`…actuator.PRESS_HOLD_MS` (two live runs, both aborting safely) —
        while the same button opened its menu under a real cursor in
        ``recon/41_burst_sampling_volume.py``. Nothing posts a message to the menubar any
        more. The cursor stays on the button while the menu is in use — through the poll
        for the popup and through the entry press — and is put back once the entry has
        been pressed or the attempt fails (:meth:`_restore_cursor`): a hover-opened popup
        can be dismissed by moving the cursor off the menubar before the posted press
        lands, and this still runs on the operator's desktop.
        ``allow_real_input=False`` refuses this step by name instead — never falling
        back to the posted press, which is known not to open this menu.
        """
        if not self._allow_real_input:
            raise AcquisitionError(
                f"the {PARAMETERS_MENU!r} menu cannot be opened without real input: this "
                "application's menubar ignores posted messages, so its button is hovered "
                "with the operator's real cursor (SetCursorPos + mouse_event) and there "
                "is deliberately no posted fallback — allow_real_input=False, so nothing "
                "was moved on this unattended or locked desktop"
            )
        roles = self._resolve()
        if roles["open_popup"]:
            raise AcquisitionError(
                "a menu popup is already open; the entry press would be unreliable — "
                "close it from the UI, this driver never WM_CLOSEs a popup"
            )
        menu = (roles.get("menu") or {}).get(PARAMETERS_MENU)
        if menu is None:
            raise AcquisitionError(f"no {PARAMETERS_MENU!r} button in the menubar")
        saved = self._cursor_position()
        pressed = 0
        try:
            for attempt in range(_MAX_ENTRY_ATTEMPTS):
                # The snapshot is taken *before* this hover, so "visible after, not
                # before" is a statement about *this* attempt: a popup panel that a
                # previous attempt left hidden is not in the set, and one the app reuses
                # without hiding it falls back to the recorded rect below.
                before = self._panel_map()
                self._hover_centre(menu["hwnd"])  # the popup opens on this real hover
                overlay = self._poll_parameters_overlay(before)
                entries = _entry_buttons(overlay, self._resolve()["raw"])
                if attempt >= len(entries):
                    break
                entry = entries[attempt]
                pressed += 1
                panel = self._press_entry(entry)
                if panel is None:
                    self._note(
                        f"the popup entry at {entry['rect'][:2]} opened no dialog; trying "
                        "the next entry in screen order"
                    )
                    continue
                try:
                    self._channel_combo(panel)
                except AcquisitionError as exc:
                    self._note(
                        f"the popup entry at {entry['rect'][:2]} did not open the "
                        f"{PARAMETERS_ENTRY!r} dialog: {exc}"
                    )
                    self._close_wrong_dialog(panel)
                    continue
                return panel
            raise AcquisitionError(
                f"none of the {pressed} {PARAMETERS_MENU!r} popup entries pressed in "
                f"screen order opened the {PARAMETERS_ENTRY!r} dialog: that dialog is the "
                "one holding the channel combo, and within "
                f"{_ENTRY_DIALOG_TIMEOUT_S:.1f} s per entry none produced it"
            )
        finally:
            # The menu has been used (or the attempt is over, hover or press): the
            # operator's cursor goes back, so no path leaves it parked on the menubar.
            self._restore_cursor(saved)

    def _close_parameters_dialog(self, panel: dict) -> None:
        """Close the dialog with its LEFT button (``Cancel``), never a window close.

        The app confines the cursor to its dialogs, so an open one traps the operator
        (docs/16 §6); a panel whose bottom row cannot be resolved is noted instead of
        raising, so a failed point is never masked by a failed cleanup.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
        except AcquisitionError as exc:
            self._note(f"the {PARAMETERS_ENTRY!r} dialog could not be closed: {exc}")

    def ensure_channel(self) -> int:
        """Make the application measure on the configured channel, and prove it took.

        Called before **every** point, because the channel is what decides which
        channel's block the stored file carries — and a point recorded on the wrong
        channel decodes as a perfectly valid point that is not the point (docs/16 §12,
        the channel trap). The order is the load-bearing part:

        1. open ``Parameters → Operating parameters`` — the menubar button is
           **hovered with the operator's real cursor** (:meth:`_hover_centre`: this
           application's menubar answers nothing posted), the popup is identified as the
           panel that appeared on that hover, its caption-less entries are pressed in
           **screen order** (the first is ``Operating parameters``) while the cursor is
           still on the button (moving it off can dismiss a hover-opened popup), and the
           cursor is put back once an entry has been pressed — the entry press is posted,
           which popup entries do answer. Which dialog opened is decided **by content**,
           never by a caption: a dialog that does not hold the channel combo is closed
           with its LEFT button and the next entry in screen order is tried;
        2. find the channel combo *structurally* (see :meth:`_channel_combo`);
        3. read the channel back from the dialog; if it is not the configured one,
           write the selection (``CB_SETCURSEL`` + ``CBN_SELCHANGE``, no Enter) and
           read it back **again** — a combo write can silently not apply (docs/16 §2);
        4. accept the dialog, then re-open it and read the selection again: only the
           re-opened dialog shows what the *application* kept, not what the control
           believes;
        5. close it with the left button.

        Returns the verified channel. Any step that cannot be verified raises
        :class:`AcquisitionError` naming what was asked for and what the dialog showed,
        which fails the point — recording on an unverified channel is the worst outcome
        this driver can produce.
        """
        wanted = self._channel_setting
        panel = self._open_parameters_dialog()
        try:
            combo, parent = self._channel_combo(panel)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                self._combo_select(combo["hwnd"], wanted.combo_index, parent)
                index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the measurement channel was not selected: channel {wanted.channel} "
                    f"(combo index {wanted.combo_index}) was requested in the "
                    f"{PARAMETERS_ENTRY!r} dialog, but the dialog reads back index {index} "
                    f"({text!r}) — recording here would store another channel's block"
                )
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.CONFIRM)  # accept the dialog
        except BaseException:
            self._close_parameters_dialog(panel)
            raise
        confirmed = self._open_parameters_dialog()
        try:
            combo, _parent = self._channel_combo(confirmed)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the application did not keep the measurement channel: channel "
                    f"{wanted.channel} (combo index {wanted.combo_index}) was selected and "
                    f"accepted, but a re-opened {PARAMETERS_ENTRY!r} dialog reads back index "
                    f"{index} ({text!r})"
                )
        finally:
            self._close_parameters_dialog(confirmed)
        return wanted.channel

    # ------------------------------------------------------------------ Actuator

    def layout_note(self) -> str | None:
        """``None`` only on the clean measurement layout; a summary note otherwise.

        A popup, a dialog or a simulator-only screen means parameter roles may resolve to
        the wrong widgets, so a run must refuse to start. The note names what was
        resolved — window class, panel count, the strip's view and button row, any
        overlay — so the refusal is diagnosable from the log alone.
        """
        roles = self._resolve()
        if roles["layout_expected"]:
            return None
        state = self._state_of(roles)
        overlay = self._find_overlay(roles)
        note = (
            f"{self._class_name}: {len(roles['raw'])} visible controls in "
            f"{len(roles['panels'])} panels (the clean measurement screen has "
            f"{EXPECTED_CONTROL_COUNT} in {EXPECTED_PANEL_COUNT}); strip view "
            f"{state.view.value} with {state.button_count} button(s); "
            f"overlay {overlay[0].value if overlay else 'none'}"
        )
        if roles["open_popup"]:
            note += "; a menu popup is open (never dismissed by WM_CLOSE here)"
        return note

    def read_parameter(self, role: ParamRole | str) -> str:
        """The parameter column's current text for ``role``."""
        wanted = self._as_role(role)
        row = self._resolve()["params"].get(wanted)
        if row is None:
            raise AcquisitionError(
                f"no parameter column field for {wanted.value!r}; only "
                f"{[r.value for r in PARAM_COLUMN_ORDER]} live in the column"
            )
        return self._get_text(row["edit"]["hwnd"])

    def write_parameter(self, role: ParamRole | str, value: str) -> str:
        """Write one column field, commit it, and **return the app's read-back**.

        The read-back is the return value on purpose: a write is never assumed to have
        taken (the app trims gate counts to what fits, docs/07). Returning the text is a
        superset of the Protocol's ``None``.
        """
        wanted = self._as_role(role)
        row = self._resolve()["params"].get(wanted)
        if row is None:
            raise AcquisitionError(f"no parameter column field for {wanted.value!r}")
        win32gui, _ = _gui()
        edit = row["edit"]
        self._set_text_commit(edit["hwnd"], value, win32gui.GetParent(edit["hwnd"]))
        return self._get_text(edit["hwnd"])

    def apply_point(self, parameters: ParameterSet) -> dict[ParamRole, str]:
        """Apply a point's window in :func:`…actuator.ordered_writes` order.

        Resolution before gates, always: writing the resolution makes the app recompute
        the gate count, so the gate count must be the last request it sees (805 requested
        -> 474 accepted in the wrong order, docs/16 §14). Returns the read-back for every
        write, keyed by role.
        """
        readbacks: dict[ParamRole, str] = {}
        for role, value in ordered_writes(parameters):
            readbacks[role] = self.write_parameter(role, value)
        return readbacks

    def select_combo(self, name: str, index: int) -> None:
        """Select entry ``index`` of the named column combo (no Enter)."""
        combo = self._resolve()["combos"].get(name)
        if combo is None:
            raise AcquisitionError(f"no {name!r} combo in the parameter column")
        win32gui, _ = _gui()
        self._combo_select(combo["hwnd"], index, win32gui.GetParent(combo["hwnd"]))

    def strip_state(self) -> StripState:
        """The strip's current structure, freshly resolved."""
        return self._state_of(self._resolve())

    def wait_for_view(
        self, views: Iterable[StripView | str], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        """Poll until the strip reaches one of ``views``; return the last state seen.

        Overlays are *not* answered here — this is the protocol's read-only wait, and the
        caller decides whether a wedged view is a failure. The cycle uses the
        overlay-watching variant (:meth:`_wait_for_view_guarded`).
        """
        wanted = {v if isinstance(v, StripView) else StripView(v) for v in views}
        deadline = time.monotonic() + max(0.0, timeout_s)
        state = self.strip_state()
        while state.view not in wanted and time.monotonic() < deadline:
            time.sleep(_POLL_S - 0.05)
            state = self.strip_state()
        return state

    def press(self, control: StripControl) -> None:
        """Press one strip button of the *current* view, held, by position.

        The overlay guard runs **first** (posted clicks ignore modality, docs/16 §8), then
        the strip is re-resolved — its rect and its children change with the view — and the
        index comes from :func:`…actuator.press_index`, never from a width.
        """
        self._settle_press()
        roles = self._resolve()
        if roles["open_popup"]:
            raise AcquisitionError(
                "a menu popup is open; the strip binding would be unreliable — close it from "
                "the UI, this driver never WM_CLOSEs a popup"
            )
        if roles["strip_panel"] is None:
            raise AcquisitionError("no recording strip panel found")
        state = self._state_of(roles)
        index = state.index_of(
            control
        )  # raises with the known row when the press is impossible
        self._click_hold(roles["strip_row"][index]["hwnd"])
        self.last_roles = self._resolve()  # the panel morphed: never reuse the old row

    def answer_overlay(self) -> OverlayKind | None:
        """Answer an overlay if one is up, and say what it was.

        Warnings are answered with the LEFT button (:func:`…actuator.overlay_answer`), so an
        existing file is never silently replaced. The Store dialog is returned **untouched**
        — it is not an overlay to dismiss, it is where the name is set. Nothing is ever
        ``WM_CLOSE``\\ d: an unanswered overlay traps the operator's cursor in the app, and
        a closed one can lose the step the caller is mid-way through.
        """
        answered: OverlayKind | None = None
        for _ in range(4):
            found = self._find_overlay()
            if found is None:
                return answered
            kind, panel, kids = found
            answer = overlay_answer(kind)
            if answer is None:
                return kind  # the Store dialog: the caller owns its fields and commit
            self._dialog_button(panel, kids, answer)
            answered = kind
            time.sleep(_OVERLAY_SETTLE_S)
        return answered

    def set_store_name(self, name: str) -> None:
        """Write the Store dialog's file-name field with the commit recipe.

        The name field is the edit that does *not* hold a path; the path field is
        recognised by its separator, never by its position.
        """
        panel, kids = self._require_store_dialog()
        self._set_text_commit(
            self._store_name_field(panel, kids)["hwnd"], name, panel["hwnd"]
        )

    def assert_working_directory(self, directory: Path) -> str:
        """Assert the Store dialog's ``Working directory``, and set it when it differs.

        The field decides where the point lands, so it is never assumed: it is read,
        compared with ``directory`` (the path the caller will watch), written with the
        numeric/text commit recipe when it differs, and read **back** — because a write
        that did not commit leaves the application storing somewhere else while the
        control paints the new value (docs/16 §12a, §12b). Returns the verified text.

        An unresolved mismatch raises :class:`AcquisitionError` **naming both paths**,
        which fails the point: watching a folder the application is not writing to
        surfaces only as a false "no file appeared", minutes later, with nothing in it
        pointing at the real cause.
        """
        panel, kids = self._require_store_dialog()
        path_edit = self._store_edits(panel, kids)[1]
        if path_edit is None:
            edits = [
                self._get_text(k["hwnd"])
                for k in kids
                if k["cls"] in ("TEdit", "TSp_Edit")
            ]
            raise AcquisitionError(
                "the Store dialog shows no path-looking field, so its Working directory "
                f"cannot be asserted against '{directory}' (the dialog's edits are {edits})"
            )
        shown = self._get_text(path_edit["hwnd"])
        if same_directory(shown, directory):
            return shown
        self._set_text_commit(path_edit["hwnd"], str(directory), panel["hwnd"])
        readback = self._get_text(path_edit["hwnd"])
        if not same_directory(readback, directory):
            raise AcquisitionError(
                f"the Store dialog's Working directory is '{readback}' where '{directory}' "
                f"is expected (it showed '{shown}' before the write): the point would land "
                "outside the directory the caller watches, so it is refused rather than "
                "stored and waited for in the wrong folder"
            )
        self._note(
            f"the Store dialog's Working directory was {shown!r}; wrote {readback!r}"
        )
        return readback

    def commit_store(self) -> None:
        """Press the Store dialog's rightmost bottom button (``Do store``)."""
        panel, kids = self._require_store_dialog()
        self._dialog_button(panel, kids, DialogControl.CONFIRM)

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """Wait for a file that was not in ``directory`` before, and return it.

        The *new name* is detected, never the arrival of any file. An overwrite warning
        means the name was taken and the store was refused, so this raises instead of
        returning a path — the caller retries under a fresh name.
        """
        path, kind = self._poll_new_file(directory, frozenset(known), timeout_s)
        if path is not None:
            return path
        if kind is OverlayKind.WARNING:
            self.answer_overlay()
            raise AcquisitionError(
                "the Store dialog raised its overwrite warning (the name is taken); answered "
                "with its safe button — retry under a fresh name"
            )
        raise AcquisitionError(
            f"no new file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """Record ``duration_s``, stop, store as ``name``; return the stored path.

        Never a blind sleep: the recording view is polled and overlays are watched for
        throughout, because a modal warning raised mid-recording wedges the app and must be
        seen. Any failure dismisses overlays, leaves the application not recording, and
        raises :class:`AcquisitionError` — a point that failed is never returned as if it
        had been stored.
        """
        try:
            note = self.layout_note()
            if note is not None:
                raise AcquisitionError(
                    f"refusing to start on an unclean layout: {note}"
                )
            state = self.strip_state()
            if state.view is StripView.STORE:
                self.press(
                    StripControl.NEW_ACQUISITION
                )  # dismiss the leftover block view
                state = self.wait_for_view((StripView.READY,), timeout_s=VIEW_TIMEOUT_S)
            if state.view not in STARTABLE_VIEWS or state.view is not StripView.READY:
                raise AcquisitionError(
                    f"the cycle must start from the ready view, not {state.view.value!r}"
                )
            # The channel is a precondition of the point, verified from the dialog
            # before a recording is spent: another channel's block decodes as a valid
            # point that is not this point (docs/16 §12).
            self.ensure_channel()
            self.press(StripControl.RECORD)
            state = self._wait_for_view_guarded((StripView.RECORDING,), VIEW_TIMEOUT_S)
            if state.view is not StripView.RECORDING:
                raise AcquisitionError(
                    f"the Record press did not start a recording (view {state.view.value!r})"
                )
            self._hold_recording(duration_s)
            self.press(StripControl.STOP)
            state = self._wait_for_view_guarded((StripView.STORE,), VIEW_TIMEOUT_S)
            if state.view is not StripView.STORE:
                raise AcquisitionError(
                    f"Stop did not reach the store view ({state.view.value!r})"
                )
            self.press(StripControl.DO_STORE)
            self._await_store_dialog(VIEW_TIMEOUT_S)
            # Where the store will land is asserted before anything is named or
            # committed: the caller watches this directory, not the one the dialog
            # happened to remember (docs/16 §12b).
            self.assert_working_directory(directory)
            known = self._names_in(directory)
            self.set_store_name(name)
            self.commit_store()
            return self._store_until_file(name, directory, known, timeout_s)
        except AcquisitionError as exc:
            self._recover()
            raise AcquisitionError(f"{name}: {exc}") from exc
        except Exception as exc:
            self._recover()
            raise AcquisitionError(f"{name}: unexpected failure: {exc!r}") from exc

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> tuple[bool, Path | str]:
        """``record_and_store`` with the failure in the return value instead of a raise.

        ``(True, path)`` or ``(False, reason)`` — the shape a sweep loop logs per point.
        """
        try:
            return True, self.record_and_store(
                name, duration_s, directory, timeout_s=timeout_s
            )
        except AcquisitionError as exc:
            return False, str(exc)

    # ------------------------------------------------------------------ cycle internals

    def _as_role(self, role: ParamRole | str) -> ParamRole:
        """Coerce to :class:`ParamRole`, refusing the dialog-only parameters by name."""
        if isinstance(role, ParamRole):
            return role
        key = str(role)
        if key in DIALOG_ONLY_PARAMETERS:
            extra = (
                " (read back only: the app derives it from the burst and the physics)"
                if key == "sampling_volume"
                else " (it has no column field at all)"
            )
            raise AcquisitionError(
                f"{key!r} is set in the Operating parameters dialog{extra}"
            )
        try:
            return ParamRole(key)
        except ValueError:
            raise AcquisitionError(
                f"unknown parameter role {key!r}; known roles are {[r.value for r in ParamRole]}"
            ) from None

    def _settle_press(self) -> None:
        """Answer every overlay before a press; refuse if one needs the caller."""
        for _ in range(4):
            found = self._find_overlay()
            if found is None:
                return
            kind, panel, kids = found
            if kind is OverlayKind.STORE_DIALOG:
                raise AcquisitionError(
                    "the Store dialog is up; no press is safe until it is handled"
                )
            self._dialog_button(panel, kids, overlay_answer(kind) or DialogControl.SAFE)
            self._note(f"answered a {kind.value} before pressing")
            time.sleep(_OVERLAY_SETTLE_S)

    def _wait_for_view_guarded(
        self, want: Iterable[StripView], timeout_s: float
    ) -> StripState:
        """Poll for ``want`` while watching for overlays.

        A warning raised mid-step is answered with its safe button and recorded; the poll
        keeps running, so a modal warning can never turn the wait into a hang.
        """
        wanted = set(want)
        deadline = time.monotonic() + max(0.0, timeout_s)
        state = self.strip_state()
        while state.view not in wanted and time.monotonic() < deadline:
            kind = self._peek_overlay()
            if kind is OverlayKind.WARNING:
                self._note("answered a warning while waiting for a view change")
                self.answer_overlay()
            elif kind is OverlayKind.STORE_DIALOG:
                return state  # reported, not waited through
            time.sleep(_POLL_S - 0.05)
            state = self.strip_state()
        return state

    def _hold_recording(self, duration_s: float) -> None:
        """Wait out the point's duration, watching the view and the overlays."""
        deadline = time.monotonic() + max(0.0, duration_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.5, remaining))
            if self._peek_overlay() is OverlayKind.WARNING:
                # Seen, not slept through: a modal warning stalls the app's own timers.
                self._note("answered a warning raised during recording")
                self.answer_overlay()
            state = self.strip_state()
            if state.view is not StripView.RECORDING:
                raise AcquisitionError(
                    f"the recording stopped on its own (view {state.view.value!r}) after "
                    f"{duration_s - max(0.0, deadline - time.monotonic()):.1f} s"
                )

    def _await_store_dialog(self, timeout_s: float) -> tuple[dict, list[dict]]:
        """Wait for the Store dialog, answering warnings that come up first."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            kind = self._peek_overlay()
            if kind is OverlayKind.STORE_DIALOG:
                return self._require_store_dialog()
            if kind is OverlayKind.WARNING:
                self._note("answered a warning before the Store dialog appeared")
                self.answer_overlay()
            time.sleep(_POLL_S)
        raise AcquisitionError("the Store dialog did not open after Do store")

    def _store_edits(self, panel: dict, kids: Sequence[dict]) -> tuple[dict, dict | None]:
        """The Store dialog's ``(name edit, path edit)``, top to bottom.

        The path field is recognised by its **separator** (``:`` or ``\\``), never by
        its position: which of the two edits is on top is not a fact this driver may
        assume. ``path`` is ``None`` when neither edit holds a path — a dialog that has
        never stored anything — which the caller reports rather than guesses around.
        """
        edits = sorted(
            (k for k in kids if k["cls"] in ("TEdit", "TSp_Edit")),
            key=lambda k: k["top"],
        )
        if len(edits) < 2:
            raise AcquisitionError(
                "the Store dialog does not show both a path and a name field"
            )

        def looks_like_a_path(k: dict) -> bool:
            text = self._get_text(k["hwnd"])
            return ":" in text or "\\" in text

        path_edit = next((k for k in edits if looks_like_a_path(k)), None)
        name_edit = next((k for k in edits if k is not path_edit), None)
        if name_edit is None:
            raise AcquisitionError("could not identify the Store dialog's name field")
        return name_edit, path_edit

    def _store_name_field(self, panel: dict, kids: Sequence[dict]) -> dict:
        """The Store dialog's file-name edit: the one whose text is not a path."""
        return self._store_edits(panel, kids)[0]

    @staticmethod
    def _names_in(directory: Path) -> frozenset[str]:
        """The directory's current entry names (empty when it does not exist yet)."""
        if not directory.is_dir():
            return frozenset()
        return frozenset(p.name for p in directory.glob("*"))

    def _poll_new_file(
        self, directory: Path, known: frozenset[str], timeout_s: float
    ) -> tuple[Path | None, OverlayKind | None]:
        """Poll for a name that was not in ``known``; report a warning instead of waiting."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            new = sorted(self._names_in(directory) - known)
            if new:
                return directory / new[0], None
            kind = self._peek_overlay()
            if kind is OverlayKind.WARNING:
                return None, kind
            if time.monotonic() >= deadline:
                return None, None
            time.sleep(_POLL_S)

    def _store_until_file(
        self, name: str, directory: Path, known: frozenset[str], timeout_s: float
    ) -> Path:
        """Wait for the file; on the overwrite warning answer ``No`` and retry once.

        The retry is the contract: the warning means the name was taken, and answering it
        with the LEFT button keeps the existing file — the point is stored again under a
        suffixed name, never over the old one (docs/16 §12b).
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        attempt = name
        retried = False
        while time.monotonic() < deadline:
            remaining = min(1.0, max(0.1, deadline - time.monotonic()))
            path, kind = self._poll_new_file(directory, known, remaining)
            if path is not None:
                return path
            if kind is not OverlayKind.WARNING:
                continue
            self.answer_overlay()  # LEFT button = No: never replace an existing file
            if retried:
                raise AcquisitionError(
                    "the store was refused twice by the overwrite warning; the name still collides"
                )
            retried = True
            attempt = f"{name}b"
            self._note(f"the name {name!r} was taken; retrying as {attempt!r}")
            self.set_store_name(attempt)
            self.commit_store()
        raise AcquisitionError(
            f"no file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )

    def _recover(self) -> None:
        """Leave the application safe after a failure, then let the caller report it.

        Overlays are answered (never closed), and a recording left running is stopped: a
        leftover recording would otherwise be stored under the next point's name.
        """
        try:
            for _ in range(4):
                kind = self._peek_overlay()
                if kind is None or kind is OverlayKind.STORE_DIALOG:
                    break
                self.answer_overlay()
            if self.strip_state().view is StripView.RECORDING:
                self._note("a recording was left running; pressing Stop")
                self.press(StripControl.STOP)
        except Exception as exc:  # noqa: BLE001 - recovery must never mask the failure
            self._note(f"recovery was incomplete: {exc!r}")


#: Import-time conformance check: this class must satisfy every Actuator method. Derived
#: from the Protocol itself, so it keeps holding if the Protocol grows.
_MISSING_METHODS = tuple(
    n
    for n in dir(Actuator)
    if not n.startswith("_") and not callable(getattr(Win32Actuator, n, None))
)
if _MISSING_METHODS:  # pragma: no cover - a wiring error, not a runtime case
    raise RuntimeError(
        f"Win32Actuator does not satisfy Actuator: missing {_MISSING_METHODS}"
    )
