"""The store-only command's boundary: what it refuses, and the one press it makes.

These cases drive the **production workflow** (:mod:`udv_echo_process.acquire.store_completed`)
through a driver-shaped double. What is pinned is the boundary the module owns: the composition a
default call builds, the name/directory/collision refusals that must land before anything is
pressed, the screen states it refuses, and the attribution of the one new entry to the name the
store was committed under. The double does not model the instrument, so nothing here claims the
application answers the press.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire import store_completed as workflow
from udv_echo_process.acquire.actuator import (
    OverlayKind,
    StripControl,
    StripState,
    WindowTarget,
)
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    collision_clause,
    store_completed,
    store_name_clause,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.store import StoreDirectoryVerification
from udv_echo_process.acquire.ui.layout import MAIN_CLASS


class FakeStoreScreen:
    """A driver-shaped double: one fixed screen, one recorded set of gestures.

    It answers only the public surface the workflow calls — the binding, the caption, the
    overlay read, the strip read, the one press, the Store dialog's name/directory/commit and
    the new-entry wait — so a call the workflow must not make (a second press, a name write
    before a refused check) shows up as a recorded gesture rather than a missing method.
    """

    def __init__(
        self,
        *,
        state: StripState | None = None,
        caption: str = "UDOP DOP3010.43",
        overlay: OverlayKind | None = None,
        stored_name: str | None = None,
        write_stored_file: bool = True,
        rewrite_directory: bool = False,
    ) -> None:
        self.state = (
            StripState(button_count=2, has_slider=True) if state is None else state
        )
        self.caption = caption
        self.overlay = overlay
        self.stored_name = stored_name
        self.write_stored_file = write_stored_file
        self.rewrite_directory = rewrite_directory
        self.warnings: list[str] = []
        self.bound: list[int] = []
        self.presses: list[StripControl] = []
        self.store_names: list[str] = []
        self.directories: list[Path] = []
        self.commits = 0
        self.waits = 0
        self.answers = 0

    # --- identity -------------------------------------------------------
    def bind_target(self, hwnd: int) -> WindowTarget:
        self.bound.append(hwnd)
        return WindowTarget(
            hwnd=hwnd, thread_id=11, process_id=22, class_name=MAIN_CLASS
        )

    def window_caption(self) -> str:
        return self.caption

    def peek_overlay(self) -> OverlayKind | None:
        if self.overlay is not None:
            return self.overlay
        # Before the store there is no dialog; after the one press, the dialog is up.
        return OverlayKind.STORE_DIALOG if self.presses else None

    def answer_overlay(self) -> OverlayKind | None:
        answered = self.overlay
        self.overlay = None
        self.answers += 1
        return answered

    # --- strip ----------------------------------------------------------
    def strip_state(self) -> StripState:
        return self.state

    def press(self, control: StripControl) -> None:
        self.presses.append(control)

    # --- Store dialog ---------------------------------------------------
    def set_store_name(self, name: str) -> None:
        self.store_names.append(name)

    def assert_working_directory(self, directory: Path) -> str:
        """The pre-typed surface, kept for callers that still ask only for the verified text."""
        self.directories.append(Path(directory))
        if self.rewrite_directory:
            self.warnings.append(
                f"the Store dialog's Working directory was 'C:\\elsewhere'; wrote "
                f"'{directory}'"
            )
        return str(directory)

    def verify_working_directory(self, directory: Path) -> StoreDirectoryVerification:
        """The Store dialog's ``Working directory``, as the typed report the live surface returns.

        ``rewrite_directory`` makes the dialog *show* another folder, so the assertion has to write
        the caller's: ``before`` is then the other folder and ``after`` the text read back. The
        note the live surface writes alongside it is reproduced too, because the report must rest
        on the typed value rather than on that prose.
        """
        self.directories.append(Path(directory))
        target = str(directory)
        if self.rewrite_directory:
            self.warnings.append(
                f"the Store dialog's Working directory was 'C:\\elsewhere'; wrote "
                f"'{target}'"
            )
            return StoreDirectoryVerification(
                before="C:\\elsewhere", after=target, changed=True
            )
        return StoreDirectoryVerification(before=target, after=target, changed=False)

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        self.waits += 1
        # By default the application appends its own extension to the name it was given.
        name = self.stored_name or f"{self.store_names[-1]}.BDD"
        path = Path(directory) / name
        if self.write_stored_file:
            path.write_bytes(b"BDD")
        return path


def declaration(**overrides) -> CompletedBlockDeclaration:
    values = {
        "channels": (1, 2),
        "profiles_per_channel": 50,
        "stated_by": "operator",
        "statement": "channels 1 and 2, 50 profiles",
    }
    values.update(overrides)
    return CompletedBlockDeclaration(**values)


def run(
    tmp_path: Path,
    *,
    name: str = "mpx12-50profiles-manual-01",
    screen: FakeStoreScreen | None = None,
    windows: tuple[int, ...] = (4711,),
    **kwargs,
):
    screen = screen if screen is not None else FakeStoreScreen()
    result = store_completed(
        name,
        tmp_path,
        declaration=declaration(),
        actuator=screen,
        enumerate_windows=lambda: windows,
        **kwargs,
    )
    return result, screen


# ------------------------------------------------------------- the default composition


class ComposedActuator(FakeStoreScreen):
    """Stands in for ``Win32Actuator`` in the default-wiring case, recording its construction."""

    last_init: ClassVar[dict[str, object]] = {}

    def __init__(self, class_name: str = MAIN_CLASS, *, channel=None, note_sink=None):
        super().__init__()
        type(self).last_init = {"class_name": class_name, "channel": channel}
        self.note_sink = note_sink


def test_default_composition_binds_the_one_enumerated_window(
    monkeypatch, tmp_path: Path
) -> None:
    """With no actuator supplied, the workflow builds one, binds the single window, stores once."""
    ComposedActuator.last_init = {}
    monkeypatch.setattr(workflow, "Win32Actuator", ComposedActuator)

    result = workflow.store_completed(
        "mpx12-50profiles-manual-01",
        tmp_path,
        declaration=declaration(),
        enumerate_windows=lambda: (4711,),
    )

    assert ComposedActuator.last_init == {"class_name": MAIN_CLASS, "channel": None}
    assert result.bound_target.hwnd == 4711
    assert result.bound_target.class_name == MAIN_CLASS
    assert result.store.commit_presses == 1
    assert result.stored_path.name == "mpx12-50profiles-manual-01.BDD"


# --------------------------------------------------- refusals that must precede the press


def test_incompatible_ready_view_refuses_before_any_press(tmp_path: Path) -> None:
    """A three-button ready row is not a completed block: nothing is pressed or written."""
    screen = FakeStoreScreen(state=StripState(button_count=3, has_slider=False))
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "'ready'" in str(raised.value)
    assert screen.bound == [4711]
    assert screen.presses == []
    assert screen.store_names == []
    assert screen.commits == 0


def test_three_button_store_row_refuses_before_any_press(tmp_path: Path) -> None:
    """A three-button store row is not enough: an *unmeasured* one binds ``New acquisition``.

    The repeated-MPX completion row is also three buttons, so the length cannot decide. Without
    a measured signature the state answers the legacy row, whose first button is ``New
    acquisition``, and the refusal names that rather than pressing index 1 (``Clear and
    restart``) on the operator's unsaved block.
    """
    screen = FakeStoreScreen(state=StripState(button_count=3, has_slider=True))
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    message = str(raised.value)
    assert "legacy three-button row" in message
    assert "requires a row that starts with 'Do store'" in message
    assert "measured geometry" in message
    assert screen.presses == []


def test_recording_view_refuses_before_any_press(tmp_path: Path) -> None:
    """The active-recording row is never a store entry point, and Stop is never pressed."""
    screen = FakeStoreScreen(state=StripState(button_count=1, has_slider=False))
    with pytest.raises(AcquisitionError):
        run(tmp_path, screen=screen)
    assert screen.presses == []


def test_name_collision_is_refused_before_anything_is_bound(tmp_path: Path) -> None:
    """An existing `name.any-suffix` takes the stem: refused before a driver or a press."""
    (tmp_path / "mpx12-50profiles-manual-01.BDD").write_bytes(b"existing")
    screen = FakeStoreScreen()

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "already taken" in str(raised.value)
    assert screen.bound == []
    assert screen.presses == []
    assert screen.commits == 0


def test_two_visible_windows_refuse_before_binding(tmp_path: Path) -> None:
    """Exactly one application, or nothing: the workflow never chooses between copies."""
    screen = FakeStoreScreen()
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen, windows=(4711, 4712))

    assert "2 visible" in str(raised.value)
    assert screen.bound == []


def test_simulator_caption_refuses_before_any_press(tmp_path: Path) -> None:
    screen = FakeStoreScreen(caption="UDOP Simul 1.0")
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "simulation" in str(raised.value)
    assert screen.presses == []


def test_an_overlay_already_up_refuses_before_any_press(tmp_path: Path) -> None:
    screen = FakeStoreScreen(overlay=OverlayKind.WARNING)
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "overlay is already up" in str(raised.value)
    assert screen.presses == []


def test_missing_store_directory_refuses_before_anything_is_pressed(
    tmp_path: Path,
) -> None:
    screen = FakeStoreScreen()
    with pytest.raises(AcquisitionError) as raised:
        store_completed(
            "block",
            tmp_path / "absent",
            declaration=declaration(),
            actuator=screen,
            enumerate_windows=lambda: (4711,),
        )
    assert "does not exist" in str(raised.value)
    assert screen.bound == []


def test_a_declaration_that_names_one_channel_is_not_a_multiplexed_block() -> None:
    with pytest.raises(ValidationError) as raised:
        declaration(channels=(1,))
    assert "single-channel completion" in str(raised.value)


def test_a_declaration_without_an_operator_or_positive_count_is_refused() -> None:
    with pytest.raises(ValidationError):
        declaration(stated_by="  ")
    with pytest.raises(ValidationError):
        declaration(profiles_per_channel=0)


def test_store_name_is_one_bare_stem() -> None:
    assert store_name_clause("mpx12-50profiles-manual-01") is None
    for bad in ("../escape", "a/b", "name.BDD", ".hidden", "nul", "", "bad "):
        assert store_name_clause(bad) is not None, bad


# ----------------------------------------------------- the one press, and its attribution


def test_one_press_one_commit_and_the_new_entry_is_the_stored_file(
    tmp_path: Path,
) -> None:
    """The success path: exactly one Do store, one name write, one commit, exact file by stem."""
    screen = FakeStoreScreen(stored_name="mpx12-50profiles-manual-01.BDD")
    result, screen = run(tmp_path, screen=screen)

    assert screen.presses == [StripControl.DO_STORE]
    assert screen.store_names == ["mpx12-50profiles-manual-01"]
    assert screen.commits == 1
    assert screen.waits == 1
    assert result.stored_path == tmp_path / "mpx12-50profiles-manual-01.BDD"
    assert result.store.stored_name == "mpx12-50profiles-manual-01.BDD"
    assert result.store.commit_presses == 1
    assert result.store.dialog_warnings_answered == 0
    assert result.strip_state.view.value == "store"
    assert result.declaration.channels == (1, 2)


def test_the_recorded_extension_is_observed_not_assumed(tmp_path: Path) -> None:
    """The application supplies the extension: the report keeps the name it actually wrote."""
    screen = FakeStoreScreen(stored_name="BLOCK.bdd")
    result, _ = run(tmp_path, name="block", screen=screen)
    assert result.store.stored_name == "BLOCK.bdd"


def test_an_unrelated_new_file_is_refused_as_unattributable(tmp_path: Path) -> None:
    """Another process's new file is never reported as this block; nothing is retried."""
    screen = FakeStoreScreen(stored_name="someone-elses-file.BDD")

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    message = str(raised.value)
    assert "committed once" in message
    assert "unknown" in message
    assert "someone-elses-file.BDD" in message
    # The single committed store is reported as committed, and never retried or renamed.
    assert screen.presses == [StripControl.DO_STORE]
    assert screen.store_names == ["mpx12-50profiles-manual-01"]
    assert screen.commits == 1
    assert screen.waits == 1


