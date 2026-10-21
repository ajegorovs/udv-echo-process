"""The guarded Enable-multiplexer press: offline, real workflow, real capture fixtures.

The popup shape is the projected 8-band settings surface the reader's own tests use. The mode
evidence is the operator's **real** recorded popup pair from ``tests/data/mpx-mode/`` — the
rolling-ON pair is the only one that may proceed; the rolling-OFF pair is the hazard case and must
refuse with zero presses. The double replaces only the Win32 layer and counts every press, so
"exactly one press on the Enable toggle" and "zero presses" are measurements.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from test_acquire_channels_read import SETTINGS_ROWS, WINDOW, _roles

from udv_echo_process.acquire import enable_multiplexed, mode_marks
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    FrameEvidence,
    FrameStats,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.channels_capture import (
    digest as frame_digest,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.enable_multiplexed import (
    EnableStage,
    acquire_enable_multiplexed,
)
from udv_echo_process.acquire.ui.channels import (
    ChannelsRead,
    ChannelsSurface,
    resolve_channels,
)
from udv_echo_process.acquire.ui.layout import observation_of
from udv_echo_process.cli import acquire_main

DATA = Path(__file__).parent / "data" / "mpx-mode"
ON = DATA / "disabled-rolling-on"
OFF = DATA / "disabled-rolling-off"

#: The Enable toggle in the projected shape: the second attributed toggle (hwnd 1028).
ENABLE_HWND = 1028


pytest.importorskip("PIL", reason="the acquire extra decodes the recorded fixtures")


def _pair(directory: Path) -> tuple[str, ...]:
    return tuple(str(directory / name) for name in mode_marks.PAIR_FILES)


def _live_mark(directory: Path) -> mode_marks.ModeMarkAttribution:
    paths = _pair(directory)
    digests = tuple(frame_digest(mode_marks.load_frame(path)) for path in paths)
    return mode_marks.attribute_frames(paths, digests, context="live-bracketed")


def _report(
    directory: Path | None = ON,
    *,
    rows: tuple[tuple, ...] = SETTINGS_ROWS,
    retained: bool = False,
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
        guards=GuardComparison(before=WindowGuard(label="settings")),
        numeric=NumericBracketing(consistent=True),
        visual_mode_mark=mark,
    )
    return read.model_copy(update={"capture": evidence})


class FakeEnableActuator:
    """The Win32 surface only: one binding, one narrow press, counters."""

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

    def press_mode_toggle(
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

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the enable command reached {name!r}")


def _run(
    tmp_path,
    live=None,
    *,
    reads: list[ChannelsRead] | None = None,
    post: ChannelsRead | None = None,
    post_capture: ChannelsRead | None = None,
    **kwargs,
):
    capture_reads = list(reads or [_report(), _report()])
    post_read = (
        post
        if post is not None
        else ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)
    )

    def capture_popup(*_args, **_kwargs):
        if capture_reads:
            return capture_reads.pop(0)
        if post_capture is not None:
            return post_capture
        raise AssertionError("a capture was taken where the workflow must take none")

    params = {
        "capture_dir": tmp_path / "captures",
        "trial_record": tmp_path / "trial.json",
        "actuator": live or FakeEnableActuator(),
        "enumerate_windows": lambda: (WINDOW,),
        "capture_popup": capture_popup,
        "read_popup": lambda *a, **k: post_read,
    }
    params.update(kwargs)
    return acquire_enable_multiplexed(**params)


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# the one press
# ---------------------------------------------------------------------------------------------


def test_exactly_one_press_on_the_enable_toggle_and_nothing_else(tmp_path) -> None:
    live = FakeEnableActuator()
    result = _run(tmp_path, live)
    assert live.presses == [ENABLE_HWND]
    assert result.presses == 1 and result.posted == "unknown"
    assert result.stage is EnableStage.PRESSED
    assert result.target_hwnd == ENABLE_HWND
    assert result.target_attribution == "Enable multiplexer"
    assert result.old_mode == "VISUAL_DISABLED"
    assert result.old_rolling == "ON_PROVEN"
    assert result.old_context == "live-bracketed"
    assert result.old_integrity == "capture-digest-verified"
    assert result.old_frame_digests is not None
    assert all(len(digest) == 64 for digest in result.old_frame_digests)


def test_the_obligation_is_on_disk_before_the_press_and_preserves_old_evidence(
    tmp_path,
) -> None:
    seen: dict = {}
    live = FakeEnableActuator(
        on_press=lambda _live: seen.update(_record(tmp_path)),
    )
    _run(tmp_path, live)
    assert seen["phase"] == "obligation"
    assert seen["old_rolling"] == "ON_PROVEN"
    assert seen["toggle_hwnd"] == ENABLE_HWND
    assert seen["scope"] == "one held press on the Enable toggle; nothing else"
    assert seen["presses"] == 0
    record = _record(tmp_path)
    assert record["phase"] == "after"
    assert record["old_frame_digests"] == list(seen["old_frame_digests"])


# ---------------------------------------------------------------------------------------------
# refusals: zero presses, no record
# ---------------------------------------------------------------------------------------------


def test_rolling_off_is_a_hazard_refused_with_zero_presses(tmp_path) -> None:
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="HAZARD"):
        _run(tmp_path, live, reads=[_report(OFF), _report(OFF)])
    assert live.presses == []
    assert not (tmp_path / "trial.json").exists()


def test_retained_evidence_is_not_a_permission(tmp_path) -> None:
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="live-bracketed|retained|not a fresh"):
        _run(
            tmp_path,
            live,
            reads=[_report(ON, retained=True), _report(ON, retained=True)],
        )
    assert live.presses == []


def test_a_missing_or_unverified_capture_refuses(tmp_path) -> None:
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="no capture|not ok|no mode attribution"):
        _run(tmp_path, live, reads=[_report(None), _report(None)])
    assert live.presses == []


def test_a_different_popup_signature_refuses(tmp_path) -> None:
    rows = tuple(row for row in SETTINGS_ROWS if row[0] != 1008)
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="signature|bands|full settings surface"):
        _run(tmp_path, live, reads=[_report(rows=rows)] * 2)
    assert live.presses == []


def test_an_extra_unattributed_toggle_refuses(tmp_path) -> None:
    rows = SETTINGS_ROWS + ((1040, 1000, "TSp_Button", (20, 250, 40, 280), ""),)
    live = FakeEnableActuator()
    with pytest.raises(
        AcquisitionError, match="signature|toggles|role|full settings surface"
    ):
        _run(tmp_path, live, reads=[_report(rows=rows)] * 2)
    assert live.presses == []


# ---------------------------------------------------------------------------------------------
# attempted vs delivered, and the post state
# ---------------------------------------------------------------------------------------------


def test_a_raised_press_leaves_posted_unknown_and_owes_confirmation(tmp_path) -> None:
    live = FakeEnableActuator(press_error=RuntimeError("post failed"))
    result = _run(tmp_path, live)
    assert result.stage is EnableStage.PRESS_RAISED
    assert result.posted == "unknown"
    assert result.presses == 1
    assert "whether any message reached" in result.press_error
    assert result.post_mode == "UNKNOWN"
    assert any("reopen" in owed for owed in result.restoration_owed)
    assert _record(tmp_path)["press_error"]


def test_a_consumed_popup_leaves_the_post_mode_unknown(tmp_path) -> None:
    result = _run(tmp_path)
    assert result.post_surface == "absent"
    assert result.post_mode == "UNKNOWN"
    assert "reopen Channels" in result.post_error
    assert result.post_frame_digests is None


# ---------------------------------------------------------------------------------------------
# the CLI never reports success without a verified enabled post-state
# ---------------------------------------------------------------------------------------------


def _patch_cli(monkeypatch, result) -> None:
    monkeypatch.setattr(
        enable_multiplexed, "acquire_enable_multiplexed", lambda **kwargs: result
    )
    monkeypatch.setattr("udv_echo_process.cli.enable_multiplexed", enable_multiplexed)


def _cli_result(**overrides):
    base = {
        "stage": EnableStage.PRESSED,
        "bound_target": WindowTarget(
            hwnd=WINDOW, thread_id=1, process_id=2, class_name="TMain_Scr"
        ),
        "presses": 1,
        "press": "attempted",
        "posted": "unknown",
        "post_mode": "UNKNOWN",
        "restoration_owed": ("reopen Channels",),
    }
    base.update(overrides)
    return enable_multiplexed.EnableMultiplexedResult(**base)


def test_cli_exits_nonzero_when_the_post_mode_is_unknown(
    tmp_path, monkeypatch, capsys
) -> None:
    _patch_cli(monkeypatch, _cli_result())
    with pytest.raises(SystemExit) as excinfo:
        acquire_main(
            [
                "enable-multiplexed",
                "--capture-dir",
                str(tmp_path),
                "--trial-record",
                str(tmp_path / "t.json"),
                "--json",
            ]
        )
    assert excinfo.value.code == 1


def test_cli_exits_zero_only_on_a_verified_enabled_post(tmp_path, monkeypatch) -> None:
    _patch_cli(
        monkeypatch,
        _cli_result(
            post_mode="VISUAL_ENABLED",
            post_frame_digests=("a" * 64, "b" * 64),
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        acquire_main(
            [
                "enable-multiplexed",
                "--capture-dir",
                str(tmp_path),
                "--trial-record",
                str(tmp_path / "t.json"),
                "--json",
            ]
        )
    assert excinfo.value.code == 0


def test_the_action_boundary_is_a_narrow_named_entry_point() -> None:
    from udv_echo_process.acquire.udop.recording import RecordingSurface

    assert hasattr(RecordingSurface, "press_mode_toggle")
    assert not hasattr(RecordingSurface, "press_any_control")


# ---------------------------------------------------------------------------------------------
# the action boundary: role re-resolution, one held press, no generic handle press
# ---------------------------------------------------------------------------------------------


def _boundary(recording, target, *, rows=SETTINGS_ROWS, classes=None, parents=None):
    roles = _roles(rows)
    class_map = {row[0]: row[2] for row in rows}
    parent_map = {**roles["parent_of"], **(parents or {})}
    class_map.update(classes or {})
    recording._class_of = lambda hwnd: class_map.get(hwnd, "")
    recording._parent_of = lambda hwnd: parent_map.get(hwnd)
    by_hwnd = {row["hwnd"]: row["text"] for row in roles["raw"]}

    class Surface:
        _target = target
        pressed: ClassVar[list[int]] = []

        @property
        def last_roles(self):
            return roles

        def screen_fingerprint(self):
            return SimpleNamespace(hwnd=WINDOW)

        def verify_bound_target(self, asked):
            assert asked == target
            return asked

        def _get_text(self, hwnd):
            return by_hwnd.get(hwnd, "")

        def _main_hwnd(self):
            return target.hwnd

        def _click_hold(self, hwnd):
            self.pressed.append(hwnd)

    return Surface()


def test_the_action_boundary_presses_only_the_attributed_enable_toggle() -> None:
    from udv_echo_process.acquire.udop import recording

    target = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )
    surface = _boundary(recording, target)
    recording.RecordingSurface.press_mode_toggle(
        surface, target=target, popup_hwnd=1000, toggle_hwnd=ENABLE_HWND
    )
    assert surface.pressed == [ENABLE_HWND]

    # The other toggle role is not the Enable control, even though it is a TSp_Button child.
    with pytest.raises(AcquisitionError, match="Enable multiplexer"):
        recording.RecordingSurface.press_mode_toggle(
            surface, target=target, popup_hwnd=1000, toggle_hwnd=1001
        )
    assert surface.pressed == [ENABLE_HWND]

    # A changed band signature has no established Enable role: no press.
    broken = tuple(row for row in SETTINGS_ROWS if row[0] != 1008)
    surface = _boundary(recording, target, rows=broken)
    with pytest.raises(AcquisitionError, match="settings surface|signature"):
        recording.RecordingSurface.press_mode_toggle(
            surface, target=target, popup_hwnd=1000, toggle_hwnd=ENABLE_HWND
        )
    assert surface.pressed == []


# ---------------------------------------------------------------------------------------------
# the boundary: the final capture after the durable claim, and the record that survives a refusal
# ---------------------------------------------------------------------------------------------


def _digested(report: ChannelsRead, digests: tuple[str, str]) -> ChannelsRead:
    """``report`` with forged capture-time digests, so the two pairs are tellable apart."""
    capture = report.capture
    assert capture is not None and capture.visual_mode_mark is not None
    mark = capture.visual_mode_mark.model_copy(update={"frame_digests": digests})
    return report.model_copy(
        update={"capture": capture.model_copy(update={"visual_mode_mark": mark})}
    )


def test_the_final_capture_is_taken_after_the_durable_claim(
    tmp_path, monkeypatch
) -> None:
    order: list[str] = []
    real_claim = enable_multiplexed.claim_trial_record

    def claim(file, payload):
        order.append("claim")
        real_claim(file, payload)

    def capture(*_args, **_kwargs):
        order.append(
            f"capture:{len([item for item in order if item.startswith('capture')]) + 1}"
        )
        return _report(ON)

    monkeypatch.setattr(enable_multiplexed, "claim_trial_record", claim)
    _run(tmp_path, capture_popup=capture)
    # The decision capture, then the durable obligation, then a NEW capture at the boundary: the
    # decision pair is never recycled into the licence.
    assert order == ["capture:1", "claim", "capture:2"]


def test_the_press_is_licensed_by_the_final_pair_and_both_pairs_are_recorded(
    tmp_path,
) -> None:
    decision = ("a" * 64, "b" * 64)
    licence = ("c" * 64, "d" * 64)
    result = _run(
        tmp_path,
        reads=[
            _digested(_report(ON), decision),
            _digested(_report(ON), licence),
        ],
    )
    assert result.old_frame_digests == decision
    assert result.final_frame_digests == licence
    record = _record(tmp_path)
    assert record["old_frame_digests"] == list(decision)
    assert record["final_frame_digests"] == list(licence)
    assert record["old_mode"] == "VISUAL_DISABLED"
    assert record["final_mode"] == "VISUAL_DISABLED"
    assert record["final_rolling"] == "ON_PROVEN"


def test_rolling_flipping_at_the_final_capture_refuses_with_zero_presses(
    tmp_path,
) -> None:
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="HAZARD"):
        _run(tmp_path, live, reads=[_report(ON), _report(OFF)])
    assert live.presses == []
    record = _record(tmp_path)
    # The obligation was already durable, so the record states the refusal — with the final pair
    # retained, no press, and nothing owed back to the operator.
    assert record["phase"] == "preflight_refused"
    assert record["presses"] == 0
    assert record["press"] == "not_attempted"
    assert record["posted"] == "not_attempted"
    assert record["press_error"] == ""
    assert record["restoration_owed"] == []
    assert record["old_rolling"] == "ON_PROVEN"
    assert record["final_rolling"] == "OFF_PROVEN"
    assert len(record["final_frame_digests"]) == 2
    assert record["boundary_error"]


def test_a_recording_that_starts_after_the_decision_refuses_at_the_boundary(
    tmp_path,
) -> None:
    live = FakeEnableActuator(
        strip_states=[
            StripState(button_count=3),
            StripState(button_count=1),
        ]
    )
    with pytest.raises(AcquisitionError, match="record|strip|button"):
        _run(tmp_path, live)
    assert live.presses == []
    record = _record(tmp_path)
    assert record["phase"] == "preflight_refused"
    assert record["press"] == "not_attempted"
    assert record["restoration_owed"] == []


def test_a_failing_final_capture_is_recorded_and_refuses(tmp_path) -> None:
    live = FakeEnableActuator()
    reads = [_report(ON), _report(None)]
    with pytest.raises(AcquisitionError, match="no capture|capture"):
        _run(tmp_path, live, reads=reads)
    assert live.presses == []
    record = _record(tmp_path)
    assert record["phase"] == "preflight_refused"
    assert record["boundary_error"]
    assert record["final_frame_digests"] == []


def test_no_invented_cap_but_a_caller_supplied_limit_refuses(tmp_path) -> None:
    live = FakeEnableActuator()
    ticks = iter([0.0, 9.0])
    with pytest.raises(AcquisitionError, match="caller allowed"):
        _run(tmp_path, live, clock=lambda: next(ticks), max_boundary_seconds=1.0)
    assert live.presses == []
    record = _record(tmp_path)
    assert record["phase"] == "preflight_refused"
    assert record["boundary_seconds"] == 9.0
    # The same nine seconds are only a diagnostic when the caller set no limit.
    (tmp_path / "uncapped").mkdir()
    ticks = iter([0.0, 9.0])
    ok = _run(tmp_path / "uncapped", clock=lambda: next(ticks))
    assert ok.presses == 1
    assert ok.boundary_seconds == 9.0


# ---------------------------------------------------------------------------------------------
# B2: the Enable target is bound by the measured row geometry, not by caption order
# ---------------------------------------------------------------------------------------------


def _rows_with(rows, hwnd: int, rect: tuple[int, int, int, int]):
    return tuple(
        (row[0], row[1], row[2], rect, *row[4:]) if row[0] == hwnd else row
        for row in rows
    )


def test_an_enable_caption_on_a_button_off_the_enable_line_refuses(tmp_path) -> None:
    # The band order — and so the caption — is unchanged, but the Enable-named button has been
    # moved right off the left margin of the line it is supposed to paint: caption order alone
    # would still press it.
    rows = _rows_with(SETTINGS_ROWS, 1028, (60, 36, 138, 68))
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="measured Enable band"):
        _run(tmp_path, live, reads=[_report(rows=rows)] * 2)
    assert live.presses == []


def test_an_enable_rect_out_of_the_measured_band_refuses(tmp_path) -> None:
    # The Enable-named button moved sideways off the measured line: no TSp_Button owns it.
    rows = _rows_with(SETTINGS_ROWS, 1028, (150, 36, 300, 68))
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="measured Enable band"):
        _run(tmp_path, live, reads=[_report(rows=rows)] * 2)
    assert live.presses == []


def test_an_enable_rect_reaching_the_rollover_mark_refuses(tmp_path) -> None:
    # A rect tall enough to cover both the Enable line and the rollover mark: it owns the label
    # band and the rollover row at once, so it is not a single row's control.
    rows = _rows_with(SETTINGS_ROWS, 1028, (9, 36, 230, 94))
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="rollover mark band"):
        _run(tmp_path, live, reads=[_report(rows=rows)] * 2)
    assert live.presses == []


def test_two_buttons_covering_the_enable_band_state_no_single_target() -> None:
    from udv_echo_process.acquire.ui.channels import bind_enable_toggle

    report = _report()
    toggles = tuple(
        toggle.model_copy(update={"rect": (9, 36, 138, 68)})
        if toggle.hwnd == 1003
        else toggle
        for toggle in report.toggles
    )
    with pytest.raises(
        AcquisitionError, match="own a rect in the measured Enable band"
    ):
        bind_enable_toggle(report.model_copy(update={"toggles": toggles}))


def test_the_bound_toggle_rect_is_popup_relative() -> None:
    from udv_echo_process.acquire.ui.channels import bind_enable_toggle

    placed = resolve_channels(observation_of(_roles(SETTINGS_ROWS, offset=(120, 40))))
    bound = bind_enable_toggle(placed)
    assert bound.hwnd == ENABLE_HWND
    assert bound.rect == (9, 36, 138, 68)


def test_the_action_boundary_requires_the_licensed_rect_exactly() -> None:
    from udv_echo_process.acquire.udop import recording

    target = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )
    pressed: list[int] = []
    surface = _boundary(recording, target)
    surface.pressed = pressed
    recording.RecordingSurface.press_mode_toggle(
        surface,
        target=target,
        popup_hwnd=1000,
        toggle_hwnd=ENABLE_HWND,
        toggle_rect=(9, 36, 138, 68),
    )
    assert pressed == [ENABLE_HWND]
    # The same handle and caption at a rect two pixels down: the control moved between the
    # licensing capture and the message, so nothing is posted.
    with pytest.raises(AcquisitionError, match="rect"):
        recording.RecordingSurface.press_mode_toggle(
            surface,
            target=target,
            popup_hwnd=1000,
            toggle_hwnd=ENABLE_HWND,
            toggle_rect=(9, 38, 138, 70),
        )
    assert pressed == [ENABLE_HWND]


# ---------------------------------------------------------------------------------------------
# the post state is never claimed
# ---------------------------------------------------------------------------------------------


def test_production_never_claims_an_enabled_mode_after_the_press(tmp_path) -> None:
    # The full settings popup is still up after the press: that is not the enabled entry shape,
    # and the two-capture list is exhausted, so any capture would raise. No mode is inferred.
    result = _run(tmp_path, post=_report(ON))
    assert result.presses == 1
    assert result.post_surface == "settings_popup"
    assert result.post_mode == "UNKNOWN"
    assert "not the clipped one-entry popup" in result.post_error
    assert result.post_frame_digests is None
    assert result.final_mode == "VISUAL_DISABLED"
    assert _record(tmp_path)["post_mode"] == "UNKNOWN"


def test_the_enable_band_is_the_true_letter_bounds_and_never_the_use_only_row(tmp_path):
    """The bind is held to the Enable line's measured letters, not to a caption ordinal."""
    from udv_echo_process.acquire import mode_marks

    assert mode_marks.ENABLE_LABEL_BAND == (29, 48, 138, 61)
    assert mode_marks.LABEL_BANDS[mode_marks.SETTINGS_FULL] == (
        mode_marks.ENABLE_LABEL_BAND
    )
    assert mode_marks.ENABLE_LABEL_BAND != mode_marks.USE_ONLY_CHANNEL_BAND
    # A control that owns only the Use only channel row does not contain the Enable letters, and a
    # control one pixel left of them does not either: the bind has no ordinal fallback.
    from udv_echo_process.acquire.ui.channels import _contains

    use_only_rect = (
        29,
        14,
        138,
        28,
    )  # a control covering the Use only channel row only
    assert _contains(use_only_rect, mode_marks.USE_ONLY_CHANNEL_BAND)
    assert not _contains(use_only_rect, mode_marks.ENABLE_LABEL_BAND)
    assert not _contains((30, 36, 138, 68), mode_marks.ENABLE_LABEL_BAND)
    # And the contract still binds exactly the measured Enable rect in the fixture tree.
    placed = resolve_channels(observation_of(_roles(SETTINGS_ROWS, offset=(120, 40))))
    from udv_echo_process.acquire.ui.channels import bind_enable_toggle

    assert bind_enable_toggle(placed).rect == (9, 36, 138, 68)


