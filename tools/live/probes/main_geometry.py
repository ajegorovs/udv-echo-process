"""Read-only: the main window's own geometry, its whole control tree, and where the strip is now.

**Why this exists.** Every number the rest of this repository binds against was measured on one
session of one machine — the parameters popup at ``left == 169`` (``driver._OVERLAY_LEFT``), the
operating dialog at ``(655, 364) 627x384`` (the W1 fixture, ``tests/test_acquire_driver.py``), the
store dialog at ``584x330`` (``docs/dop3000/live-bringup.md``) and the recording strip at
``(448, 477) 352x40`` (``docs/dop3000/udop-automation.md`` §1). Some of those are *bindings* and
some are only *notes*, and the difference decides how a moved control fails (a loud refusal or a
silent wrong press). The only way to tell which is to measure the live geometry and compare it
against the asserts, so this probe measures it — and it is the main window's own tree, which
:mod:`tools.live.probes.dialog_fields` cannot see: it opens a dialog and dumps *that*.

**It presses nothing.** No menubar hover, no popup entry, no dialog, and above all no strip
button: the ready view's three are ``Pause``, ``Record`` and ``Clear and restart``, and any of
them changes the application's recording state, which is exactly what a geometry read must not
do. The driver's own ``_resolve``/``strip_state``/``screen_fingerprint`` are reads (the last is
the supported read-only call ``acquire status`` prints), and this probe uses them rather than
reimplementing the resolution a second time.

What it reports:

1. the **main window** — class, handle, screen rect, client rect and client screen origin, whether
   it is maximised, whether it is the foreground window, and its caption through the driver's own
   reader (``WM_GETTEXT``: top-level captions do come back, where the caption-less ``TSp_*``
   controls do not);
2. the driver's **resolution** of that window — :meth:`~…Win32Actuator.screen_fingerprint` (the
   same read ``acquire status`` prints), the role map's panels/combos/parameter rows, and the
   strip: the panel it resolved, its top-row buttons in order with the :class:`StripControl` each
   position means, and the button count that mapping rests on;
3. the **whole control tree**, visible *and* hidden, each row carrying class, own text, rect,
   visibility and parent — so a control that moved can be found wherever it now is;
4. **pictures**: one full-screen frame plus a crop of the strip's *measured* rect and a crop of the
   rect the repository asserts, out of that same frame, so the two cannot disagree about the moment
   they show. Both are lossless PNGs, and each is described by its own statistics because a black
   PNG looks like a successful capture (:mod:`tools.live.probes.dialog_shot`'s rule).

Nothing is written to the application and nothing is stored. Output is one JSON object on stdout
(``task_run.py`` tees it to ``outputs/live/task-main_geometry.py.log``) and, written by absolute
path because the probe's working directory is the probes directory,
``outputs/live/main-geometry.json``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

import win32gui

# The capture half of the same measurement pass: one grab route, one blank-image check, one set of
# DPI facts — imported rather than copied, so a fix to either lands in both probes at once.
from dialog_shot import dpi_facts, grab_screen, image_stats

from udv_echo_process.acquire import driver

#: Where the pictures and the JSON go: ``outputs/`` is gitignored, and large binaries belong there.
OUT = REPO / "outputs" / "live"

#: What ``docs/dop3000/udop-automation.md`` §1 measured for the strip, and what the W1 fixture
#: pins the operating dialog and the parameters popup at. Cropped **as regions**, so the PNG shows
#: what is there now rather than asserting that something is.
ASSERTED_STRIP = (448, 477, 448 + 352, 477 + 40)
ASSERTED_DIALOG = (655, 364, 655 + 627, 364 + 384)
ASSERTED_POPUP = (169, 55, 401, 250)

#: How deep the walk goes: the application nests a value's edit inside its value button, a dialog
#: inside a panel inside the main window.
MAX_DEPTH = 6

#: A settle before the grab: the frame is taken with nothing pressed, so this only gives the
#: application its own time to finish painting after whatever the previous dispatch did.
SETTLE_S = 0.8


def walk(hwnd: int, read_text, depth: int = 0) -> list[dict]:
    """Every descendant of ``hwnd`` — visible or not — with its class, text, rect and parent.

    Depth-first, pre-order, so a parent is the entry immediately above its own children. A control
    that dies mid-walk is recorded as an ``error`` row rather than failing the dump: a partial
    inventory is what a geometry comparison can still use.
    """
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
                    "parent": hwnd,
                    "cls": win32gui.GetClassName(child),
                    "text": read_text(child),
                    "rect": [left, top, right, bottom],
                    "visible": bool(win32gui.IsWindowVisible(child)),
                }
            )
        except win32gui.error as exc:  # a vanished control is a row, not a failed run
            rows.append({"depth": depth, "hwnd": child, "parent": hwnd, "error": repr(exc)})
        rows.extend(walk(child, read_text, depth + 1))
        child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def rect_of(row: dict | None) -> list[int] | None:
    """The ``(left, top, right, bottom)`` of a driver row, which stores it as four fields."""
    if not row:
        return None
    return [row["left"], row["top"], row["left"] + row["w"], row["top"] + row["h"]]


def crop_of(frame, rect: list[int], origin: tuple[int, int]):
    """The frame's own pixels at ``rect`` — clamped, with the box recorded by the caller."""
    origin_x, origin_y = origin
    box = (rect[0] - origin_x, rect[1] - origin_y, rect[2] - origin_x, rect[3] - origin_y)
    safe = (
        max(0, box[0]),
        max(0, box[1]),
        min(frame.width, box[2]),
        min(frame.height, box[3]),
    )
    return frame.crop(safe), list(box)