def test_an_unrelated_new_directory_is_refused_as_unattributable(
    tmp_path: Path,
) -> None:
    """The new-entry wait reports any new name; a directory is not a stored block."""
    screen = FakeStoreScreen(stored_name="new-folder", write_stored_file=False)
    target = tmp_path / "new-folder"
    target.mkdir()
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)
    assert "not a regular file" in str(raised.value)


def test_a_collision_that_appears_before_the_press_refuses_the_store(
    tmp_path: Path,
) -> None:
    """The name is re-read immediately before the press; a racing file wins, nothing is pressed."""
    screen = FakeStoreScreen()
    # The name appears after the initial check but before the pre-press re-read: the workflow
    # lists the directory twice, so a file created by the first strip read is seen by the second.
    original_strip_state = screen.strip_state
    created = {"done": False}

    def strip_state_then_race() -> StripState:
        if not created["done"]:
            (tmp_path / "mpx12-50profiles-manual-01.BDD").write_bytes(b"raced")
            created["done"] = True
        return original_strip_state()

    screen.strip_state = strip_state_then_race  # type: ignore[method-assign]

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "already taken" in str(raised.value)
    assert screen.presses == []


@pytest.mark.parametrize("field", ["store_timeout_s", "dialog_timeout_s"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, True])
def test_invalid_deadline_refuses_before_binding(tmp_path: Path, field, value) -> None:
    screen = FakeStoreScreen()
    with pytest.raises(AcquisitionError, match="finite positive"):
        store_completed(
            "block",
            tmp_path,
            declaration=declaration(),
            actuator=screen,
            enumerate_windows=lambda: (101,),
            **{field: value},
        )
    assert screen.bound == []
    assert screen.presses == []


