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
menubar hover and the cursor restore and left the menu popup open on the desktop. Two
measurements followed, both reported by the operator on 2026-09-18 and confirmed here: **Escape
closes nothing in this application** — no popup, no dialog, no overlay ("noted before") — and a
hover-opened popup is not collapsed by moving the cursor off the menubar, nor past the last
entry, nor by a posted `WM_CANCELMODE`; the only clean exit is the one the driver already takes,
*pressing* an entry. So a gesture that hovers can strand the application, and only a restart
clears it (the operator restarted it once during this reconnaissance). Two rules are built in
here: a restore happens in a `finally`, and anything that *opens* a dialog closes it in a
`finally` too, because the operator has no key that would.
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
        report["screen_visible"] = [
            {
                "cls": row.get("cls"),
                "text": row.get("text"),
                "rect": row.get("rect"),
            }
            for row in tree
            if row.get("visible")
        ]

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
    panel = None
    try:
        panel = actuator._open_parameters_dialog()
        report["dialog"] = {k: v for k, v in panel.items() if k != "raw"}
        dialog = walk(panel["hwnd"], text)
        report["dialog_controls"] = len(dialog)
        report["dialog_with_text"] = stated(dialog)
        report["dialog_value_buttons"] = [
            row for row in dialog if row.get("cls") == "TSp_Value_Button"
        ]
        # The whole tree, so the fixture a test pins the binding against is complete rather than
        # only the controls that happened to state something on the day.
        report["dialog_all"] = [
            {
                "depth": row["depth"],
                "cls": row.get("cls"),
                "text": row.get("text"),
                "rect": row.get("rect"),
                "visible": row.get("visible"),
            }
            for row in dialog
        ]
        # **Does the dialog populate lazily?** The first run of this probe (against an instance
        # that had been up ten hours, whose surfaces had therefore been built at least once) read
        # the three dialog-only facts straight out of the main window's hidden panels; the run
        # against a *freshly restarted* instance found those panels stating other things and none
        # of these. So: dump the same subtree again after it has been on screen for two seconds,
        # and dump the main window's panels again while it is open, to see whether a value appears
        # with time or with the surface being built.
        time.sleep(2.0)
        again = walk(panel["hwnd"], text)
        report["dialog_with_text_after_2s"] = stated(again)
        report["dialog_controls_after_2s"] = len(again)
        report["dialog_value_buttons_after_2s"] = [
            row for row in again if row.get("cls") == "TSp_Value_Button"
        ]
        if root:
            built = walk(root, text)
            report["tree_with_text_while_dialog_open"] = stated(built)
    except (driver.AcquisitionError, ValueError) as exc:
        report["dialog_error"] = repr(exc)
    finally:
        # A dialog is *not* recoverable by the operator: Escape closes nothing in this
        # application (reported 2026-09-18 and noted before), so a dump that raises must still
        # put the dialog back the way it found it — its own left (`Cancel`) button.
        if panel is not None:
            try:
                actuator._close_parameters_dialog(panel)
                report["dialog_closed"] = True
            except (driver.AcquisitionError, ValueError) as exc:
                report["dialog_close_error"] = repr(exc)

    # --- 5. the read path itself, as the driver now reads it -----------------------------
    # The reconnaissance above established *where* the three dialog-only facts are stated; this is
    # the implementation reading them as the driver performs it, on the same application, in the
    # same run: the table is bound by position, its shape and its anchors are checked against the
    # screen, and the dialog is closed again. The snapshot is then taken twice — once with the
    # reading handed over, once without it — because the difference between the two is the whole
    # point of the hand-over rule: a reading carries what a step established, and only that.
    try:
        # What the reader is looking at, before it reads: a refusal that says "no value buttons"
        # without saying what *was* there cannot be told from a stale binding.
        diagnostic = actuator._open_parameters_dialog()
        kids = actuator._children_of(diagnostic["hwnd"], actuator._resolve())
        report["read_path_panel"] = {k: v for k, v in diagnostic.items() if k != "raw"}
        report["read_path_children"] = len(kids)
        report["read_path_classes"] = sorted({k["cls"] for k in kids})
        report["read_path_value_buttons"] = sum(
            1 for k in kids if k["cls"] == "TSp_Value_Button"
        )
        actuator._close_parameters_dialog(diagnostic)

        reading = actuator.read_dialog_parameters()
        report["dialog_reading"] = json.loads(reading.model_dump_json())
        report["dialog_reading_readable"] = reading.readable()
        with_it = actuator.instrument_snapshot(routed_channel=None, dialog_parameters=reading)
        without_it = actuator.instrument_snapshot(routed_channel=None)
        report["snapshot_with_the_reading"] = {
            name: fact.model_dump() for name, fact in with_it.facts()
        }
        report["snapshot_without_the_reading"] = {
            name: fact.model_dump() for name, fact in without_it.facts()
        }
    except (driver.AcquisitionError, ValueError) as exc:
        report["read_path_error"] = repr(exc)

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
