#!/usr/bin/env python3
"""Which process owns the window you intend to drive?

The failure this prevents
------------------------
Several processes can run from one executable path - a launcher stub, a second instance, or a
leftover owning **zero** windows. `Application(backend="win32").connect(path="App.exe")` selects
by executable path and can bind to the windowless one; every later `window(class_name=...)` then
raises `ElementNotFoundError`, which is indistinguishable from "the app is not running" or "the
app hung on startup". Measured: two processes from one exe, one owning 45 windows and one owning
none.

This script enumerates windows and processes directly (no `pywinauto` import), so it also works
during a **cold start**, when the main window does not exist yet or exists hidden behind a startup
dialog - the case where every class-name lookup fails by design.

Usage
-----
    python win_attach.py --class TMain_Scr                 # every window of that class
    python win_attach.py --process MyApp.exe               # every window that process owns
    python win_attach.py --process MyApp.exe --class TMain_Scr --wait 30
    python win_attach.py --pid 12345 --all                 # one pid, all classes, incl. hidden
    python win_attach.py --class TMain_Scr --json

Exit codes: 0 = at least one candidate, 3 = none found (useful as a pre-flight gate).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
import ctypes.wintypes as wintypes

import win32gui
import win32process

PSAPI = ctypes.WinDLL("psapi")
K32 = ctypes.WinDLL("kernel32")
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def list_processes() -> list[tuple[int, str]]:
    """(pid, exe basename) for every process we can query."""
    buf = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    PSAPI.EnumProcesses(ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(needed))
    out: list[tuple[int, str]] = []
    for i in range(needed.value // ctypes.sizeof(wintypes.DWORD)):
        pid = buf[i]
        if not pid:
            continue
        out.append((pid, exe_of(pid)))
    return out


def exe_of(pid: int) -> str:
    handle = K32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return "?"
    try:
        name = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if PSAPI.GetModuleFileNameExW(handle, None, name, ctypes.byref(size)):
            return name.value.rsplit("\\", 1)[-1]
        return "?"
    finally:
        K32.CloseHandle(handle)


def windows_of_pid(pid: int, class_filter: str | None = None) -> list[dict]:
    found: list[dict] = []

    def cb(hwnd, _):
        try:
            owner, _tid = win32process.GetWindowThreadProcessId(hwnd)
            if owner != pid:
                return True
            cls = win32gui.GetClassName(hwnd)
            if class_filter and cls != class_filter:
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            found.append({
                "pid": pid,
                "exe": exe_of(pid),
                "hwnd": hwnd,
                "class": cls,
                "title": win32gui.GetWindowText(hwnd),
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "top_level": win32gui.GetParent(hwnd) == 0,
                "rect": [left, top, right, bottom],
                "area": max(0, right - left) * max(0, bottom - top),
            })
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return sorted(found, key=lambda x: (not x["visible"], -x["area"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--class", dest="cls", help="window class to look for (e.g. TMain_Scr)")
    ap.add_argument("--process", help="executable basename to restrict to (e.g. MyApp.exe)")
    ap.add_argument("--pid", type=int, help="list what this pid owns (use during cold start)")
    ap.add_argument("--all", action="store_true", help="include hidden windows (default: yes)")
    ap.add_argument("--visible-only", action="store_true", help="ignore hidden windows")
    ap.add_argument("--require-visible", action="store_true",
                    help="wait until a visible candidate exists (exit 3 otherwise)")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to wait for a candidate")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not (args.cls or args.process or args.pid):
        ap.error("give --class, --process or --pid")

    procs = list_processes()
    if args.process:
        wanted = args.process.lower()
        pids = [p for p, exe in procs if exe.lower() == wanted]
        if not pids:
            print(f"no running process named {args.process!r}", file=sys.stderr)
            print("note: a non-elevated enumeration cannot see processes it may not query; "
                  "run this from the same integrity level as the app.", file=sys.stderr)
            return 3
    elif args.pid:
        pids = [args.pid]
    else:
        pids = [p for p, _exe in procs]

    deadline = time.time() + args.wait
    cands: list[dict] = []
    while True:
        cands = [w for pid in pids for w in windows_of_pid(pid, args.cls)]
        if args.visible_only or args.require_visible:
            cands = [w for w in cands if w["visible"]]
        if cands or time.time() >= deadline:
            break
        time.sleep(0.5)

    if args.json:
        print(json.dumps(cands, indent=2))
        return 0 if cands else 3

    if not cands:
        print(f"no candidate window found (class={args.cls!r} process={args.process!r} "
              f"pid={args.pid!r}) after {args.wait}s", file=sys.stderr)
        # the cold-start diagnostic: show what the app DOES own before calling it dead
        for pid in pids[:4]:
            own = windows_of_pid(pid)
            print(f"\npid {pid} ({exe_of(pid)}) owns {len(own)} top-level windows:", file=sys.stderr)
            for win in own[:12]:
                flag = "visible" if win["visible"] else "HIDDEN "
                print(f"   {flag} {win['class']:<28} {win['title'][:40]!r} {win['rect']}",
                      file=sys.stderr)
            if not own:
                print("   (none - no UI yet, or a windowless leftover; see references/"
                      "app-lifecycle-and-state.md)", file=sys.stderr)
        return 3

    print(f"{len(cands)} candidate(s):")
    for i, win in enumerate(cands):
        mark = "<-- best" if i == 0 else ""
        flag = "visible" if win["visible"] else "HIDDEN "
        print(f"  {flag} pid {win['pid']:<7} hwnd {hex(win['hwnd']):>10}  "
              f"{win['class']:<24} {win['title'][:34]!r} {win['rect']} {mark}")
    best = cands[0]
    if not best["visible"]:
        print("\nWARNING: the best candidate is HIDDEN - during a cold start that is either the "
              "app on its startup dialog, or a stale instance. A hidden window renders black "
              "through PrintWindow and exposes nothing. Wait for visibility before driving.")
    if len(cands) > 1:
        print("\nNOTE: multiple candidates - bind to a specific hwnd/pid rather than re-finding "
              "by class name later, or you may drive a different instance than you validated.")
    print("\n# bind (pywinauto):")
    print("from pywinauto import Application")
    print(f"app = Application(backend='win32').connect(process={best['pid']})")
    print(f"win = app.window(handle={hex(best['hwnd'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