@pytest.mark.parametrize("channels", [(True, 2), ("1", 2), (1.0, 2), None, 1])
def test_channel_identifiers_are_not_coerced(channels) -> None:
    with pytest.raises(ValidationError):
        declaration(channels=channels)


def test_invalid_declaration_refuses_before_binding(tmp_path: Path) -> None:
    screen = FakeStoreScreen()
    with pytest.raises(AcquisitionError, match="declaration"):
        store_completed(
            "block",
            tmp_path,
            declaration=None,
            actuator=screen,
            enumerate_windows=lambda: (101,),
        )
    assert screen.bound == []
    assert screen.presses == []


def test_second_window_before_press_refuses(tmp_path: Path) -> None:
    screen = FakeStoreScreen()
    windows = iter([(101,), (101, 202)])
    with pytest.raises(AcquisitionError, match="2 visible"):
        store_completed(
            "block",
            tmp_path,
            declaration=declaration(),
            actuator=screen,
            enumerate_windows=lambda: next(windows),
        )
    assert screen.presses == []


def test_cli_store_completed_uses_default_workflow_and_serializes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import json

    from udv_echo_process.cli import acquire_main

    screen = FakeStoreScreen()
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (101,))
    with pytest.raises(SystemExit) as exited:
        acquire_main(
            [
                "store-completed",
                "block",
                "--channel",
                "1",
                "2",
                "--profiles",
                "50",
                "--stated-by",
                "operator",
                "--store-dir",
                str(tmp_path),
                "--json",
            ]
        )
    assert exited.value.code == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["declaration"]["channels"] == [1, 2]
    assert report["declaration"]["profiles_per_channel"] == 50
    assert report["store"]["stored_name"] == "block.BDD"
    assert screen.bound == [101]
    assert screen.presses == [StripControl.DO_STORE]
    assert screen.commits == 1
    assert output.err == ""


