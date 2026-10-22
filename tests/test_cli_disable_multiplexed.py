"""The public ``acquire disable-multiplexed`` workflow, end to end, without a desktop.

The Win32 layer is a double: one bound window whose strip reports ``ready``, a scripted tree
(the projected clipped entry rows, then the projected full settings rows), the reader's own
``_get_text`` seam, and counters for every press. The two screenshot backends return the
**authentic** PNG pairs under ``tests/data/mpx-mode/``: ``entry-clipped-enabled`` before the
press and ``disabled-rolling-on`` after it, so the capture contract — templates, digests and
the mode attribution — is exercised on the real pixels, not on painted stand-ins.

What each test pins:

* exit ``0`` only when the post-press settings pair is fresh, ``VISUAL_DISABLED``, carries two
  64-character digests of its own frames, and every error field is empty;
* a raised press is recorded as an attempt but can never be reported as a verified post;
* an unknown post state and a failed trial-record rewrite both exit non-zero;
* the production callbacks are the reader itself, called with the binding and capture directory.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image
from test_acquire_channels_read import ENTRY_ROWS, SETTINGS_ROWS, WINDOW, _roles

from udv_echo_process.acquire import channels_read, disable_multiplexed
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_capture import ScreenFrame
from udv_echo_process.cli import acquire_main

DATA = __import__("pathlib").Path(__file__).parent / "data" / "mpx-mode"
ENTRY = DATA / "entry-clipped-enabled"
SETTINGS = DATA / "disabled-rolling-on"
ENTRY_HWND = 1003
POPUP_HWND = 1000

pytest.importorskip("PIL", reason="the acquire extra decodes the recorded fixtures")

#: The real reader, kept before the monkeypatch so the wrapper exercises it (not itself).
_READ_CHANNELS = channels_read.read_channels


def _frames(directory):
    return [
        Image.open(directory / f"channels-roi-frame-{index}.png").convert("RGB")
        for index in (1, 2)
    ]


class ReadyDesktop:
    """The Win32 surface only: one READY binding, scripted trees, an image queue, counters.

    ``screen_fingerprint`` is the reader's one resolution point (the driver re-enumerates there),
    so the surface for the next pair of reads is decided there and not by how often a consumer
    asks for ``last_roles``. The first two captures are the entry popup, the next two the full
    settings popup.
    """

    def __init__(self, *, post_absent: bool = False) -> None:
        self.post_absent = post_absent
        self.presses: list[int] = []
        self.bindings = 0
        self.warnings: list[str] = []
        self.reads = 0
        self._surface = "entry"
        self._target: WindowTarget | None = None
        self._images = [*_frames(ENTRY), *_frames(ENTRY), *_frames(SETTINGS)]

    # -- binding -------------------------------------------------------------------------
    def bind_target(self, hwnd: int) -> WindowTarget:
        self.bindings += 1
        assert hwnd == WINDOW
        self._target = WindowTarget(
            hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
        )
        return self._target

    def verify_bound_target(self, target: WindowTarget) -> WindowTarget:
        assert target == self._target
        return target

    # -- the read preconditions ----------------------------------------------------------
    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self):
        return None

    def strip_state(self) -> StripState:
        return StripState(button_count=3)  # the ready row, and nothing else

    # -- the reader's own seams ----------------------------------------------------------
    def screen_fingerprint(self) -> SimpleNamespace:
        self.reads += 1
        if self.reads <= 4:
            self._surface = "entry"
        elif self.post_absent:
            self._surface = "absent"
        else:
            self._surface = "settings"
        return SimpleNamespace(hwnd=WINDOW, rect=(0, 0, 1200, 800))

    @property
    def last_roles(self) -> dict:
        if self._surface == "entry":
            return _roles(ENTRY_ROWS)
        if self._surface == "absent":
            return _roles(())
        return _roles(SETTINGS_ROWS)

    def _get_text(self, hwnd: int) -> str:
        row = next(row for row in _roles(SETTINGS_ROWS)["raw"] if row["hwnd"] == hwnd)
        assert row["cls"] in {"Edit", "TSp_Edit"}
        return row["text"]

    # -- the screenshot backend ----------------------------------------------------------
    def grab(self) -> ScreenFrame:
        assert self._images, (
            "the command grabbed more frames than the scripted surfaces"
        )
        image = self._images.pop(0)
        return ScreenFrame(image=image, origin=(0, 0), size=image.size)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the disable command reached {name!r} on the Win32 double"
        )


def _install(
    monkeypatch,
    desktop: ReadyDesktop,
    *,
    raise_press: bool = False,
    press_rows=None,
):
    """Wire the double through the two seams the production command uses."""
    calls: list[dict] = []

    def read_channels(actuator=None, *, target=None, capture_dir=None, **kwargs):
        calls.append(
            {"actuator": actuator, "target": target, "capture_dir": capture_dir}
        )
        assert actuator is desktop
        assert target is not None
        assert capture_dir is not None
        # Keep the real production reader in the loop: only its Win32 seams are replaced.
        return _READ_CHANNELS(
            actuator,
            target=target,
            capture_dir=capture_dir,
            image_backend=desktop.grab,
        )

    def hold(hwnd: int) -> None:
        desktop.presses.append(int(hwnd))
        if raise_press:
            raise OSError("the control vanished")

    def class_of(hwnd: int) -> str:
        return "TSp_Panel" if hwnd == POPUP_HWND else "TSp_Button"

    def parent_of(hwnd: int) -> int:
        return WINDOW if hwnd == POPUP_HWND else POPUP_HWND

    def visible_children(hwnd: int):
        # The same tree owner the resolver enumerates, with current screen rects for the
        # clipped popup (its origin is (0,0) in the projected rows).
        if press_rows is not None:
            return tuple(press_rows)
        return tuple(_roles(ENTRY_ROWS)["raw"])

    monkeypatch.setattr(disable_multiplexed, "Win32Actuator", lambda **_: desktop)
    monkeypatch.setattr(
        disable_multiplexed, "visible_main_windows", lambda *args: (WINDOW,)
    )
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))
    monkeypatch.setattr(channels_read, "read_channels", read_channels)
    monkeypatch.setattr(
        channels_read,
        "_window_state",
        lambda hwnd: {"foreground": True, "minimized": False},
    )
    monkeypatch.setattr(disable_multiplexed, "_click_hold", hold)
    monkeypatch.setattr(disable_multiplexed, "_class_of", class_of)
    monkeypatch.setattr(disable_multiplexed, "_parent_of", parent_of)
    monkeypatch.setattr(disable_multiplexed, "_visible_children", visible_children)
    return calls


def _run(tmp_path, monkeypatch, *, desktop=None, raise_press=False, press_rows=None):
    desktop = desktop or ReadyDesktop()
    calls = _install(
        monkeypatch, desktop, raise_press=raise_press, press_rows=press_rows
    )
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "disable-multiplexed",
                "--capture-dir",
                str(tmp_path / "captures"),
                "--trial-record",
                str(tmp_path / "trial.json"),
                "--json",
            ]
        )
    return exit_info.value.code, desktop, calls


def test_exit_zero_only_after_a_fresh_verified_disabled_pair(
    tmp_path, monkeypatch, capsys
):
    code, desktop, calls = _run(tmp_path, monkeypatch)
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert desktop.presses == [ENTRY_HWND]
    assert report["posted"] == "unknown"
    assert report["post_mode"] == "VISUAL_DISABLED"
    assert report["post_capture_kind"] == "settings_numeric"
    digests = report["post_frame_digests"]
    assert len(digests) == 2 and all(len(value) == 64 for value in digests)
    assert report["press_error"] == "" and report["post_error"] == ""
    # the production callback is the reader itself, bound to this target and capture root
    assert len(calls) >= 3
    assert all(call["target"].hwnd == WINDOW for call in calls)
    assert all(call["capture_dir"] for call in calls)
    record = json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))
    assert record["phase"] == "after"
    assert record["posted"] == "unknown"
    assert record["post_frame_digests"] == digests


def test_a_raised_press_cannot_be_reported_as_a_verified_post(
    tmp_path, monkeypatch, capsys
):
    code, desktop, _calls = _run(tmp_path, monkeypatch, raise_press=True)
    report = json.loads(capsys.readouterr().out)

    assert code == 1
    assert desktop.presses == [ENTRY_HWND]
    assert report["stage"] == "press_raised"
    assert report["press_error"]
    # the post evidence may still be independently true, but it is not this invocation's success
    record = json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))
    assert record["posted"] == "unknown"
    assert "OSError" in record["press_error"]


def test_an_unknown_post_state_exits_one(tmp_path, monkeypatch, capsys):
    code, desktop, _calls = _run(
        tmp_path, monkeypatch, desktop=ReadyDesktop(post_absent=True)
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert code == 1
    assert desktop.presses == [ENTRY_HWND]
    assert report["post_mode"] == "UNKNOWN"
    assert report["post_frame_digests"] is None
    assert "no fresh verified disabled settings entry" in captured.err


def test_a_failed_trial_record_rewrite_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        disable_multiplexed,
        "update_trial_record",
        lambda path, payload: "the record could not be rewritten",
    )
    code, desktop, _calls = _run(tmp_path, monkeypatch)
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert code == 1
    assert desktop.presses == [ENTRY_HWND]
    assert report["trial_record_error"] == "the record could not be rewritten"
    assert report["post_frame_digests"]
    # The press did happen, but the only durable statement left is the pre-press obligation: it
    # must say so (open, pending, press not_attempted *as of that write*) and never be read as
    # "no press happened".
    assert report["action"] == "pending"
    assert report["trial_record_phase"] == "obligation"
    assert report["obligation_open"] is True
    assert report["presses"] == 1 and report["press"] == "attempted"
    record = json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))
    assert record["phase"] == "obligation"
    assert record["action"] == "pending"
    assert record["obligation_open"] is True
    assert record["press"] == "not_attempted"
    assert record["posted"] == "not_attempted"
    assert "as of this record's own write" in record["press_state_as_of"]
    assert "does not say the press did not happen" in captured.err


def test_stale_entry_geometry_refuses_at_the_press_with_zero_presses(
    tmp_path, monkeypatch, capsys
):
    rows = [
        {**row, "rect": (*row["rect"][:1], row["rect"][1] + 6, *row["rect"][2:])}
        if row["hwnd"] == ENTRY_HWND
        else row
        for row in _roles(ENTRY_ROWS)["raw"]
    ]
    code, desktop, _calls = _run(tmp_path, monkeypatch, press_rows=rows)
    captured = capsys.readouterr()
    report = json.loads(captured.out)

    assert code == 1
    assert desktop.presses == []
    assert report["stage"] == "refused"
    assert report["presses"] == 0
    assert report["press"] == "not_attempted" and report["posted"] == "not_attempted"
    record = json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))
    assert record["phase"] == "after"
    assert record["presses"] == 0 and record["press"] == "not_attempted"
    assert "licensed one" in record["boundary_error"]
