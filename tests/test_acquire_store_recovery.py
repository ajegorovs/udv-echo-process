"""A store row that binds no ``New acquisition`` is refused, not pressed into.

The multiplexed (MPX) acquisition ends in a **two-button** store row — ``Do store`` then
``Clear and restart``, measured from the 2026-10-20 capture
(``tests/test_acquire_multiplexer_strip.py``). There is no ``New acquisition`` in it, and that
role is what every recovery path reaches for to leave a store view without committing the block
it holds.

Every consumer of that gesture therefore reads one clause,
:func:`udv_echo_process.acquire.ui.strip.new_acquisition_refusal`, and refuses **before** it
presses anything:

- the record cycle (:meth:`…udop.recording.RecordingSurface.record_and_store`) — which used to
  press ``New acquisition``, get ``ValueError`` out of :func:`…actuator.press_index`, and report
  the whole point as an *unexpected failure*;
- the live preflight (:meth:`…driver.Win32Actuator.preflight`), the same leftover-store recovery;
- the runner's pre-point reset (:meth:`…runner.SweepRunner._reset_block`), where ``Clear and
  restart`` *is* bound on this row and would have discarded the operator's unsaved block as a
  side effect of starting the next point.

What the clause preserves is the recovery the evidence supports: the three- and four-entry store
rows bind ``New acquisition``, so they keep being cleared and restarted exactly as before.

No case here posts a press: each double records the handle it would have posted, and the
assertions say that list stayed empty on the refusing path.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from test_acquire_mpx_row_variant import CAPTURED
from test_acquire_multiplexer_strip import MPX_PANEL, MPX_VISIBLE_KIDS, _widget
from test_acquire_runner import (
    CLEAR,
    DURATION_S,
    FakeActuator,
    make_runner,
    point_for,
)

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import (
    ProcessMode,
    StripControl,
    StripRowVariant,
    StripState,
    StripView,
)
from udv_echo_process.acquire.runner import ABORT_NOTE
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import RecordingSurface
from udv_echo_process.acquire.ui.strip import (
    has_slider,
    new_acquisition_refusal,
    strip_row,
    strip_state_of,
)

READY_THREE = StripState(button_count=3)
RECORDING_ONE = StripState(button_count=1)
STORE_TWO = StripState(button_count=2, has_slider=True)
STORE_THREE = StripState(button_count=3, has_slider=True)
STORE_FOUR = StripState(button_count=4, has_slider=True)

#: The **measured** repeated-MPX completion row (2026-10-21 capture): three buttons, a slider,
#: and the exact ``477x123`` / ``91-138-198`` signature that selects
#: ``StripRowVariant.REPEATED_MPX_COMPLETION``. Its row binds ``Do store`` / ``Clear and
#: restart`` / ``Remove current sequence`` — no ``New acquisition``, so no supported recovery.
STORE_THREE_REPEATED = strip_state_of(3, True, 100, row_signature=CAPTURED)

#: The three-button store row ``STRIP_BUTTON_ORDER`` already bound; ``New acquisition`` is its
#: leftmost button, which is what makes the recovery supported.
STORE_THREE_ROW: tuple[dict, ...] = (
    _widget(11, "TSp_Button", 10, 9, 80, 20),
    _widget(12, "TSp_Button", 100, 9, 80, 20),
    _widget(13, "TSp_Button", 190, 9, 80, 20),
    _widget(14, "TSp_Sliding_Bar", 122, 35, 150, 50),
)
READY_ROW: tuple[dict, ...] = (
    _widget(21, "TSp_Button", 10, 9, 80, 20),
    _widget(22, "TSp_Button", 100, 9, 80, 20),
    _widget(23, "TSp_Button", 190, 9, 80, 20),
)
RECORDING_ROW: tuple[dict, ...] = (_widget(31, "TSp_Button", 10, 9, 80, 20),)


# ------------------------------------------------------------------- the clause itself


def test_the_two_button_store_row_refuses_the_new_acquisition_recovery() -> None:
    """The clause names the row it read and hands the unsaved block back to the operator."""
    refusal = new_acquisition_refusal(STORE_TWO)

    assert refusal is not None
    # What it read: the row, its length and its bound roles — evidence, not a bare refusal.
    assert "2 button(s)" in refusal
    assert "do_store" in refusal and "clear_and_restart" in refusal
    assert "new_acquisition" not in refusal.split("binds no")[1]
    # What it means, and the remedy that is the operator's to choose.
    assert "unsaved block" in refusal
    assert "multiplexed (MPX)" in refusal
    assert "'Do store'" in refusal and "'Clear and restart'" in refusal
    # What it did not do: nothing was stored, cleared or discarded by the driver.
    assert "nothing is stored, cleared or discarded" in refusal.lower()


@pytest.mark.parametrize("state", [STORE_THREE, STORE_FOUR], ids=["store-3", "store-4"])
def test_the_store_rows_that_bind_new_acquisition_keep_the_recovery(
    state: StripState,
) -> None:
    """Three and four buttons *do* bind the role: their recovery is unchanged, not refused."""
    assert StripControl.NEW_ACQUISITION in state.controls
    assert new_acquisition_refusal(state) is None


@pytest.mark.parametrize(
    "state",
    [READY_THREE, RECORDING_ONE, StripState(button_count=4)],
    ids=["ready", "recording", "ambiguous"],
)
def test_other_views_are_not_this_clauses_business(state: StripState) -> None:
    """Only the store view holds a block; every other refusal has its own owner."""
    assert new_acquisition_refusal(state) is None


# ------------------------------------------------------------- the record cycle's boundary


class StripSurface(RecordingSurface):
    """The production cycle over an already-resolved strip, posting nothing.

    ``_resolve`` reports one panel and one row, ``_click_hold`` records the handle a real press
    would have posted, and :meth:`press` morphs the row the way the instrument does. The cycle
    itself — the order, the waits, the refusal — is the production code.
    """

    def __init__(self, kids: Sequence[dict], *, stop_at: StripControl | None = None) -> None:
        self.panel = MPX_PANEL
        self.kids = list(kids)
        self.presses: list[int] = []
        self.notes: list[str] = []
        self.stop_at = stop_at

    # the collaborators ``press``/``record_and_store`` reach through ``self``

    def layout_note(self, *, expected_mode: ProcessMode | None = None) -> str | None:
        return None

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def _resolve(self) -> dict:
        return {
            "strip_panel": self.panel,
            "strip_row": strip_row(self.panel, self.kids),
            "strip_slider": has_slider(self.kids),
            "open_popup": False,
            "panels": [self.panel],
            "value_dialogs": set(),
            "identities": {},
        }

    def _settle_press(self) -> None:
        """No overlay is up in any of these states."""

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(hwnd)

    def press(self, control: StripControl) -> None:
        super().press(control)
        if self.stop_at is not None and control is self.stop_at:
            raise AcquisitionError("scripted end of this case")
        if control is StripControl.NEW_ACQUISITION:
            self.kids = list(READY_ROW)
        elif control is StripControl.RECORD:
            self.kids = list(RECORDING_ROW)

    @property
    def controls_pressed(self) -> list[int]:
        return self.presses


def test_the_cycle_refuses_before_any_press_on_the_mpx_store_row(tmp_path: Path) -> None:
    """``record_and_store`` raises the existing error, by name, and posts nothing."""
    strip = StripSurface(MPX_VISIBLE_KIDS)

    with pytest.raises(AcquisitionError) as caught:
        strip.record_and_store(
            "mpx-point", 0.0, tmp_path, expected_mode=ProcessMode.SIMULATION
        )

    message = str(caught.value)
    assert "unsaved block" in message, message
    assert "multiplexed (MPX)" in message, message
    assert "unexpected failure" not in message, message
    assert "ValueError" not in message, message
    assert strip.presses == [], "a press was posted out of a store row with no such binding"
    assert "cleared the leftover block view" not in strip.notes


def test_the_cycle_still_clears_a_three_button_store_row(tmp_path: Path) -> None:
    """The supported recovery is untouched: ``New acquisition`` is still the first press."""
    strip = StripSurface(STORE_THREE_ROW, stop_at=StripControl.STOP)
    row = strip_row(strip.panel, strip.kids)
    assert strip.strip_state().view is StripView.STORE

    with pytest.raises(AcquisitionError) as caught:
        strip.record_and_store(
            "store-three",
            0.0,
            tmp_path,
            expected_mode=ProcessMode.SIMULATION,
            verify_channel=False,
        )

    assert "unsaved block" not in str(caught.value), caught.value
    assert strip.presses[0] == row[0]["hwnd"], strip.presses
    assert len(strip.presses) >= 2, strip.presses


# ---------------------------------------------------------------- the preflight's boundary


class PreflightScreen(driver.Win32Actuator):
    """``Win32Actuator`` over one strip state: presses are recorded, never posted."""

    def __init__(self) -> None:
        super().__init__()
        self.state = STORE_TWO
        self.presses: list[int] = []

    def strip_state(self) -> StripState:
        return self.state

    def wait_for_view_guarded(self, want, timeout_s: float) -> StripState:
        return self.state

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(hwnd)

    def _settle_press(self) -> None:
        """No overlay is up: the state under test is the strip's own row."""

    def _resolve(self) -> dict:
        return {
            "strip_panel": MPX_PANEL,
            "strip_row": strip_row(MPX_PANEL, MPX_VISIBLE_KIDS),
            "strip_slider": True,
            "open_popup": False,
            "panels": [MPX_PANEL],
            "value_dialogs": set(),
            "identities": {},
        }

    def press(self, control: StripControl) -> None:
        self.presses.append(control)  # type: ignore[arg-type]
        if control is StripControl.RECORD:
            raise AcquisitionError("scripted end of this case")


