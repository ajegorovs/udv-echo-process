"""Contract tests for the actuator *driver* cycle — ``acquire/driver.py``.

``test_acquire_actuator.py`` pins the binding tables and the ported recipes.
This module pins the **cycle** those tables drive: the order the depth window is
written in, the overlay check that must precede every press, the
record -> stop -> store chain, the overwrite warning, and the states a point
cycle is allowed to leave the application in.

Everything here runs against a **self-contained in-memory application**
(:class:`FakeUdopApp`) driven through the :class:`Actuator` Protocol by
:class:`FakeActuator`, which records the exact call sequence. Nothing imports
the sibling test module, nothing touches ``pywinauto``, and no script posts
real input to the application running on the operator's desktop.

Why a fake and not the live driver: the contract is what a point cycle must
*observably do* — the order of writes, the guard before each press, the left
button on a warning, the refusal to start from a recording. Pinning those on a
recorded call sequence keeps the assertions valid for ``Win32Actuator``, whose
calls cannot be observed without a running DOP3010 (docs/16, ``udop-automation.md``
§§3-8).
"""

from __future__ import annotations

import ctypes
import inspect
import os
import time
import typing
from collections.abc import Iterable
from pathlib import Path

import pytest

from udv_echo_process.acquire.actuator import (
    OVERLAY_ANSWERS,
    PARAM_COLUMN_ORDER,
    PARAMETER_WRITE_ORDER,
    PRESS_HOLD_MS,
    STARTABLE_VIEWS,
    STORE_TIMEOUT_S,
    STRIP_BUTTON_ORDER,
    VIEW_TIMEOUT_S,
    Actuator,
    DialogControl,
    OverlayKind,
    ParamRole,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    ordered_writes,
    overlay_answer,
    press_index,
)
from udv_echo_process.acquire.config import ParameterSet

#: The simulated clock the fake advances on every strip poll. A point's duration
#: is therefore measured in *observations*, exactly like the live loop's.
POLL_INTERVAL_S = 0.02

#: One polling budget: the driver re-resolves the strip instead of sleeping on
#: the clock. ~12 polls per call.
POLL_S = 0.25

#: The budget the cycle gives a view change after a press.
VIEW_WAIT_S = 2.0

READY_THREE = StripState(button_count=3)
READY_FOUR = StripState(button_count=4)
RECORDING_ONE = StripState(button_count=1)
STORE_THREE = StripState(button_count=3, has_slider=True)
STORE_FOUR = StripState(button_count=4, has_slider=True)

#: The point used throughout: the finest rung of the ``c = 1460`` ladder.
POINT_NAME = "sw100-k1-161738"


class PointFailed(RuntimeError):
    """A point cycle that did not produce a stored file — never a silent skip."""


class FakeUdopApp:
    """The DOP3010's observable behaviour, in memory.

    Holds the strip's structure, the modal panels, the parameter column's text
    and a directory of stored files. Every structural fact is taken from the
    interface module's tables, so the fake and the real application are read
    through the same vocabulary.
    """

    def __init__(self, *, cap: int = 10_000, profile_period_s: float = 0.02) -> None:
        self.cap = cap
        self.profile_period_s = profile_period_s
        self.directory: Path | None = None
        self.payload = b"BDD" + bytes(96)

        self.strip = READY_THREE
        self.parameters: dict[ParamRole, str] = {}
        self.recording = False
        self.elapsed_s = 0.0
        self.profiles = 0
        self.polls = 0
        self.stop_presses = 0
        self.cap_warned = False
        self.layout_note: str | None = None

        #: Overlays to raise once the recording has this many profiles.
        self.pending: dict[int, list[OverlayKind]] = {}
        #: The topmost panel, if any: a warning sits *on top of* the store dialog.
        self.overlay: OverlayKind | None = None
        self.store_dialog_open = False
        self.name: str | None = None

        self.commit_attempts = 0
        self.stored: list[str] = []
        self.rejected_stores: list[str | None] = []
        self.replaced: list[str | None] = []
        self.raised: list[OverlayKind] = []
        self.raised_while_recording: list[OverlayKind] = []
        self.answered: list[OverlayKind] = []
        #: Presses that landed while a modal panel was up — posted clicks ignore
        #: modality (docs/16 §8), so this list must stay empty.
        self.blind_presses: list[StripControl] = []
        self.dialog_presses: list[DialogControl] = []
        #: The application has no ``WM_CLOSE`` path for its panels (§6): a
        #: popup closed that way wedges the menu loop until restart.
        self.close_attempts: list[str] = []

    # ------------------------------------------------------------- the scripted app

    def schedule(self, profiles: int, *kinds: OverlayKind) -> None:
        """Raise overlays once the recording has accumulated ``profiles`` profiles."""
        self.pending.setdefault(profiles, []).extend(kinds)

    def raise_overlay(self, kind: OverlayKind) -> None:
        self.overlay = kind
        self.raised.append(kind)
        if self.recording:
            self.raised_while_recording.append(kind)

    def poll(self) -> StripState:
        """One observation of the strip: the clock advances, panels can appear."""
        self.polls += 1
        if self.recording:
            self.elapsed_s += POLL_INTERVAL_S
            self.profiles = int(self.elapsed_s / self.profile_period_s)
            for at in sorted(p for p in self.pending if p <= self.profiles):
                for kind in self.pending.pop(at):
                    self.raise_overlay(kind)
            if self.profiles > self.cap and not self.cap_warned:
                self.cap_warned = True
                self.raise_overlay(OverlayKind.WARNING)
        return self.strip

    def press(self, control: StripControl) -> None:
        """A held press at the control's index in the *current* view (§5)."""
        if self.overlay is not None or self.store_dialog_open:
            self.blind_presses.append(control)
        if control is StripControl.RECORD:
            self.recording, self.elapsed_s, self.profiles = True, 0.0, 0
            self.strip = RECORDING_ONE
        elif control is StripControl.STOP:
            self.stop_presses += 1
            if self.stop_presses == 1 and self.profiles > self.cap:
                # Crossing the cap wedges the cycle: the recording keeps running
                # and the stop never reaches the store view (docs/16 §7).
                return
            self.recording = False
            self.strip = STORE_FOUR
        elif control is StripControl.DO_STORE:
            self.store_dialog_open = True
        elif control is StripControl.NEW_ACQUISITION:
            self.recording, self.store_dialog_open = False, False
            self.strip = READY_THREE
        elif control is StripControl.CLEAR_AND_RESTART:
            self.recording = False
            self.strip = READY_THREE

    def press_dialog(self, control: DialogControl) -> None:
        """Press one end of a dialog's bottom button pair (never a title, never a rect)."""
        if self.overlay is None:
            raise AssertionError("no dialog is up to press")
        self.dialog_presses.append(control)
        kind = self.overlay
        self.overlay = None
        self.answered.append(kind)
        if kind is OverlayKind.WARNING:
            if control is DialogControl.SAFE:
                # `No`: the existing file is left alone and the store is retried.
                self.rejected_stores.append(self.name)
            else:
                self.replaced.append(self.name)
                self._write_file()

    def answer_overlay(self) -> OverlayKind | None:
        """The topmost panel, if one is up. A warning stays up until its button is pressed."""
        if self.overlay is not None:
            return self.overlay
        if self.store_dialog_open:
            return OverlayKind.STORE_DIALOG
        return None

    def commit_store(self) -> None:
        """Press the Store dialog's rightmost button (``Do store``)."""
        self.commit_attempts += 1
        if self.name is None or self.directory is None:
            raise AssertionError("the Store dialog has no name to commit")
        if (self.directory / f"{self.name}.BDD").exists():
            # One geometry serves every warning, so this is `already exists -> [No] [Yes]`.
            self.raise_overlay(OverlayKind.WARNING)
            return
        self._write_file()

    def _write_file(self) -> None:
        assert self.directory is not None and self.name is not None
        target = self.directory / f"{self.name}.BDD"
        target.write_bytes(self.payload)
        self.stored.append(target.name)
        self.store_dialog_open = False
        self.recording = False
        self.strip = READY_THREE


