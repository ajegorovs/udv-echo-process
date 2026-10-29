"""Keep the operator's pointer usable while this application's popups try to trap it.

The application confines the cursor to its dialog's rectangle with ``ClipCursor`` while a popup is open. A clip is not
window-scoped: it applies to the whole desktop, so an operator working in front of the application finds their pointer
trapped inside a dialog they cannot even see. Measured on this application: the clip is set to the store dialog's own
rect, and ``ClipCursor(NULL)`` from a process that is *not* in the foreground releases it, after which the application
does not re-apply it.

Two things therefore belong together, and both were measured together: release the clip, and put the pointer back where
the operator left it, because opening a modal also re-centres the cursor on this application (measured: the pointer moved
from the corner to the dialog's centre at the moment it appeared).

The surface is injected rather than reached for, so the behaviour is testable without a desktop.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol, Self

#: How often the guard looks for a clip while it is active. The clip exists for at most this long before release, so a
#: shorter interval means a shorter trap; it is not free, hence a default rather than "as fast as possible".
POLL_S = 0.05


class PointerSurface(Protocol):
    """The five desktop facts this module needs, so a test can supply them."""

    def clip(self) -> tuple[int, int, int, int] | None: ...

    def release_clip(self) -> bool: ...

    def cursor(self) -> tuple[int, int]: ...

    def move_cursor(self, x: int, y: int) -> bool: ...

    def screen(self) -> tuple[int, int]: ...


@dataclass
class PointerReport:
    """What the guard saw and did — the evidence a caller reports instead of claiming the pointer stayed free."""

    cursor_start: tuple[int, int] | None = None
    cursor_restored: tuple[int, int] | None = None
    detections: int = 0
    releases: int = 0
    release_failures: int = 0
    clips_seen: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def pointer_was_free_of_clips(self) -> bool:
        return self.detections == 0

    @property
    def every_clip_was_released(self) -> bool:
        return self.detections == 0 or self.releases >= self.detections


class Win32Pointer:
    """The real surface: user32 reached lazily, so importing this module off Windows stays safe."""

    def __init__(self) -> None:
        import ctypes

        self._ctypes = ctypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    def clip(self) -> tuple[int, int, int, int] | None:
        rect = self._ctypes.wintypes.RECT()
        if not self._user32.GetClipCursor(self._ctypes.byref(rect)):
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)

    def release_clip(self) -> bool:
        return bool(self._user32.ClipCursor(None))

    def cursor(self) -> tuple[int, int]:
        point = self._ctypes.wintypes.POINT()
        self._user32.GetCursorPos(self._ctypes.byref(point))
        return (point.x, point.y)

    def move_cursor(self, x: int, y: int) -> bool:
        return bool(self._user32.SetCursorPos(int(x), int(y)))

    def screen(self) -> tuple[int, int]:
        return (self._user32.GetSystemMetrics(0), self._user32.GetSystemMetrics(1))


class FreePointer:
    """A context manager that frees the pointer for the duration of a popup, and restores it afterwards.

    ``with FreePointer() as guard:`` … and after the block ``guard.report`` says whether a clip was seen, whether each one
    was released, and where the cursor was put back. A clip that reappears is released again, because the application
    decides when to re-apply it and this cannot assume one release is enough.
    """

    def __init__(self, surface: PointerSurface | None = None, poll_s: float = POLL_S) -> None:
        self._surface = surface
        self._poll_s = poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.report = PointerReport()

    def _resolve(self) -> PointerSurface:
        if self._surface is None:
            self._surface = Win32Pointer()
        return self._surface

    def _loop(self) -> None:
        surface = self._resolve()
        while not self._stop.is_set():
            try:
                current = surface.clip()
                screen = surface.screen()
            except Exception:  # noqa: BLE001 - a surface that cannot answer must not kill the guard
                return
            clipped = current is not None and tuple(current) != (0, 0, screen[0], screen[1])
            if clipped:
                self.report.detections += 1
                if current not in self.report.clips_seen and len(self.report.clips_seen) < 8:
                    self.report.clips_seen.append(tuple(current))
                try:
                    if surface.release_clip():
                        self.report.releases += 1
                except Exception:  # noqa: BLE001 - a surface that refuses is reported by the counts, not raised
                    self.report.release_failures += 1
            self._stop.wait(self._poll_s)

    def __enter__(self) -> Self:
        surface = self._resolve()
        self.report.cursor_start = surface.cursor()
        self._thread = threading.Thread(target=self._loop, name="free-pointer", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        surface = self._resolve()
        if self.report.cursor_start is not None:
            surface.move_cursor(*self.report.cursor_start)
            self.report.cursor_restored = surface.cursor()