def test_the_preflight_refuses_before_any_press_on_the_mpx_store_row() -> None:
    """The leftover-store recovery is the same gesture, so it obeys the same clause."""
    screen = PreflightScreen()

    with pytest.raises(AcquisitionError) as caught:
        screen.preflight(0.0)

    assert "unsaved block" in str(caught.value), caught.value
    assert screen.presses == [], "the preflight posted a press out of an unbound store row"


def test_the_preflight_still_clears_a_three_button_store_row() -> None:
    """Three buttons bind the role: the preflight's recovery press is unchanged."""
    screen = PreflightScreen()
    screen.state = STORE_THREE

    with pytest.raises(AcquisitionError) as caught:
        screen.preflight(0.0)

    assert "unsaved block" not in str(caught.value), caught.value
    # The recovery press was first and was posted; the case ends at the scripted Record press.
    assert screen.presses[0] is StripControl.NEW_ACQUISITION, screen.presses


# ------------------------------------------------------------------ the runner's boundary


class MpxStoreActuator(FakeActuator):
    """The runner's fake, in the two-button store row an MPX run ends in."""

    def _state(self) -> StripState:
        state = super()._state()
        if state.view is StripView.STORE:
            return STORE_TWO
        return state


def test_the_pre_point_reset_refuses_on_the_mpx_store_row_without_a_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Clear and restart`` is bound here, and would have discarded the unsaved block."""
    fake, engine, _, _ = make_runner(
        tmp_path, monkeypatch, fake_class=MpxStoreActuator
    )
    fake.view = StripView.STORE

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, "an operator remedy ends the run, it does not continue it"
    assert "unsaved block" in outcome.reason, outcome.reason
    assert outcome.reason.endswith(ABORT_NOTE)
    assert [call for call in fake.calls if call[:2] == ("press", CLEAR)] == []
    assert [call for call in fake.calls if call[0] in ("record_and_store",)] == []


def test_the_pre_point_reset_still_clears_a_three_button_store_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row that binds ``New acquisition`` keeps the documented reset."""
    fake, engine, _, _ = make_runner(tmp_path, monkeypatch)
    fake.view = StripView.STORE
    assert fake._state().button_count == 3

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert "unsaved block" not in str(outcome.reason), outcome.reason
    assert [call for call in fake.calls if call[:2] == ("press", CLEAR)], fake.calls


