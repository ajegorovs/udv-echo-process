"""Inventory the application's **pre-created, hidden** panels — and touch nothing.

**Why this exists.** The ``Channels`` dropdown is the one surface the multiplexed plan has to
bind and the one surface nobody has enumerated: ``UI-MENU-10`` is a *picture* of it, and a
picture names captions but no handle, no class and no check state. Opening the popup is the
expensive way to get those — the menubar opens on a real-cursor hover, and this driver cannot
dismiss a hover-opened popup afterwards (``udop/parameters.py``: the cursor restore, ``ESC``,
a click outside and a posted ``WM_CANCELMODE`` all leave it up; ``WM_CLOSE`` wedges the
application's modal menu loop), so the operator has to clear it by hand.

The cheap half is this probe: this application **pre-creates** its menu overlays at startup
with ``WS_VISIBLE`` off (the reason ``_is_visible`` exists at all, and the live failure that
made it necessary — a panel in the tree is not a menu on screen). So the whole control tree of
each dropdown, with handles, classes, rectangles and check states, is readable **without
hovering anything and without moving the operator's cursor**.

**What it does.**

1. resolves the screen through the driver's own resolver (``_resolve``) and reports the
   window, its class and rect, the foreground window and whether a popup/dialog is already up
   — the read refuses to pretend it is measuring a clean screen;
2. lists every panel in the tree that is **not visible** (``_hidden_panels``: presence is
   evidence, never a target) with its rect, and for each one walks **every** descendant
   (``_descendants_of``) and reads, per control: class, rect, ``IsWindowVisible``, own text
   (``WM_GETTEXT`` through the driver's reader — ``GetWindowText`` returns ``""`` for
   everything owned by another process), and, where the class makes it meaningful, the
   *state*: ``BM_GETCHECK``/``BM_GETSTATE`` for buttons and checkboxes, ``CB_GETCURSEL`` plus
   the item list for combos;
3. does exactly the same for the **visible** panels, so the hidden rows can be compared with
   the screen the application is actually painting — a panel that is hidden *and* shaped like
   a dropdown is the popup, and the comparison is what says so;
4. prints one JSON object and exits. **No press, no hover, no cursor movement, no write.**

**Reading the result.** A hidden panel whose width is a few hundred pixels, whose height lines
up with the crop the index records, and whose children include ``TSp_CheckBox`` rows and a
``TComboBox`` is the ``Channels`` popup. Which *one* it is, is decided by geometry against
``UI-MENU-10`` and by the control inventory — never by an index into a list of panels, and never
by a caption, because these widgets have none.

**The dispatcher trap, unchanged.** Name the probe as a file **under ``tools/live/probes``**::

    ./tools/live/dispatch.sh hidden_menus.py

A repo-relative path is joined onto the probes directory again by ``task_run.py`` and finds no
file, and the dispatcher then polls for an exit line that can never appear.
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

#: ``BM_GETCHECK`` / ``BM_GETSTATE`` / ``CB_GETCURSEL`` — reads only; none of these change a
#: control, which is the condition for running this probe on an instrument someone is using.
BM_GETCHECK = 0x00F0
BM_GETSTATE = 0x00F2
CB_GETCURSEL = 0x0147

#: Button-ish classes: the ones whose check state means something. Read for every class anyway
#: (a message an unused class ignores is harmless), but only reported where it applies.
BUTTON_CLASSES = (
    "TSp_CheckBox",
    "TSp_Button",
    "TSp_RadioButton",
    "Button",
)
COMBO_CLASSES = ("TComboBox", "TSp_ComboBox", "ComboBox")


def state_of(hwnd: int, cls: str) -> dict:
    """The read-only state a control exposes: check, state bits, combo selection and items.

    Every call here is a ``SendMessage`` of a *getter*. A class that does not implement one
    answers 0, which is reported as it came back rather than interpreted: ``checked: 0`` on a
    class that has no check state is not "unchecked", and the row carries ``cls`` so the reader
    can tell the two apart.
    """
    row: dict[str, object] = {}
    if cls in BUTTON_CLASSES or "Check" in cls:
        try:
            row["check"] = win32gui.SendMessage(hwnd, BM_GETCHECK, 0, 0)
        except win32gui.error as exc:
            row["check_error"] = repr(exc)
        try:
            row["state"] = win32gui.SendMessage(hwnd, BM_GETSTATE, 0, 0)
        except win32gui.error as exc:
            row["state_error"] = repr(exc)
    if cls in COMBO_CLASSES or "Combo" in cls:
        try:
            row["cursel"] = win32gui.SendMessage(hwnd, CB_GETCURSEL, 0, 0)
        except win32gui.error as exc:
            row["cursel_error"] = repr(exc)
    return row


def walk(hwnd: int, read_text) -> list[dict]:
    """Every descendant of ``hwnd``, live, visible or not — class, rect, visibility, state.

    Depth-first pre-order, so a parent is the row immediately above its children and the list
    order is the screen order within each nesting level. A control that vanishes mid-walk is a
    row, not a failed read.
    """
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
                    "id": win32gui.GetDlgCtrlID(child),
                }
                row.update(state_of(child, cls))
                rows.append(row)
                stack.append(child)
            except win32gui.error as exc:
                rows.append({"hwnd": child, "parent": parent, "error": repr(exc)})
            child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def summarise(panel: dict, controls: list[dict]) -> dict:
    """The panel's shape as counts and its child classes — the fingerprint a popup is known by."""
    classes: dict[str, int] = {}
    for row in controls:
        if "cls" in row:
            classes[row["cls"]] = classes.get(row["cls"], 0) + 1
    return {
        "hwnd": panel["hwnd"],
        "rect": list(panel["rect"]),
        "id": panel.get("id"),
        "controls": len(controls),
        "classes": dict(sorted(classes.items(), key=lambda kv: -kv[1])),
        "checked": [
            {"hwnd": row["hwnd"], "check": row.get("check"), "rect": row.get("rect")}
            for row in controls
            if row.get("check") == 1
        ],
    }


