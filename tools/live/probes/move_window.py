"""Move the application window, so the port's geometry assumptions can be tested here.

A second machine will not put UDOP's window where this one does, and some of the port's
predicates are stated in **screen** coordinates — the overlay panel is identified as "the
visible panel at ``left == 169``" (`driver._poll_parameters_overlay`, the reference's own
rule), and the popup entries are taken in screen-``top`` order. Those were true here; nothing
says they are true at another window position, at another resolution, or on the second
machine's install.

Measured first on this machine: the window is **maximized** (``(-8, -8, 1928, 1058)`` on a
1920x1080 screen), i.e. the frame *is* the screen — which is exactly why absolute screen
coordinates held. A windowed application is what the second machine is likely to be running,
so this probe un-maximizes before moving, and ``restore`` puts the window back maximized.

Window operations go through ``user32`` with ctypes rather than pywin32: this interpreter's
``win32gui`` has no ``IsZoomed``/``GetSystemMetrics``, and the driver's own cursor work is
ctypes anyway.

Nothing here posts input or touches the instrument; it moves a window and prints the rects.
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import win32gui

from udv_echo_process.acquire.driver import MAIN_CLASS

user32 = ctypes.windll.user32

SW_RESTORE = 9
SW_MAXIMIZE = 3
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FLAGS = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE

#: Where the window goes: far enough to break any absolute x, small enough to stay on screen.
OFFSET = (300, 120)


def find() -> int:
    found: list[int] = []

    def visit(hwnd: int, _param: object) -> bool:
        if win32gui.GetClassName(hwnd) == MAIN_CLASS and win32gui.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    if not found:
        raise SystemExit(f"no visible {MAIN_CLASS!r} window")
    return found[0]


def rect(hwnd: int) -> tuple[int, int, int, int]:
    value = ctypes.wintypes.RECT()  # type: ignore[attr-defined]
    user32.GetWindowRect(hwnd, ctypes.byref(value))
    return value.left, value.top, value.right, value.bottom


def zoomed(hwnd: int) -> bool:
    return bool(user32.IsZoomed(hwnd))


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "move"
    hwnd = find()
    print(f"window {hwnd} {MAIN_CLASS!r} at {rect(hwnd)}")
    screen = (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    print(f"screen {screen[0]}x{screen[1]}  maximized: {zoomed(hwnd)}")

    if action == "restore":
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        print(f"restored: {rect(hwnd)}  maximized: {zoomed(hwnd)}")
        return 0

    if zoomed(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.5)
        print(f"un-maximized to {rect(hwnd)}")

    left, top, _, _ = rect(hwnd)
    target = {
        "park": OFFSET,
    }.get(action, (left + OFFSET[0], top + OFFSET[1]))
    user32.SetWindowPos(hwnd, 0, target[0], target[1], 0, 0, SWP_FLAGS)
    time.sleep(0.3)
    print(f"moved to {rect(hwnd)}  maximized: {zoomed(hwnd)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
