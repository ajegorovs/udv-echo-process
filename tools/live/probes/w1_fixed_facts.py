"""W1 reconnaissance: where the dialog-only fixed facts, and the cap, are stated on the live app.

The plan's W1 asks for the **read path** of four facts that no surface here can state yet: the
sound speed, the first gate and the burst length (dialog-only, ``actuator.DIALOG_ONLY_PARAMETERS``)
and the block cap (an application setting, "Do not keep in a block more profiles than", in
``Record settings``). Nothing else in this slice needs the instrument, so this probe answers, once,
against the running application:

1. **what the reading says now** — ``instrument_snapshot(routed_channel=None)``, printed whole.
   Asked for *no* routing on purpose: the reading then presses nothing at all (no menubar hover,
   no dialog), which is the safest live check of the P1 slice and the honest state — the channel
   is carried unreadable rather than assumed;
2. **the whole control tree of the main window**, visible *and* hidden, with every control's own
   text — read with the driver's own reader (``WM_GETTEXT``, ``driver._get_text``), never
   ``win32gui.GetWindowText``: that API does **not** retrieve text from a control in another
   process, which is why a first run of this probe saw empty captions everywhere (measured
   2026-09-18);
3. **the ``Parameters`` popup's entries** — hovered with the driver's ported gesture and read,
   **never pressed**. Every entry below the topmost one is state-changing: the second is
   ``Default parameters``, and pressing it *selects the assisted mode* (manual doc 04, and
   ``driver._open_parameters_dialog``'s own note records the assisted-mode word flipping in a file
   after a retry walked down this popup). The popup is dismissed by moving the cursor back off the
   menubar, and whether it closed is reported;
4. **the ``Operating parameters`` dialog's own tree**, opened through the driver's gesture (the
   topmost entry only) and closed again with its **left** button. Its widgets are caption-less, so
   a field is identified the way this repository identifies them: by **position** in the dialog and
   by the **value** it reads back, matched against the values measured on this install.

Nothing is written and nothing is accepted: the presses are the topmost menubar entry and the
dialog's own left (``Cancel``) button. Output is JSON on stdout, which ``task_run.py`` tees to
``outputs/live/task-<probe>.log``.

**A probe that hovers owns its cleanup.** The first run of this probe crashed *between* the
menubar hover and the cursor restore, and left the menu popup open on the desktop — after which
every later gesture refused ("a menu popup is already open; this driver never ``WM_CLOSE``s a
popup"). Two lessons are built in here: the restore happens in a ``finally``, and step 0
*recovers* from that state rather than only avoiding it, by moving the real cursor off the menubar
(which is what closes the popup) and reporting whether it closed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import win32gui

from udv_echo_process.acquire import driver

#: How deep the walk goes: the app nests a dialog inside a panel inside the main window.
MAX_DEPTH = 6


def walk(hwnd: int, read_text, depth: int = 0) -> list[dict]:
    """Every descendant of ``hwnd`` — visible or not — with its class, rect and own text."""
    rows: list[dict] = []
    if depth > MAX_DEPTH:
        return rows
    child = win32gui.GetWindow(hwnd, 5)  # GW_CHILD
    while child:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(child)
            rows.append(
                {
                    "depth": depth,
                    "hwnd": child,
                    "cls": win32gui.GetClassName(child),
                    "text": read_text(child),
                    "rect": [left, top, right, bottom],
                    "visible": bool(win32gui.IsWindowVisible(child)),
                    "parent": hwnd,
                }
            )
        except win32gui.error as exc:  # a control that died mid-walk is not a failure to report
            rows.append({"depth": depth, "hwnd": child, "error": repr(exc)})
        rows.extend(walk(child, read_text, depth + 1))
        child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def stated(rows: list[dict]) -> list[dict]:
    """The controls that state something — an empty caption is this application's rule."""
    return [row for row in rows if row.get("text")]