def emit(report: dict, started: float) -> None:
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    started = time.monotonic()
    report: dict[str, object] = {"probe": "hidden_menus"}

    actuator = driver.Win32Actuator()
    text = actuator._get_text

    roles = actuator._resolve()
    report["window"] = {
        "hwnd": roles.get("window"),
        "class": win32gui.GetClassName(roles["window"])
        if roles.get("window")
        else None,
        "caption": actuator.window_caption(),
        "rect": list(win32gui.GetWindowRect(roles["window"]))
        if roles.get("window")
        else None,
    }
    report["foreground"] = {
        "hwnd": win32gui.GetForegroundWindow(),
        "class": _safe_class(win32gui.GetForegroundWindow()),
        "is_application": win32gui.GetForegroundWindow() == roles.get("window"),
    }
    report["screen_state"] = {
        "open_popup": roles.get("open_popup"),
        "panels_visible": len(roles.get("panels") or []),
        "raw_controls": len(roles.get("raw") or []),
        "strip_slider": roles.get("strip_slider"),
    }

    # --- visible panels: the screen the application is painting right now --------------------
    visible: list[dict] = []
    for panel in roles.get("panels") or []:
        try:
            controls = walk(panel["hwnd"], text)
        except (win32gui.error, OSError) as exc:
            visible.append({"hwnd": panel["hwnd"], "walk_error": repr(exc)})
            continue
        visible.append({**summarise(panel, controls), "tree": controls})
    report["visible_panels"] = visible

    # --- hidden panels: the pre-created overlays, with their whole control tree ------------
    hidden_panels = actuator._hidden_panels()
    report["hidden_panel_count"] = len(hidden_panels)
    hidden: list[dict] = []
    for panel in hidden_panels:
        try:
            controls = walk(panel["hwnd"], text)
        except (win32gui.error, OSError) as exc:
            hidden.append(
                {**{k: panel[k] for k in ("hwnd", "rect")}, "walk_error": repr(exc)}
            )
            continue
        row = summarise(panel, controls)
        # The full tree for every hidden panel: there were few enough of them to print whole,
        # and which children matter is decided by the reader against UI-MENU-10, not here.
        row["tree"] = controls
        hidden.append(row)
    report["hidden_panels"] = hidden

    # --- combos, wherever they are: the item list is an identity, not a caption -------------
    combos: list[dict] = []
    for source, rows in (("visible", visible), ("hidden", hidden)):
        for panel in rows:
            for control in panel.get("tree") or []:
                if control.get("cls") in COMBO_CLASSES or "Combo" in str(
                    control.get("cls")
                ):
                    try:
                        items = actuator._combo_items(control["hwnd"])
                    except Exception as exc:  # noqa: BLE001 - a read failure is a row
                        items = (f"<unreadable: {exc!r}>",)
                    combos.append(
                        {
                            "panel": panel.get("hwnd"),
                            "source": source,
                            "hwnd": control["hwnd"],
                            "cls": control.get("cls"),
                            "rect": control.get("rect"),
                            "cursel": control.get("cursel"),
                            "items": list(items),
                        }
                    )
    report["combos"] = combos
    report["driver_notes"] = list(actuator.warnings)
    emit(report, started)
    return 0


def _safe_class(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd)
    except win32gui.error:
        return "<vanished>"


if __name__ == "__main__":
    raise SystemExit(main())