class FakeActuator:
    """An in-memory :class:`Actuator` over :class:`FakeUdopApp`.

    Records the exact call sequence in ``calls`` so a test can assert the order
    the cycle's actions were taken in, not merely its final state.
    """

    def __init__(
        self,
        app: FakeUdopApp | None = None,
        *,
        directory: Path | None = None,
    ) -> None:
        self.app = FakeUdopApp() if app is None else app
        self.directory = Path(directory) if directory is not None else Path("capture")
        #: The action log: reads are not actions and are not recorded here.
        self.calls: list[tuple] = []
        self.presses: list[tuple[int, StripControl]] = []
        self.names_set: list[str] = []
        self.stored: Path | None = None
        self.outcome: tuple[str, str] = ("pending", "")

    # ------------------------------------------------------------- the Protocol

    def layout_note(self) -> str | None:
        return self.app.layout_note

    def read_parameter(self, role: ParamRole) -> str:
        return self.app.parameters.get(role, "")

    def write_parameter(self, role: ParamRole, value: str) -> None:
        self.app.parameters[role] = value
        self.calls.append(("write_parameter", role.value, value))

    def strip_state(self) -> StripState:
        return self.app.strip

    def wait_for_view(
        self, views: Iterable[StripView], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        wanted = tuple(views)
        state = self.app.strip
        for _ in range(max(1, int(round(timeout_s / POLL_INTERVAL_S)))):  # noqa: RUF046
            state = self.app.poll()  # the strip is always observed, never slept on
            if state.view in wanted:
                break
        self.calls.append(("wait_for_view", tuple(v.value for v in wanted), timeout_s))
        return state

    def press(self, control: StripControl) -> None:
        index = self.strip_state().index_of(control)  # re-resolved: the panel morphs
        self.app.press(control)
        self.presses.append((index, control))
        self.calls.append(("press", index, control.value))

    def answer_overlay(self) -> OverlayKind | None:
        kind = self.app.answer_overlay()
        self.calls.append(("answer_overlay", None if kind is None else kind.value))
        return kind

    def set_store_name(self, name: str) -> None:
        self.app.name = name
        self.names_set.append(name)
        self.calls.append(("set_store_name", name))

    def commit_store(self) -> None:
        self.app.commit_store()
        self.calls.append(("commit_store",))

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        directory = Path(directory)
        known_names = {Path(name).name for name in known}
        for _ in range(max(1, int(round(timeout_s / POLL_INTERVAL_S)))):  # noqa: RUF046
            fresh = sorted(
                p.name for p in directory.iterdir() if p.name not in known_names
            )
            if fresh:
                self.calls.append(("wait_for_stored_file", fresh[0], timeout_s))
                return directory / fresh[0]
            self.app.poll()
        self.calls.append(("wait_for_stored_file", None, timeout_s))
        raise PointFailed(f"no new file appeared in {directory}")

    # ------------------------------------------------------------ the cycle itself

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.app.directory = directory
        if not self.app.strip.is_startable:
            # Never from `recording`: a leftover recording is stored under the
            # next point's name (docs/16 §15b).
            self.outcome = ("refused", self.app.strip.view.value)
            raise PointFailed(f"cannot start from view {self.app.strip.view.value}")
        try:
            stored = self._run_point(name, duration_s, directory, timeout_s)
        except PointFailed as exc:
            self._recover()
            self.outcome = ("failed", str(exc))
            raise
        self.stored = stored
        self.outcome = ("stored", stored.name)
        return stored

    def _run_point(
        self, name: str, duration_s: float, directory: Path, timeout_s: float
    ) -> Path:
        state = self.wait_for_view(STARTABLE_VIEWS, timeout_s=POLL_S)
        if not state.is_startable:
            raise PointFailed(f"cannot start from view {state.view.value}")
        if state.view is StripView.STORE:
            self._guard()
            self.press(StripControl.NEW_ACQUISITION)  # dismiss the store prompt
            self.wait_for_view((StripView.READY,), timeout_s=POLL_S)
        self._guard()
        self.press(StripControl.RECORD)
        self._hold(duration_s)
        self._guard()
        self.press(StripControl.STOP)
        state = self.wait_for_view((StripView.STORE,), timeout_s=VIEW_WAIT_S)
        if state.view is not StripView.STORE:
            raise PointFailed(f"Stop did not reach the store view ({state.view.value})")
        known = sorted(p.name for p in directory.iterdir())
        self._guard()
        self.press(StripControl.DO_STORE)  # opens the Store dialog
        return self._store(name, directory, known, timeout_s)

    def _hold(self, duration_s: float) -> None:
        """Wait out the point by polling the strip — never a blind sleep (§8)."""
        while self.app.elapsed_s < duration_s:
            self._guard()
            state = self.wait_for_view((StripView.RECORDING,), timeout_s=POLL_S)
            if state.view is not StripView.RECORDING:
                raise PointFailed(
                    f"the strip left the recording view ({state.view.value}) "
                    f"before {duration_s} s"
                )

    def _store(
        self, name: str, directory: Path, known: list[str], timeout_s: float
    ) -> Path:
        candidate = name
        for attempt in (1, 2):
            self._guard()  # never press with a panel up
            self.set_store_name(candidate)
            self._guard()
            self.commit_store()
            if self._guard() is OverlayKind.WARNING:
                # `already exists -> [No] [Yes]`: No is the left button, and the
                # store is retried under a fresh name (§4.7).
                candidate = f"{name}-{attempt + 1}"
                continue
            return self.wait_for_stored_file(
                directory, known=known, timeout_s=timeout_s
            )
        raise PointFailed(f"the store of {name!r} never completed")

    def _recover(self) -> None:
        """Leave the application in a known-good state after a failed point (§7)."""
        for _ in range(6):
            state = self.app.strip
            if state.is_startable and not self.app.recording:
                return
            self._guard()
            if state.view is StripView.RECORDING:
                self.press(StripControl.STOP)  # end the leftover recording
                continue
            self.press(StripControl.NEW_ACQUISITION)  # discard the block, back to ready
        raise PointFailed("the strip would not return to a startable view")

    def _guard(self) -> OverlayKind | None:
        """Answer an overlay if one is up, before whatever comes next.

        A warning is answered with :func:`overlay_answer`'s button — the LEFT one,
        so an existing file is never silently replaced. The Store dialog is not
        dismissed here: the caller owns its name and its commit.
        """
        kind = self.answer_overlay()
        if kind is OverlayKind.WARNING:
            self.press_dialog(overlay_answer(kind))
        return kind

    def press_dialog(self, control: DialogControl | None) -> None:
        assert control is not None
        self.app.press_dialog(control)
        self.calls.append(("press_dialog", control.value))


# ------------------------------------------------------------------------ helpers


def as_protocol(fake: FakeActuator) -> Actuator:
    """Hand the fake back as the interface, so every call binds to the contract."""
    assert isinstance(fake, Actuator)
    return fake


def actions(fake: FakeActuator, *names: str) -> list[tuple]:
    """The recorded calls whose name is in ``names``, in order."""
    return [call for call in fake.calls if call[0] in names]


def protocol_methods() -> list[str]:
    """The public methods the :class:`Actuator` Protocol requires."""
    return sorted(
        name
        for name, member in inspect.getmembers(Actuator)
        if not name.startswith("_") and callable(member)
    )


def make_fake(directory: Path | None = None, **app_kwargs) -> FakeActuator:
    return FakeActuator(FakeUdopApp(**app_kwargs), directory=directory)


# ------------------------------------------------------- the interface and the fake


def test_the_fake_satisfies_the_whole_actuator_interface() -> None:
    """The interface must be satisfiable by pure Python — that is why it is a Protocol."""
    fake = FakeActuator()
    assert isinstance(fake, Actuator)
    assert not isinstance(object(), Actuator)

    required = protocol_methods()
    assert "record_and_store" in required and "press" in required
    missing = [name for name in required if not callable(getattr(fake, name, None))]
    assert missing == []

    for name in required:
        fake_method = getattr(FakeActuator, name)
        protocol_method = getattr(Actuator, name)
        assert list(inspect.signature(fake_method).parameters) == list(
            inspect.signature(protocol_method).parameters
        ), name
        hints = typing.get_type_hints(fake_method)
        assert "return" in hints, name
    assert typing.get_type_hints(FakeActuator.record_and_store)["return"] is Path
    assert typing.get_type_hints(FakeActuator.press)["return"] is type(None)


# ---------------------------------------------------- parameter write order (§3)


def test_parameters_are_written_resolution_first_and_gates_last(tmp_path: Path) -> None:
    """Writing gates first gets them recomputed away: 805 requested -> 474 accepted."""
    assert PARAMETER_WRITE_ORDER == (ParamRole.RESOLUTION, ParamRole.GATES)
    # The column shows gates *above* resolution, so the write order is not the
    # visual order — it is the dependency order the application imposes.
    assert PARAM_COLUMN_ORDER.index(ParamRole.GATES) < PARAM_COLUMN_ORDER.index(
        ParamRole.RESOLUTION
    )

    parameters = ParameterSet(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        resolution_mm=0.121667,
        gates=805,
    )
    writes = ordered_writes(parameters)
    assert [role for role, _ in writes] == [ParamRole.RESOLUTION, ParamRole.GATES]
    assert writes[0][1] == "0.122"  # the sidebar's 3 decimals
    assert writes[1][1] == "805"

    fake = make_fake(tmp_path)
    actuator = as_protocol(fake)
    for role, value in writes:
        actuator.answer_overlay()  # a panel up would swallow the write too
        actuator.write_parameter(role, value)

    assert [call[1] for call in actions(fake, "write_parameter")] == [
        "resolution_mm",
        "gates",
    ]
    assert actions(fake, "write_parameter")[-1][1] == ParamRole.GATES.value  # gate-last
    assert actuator.read_parameter(ParamRole.RESOLUTION) == "0.122"
    assert actuator.read_parameter(ParamRole.GATES) == "805"
    assert actuator.read_parameter(ParamRole.PRF) == ""


# -------------------------------------------- the overlay guard before every press


def test_every_press_is_preceded_by_an_overlay_check(tmp_path: Path) -> None:
    """A posted click ignores modality (docs/16 §8), so the guard is not optional."""
    fake = make_fake(tmp_path)
    fake.app.schedule(12, OverlayKind.WARNING)  # a panel appears mid-recording
    actuator = as_protocol(fake)
    actuator.record_and_store(POINT_NAME, 1.0, tmp_path)

    assert fake.calls, "the cycle was exercised through the Protocol"
    pressed = [
        i for i, call in enumerate(fake.calls) if call[0] in ("press", "press_dialog")
    ]
    assert pressed, "the cycle pressed something"
    for i in pressed:
        assert fake.calls[i - 1][0] == "answer_overlay", fake.calls[i - 1]

    assert OverlayKind.WARNING in fake.app.raised
    assert OverlayKind.WARNING in fake.app.answered
    # Answered *via* overlay_answer: the left button of the pair, never a window close.
    assert overlay_answer(OverlayKind.WARNING) is DialogControl.SAFE
    assert fake.app.dialog_presses == [DialogControl.SAFE]
    # The Store dialog is not an overlay to dismiss — nothing is pressed for it.
    assert OVERLAY_ANSWERS[OverlayKind.STORE_DIALOG] is None
    assert ("answer_overlay", OverlayKind.STORE_DIALOG.value) in fake.calls
    # ...and the interface offers no way to close a window at all (docs/16 §6).
    assert [name for name in dir(Actuator) if "close" in name.lower()] == []
    assert [name for name in dir(FakeActuator) if "close" in name.lower()] == []
    assert fake.app.close_attempts == []
    assert fake.app.blind_presses == []
    assert fake.app.overlay is None  # never left behind: it traps the operator (§9)


# --------------------------------------------- the strip's views and press binding


@pytest.mark.parametrize(
    ("button_count", "has_slider", "expected"),
    [
        (1, False, StripView.RECORDING),
        (3, False, StripView.READY),
        (4, False, StripView.READY),
        (3, True, StripView.STORE),
        (4, True, StripView.STORE),
        (0, False, StripView.UNKNOWN),
        (2, False, StripView.UNKNOWN),
    ],
)
def test_the_strip_view_is_recognised_structurally(
    button_count: int, has_slider: bool, expected: StripView
) -> None:
    assert classify_strip_view(button_count, has_slider) is expected
    assert StripState(button_count=button_count, has_slider=has_slider).view is expected


def test_the_documented_button_rows_are_the_only_ones_that_press() -> None:
    """Every row the driver may bind to is a documented ``(view, count)`` pair."""
    assert set(STRIP_BUTTON_ORDER) == {
        (StripView.RECORDING, 1),
        (StripView.READY, 3),
        (StripView.READY, 4),
        (StripView.STORE, 3),
        (StripView.STORE, 4),
    }
    assert StripState(button_count=2).is_startable is False
    assert STARTABLE_VIEWS == (StripView.READY, StripView.STORE)


@pytest.mark.parametrize(
    ("view", "button_count", "control", "expected_index"),
    [
        (StripView.RECORDING, 1, StripControl.STOP, 0),
        (StripView.READY, 3, StripControl.PAUSE, 0),
        (StripView.READY, 3, StripControl.RECORD, 1),
        (StripView.READY, 3, StripControl.CLEAR_AND_RESTART, 2),
        (StripView.READY, 4, StripControl.RECORD, 1),  # `Record` stays at index 1
        (StripView.READY, 4, StripControl.DO_STORE, 2),
        (StripView.STORE, 3, StripControl.NEW_ACQUISITION, 0),
        (StripView.STORE, 3, StripControl.DO_STORE, 1),
        (StripView.STORE, 4, StripControl.DO_STORE, 1),
        (StripView.STORE, 4, StripControl.REMOVE_CURRENT_BLOCK, 3),
    ],
)
def test_a_press_binds_to_its_index_in_the_current_view(
    view: StripView, button_count: int, control: StripControl, expected_index: int
) -> None:
    """134 px vs 138 px is too close to identify a button (§5): the index is the binding."""
    fake = make_fake()
    fake.app.strip = StripState(
        button_count=button_count, has_slider=view is StripView.STORE
    )
    actuator = as_protocol(fake)
    actuator.answer_overlay()
    actuator.press(control)

    assert press_index(view, control, button_count) == expected_index
    assert fake.presses == [(expected_index, control)]
    assert fake.calls[-1] == ("press", expected_index, control.value)
    assert fake.app.blind_presses == []
    # A press is a *held* press at that index — an instant down/up is ignored (§1).
    assert PRESS_HOLD_MS == 180


# --------------------------------------------------------------- the point cycle


@pytest.mark.parametrize(
    ("start", "expected_presses"),
    [
        (
            READY_THREE,
            [
                (1, StripControl.RECORD),
                (0, StripControl.STOP),
                (1, StripControl.DO_STORE),
            ],
        ),
        (
            STORE_FOUR,
            [
                (0, StripControl.NEW_ACQUISITION),
                (1, StripControl.RECORD),
                (0, StripControl.STOP),
                (1, StripControl.DO_STORE),
            ],
        ),
    ],
    ids=["from-ready", "from-store-view"],
)
def test_a_point_cycle_records_stops_stores_and_reports_a_new_file(
    tmp_path: Path, start: StripState, expected_presses: list[tuple[int, StripControl]]
) -> None:
    """``Record -> duration -> Stop -> store view -> Do store -> name -> stored``."""
    fake = make_fake(tmp_path)
    fake.app.strip = start
    actuator = as_protocol(fake)

    path = actuator.record_and_store(POINT_NAME, 1.0, tmp_path)

    assert fake.outcome[0] == "stored"
    assert fake.presses == expected_presses
    assert fake.names_set == [POINT_NAME]
    assert fake.app.commit_attempts == 1
    # The duration was held by observing the strip, not by one long wait.
    assert len(actions(fake, "wait_for_view")) >= 4
    assert fake.app.polls >= int(1.0 / POLL_INTERVAL_S)
    # The new file is *reported*, and it is the only new name in the directory.
    reported = [call for call in actions(fake, "wait_for_stored_file")]
    assert reported and reported[-1][1] == f"{POINT_NAME}.BDD"
    assert path == tmp_path / f"{POINT_NAME}.BDD"
    assert path.read_bytes() == fake.app.payload
    # The dialog is closed and the strip is back in a startable view.
    assert fake.app.store_dialog_open is False
    assert fake.app.overlay is None
    assert fake.app.strip.is_startable is True
    assert fake.app.recording is False
    assert fake.app.blind_presses == []


def test_an_existing_file_raises_the_overwrite_warning_and_the_left_button_wins(
    tmp_path: Path,
) -> None:
    """`No` is the left button: the existing file is never silently replaced (§4.7)."""
    fake = make_fake(tmp_path)
    actuator = as_protocol(fake)
    existing = tmp_path / f"{POINT_NAME}.BDD"
    existing.write_bytes(b"seed")

    path = actuator.record_and_store(POINT_NAME, 1.0, tmp_path)

    assert fake.outcome == ("stored", f"{POINT_NAME}-2.BDD")
    assert fake.app.commit_attempts == 2  # retried exactly once
    assert fake.names_set == [POINT_NAME, f"{POINT_NAME}-2"]  # a fresh name
    assert fake.app.raised.count(OverlayKind.WARNING) == 1
    assert fake.app.dialog_presses == [DialogControl.SAFE]  # the LEFT button
    assert fake.app.rejected_stores == [POINT_NAME]
    assert fake.app.replaced == []
    assert existing.read_bytes() == b"seed"  # untouched
    assert path.name == f"{POINT_NAME}-2.BDD"
    assert fake.app.overlay is None  # the warning was answered, not left up
    assert fake.app.strip.is_startable is True
    assert fake.app.blind_presses == []


def test_a_point_that_never_reaches_the_store_view_is_failed_and_not_stored(
    tmp_path: Path,
) -> None:
    """The cap case: the stop never reaches the store view, so the point is invalid."""
    fake = make_fake(tmp_path, cap=100, profile_period_s=0.02)
    actuator = as_protocol(fake)

    with pytest.raises(PointFailed, match="store view"):
        actuator.record_and_store(POINT_NAME, 3.0, tmp_path)  # >cap x period profiles

    assert fake.outcome[0] == "failed"
    # Reported as failed, and NOT stored: no name, no commit, no file.
    assert actions(fake, "set_store_name") == []
    assert actions(fake, "commit_store") == []
    assert actions(fake, "wait_for_stored_file") == []
    assert fake.app.commit_attempts == 0
    assert fake.app.stored == []
    assert [p.name for p in tmp_path.iterdir()] == []
    # The cap condition was observed while recording, not discovered afterwards.
    assert fake.app.cap_warned is True
    assert OverlayKind.WARNING in fake.app.raised_while_recording
    assert fake.app.overlay is None
    # ...and the actuator returns to a known-good state: no longer recording, with
    # the leftover block stopped (the next cycle dismisses it from the store view).
    assert fake.app.recording is False
    assert fake.app.strip.is_startable is True
    assert fake.presses == [
        (1, StripControl.RECORD),
        (0, StripControl.STOP),  # the stop that never reached the store view
        (0, StripControl.STOP),  # the recovery: end the leftover recording
    ]
    assert fake.app.blind_presses == []

    # The recovered state is genuinely startable, and a recording never is.
    fake.app.strip = RECORDING_ONE
    fake.app.recording = True
    before = list(fake.presses)
    with pytest.raises(PointFailed, match="recording"):
        actuator.record_and_store(POINT_NAME, 1.0, tmp_path)
    assert fake.outcome[0] == "refused"
    assert fake.presses == before  # nothing was pressed from a running recording


def test_waiting_is_polling_and_never_a_blind_sleep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop observes the strip; a panel appearing mid-recording is answered."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: slept.append(seconds))

    fake = make_fake(tmp_path)
    fake.app.schedule(12, OverlayKind.WARNING)  # a panel appears mid-recording
    actuator = as_protocol(fake)

    path = actuator.record_and_store(POINT_NAME, 2.0, tmp_path)

    assert slept == []  # the fake's loop, like the driver's, never sleeps
    waits = actions(fake, "wait_for_view")
    assert len(waits) >= 4  # the loop kept looking
    assert (
        max(call[2] for call in waits) <= VIEW_WAIT_S
    )  # short budgets, not one long wait
    assert fake.app.polls >= int(2.0 / POLL_INTERVAL_S)  # the strip was re-resolved
    # The overlay that appeared mid-recording was seen and answered, not pressed through.
    assert fake.app.raised_while_recording == [OverlayKind.WARNING]
    assert OverlayKind.WARNING in fake.app.answered
    assert fake.app.blind_presses == []
    assert fake.app.overlay is None
    assert fake.presses == [
        (1, StripControl.RECORD),
        (0, StripControl.STOP),
        (1, StripControl.DO_STORE),
    ]
    assert path.name == f"{POINT_NAME}.BDD"


# ------------------------------------------------ the live driver, if it exists yet


@pytest.fixture(scope="module")
def win32_actuator_type() -> type:
    """``Win32Actuator`` when the Windows driver module is present (it may not be)."""
    module = pytest.importorskip(
        "udv_echo_process.acquire.driver",
        reason="the Windows driver lands separately; there is nothing to construct yet",
    )
    actuator_type = getattr(module, "Win32Actuator", None)
    if actuator_type is None:
        pytest.skip("udv_echo_process.acquire.driver defines no Win32Actuator yet")
    return actuator_type


def test_the_windows_actuator_is_constructible_without_sending_a_message(
    win32_actuator_type: type,
) -> None:
    """Constructing it must not touch the application on the operator's desktop."""
    try:
        actuator = win32_actuator_type()
    except Exception as exc:  # noqa: BLE001 - a sibling module still being written
        pytest.skip(
            f"Win32Actuator() is not constructible in this environment: {exc!r}"
        )
    assert isinstance(actuator, Actuator)


# ------------------------------- the channel knob and the store directory (§12b)

driver = pytest.importorskip(
    "udv_echo_process.acquire.driver",
    reason="the Windows driver lands separately; its cycle cannot be exercised yet",
)

#: The fake window's handles. They are deliberately *not* meaningful: the driver may
#: not key on a control id (ids change on every launch), so nothing here depends on
#: their value either.
HWND_MENU_BAR, HWND_PARAMETERS = 1, 2
HWND_POPUP, HWND_ENTRY_DEFAULTS, HWND_ENTRY_OPERATING = 3, 4, 5
HWND_LEFT_PANEL, HWND_LEFT_VALUE, HWND_LEFT_COMBO = 6, 7, 8
HWND_DIALOG, HWND_DIALOG_VALUE_BUTTON, HWND_DIALOG_COMBO = 9, 10, 11
HWND_DIALOG_CANCEL, HWND_DIALOG_ACCEPT = 12, 13
HWND_STORE_DIALOG, HWND_STORE_DIR, HWND_STORE_NAME = 14, 15, 16
HWND_STORE_CANCEL, HWND_STORE_DOSTORE = 17, 18
HWND_DECOY_COMBO = 19


def _node(
    hwnd: int,
    cls: str,
    text: str = "",
    *,
    left: int = 0,
    top: int = 0,
    w: int = 60,
    h: int = 20,
) -> dict:
    """One control, in the shape ``_resolve`` produces."""
    return {
        "hwnd": hwnd,
        "cls": cls,
        "text": text,
        "rect": (left, top, left + w, top + h),
        "left": left,
        "top": top,
        "w": w,
        "h": h,
        "id": 0,  # ids are never an identity here
    }


class FakeUdopWindow:
    """The pieces of the running application the channel and store paths touch.

    It holds the two panels the driver must distinguish (the sidebar's parameter
    column and the ``Operating parameters`` dialog), the store dialog's two edits,
    and the application's *own* channel. Nothing here is a window: the driver's
    message layer is what is faked, and every fact the driver may key on (class,
    nesting, item list, text) is present in the structure it resolves.

    Scripted failures, each one a documented hazard:

    - ``combo_writes_ignored`` — a selection that never reaches the application
      (its combo stays where it was): ``CB_SETCURSEL`` did nothing;
    - ``combo_control_only`` — the combo's own state moves while the application
      keeps its channel, which is the "a combo write can silently apply" case
      (docs/16 §2);
    - ``text_writes_ignored`` — a text field that paints the new value and keeps
      its own (``WM_SETTEXT`` without the commit, docs/14 §4).
    """

    def __init__(
        self,
        *,
        channel: int = 1,
        directory: str = "",
        combo_writes_ignored: bool = False,
        combo_control_only: bool = False,
        text_writes_ignored: bool = False,
    ) -> None:
        self.channel = channel  # the application's own channel, 1-based
        self.directory = directory
        self.combo_writes_ignored = combo_writes_ignored
        self.combo_control_only = combo_control_only
        self.text_writes_ignored = text_writes_ignored

        self.menu_open = False
        self.dialog_open = False
        self.store_open = False
        self.combo_index = channel - 1
        self.combo_text = str(channel)
        self.name_text = ""
        self.strip = READY_THREE
        self.recording = False
        #: The observable order of everything that happened.
        self.events: list[tuple] = []
        #: The panel the driver is told is open at the store step.
        self.store_panel = _node(
            HWND_STORE_DIALOG, "TSp_Panel", "Store", left=300, top=300, w=560, h=300
        )
        self.store_buttons = (
            _node(HWND_STORE_CANCEL, "TSp_Button", "Cancel", left=700, top=560),
            _node(HWND_STORE_DOSTORE, "TSp_Button", "Do store", left=790, top=560),
        )

    # ------------------------------------------------------------- the structure

    def nodes(self) -> list[dict]:
        """Every control currently visible, in enumeration order (not screen order)."""
        out = [
            _node(HWND_MENU_BAR, "TSp_Panel", "", top=0, h=24, w=900),
            _node(HWND_PARAMETERS, "TSp_Button", "Parameters", left=120, top=2, w=80),
            _node(HWND_LEFT_PANEL, "TSp_Panel", "", top=30, w=200, h=600),
            _node(HWND_LEFT_VALUE, "TSp_Value_Button", "", left=10, top=200, w=180),
            _node(HWND_LEFT_COMBO, "TComboBox", "1", left=40, top=202, w=120),
            # A decoy: a combo the sidebar nests the same way, listing the same
            # channels. It must never be the one that is selected.
            _node(HWND_DECOY_COMBO, "TComboBox", "1", left=40, top=260, w=120),
        ]
        if self.menu_open:
            out += [
                _node(HWND_POPUP, "TSp_Panel", "", left=120, top=24, w=200, h=80),
                # `Default parameters` is enumerated FIRST — the order the reference
                # implementation walked into when it matched by position (docs §6).
                _node(HWND_ENTRY_DEFAULTS, "TSp_Button", "Default parameters", left=124, top=30),
                _node(
                    HWND_ENTRY_OPERATING,
                    "TSp_Button",
                    "Operating parameters",
                    left=124,
                    top=54,
                ),
            ]
        if self.dialog_open:
            out += [
                _node(HWND_DIALOG, "TSp_Panel", "", left=300, top=100, w=360, h=200),
                _node(HWND_DIALOG_VALUE_BUTTON, "TSp_Value_Button", "Channel", left=310, top=140),
                _node(HWND_DIALOG_COMBO, "TComboBox", self.combo_text, left=340, top=142, w=120),
                _node(HWND_DIALOG_CANCEL, "TSp_Button", "Cancel", left=520, top=260),
                _node(HWND_DIALOG_ACCEPT, "TSp_Button", "Accept", left=600, top=260),
            ]
        if self.store_open:
            out += [
                self.store_panel,
                _node(HWND_STORE_DIR, "TEdit", self.directory, left=380, top=350, w=400),
                _node(HWND_STORE_NAME, "TEdit", self.name_text, left=380, top=390, w=400),
                *self.store_buttons,
            ]
        return out

    def parent_of(self, hwnd: int) -> int:
        """The fake's own parent map (the windows' real nesting)."""
        if hwnd in (HWND_ENTRY_DEFAULTS, HWND_ENTRY_OPERATING):
            return HWND_POPUP
        if hwnd == HWND_POPUP or hwnd == HWND_PARAMETERS:
            return HWND_MENU_BAR
        if hwnd in (HWND_LEFT_COMBO, HWND_DECOY_COMBO):
            return HWND_LEFT_VALUE
        if hwnd == HWND_LEFT_VALUE:
            return HWND_LEFT_PANEL
        if hwnd in (HWND_DIALOG_VALUE_BUTTON, HWND_DIALOG_CANCEL, HWND_DIALOG_ACCEPT):
            return HWND_DIALOG
        if hwnd == HWND_DIALOG_COMBO:
            return HWND_DIALOG_VALUE_BUTTON
        if hwnd in (HWND_STORE_DIR, HWND_STORE_NAME, *[b["hwnd"] for b in self.store_buttons]):
            return HWND_STORE_DIALOG
        return 0  # the main window

    # --------------------------------------------------------- the application

    def combo_items(self, hwnd: int) -> tuple[str, ...]:
        return driver.channel_items() if hwnd in (HWND_DIALOG_COMBO, HWND_LEFT_COMBO, HWND_DECOY_COMBO) else ()

    def open_dialog(self) -> None:
        """The dialog appears showing the application's own channel."""
        self.dialog_open = True
        self.combo_index = self.channel - 1
        self.combo_text = str(self.channel)
        self.events.append(("dialog", "open", self.channel))

    def select(self, index: int) -> None:
        """``CB_SETCURSEL`` + ``CBN_SELCHANGE``, with the scripted failure modes."""
        self.events.append(("combo", "select", index))
        if self.combo_writes_ignored:
            return  # the control never moves
        self.combo_index = index
        self.combo_text = driver.channel_items()[index]
        if not self.combo_control_only:
            self.channel = index + 1  # the combo commits on the change notification

    def accept(self) -> None:
        self.events.append(("dialog", "accept"))
        self.dialog_open = False

    def cancel(self) -> None:
        self.events.append(("dialog", "cancel"))
        self.dialog_open = False

    def write_text(self, hwnd: int, text: str) -> None:
        self.events.append(("text", hwnd, text))
        if self.text_writes_ignored:
            return
        if hwnd == HWND_STORE_DIR:
            self.directory = text
        elif hwnd == HWND_STORE_NAME:
            self.name_text = text


class FakeDriver(driver.Win32Actuator):
    """``Win32Actuator`` over :class:`FakeUdopWindow`: every message layer faked.

    What is *not* faked is the logic under test — the resolution walk, the channel
    combo's identity, the read-back, the working-directory assertion and the order
    the cycle takes them in. Nothing here posts input to any window.
    """

    def __init__(self, app: FakeUdopWindow, **kwargs) -> None:
        super().__init__(**kwargs)
        self.app = app

    # ----------------------------------------------------------- the window layer

    def _resolve(self) -> dict:
        nodes = self.app.nodes()
        raw = [{k: v for k, v in node.items() if not k.startswith("_")} for node in nodes]
        by_hwnd = {node["hwnd"]: node for node in nodes}
        handles = [HWND_MENU_BAR, HWND_LEFT_PANEL]
        if self.app.dialog_open:
            handles.append(HWND_DIALOG)
        panels = [by_hwnd[hwnd] for hwnd in handles if hwnd in by_hwnd]
        return {
            "window": 0,
            "raw": raw,
            "parent_of": {node["hwnd"]: self.app.parent_of(node["hwnd"]) for node in nodes},
            "panels": sorted(panels, key=lambda p: p["top"]),
            "left_panel": by_hwnd.get(HWND_LEFT_PANEL),
            "menu": {"Parameters": by_hwnd.get(HWND_PARAMETERS)},
            "open_popup": self.app.menu_open,
            "value_dialogs": set(),
            "browse_dialogs": set(),
            "strip_panel": None,
        }

    def _children_of(self, parent: int, roles: dict) -> list[dict]:
        return [k for k in roles["raw"] if roles["parent_of"].get(k["hwnd"]) == parent]

    def _hover(self, hwnd: int) -> None:
        assert hwnd == HWND_PARAMETERS
        self.app.menu_open = True
        self.app.events.append(("hover", "Parameters"))

    def _click_hold(self, hwnd: int, hold_ms: int = PRESS_HOLD_MS) -> None:
        if hwnd == HWND_ENTRY_OPERATING:
            self.app.menu_open = False
            self.app.events.append(("click", "Operating parameters"))
            self.app.open_dialog()
        elif hwnd == HWND_ENTRY_DEFAULTS:
            raise AssertionError("the driver pressed `Default parameters`")
        elif hwnd == HWND_DIALOG_ACCEPT:
            self.app.accept()
        elif hwnd == HWND_DIALOG_CANCEL:
            self.app.cancel()
        else:
            self.app.events.append(("press", hwnd))

    def _send(self, hwnd: int, msg: int, wp: int = 0, lp: int = 0, timeout_ms: int = 0) -> int:
        """The two combo read-backs, answered the way the real control answers."""
        if msg == driver.CB_GETCURSEL:
            return self.app.combo_index if hwnd == HWND_DIALOG_COMBO and self.app.dialog_open else 0xFFFF_FFFF_FFFF_FFFF
        if msg == driver.CB_GETCOUNT:
            return len(self.app.combo_items(hwnd))
        if msg == driver.CB_GETLBTEXT:
            text = self.app.combo_items(hwnd)[wp]
            ctypes.memmove(lp, (text + "\x00").encode("utf-16-le"), 2 * (len(text) + 1))
            return len(text)
        raise AssertionError(f"unexpected message {msg:#x}")

    def _get_text(self, hwnd: int) -> str:
        for node in self.app.nodes():
            if node["hwnd"] == hwnd:
                return node["text"]
        return ""

    def _set_text_commit(self, hwnd: int, text: str, parent: int | None = None) -> None:
        self.app.write_text(hwnd, text)

    def _combo_select(self, hwnd: int, index: int, parent: int | None = None) -> None:
        assert hwnd == HWND_DIALOG_COMBO, hwnd
        self.app.select(index)

    def _require_store_dialog(self) -> tuple[dict, list[dict]]:
        roles = self._resolve()
        return self.app.store_panel, self._children_of(HWND_STORE_DIALOG, roles)

    # ------------------------------------------------- the rest of the point cycle

    def layout_note(self) -> str | None:
        return None

    def strip_state(self) -> StripState:
        if self.app.recording:
            return RECORDING_ONE
        return self.app.strip

    def press(self, control: StripControl) -> None:
        self.app.events.append(("press", control.value))
        if control is StripControl.RECORD:
            self.app.recording, self.app.strip = True, READY_THREE
        elif control is StripControl.STOP:
            self.app.recording, self.app.strip = False, STORE_FOUR
        elif control is StripControl.DO_STORE:
            self.app.store_open = True

    def wait_for_view(self, views, *, timeout_s: float = VIEW_TIMEOUT_S) -> StripState:
        return self.strip_state()

    def _wait_for_view_guarded(self, want, timeout_s: float) -> StripState:
        return self.strip_state()

    def _hold_recording(self, duration_s: float) -> None:
        self.app.events.append(("hold", duration_s))

    def _await_store_dialog(self, timeout_s: float) -> tuple[dict, list[dict]]:
        return self._require_store_dialog()

    def _store_until_file(
        self, name: str, directory: Path, known: frozenset[str], timeout_s: float
    ) -> Path:
        self.app.events.append(("stored", name))
        return Path(directory) / f"{name}.BDD"


def fake_driver(app: FakeUdopWindow, **kwargs) -> FakeDriver:
    return FakeDriver(app, **kwargs)


def events_of(app: FakeUdopWindow, kind: str) -> list[tuple]:
    return [event for event in app.events if event[0] == kind]


# ---------------------------------------------- the channel is one verified knob


def test_the_channel_combo_is_identified_structurally_not_by_position() -> None:
    """The sidebar nests a combo listing the same channels; it is never the one."""
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app, channel=4)
    panel = actuator._open_parameters_dialog()
    combo, parent = actuator._channel_combo(panel)
    assert combo["hwnd"] == HWND_DIALOG_COMBO
    assert parent == HWND_DIALOG_VALUE_BUTTON  # reached *through* a value button
    assert panel["hwnd"] == HWND_DIALOG