# --------------------------------------- the measured repeated-MPX completion row (2026-10-21)


def test_the_measured_repeated_mpx_row_refuses_the_new_acquisition_recovery() -> None:
    """The variant row binds no ``New acquisition`` either, and the clause says which row.

    The two-button row above is one measurement; this is a second, *distinct* row that shares
    ``(STORE, 3)`` with the legacy row. It is the case a count-keyed reading gets wrong: the
    legacy three-button row binds ``New acquisition`` and its recovery stays supported, while
    this one binds ``Do store`` / ``Clear and restart`` / ``Remove current sequence`` and has no
    gesture out that does not act on the operator's unsaved block.
    """
    assert STORE_THREE_REPEATED.row_variant is StripRowVariant.REPEATED_MPX_COMPLETION
    refusal = new_acquisition_refusal(STORE_THREE_REPEATED)

    assert refusal is not None, "the measured row must not be handed the legacy recovery"
    assert "3 button(s)" in refusal
    assert "do_store" in refusal and "clear_and_restart" in refusal
    assert "remove_current_sequence" in refusal
    assert "repeated multiplexed (MPX) completion row" in refusal, refusal
    assert "unsaved block" in refusal
    # The same key without the measurement is the legacy row, and its recovery is unchanged.
    assert STORE_THREE.row_variant is None
    assert new_acquisition_refusal(STORE_THREE) is None


class RepeatedCompletionActuator(FakeActuator):
    """The runner's fake, in the *measured* repeated-MPX completion row."""

    def _state(self) -> StripState:
        state = super()._state()
        if state.view is StripView.STORE:
            return STORE_THREE_REPEATED
        return state


def test_the_pre_point_reset_refuses_on_the_measured_repeated_mpx_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``Clear``, no ``Remove current sequence`` and no ``Record``: the point stops.

    ``Clear and restart`` *is* bound at index 1 of this measured row, and ``Remove current
    sequence`` at index 2 — pressing either would act on the operator's unsaved block — so the
    same clause that guards the two-button row has to guard this one before any press is posted.
    """
    fake, engine, _, _ = make_runner(
        tmp_path, monkeypatch, fake_class=RepeatedCompletionActuator
    )
    fake.view = StripView.STORE
    assert fake._state().row_variant is StripRowVariant.REPEATED_MPX_COMPLETION

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, "an operator remedy ends the run, it does not continue it"
    assert "unsaved block" in outcome.reason, outcome.reason
    assert "repeated multiplexed (MPX) completion row" in outcome.reason, outcome.reason
    assert outcome.reason.endswith(ABORT_NOTE)
    posted = [call[1] for call in fake.calls if call[0] == "press"]
    assert posted == [], f"a press was posted out of an unbound completion row: {posted}"
    for refused in (
        StripControl.CLEAR_AND_RESTART,
        StripControl.REMOVE_CURRENT_SEQUENCE,
        StripControl.RECORD,
        StripControl.NEW_ACQUISITION,
    ):
        assert [call for call in fake.calls if call[:2] == ("press", refused.value)] == []
    assert [call for call in fake.calls if call[0] == "record_and_store"] == []