def test_an_unknown_mode_label_refuses_the_enable_with_zero_presses(tmp_path):
    """A popup whose Enable line was not recognised is not a disable proof, whatever else paints."""
    from udv_echo_process.acquire import mode_marks

    unknown = mode_marks.ModeMarkAttribution(
        surface=mode_marks.SETTINGS_FULL,
        mode="UNKNOWN",
        rolling="ON_PROVEN",
        enable_precondition=False,
        recognition="NOT_MATCHED",
        unknown_reasons=("the Enable line holds no ink",),
    )
    report = _report()
    capture = report.capture.model_copy(update={"visual_mode_mark": unknown})
    unlicensed = report.model_copy(update={"capture": capture})
    live = FakeEnableActuator()
    with pytest.raises(AcquisitionError, match="disabled settings surface is required"):
        _run(tmp_path, live, reads=[unlicensed] * 2)
    assert live.presses == []


# ---------------------------------------------------------------------------------------------
# the post-press entry pair: the only source of a VISUAL_ENABLED post state
# ---------------------------------------------------------------------------------------------

ENTRY = DATA / "entry-clipped-enabled"


def _entry_mark() -> mode_marks.ModeMarkAttribution:
    """The operator's real clipped ``Desable multiplexer`` pair, recognised by the live path."""
    return _live_mark(ENTRY)