def test_the_menu_entry_is_matched_by_title_not_by_enumeration_order() -> None:
    """Matching position once selected `Default parameters` and raised a modal (docs §6)."""
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app, channel=3)
    actuator.ensure_channel()
    assert ("click", "Operating parameters") in app.events
    assert ("hover", "Parameters") in app.events


def test_a_channel_already_selected_is_read_back_and_not_rewritten() -> None:
    """Nothing is written when the dialog already stands on the configured channel."""
    app = FakeUdopWindow(channel=2)
    actuator = fake_driver(app, channel=2)
    assert actuator.ensure_channel() == 2
    assert events_of(app, "combo") == []  # no write was needed
    # ...and the dialog was accepted and then closed (never left trapping the cursor).
    assert ("dialog", "accept") in app.events
    assert ("dialog", "cancel") in app.events
    assert app.dialog_open is False


def test_a_different_channel_is_selected_read_back_and_kept() -> None:
    """Channel 7 from a dialog standing on channel 1: index 6, verified, kept."""
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app, channel=7)
    assert actuator.ensure_channel() == 7
    assert events_of(app, "combo") == [("combo", "select", 6)]
    assert app.channel == 7  # the application took the selection
    assert app.dialog_open is False
    # The dialog was re-opened to confirm the application kept it: two opens.
    assert events_of(app, "dialog").count(("dialog", "open", 7)) == 1


