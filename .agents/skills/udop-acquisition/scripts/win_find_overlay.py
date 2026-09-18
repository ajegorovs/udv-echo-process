#!/usr/bin/env python3
"""List the child panels of a target window topmost-first and flag any overlay covering it.

Why this exists: a posted WM_LBUTTONDOWN/WM_LBUTTONUP reaches the window it names even when a modal
panel covers it, so a driver keeps pressing widgets the operator cannot see. A warning that goes
unanswered also *hides* part of the surface, so the next press lands on something the map did not
intend. Check for an overlay before every press sequence.

How it decides: walk the main window's children in z-order (GW_CHILD is the top of the z-order, then
GW_HWNDNEXT downwards). Skip panels whose position the caller declares as known (`--skip x,y`, one
per mapped cluster). Among the rest, the first panel that (a) does not span nearly the whole window
and (b) owns at least one button in its own bottom strip is the overlay candidate.

    python win_find_overlay.py --class-name TMain_Scr --skip 0,23 --skip 0,55 --skip 448,477 \
        --skip 0,1016
    python win_find_overlay.py --hwnd 0x1a2b3c --press        # answer its safe (left) button

Exit codes: 0 overlay found (pressed if --press), 3 nothing found, 1 cannot resolve the target.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

# Declare the signatures once: without this the default prototypes take 32-bit ints and a 64-bit
# buffer address raises `OverflowError: int too long to convert` (or truncates silently).
SM_FLAGS = 0x0002  # SMTO_ABORTIFHUNG
for _fn, _args, _ret in (
    (u32.SendMessageTimeoutW, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t,
                               ctypes.c_uint, ctypes.c_uint,
                               ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
    (u32.SendMessageW, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t],
     ctypes.c_ssize_t),
    (u32.GetWindow, [ctypes.c_void_p, ctypes.c_uint], ctypes.c_void_p),
    (u32.GetWindowRect, [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)], ctypes.c_int),
    (u32.GetClientRect, [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)], ctypes.c_int),
    (u32.GetDlgCtrlID, [ctypes.c_void_p], ctypes.c_int),
    (u32.IsWindowVisible, [ctypes.c_void_p], ctypes.c_int),
    (u32.IsWindowEnabled, [ctypes.c_void_p], ctypes.c_int),
):
    _fn.argtypes = _args
    _fn.restype = _ret

GW_CHILD, GW_HWNDNEXT = 5, 2
WM_GETTEXT = 0x000D
WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0201, 0x0202, 0x0001
HOLD_S = 0.18   # an instant down/up is discarded by custom widget layers


def rect_of(hwnd: int):
    rc = wintypes.RECT()
    u32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
    return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)


def text_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u32.SendMessageTimeoutW(ctypes.c_void_p(hwnd), WM_GETTEXT, 256, ctypes.addressof(buf),
                            SM_FLAGS, 1500, ctypes.byref(ctypes.c_size_t(0)))
    return buf.value


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def children(hwnd: int):
    out, ch = [], u32.GetWindow(ctypes.c_void_p(hwnd), GW_CHILD)
    while ch:
        out.append(ch)
        ch = u32.GetWindow(ctypes.c_void_p(ch), GW_HWNDNEXT)
    return out


def click_hold(hwnd: int, hold: float = HOLD_S) -> None:
    _l, _t, w, h = rect_of(hwnd)
    lp = ((h // 2) << 16) | (w // 2)   # client-relative coordinates of the centre
    u32.PostMessageW(ctypes.c_void_p(hwnd), WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(hold)
    u32.PostMessageW(ctypes.c_void_p(hwnd), WM_LBUTTONUP, 0, lp)


def find_by_class(class_name: str):
    """Largest visible top-level window of `class_name` (visible beats large, per the attach rules)."""
    hits = []

    def cb(hwnd, _):
        if u32.IsWindowVisible(ctypes.c_void_p(hwnd)) and class_of(hwnd) == class_name:
            r = rect_of(hwnd)
            hits.append((r[2] * r[3], hwnd, r))

    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(cb), None)
    if not hits:
        return None, None
    hits.sort(reverse=True)
    return hits[0][1], hits[0][2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class-name", help="top-level window class to target (e.g. TMain_Scr)")
    ap.add_argument("--hwnd", help="target window handle, decimal or 0x-hex (instead of --class-name)")
    ap.add_argument("--skip", action="append", default=[], metavar="X,Y",
                    help="window position of a known panel to ignore; repeatable")
    ap.add_argument("--button-class", default="Button",
                    help="substring of the button class name (default: 'Button', matches TSp_Button)")
    ap.add_argument("--press", action="store_true",
                    help="press the candidate overlay's leftmost bottom button with the held-click recipe")
    args = ap.parse_args()

    if args.hwnd:
        hwnd = int(args.hwnd, 0)
        r = rect_of(hwnd)
    elif args.class_name:
        hwnd, r = find_by_class(args.class_name)
    else:
        ap.error("give --class-name or --hwnd")
    if not hwnd:
        print(f"no visible window of class {args.class_name!r}", file=sys.stderr)
        return 1

    skip = set()
    for s in args.skip:
        x, _, y = s.partition(",")
        skip.add((int(x), int(y)))

    cr = wintypes.RECT()
    u32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(cr))
    print(f"target hwnd={hwnd:#x} class={class_of(hwnd)!r} window_rect={r} "
          f"client={cr.right - cr.left}x{cr.bottom - cr.top}")
    print(f"skipping {sorted(skip) or '-'}\n")

    for h in children(hwnd):
        rc = rect_of(h)
        if rc[2] * rc[3] < 20000:            # labels, separators, decoration
            continue
        kids = children(h)
        key = (rc[0], rc[1])
        known = key in skip
        label = "known" if known else "CANDIDATE"
        print(f"[{label}] panel ({rc[0]},{rc[1]}) {rc[2]}x{rc[3]} hwnd={h:#x} children={len(kids)}")
        for k in sorted(kids, key=lambda k: rect_of(k)[1]):
            kr = rect_of(k)
            print(f"      {class_of(k):<20} ({kr[0]},{kr[1]}) {kr[2]}x{kr[3]} "
                  f"enabled={bool(u32.IsWindowEnabled(ctypes.c_void_p(k)))}"
                  f" text={text_of(k)!r}")
        if known:
            continue
        spans_window = rc[2] > 0.95 * r[2]
        btns = sorted([k for k in kids
                       if args.button_class.lower() in class_of(k).lower()
                       and rect_of(k)[1] > rc[1] + rc[3] - 70], key=lambda k: rect_of(k)[0])
        if spans_window or not btns:
            print("      (not an overlay: spans the window or has no bottom buttons)\n")
            continue
        print(f"      -> OVERLAY. bottom buttons (left to right): "
              f"{[(rect_of(k)[0], rect_of(k)[2]) for k in btns]}")
        print(f"      -> safe choice = leftmost, hwnd={btns[0]:#x}")
        print("      -> answer it before pressing anything else on the surface underneath")
        if args.press:
            click_hold(btns[0])
            time.sleep(1.0)
            print("      pressed; re-resolve the map before continuing")
        return 0

    print("no overlay found: nothing is covering the target's own panels")
    return 3


if __name__ == "__main__":
    sys.exit(main())
