"""Open the ``Channels`` dropdown, photograph it and dump its live tree — press nothing.

**What it answers that the passive read cannot.** ``probes/hidden_menus.py`` reads the whole
dropdown while it is hidden: handles, classes, rectangles and the field values. What a *hidden*
panel cannot state is the **paint** — and in this dropdown that is where the state lives, because
there is no ``TSp_CheckBox`` in it: every tick (``Use only channel``, ``Roll over the channels``,
the twenty channel numbers) is an owner-drawn ``TSp_Button`` that answers ``BM_GETCHECK`` with 0
whether or not it is ticked. The multiplexer's on/off, the participant set and the roll-over flag
are therefore readable only as pixels, which is what this probe captures.

**What it does, in order.**

1. resolves the screen through the driver's own resolver and **refuses** when a popup or a dialog
   is already up, when the bar is not one of the two measured lengths, or when the application is
   not foreground (measured live 2026-09-17: an inactive window ignores the hover and the menu
   never opens, which reads as a broken gesture);
2. hovers the **seventh button of the menu bar** — the ``Channels`` entry, measured 2026-10-19 at
   hwnd 507514148 / rect ``(526,28,596,53)``, and the reason this probe states the ordinal at all:
   the popup it opens starts at that button's own left (526, the same convention as ``Parameters``
   at 169), so the identity is checked *after* the hover by the panel's rect, not assumed from the
   press;
3. polls for the panel that appeared **visible** on that hover, and refuses by name when none
   appears — naming the hidden panels, because a pre-created hidden overlay is not an open menu;
4. captures the whole screen twice (a stability check), crops the panel's rect out of that **same**
   frame, and saves both PNGs under ``outputs/live/`` — lossless, because the reader is reading
   small painted tick marks;
5. walks the panel's controls from the **same** moment and reports each one's class, rect, text and
   ``BM_GETCHECK``/``CB_GETCURSEL``, so the picture and the tree cannot disagree;
6. restores the operator's cursor and reports the popup **still up**. It does not close it: this
   driver cannot dismiss a hover-opened popup (the cursor restore, ``ESC``, a click outside and a
   posted ``WM_CANCELMODE`` all leave it up; ``WM_CLOSE`` wedges the modal menu loop until the
   application is restarted — ledger B20). Clearing it is the operator's one click, and the report
   says so instead of pretending the screen was left as it was found.

**Nothing is pressed**: no popup entry, no tick, no field. The hover is the only real-input step.

**The dispatcher trap, unchanged.** Name the probe as a file **under ``tools/live/probes``**::

    PROBE_TIMEOUT_S=120 ./tools/live/dispatch.sh channels_popup.py

and select a task registered for *this* clone with ``LIVE_TASK_NAME`` — the dispatcher refuses a
task whose action names another tree.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

import win32gui

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.ui.layout import observation_of
from udv_echo_process.acquire.ui.menu import MEASURED_BAR, MEASURED_BAR_LENGTHS, menubar_buttons
from udv_echo_process.acquire.udop.recording import dialog_up_clause

#: The two capture helpers and their blank-frame guard are ``dialog_shot.py``'s — proven on this
#: application, and re-deriving them here would be the second implementation of one measurement.
from dialog_shot import dpi_facts, grab_screen, image_stats, save  # noqa: E402

OUT = REPO / "outputs" / "live"

#: The entry this probe hovers, as a **position in the measured bar** — ``MENU_ORDER``'s own
#: vocabulary names it, and the bar this build paints is ``MEASURED_BAR``; both put it 8th, i.e.
#: index 7. The identity is confirmed by the popup's rect afterwards, never by this number alone.
CHANNELS_INDEX = MEASURED_BAR.index("Channels")

#: A settle between the hover and the first grab: the panel is shown by the gesture and painted a
#: moment later, and the two-frame comparison below is what measures whether it had settled.
SETTLE_S = 0.9

#: How long the popup is given to appear (the driver's own menu poll is on the same order).
POLL_S = 5.0
POLL_STEP_S = 0.1

BM_GETCHECK = 0x00F0
CB_GETCURSEL = 0x0147
COMBO_CLASSES = ("TComboBox", "TSp_ComboBox", "ComboBox")


def walk(hwnd: int, read_text) -> list[dict]:
    """Every descendant of ``hwnd`` — class, rect, visibility, text and read-only state."""
    rows: list[dict] = []
    stack = [hwnd]
    while stack:
        parent = stack.pop()
        child = win32gui.GetWindow(parent, 5)  # GW_CHILD
        while child:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(child)
                cls = win32gui.GetClassName(child)
                row = {
                    "hwnd": child,
                    "parent": parent,
                    "cls": cls,
                    "text": read_text(child),
                    "rect": [left, top, right, bottom],
                    "visible": bool(win32gui.IsWindowVisible(child)),
                }
                if "Button" in cls or "Check" in cls:
                    row["check"] = win32gui.SendMessage(child, BM_GETCHECK, 0, 0)
                if cls in COMBO_CLASSES or "Combo" in cls:
                    row["cursel"] = win32gui.SendMessage(child, CB_GETCURSEL, 0, 0)
                rows.append(row)
                stack.append(child)
            except win32gui.error as exc:
                rows.append({"hwnd": child, "parent": parent, "error": repr(exc)})
            child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def emit(report: dict, started: float) -> None:
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    started = time.monotonic()
    report: dict[str, object] = {"probe": "channels_popup"}
    OUT.mkdir(parents=True, exist_ok=True)

    actuator = driver.Win32Actuator()
    read_text = actuator._get_text

    roles = actuator._resolve()
    report["window"] = {
        "hwnd": roles.get("window"),
        "rect": list(win32gui.GetWindowRect(roles["window"])),
        "class": win32gui.GetClassName(roles["window"]),
    }
    dialog = dialog_up_clause(roles)
    if roles.get("open_popup") or dialog is not None:
        report["opened"] = False
        report["error"] = (
            f"a surface is already up on this screen, so the hover would be ambiguous: "
            f"open_popup={roles.get('open_popup')}, dialog={dialog!r} — nothing was hovered"
        )
        emit(report, started)
        return 2

    bar = menubar_buttons(observation_of(roles))
    report["bar"] = {"buttons": len(bar), "measured_lengths": list(MEASURED_BAR_LENGTHS)}
    if len(bar) not in MEASURED_BAR_LENGTHS or len(bar) <= CHANNELS_INDEX:
        report["opened"] = False
        report["error"] = (
            f"the bar paints {len(bar)} button(s), which is not one of the measured lengths "
            f"{list(MEASURED_BAR_LENGTHS)} (or not enough for entry {CHANNELS_INDEX}) — the "
            "'Channels' entry cannot be shown by position, and nothing was hovered"
        )
        emit(report, started)
        return 2
    target = bar[CHANNELS_INDEX]
    report["target"] = {
        "entry": MEASURED_BAR[CHANNELS_INDEX],
        "index": CHANNELS_INDEX,
        "hwnd": target.hwnd,
        "rect": list(target.rect) if target.rect is not None else None,
    }

    actuator._require_foreground(roles["window"])
    before = actuator._panel_map(roles)
    saved = actuator._cursor_position()
    panel: dict | None = None
    try:
        hover = actuator._hover_centre(target.hwnd)
        report["hover_point"] = list(hover)
        deadline = time.monotonic() + POLL_S
        while time.monotonic() < deadline:
            panels = actuator._panel_map()
            fresh = [
                p
                for hwnd, p in panels.items()
                if hwnd not in before and actuator._is_visible(p["hwnd"])
            ]
            if len(fresh) == 1:
                panel = fresh[0]
                break
            now_visible = [
                p
                for hwnd, p in panels.items()
                if p.get("rect") and p["left"] == target.rect.left and actuator._is_visible(hwnd)
            ]
            if len(now_visible) == 1:
                panel = now_visible[0]
                break
            time.sleep(POLL_STEP_S)
    finally:
        # The cursor goes back whatever happened — no path leaves it parked on the menubar. The
        # popup stays up: nothing this driver sends dismisses a hover-opened popup (module docstring).
        actuator._restore_cursor(saved)

    if panel is None:
        hidden = actuator._hidden_panels()
        report["opened"] = False
        report["error"] = (
            f"the '{MEASURED_BAR[CHANNELS_INDEX]}' popup did not appear within {POLL_S:.0f} s of "
            "its hover: no visible panel appeared that was not visible before it and none is a "
            "visible panel at the entry's own left; the panels in the tree that are not visible "
            f"are {[p['rect'] for p in hidden[:6]]} — a pre-created panel is not an open menu"
        )
        emit(report, started)
        return 3

    report["opened"] = True
    report["panel"] = {"hwnd": panel["hwnd"], "rect": list(panel["rect"])}

    # The tree and the picture are taken from the same moment: the tree first (cheap), then two
    # grabs for the stability answer, and the crop from the second.
    try:
        controls = walk(panel["hwnd"], read_text)
    except (win32gui.error, OSError) as exc:
        controls = []
        report["walk_error"] = repr(exc)
    report["controls"] = controls
    report["checked_rows"] = [
        {"hwnd": r["hwnd"], "rect": r.get("rect"), "check": r.get("check")}
        for r in controls
        if r.get("check") == 1
    ]

    report["dpi"] = dpi_facts()
    time.sleep(SETTLE_S)
    first, route = grab_screen()
    time.sleep(0.15)
    second, _ = grab_screen()
    report["capture"] = {
        "route": route,
        "frame_stable": first.tobytes() == second.tobytes(),
        "settle_s": SETTLE_S,
    }
    left, top, right, bottom = panel["rect"]
    origin_x, origin_y = report["dpi"]["virtual_screen_origin"]
    box = (left - origin_x, top - origin_y, right - origin_x, bottom - origin_y)
    crop = second.crop(box)
    report["images"] = {
        "popup": save(crop, OUT / "channels-popup.png"),
        "full": save(second, OUT / "channels-popup-full.png"),
    }
    report["non_blank"] = all(row["non_blank"] for row in report["images"].values())

    still_up = actuator._is_visible(panel["hwnd"])
    report["popup_left_open"] = still_up
    if still_up:
        report["operator_action"] = (
            f"the '{MEASURED_BAR[CHANNELS_INDEX]}' dropdown is still on screen at "
            f"{tuple(panel['rect'])} — one click anywhere outside it clears it; this driver never "
            "closes a hover-opened popup and never WM_CLOSEs one (that wedges the menu loop)"
        )
    report["driver_notes"] = list(actuator.warnings)
    emit(report, started)
    return 0 if report["non_blank"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