def test_a_selection_that_does_not_take_fails_the_point_naming_the_channel() -> None:
    """A combo write that silently did nothing must never become a recorded point."""
    app = FakeUdopWindow(channel=1, combo_writes_ignored=True)
    actuator = fake_driver(app, channel=6)
    with pytest.raises(driver.AcquisitionError) as excinfo:
        actuator.ensure_channel()
    reason = str(excinfo.value)
    assert "channel 6" in reason and "index 5" in reason and "'1'" in reason
    assert app.dialog_open is False  # closed on the way out, never left modal


def test_a_selection_the_application_does_not_keep_fails_the_point() -> None:
    """The control believed it; the re-opened dialog shows the application did not."""
    app = FakeUdopWindow(channel=1, combo_control_only=True)
    actuator = fake_driver(app, channel=9)
    with pytest.raises(Exception, match="did not keep"):
        actuator.ensure_channel()
    assert app.dialog_open is False


def test_an_invalid_channel_is_refused_at_construction() -> None:
    app = FakeUdopWindow()
    with pytest.raises(Exception, match="channel"):
        fake_driver(app, channel=11)
    with pytest.raises(Exception, match="channel"):
        fake_driver(app, channel=0)


def test_cb_err_is_read_as_no_selection_not_as_a_huge_index() -> None:
    """``CB_GETCURSEL`` answers ``CB_ERR`` (-1) as an unsigned giant."""
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app, channel=1)

    def send_none(hwnd, msg, wp=0, lp=0, timeout_ms=0):
        return 0xFFFF_FFFF_FFFF_FFFF

    actuator._send = send_none  # type: ignore[method-assign]
    assert actuator._combo_index(HWND_DIALOG_COMBO) == -1


