"""Read-only: enumerate this application's **top-level windows**, so a surface the main-window walk
cannot see can still be read — the caption-less cursor info window above all.

**Why this exists.** ``main_geometry.py`` dumps the tree of ``TMain_Scr`` and everything under it. A
window the application spawns *beside* its main window is not a descendant of ``TMain_Scr``, so no
main-tree dump can ever see it — and "it is not in the tree" is therefore **not** evidence that it
carries no controls. This probe asks the question at the right level: which top-level windows does this
process own right now, and does any of them expose readable control text?

**What it does, in order — and it presses nothing, moves nothing, opens nothing, closes nothing.**

1. locate the application's main window through the driver's own locator (class ``TMain_Scr``, with the
   driver's own refusal if it is absent) and take its process id;
2. ``EnumWindows`` over every top-level window, keep the ones this process owns, and for each record
   hwnd, class, caption, rect, visibility and **direct children**, each child's text read with the
   driver's own reader (``WM_GETTEXT`` — never ``win32gui.GetWindowText``, which cannot read another
   process's controls);
3. photograph the whole screen three times (``PIL.ImageGrab(all_screens=True)``), keep the last frame,
   and compare the first two byte-for-byte so ``stable`` says whether the screen was still while it was
   photographed; ``non_blank`` counts the frame's distinct greys, so a flat capture cannot pass as one;
4. print one JSON object on stdout. The only files written are that PNG and the dispatcher's log.

**How to read the result.** ``info_windows`` is every visible top-level window of this process that is
not the main window. If the cursor info box is up on the plot and its depth/value appear *there* as
control text, an app-side readout exists and an experiment can read it live; if that list holds only the
application's own message window while the box is visibly painted, the readout is paint-only and the
analysis stays post-processing. The box's presence is taken from the screenshot, never inferred from the
window list.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from udv_echo_process.acquire import driver

OUT = ROOT / "outputs" / "live"


def _top_level_windows(win32gui) -> list[int]:
    found: list[int] = []

    def visit(hwnd, _lparam):
        found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    return found


def _child_windows(win32gui, parent: int) -> list[int]:
    found: list[int] = []

    def visit(child, _lparam):
        found.append(child)
        return True

    win32gui.EnumChildWindows(parent, visit, None)
    return found


def _pid_of(win32process, hwnd: int) -> int | None:
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:  # noqa: BLE001 - a window that dies mid-enumeration is simply not ours
        return None


def _describe(win32gui, text, hwnd: int) -> dict[str, object]:
    try:
        rect = list(win32gui.GetWindowRect(hwnd))
    except Exception:  # noqa: BLE001 - a rect we cannot read is recorded as absent
        rect = None
    return {
        "hwnd": hwnd,
        "cls": win32gui.GetClassName(hwnd),
        "text_wm_gettext": text(hwnd),
        "rect": rect,
        "visible": bool(win32gui.IsWindowVisible(hwnd)),
        "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
    }


def main() -> int:
    import win32gui
    import win32process
    from PIL import ImageGrab

    report: dict[str, object] = {"probe": "top_level_windows"}

    try:
        actuator = driver.Win32Actuator()
        hwnd = actuator._main_hwnd()
    except driver.AcquisitionError as exc:
        report["error"] = f"no main window: {exc}"
        print(json.dumps(report), flush=True)
        return 2

    text = actuator._get_text
    main_pid = _pid_of(win32process, hwnd)
    report["main_window"] = {
        "hwnd": hwnd,
        "cls": win32gui.GetClassName(hwnd),
        "caption": text(hwnd),
        "pid": main_pid,
        "rect": list(win32gui.GetWindowRect(hwnd)),
        "foreground": bool(win32gui.GetForegroundWindow() == hwnd),
    }

    ours: list[dict[str, object]] = []
    for w in _top_level_windows(win32gui):
        if _pid_of(win32process, w) != main_pid:
            continue
        entry = _describe(win32gui, text, w)
        entry["is_main_window"] = w == hwnd
        kids = [_describe(win32gui, text, c) for c in _child_windows(win32gui, w)]
        entry["children"] = kids
        entry["child_count"] = len(kids)
        ours.append(entry)

    report["top_level_windows"] = ours
    report["top_level_count"] = len(ours)
    info = [e for e in ours if e["visible"] and not e["is_main_window"]]
    report["info_windows"] = info
    report["info_window_count"] = len(info)

    interesting: list[dict[str, object]] = []
    for e in ours:
        for c in e["children"]:
            blob = f"{c.get('text_wm_gettext') or ''} {c.get('cls') or ''}".lower()
            if any(t in blob for t in ("depth", "veloc", "mm")):
                interesting.append(
                    {"window": e["hwnd"], "cls": c["cls"], "text": c["text_wm_gettext"], "rect": c["rect"]}
                )
    report["depth_or_velocity_text_controls"] = interesting

    images: dict[str, object] = {}
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        shots = []
        for label in ("a", "b"):
            frame = ImageGrab.grab(all_screens=True)
            shots.append(frame)
            frame.save(str(OUT / f"top-level-windows-full-{label}.png"))
        final = ImageGrab.grab(all_screens=True)
        greys = final.convert("L").getcolors(maxcolors=256) or []
        images = {
            "size": list(final.size),
            "mode": final.mode,
            "distinct_grey_levels": len(greys),
            "grey_range": sorted({c for _n, c in greys})[:1] + sorted({c for _n, c in greys})[-1:],
            "non_blank": len(greys) > 2,
            "stable": shots[0].tobytes() == shots[1].tobytes(),
            "saved_to": str(OUT / "top-level-windows-full-a.png"),
        }
    except Exception as exc:  # noqa: BLE001 - a failed capture is reported, never raised
        images = {"error": repr(exc)}
    report["images"] = images
    report["screen_non_blank"] = bool(images.get("non_blank", False)) if isinstance(images, dict) else False

    print(json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