def _entry_capture(
    root: Path,
    *,
    mark: mode_marks.ModeMarkAttribution | None = None,
    kind: str = "entry_no_numeric",
    popup: int = 1000,
    hwnd: int = WINDOW,
    status: str = "ok",
    digests: tuple[str, ...] | None = None,
    claim: Path | None = None,
) -> CaptureEvidence:
    paths = _pair(ENTRY)
    real_digests = tuple(frame_digest(mode_marks.load_frame(path)) for path in paths)
    rect = (8, 8, 166, 51)
    stats = FrameStats(
        width=158,
        height=43,
        mode="RGB",
        distinct_grey_levels=11,
        dominant_fraction=0.31,
        non_blank=True,
    )
    frames = tuple(
        FrameEvidence(
            index=index,
            path=paths[index - 1],
            rect=rect,
            stats=stats,
            digest=(digests or real_digests)[index - 1],
        )
        for index in (1, 2)
    )
    before = WindowGuard(
        label="before",
        hwnd=hwnd,
        rect=(0, 0, 1920, 1080),
        foreground=True,
        minimized=False,
        surface="multiplexer_on_entry",
        popup_rect=rect,
        popup_hwnd=popup,
    )
    after = before.model_copy(update={"label": "after"})
    return CaptureEvidence(
        status=status,
        captured=True,
        roi=rect,
        capture_kind=kind,
        directory=str(claim or (root / "captures" / "capture-003")),
        frames=frames,
        stable=True,
        guards=GuardComparison(before=before, after=after, consistent=True),
        numeric=NumericBracketing(
            applicable=kind == "settings_numeric",
            note="no numeric settings fields on the clipped entry popup",
        ),
        visual_mode_mark=_entry_mark() if mark is None else mark,
    )


