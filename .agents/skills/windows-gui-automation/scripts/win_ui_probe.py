#!/usr/bin/env python
"""Read-only UI reconnaissance probe for a Windows desktop application.

It never clicks, types or changes anything. It answers the questions that decide how
an app without an API can be automated:

  * what top-level windows does the process own, and which are visible?
  * which controls are real child windows with a stable class name and control id
    (addressable by message) and which are owner-drawn with no identity at all?
  * what do they look like on screen, captured without stealing focus and without
    another window occluding the target?

Writes into --out: windows.json, controls.csv, summary.md, <window>.png

Usage:
  python win_ui_probe.py --process notepad.exe
  python win_ui_probe.py --process MyApp.exe --class TMain_Scr --depth 6 --out probe
  python win_ui_probe.py --pid 1356 --no-capture
  python win_ui_probe.py --process MyApp.exe --uia      # compare backends

Dependencies: pip install pywinauto pywin32 pillow

Notes: run it while the app is in the state you care about (the screen you need to map),
because hidden pages are skipped. Driving a 32-bit target from 64-bit Python is fine for
message-based access; prefer matching bitness once you need real input injection.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import sys
from datetime import datetime
from pathlib import Path

import win32gui
import win32ui
from PIL import Image
from pywinauto import Application

PW_RENDERFULLCONTENT = 0x00000002
MAX_ROWS = 8000


def rect_of(ctrl):
    try:
        r = ctrl.rectangle()
    except Exception:
        return None
    if r.right <= r.left or r.bottom <= r.top:
        return None
    return (r.left, r.top, r.right, r.bottom)


def text_of(ctrl) -> str:
    try:
        return ctrl.window_text().strip()
    except Exception:
        return ""


def info_of(ctrl) -> dict:
    ie = ctrl.element_info
    return {
        "class_name": getattr(ie, "class_name", None),
        "control_id": getattr(ie, "control_id", None),
        "automation_id": getattr(ie, "automation_id", None),
        "control_type": getattr(ie, "control_type", None),
    }


def classify(row: dict) -> str:
    """A = Win32-identifiable, B = UIA-reachable, C = text only, D = coordinates only."""
    if row.get("class_name") and row.get("control_id") is not None:
        return "A"
    if row.get("automation_id") or row.get("control_type"):
        return "B"
    if row.get("text"):
        return "C"
    return "D"


def capture_window(hwnd: int, path: Path):
    """Render the window's own pixels; works while occluded or unfocused."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None
    hdc = win32gui.GetWindowDC(hwnd)
    rendered = False
    try:
        src = win32ui.CreateDCFromHandle(hdc)
        mem = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src, w, h)
        mem.SelectObject(bmp)
        rendered = bool(
            ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), PW_RENDERFULLCONTENT)
        )
        info = bmp.GetInfo()
        img = Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bmp.GetBitmapBits(True),
            "raw",
            "BGRX",
            0,
            1,
        )
        img.save(path)
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
    except Exception:
        return None
    finally:
        win32gui.ReleaseDC(hwnd, hdc)
    return {"origin": [left, top], "size": [w, h], "printwindow_ok": rendered}


def collect_visible(root, max_depth: int) -> list[dict]:
    """Handle-deduplicated, visibility-filtered rows, sorted top-to-bottom."""
    rows: list[dict] = []
    seen: set[int] = set()

    def rec(ctrl, depth: int) -> None:
        if depth > max_depth or len(rows) > MAX_ROWS:
            return
        try:
            handle = ctrl.handle
        except Exception:
            return
        if not handle or handle in seen:
            return  # owner-drawn toolkits report the same widget under several parents
        seen.add(handle)
        try:
            if not ctrl.is_visible():
                return
        except Exception:
            return
        rect = rect_of(ctrl)
        if rect is None:
            return
        row = {"handle": handle, "depth": depth, "text": text_of(ctrl), "screen_rect": list(rect)}
        row.update(info_of(ctrl))
        row["class_hint"] = classify(row)
        rows.append(row)
        try:
            kids = ctrl.children()
        except Exception:
            return
        for kid in kids:
            rec(kid, depth + 1)

    rec(root, 0)
    rows.sort(key=lambda r: (r["screen_rect"][1], r["screen_rect"][0]))
    return rows


def dump_backend(backend: str, target: dict, cls: str | None, depth: int) -> list[dict]:
    app = Application(backend=backend).connect(timeout=10, **target)
    windows: list[dict] = []
    for win in app.windows():
        rect = rect_of(win)
        try:
            visible = bool(win.is_visible())
        except Exception:
            visible = False
        windows.append(
            {
                "handle": win.handle,
                "title": text_of(win),
                "class_name": getattr(win.element_info, "class_name", None),
                "visible": visible,
                "screen_rect": list(rect) if rect else None,
                "controls": [],
            }
        )
    for w in windows:
        if not w["visible"] or (cls and w["class_name"] != cls):
            continue
        if not (w["title"] or cls):
            continue
        w["controls"] = collect_visible(app.window(handle=w["handle"]), depth)
    return windows


