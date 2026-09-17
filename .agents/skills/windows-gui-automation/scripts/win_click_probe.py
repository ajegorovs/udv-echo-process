"""Which click recipe does this control actually accept?

A synthetic click can be ignored for reasons that have nothing to do with the target being
unreachable: the press was not held long enough, `lParam` was in the wrong coordinate space, the
cursor never moved onto the control, or the first click went to activating the window. This probe
varies the *recipe* while holding the target fixed, and reports which one the application reacts to.

Run it before writing a control off as "not drivable by software" - and before escalating to
real input injection.

    # a window by class (pick the visible, largest one); --child N indexes its visible children
    python win_click_probe.py --class TMain_Scr --child 3

    # or by handle
    python win_click_probe.py --hwnd 0x40910 --hold 200

    # useful flags
    --all             try every recipe even after one works
    --no-injected     skip recipes that move the real pointer (safe while a user works)
    --capture-self    hash the control's own pixels instead of its parent's
    --wait 1.5        seconds to wait for the app to react before declaring no change

The change detector is a hash of the parent window's rendered pixels (plus the control's text),
which needs no knowledge of the application. Exit codes: 0 = some recipe worked, 2 = none did,
1 = usage/resolution error. If exit code 2 comes with `enabled=False` or a hit-test that is not the
control itself, the target is not reachable for a mundane reason - fix that first.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import sys
import time
from ctypes import wintypes

u32 = ctypes.windll.user32
gdi = ctypes.windll.gdi32

# Every handle is 64-bit: declare the signatures once, or pointer arguments truncate.
u32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
u32.GetWindow.restype = ctypes.c_void_p
u32.GetParent.argtypes = [ctypes.c_void_p]
u32.GetParent.restype = ctypes.c_void_p
u32.GetDesktopWindow.restype = ctypes.c_void_p
u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
u32.GetWindowDC.argtypes = [ctypes.c_void_p]
u32.GetWindowDC.restype = ctypes.c_void_p
u32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
u32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
u32.WindowFromPoint.restype = ctypes.c_void_p
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.SendMessageTimeoutW.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t,
    ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
u32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi.CreateCompatibleDC.restype = ctypes.c_void_p
gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi.SelectObject.restype = ctypes.c_void_p
gdi.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
gdi.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
gdi.DeleteObject.argtypes = [ctypes.c_void_p]
gdi.DeleteDC.argtypes = [ctypes.c_void_p]

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_COMMAND, WM_GETTEXT, BM_CLICK, MK_LBUTTON = 0x0111, 0x000D, 0x00F5, 0x0001
GW_CHILD, GW_HWNDNEXT, SRCCOPY, PW_RENDERFULLCONTENT = 5, 2, 0x00CC0020, 0x2
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint),
                ("biSizeImage", ctypes.c_uint), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.c_uint),
                ("biClrImportant", ctypes.c_uint)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def rect_of(hwnd):
    rc = wintypes.RECT()
    u32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rc))
    return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top


def text_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u32.SendMessageTimeoutW(ctypes.c_void_p(hwnd), WM_GETTEXT, 256, ctypes.addressof(buf), 2,
                            1500, ctypes.byref(ctypes.c_size_t(0)))
    return buf.value


def class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def fingerprint(hwnd):
    """md5 of the window's own rendered pixels plus its text - an app-agnostic change detector."""
    _l, _t, w, h = rect_of(hwnd)
    if w <= 0 or h <= 0:
        return "empty"
    hdc = u32.GetWindowDC(ctypes.c_void_p(hwnd))
    memdc = gdi.CreateCompatibleDC(ctypes.c_void_p(hdc))
    bmp = gdi.CreateCompatibleBitmap(ctypes.c_void_p(hdc), w, h)
    gdi.SelectObject(ctypes.c_void_p(memdc), ctypes.c_void_p(bmp))
    ok = u32.PrintWindow(ctypes.c_void_p(hwnd), ctypes.c_void_p(memdc), PW_RENDERFULLCONTENT)
    if not ok:
        gdi.BitBlt(ctypes.c_void_p(memdc), 0, 0, w, h, ctypes.c_void_p(hdc), 0, 0, SRCCOPY)
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = w
    header.biHeight = -h          # top-down
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    # BITMAPINFO is the header followed by (unused, 32-bit) colour entries.
    bi_storage = ctypes.create_string_buffer(ctypes.sizeof(BITMAPINFOHEADER) + 12)
    ctypes.memmove(bi_storage, ctypes.byref(header), ctypes.sizeof(BITMAPINFOHEADER))
    gdi.GetDIBits(ctypes.c_void_p(memdc), ctypes.c_void_p(bmp), 0, h, buf,
                  ctypes.byref(bi_storage), 0)
    raw = buf.raw
    gdi.DeleteObject(ctypes.c_void_p(bmp))
    gdi.DeleteDC(ctypes.c_void_p(memdc))
    u32.ReleaseDC(ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc))
    black = raw.count(b"\x00") / max(len(raw), 1)
    return f"{hashlib.md5(raw).hexdigest()[:12]} text={text_of(hwnd)!r} black={black:.2f}"