# --------------------------------------- the store dialog's Working directory


def test_same_directory_normalises_the_application_s_own_rendering(tmp_path: Path) -> None:
    expected = tmp_path / "capture"
    for shown in (
        str(expected),
        f"{expected}{os.sep}",  # the app adds a trailing separator
        f'"{expected}"',  # a quoted path
        f"  {expected}  ",
    ):
        assert driver.same_directory(shown, expected), shown
    assert not driver.same_directory("", expected)  # no path shown is not the path
    assert not driver.same_directory(str(tmp_path / "elsewhere"), expected)
    assert not driver.same_directory(str(expected / "deeper"), expected)


def test_a_matching_working_directory_is_left_alone(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    app = FakeUdopWindow(channel=1, directory=str(directory))
    app.store_open = True
    actuator = fake_driver(app)
    assert actuator.assert_working_directory(directory) == str(directory)
    assert events_of(app, "text") == []  # read, compared, and nothing written


def test_a_different_working_directory_is_written_and_read_back(tmp_path: Path) -> None:
    """The write path is exercised: the field decides where the point lands."""
    directory = tmp_path / "capture"
    app = FakeUdopWindow(channel=1, directory=str(tmp_path / "somewhere-else"))
    app.store_open = True
    actuator = fake_driver(app)
    assert actuator.assert_working_directory(directory) == str(directory)
    assert events_of(app, "text") == [("text", HWND_STORE_DIR, str(directory))]
    assert app.directory == str(directory)
    assert any("Working directory was" in note for note in actuator.warnings)


def test_an_unresolved_working_directory_mismatch_names_both_paths(tmp_path: Path) -> None:
    """A write that does not commit fails the point instead of watching the wrong folder."""
    expected = tmp_path / "capture"
    other = tmp_path / "somewhere-else"
    app = FakeUdopWindow(channel=1, directory=str(other), text_writes_ignored=True)
    app.store_open = True
    actuator = fake_driver(app)
    with pytest.raises(driver.AcquisitionError) as excinfo:
        actuator.assert_working_directory(expected)
    reason = str(excinfo.value)
    assert str(other) in reason and str(expected) in reason


def test_a_store_dialog_without_a_path_field_is_refused(tmp_path: Path) -> None:
    """Never guess which edit is the directory: report it and fail the point."""
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app)
    app.nodes = lambda: [  # a dialog whose two edits both hold names
        _node(HWND_STORE_DIALOG, "TSp_Panel", "Store", left=300, top=300, w=560, h=300),
        _node(HWND_STORE_NAME, "TEdit", "point-1", left=380, top=390, w=400),
        _node(HWND_STORE_NAME + 1, "TEdit", "comments", left=380, top=420, w=400),
        *app.store_buttons,
    ]
    with pytest.raises(Exception, match="Working directory"):
        actuator.assert_working_directory(tmp_path / "capture")


