#!/usr/bin/env python
"""Read and set control values by Win32 message, with restore. The write half of the probe.

Companion to `win_ui_probe.py` (read-only reconnaissance). Use this once a control map exists
and you need to prove that the app *accepts* a value you send it.

Read path: window text of a control addressed by control id, scoped to the visible top-level
window (ids repeat across hidden pages, so a blind id lookup returns the wrong widget).

Write path: `WM_SETTEXT` followed by a `VK_RETURN` key message to commit. This needs no focus,
no cursor movement and no keystrokes, so it works while the window is occluded, unfocused, or
the desktop is locked — and it is bitness-agnostic.

A successful write is NOT proof the app accepted the value: the text buffer can change while the
application keeps its own copy. Always pair a write with a *coupled observable* the app derives
from that parameter (a status readout, a derived count, a timestamp interval, the parameters in
the file it writes). See references/control-id-mapping.md section 5.

Usage:
  # read a set of ids
  python win_control_io.py --process MyApp.exe --class TMain_Scr --ids 134540 200058 331106

  # read everything a map file declares (parameters dict with control_id / class_name)
  python win_control_io.py --process MyApp.exe --class TMain_Scr --map control-map.json

  # set one field, read back, then put the original value back
  python win_control_io.py --process MyApp.exe --class TMain_Scr --id 134540 --set 200 --restore

Dependencies: pip install pywinauto pywin32
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import win32con
import win32gui
from pywinauto import Application


def find_control(app, window_spec: dict, control_id: int, class_name: str | None = None):
    """First visible, non-degenerate control with this id, deduplicated by handle.

    Owner-drawn toolkits report the same widget under several parents and reuse ids across
    hidden pages, so visibility + a real rectangle are part of the match, not a nicety.
    """
    try:
        root = app.window(**window_spec)
    except Exception:
        root = None

    candidates = []
    for ctrl in (root.descendants() if root is not None else []):
        try:
            if ctrl.element_info.control_id != control_id:
                continue
        except Exception:
            continue
        if class_name and getattr(ctrl.element_info, "class_name", None) != class_name:
            continue
        candidates.append(ctrl)

    seen: set[int] = set()
    fallback = None
    for ctrl in candidates:
        try:
            hwnd = ctrl.handle
        except Exception:
            continue
        if hwnd in seen:
            continue
        seen.add(hwnd)
        if fallback is None:
            fallback = ctrl
        try:
            rect = ctrl.rectangle()
            if rect.right > rect.left and ctrl.is_visible():
                return ctrl
        except Exception:
            continue
    return fallback


def read_value(ctrl) -> str | None:
    if ctrl is None:
        return None
    for getter in (lambda: win32gui.GetWindowText(ctrl.handle), lambda: ctrl.window_text()):
        try:
            return getter().strip()
        except Exception:
            continue
    return None


def write_value(ctrl, value: str, commit: bool = True) -> bool:
    """Set the text, then nudge the commit path an operator would trigger."""
    if ctrl is None:
        return False
    try:
        hwnd = ctrl.handle
    except Exception:
        return False
    win32gui.SendMessage(hwnd, win32con.WM_SETTEXT, 0, value)
    if commit:
        win32gui.SendMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
        win32gui.SendMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        time.sleep(0.3)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="read/set a control by Win32 message",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--process", help="executable name or path")
    ap.add_argument("--pid", type=int, help="process id (alternative to --process)")
    ap.add_argument("--class", dest="cls", help="top-level window class holding the controls")
    ap.add_argument("--title", help="top-level window title (alternative to --class)")
    ap.add_argument("--ids", type=int, nargs="*", default=[], help="control ids to read")
    ap.add_argument("--map", help="control-map.json to read ids/names from")
    ap.add_argument("--id", type=int, help="control id to write")
    ap.add_argument("--set", dest="value", help="value to write")
    ap.add_argument("--control-class", help="restrict the match to this widget class")
    ap.add_argument("--restore", action="store_true", help="put the previous value back after writing")
    args = ap.parse_args()
    if not args.process and not args.pid:
        ap.error("give --process or --pid")
    if not args.cls and not args.title:
        ap.error("give --class (or --title) so the lookup is scoped to the right window")
    if args.value is not None and args.id is None:
        ap.error("--set needs --id")

    target = {"process": args.pid} if args.pid else {"path": args.process}
    window_spec = {"class_name": args.cls} if args.cls else {"title": args.title}
    app = Application(backend="win32").connect(timeout=10, **target)

    named: list[tuple[str, int, str | None]] = []
    if args.map:
        cmap = json.loads(Path(args.map).read_text(encoding="utf-8"))
        for name, spec in (cmap.get("parameters") or {}).items():
            named.append((name, spec["control_id"], spec.get("class_name")))
    named += [(f"id {i}", i, None) for i in args.ids]

    for name, cid, cls in named:
        ctrl = find_control(app, window_spec, cid, cls or args.control_class)
        print(f"{name:<28} id={cid:<9} = {read_value(ctrl)!r}")

    if args.id is not None and args.value is not None:
        ctrl = find_control(app, window_spec, args.id, args.control_class)
        if ctrl is None:
            print(f"no visible control with id {args.id} in {window_spec}")
            return 1
        before = read_value(ctrl)
        print(f"\nwriting id={args.id}: {before!r} -> {args.value!r}")
        sent = write_value(ctrl, args.value)
        after = read_value(ctrl)
        print(f"  message sent={sent}  read back={after!r}")
        if after != args.value:
            print("  the widget did not even take the text: try the click / focus rungs of the "
                  "escalation ladder (references/control-id-mapping.md section 4)")
        else:
            print("  text accepted - NOT yet proof the app applied it. Check a coupled "
                  "observable (a derived readout or the artifact this run writes) before "
                  "believing this point.")
        if args.restore and before is not None:
            write_value(ctrl, before)
            print(f"  restored -> {read_value(ctrl)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