def main() -> int:
    ap = argparse.ArgumentParser(
        description="read-only UI reconnaissance probe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--process", help="executable name or path")
    ap.add_argument("--pid", type=int, help="process id (alternative to --process)")
    ap.add_argument("--class", dest="cls", help="restrict the dump to this window class")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--out", default="ui_probe")
    ap.add_argument("--uia", action="store_true", help="also dump through the UI Automation backend")
    ap.add_argument("--no-capture", action="store_true", help="skip PrintWindow captures")
    args = ap.parse_args()
    if not args.process and not args.pid:
        ap.error("give --process or --pid")

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = {"process": args.pid} if args.pid else {"path": args.process}

    backends = ["win32", "uia"] if args.uia else ["win32"]
    report: dict = {"stamp": stamp, "target": args.process or args.pid, "backends": {}}
    for backend in backends:
        try:
            report["backends"][backend] = {"windows": dump_backend(backend, target, args.cls, args.depth), "error": None}
        except Exception as exc:  # connect or enumeration refused
            report["backends"][backend] = {"windows": [], "error": repr(exc)}

    # captures + image coordinates, only for the backend we will automate with
    captures: dict = {}
    if not args.no_capture and "win32" in report["backends"]:
        for w in report["backends"]["win32"]["windows"]:
            if not w["visible"] or not (w["title"] or args.cls):
                continue
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in w["title"])[:40] or "window"
            path = outdir / f"{stamp}-{safe}.png"
            cap = capture_window(w["handle"], path)
            if not cap:
                continue
            cap["file"] = str(path)
            captures[w["handle"]] = cap
            left, top = cap["origin"]
            for row in w["controls"]:
                l, t, r, b = row["screen_rect"]
                row["image_rect"] = [l - left, t - top, r - left, b - top]

    (outdir / "windows.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    with (outdir / "controls.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["backend", "window_title", "window_class", "handle", "class_name", "control_id",
             "automation_id", "control_type", "class_hint", "text", "left", "top", "right",
             "bottom", "image_left", "image_top", "image_right", "image_bottom"]
        )
        for backend, entry in report["backends"].items():
            for w in entry["windows"]:
                for row in w["controls"]:
                    ir = row.get("image_rect") or ["", "", "", ""]
                    writer.writerow(
                        [backend, w["title"], w["class_name"], row["handle"], row["class_name"],
                         row["control_id"], row["automation_id"], row["control_type"],
                         row["class_hint"], row["text"], *row["screen_rect"], *ir]
                    )

    md = [f"# UI probe - {args.process or args.pid} - {stamp}", ""]
    for backend, entry in report["backends"].items():
        md.append(f"## backend `{backend}`")
        if entry["error"]:
            md += [f"- connect/enumeration failed: `{entry['error']}`", ""]
            continue
        for w in entry["windows"]:
            hint_counts: dict = {}
            for row in w["controls"]:
                hint_counts[row["class_hint"]] = hint_counts.get(row["class_hint"], 0) + 1
            cap = captures.get(w["handle"], {})
            md += [
                "",
                f"### `{w['title']}` class `{w['class_name']}` handle {w['handle']}",
                "",
                f"- visible: {w['visible']}  rect: {w['screen_rect']}",
                f"- controls: {len(w['controls'])}  A/B/C/D: {hint_counts}",
            ]
            if cap:
                md.append(f"- capture: `{cap['file']}` origin `{cap['origin']}` printwindow_ok={cap['printwindow_ok']}")
            md += [
                "",
                "| depth | class | control_id | type | hint | text | image_rect |",
                "|---|---|---|---|---|---|---|",
            ]
            for row in w["controls"]:
                txt = (row["text"] or "").replace("|", "\\|")[:40]
                md.append(
                    f"| {row['depth']} | `{row['class_name']}` | {row['control_id']} | "
                    f"{row['control_type']} | {row['class_hint']} | {txt} | {row.get('image_rect')} |"
                )
        md.append("")
    (outdir / "summary.md").write_text("\n".join(md), encoding="utf-8")

    for backend, entry in report["backends"].items():
        if entry["error"]:
            print(f"{backend}: FAILED - {entry['error']}")
            continue
        total = sum(len(w["controls"]) for w in entry["windows"])
        counts: dict = {}
        for w in entry["windows"]:
            for row in w["controls"]:
                counts[row["class_hint"]] = counts.get(row["class_hint"], 0) + 1
        print(f"{backend}: {len(entry['windows'])} windows, {total} deduped visible controls, hints {counts}")
    for cap in captures.values():
        print(f"capture: {cap['file']} origin={cap['origin']} printwindow_ok={cap['printwindow_ok']}")
    print(f"wrote {outdir}/windows.json, {outdir}/controls.csv, {outdir}/summary.md")
    print("next: read the labels off the capture and bind them to ids by geometry "
          "(references/control-id-mapping.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
