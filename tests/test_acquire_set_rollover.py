"""The guarded rolling setter: offline, real workflow, real capture fixtures.

The popup shape is the same projected 8-band settings surface the reader's own tests use, so the
rollover toggle is the third attributed toggle (hwnd 1002, rect (213, 76, 367, 94)) and the Enable
toggle is the second. The rolling evidence is the operator's **real** recorded ON/OFF pair. The
double replaces only the Win32 layer, so "one press on the rollover toggle" and "zero presses" are
measurements; its ``__getattr__`` makes any reach for ``press_mode_toggle`` a failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_acquire_channels_read import SETTINGS_ROWS, WINDOW, _roles

from udv_echo_process.acquire import mode_marks, set_rollover
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.channels_capture import (
    digest as frame_digest,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.set_rollover import (
    PopupClosure,
    Rolling,
    SetRolloverStage,
    acquire_set_rollover,
)
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import (
    ChannelsRead,
    ChannelsSurface,
    resolve_channels,
)
from udv_echo_process.acquire.ui.layout import observation_of
from udv_echo_process.cli import acquire_main

pytest.importorskip("PIL", reason="the acquire extra decodes the recorded fixtures")

DATA = Path(__file__).parent / "data" / "mpx-mode"
ON = DATA / "disabled-rolling-on"
OFF = DATA / "disabled-rolling-off"

ROLLOVER_HWND = 1002
ENABLE_HWND = 1028


def _pair(directory: Path) -> tuple[str, ...]:
    return tuple(str(directory / name) for name in mode_marks.PAIR_FILES)


def _live_mark(directory: Path) -> mode_marks.ModeMarkAttribution:
    paths = _pair(directory)
    digests = tuple(frame_digest(mode_marks.load_frame(path)) for path in paths)
    return mode_marks.attribute_frames(paths, digests, context="live-bracketed")


def _guard(label: str, *, foreground: bool | None = True) -> WindowGuard:
    return WindowGuard(
        label=label,
        hwnd=WINDOW,
        foreground=foreground,
        minimized=False,
        popup_hwnd=1000,
    )


def _report(
    directory: Path | None = ON,
    *,
    rows: tuple[tuple, ...] = SETTINGS_ROWS,
    retained: bool = False,
    foreground: bool | None = True,
) -> ChannelsRead:
    read = resolve_channels(observation_of(_roles(rows)))
    if directory is None:
        return read
    mark = (
        mode_marks.attribute_capture(directory) if retained else _live_mark(directory)
    )
    evidence = CaptureEvidence(
        status="ok",
        captured=True,
        stable=True,
        directory=str(directory),
        guards=GuardComparison(
            before=_guard("settings", foreground=foreground),
            after=_guard("settings-close", foreground=foreground),
            consistent=True,
        ),
        numeric=NumericBracketing(consistent=True),
        visual_mode_mark=mark,
    )
    return read.model_copy(update={"capture": evidence})


class FakeRolloverActuator:
    """The Win32 surface only: one binding, one narrow rollover press, open/close, counters."""

    def __init__(
        self,
        *,
        press_error: Exception | None = None,
        on_press=None,
        strip_states: list[StripState] | None = None,
    ) -> None:
        self.press_error = press_error
        self.on_press = on_press
        self.strip_states = list(strip_states or [])
        self.presses: list[int] = []
        self.press_rects: list[tuple[int, int, int, int] | None] = []
        self.opens = 0
        self.closes = 0
        self.warnings: list[str] = []
        self._target: WindowTarget | None = None

    def bind_target(self, hwnd: int) -> WindowTarget:
        self._target = WindowTarget(
            hwnd=int(hwnd), thread_id=11, process_id=22, class_name="TMain_Scr"
        )
        return self._target

    def verify_bound_target(self, target: WindowTarget) -> WindowTarget:
        assert self._target == target
        return target

    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self):
        return None

    def strip_state(self) -> StripState:
        if self.strip_states:
            return self.strip_states.pop(0)
        return StripState(button_count=3)

    def open_channels_popup(self, **kwargs) -> ChannelsOpen:
        self.opens += 1
        return ChannelsOpen(
            outcome=PopupOutcome.OPEN,
            surface=ChannelsSurface.SETTINGS_POPUP.value,
            readable=True,
            point=(10, 20),
            reads=1,
        )

    def dismiss_channels_popup(self, **kwargs) -> ChannelsDismissal:
        self.closes += 1
        return ChannelsDismissal(
            outcome=DismissalOutcome.ABSENT,
            point=(0, 0),
            surface_before=ChannelsSurface.SETTINGS_POPUP.value,
            surface_after=ChannelsSurface.ABSENT.value,
            reads=1,
        )

    def press_rollover_toggle(
        self,
        *,
        target: WindowTarget,
        popup_hwnd: int,
        toggle_hwnd: int,
        toggle_rect=None,
    ) -> None:
        assert self._target == target
        assert popup_hwnd == 1000
        if self.on_press is not None:
            self.on_press(self)
        if self.press_error is not None:
            raise self.press_error
        self.presses.append(int(toggle_hwnd))
        self.press_rects.append(toggle_rect)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the rolling setter reached {name!r}")


def _run(
    tmp_path,
    live=None,
    *,
    captures: list[ChannelsRead] | None = None,
    reads: list[ChannelsRead] | None = None,
    **kwargs,
):
    capture_reads = list(captures or [_report(ON), _report(ON), _report(ON)])
    read_reads = list(
        reads
        or [
            ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False),
            ChannelsRead(surface=ChannelsSurface.SETTINGS_POPUP, readable=True),
        ]
    )

    def capture_popup(*_args, **_kwargs):
        if not capture_reads:
            raise AssertionError(
                "a capture was taken where the workflow must take none"
            )
        return capture_reads.pop(0)

    def read_popup(*_args, **_kwargs):
        if not read_reads:
            raise AssertionError("a read was taken where the workflow must take none")
        return read_reads.pop(0)

    params = {
        "requested": "on",
        "expect": "off",
        "baseline": "off",
        "capture_dir": tmp_path / "captures",
        "trial_record": tmp_path / "trial.json",
        "actuator": live or FakeRolloverActuator(),
        "enumerate_windows": lambda: (WINDOW,),
        "capture_popup": capture_popup,
        "read_popup": read_popup,
    }
    params.update(kwargs)
    return acquire_set_rollover(**params)


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# one press, on the rollover row, only after a durable pending claim
# ---------------------------------------------------------------------------------------------


def test_one_press_on_the_rollover_toggle_with_nested_capture_evidence(
    tmp_path,
) -> None:
    live = FakeRolloverActuator()
    result = _run(tmp_path, live, captures=[_report(OFF), _report(OFF), _report(ON)])
    assert live.presses == [ROLLOVER_HWND]
    assert result.stage is SetRolloverStage.PRESSED
    assert result.presses == 1 and result.posted == "unknown"
    assert (
        result.decision is not None
        and result.final is not None
        and result.post is not None
    )
    assert result.decision.visual_mode_mark.rolling == "OFF_PROVEN"
    assert result.final.visual_mode_mark.rolling == "OFF_PROVEN"
    assert result.post_rolling == "ON_PROVEN"
    assert not hasattr(result, "old_rolling") and not hasattr(result, "final_rolling")
    assert live.opens == 1 and live.closes == 1
    assert result.popup_left_open is False
    assert any("separate invocation" in owed for owed in result.restoration_owed)


def test_the_pending_record_exists_before_the_press(tmp_path) -> None:
    seen: dict = {}
    live = FakeRolloverActuator(on_press=lambda _live: seen.update(_record(tmp_path)))
    _run(tmp_path, live, captures=[_report(OFF), _report(OFF), _report(ON)])
    assert seen["phase"] == "pending"
    assert seen["press"] == "not_attempted"
    assert seen["presses"] == 0
    assert seen["baseline"] == "off"
    assert seen["decision_rolling"] == "OFF_PROVEN"
    assert seen["hover_attempted"] is True
    assert "as of that write" in seen["press_state_as_of"]
    record = _record(tmp_path)
    assert record["phase"] == "after"
    assert record["presses"] == 1


# ---------------------------------------------------------------------------------------------
# refusals before any press: wrong control, geometry, order, retained, foreground
# ---------------------------------------------------------------------------------------------


def test_the_enable_toggle_is_never_the_rollover_target(tmp_path) -> None:
    live = FakeRolloverActuator()
    rows = tuple(
        (hwnd, parent, cls, (9, 36, 138, 68) if hwnd == ROLLOVER_HWND else rect, text)
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )
    with pytest.raises(AcquisitionError, match="Roll over|rollover|own"):
        _run(tmp_path, live, captures=[_report(OFF, rows=rows)] * 2)
    assert live.presses == []
    assert live.closes == 1  # the popup this command opened is still closed


def test_an_oversized_rect_that_reaches_other_rows_refuses(tmp_path) -> None:
    live = FakeRolloverActuator()
    rows = tuple(
        (hwnd, parent, cls, (0, 0, 393, 426) if hwnd == ROLLOVER_HWND else rect, text)
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )
    with pytest.raises(
        AcquisitionError, match="full settings surface|reaches into|own"
    ):
        _run(tmp_path, live, captures=[_report(OFF, rows=rows)] * 2)
    assert live.presses == []


def test_bind_rollover_refuses_a_rect_that_reaches_the_enable_line() -> None:
    from udv_echo_process.acquire.ui.channels import bind_rollover_toggle

    base = _report(None)
    toggles = list(base.toggles)
    toggles[2] = toggles[2].model_copy(update={"rect": (9, 36, 367, 110)})
    report = base.model_copy(update={"toggles": tuple(toggles)})
    with pytest.raises(AcquisitionError, match="reaches into|own"):
        bind_rollover_toggle(report)


def test_two_controls_owning_the_rollover_row_refuse() -> None:
    from udv_echo_process.acquire.ui.channels import bind_rollover_toggle

    base = _report(None)
    toggles = list(base.toggles)
    toggles[0] = toggles[0].model_copy(update={"rect": (213, 76, 367, 94)})
    report = base.model_copy(update={"toggles": tuple(toggles)})
    with pytest.raises(AcquisitionError, match="own"):
        bind_rollover_toggle(report)


def test_retained_evidence_is_not_a_licence(tmp_path) -> None:
    live = FakeRolloverActuator()
    with pytest.raises(AcquisitionError, match="live-bracketed|retained|not a fresh"):
        _run(tmp_path, live, captures=[_report(OFF, retained=True)] * 2)
    assert live.presses == []
    assert not (tmp_path / "trial.json").exists()
    assert live.closes == 1


def test_a_foreground_that_is_not_proven_refuses(tmp_path) -> None:
    live = FakeRolloverActuator()
    with pytest.raises(AcquisitionError, match="foreground"):
        _run(tmp_path, live, captures=[_report(OFF, foreground=None)] * 2)
    assert live.presses == []
    assert not (tmp_path / "trial.json").exists()


def test_an_already_open_popup_is_refused_without_a_hover(tmp_path) -> None:
    live = FakeRolloverActuator()
    open_popup = resolve_channels(observation_of(_roles(SETTINGS_ROWS)))
    with pytest.raises(AcquisitionError, match="adopt_open=False|already open"):
        _run(
            tmp_path,
            live,
            reads=[open_popup, open_popup],
            captures=[_report(OFF)],
        )
    assert live.presses == []
    assert live.opens == 0
    assert live.closes == 0
    assert not (tmp_path / "trial.json").exists()


# ---------------------------------------------------------------------------------------------
# mid-flight refusal, unknown post, raised press and a failed rewrite
# ---------------------------------------------------------------------------------------------


def test_a_recording_started_at_the_boundary_refuses_with_a_refused_record(
    tmp_path,
) -> None:
    live = FakeRolloverActuator(
        strip_states=[StripState(button_count=3), StripState(button_count=1)]
    )
    with pytest.raises(AcquisitionError, match="recording|ready"):
        _run(tmp_path, live, captures=[_report(OFF), _report(OFF)])
    assert live.presses == []
    record = _record(tmp_path)
    assert record["phase"] == "refused"
    assert record["press"] == "not_attempted"
    assert record["obligation_open"] is False
    assert live.closes == 1


def test_an_absent_post_surface_leaves_the_rolling_state_unknown(tmp_path) -> None:
    empty = ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)
    result = _run(
        tmp_path,
        captures=[_report(OFF), _report(OFF), _report(ON)],
        reads=[empty, empty],
    )
    assert result.presses == 1
    assert result.post is None
    assert result.post_rolling == "UNKNOWN"
    assert "UNKNOWN" in result.post_error


def test_a_raised_press_is_unknown_delivery_not_a_no_action(tmp_path) -> None:
    live = FakeRolloverActuator(press_error=RuntimeError("post failed"))
    result = _run(tmp_path, live, captures=[_report(OFF), _report(OFF)])
    assert result.stage is SetRolloverStage.PRESS_RAISED
    assert result.presses == 1 and result.posted == "unknown"
    assert "whether any message reached" in result.press_error
    assert _record(tmp_path)["press_error"]


def test_a_failed_rewrite_after_the_press_keeps_the_pending_record(
    tmp_path, monkeypatch
) -> None:
    def fail(_file, _payload):
        return "disk full"

    monkeypatch.setattr(set_rollover, "update_trial_record", fail)
    live = FakeRolloverActuator()
    result = _run(tmp_path, live, captures=[_report(OFF), _report(OFF), _report(ON)])
    assert result.presses == 1
    assert result.trial_record_phase == "pending"
    assert "disk full" in result.trial_record_error
    record = _record(tmp_path)
    assert record["phase"] == "pending"
    assert record["press"] == "not_attempted"
    assert "as of that write" in record["press_state_as_of"]


# ---------------------------------------------------------------------------------------------
# no-op and the baseline rule
# ---------------------------------------------------------------------------------------------


def test_requested_equals_expect_is_a_zero_press_noop_without_a_record(
    tmp_path,
) -> None:
    live = FakeRolloverActuator()
    result = _run(
        tmp_path,
        live,
        requested="off",
        expect="off",
        baseline="off",
        captures=[_report(OFF)],
        reads=[ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)],
    )
    assert result.stage is SetRolloverStage.NOOP
    assert result.presses == 0 and result.posted == "not_attempted"
    assert result.decision is not None
    assert result.trial_record is None
    assert not (tmp_path / "trial.json").exists()
    assert live.presses == []
    assert live.closes == 1 and result.popup_left_open is False


def test_a_restore_invocation_keeps_the_trials_declared_baseline(tmp_path) -> None:
    result = _run(
        tmp_path,
        requested="off",
        expect="on",
        baseline="off",
        captures=[_report(ON), _report(ON), _report(OFF)],
    )
    assert result.restoration_owed == ()
    assert _record(tmp_path)["baseline"] == "off"
    assert _record(tmp_path)["requested"] == "off"


def test_a_literal_vocabulary_is_checked_before_any_gesture(tmp_path) -> None:
    live = FakeRolloverActuator()
    with pytest.raises(AcquisitionError, match="literal"):
        _run(tmp_path, live, requested="maybe")
    assert live.opens == 0 and live.presses == []


def test_the_action_boundary_presses_only_the_attributed_rollover_toggle() -> None:
    from test_acquire_enable_multiplexed import _boundary

    from udv_echo_process.acquire.udop import recording

    target = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )
    surface = _boundary(recording, target)
    recording.RecordingSurface.press_rollover_toggle(
        surface, target=target, popup_hwnd=1000, toggle_hwnd=ROLLOVER_HWND
    )
    assert surface.pressed == [ROLLOVER_HWND]

    # The Enable toggle is a TSp_Button child of the same popup, and is not this row.
    with pytest.raises(AcquisitionError, match="Roll over the channels|own"):
        recording.RecordingSurface.press_rollover_toggle(
            surface, target=target, popup_hwnd=1000, toggle_hwnd=ENABLE_HWND
        )

    # A rect that moved since the licence is refused before anything is posted.
    with pytest.raises(AcquisitionError, match="moved|licensed"):
        recording.RecordingSurface.press_rollover_toggle(
            surface,
            target=target,
            popup_hwnd=1000,
            toggle_hwnd=ROLLOVER_HWND,
            toggle_rect=(0, 0, 10, 10),
        )


def test_the_rollover_setter_never_uses_the_mode_toggle_entry_point() -> None:
    from udv_echo_process.acquire.udop.recording import RecordingSurface

    assert hasattr(RecordingSurface, "press_rollover_toggle")
    assert not hasattr(RecordingSurface, "press_any_control")
    source = Path(set_rollover.__file__).read_text(encoding="utf-8")
    assert "press_mode_toggle" not in source


# ---------------------------------------------------------------------------------------------
# the CLI never reports success without a verified post
# ---------------------------------------------------------------------------------------------


def _patch_cli(monkeypatch, result) -> None:
    monkeypatch.setattr(set_rollover, "acquire_set_rollover", lambda **kwargs: result)
    monkeypatch.setattr("udv_echo_process.cli.set_rollover", set_rollover)


def _cli_result(monkeypatch, tmp_path, **overrides):
    base = {
        "stage": SetRolloverStage.PRESSED,
        "requested": Rolling.ON,
        "expect": Rolling.OFF,
        "baseline": Rolling.OFF,
        "bound_target": WindowTarget(
            hwnd=WINDOW, thread_id=1, process_id=2, class_name="TMain_Scr"
        ),
        "presses": 1,
        "press": "attempted",
        "posted": "unknown",
        "post_rolling": "UNKNOWN",
        "trial_record_phase": "after",
    }
    base.update(overrides)
    return set_rollover.SetRolloverResult(**base)


def _cli_run(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        acquire_main(
            [
                "set-rollover",
                "--requested",
                "on",
                "--expect",
                "off",
                "--baseline",
                "off",
                "--capture-dir",
                str(tmp_path),
                "--trial-record",
                str(tmp_path / "t.json"),
                "--json",
            ]
        )
    return excinfo.value.code


def test_cli_exits_one_when_the_post_rolling_state_is_unknown(
    tmp_path, monkeypatch
) -> None:
    _patch_cli(monkeypatch, _cli_result(monkeypatch, tmp_path))
    assert _cli_run(tmp_path) == 1


def test_cli_exits_zero_only_on_a_fresh_verified_post(tmp_path, monkeypatch) -> None:
    evidence = _report(ON).capture
    _patch_cli(
        monkeypatch,
        _cli_result(
            monkeypatch,
            tmp_path,
            post_rolling="ON_PROVEN",
            post=evidence,
        ),
    )
    assert _cli_run(tmp_path) == 0


# ---------------------------------------------------------------------------------------------
# the declaration still owes its restoration when nothing was pressed
# ---------------------------------------------------------------------------------------------


def test_a_noop_still_owes_the_declared_baseline_restoration(tmp_path) -> None:
    """``requested == expect`` presses nothing, but it does not erase what the trial owes."""
    live = FakeRolloverActuator()
    result = _run(
        tmp_path,
        live,
        requested="on",
        expect="on",
        baseline="off",
        captures=[_report(ON)],
        reads=[ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)],
    )
    assert result.stage is SetRolloverStage.NOOP
    assert result.presses == 0 and live.presses == []
    assert result.restoration_owed, (
        "a no-op that leaves the baseline unreached owes the undo"
    )
    assert "--requested off --baseline off" in result.restoration_owed[0]
    assert result.trial_record is None
    assert not (tmp_path / "trial.json").exists()


# ---------------------------------------------------------------------------------------------
# timing bounds: validated before the first read, hover, claim or press
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_boundary_seconds": float("nan")},
        {"max_boundary_seconds": float("inf")},
        {"max_boundary_seconds": -0.5},
        {"max_boundary_seconds": 0.0},
        {"max_boundary_seconds": True},
        {"settle_s": float("nan")},
        {"settle_s": float("-inf")},
        {"settle_s": -1.0},
        {"settle_s": True},
        {"settle_s": "3"},
    ],
)
def test_a_nonfinite_or_negative_timing_is_refused_before_any_gesture(
    tmp_path, overrides
) -> None:
    live = FakeRolloverActuator()
    enumerated: list[int] = []

    def capture_popup(*_args, **_kwargs):
        raise AssertionError(
            "a capture was taken before the timing bounds were validated"
        )

    def read_popup(*_args, **_kwargs):
        raise AssertionError("a read was taken before the timing bounds were validated")

    with pytest.raises(
        AcquisitionError, match="finite|positive|non-negative|not a number"
    ):
        acquire_set_rollover(
            requested="on",
            expect="off",
            baseline="off",
            capture_dir=tmp_path / "captures",
            trial_record=tmp_path / "trial.json",
            actuator=live,
            enumerate_windows=lambda: (enumerated.append(1), (WINDOW,))[1],
            capture_popup=capture_popup,
            read_popup=read_popup,
            **overrides,
        )
    assert enumerated == []
    assert live.opens == 0 and live.closes == 0 and live.presses == []
    assert not (tmp_path / "trial.json").exists()


# ---------------------------------------------------------------------------------------------
# the close contract: an owned popup must be observed ABSENT; adopt policy is the only exemption
# ---------------------------------------------------------------------------------------------


def _open_report() -> ChannelsRead:
    return resolve_channels(observation_of(_roles(SETTINGS_ROWS)))


def test_an_adopted_popup_is_left_open_by_policy_and_still_settles(tmp_path) -> None:
    live = FakeRolloverActuator()
    result = _run(
        tmp_path,
        live,
        adopt_open=True,
        requested="off",
        expect="off",
        baseline="off",
        captures=[_report(OFF)],
        reads=[_open_report()],
    )
    assert live.opens == 0 and live.closes == 0
    assert result.opened is not None and result.opened.adopted is True
    assert result.hover_attempted is False
    assert result.popup_closure is PopupClosure.ADOPTED_LEFT_OPEN
    assert result.popup_closure.settled is True
    assert result.popup_left_open is True


def test_an_adopted_popup_asked_closed_must_be_observed_absent(tmp_path) -> None:
    def unproven_close(**_kwargs) -> ChannelsDismissal:
        return ChannelsDismissal(
            outcome=DismissalOutcome.UNKNOWN,
            point=(0, 0),
            surface_before=ChannelsSurface.SETTINGS_POPUP.value,
            surface_after=ChannelsSurface.SETTINGS_POPUP.value,
            reads=2,
        )

    result = _run(
        tmp_path,
        FakeRolloverActuator(),
        adopt_open=True,
        close_adopted=True,
        requested="off",
        expect="off",
        baseline="off",
        captures=[_report(OFF)],
        reads=[_open_report()],
        close_popup=unproven_close,
    )
    assert result.popup_closure is PopupClosure.ADOPTED_UNCLOSED
    assert result.popup_closure.settled is False


def test_an_adopted_popup_asked_closed_and_observed_absent_settles(tmp_path) -> None:
    live = FakeRolloverActuator()
    result = _run(
        tmp_path,
        live,
        adopt_open=True,
        close_adopted=True,
        requested="off",
        expect="off",
        baseline="off",
        captures=[_report(OFF)],
        reads=[_open_report()],
    )
    assert live.closes == 1
    assert result.popup_closure is PopupClosure.ADOPTED_CLOSED
    assert result.popup_closure.settled is True


def test_an_owned_close_that_raises_leaves_the_invocation_unsettled(tmp_path) -> None:
    def raising_close(**_kwargs):
        raise RuntimeError("close failed")

    result = _run(
        tmp_path,
        FakeRolloverActuator(),
        captures=[_report(OFF), _report(OFF), _report(ON)],
        close_popup=raising_close,
    )
    assert result.presses == 1
    assert result.post_rolling == "ON_PROVEN"
    assert result.closed is None
    assert result.popup_closure is PopupClosure.OWNED_LEFT_OPEN
    assert result.popup_closure.settled is False


def test_an_owned_close_read_back_as_a_popup_is_not_a_close(tmp_path) -> None:
    def still_up(**_kwargs) -> ChannelsDismissal:
        return ChannelsDismissal(
            outcome=DismissalOutcome.UNKNOWN,
            point=None,
            surface_before=ChannelsSurface.SETTINGS_POPUP.value,
            surface_after=ChannelsSurface.SETTINGS_POPUP.value,
            reads=3,
        )

    result = _run(
        tmp_path,
        FakeRolloverActuator(),
        requested="off",
        expect="off",
        baseline="off",
        captures=[_report(OFF)],
        reads=[ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)],
        close_popup=still_up,
    )
    assert result.popup_closure is PopupClosure.OWNED_LEFT_OPEN
    assert result.popup_left_open is True


@pytest.mark.parametrize(
    ("closure", "expected"),
    [
        (PopupClosure.OWNED_CLOSED, 0),
        (PopupClosure.OWNED_LEFT_OPEN, 1),
        (PopupClosure.ADOPTED_LEFT_OPEN, 0),
    ],
)
def test_cli_noop_requires_a_settled_close(
    tmp_path, monkeypatch, closure, expected
) -> None:
    _patch_cli(
        monkeypatch,
        _cli_result(
            monkeypatch,
            tmp_path,
            stage=SetRolloverStage.NOOP,
            presses=0,
            press="not_attempted",
            posted="not_attempted",
            trial_record_phase="",
            popup_closure=closure,
        ),
    )
    assert _cli_run(tmp_path) == expected


def test_cli_exits_one_when_a_verified_post_cannot_prove_the_close(
    tmp_path, monkeypatch
) -> None:
    evidence = _report(ON).capture
    _patch_cli(
        monkeypatch,
        _cli_result(
            monkeypatch,
            tmp_path,
            post_rolling="ON_PROVEN",
            post=evidence,
            popup_closure=PopupClosure.OWNED_LEFT_OPEN,
        ),
    )
    assert _cli_run(tmp_path) == 1


def test_cli_settles_a_verified_post_whose_adopted_popup_stayed_open_by_policy(
    tmp_path, monkeypatch
) -> None:
    evidence = _report(ON).capture
    _patch_cli(
        monkeypatch,
        _cli_result(
            monkeypatch,
            tmp_path,
            post_rolling="ON_PROVEN",
            post=evidence,
            popup_closure=PopupClosure.ADOPTED_LEFT_OPEN,
        ),
    )
    assert _cli_run(tmp_path) == 0


# ---------------------------------------------------------------------------------------------
# the durable record keeps the decision rect and the boundary rect apart
# ---------------------------------------------------------------------------------------------


def _moved_rollover_rows() -> tuple[tuple, ...]:
    return tuple(
        (hwnd, parent, cls, (212, 76, 368, 94) if hwnd == ROLLOVER_HWND else rect, text)
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )


def test_the_boundary_rect_and_the_decision_rect_stay_separate(tmp_path) -> None:
    live = FakeRolloverActuator()
    result = _run(
        tmp_path,
        live,
        captures=[
            _report(OFF),
            _report(OFF, rows=_moved_rollover_rows()),
            _report(ON),
        ],
    )
    assert result.decision_rect == (213, 76, 367, 94)
    assert result.boundary_rect == (212, 76, 368, 94)
    assert live.press_rects == [(212, 76, 368, 94)]
    record = _record(tmp_path)
    assert record["decision_toggle_rect"] == [213, 76, 367, 94]
    assert record["boundary_toggle_rect"] == [212, 76, 368, 94]
    assert record["phase"] == "after"