# ------------------------------------- the order a point takes them in (§12, §12b)


def test_a_point_verifies_the_channel_before_recording(tmp_path: Path) -> None:
    """The channel is a precondition of the point, not a setting applied earlier."""
    directory = tmp_path / "capture"
    directory.mkdir()
    # The dialog remembers *another* folder, as it does between runs: the point must
    # write its own and verify it, not follow the remembered one.
    app = FakeUdopWindow(channel=1, directory=str(tmp_path / "somewhere-else"))
    actuator = fake_driver(app, channel=5)

    stored = actuator.record_and_store("sw100-k1-161738", 0.5, directory)

    assert stored == directory / "sw100-k1-161738.BDD"
    order = [event[0] for event in app.events]
    dialog = order.index("dialog")
    press_record = app.events.index(("press", StripControl.RECORD.value))
    assert dialog < press_record, app.events  # the channel was verified first
    assert app.channel == 5
    # The store dialog's directory was asserted before anything was named or stored.
    write_dir = app.events.index(("text", HWND_STORE_DIR, str(directory)))
    write_name = next(
        i for i, event in enumerate(app.events) if event[0] == "text" and event[1] == HWND_STORE_NAME
    )
    assert write_dir < write_name, app.events
    assert app.directory == str(directory)
    assert app.name_text == "sw100-k1-161738"


