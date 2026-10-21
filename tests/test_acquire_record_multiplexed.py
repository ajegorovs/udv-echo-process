"""The record-multiplexed command's boundary: one Record, the application's completion, one store.

Every case here drives the **production workflow**
(:mod:`udv_echo_process.acquire.record_multiplexed`) — the CLI cases included, through
``acquire_main`` with only the Win32 boundary replaced (the actuator class and the window
enumeration). What is pinned is what the module owns: the composition a default call builds, the
refusals that must land before anything is pressed, the one ``Record`` press on the bound window,
the bounded wait for the application's own completion, and that the store is the **same**
store-only path on the **same** binding with exactly one ``Do store``.

The double models no instrument: nothing here claims the application answers a press, and the
completion is the strip reading the flow classifies, not a recording anybody made.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire import record_multiplexed as workflow
from udv_echo_process.acquire.actuator import (
    OverlayKind,
    StripControl,
    StripState,
    WindowTarget,
)
from udv_echo_process.acquire.mpx_artifact import verify_mpx_artifact
from udv_echo_process.acquire.record_multiplexed import (
    MpxStage,
    MultiplexedRecordingDeclaration,
    MultiplexedRecordingResult,
    record_multiplexed,
)
from udv_echo_process.acquire.store_completed import store_completed
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.store import StoreDirectoryVerification
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.cli import acquire_main

HWND = 4711

#: The committed 4-channel multiplexed fixture; verification in these tests is the production
#: verifier on it, so a stored run's artifact report is a real decode rather than a stand-in.
FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
FIXTURE_CHANNELS = (6, 7, 8, 9)
FIXTURE_PROFILES = 400


def _fixture_verifier(_path: Path, declaration):
    """Production verification of the committed fixture, for runs whose store writes b'\\x00'."""
    return verify_mpx_artifact(FIXTURE, declaration)


READY = StripState(button_count=3, has_slider=False)
RECORDING = StripState(button_count=1, has_slider=False)
COMPLETED = StripState(button_count=2, has_slider=True, slider_max=50)
AMBIGUOUS = StripState(button_count=4, has_slider=False)


class FakeMpxScreen:
    """A driver-shaped double: one bound window, a scripted strip, one recorded gesture list.

    ``strip_state`` answers the entry row until ``Record`` is pressed, then walks
    ``after_press`` (the last reading repeats). Every press is recorded with the handle the
    actuator was bound to at that moment, so "the store ran on the same binding" is a checkable
    fact rather than an assumption.
    """

    def __init__(
        self,
        *,
        entry: StripState = READY,
        after_press: Sequence[StripState] = (RECORDING, COMPLETED),
        caption: str = "UDOP DOP3010.43",
        overlay: OverlayKind | None = None,
        read_error: Exception | None = None,
        target_thread: int = 11,
        target_process: int = 22,
        payload: bytes | None = None,
    ) -> None:
        self.entry = entry
        self.after_press = tuple(after_press) or (COMPLETED,)
        self.caption = caption
        self.overlay = overlay
        self.read_error = read_error
        self.payload = payload
        self.target: WindowTarget | None = None
        self.target_thread = target_thread
        self.target_process = target_process
        self.bound: list[int] = []
        self.presses: list[tuple[StripControl, int]] = []
        self.store_names: list[str] = []
        self.commits = 0
        self.warnings: list[str] = []
        self.recorded = False
        self._poll = 0
        self._pending = ""
        self._store_pressed = False

    # --- identity and screen --------------------------------------------
    def bind_target(self, hwnd: int) -> WindowTarget:
        self.bound.append(hwnd)
        self.target = WindowTarget(
            hwnd=hwnd,
            thread_id=self.target_thread,
            process_id=self.target_process,
            class_name=MAIN_CLASS,
        )
        return self.target

    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget:
        if self.target != expected or (self.target_thread, self.target_process) != (
            expected.thread_id,
            expected.process_id,
        ):
            raise AcquisitionError("the original target identity changed")
        return expected

    def window_caption(self) -> str:
        return self.caption

    def peek_overlay(self) -> OverlayKind | None:
        if self.overlay is not None:
            return self.overlay
        # Nothing is up before 'Do store'; after it the Store dialog is.
        return OverlayKind.STORE_DIALOG if self.commits or self._store_pressed else None

    def strip_state(self) -> StripState:
        if self.read_error is not None:
            raise self.read_error
        if not self.recorded:
            return self.entry
        index = min(self._poll, len(self.after_press) - 1)
        state = self.after_press[index]
        # The first reading after a press is the one the flow polls for; later calls (the store's
        # own re-read) must see the completion row it settled on.
        if state.view.value == "store":
            return state
        self._poll += 1
        return state

    # --- gestures -------------------------------------------------------
    def press(self, control: StripControl) -> None:
        hwnd = self.target.hwnd if self.target is not None else 0
        self.presses.append((control, hwnd))
        if control is StripControl.RECORD:
            self.recorded = True
        if control is StripControl.DO_STORE:
            self._store_pressed = True

    def set_store_name(self, name: str) -> None:
        self.store_names.append(name)

    def verify_working_directory(self, directory: Path) -> StoreDirectoryVerification:
        return StoreDirectoryVerification(
            before=str(directory), after=str(directory), changed=False
        )

    def commit_store(self) -> None:
        self.commits += 1
        self._pending = self.store_names[-1]

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        path = Path(directory) / f"{self._pending}.BDD"
        path.write_bytes(b"\x00" if self.payload is None else self.payload)
        return path

    def controls_pressed(self) -> list[StripControl]:
        return [control for control, _hwnd in self.presses]


def declaration(**overrides) -> MultiplexedRecordingDeclaration:
    fields = {
        "multiplexer_enabled": True,
        "channels": (1, 2),
        "profiles_per_channel": 50,
        "stated_by": "operator",
    }
    fields.update(overrides)
    return MultiplexedRecordingDeclaration(**fields)


def run(
    tmp_path: Path,
    *,
    screen: FakeMpxScreen,
    windows: Sequence[int] = (HWND,),
    completion_timeout_s: float = 30.0,
    clock=None,
    sleep=None,
    **kwargs,
) -> MultiplexedRecordingResult:
    extra = {}
    if clock is not None:
        extra["clock"] = clock
    if sleep is not None:
        extra["sleep"] = sleep
    return record_multiplexed(
        "mpx-run",
        tmp_path,
        declaration=declaration(),
        completion_timeout_s=completion_timeout_s,
        actuator=screen,
        enumerate_windows=lambda: windows,
        **extra,
        **kwargs,
    )


class FakeClock:
    """A monotonic clock that advances on every read, so deadlines are reached without waiting."""

    def __init__(self, step: float = 1.0) -> None:
        self.now = 1000.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


# --------------------------------------------------------------------------- success paths


def test_default_composition_records_once_and_stores_once_on_the_bound_window(
    tmp_path: Path, monkeypatch
):
    screen = FakeMpxScreen(payload=FIXTURE.read_bytes())
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (HWND,))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "record-multiplexed",
                "mpx-run",
                "--channel",
                *[str(channel) for channel in FIXTURE_CHANNELS],
                "--profiles",
                str(FIXTURE_PROFILES),
                "--stated-by",
                "operator",
                "--mpx-enabled",
                "--completion-timeout",
                "30",
                "--store-dir",
                str(tmp_path),
            ]
        )

    assert exit_info.value.code == 0
    # Exactly one Record and one Do store, both on the one bound handle, and no other press.
    assert screen.controls_pressed() == [StripControl.RECORD, StripControl.DO_STORE]
    assert {hwnd for _control, hwnd in screen.presses} == {HWND}
    # A store handoff checks the original binding without binding a second time.
    assert screen.bound == [HWND]
    assert screen.commits == 1
    assert (tmp_path / "mpx-run.BDD").exists()


def test_workflow_result_carries_the_same_binding_through_the_store(tmp_path: Path):
    screen = FakeMpxScreen()
    result = run(tmp_path, screen=screen, verify_artifact=_fixture_verifier)

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path == tmp_path / "mpx-run.BDD"
    assert result.record_presses == 1
    assert result.record_started is True
    assert result.completion_state is not None
    assert result.completion_state.button_count == 2
    assert result.completion_state.has_slider is True
    assert result.store is not None
    assert result.store.bound_target.hwnd == result.bound_target.hwnd == HWND
    assert screen.controls_pressed() == [StripControl.RECORD, StripControl.DO_STORE]
    assert result.store.store.commit_presses == 1


def test_queued_press_is_provisional_inside_the_grace(tmp_path: Path):
    """A 'ready' row straight after the press is not a failure: the press is queued."""
    screen = FakeMpxScreen(after_press=(READY, READY, RECORDING, COMPLETED))
    result = run(tmp_path, screen=screen, verify_artifact=_fixture_verifier)

    assert result.stage is MpxStage.STORED
    assert any("ready" in reading for reading in result.observed)
    assert screen.controls_pressed() == [StripControl.RECORD, StripControl.DO_STORE]


# --------------------------------------------------------------------------- post-press outcomes


def test_timeout_leaves_the_recording_running_and_presses_nothing_else(tmp_path: Path):
    screen = FakeMpxScreen(after_press=(RECORDING,))
    result = run(
        tmp_path,
        screen=screen,
        completion_timeout_s=5.0,
        clock=FakeClock(step=1.0),
        sleep=lambda _s: None,
    )

    assert result.stage is MpxStage.STILL_RUNNING
    assert result.record_started is True
    assert result.store is None and result.stored_path is None
    assert screen.controls_pressed() == [StripControl.RECORD]
    assert screen.commits == 0
    assert "left running" in result.reason
    assert "still in progress" in " ".join(result.owed)


def test_ready_past_the_grace_is_reported_as_never_started(tmp_path: Path):
    screen = FakeMpxScreen(after_press=(READY,))
    result = run(
        tmp_path, screen=screen, clock=FakeClock(step=10.0), sleep=lambda _s: None
    )

    assert result.stage is MpxStage.RECORD_NOT_STARTED
    assert result.record_presses == 1
    assert result.record_started is False
    assert screen.controls_pressed() == [StripControl.RECORD]
    assert screen.commits == 0


def test_unsettled_completion_row_is_terminal_and_stores_nothing(tmp_path: Path):
    screen = FakeMpxScreen(after_press=(RECORDING, AMBIGUOUS))
    result = run(tmp_path, screen=screen, sleep=lambda _s: None)

    assert result.stage is MpxStage.COMPLETION_UNKNOWN
    assert result.record_started is True
    assert result.store is None
    assert screen.controls_pressed() == [StripControl.RECORD]
    assert screen.commits == 0


def test_a_read_error_is_reported_with_its_original_facts(tmp_path: Path):
    screen = FakeMpxScreen(after_press=(RECORDING,))
    clock = FakeClock(step=0.1)

    def fail_after_the_press() -> StripState:
        if screen.recorded:
            raise RuntimeError("GetWindowRect failed with 1400")
        return READY

    screen.strip_state = fail_after_the_press  # type: ignore[method-assign]
    result = run(tmp_path, screen=screen, clock=clock, sleep=lambda _s: None)

    assert result.stage is MpxStage.COMPLETION_UNKNOWN
    assert result.error.startswith("RuntimeError: GetWindowRect failed with 1400")
    assert "nothing was retried" in result.reason
    assert screen.controls_pressed() == [StripControl.RECORD]
    assert screen.commits == 0


def test_store_refusal_after_completion_is_reported_and_not_retried(tmp_path: Path):
    """A name taken between the preflight and the store: Do store is never pressed."""
    screen = FakeMpxScreen()
    original = screen.strip_state

    def strip_state_then_collide() -> StripState:
        state = original()
        if screen.recorded and not (tmp_path / "mpx-run.BDD").exists():
            (tmp_path / "mpx-run.BDD").write_bytes(b"someone else's block")
        return state

    screen.strip_state = strip_state_then_collide  # type: ignore[method-assign]
    result = run(tmp_path, screen=screen, sleep=lambda _s: None)

    assert result.stage is MpxStage.STORE_FAILED
    assert result.store_invoked is True
    assert result.stored_path is None
    assert "already taken" in result.error
    assert screen.controls_pressed() == [StripControl.RECORD]
    assert screen.commits == 0
    assert screen.store_names == []


# --------------------------------------------------------------------------- zero-action refusals


@pytest.mark.parametrize(
    "name",
    ["", "  ", "a.b", "sub/dir", ".hidden", "nul"],
)
def test_an_unusable_name_is_refused_before_any_action(tmp_path: Path, name: str):
    screen = FakeMpxScreen()
    with pytest.raises(AcquisitionError):
        record_multiplexed(
            name,
            tmp_path,
            declaration=declaration(),
            completion_timeout_s=30.0,
            actuator=screen,
            enumerate_windows=lambda: (HWND,),
        )
    assert screen.bound == []
    assert screen.presses == []


def test_an_existing_entry_refuses_before_the_press(tmp_path: Path):
    (tmp_path / "mpx-run.BDD").write_bytes(b"already here")
    screen = FakeMpxScreen()
    with pytest.raises(AcquisitionError, match="already taken"):
        run(tmp_path, screen=screen)
    assert screen.bound == []
    assert screen.presses == []


def test_a_missing_directory_refuses_before_the_press(tmp_path: Path):
    screen = FakeMpxScreen()
    with pytest.raises(AcquisitionError, match="does not exist"):
        run(tmp_path / "nope", screen=screen)
    assert screen.bound == []
    assert screen.presses == []


def test_two_visible_windows_refuse_before_binding(tmp_path: Path):
    screen = FakeMpxScreen()
    with pytest.raises(AcquisitionError, match="does not choose between copies"):
        run(tmp_path, screen=screen, windows=(HWND, 4712))
    assert screen.bound == []
    assert screen.presses == []


@pytest.mark.parametrize(
    "entry",
    [
        COMPLETED,  # a block is already on screen: not the ready row
        RECORDING,  # a recording is already running
        AMBIGUOUS,  # the row ledger B10 leaves unresolved
    ],
)
def test_a_strip_that_is_not_the_ready_row_refuses_before_the_press(
    tmp_path: Path, entry: StripState
):
    screen = FakeMpxScreen(entry=entry)
    with pytest.raises(AcquisitionError):
        run(tmp_path, screen=screen)
    assert screen.presses == []


def test_a_simulator_caption_refuses_before_the_press(tmp_path: Path):
    screen = FakeMpxScreen(caption="UDOP Simul 4.3")
    with pytest.raises(AcquisitionError):
        run(tmp_path, screen=screen)
    assert screen.presses == []


def test_an_overlay_already_up_refuses_before_the_press(tmp_path: Path):
    screen = FakeMpxScreen(overlay=OverlayKind.WARNING)
    with pytest.raises(AcquisitionError):
        run(tmp_path, screen=screen)
    assert screen.presses == []


# --------------------------------------------------------------------------- declarations and bounds


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"multiplexer_enabled": False}, "not declared the multiplexer enabled"),
        ({"channels": (1,)}, "single-channel completion is not one"),
        ({"channels": (1, 1)}, "repeat one"),
        ({"channels": ()}, "names no channels"),
        ({"profiles_per_channel": 0}, "positive profile count"),
        ({"stated_by": "  "}, "names no operator"),
    ],
)
def test_the_operator_statement_is_a_contract(overrides, match: str):
    with pytest.raises(ValidationError, match=match):
        declaration(**overrides)


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("inf"), float("nan")])
def test_the_completion_bound_must_be_finite_and_positive(
    tmp_path: Path, timeout: float
):
    screen = FakeMpxScreen()
    with pytest.raises(AcquisitionError, match="completion_timeout_s"):
        run(tmp_path, screen=screen, completion_timeout_s=timeout)
    assert screen.presses == []


# --------------------------------------------------------------------------- explicit store target


def test_bound_target_verification_is_read_only_and_checks_live_identity(monkeypatch):
    from udv_echo_process.acquire import driver

    live = driver.Win32Actuator(channel=1)
    original = WindowTarget(
        hwnd=HWND, thread_id=11, process_id=22, class_name=MAIN_CLASS
    )
    live._target = original
    checked = []

    def mismatch(target, **kwargs):
        checked.append(target)

    monkeypatch.setattr(driver, "_target_mismatch", mismatch)
    assert live.verify_bound_target(original) == original
    assert checked == [original]
    assert live._target is original
    monkeypatch.setattr(
        driver, "_target_mismatch", lambda *args, **kwargs: "root identity changed"
    )
    with pytest.raises(AcquisitionError, match="root identity changed"):
        live.verify_bound_target(original)
    assert live._target is original
    replacement = WindowTarget(
        hwnd=9999, thread_id=11, process_id=22, class_name=MAIN_CLASS
    )
    live._target = replacement
    with pytest.raises(AcquisitionError, match="binding differs"):
        live.verify_bound_target(original)
    assert live._target is replacement


@pytest.mark.parametrize("mode", [1, "true", "yes"])
def test_mode_confirmation_is_not_coerced(mode):
    with pytest.raises(ValidationError):
        declaration(multiplexer_enabled=mode)


def test_unexpected_store_failure_is_a_post_record_result(tmp_path: Path):
    screen = FakeMpxScreen()

    def fail(directory):
        raise OSError("readback unavailable")

    screen.verify_working_directory = fail
    result = run(tmp_path, screen=screen)
    assert result.stage is MpxStage.STORE_FAILED
    assert result.record_presses == 1
    assert result.error == "OSError: readback unavailable"
    assert screen.controls_pressed() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 0
    assert screen.bound == [HWND]


def test_the_store_refuses_a_window_the_caller_did_not_bind(tmp_path: Path):
    """`store_completed(target=...)` verifies, and never selects a replacement."""
    screen = FakeMpxScreen()
    target = screen.bind_target(HWND)
    with pytest.raises(AcquisitionError, match="never selects a replacement"):
        store_completed(
            "mpx-run",
            tmp_path,
            declaration=workflow.MultiplexedRecordingDeclaration(
                multiplexer_enabled=True,
                channels=(1, 2),
                profiles_per_channel=50,
                stated_by="operator",
            ).completed_block(),
            actuator=screen,
            enumerate_windows=lambda: (9999,),
            target=target,
        )
    assert screen.controls_pressed() == []
    assert screen.commits == 0


def test_the_store_refuses_a_recycled_handle(tmp_path: Path):
    screen = FakeMpxScreen(target_thread=99, target_process=88)
    target = WindowTarget(hwnd=HWND, thread_id=11, process_id=22, class_name=MAIN_CLASS)
    with pytest.raises(AcquisitionError, match="the original target identity changed"):
        store_completed(
            "mpx-run",
            tmp_path,
            declaration=workflow.MultiplexedRecordingDeclaration(
                multiplexer_enabled=True,
                channels=(1, 2),
                profiles_per_channel=50,
                stated_by="operator",
            ).completed_block(),
            actuator=screen,
            enumerate_windows=lambda: (HWND,),
            target=target,
        )
    assert screen.controls_pressed() == []
