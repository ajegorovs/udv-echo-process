"""Measure a numeric field's accepted values on a running Windows app, then restore it.

Companion to win_control_io.py: that one reads/writes a control whose domain you know; this one
*measures* the domain. It writes a ladder of targets into one control, reads each one back, and
reports what the application actually accepted (snapping, clamping, refusals). Every field it
touches — including the ones held with --hold — is restored at the end.

Controls are found by control id among the visible, handle-deduplicated descendants of the app's
main window, because owner-drawn toolkits repeat ids across hidden pages and return empty
captions for buttons. Values are written with WM_SETTEXT plus a posted VK_RETURN, so the app need
not be focused and the user's own typing is never disturbed.

Usage:
  python win_param_scan.py --process App.exe --id 134530 --read
  python win_param_scan.py --process App.exe --id 134530 --scan 0.05 20 0.01
  python win_param_scan.py --process App.exe --id 200058 --scan 1 1200 1 --hold 134530=0.125
  python win_param_scan.py --process App.exe --id 134530 --class TSp_Edit --window-class TMain_Scr

Requires: pywinauto, pywin32 (pip install pywinauto pywin32)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import win32con
import win32gui
from pywinauto import Application


def main_window(app, class_name: str | None):
    if class_name:
        return app.window(class_name=class_name)
    for w in app.windows():
        try:
            if w.is_visible() and w.window_text():
                return w
        except Exception:
            continue
    raise SystemExit("no visible top-level window found; pass --window-class")


def find_ctrl(app, win, control_id: int, class_name: str | None = None):
    """First VISIBLE control with this id. Hidden pages reuse ids, so visibility is the match."""
    for ctrl in win.descendants():
        try:
            if ctrl.element_info.control_id != control_id:
                continue
            if class_name and ctrl.element_info.class_name != class_name:
                continue
            r = ctrl.rectangle()
            if r.right > r.left and ctrl.is_visible():
                return ctrl
        except Exception:
            continue
    return None


def read(ctrl) -> str:
    try:
        return ctrl.window_text().strip()
    except Exception:
        return ""


def write(ctrl, value: str, settle: float) -> None:
    win32gui.SendMessage(ctrl.handle, win32con.WM_SETTEXT, 0, value)
    win32gui.SendMessage(ctrl.handle, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
    win32gui.SendMessage(ctrl.handle, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
    time.sleep(settle)


def ladder(start: float, stop: float, step: float) -> list[float]:
    out, v, n = [], start, 0
    while v <= stop + 1e-9 and n < 5000:
        out.append(round(v, 6))
        n += 1
        v = start + n * step
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", required=True)
    ap.add_argument("--id", type=int, required=True, help="control id of the field to scan")
    ap.add_argument("--class", dest="ctrl_class", default=None, help="expected control class")
    ap.add_argument("--window-class", default=None, help="main window class (default: first visible)")
    ap.add_argument("--scan", nargs=3, type=float, metavar=("START", "STOP", "STEP"))
    ap.add_argument("--hold", action="append", default=[], metavar="ID=VALUE",
                    help="field to pin at a known value while scanning (repeatable)")
    ap.add_argument("--read", action="store_true", help="just report the current values")
    ap.add_argument("--settle", type=float, default=0.2, help="seconds to wait after a write")
    ap.add_argument("--out", default=".", help="directory for the JSON record")
    args = ap.parse_args()

    app = Application(backend="win32").connect(path=args.process, timeout=10)
    win = main_window(app, args.window_class)
    target = find_ctrl(app, win, args.id, args.ctrl_class)
    if target is None:
        print(f"control id {args.id} not found among visible controls of {win.window_text()!r}")
        return 1

    holds = []
    for spec in args.hold:
        cid, _, val = spec.partition("=")
        ctrl = find_ctrl(app, win, int(cid), args.ctrl_class)
        if ctrl is None:
            print(f"--hold control {cid} not found")
            return 1
        holds.append((int(cid), ctrl, read(ctrl), val))

    original = read(target)
    print(f"target: id={args.id} class={target.element_info.class_name} "
          f"current={original!r}")
    for cid, ctrl, before, val in holds:
        print(f"held  : id={cid} {before!r} -> {val!r}")
        write(ctrl, val, args.settle)

    if args.read and not args.scan:
        return 0

    rows: list[dict] = []
    print(f"\n{'target':>10}  {'accepted':>10}  neighbours")
    print("-" * 44)
    for t in ladder(*args.scan):
        write(target, f"{t:g}", args.settle)
        accepted = read(target)
        neighbours = ", ".join(f"{cid}={read(c)}" for cid, c, _, _ in holds)
        rows.append({"target": t, "accepted": accepted, "neighbours": neighbours})
        print(f"{t:>10}  {accepted:>10}  {neighbours}")

    accepted_set: list[str] = []
    for r in rows:
        if r["accepted"] and r["accepted"] not in accepted_set:
            accepted_set.append(r["accepted"])

    def as_float(s: str):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    rungs = sorted(v for v in (as_float(a) for a in accepted_set) if v is not None)
    midpoints = [round((a + b) / 2, 6) for a, b in zip(rungs, rungs[1:])]
    print(f"\ndistinct accepted ({len(rungs)}): {', '.join(str(v) for v in rungs)}")
    print(f"transition midpoints      : {', '.join(str(v) for v in midpoints)}")

    # restore, held fields last so the target's own restore is not perturbed
    write(target, original, args.settle)
    for cid, ctrl, before, _ in holds:
        write(ctrl, before, args.settle)
    print(f"\nrestored: id={args.id} {read(target)!r}" +
          " | " + ", ".join(f"{cid}={read(c)!r}" for cid, c, _, _ in holds))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"param-scan-{args.id}-{stamp}.json"
    out.write_text(json.dumps({
        "stamp": stamp,
        "process": args.process,
        "control_id": args.id,
        "original": original,
        "held": [{"control_id": cid, "before": before, "pinned": val}
                 for cid, _, before, val in holds],
        "rows": rows,
        "accepted": rungs,
        "transition_midpoints": midpoints,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