def test_a_point_is_failed_when_the_channel_cannot_be_verified(tmp_path: Path) -> None:
    """The failure names the channel, and nothing is recorded or stored."""
    directory = tmp_path / "capture"
    directory.mkdir()
    app = FakeUdopWindow(channel=1, combo_writes_ignored=True, directory=str(directory))
    actuator = fake_driver(app, channel=4)

    ok, reason = actuator.try_record_and_store("sw100-k1-161738", 0.5, directory)

    assert ok is False
    assert "channel 4" in str(reason)
    assert app.store_open is False
    assert app.name_text == ""
    assert [p.name for p in directory.iterdir()] == []


def test_a_point_is_failed_when_the_directory_cannot_be_asserted(tmp_path: Path) -> None:
    """The failure names both paths, and nothing is stored under this point's name."""
    expected = tmp_path / "capture"
    expected.mkdir()
    app = FakeUdopWindow(channel=1, directory=str(tmp_path / "elsewhere"), text_writes_ignored=True)
    actuator = fake_driver(app, channel=1)

    ok, reason = actuator.try_record_and_store("sw100-k1-161738", 0.5, expected)

    assert ok is False
    assert str(expected) in str(reason)
    assert str(tmp_path / "elsewhere") in str(reason)
    assert app.name_text == ""