def test_collision_clause_compares_stems_case_folded(tmp_path: Path) -> None:
    (tmp_path / "Block.BDD").write_bytes(b"x")
    assert collision_clause("block", tmp_path) is not None
    assert collision_clause("other", tmp_path) is None


# -------------------------------- the screen between the two checks, and the one warning


class ScriptedScreen(FakeStoreScreen):
    """The same window answering differently on each successive read: the screen moved.

    Each script is consumed one read at a time and its **last** value repeats, so a script of
    one value is a constant read and a script of two is "first check sees this, the second
    check sees that". The workflow reads the caption, the overlay and the strip twice (before
    the press and immediately before it), which is the window this class scripts.
    """

    def __init__(
        self,
        *,
        captions: Sequence[str] = (),
        overlays: Sequence[OverlayKind | None] = (),
        states: Sequence[StripState] = (),
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._captions = list(captions)
        self._overlays = list(overlays)
        self._states = list(states)
        self.caption_reads = 0
        self.overlay_reads = 0
        self.strip_reads = 0

    @staticmethod
    def _read(script: list, fallback):
        if not script:
            return fallback()
        return script.pop(0) if len(script) > 1 else script[0]

    def window_caption(self) -> str:
        self.caption_reads += 1
        return self._read(self._captions, super().window_caption)

    def peek_overlay(self) -> OverlayKind | None:
        self.overlay_reads += 1
        return self._read(self._overlays, super().peek_overlay)

    def strip_state(self) -> StripState:
        self.strip_reads += 1
        return self._read(self._states, super().strip_state)


def test_a_row_that_turns_three_button_between_the_checks_refuses_before_the_press(
    tmp_path: Path,
) -> None:
    """The completed row read first, an unmeasured three-button store row second: no press.

    The second read is the one that authorizes the gesture, so a row that gains a role between
    the checks makes a press a choice this command does not make — and a three-button row that
    is not the *measured* repeated-MPX row is that role change, not a completion.
    """
    screen = ScriptedScreen(
        states=[
            StripState(button_count=2, has_slider=True),
            StripState(button_count=3, has_slider=True),
        ]
    )

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "legacy three-button row" in str(raised.value)
    # Both checks ran: the first read accepted the row, the second one refused it.
    assert screen.strip_reads == 2
    assert screen.presses == []
    assert screen.store_names == []
    assert screen.commits == 0
    assert screen.waits == 0


def test_a_caption_that_turns_to_the_simulator_refuses_before_the_press(
    tmp_path: Path,
) -> None:
    """The instrument read first, the simulator read second: the store is never started."""
    screen = ScriptedScreen(captions=["UDOP DOP3010.43", "UDOP Simul 1.0"])

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "simulation" in str(raised.value)
    assert screen.caption_reads == 2
    assert screen.presses == []
    assert screen.store_names == []
    assert screen.commits == 0


def test_an_overlay_that_appears_at_the_second_check_refuses_before_the_press(
    tmp_path: Path,
) -> None:
    """No overlay at the first read, a Store dialog at the second: nothing is pressed or dismissed."""
    screen = ScriptedScreen(overlays=[None, OverlayKind.STORE_DIALOG])

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    assert "overlay is already up" in str(raised.value)
    assert screen.overlay_reads == 2
    assert screen.presses == []
    assert screen.store_names == []
    assert screen.answers == 0
    assert screen.commits == 0


def test_one_warning_before_the_dialog_is_answered_once_then_committed_once(
    tmp_path: Path,
) -> None:
    """One warning between the press and the Store dialog is answered once, and the store commits once."""
    screen = ScriptedScreen(
        overlays=[
            None,
            None,  # the two pre-press checks see no overlay
            OverlayKind.WARNING,  # first read after the press
            OverlayKind.STORE_DIALOG,  # and then the dialog the warning was hiding
        ]
    )

    result, screen = run(tmp_path, screen=screen)

    assert screen.presses == [StripControl.DO_STORE]
    assert screen.answers == 1
    # Two pre-press overlay reads, then the warning, then the dialog.
    assert screen.overlay_reads == 4
    assert screen.store_names == ["mpx12-50profiles-manual-01"]
    assert screen.commits == 1
    assert screen.waits == 1
    assert result.store.dialog_warnings_answered == 1
    assert result.store.commit_presses == 1
    assert result.store.stored_name == "mpx12-50profiles-manual-01.BDD"
    assert result.stored_path == tmp_path / "mpx12-50profiles-manual-01.BDD"


def test_a_second_warning_before_the_dialog_refuses_with_no_further_press_or_commit(
    tmp_path: Path,
) -> None:
    """A warning after the one answered warning refuses: one press, one answer, no commit.

    Policy as written: the second warning is left up — the workflow answers warnings once and
    does not dismiss, clear or retry around a second one, so nothing is pressed again and no
    name is written or committed.
    """
    screen = ScriptedScreen(
        overlays=[
            None,
            None,
            OverlayKind.WARNING,
            OverlayKind.WARNING,
        ]
    )

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen)

    message = str(raised.value)
    assert "second warning" in message
    assert "does not keep answering" in message
    assert screen.presses == [StripControl.DO_STORE]
    assert screen.answers == 1
    assert screen.store_names == []
    assert screen.commits == 0
    assert screen.waits == 0