def _entry_report(capture: CaptureEvidence | None = None) -> ChannelsRead:
    return ChannelsRead(
        surface=ChannelsSurface.MULTIPLEXER_ON_ENTRY,
        readable=True,
        capture=capture,
    )


def _entry_run(tmp_path, *, capture=None, post=None, **kwargs):
    evidence = _entry_capture(tmp_path) if capture is None else capture
    return _run(
        tmp_path,
        post=post if post is not None else _entry_report(),
        post_capture=_entry_report(evidence),
        **kwargs,
    )


def test_a_fresh_post_press_entry_pair_proves_the_enabled_mode(tmp_path) -> None:
    live = FakeEnableActuator()
    result = _entry_run(tmp_path, live=live)
    assert live.presses == [ENABLE_HWND]
    assert result.presses == 1
    assert result.post_surface == "multiplexer_on_entry"
    assert result.post_mode == "VISUAL_ENABLED"
    assert result.post_capture_kind == "entry_no_numeric"
    assert result.post_error == ""
    assert result.post_frame_digests is not None
    assert len(result.post_frame_digests) == 2
    assert all(len(digest) == 64 for digest in result.post_frame_digests)
    assert result.post_rolling == "UNKNOWN"
    record = _record(tmp_path)
    assert record["post_mode"] == "VISUAL_ENABLED"
    assert record["post_capture_kind"] == "entry_no_numeric"
    assert record["post_frame_digests"] == list(result.post_frame_digests)


