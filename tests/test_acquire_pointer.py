"""The pointer guard: release the application's clip, restore the operator's cursor.

Both behaviours were measured against the live application before they were written down here: a store dialog sets
`ClipCursor` to its own rect while another window holds the foreground, `ClipCursor(NULL)` from the non-foreground probe
releases it, the application does not re-apply it, and opening the dialog re-centres the cursor (observed at 423,0 → 968,556
and restored afterwards).

These tests use a fake surface, so they assert the contract rather than the desktop.
"""

from __future__ import annotations

import time

from udv_echo_process.acquire.ui.pointer import FreePointer, PointerReport

SCREEN = (1920, 1080)
DIALOG = (676, 391, 1260, 721)


class FakePointer:
    """A surface that can be told what the desktop is doing, and remembers what was asked of it."""

    def __init__(self, clips: list[tuple[int, int, int, int] | None] | None = None) -> None:
        self.clips = list(clips or [])
        self.release_calls = 0
        self.moves: list[tuple[int, int]] = []
        self.cursor_now = (423, 0)
        self.release_works = True

    def clip(self):
        if self.clips:
            return self.clips.pop(0) if len(self.clips) > 1 else self.clips[0]
        return (0, 0, SCREEN[0], SCREEN[1])

    def release_clip(self) -> bool:
        self.release_calls += 1
        if self.release_works:
            self.clips = [(0, 0, SCREEN[0], SCREEN[1])]
        return self.release_works

    def cursor(self):
        return self.cursor_now

    def move_cursor(self, x: int, y: int) -> bool:
        self.moves.append((int(x), int(y)))
        self.cursor_now = (int(x), int(y))
        return True

    def screen(self):
        return SCREEN


class TestASmallerClipIsReleased:
    def test_the_dialogs_clip_is_released(self):
        surface = FakePointer([DIALOG, DIALOG, DIALOG])
        with FreePointer(surface, poll_s=0.01) as guard:
            time.sleep(0.12)
        assert guard.report.detections >= 1
        assert surface.release_calls >= 1
        assert guard.report.every_clip_was_released

    def test_a_full_screen_clip_is_not_a_trap(self):
        # A full-screen clip is what Windows reports when nothing is confined, so it must not count as a detection.
        surface = FakePointer([(0, 0, SCREEN[0], SCREEN[1])] * 4)
        with FreePointer(surface, poll_s=0.01) as guard:
            time.sleep(0.08)
        assert guard.report.detections == 0
        assert surface.release_calls == 0
        assert guard.report.pointer_was_free_of_clips

    def test_a_released_clip_that_returns_is_released_again(self):
        surface = FakePointer([DIALOG, DIALOG, DIALOG, DIALOG])
        surface.release_works = True

        # every release "succeeds" but the surface keeps reporting the dialogs rect until it is popped
        class Stubborn(FakePointer):
            def release_clip(self) -> bool:
                self.release_calls += 1
                self.clips = [DIALOG]
                return True

        stubborn = Stubborn([DIALOG])
        with FreePointer(stubborn, poll_s=0.01) as guard:
            time.sleep(0.12)
        assert guard.report.detections >= 2
        assert stubborn.release_calls >= 2


class TestTheCursorComesBack:
    def test_the_operators_cursor_is_restored(self):
        surface = FakePointer()
        surface.cursor_now = (423, 0)
        with FreePointer(surface, poll_s=0.01):
            surface.cursor_now = (968, 556)  # the application re-centres it when the dialog opens
        assert surface.moves == [(423, 0)]
        assert surface.cursor_now == (423, 0)


class TestWhatTheReportSays:
    def test_a_quiet_run_says_the_pointer_was_never_trapped(self):
        surface = FakePointer([(0, 0, SCREEN[0], SCREEN[1])] * 3)
        with FreePointer(surface, poll_s=0.01) as guard:
            time.sleep(0.06)
        report: PointerReport = guard.report
        assert report.pointer_was_free_of_clips is True
        assert report.every_clip_was_released is True
        assert report.clips_seen == []

    def test_a_trap_records_its_rectangle(self):
        surface = FakePointer([DIALOG])
        with FreePointer(surface, poll_s=0.01) as guard:
            time.sleep(0.06)
        assert DIALOG in guard.report.clips_seen