def save(image, path: Path) -> dict:
    """Write one PNG and describe it — size, dimensions and the blank check in one row."""
    image.save(path, format="PNG", optimize=False)
    row = image_stats(image)
    row["path"] = str(path)
    row["bytes"] = path.stat().st_size
    return row


def emit(report: dict, started: float) -> None:
    """Stamp the elapsed time, write the JSON artifact and print the report once."""
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "main-geometry.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    started = time.monotonic()
    report: dict[str, object] = {"probe": "main_geometry"}
    OUT.mkdir(parents=True, exist_ok=True)

    actuator = driver.Win32Actuator()
    text = actuator._get_text

    # --- 1. the main window, by class, as the driver itself finds it ---------------------
    try:
        hwnd = actuator._main_hwnd()
    except driver.AcquisitionError as exc:
        report["error"] = f"no main window: {exc}"
        emit(report, started)
        return 2

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    client = win32gui.GetClientRect(hwnd)
    origin = win32gui.ClientToScreen(hwnd, (0, 0))
    import ctypes

    user32 = ctypes.windll.user32
    report["main_window"] = {
        "hwnd": hwnd,
        "cls": win32gui.GetClassName(hwnd),
        "expected_cls": driver.MAIN_CLASS,
        "caption": text(hwnd),
        "rect": [left, top, right, bottom],
        "client_rect": list(client),
        "client_origin": list(origin),
        "maximized": bool(user32.IsZoomed(hwnd)),
        "foreground": actuator._foreground_window() == hwnd,
        "screen": [user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)],
    }

    # --- 2. the driver's own resolution of that window (the binding the code uses) --------
    try:
        roles = actuator._resolve()
        fingerprint = actuator.screen_fingerprint()
        report["fingerprint"] = json.loads(fingerprint.model_dump_json())
        report["layout_note"] = actuator.layout_note()
        report["panels"] = [
            {"cls": p["cls"], "rect": rect_of(p), "id": p.get("id")}
            for p in roles.get("panels") or []
        ]
        report["visible_controls"] = len(roles.get("raw") or [])
        report["combos"] = {
            name: {"rect": rect_of(row), "id": row.get("id")}
            for name, row in (roles.get("combos") or {}).items()
        }
        report["param_rows"] = [
            {
                "role": str(row.get("role")),
                "rect": rect_of(row.get("edit")),
                "text": text(row["edit"]["hwnd"]) if row.get("edit") else None,
            }
            for row in (roles.get("param_rows") or [])
        ]
        report["open_popup"] = bool(roles.get("open_popup"))

        # --- the strip: the panel, its top row, and what each position *means* ------------
        panel = roles.get("strip_panel")
        row = roles.get("strip_row") or []
        state = actuator.strip_state()
        report["strip"] = {
            "panel_rect": rect_of(panel),
            "panel_id": panel.get("id") if panel else None,
            "panel_children": len(actuator._children_of(panel["hwnd"], roles)) if panel else 0,
            "has_slider": bool(state.has_slider),
            "view": state.view.value,
            "button_count": state.button_count,
            "row": [
                {"left_to_right_index": i, "rect": rect_of(k), "id": k.get("id")}
                for i, k in enumerate(row)
            ],
            "row_meanings": None,
            "rect_from_client_origin": (
                None if panel is None else [panel["left"] - origin[0], panel["top"] - origin[1]]
            ),
        }
        try:
            from udv_echo_process.acquire.actuator import strip_controls

            report["strip"]["row_meanings"] = [
                control.value for control in strip_controls(state.view, state.button_count)
            ]
        except (ValueError, ImportError) as exc:
            # A row the mapping does not cover is a finding, not a crash: the press by index
            # cannot be expressed for it either.
            report["strip"]["row_meanings_error"] = repr(exc)
    except (driver.AcquisitionError, ValueError) as exc:
        report["resolve_error"] = repr(exc)

    # --- 3. the whole tree, visible and hidden -------------------------------------------
    tree = walk(hwnd, text)
    report["tree_controls"] = len(tree)
    report["tree"] = tree
    report["tree_with_text"] = [row for row in tree if row.get("text")]

    # --- 4. one frame, three crops -------------------------------------------------------
    try:
        time.sleep(SETTLE_S)
        first, route = grab_screen()
        time.sleep(0.15)
        second, _ = grab_screen()
        report["capture"] = {
            "route": route,
            "settle_s": SETTLE_S,
            "frame_stable": first.tobytes() == second.tobytes(),
            "full_image_size": [second.width, second.height],
        }
        dpi = dpi_facts()
        report["dpi"] = dpi
        origin_xy = (dpi["virtual_screen_origin"][0], dpi["virtual_screen_origin"][1])
        images = {"full": save(second, OUT / "main-geometry-full.png")}
        measured = report["strip"]["panel_rect"] if report.get("strip") else None
        for name, rect in (
            ("strip_measured", measured),
            ("strip_asserted", list(ASSERTED_STRIP)),
            ("dialog_asserted", list(ASSERTED_DIALOG)),
            ("popup_asserted", list(ASSERTED_POPUP)),
        ):
            if rect is None:
                continue
            crop, box = crop_of(second, rect, origin_xy)
            row = save(crop, OUT / f"main-geometry-{name}.png")
            row["source_rect"] = list(rect)
            row["crop_box"] = box
            images[name] = row
        report["images"] = images
        report["images_note"] = (
            "one frame, four crops: the three 'asserted' regions are cropped from where the "
            "repository says a control is, so the PNG shows what is actually there — they are "
            "regions, not claims that a control is inside them"
        )
        report["non_blank"] = all(row["non_blank"] for row in images.values())
    except Exception as exc:  # noqa: BLE001 — a failed capture is reported, never fatal here
        report["capture_error"] = repr(exc)

    report["driver_notes"] = list(actuator.warnings)
    emit(report, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