def test_an_entry_read_without_capture_evidence_is_unknown(tmp_path) -> None:
    result = _run(
        tmp_path,
        post=_entry_report(),
        post_capture=_entry_report(None),
    )
    assert result.post_mode == "UNKNOWN"
    assert "no fresh capture" in result.post_error
    assert result.post_frame_digests is None
    assert result.presses == 1


def test_an_altered_entry_label_is_not_enabled(tmp_path) -> None:
    mark = _entry_mark().model_copy(
        update={"label": "ENABLE_MULTIPLEXER", "mode": "UNKNOWN"}
    )
    result = _entry_run(tmp_path, capture=_entry_capture(tmp_path, mark=mark))
    assert result.post_mode == "UNKNOWN"
    assert "label='ENABLE_MULTIPLEXER'" in result.post_error


def test_a_wrong_sized_entry_crop_is_unknown(tmp_path) -> None:
    mark = mode_marks.ModeMarkAttribution(
        surface="UNSUPPORTED",
        label="UNRECOGNIZED",
        mode="UNKNOWN",
        mark="NOT_READ",
        rolling="UNKNOWN",
        recognition="NOT_MATCHED",
    )
    result = _entry_run(tmp_path, capture=_entry_capture(tmp_path, mark=mark))
    assert result.post_mode == "UNKNOWN"
    assert "wrong-sized or otherwise unattributed" in result.post_error


