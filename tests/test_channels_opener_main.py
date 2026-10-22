"""Offline: ``channels_opener.main``'s orchestration, end to end, against a double.

The regression this file exists for: the report's reopen comparison must be based on the reading
taken **with the popup open**, never on the pre-hover reading. A run that starts from an absent
screen has a pre-hover reading with no amounts at all, so basing the comparison on it makes every
amount UNREADABLE and the run exit ``5`` with the popup closed — a false failure that only a test
driving ``main`` itself can see. Nothing here inspects source text: the fake lifecycle is called
and its report is read back.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire import (
    driver as _driver,
)
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import (
    SETTINGS_SIGNATURE,
    Attribution,
    ChannelsRead,
    ChannelsSurface,
    PerChannelAmounts,
    ValueSlot,
)

_SPEC = importlib.util.spec_from_file_location(
    "channels_opener", REPO / "tools" / "live" / "probes" / "channels_opener.py"
)
opener = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["channels_opener"] = opener
_SPEC.loader.exec_module(opener)

TARGET = WindowTarget(hwnd=900, thread_id=7, process_id=8, class_name="TMain_Scr")


def _slot(text: str, value: int) -> ValueSlot:
    return ValueSlot(
        slot=text, attribution=Attribution(caption=text), text=text, value=value
    )


def _absent() -> ChannelsRead:
    return ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)


def _settings(repeat: str = "2") -> ChannelsRead:
    return ChannelsRead(
        surface=ChannelsSurface.SETTINGS_POPUP,
        readable=True,
        signature=SETTINGS_SIGNATURE,
        repeat=_slot(repeat, int(repeat)),
        start_channel=_slot("1", 1),
        apply_from=_slot("1", 1),
        per_channel=PerChannelAmounts(
            profiles=_slot("50", 50), seconds=_slot("2.01", 201)
        ),
    )


class FakeActuator:
    """The lifecycle double, with one scripted popup that opens, closes and reopens."""

    def __init__(self, **_kwargs):
        self.opened = 0
        self.dismissed = 0

    def bind_target(self, hwnd):
        assert hwnd == TARGET.hwnd
        return TARGET

    def open_channels_popup(self, **_kwargs):
        self.opened += 1
        return ChannelsOpen(
            outcome=PopupOutcome.OPEN, surface="settings_popup", readable=True
        )

    def dismiss_channels_popup(self, **_kwargs):
        self.dismissed += 1
        return ChannelsDismissal(
            outcome=DismissalOutcome.ABSENT,
            point=(700, 500),
            surface_before="settings_popup",
            surface_after="absent",
        )


def test_main_bases_the_reopen_comparison_on_the_opened_reading_not_the_absent_one(
    monkeypatch, tmp_path
):
    readings = [_absent(), _settings(), _settings()]
    calls: list[dict] = []

    def fake_read(**kwargs):
        calls.append(kwargs)
        return readings.pop(0)

    from udv_echo_process.acquire import channels_read
    from udv_echo_process.acquire.win32 import tree

    monkeypatch.setattr(channels_read, "read_channels", fake_read)
    monkeypatch.setattr(_driver, "Win32Actuator", FakeActuator)
    monkeypatch.setattr(tree, "visible_main_windows", lambda _cls: (TARGET.hwnd,))

    report = tmp_path / "channels-opener.json"
    code = opener.main(["--report", str(report), "--settle", "0"])

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["baseline"]["surface"] == "absent"
    assert payload["phase"] == "complete"
    assert payload["comparison"]["ok"] is True
    assert payload["comparison"]["unreadable"] == []
    assert (
        payload["comparison"]["amounts_before"]
        == payload["comparison"]["amounts_after"]
    )
    assert payload["comparison"]["amounts_before"]["repeat"] == "2"
    assert code == 0
    # first, the opened reading, the reopened reading: the fake opener polls nothing itself.
    assert len(calls) == 3


def test_main_stops_after_one_close_that_is_not_observed_absent(monkeypatch, tmp_path):
    readings = [_absent(), _settings()]
    calls: list[dict] = []

    class UnknownClose(FakeActuator):
        def dismiss_channels_popup(self, **_kwargs):
            self.dismissed += 1
            return ChannelsDismissal(
                outcome=DismissalOutcome.UNKNOWN,
                point=(700, 500),
                surface_before="settings_popup",
                surface_after="settings_popup",
                clause="the poll ran out",
            )

    def fake_read(**kwargs):
        calls.append(kwargs)
        return readings.pop(0)

    from udv_echo_process.acquire import channels_read
    from udv_echo_process.acquire.win32 import tree

    monkeypatch.setattr(channels_read, "read_channels", fake_read)
    monkeypatch.setattr(_driver, "Win32Actuator", UnknownClose)
    monkeypatch.setattr(tree, "visible_main_windows", lambda _cls: (TARGET.hwnd,))

    report = tmp_path / "channels-opener.json"
    code = opener.main(["--report", str(report), "--settle", "0"])

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert code == 5
    assert payload["phase"] == "dismissal_unconfirmed"
    assert payload["popup_left_open_for_operator"] is True
    assert "reopen" not in payload
    # first, the opened reading, and the dismissal's own read: no reopen, no second path.
    assert len(calls) == 2


def test_the_report_is_written_before_the_gesture_and_says_one_was_attempted(
    monkeypatch, tmp_path
):
    """The review's evidence issue: the note must exist on disk *before* the hover."""
    readings = [_absent(), _settings(), _settings()]
    report = tmp_path / "channels-opener.json"
    seen: list[dict] = []

    class ObservingActuator(FakeActuator):
        def bind_target(self, hwnd):
            seen.append(json.loads(report.read_text(encoding="utf-8")))
            return super().bind_target(hwnd)

        def open_channels_popup(self, **_kwargs):
            seen.append(json.loads(report.read_text(encoding="utf-8")))
            return super().open_channels_popup(**_kwargs)

    def fake_read(**_kwargs):
        return readings.pop(0)

    from udv_echo_process.acquire import channels_read
    from udv_echo_process.acquire.win32 import tree

    monkeypatch.setattr(channels_read, "read_channels", fake_read)
    monkeypatch.setattr(_driver, "Win32Actuator", ObservingActuator)
    monkeypatch.setattr(tree, "visible_main_windows", lambda _cls: (TARGET.hwnd,))

    assert opener.main(["--report", str(report), "--settle", "0"]) == 0

    assert seen[0]["phase"] == "starting"
    assert seen[0].get("gesture_attempted") is not True
    # By the time the hover is taken, the durable note already says a gesture was attempted.
    assert seen[1]["gesture_attempted"] is True
    assert seen[1]["phase"] == "gesturing"