def post(hwnd, msg, wp=0, lp=0):
    return bool(u32.PostMessageW(ctypes.c_void_p(hwnd), msg, wp, lp))


def sendinput_mouse(flags, x=0, y=0):
    sw, sh = u32.GetSystemMetrics(0), u32.GetSystemMetrics(1)
    inp = INPUT()
    inp.type = 0
    inp.mi = MOUSEINPUT(dx=int(x * 65535 / max(sw - 1, 1)), dy=int(y * 65535 / max(sh - 1, 1)),
                        mouseData=0, dwFlags=flags | (MOUSEEVENTF_ABSOLUTE if (x or y) else 0),
                        time=0, dwExtraInfo=None)
    u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def make_recipes(hold_ms, injected):
    hold = hold_ms / 1000.0

    def lp_for(btn, client=True):
        _l, _t, w, h = rect_of(btn)
        if client:
            return ((h // 2) << 16) | (w // 2)
        cx, cy = _l + w // 2, _t + h // 2
        return ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)

    out = []

    def posted_instant(btn, parent):
        lp = lp_for(btn)
        post(btn, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        post(btn, WM_LBUTTONUP, 0, lp)

    def posted_hold(btn, parent):
        lp = lp_for(btn)
        post(btn, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(hold)
        post(btn, WM_LBUTTONUP, 0, lp)

    def posted_move_hold(btn, parent):
        lp = lp_for(btn)
        post(btn, WM_MOUSEMOVE, 0, lp)
        time.sleep(0.25)
        post(btn, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(hold)
        post(btn, WM_LBUTTONUP, 0, lp)

    def screen_coords_hold(btn, parent):
        lp = lp_for(btn, client=False)
        post(btn, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(hold)
        post(btn, WM_LBUTTONUP, 0, lp)

    def cursor_parked_posted(btn, parent):
        l, t, w, h = rect_of(btn)
        u32.SetCursorPos(l + w // 2, t + h // 2)
        time.sleep(0.25)
        posted_move_hold(btn, parent)

    def real_click(btn, parent):
        l, t, w, h = rect_of(btn)
        u32.SetCursorPos(l + w // 2, t + h // 2)
        time.sleep(0.2)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(hold)
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def real_click_move_hold(btn, parent):
        l, t, w, h = rect_of(btn)
        cx, cy = l + w // 2, t + h // 2
        u32.SetCursorPos(cx - 40, cy)
        time.sleep(0.15)
        u32.SetCursorPos(cx, cy)
        time.sleep(0.35)
        u32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(max(hold, 0.2))
        u32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def sendinput_click(btn, parent):
        l, t, w, h = rect_of(btn)
        cx, cy = l + w // 2, t + h // 2
        sendinput_mouse(MOUSEEVENTF_MOVE, cx - 30, cy)
        time.sleep(0.15)
        sendinput_mouse(MOUSEEVENTF_MOVE, cx, cy)
        time.sleep(0.35)
        sendinput_mouse(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_MOVE, cx, cy)
        time.sleep(max(hold, 0.2))
        sendinput_mouse(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_MOVE, cx, cy)

    def bm_click(btn, parent):
        u32.SendMessageTimeoutW(ctypes.c_void_p(btn), BM_CLICK, 0, 0, 2, 2000,
                                ctypes.byref(ctypes.c_size_t(0)))

    def wm_command_parent(btn, parent):
        cid = u32.GetDlgCtrlID(ctypes.c_void_p(btn))
        cid = ctypes.c_short(cid).value if cid > 32767 else cid
        post(parent, WM_COMMAND, cid & 0xFFFF, btn)

    out.append(("posted_instant (the naive baseline)", posted_instant))
    out.append((f"posted_held {hold_ms:.0f} ms", posted_hold))
    out.append(("posted move-first then held", posted_move_hold))
    out.append(("posted with SCREEN coords, held", screen_coords_hold))
    if injected:
        out.append(("cursor parked, then posted, held", cursor_parked_posted))
        out.append(("injected real click, held", real_click))
        out.append(("injected move-in then click, held", real_click_move_hold))
        out.append(("SendInput absolute move + click", sendinput_click))
    out.append(("BM_CLICK", bm_click))
    out.append(("WM_COMMAND to the parent", wm_command_parent))
    return out


def find_window(class_name):
    """The visible, largest top-level window of this class."""
    hits = []

    def cb(hwnd, _):
        if class_name and class_of(hwnd) != class_name:
            return
        l, t, w, h = rect_of(hwnd)
        hits.append((bool(u32.IsWindowVisible(ctypes.c_void_p(hwnd)), w * h, hwnd, (l, t, w, h)))

    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), None)
    if not hits:
        return None
    hits.sort(key=lambda x: (not x[0], -x[1]))
    return hits[0][2]


def visible_children(hwnd):
    out, ch = [], u32.GetWindow(ctypes.c_void_p(hwnd), GW_CHILD)
    while ch:
        l, t, w, h = rect_of(ch)
        if u32.IsWindowVisible(ctypes.c_void_p(ch)) and w > 0 and h > 0:
            out.append(ch)
        ch = u32.GetWindow(ctypes.c_void_p(ch), GW_HWNDNEXT)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Find which click recipe a control accepts.")
    ap.add_argument("--hwnd", help="target control handle, hex or decimal")
    ap.add_argument("--class", dest="cls", help="window class to find the target in")
    ap.add_argument("--child", type=int, default=None, help="index among the window's visible children")
    ap.add_argument("--hold", type=int, default=180, help="press duration in ms (default 180)")
    ap.add_argument("--wait", type=float, default=1.5, help="seconds to wait for a reaction")
    ap.add_argument("--all", action="store_true", help="keep going after a recipe works")
    ap.add_argument("--no-injected", action="store_true", help="skip recipes that move the pointer")
    ap.add_argument("--capture-self", action="store_true", help="hash the control, not its parent")
    a = ap.parse_args()

    if a.hwnd:
        target = int(a.hwnd, 0)
    elif a.cls:
        win = find_window(a.cls)
        if not win:
            print(f"no window of class {a.cls!r} found")
            return 1
        if a.child is None:
            print(f"window {a.cls} hwnd={win:#x}; pass --child N (visible children follow)")
            for i, ch in enumerate(visible_children(win)):
                print(f"   [{i}] {class_of(ch):<20} {rect_of(ch)} text={text_of(ch)!r}")
            return 1
        kids = visible_children(win)
        if a.child >= len(kids):
            print(f"--child {a.child} out of range ({len(kids)} visible children)")
            return 1
        target = kids[a.child]
    else:
        ap.print_help()
        return 1

    parent = u32.GetParent(ctypes.c_void_p(target)) or u32.GetDesktopWindow()
    watch = target if a.capture_self else parent
    l, t, w, h = rect_of(target)
    covered = u32.WindowFromPoint(wintypes.POINT(l + w // 2, t + h // 2))
    print(f"target  {class_of(target)} hwnd={target:#x} rect={(l, t, w, h)} text={text_of(target)!r}")
    print(f"        enabled={bool(u32.IsWindowEnabled(ctypes.c_void_p(target)))} "
          f"WS_DISABLED={bool(u32.GetWindowLongW(ctypes.c_void_p(target), -16) & 0x08000000)} "
          f"visible={bool(u32.IsWindowVisible(ctypes.c_void_p(target)))}")
    print(f"        hit-test at centre -> {class_of(covered)} hwnd={covered:#x} "
          f"({'the control itself' if covered == target else 'SOMETHING ELSE IS ON TOP'})")
    print(f"watching {class_of(watch)} hwnd={watch:#x} for changes\n")

    baseline = fingerprint(watch)
    print(f"baseline: {baseline}\n")
    if "black=1.00" in baseline or "black=0.99" in baseline:
        print("WARNING: the watched window captured as (near) pure black - it is probably not yet "
              "realised or visible, or renders nothing through PrintWindow. Every 'no change' below "
              "is then meaningless: wait for visibility, or watch a different window.\n")
    winner = None
    for name, fn in make_recipes(a.hold, not a.no_injected):
        before = fingerprint(watch)
        try:
            fn(target, parent)
        except Exception as exc:
            print(f"  {name:<34} raised {type(exc).__name__}: {exc}")
            continue
        time.sleep(a.wait)
        after = fingerprint(watch)
        changed = after != before
        print(f"  {name:<34} {'CHANGED' if changed else 'no change'}")
        if changed:
            winner = name
            if not a.all:
                break
    print()
    if winner:
        print(f"Recipe that works: {winner}")
        print("Use it, with client-relative lParam, and verify against an observable - not the control's "
              "own text.")
        return 0
    print("No recipe changed the watched window. Check the hit-test line above first: a disabled "
          "control or one covered by another window will ignore everything. If both are clean, the "
          "app may key off state you have not reached yet - capture the surrounding states before "
          "redesigning.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