def test_a_retained_or_unverified_entry_pair_is_not_a_post_mode(tmp_path) -> None:
    mark = _entry_mark().model_copy(
        update={
            "acquisition_context": "retained",
            "freshness": "not_established",
            "integrity": "decoded-pair-only",
        }
    )
    result = _entry_run(tmp_path, capture=_entry_capture(tmp_path, mark=mark))
    assert result.post_mode == "UNKNOWN"
    assert "not a fresh live-bracketed" in result.post_error


def test_a_pair_without_two_digests_states_no_enabled_mode(tmp_path) -> None:
    mark = _entry_mark().model_copy(update={"frame_digests": None})
    result = _entry_run(tmp_path, capture=_entry_capture(tmp_path, mark=mark))
    assert result.post_mode == "UNKNOWN"
    assert "no two genuine frame digests" in result.post_error
    assert result.post_frame_digests is None


def test_identity_drift_on_the_post_pair_is_unknown(tmp_path) -> None:
    result = _entry_run(tmp_path, capture=_entry_capture(tmp_path, popup=2222))
    assert result.post_mode == "UNKNOWN"
    assert "different panel's entry line" in result.post_error
    assert result.post_frame_digests is None


def test_a_post_pair_from_outside_the_capture_root_is_unknown(tmp_path) -> None:
    result = _entry_run(
        tmp_path,
        capture=_entry_capture(tmp_path, claim=tmp_path / "elsewhere" / "capture-001"),
    )
    assert result.post_mode == "UNKNOWN"
    assert "outside this invocation's capture root" in result.post_error


