"""Offline: the managed open/read/capture/close workflow, driven against a double.

No window, no cursor, no application. The double records every lifecycle call, so the cases that
matter here are the ones a single happy path cannot show: a failure at each stage, the *absence*
of a hidden retry, a strip view that cannot be read staying ``unknown`` instead of ``ready``, and
a close that is attempted in a ``finally`` while the read and its capture survive it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire import (
    driver as _driver,  # noqa: F401  (breaks the ui.channels import cycle)
)
from udv_echo_process.acquire.actuator import StripView, WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.channels_inspect import (
    InspectionOutcome,
    inspect_channels,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import (
    SETTINGS_SIGNATURE,
    ChannelsRead,
    ChannelsSurface,
)

TARGET = WindowTarget(hwnd=4242, thread_id=7, process_id=8, class_name="TMain_Scr")


def evidence(status: str = "ok") -> CaptureEvidence:
    return CaptureEvidence(
        status=status,
        captured=True,
        guards=GuardComparison(before=WindowGuard(label="before", hwnd=TARGET.hwnd)),
        numeric=NumericBracketing(),
    )


def reading(
    surface: ChannelsSurface = ChannelsSurface.SETTINGS_POPUP,
    *,
    readable: bool = True,
    capture: CaptureEvidence | None = None,
) -> ChannelsRead:
    return ChannelsRead(
        surface=surface,
        readable=readable,
        signature=SETTINGS_SIGNATURE if readable else (),
        capture=capture,
    )


class ScriptedReads:
    """A read callable that hands out prepared results in order and records its calls."""

    def __init__(self, *values):
        self.values = list(values)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(value, Exception):
            raise value
        return value


class Fake:
    """The lifecycle double: one call per stage, and a call log that proves nothing else ran."""

    def __init__(
        self,
        *,
        opened: ChannelsOpen | None = None,
        closed: ChannelsDismissal | None = None,
        view: StripView | str | None = StripView.READY,
        open_error: Exception | None = None,
        close_error: Exception | None = None,
        state_error: Exception | None = None,
    ):
        self.calls: list[str] = []
        self.opened = opened or ChannelsOpen(
            outcome=PopupOutcome.OPEN, surface="settings_popup", readable=True
        )
        self.closed = closed or ChannelsDismissal(
            outcome=DismissalOutcome.ABSENT,
            point=(700, 500),
            surface_before="settings_popup",
            surface_after="absent",
        )
        self.view = view
        self.open_error = open_error
        self.close_error = close_error
        self.state_error = state_error

    def verify_bound_target(self, expected):
        self.calls.append("verify")
        assert expected == TARGET
        return expected

    def strip_state(self):
        self.calls.append("strip_state")
        if self.state_error is not None:
            raise self.state_error
        return SimpleNamespace(view=self.view)

    def open_channels_popup(self, **kwargs):
        self.calls.append("open")
        if self.open_error is not None:
            raise self.open_error
        return self.opened

    def dismiss_channels_popup(self, **kwargs):
        self.calls.append("dismiss")
        if self.close_error is not None:
            raise self.close_error
        return self.closed


def run(fake: Fake, reads: ScriptedReads, **kwargs):
    options = {
        "actuator": fake,
        "target": TARGET,
        "capture_dir": "captures",
        "allow_real_input": True,
    }
    options.update(kwargs)
    return inspect_channels(read=reads, **options)


def test_owned_popup_is_read_captured_and_closed_once():
    captured = evidence()
    reads = ScriptedReads(reading(ChannelsSurface.ABSENT), reading(capture=captured))
    fake = Fake()

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.CLOSED
    assert result.mode == "ready" and result.mode_source == "strip_state"
    assert result.capture is captured and result.read.capture is captured
    assert (
        result.closed is not None and result.closed.outcome is DismissalOutcome.ABSENT
    )
    assert result.popup_left_open is False
    assert fake.calls == ["verify", "strip_state", "open", "dismiss"]
    # One read before the hover, one capture read inside it: no hidden retry.
    assert len(reads.calls) == 2


def test_capture_failure_still_closes_and_preserves_the_close_outcome():
    reads = ScriptedReads(
        reading(ChannelsSurface.ABSENT), AcquisitionError("the grab failed")
    )
    fake = Fake()

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.CLOSED
    assert result.read is None and result.capture is None
    assert result.refused_stage == "capture" and "grab failed" in result.refused
    assert result.closed.outcome is DismissalOutcome.ABSENT
    assert fake.calls.count("dismiss") == 1


def test_close_that_is_not_observed_absent_keeps_the_capture_and_is_not_retried():
    captured = evidence()
    reads = ScriptedReads(reading(ChannelsSurface.ABSENT), reading(capture=captured))
    fake = Fake(
        closed=ChannelsDismissal(
            outcome=DismissalOutcome.UNKNOWN,
            point=(700, 500),
            surface_before="settings_popup",
            surface_after="settings_popup",
            clause="the poll ran out",
        )
    )

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.UNCONFIRMED
    assert result.capture is captured
    assert result.closed.outcome is DismissalOutcome.UNKNOWN
    assert result.popup_left_open is True
    assert fake.calls.count("dismiss") == 1
    assert any("no second path" in note for note in result.notes)


def test_a_refused_close_is_recorded_and_not_retried():
    captured = evidence()
    reads = ScriptedReads(reading(ChannelsSurface.ABSENT), reading(capture=captured))
    fake = Fake(close_error=AcquisitionError("the path cannot be derived"))

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.UNCONFIRMED
    assert result.closed is None
    assert result.capture is captured
    assert fake.calls.count("dismiss") == 1
    assert any("not retried" in note for note in result.notes)


def test_an_open_that_is_unknown_refuses_and_never_reaches_a_read():
    reads = ScriptedReads(reading(ChannelsSurface.ABSENT))
    fake = Fake(
        opened=ChannelsOpen(
            outcome=PopupOutcome.UNKNOWN,
            surface="absent",
            readable=False,
            clause="the hover produced nothing",
        )
    )

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "open"
    assert result.popup_left_open is False
    assert fake.calls.count("open") == 1 and "dismiss" not in fake.calls
    assert len(reads.calls) == 1


def test_a_recording_strip_refuses_before_any_gesture():
    reads = ScriptedReads(reading())
    fake = Fake(view=StripView.RECORDING)

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "recording"
    assert result.mode == "recording"
    assert fake.calls == ["verify", "strip_state"]
    assert reads.calls == []


def test_an_unreadable_strip_view_is_unknown_and_never_ready():
    reads = ScriptedReads(reading())
    fake = Fake(state_error=RuntimeError("the strip panel did not resolve"))

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "mode"
    assert result.mode == "unknown" and result.mode_source == "unread"
    assert fake.calls == ["verify", "strip_state"]
    assert reads.calls == []


def test_allow_real_input_false_refuses_before_anything_is_read_or_moved():
    reads = ScriptedReads(reading())
    fake = Fake()

    result = run(fake, reads, allow_real_input=False)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "real-input"
    assert fake.calls == [] and reads.calls == []


def test_an_already_open_popup_is_refused_unless_adoption_is_requested():
    reads = ScriptedReads(reading())
    fake = Fake()

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "adopt"
    assert fake.calls == ["verify", "strip_state"] and "open" not in fake.calls


def test_an_adopted_popup_is_left_open_unless_the_caller_owns_the_close():
    captured = evidence()
    reads = ScriptedReads(reading(capture=captured))
    fake = Fake()

    result = run(fake, reads, adopt_open=True)

    assert result.outcome is InspectionOutcome.READ
    assert result.capture is captured
    assert result.closed is None and result.popup_left_open is True
    assert "dismiss" not in fake.calls
    assert any("left open" in note for note in result.notes)


def test_an_adopted_popup_is_closed_when_close_adopted_is_explicit():
    reads = ScriptedReads(reading(capture=evidence()))
    fake = Fake()

    result = run(fake, reads, adopt_open=True, close_adopted=True)

    assert result.outcome is InspectionOutcome.CLOSED
    assert result.opened is None
    assert result.closed.outcome is DismissalOutcome.ABSENT
    assert fake.calls == ["verify", "strip_state", "dismiss"]


@pytest.mark.parametrize(
    "surface", [ChannelsSurface.AMBIGUOUS, ChannelsSurface.CHANGED_STRUCTURE]
)
def test_a_pre_open_surface_that_is_not_the_popup_refuses_without_a_hover(surface):
    reads = ScriptedReads(reading(surface))
    fake = Fake()

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.REFUSED
    assert result.refused_stage == "surface"
    assert "open" not in fake.calls


def test_a_non_acquisition_capture_failure_is_a_stated_partial_fact_not_an_escape():
    reads = ScriptedReads(
        reading(ChannelsSurface.ABSENT), RuntimeError("the grab raised")
    )
    fake = Fake()

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.CLOSED
    assert result.read is None and result.capture is None
    assert result.refused_stage == "capture"
    assert "RuntimeError: the grab raised" in result.refused
    assert fake.calls.count("dismiss") == 1


def test_a_non_acquisition_close_failure_keeps_the_read_and_is_not_retried():
    captured = evidence()
    reads = ScriptedReads(reading(ChannelsSurface.ABSENT), reading(capture=captured))
    fake = Fake(close_error=RuntimeError("the walker raised"))

    result = run(fake, reads)

    assert result.outcome is InspectionOutcome.UNCONFIRMED
    assert result.capture is captured
    assert result.closed is None
    assert any("RuntimeError: the walker raised" in note for note in result.notes)
    assert fake.calls.count("dismiss") == 1