class RecordingClock:
    """A stand-in for the module's ``time``: monotonic seconds that only ``sleep`` advances.

    Time is held in integer microseconds so the deadline comparison is exact rather than at the
    mercy of ``0.4 + 0.4 + …`` drift, which would otherwise buy one extra poll.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self._micros = round(start * 1_000_000)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self._micros / 1_000_000

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._micros += round(seconds * 1_000_000)


def test_a_missing_store_dialog_is_bounded_by_the_clock_not_a_wall_wait(
    tmp_path: Path, monkeypatch
) -> None:
    """No dialog ever appears: the wait ends on the injected clock, with one press and no commit.

    The module's polling seam is its own ``time``, so the deadline is exercised without any real
    sleep: every poll advances the fake clock by exactly :data:`DIALOG_POLL_S` and the refusal is
    the bounded one, not a short-circuit.
    """
    clock = RecordingClock()
    monkeypatch.setattr(workflow, "time", clock)
    screen = ScriptedScreen(overlays=[None])  # never a Store dialog, never a warning

    wall_started = time.monotonic()
    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen=screen, dialog_timeout_s=2.0)
    wall_elapsed = time.monotonic() - wall_started

    assert "the Store dialog did not open within 2 s" in str(raised.value)
    assert clock.sleeps == [workflow.DIALOG_POLL_S] * 5
    assert clock.monotonic() - 1000.0 == pytest.approx(2.0)
    # The bound was the clock's: the case never waited on the wall.
    assert wall_elapsed < 1.0
    assert screen.presses == [StripControl.DO_STORE]
    assert screen.answers == 0
    assert screen.store_names == []
    assert screen.commits == 0
    assert screen.waits == 0


def test_a_rewritten_working_directory_is_reported_with_its_before_and_after(
    tmp_path: Path,
) -> None:
    """The dialog showed another folder: the report carries both texts and says it wrote it."""
    elsewhere = "C:\\elsewhere"
    screen = FakeStoreScreen(rewrite_directory=True)

    result, screen = run(tmp_path, screen=screen)

    verification = result.store.directory_verification
    assert verification is not None
    assert verification.changed is True
    assert verification.before == elsewhere
    assert verification.after == str(tmp_path)
    # The scalar report fields restate the typed value rather than a note's wording.
    assert result.store.directory_rewritten is True
    assert result.store.working_directory == verification.after
    assert (
        f"read {elsewhere!r} and wrote {verification.after!r}" in result.store.summary()
    )
    assert screen.directories == [tmp_path]
    assert screen.commits == 1
    assert result.store.commit_presses == 1


def test_an_already_correct_working_directory_is_not_reported_as_rewritten(
    tmp_path: Path,
) -> None:
    """The field already held the caller's folder: ``before`` and ``after`` agree, nothing written."""
    screen = FakeStoreScreen()

    result, _ = run(tmp_path, screen=screen)

    verification = result.store.directory_verification
    assert verification is not None
    assert verification.changed is False
    assert verification.before == verification.after == str(tmp_path)
    assert result.store.directory_rewritten is False
    assert result.store.working_directory == str(tmp_path)
    assert "nothing was written" in result.store.summary()