def test_an_unknown_open_keeps_its_record_and_does_not_claim_no_gesture(
    monkeypatch, tmp_path
):
    readings = [_absent()]

    class UnknownOpen(FakeActuator):
        def open_channels_popup(self, **_kwargs):
            self.opened += 1
            return ChannelsOpen(
                outcome=PopupOutcome.UNKNOWN,
                surface="settings_popup",
                readable=False,
                point=(700, 500),
                reads=3,
                clause="the hover produced no readable popup",
            )

    from udv_echo_process.acquire import channels_read
    from udv_echo_process.acquire.win32 import tree

    monkeypatch.setattr(channels_read, "read_channels", lambda **_k: readings.pop(0))
    monkeypatch.setattr(_driver, "Win32Actuator", UnknownOpen)
    monkeypatch.setattr(tree, "visible_main_windows", lambda _cls: (TARGET.hwnd,))

    report = tmp_path / "channels-opener.json"
    code = opener.main(["--report", str(report), "--settle", "0"])
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert code == 4
    assert payload["phase"] == "open_unconfirmed"
    assert payload["gesture_attempted"] is True
    # The typed record survives: surface, clause and the read count are all stated.
    assert payload["opened"]["outcome"] == "unknown"
    assert payload["opened"]["surface"] == "settings_popup"
    assert payload["opened"]["reads"] == 3
    assert "no readable popup" in payload["opened"]["clause"]
    # The typed record states the last surface it saw, so that (and only that) is classified.
    assert payload["popup_left_open_for_operator"] is True


def test_an_unexpected_exception_never_leaves_a_success_shaped_prior_state(
    monkeypatch, tmp_path
):
    from udv_echo_process.acquire import channels_read
    from udv_echo_process.acquire.win32 import tree

    def explode(_cls):
        raise RuntimeError("the window walk failed")

    monkeypatch.setattr(channels_read, "read_channels", lambda **_k: _absent())
    monkeypatch.setattr(_driver, "Win32Actuator", FakeActuator)
    monkeypatch.setattr(tree, "visible_main_windows", explode)

    report = tmp_path / "channels-opener.json"
    code = opener.main(["--report", str(report), "--settle", "0"])
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert code == 2
    assert payload["phase"] == "failed"
    assert "RuntimeError: the window walk failed" in payload["failed"]
    assert payload["gesture_attempted"] is False
    assert payload["popup_left_open_for_operator"] is None


def test_a_baseline_compares_all_five_amounts_and_names_an_unstated_one():
    before = _settings()
    outcome = opener.hover_outcome(
        _absent(),
        before,
        {"numeric_texts": {"repeat": "2", "profiles": "50"}},
    )
    assert outcome["baseline_uncompared"] == [
        "start_channel",
        "apply_from",
        "seconds",
    ]
    assert outcome["baseline_differences"] == []
    assert "2 of 5" in outcome["settings_unchanged"]

    drifted = opener.hover_outcome(
        _absent(),
        before,
        {
            "numeric_texts": {
                "repeat": "2",
                "start_channel": "1",
                "apply_from": "1",
                "profiles": "9",
                "seconds": "2.01",
            }
        },
    )
    assert drifted["baseline_differences"] == ["profiles: '9' -> '50'"]
    assert drifted["baseline_uncompared"] == []
