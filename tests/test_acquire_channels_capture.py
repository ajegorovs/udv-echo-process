"""The optional capture evidence: attributed, still, bracketed — and never a caption.

The workflow is driven end to end, including the public CLI, against an **injected image
backend** and fake window-state reads, so nothing here needs a desktop, a screenshot, Pillow or
``pywin32``. The structural rows are the projected settings-popup shape the read tests already
carry (``test_acquire_channels_read``), reused rather than duplicated so the two halves cannot
drift.

What is held:

1. the ROI is the popup's own rectangle out of the structural report — never a constant;
2. two frames are saved and their digests compared, and a differing pair stays ``UNKNOWN``;
3. every numeric amount is bracketed by a read taken before and after the capture, and a value
   that moves refuses the pairing instead of picking one side;
4. foreground, non-minimised and same-target guards are required, and a missing reading is a
   failure rather than a pass;
5. the caption is ``UNKNOWN`` with ``recognition: NOT_PERFORMED`` — no OCR, and the operator's
   caption is nowhere in the report;
6. without ``--capture-dir`` the report is the original one read, with ``capture`` null.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from test_acquire_channels_read import SETTINGS_ROWS, WINDOW

from udv_echo_process.acquire import channels_capture, channels_read
from udv_echo_process.acquire.actuator import WindowTarget

SCREEN = (1920, 1080)
POPUP = (0, 0, 393, 426)


class FakeImage:
    """A duck-typed frame: the members the capture path asks of a real grab, and no more."""

    def __init__(self, width: int, height: int, seed: int = 0) -> None:
        self.width = width
        self.height = height
        self.mode = "RGB"
        self.seed = seed
        self.pixels = bytes(((x * 31 + seed * 17) % 251) for x in range(width * height))

    def convert(self, mode: str) -> FakeImage:
        assert mode == "L"
        return self

    def histogram(self) -> list[int]:
        counts = [0] * 256
        for value in self.pixels:
            counts[value] += 1
        return counts

    def crop(self, box: tuple[int, int, int, int]) -> FakeImage:
        left, top, right, bottom = box
        # A real crop slices the frame: the same region of a flat frame stays flat, and two
        # frames with different pixels stay different after cropping.
        cropped = FakeImage(right - left, bottom - top, seed=self.seed)
        cropped.pixels = b"".join(
            self.pixels[row * self.width + left : row * self.width + right]
            for row in range(top, bottom)
        )
        return cropped

    def tobytes(self) -> bytes:
        return self.pixels

    def save(self, path, format: str = "") -> None:
        assert format == "PNG", "a capture is PNG: JPEG ringing is what costs a caption"
        Path(path).write_bytes(b"fake-png")


def backend(*, seeds: tuple[int, int] = (0, 0), flat: bool = False, fail: bool = False):
    """An image backend returning two frames with given seeds, optionally flat or failing."""
    calls: list[int] = []

    def grab() -> FakeImage:
        if fail:
            raise RuntimeError("no desktop")
        index = len(calls)
        calls.append(index)
        if flat:
            image = FakeImage(*SCREEN, seed=0)
            image.pixels = bytes(64 for _ in range(SCREEN[0] * SCREEN[1]))
            return image
        return FakeImage(*SCREEN, seed=seeds[min(index, 1)])

    grab.calls = calls  # type: ignore[attr-defined]
    return grab


class CaptureActuator:
    """The read surface only, with a fingerprint that states the window rect."""

    def __init__(
        self, *, after_text: str | None = None, rect=(0, 0, 1920, 1080)
    ) -> None:
        self.reads = 0
        self.after_text = after_text
        self.rect = rect
        self.warnings: list[str] = []

    def bind_target(self, hwnd):
        assert hwnd == WINDOW
        return WindowTarget(
            hwnd=WINDOW, thread_id=12, process_id=34, class_name="TMain_Scr"
        )

    def verify_bound_target(self, target):
        assert target.hwnd == WINDOW
        return target

    def screen_fingerprint(self):
        self.reads += 1
        return type("Fingerprint", (), {"hwnd": WINDOW, "rect": self.rect})()

    def _get_text(self, hwnd: int) -> str:
        from test_acquire_channels_read import _roles

        row = next(row for row in _roles(SETTINGS_ROWS)["raw"] if row["hwnd"] == hwnd)
        assert row["cls"] in {"Edit", "TSp_Edit"}
        text = row["text"]
        # A second inspection states a different repeat: the bracketing must refuse the pair.
        # Only the *second* inspection (reads == 2) states the changed value.
        if self.after_text is not None and self.reads > 1 and hwnd == REPEAT_EDIT:
            return self.after_text
        return text

    @property
    def last_roles(self) -> dict:
        from test_acquire_channels_read import _roles

        return _roles(SETTINGS_ROWS)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the capture path reached {name!r} on the actuator; channels-read has no gesture"
        )


#: The repeat amount's own ``TSp_Edit`` in the projected settings shape.
REPEAT_EDIT = 1018


@pytest.fixture(autouse=True)
def one_visible_window(monkeypatch):
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))


def states(*, foreground: bool | None = True, minimized: bool | None = False):
    return lambda hwnd: {"foreground": foreground, "minimized": minimized}


def capture(
    tmp_path, *, actuator=None, image_backend=None, window_state=None, **kwargs
):
    return channels_read.read_channels(
        actuator if actuator is not None else CaptureActuator(),
        capture_dir=tmp_path,
        image_backend=image_backend or backend(**kwargs),
        window_state=window_state or states(),
    )


# ---------------------------------------------------------------------------------------------
# the evidence a still, attributed capture carries
# ---------------------------------------------------------------------------------------------


def test_a_still_attributed_capture_is_ok_bracketed_and_caption_free(tmp_path) -> None:
    report = capture(tmp_path)
    evidence = report.capture
    assert evidence is not None
    assert evidence.status == "ok", evidence.unknown_reasons
    assert evidence.roi == POPUP
    assert evidence.captured is True
    assert evidence.stable is True
    assert len(evidence.frames) == 2
    assert all(frame.stats.non_blank for frame in evidence.frames)
    assert evidence.frames[0].digest == evidence.frames[1].digest
    assert Path(evidence.frames[0].path).exists()
    assert Path(evidence.frames[1].path).exists()
    assert evidence.directory and Path(evidence.directory).parent == tmp_path
    # the caption is not read, and the operator's statement is nowhere in the report
    assert evidence.caption == "UNKNOWN"
    assert evidence.recognition == "NOT_PERFORMED"
    assert "no recognition was performed" in evidence.caption_evidence
    # every amount held across the capture, from its own widget
    assert evidence.numeric.consistent is True
    assert {b.slot for b in evidence.numeric.slots} == {
        "repeat",
        "start_channel",
        "apply_from",
        "profiles",
        "seconds",
    }
    assert evidence.guards.consistent is True
    # the read itself is unchanged: a successful inspection verifies no setup
    assert report.readable is True
    assert report.setup_verified is False


def test_the_roi_is_derived_from_the_popup_rect_not_hardcoded(tmp_path) -> None:
    # A translated capture: every row shifted, so a constant ROI could not match.
    rows = tuple(
        (
            hwnd,
            parent,
            cls,
            (rect[0] + 40, rect[1] + 7, rect[2] + 40, rect[3] + 7),
            text,
        )
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )

    class Translated(CaptureActuator):
        @property
        def last_roles(self):
            from test_acquire_channels_read import _roles

            return _roles(rows)

    report = channels_read.read_channels(
        Translated(),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    )
    assert report.capture.roi == (40, 7, 433, 433)


# ---------------------------------------------------------------------------------------------
# the refusals: each one is unknown, never a quietly successful picture
# ---------------------------------------------------------------------------------------------


def test_two_frames_that_differ_leave_the_capture_unknown(tmp_path) -> None:
    evidence = capture(tmp_path, image_backend=backend(seeds=(0, 1))).capture
    assert evidence.status == "UNKNOWN"
    assert evidence.stable is False
    assert evidence.captured is True, (
        "a torn frame is still a picture; it is just not evidence"
    )
    assert any("differ" in reason for reason in evidence.unknown_reasons)


def test_a_flat_frame_is_not_evidence(tmp_path) -> None:
    evidence = capture(tmp_path, image_backend=backend(flat=True)).capture
    assert evidence.status == "UNKNOWN"
    assert evidence.frames[0].stats.non_blank is False
    assert any("blank" in reason for reason in evidence.unknown_reasons)


def test_a_failed_grab_is_reported_and_nothing_is_written(tmp_path) -> None:
    evidence = capture(tmp_path, image_backend=backend(fail=True)).capture
    assert evidence.status == "UNKNOWN"
    assert evidence.captured is False
    assert evidence.frames == ()
    assert any("could not be captured" in reason for reason in evidence.unknown_reasons)
    assert not list(tmp_path.glob("*.png"))


def test_a_background_or_minimised_window_cannot_be_attributed(tmp_path) -> None:
    for state in (
        states(foreground=False),
        states(minimized=True),
        states(foreground=None),
        states(minimized=None),
    ):
        evidence = capture(tmp_path, window_state=state).capture
        assert evidence.status == "UNKNOWN"
        assert evidence.guards.consistent is False
        assert evidence.unknown_reasons


def test_a_number_that_moves_across_the_capture_refuses_the_pairing(tmp_path) -> None:
    report = channels_read.read_channels(
        CaptureActuator(after_text="21"),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    )
    evidence = report.capture
    assert evidence.status == "UNKNOWN"
    assert evidence.numeric.consistent is False
    repeat = next(b for b in evidence.numeric.slots if b.slot == "repeat")
    assert (repeat.text_before, repeat.text_after) == ("1", "21")
    assert any("did not hold" in reason for reason in evidence.unknown_reasons)


def test_a_popup_rect_outside_the_frame_is_refused_not_cropped(tmp_path) -> None:
    report = channels_read.read_channels(
        CaptureActuator(),
        capture_dir=tmp_path,
        image_backend=lambda: FakeImage(64, 64),
        window_state=states(),
    )
    assert report.capture.status == "UNKNOWN"
    assert any(
        "outside the 64x64 frame" in reason for reason in report.capture.unknown_reasons
    )


# ---------------------------------------------------------------------------------------------
# the public CLI, and the opt-in boundary
# ---------------------------------------------------------------------------------------------


def test_without_capture_dir_the_report_is_unchanged() -> None:
    report = channels_read.read_channels(CaptureActuator())
    assert report.capture is None
    assert report.readable is True


def test_the_cli_captures_into_the_named_directory_and_stays_unknown_on_the_caption(
    tmp_path, monkeypatch, capsys
) -> None:
    from udv_echo_process.cli import acquire_main

    monkeypatch.setattr(
        channels_read, "Win32Actuator", lambda **kwargs: CaptureActuator()
    )
    monkeypatch.setattr(channels_read, "_grab_screen", backend())
    monkeypatch.setattr(channels_read, "_window_state", states())
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["channels-read", "--json", "--capture-dir", str(tmp_path)])
    assert exit_info.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["capture"]["status"] == "ok"
    assert report["capture"]["caption"] == "UNKNOWN"
    assert report["capture"]["recognition"] == "NOT_PERFORMED"
    assert report["capture"]["stable"] is True
    assert report["repeat"]["text"] == "1"
    assert report["capture"]["frames"][1]["path"].endswith("channels-roi-frame-2.png")
    assert Path(report["capture"]["frames"][1]["path"]).exists()


def test_the_cli_exits_three_when_the_capture_cannot_be_attributed(
    tmp_path, monkeypatch, capsys
) -> None:
    from udv_echo_process.cli import acquire_main

    monkeypatch.setattr(
        channels_read, "Win32Actuator", lambda **kwargs: CaptureActuator()
    )
    monkeypatch.setattr(channels_read, "_grab_screen", backend(seeds=(0, 1)))
    monkeypatch.setattr(channels_read, "_window_state", states())
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["channels-read", "--json", "--capture-dir", str(tmp_path)])
    assert exit_info.value.code == 3
    captured = capsys.readouterr()
    assert json.loads(captured.out)["capture"]["status"] == "UNKNOWN"
    assert "capture:" in captured.err


def test_no_recognition_dependency_is_imported() -> None:
    for module in ("pytesseract", "easyocr", "cv2", "tesserocr"):
        assert module not in sys.modules, f"{module} must not be reachable from a read"
    assert (
        channels_capture.CAPTION_EVIDENCE
        == channels_capture.CaptureEvidence.model_fields["caption_evidence"].default
    )


# ---------------------------------------------------------------------------------------------
# B1: the frame's own origin, and a grab that disagrees with the reported screen
# ---------------------------------------------------------------------------------------------


def _translated_rows(dx: int, dy: int) -> tuple[tuple, ...]:
    return tuple(
        (hwnd, parent, cls, (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy), text)
        for hwnd, parent, cls, r, text in SETTINGS_ROWS
    )


def test_a_frame_above_and_left_of_the_primary_monitor_is_cropped_by_its_origin(
    tmp_path,
) -> None:
    """A virtual desktop with a negative origin: the popup sits at negative screen coords.

    The crop box is the popup rect minus the *frame's* origin, so a backend that states the
    virtual origin the grab was taken from produces the popup out of the right pixels. Treating
    the origin as ``(0, 0)`` puts the box off the frame and must refuse.
    """

    rows = _translated_rows(-1920, -200)

    class NegativeOrigin(CaptureActuator):
        @property
        def last_roles(self):
            from test_acquire_channels_read import _roles

            return _roles(rows)

    frame = channels_capture.ScreenFrame(
        image=FakeImage(*SCREEN), origin=(-1920, -200), size=SCREEN
    )
    report = channels_read.read_channels(
        NegativeOrigin(),
        capture_dir=tmp_path,
        image_backend=lambda: frame,
        window_state=states(),
    )
    evidence = report.capture
    assert evidence.roi == (-1920, -200, -1527, 226)
    assert evidence.status == "ok", evidence.unknown_reasons
    assert len(evidence.frames) == 2
    assert evidence.frames[0].rect == evidence.roi


def test_a_grab_whose_size_disagrees_with_the_reported_screen_is_refused(
    tmp_path,
) -> None:
    """A 960x540 bitmap declared as a 1920x1080 desktop is scaled or partial: no crop is guessed."""

    frame = channels_capture.ScreenFrame(
        image=FakeImage(960, 540), origin=(0, 0), size=SCREEN
    )
    report = channels_read.read_channels(
        CaptureActuator(),
        capture_dir=tmp_path,
        image_backend=lambda: frame,
        window_state=states(),
    )
    evidence = report.capture
    assert evidence.status == "UNKNOWN"
    assert evidence.captured is False
    assert any(
        "960x540" in reason and "1920x1080" in reason
        for reason in evidence.unknown_reasons
    ), evidence.unknown_reasons
    assert not list(tmp_path.rglob("*.png"))


# ---------------------------------------------------------------------------------------------
# B2: a second capture into the same caller directory must not overwrite the first
# ---------------------------------------------------------------------------------------------


def test_a_repeated_capture_into_the_same_directory_preserves_the_earlier_files(
    tmp_path,
) -> None:
    first = capture(tmp_path).capture
    first_paths = [frame.path for frame in first.frames]
    original = {path: Path(path).read_bytes() for path in first_paths}
    second = capture(tmp_path).capture
    second_paths = [frame.path for frame in second.frames]

    assert first.status == "ok" and second.status == "ok"
    assert first_paths and second_paths
    assert set(first_paths).isdisjoint(second_paths), (
        "a second capture re-used the first run's filenames, so the old evidence was overwritten"
    )
    for path in first_paths + second_paths:
        assert Path(path).exists(), path
    for path in first_paths:
        assert Path(path).read_bytes() == original[path], (
            f"the earlier capture at {path} was overwritten"
        )
    assert len(list(tmp_path.rglob("*.png"))) == 4


# ---------------------------------------------------------------------------------------------
# B3: a non-readable structural report cannot produce an ``ok`` capture
# ---------------------------------------------------------------------------------------------


def test_a_non_readable_report_is_never_an_ok_capture(tmp_path) -> None:
    """The group box's bands changed, so three of five amounts did not resolve.

    The structural report says ``readable=False``; an ``ok`` capture would pair a picture with
    amounts the read itself refused, so the capture must stay ``UNKNOWN`` and name the gap.
    """

    rows = SETTINGS_ROWS + (
        (1050, 1019, "TSp_Value_Button", (20, 380, 80, 406), ""),
        (1051, 1050, "TSp_Edit", (24, 384, 74, 402), "3"),
    )

    class Unreadable(CaptureActuator):
        def _get_text(self, hwnd: int) -> str:
            from test_acquire_channels_read import _roles

            return next(row for row in _roles(rows)["raw"] if row["hwnd"] == hwnd)[
                "text"
            ]

        @property
        def last_roles(self):
            from test_acquire_channels_read import _roles

            return _roles(rows)

    report = channels_read.read_channels(
        Unreadable(),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    )
    evidence = report.capture
    assert report.readable is False
    assert evidence.status == "UNKNOWN"
    assert evidence.numeric.consistent is False
    assert any("not readable" in reason for reason in evidence.unknown_reasons), (
        evidence.unknown_reasons
    )
    assert "apply_from" in evidence.numeric.note, evidence.numeric.note
    assert "profiles" in evidence.numeric.note, evidence.numeric.note


# ---------------------------------------------------------------------------------------------
# B4: a failed closing read keeps its frames and reports unknown instead of orphaning them
# ---------------------------------------------------------------------------------------------


def test_a_failed_closing_read_keeps_the_frames_and_reports_unknown(tmp_path) -> None:
    class ClosingFails(CaptureActuator):
        def screen_fingerprint(self):
            self.reads += 1
            if self.reads > 1:
                raise RuntimeError("the window disappeared during the closing read")
            return type("Fingerprint", (), {"hwnd": WINDOW, "rect": self.rect})()

    report = channels_read.read_channels(
        ClosingFails(),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    )
    evidence = report.capture
    assert evidence is not None
    assert evidence.status == "UNKNOWN"
    assert evidence.captured is True
    assert len(evidence.frames) == 2
    assert all(Path(frame.path).exists() for frame in evidence.frames)
    assert evidence.numeric.consistent is False
    assert any(
        "closing read" in reason or "after-capture read" in reason
        for reason in evidence.unknown_reasons
    ), evidence.unknown_reasons


# ---------------------------------------------------------------------------------------------
# B5: the pairing compares the edit *and* its owner, and the popup must be the same popup
# ---------------------------------------------------------------------------------------------


def _renumber(rows: tuple[tuple, ...], old: int, new: int) -> tuple[tuple, ...]:
    return tuple(
        (
            new if hwnd == old else hwnd,
            new if parent == old else parent,
            cls,
            rect,
            text,
        )
        for hwnd, parent, cls, rect, text in rows
    )


def test_a_changed_owning_widget_refuses_the_pairing_even_when_the_edit_holds(
    tmp_path,
) -> None:
    after_rows = _renumber(SETTINGS_ROWS, 1017, 1099)

    class OwnerMoves(CaptureActuator):
        @property
        def last_roles(self):
            from test_acquire_channels_read import _roles

            return _roles(after_rows if self.reads > 1 else SETTINGS_ROWS)

    evidence = channels_read.read_channels(
        OwnerMoves(),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    ).capture
    assert evidence.status == "UNKNOWN"
    repeat = next(b for b in evidence.numeric.slots if b.slot == "repeat")
    assert (repeat.hwnd_before, repeat.hwnd_after) == (1018, 1018)
    assert (repeat.owner_before, repeat.owner_after) == (1017, 1099)
    assert repeat.consistent is False
    assert "owner" in evidence.numeric.note


def test_a_changed_popup_handle_with_the_same_rect_is_refused(tmp_path) -> None:
    after_rows = _renumber(SETTINGS_ROWS, 1000, 1099)

    class PopupReplaced(CaptureActuator):
        @property
        def last_roles(self):
            from test_acquire_channels_read import _roles

            return _roles(after_rows if self.reads > 1 else SETTINGS_ROWS)

    evidence = channels_read.read_channels(
        PopupReplaced(),
        capture_dir=tmp_path,
        image_backend=backend(),
        window_state=states(),
    ).capture
    assert evidence.status == "UNKNOWN"
    assert any(
        "popup" in reason and "identity" in reason
        for reason in evidence.unknown_reasons
    ), evidence.unknown_reasons


# ---------------------------------------------------------------------------------------------
# the explicit capture kinds: entry_no_numeric never relaxes settings_numeric
# ---------------------------------------------------------------------------------------------


def _kind_evidence(
    kind: str,
    *,
    surface: str,
    applicable: bool,
    slots: tuple = (),
    roi=(0, 0, 158, 43),
):
    """One assembled record at the chosen contract, with two non-blank agreeing frames."""
    width, height = roi[2] - roi[0], roi[3] - roi[1]
    frames = tuple(
        channels_capture.FrameEvidence(
            index=index,
            path=f"frame-{index}.png",
            rect=roi,
            stats=channels_capture.FrameStats(
                width=width,
                height=height,
                distinct_grey_levels=4,
                dominant_fraction=0.4,
                non_blank=True,
            ),
            digest="a" * 64,
        )
        for index in (1, 2)
    )
    guard = channels_capture.WindowGuard(
        label="before",
        hwnd=WINDOW,
        rect=(0, 0, 1920, 1080),
        foreground=True,
        minimized=False,
        surface=surface,
        popup_rect=roi,
        popup_hwnd=1000,
    )
    return channels_capture.assemble(
        roi=roi,
        frames=frames,
        guards=channels_capture.GuardComparison(
            before=guard,
            after=guard.model_copy(update={"label": "after"}),
            consistent=True,
        ),
        numeric=channels_capture.NumericBracketing(
            slots=slots,
            consistent=not applicable,
            note="no numeric settings fields on the clipped entry popup",
            applicable=applicable,
        ),
        capture_kind=kind,
    )


def test_an_entry_capture_is_ok_without_any_numeric_pairing() -> None:
    evidence = _kind_evidence(
        channels_capture.CAPTURE_ENTRY_NO_NUMERIC,
        surface="multiplexer_on_entry",
        applicable=False,
    )
    assert evidence.status == "ok"
    assert evidence.capture_kind == "entry_no_numeric"
    assert evidence.stable is True
    assert evidence.numeric.slots == ()
    assert evidence.numeric.applicable is False


def test_an_entry_capture_that_pairs_an_amount_is_not_ok() -> None:
    slot = channels_capture.Bracket(slot="profiles", consistent=True)
    evidence = _kind_evidence(
        channels_capture.CAPTURE_ENTRY_NO_NUMERIC,
        surface="multiplexer_on_entry",
        applicable=True,
        slots=(slot,),
    )
    assert evidence.status == "UNKNOWN"
    assert any("not mixed" in reason for reason in evidence.unknown_reasons)


def test_the_settings_contract_still_requires_all_five_amounts() -> None:
    evidence = _kind_evidence(
        channels_capture.CAPTURE_SETTINGS_NUMERIC,
        surface="settings_popup",
        applicable=False,
        roi=(0, 0, 393, 426),
    )
    assert evidence.status == "UNKNOWN"
    assert any(
        "numeric contract inapplicable" in reason for reason in evidence.unknown_reasons
    )


def test_an_entry_kind_over_a_settings_surface_is_refused() -> None:
    evidence = _kind_evidence(
        channels_capture.CAPTURE_ENTRY_NO_NUMERIC,
        surface="settings_popup",
        applicable=False,
    )
    assert evidence.status == "UNKNOWN"
    assert any("settings_popup" in reason for reason in evidence.unknown_reasons)
