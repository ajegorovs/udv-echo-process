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

import inspect
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