def main() -> int:
    report: dict[str, object] = {"probe": "w1_fixed_facts"}

    actuator = driver.Win32Actuator()
    text = actuator._get_text
    report["channel_setting"] = getattr(actuator._channel_setting, "channel", None)

    # --- 0. a clean screen: dismiss any popup a previous gesture left open ---------------
    # A hover-opened popup is dismissed by moving the cursor off the menubar, and this driver
    # never `WM_CLOSE`s one (`_open_parameters_dialog` refuses while one is up). A probe that
    # hovers must therefore be able to *recover*, not only to avoid: the first run of this
    # probe crashed between the hover and the restore and left the popup open on the desktop,
    # which is exactly the state the operator should never have to clear by hand.
    try:
        roles = actuator._resolve()
        report["popup_open_at_start"] = bool(roles.get("open_popup"))
        if roles.get("open_popup"):
            saved = actuator._cursor_position()
            plot = roles.get("plot") or roles.get("client") or roles.get("window")
            if isinstance(plot, dict):
                target = (
                    plot["left"] + plot.get("w", 0) // 2,
                    plot["top"] + plot.get("h", 0) // 2,
                )
            else:
                # `roles["plot"]` is the control's *handle* here, not its row: the rect has to be
                # asked of the window itself.
                left, top, right, bottom = win32gui.GetWindowRect(int(plot))
                target = ((left + right) // 2, (top + bottom) // 2)
            actuator._move_real_cursor(
                target,
                what="the plot area's centre",
                why="to dismiss the menu popup a previous gesture left open — moving the "
                "cursor off the menubar is what closes it",
            )
            report["popup_dismissed_by"] = target
            report["popup_open_after_dismiss"] = bool(actuator._resolve().get("open_popup"))
            if report["popup_open_after_dismiss"]:
                # Moving the cursor off the menubar did *not* close it (measured 2026-09-18),
                # so the remaining documented route is tried: `WM_CANCELMODE` is what the system
                # itself sends to cancel a menu, and it carries no input at all. `WM_CLOSE` is a
                # different message and is deliberately never used (docs/16 §6).
                main = roles["window"]
                main_hwnd = main["hwnd"] if isinstance(main, dict) else int(main)
                u32 = driver._user32()
                WM_CANCELMODE = 0x001F
                u32.PostMessageW(main_hwnd, WM_CANCELMODE, 0, 0)
                time.sleep(0.5)
                report["popup_open_after_cancelmode"] = bool(
                    actuator._resolve().get("open_popup")
                )
    except (driver.AcquisitionError, ValueError, KeyError) as exc:
        report["dismiss_error"] = repr(exc)

    # --- 1. the reading, pressing nothing ------------------------------------------------
    try:
        snapshot = actuator.instrument_snapshot(routed_channel=None)
        report["snapshot"] = json.loads(snapshot.model_dump_json())
        report["snapshot_read"] = {
            name: snapshot.fact(name).model_dump() for name in snapshot.read_facts()
        }
        report["snapshot_unreadable"] = list(snapshot.unreadable_facts())
    except (driver.AcquisitionError, ValueError) as exc:
        report["snapshot_error"] = repr(exc)

    # --- 2. the measurement screen's own reads, and the whole tree -----------------------
    try:
        roles = actuator._resolve()
        report["raw_controls"] = len(roles.get("raw", []) or [])
        report["param_column"] = [
            {"role": str(role), "text": text(row["edit"]["hwnd"])}
            for role, row in (roles.get("params") or {}).items()
        ]
        report["strip_view"] = str(roles.get("state"))
        report["strip_row"] = str(roles.get("strip_row"))
        report["menubar"] = sorted((roles.get("menu") or {}).keys())
    except (driver.AcquisitionError, ValueError) as exc:
        report["resolve_error"] = repr(exc)

    root = None
    try:
        found: list[int] = []

        def visit(hwnd: int, _p: object) -> bool:
            if win32gui.GetClassName(hwnd) == driver.MAIN_CLASS and win32gui.IsWindowVisible(
                hwnd
            ):
                found.append(hwnd)
            return True

        win32gui.EnumWindows(visit, None)
        root = found[0] if found else None
    except win32gui.error as exc:
        report["find_error"] = repr(exc)
    report["main_hwnd"] = root
    if root:
        tree = walk(root, text)
        report["tree_controls"] = len(tree)
        report["tree_with_text"] = stated(tree)

    # --- 3. the Parameters popup's entries, read and never pressed -----------------------
    # **Opt-in** (`--popup`): measured 2026-09-18, hovering the menubar opens a popup that
    # neither a cursor restore nor a posted `WM_CANCELMODE` closes, so this read leaves the
    # application in a state only the operator can clear. It was worth doing once — the five
    # entries carry *no caption even through `WM_GETTEXT`*, which is why every binding in the
    # driver is structural — and it is not worth doing on every run.
    if "--popup" in sys.argv:
        saved = actuator._cursor_position()
        try:
            roles = actuator._resolve()
            menu = (roles.get("menu") or {}).get(driver.PARAMETERS_MENU)
            report["menu_hwnd"] = menu and menu.get("hwnd")
            before = actuator._panel_map()
            actuator._hover_centre(menu["hwnd"])
            overlay = actuator._poll_parameters_overlay(before)
            entries = driver._entry_buttons(overlay, actuator._resolve()["raw"])
            report["popup_entries"] = [
                {
                    "index": index,
                    "text": text(entry["hwnd"]),
                    "rect": [
                        entry["left"],
                        entry["top"],
                        entry["left"] + entry.get("w", 0),
                        entry["top"] + entry.get("h", 0),
                    ],
                }
                for index, entry in enumerate(entries)
            ]
            report["popup_entries_pressed"] = 0
        except (driver.AcquisitionError, ValueError, KeyError) as exc:
            report["popup_error"] = repr(exc)
        finally:
            # The restore is not optional: this is the step whose failure leaves the operator with
            # a popup on the desktop and the next gesture refusing to run.
            actuator._restore_cursor(saved)
            try:
                report["popup_still_open"] = bool(actuator._resolve().get("open_popup"))
            except (driver.AcquisitionError, ValueError) as exc:
                report["popup_recheck_error"] = repr(exc)

    # --- 4. the Operating parameters dialog, dumped and closed ---------------------------
    if report.get("popup_still_open"):
        report["dialog_error"] = "skipped: the popup did not close, and this probe never WM_CLOSEs one"
        print(json.dumps(report, indent=2, default=str))
        return 0
    try:
        panel = actuator._open_parameters_dialog()
        report["dialog"] = {k: v for k, v in panel.items() if k != "raw"}
        dialog = walk(panel["hwnd"], text)
        report["dialog_controls"] = len(dialog)
        report["dialog_with_text"] = stated(dialog)
        report["dialog_value_buttons"] = [
            row for row in dialog if row.get("cls") == "TSp_Value_Button"
        ]
        actuator._close_parameters_dialog(panel)
        report["dialog_closed"] = True
    except (driver.AcquisitionError, ValueError) as exc:
        report["dialog_error"] = repr(exc)

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