def test_a_settings_capture_never_satisfies_the_entry_contract(tmp_path) -> None:
    result = _entry_run(
        tmp_path, capture=_entry_capture(tmp_path, kind="settings_numeric")
    )
    assert result.post_mode == "UNKNOWN"
    assert "never interchanged" in result.post_error


def test_a_raised_post_capture_leaves_the_mode_unknown(tmp_path) -> None:
    # No capture double is supplied for the post pair: the capture call raises and the
    # workflow records it as unknown instead of retrying.
    result = _run(tmp_path, post=_entry_report())
    assert result.post_mode == "UNKNOWN"
    assert "could not be taken" in result.post_error
    assert result.presses == 1


def test_a_record_rewrite_failure_keeps_the_verified_post_and_reports_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        enable_multiplexed, "update_trial_record", lambda *a, **k: "disk full"
    )
    result = _entry_run(tmp_path)
    assert result.post_mode == "VISUAL_ENABLED"
    assert result.trial_record_error == "disk full"


def test_cli_exits_nonzero_when_enabled_has_no_fresh_digests(
    tmp_path, monkeypatch
) -> None:
    _patch_cli(monkeypatch, _cli_result(post_mode="VISUAL_ENABLED"))
    with pytest.raises(SystemExit) as excinfo:
        acquire_main(
            [
                "enable-multiplexed",
                "--capture-dir",
                str(tmp_path),
                "--trial-record",
                str(tmp_path / "t.json"),
                "--json",
            ]
        )
    assert excinfo.value.code == 1


def test_cli_exits_nonzero_when_the_press_raised_even_if_the_post_reads_enabled(
    tmp_path, monkeypatch
) -> None:
    _patch_cli(
        monkeypatch,
        _cli_result(
            post_mode="VISUAL_ENABLED",
            post_frame_digests=("a" * 64, "b" * 64),
            press_error="the press raised RuntimeError: boom",
        ),
    )
    with pytest.raises(SystemExit) as excinfo:
        acquire_main(
            [
                "enable-multiplexed",
                "--capture-dir",
                str(tmp_path),
                "--trial-record",
                str(tmp_path / "t.json"),
                "--json",
            ]
        )
    assert excinfo.value.code == 1
