"""Tests for the actuator interface — ``acquire/actuator.py``.

Two things are checked here:

- the **binding tables and ordering rules** that were paid for on the live
  application: the strip's view is structural (button count + slider), a button's
  identity is its left-to-right **index in the current view** (widths are too
  close to identify: 134 vs 138 px), the resolution is written **before** the gate
  count (805 requested -> 474 accepted in the other order, docs/16 §14), every
  strip press is **held** ~180 ms, a numeric write needs its ``VK_RETURN`` commit
  (docs/14 §4), and an overlay is answered with its **left** button (docs/16 §8);
- that the interface is satisfiable by a **pure-Python fake** — no ``pywinauto``,
  no window, no coordinates — which is the whole reason the actuator is a
  :class:`typing.Protocol` here.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from udv_echo_process.acquire.actuator import (
    DIALOG_ONLY_PARAMETERS,
    NUMERIC_WRITE_RECIPE,
    OVERLAY_ANSWERS,
    PARAM_COLUMN_ORDER,
    PARAMETER_WRITE_ORDER,
    PRESS_HOLD_MS,
    STARTABLE_VIEWS,
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
    strip_controls,
)
from udv_echo_process.acquire.config import RUNG_DIVISOR, ParameterSet

READY_THREE = StripState(button_count=3)
READY_FOUR = StripState(button_count=4)
RECORDING_ONE = StripState(button_count=1)
STORE_FOUR = StripState(button_count=4, has_slider=True)


# ------------------------------------------------------------- strip's view


@pytest.mark.parametrize(
    ("button_count", "has_slider", "expected"),
    [
        (1, False, StripView.RECORDING),  # a single [Stop]
        (3, False, StripView.READY),  # stopped with data, no slider
        (4, False, StripView.READY),
        (3, True, StripView.STORE),  # the slider is decisive
        (4, True, StripView.STORE),
        (0, False, StripView.UNKNOWN),
        (2, False, StripView.UNKNOWN),  # the morph state between views
    ],
)
def test_strip_view_is_recognised_structurally(
    button_count: int, has_slider: bool, expected: StripView
) -> None:
    assert classify_strip_view(button_count, has_slider) is expected


def test_strip_view_rejects_a_negative_button_count() -> None:
    with pytest.raises(ValueError, match="button_count"):
        classify_strip_view(-1, False)


# --------------------------------------------------------- strip's buttons


@pytest.mark.parametrize(
    ("view", "button_count", "expected"),
    [
        (StripView.RECORDING, 1, (StripControl.STOP,)),
        (
            StripView.READY,
            3,
            (StripControl.PAUSE, StripControl.RECORD, StripControl.CLEAR_AND_RESTART),
        ),
        (
            StripView.READY,
            4,
            (
                StripControl.PAUSE,
                StripControl.RECORD,
                StripControl.DO_STORE,
                StripControl.CLEAR_AND_RESTART,
            ),
        ),
        (
            StripView.STORE,
            3,
            (
                StripControl.NEW_ACQUISITION,
                StripControl.DO_STORE,
                StripControl.CLEAR_AND_RESTART,
            ),
        ),
        (
            StripView.STORE,
            4,
            (
                StripControl.NEW_ACQUISITION,
                StripControl.DO_STORE,
                StripControl.CLEAR_AND_RESTART,
                StripControl.REMOVE_CURRENT_BLOCK,
            ),
        ),
    ],
)
def test_button_rows_are_position_ordered(
    view: StripView, button_count: int, expected: tuple[StripControl, ...]
) -> None:
    """docs/16 §7: identities come from the order in the view, never the width."""
    assert strip_controls(view, button_count) == expected
    assert STRIP_BUTTON_ORDER[(view, button_count)] == expected


@pytest.mark.parametrize(
    ("view", "button_count"),
    [
        (StripView.UNKNOWN, 2),
        (StripView.RECORDING, 3),
        (StripView.READY, 1),
        (StripView.STORE, 1),
    ],
)
def test_an_unknown_row_is_refused_not_guessed(
    view: StripView, button_count: int
) -> None:
    with pytest.raises(ValueError, match="no known button row"):
        strip_controls(view, button_count)


@pytest.mark.parametrize(
    ("view", "button_count", "control", "expected_index"),
    [
        (StripView.RECORDING, 1, StripControl.STOP, 0),
        (StripView.READY, 3, StripControl.RECORD, 1),
        (StripView.READY, 4, StripControl.RECORD, 1),
        (StripView.READY, 3, StripControl.PAUSE, 0),
        (StripView.READY, 3, StripControl.CLEAR_AND_RESTART, 2),
        (StripView.STORE, 3, StripControl.NEW_ACQUISITION, 0),
        (StripView.STORE, 3, StripControl.DO_STORE, 1),
        (StripView.STORE, 4, StripControl.DO_STORE, 1),
        (StripView.STORE, 4, StripControl.REMOVE_CURRENT_BLOCK, 3),
    ],
)
def test_a_press_binds_to_an_index_in_the_current_view(
    view: StripView, button_count: int, control: StripControl, expected_index: int
) -> None:
    assert press_index(view, control, button_count) == expected_index


def test_pressing_a_button_that_is_not_in_this_view_is_refused() -> None:
    """Record sat at x=547 in the triplet and x=458 as Stop: position is state."""
    with pytest.raises(ValueError, match="no 'record'"):
        press_index(StripView.STORE, StripControl.RECORD, 3)


def test_strip_state_derives_its_own_view() -> None:
    assert READY_THREE.view is StripView.READY
    assert RECORDING_ONE.view is StripView.RECORDING
    assert STORE_FOUR.view is StripView.STORE
    assert READY_THREE.index_of(StripControl.RECORD) == 1
    assert [control.value for control in READY_THREE.controls] == [
        "pause",
        "record",
        "clear_and_restart",
    ]
    # The store slider's maximum is the selected block's profile count.
    store_state = StripState(button_count=4, has_slider=True, slider_max=1384)
    assert store_state.slider_max == 1384


def test_an_unknown_view_has_no_controls() -> None:
    state = StripState(button_count=2)
    assert state.controls == ()
    assert state.is_startable is False


def test_a_point_cycle_may_not_start_from_a_recording() -> None:
    """A leftover recording is stored under the next point's name (docs/16 §15b)."""
    assert READY_THREE.is_startable is True
    assert STORE_FOUR.is_startable is True
    assert RECORDING_ONE.is_startable is False
    assert StripView.RECORDING not in STARTABLE_VIEWS


def test_strip_state_rejects_impossible_structures() -> None:
    with pytest.raises(ValueError):
        StripState(button_count=-1)
    with pytest.raises(ValueError):
        StripState(button_count=3, slider_max=-1)


# --------------------------------------------------- parameter write ordering


def test_param_column_order_is_the_measured_top_to_bottom_row() -> None:
    """``recon/udop_roles.py``: the column's value fields, ordered by ``top``."""
    assert PARAM_COLUMN_ORDER == (
        ParamRole.US_FREQUENCY,
        ParamRole.PRF,
        ParamRole.GATES,
        ParamRole.RESOLUTION,
        ParamRole.VELOCITY_SCALE_FACTOR,
        ParamRole.EMISSIONS_PER_PROFILE,
        ParamRole.DOPPLER_ANGLE,
    )
    assert len(PARAM_COLUMN_ORDER) == len(set(PARAM_COLUMN_ORDER))


def test_resolution_is_written_before_the_gate_count() -> None:
    """The auto-resolution flags make the app recompute gates (docs/16 §14)."""
    assert PARAMETER_WRITE_ORDER == (ParamRole.RESOLUTION, ParamRole.GATES)
    parameters = ParameterSet(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        resolution_mm=round(1 * 1460.0 / RUNG_DIVISOR, 6),
        gates=805,
    )
    writes = ordered_writes(parameters)
    assert [role for role, _ in writes] == [ParamRole.RESOLUTION, ParamRole.GATES]
    # The sidebar shows 3 decimals; the gate count is an integer.
    assert writes[0][1] == "0.122"
    assert writes[1][1] == "805"


def test_ordered_writes_covers_only_the_depth_window_fields() -> None:
    """PRF/emissions are read-once covariates; burst has no column field at all."""
    parameters = ParameterSet(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        resolution_mm=0.121667,
        gates=805,
        prf_us=200.0,
        emissions_per_profile=100,
        burst_length=4,
    )
    roles = {role for role, _ in ordered_writes(parameters)}
    assert roles == {ParamRole.RESOLUTION, ParamRole.GATES}
    assert ParamRole.PRF not in roles
    assert ParamRole.EMISSIONS_PER_PROFILE not in roles


# ------------------------------------------------------------- ported recipes


def test_the_press_recipe_keeps_its_hold_time() -> None:
    """An instant down/up in the same millisecond is ignored (docs/16 §1)."""
    assert PRESS_HOLD_MS == 180


def test_the_numeric_write_recipe_ends_with_the_commit_key_event() -> None:
    """``WM_SETTEXT`` alone leaves the control changed and the model untouched."""
    assert NUMERIC_WRITE_RECIPE == (
        "WM_SETTEXT",
        "WM_COMMAND(EN_CHANGE)",
        "WM_KEYDOWN(VK_RETURN)",
        "WM_KEYUP(VK_RETURN)",
    )
    assert NUMERIC_WRITE_RECIPE[-1] == "WM_KEYUP(VK_RETURN)"


def test_the_store_dialog_is_never_answered_by_the_overlay_guard() -> None:
    """It is not an overlay to dismiss: the caller sets the name and commits."""
    assert overlay_answer(OverlayKind.STORE_DIALOG) is None
    assert OVERLAY_ANSWERS[OverlayKind.STORE_DIALOG] is None


def test_every_warning_is_answered_with_the_left_button() -> None:
    """``Cancel`` is left of the pair, and ``No`` is left of ``Yes`` (docs/16 §8, §12b)."""
    assert overlay_answer(OverlayKind.WARNING) is DialogControl.SAFE
    assert OVERLAY_ANSWERS[OverlayKind.WARNING] is DialogControl.SAFE
    assert DialogControl.SAFE.value == "safe"
    assert DialogControl.CONFIRM.value == "confirm"


def test_burst_and_sampling_volume_are_dialog_only() -> None:
    """docs/16 §13: burst has no sidebar field, and the app picks the volume."""
    assert "burst_length" in DIALOG_ONLY_PARAMETERS
    assert "sampling_volume" in DIALOG_ONLY_PARAMETERS
    sidebar_names = {role.value for role in PARAM_COLUMN_ORDER}
    assert not sidebar_names & set(DIALOG_ONLY_PARAMETERS)


def test_view_and_store_timeouts_are_the_ported_budgets() -> None:
    assert VIEW_TIMEOUT_S == 12.0


# ------------------------------------------------- the interface and its fake


class FakeActuator:
    """A pure-Python :class:`Actuator`: no Windows, no ids, no coordinates."""

    def __init__(self) -> None:
        self.state = READY_THREE
        self.presses: list[tuple[int, StripControl]] = []
        self.parameters: dict[ParamRole, str] = {}
        self.overlays: list[OverlayKind] = []
        self.answered: list[OverlayKind] = []
        self.store_name: str | None = None
        self.commits = 0
        self.layout: str | None = None

    def layout_note(self) -> str | None:
        return self.layout

    def read_parameter(self, role: ParamRole) -> str:
        return self.parameters.get(role, "")

    def write_parameter(self, role: ParamRole, value: str) -> None:
        self.parameters[role] = value

    def strip_state(self) -> StripState:
        return self.state

    def wait_for_view(
        self, views: Iterable[StripView], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        # The contract returns the last state seen and lets the caller judge it.
        return self.state

    def press(self, control: StripControl) -> None:
        index = self.state.index_of(control)  # binds by position in this view
        self.presses.append((index, control))
        self.state = _next_state(control)

    def answer_overlay(self) -> OverlayKind | None:
        if not self.overlays:
            return None
        kind = self.overlays.pop(0)
        self.answered.append(kind)
        return kind

    def set_store_name(self, name: str) -> None:
        self.store_name = name

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = 60.0,
    ) -> Path:
        assert self.store_name is not None
        return Path(directory) / f"{self.store_name}.BDD"

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        timeout_s: float = 60.0,
    ) -> Path:
        if not self.state.is_startable:
            raise RuntimeError(f"cannot start from view {self.state.view.value}")
        if self.state.view is StripView.STORE:
            self.press(StripControl.NEW_ACQUISITION)
        self.press(StripControl.RECORD)
        self.press(StripControl.STOP)
        self.set_store_name(name)
        self.commit_store()
        return self.wait_for_stored_file(directory / f"{duration_s}", known=())


def _next_state(control: StripControl) -> StripState:
    """The strip's state machine, as measured (docs/16 §3, §7)."""
    if control is StripControl.RECORD:
        return RECORDING_ONE
    if control is StripControl.STOP:
        return STORE_FOUR
    if control is StripControl.DO_STORE:
        return STORE_FOUR
    if control is StripControl.NEW_ACQUISITION:
        return READY_THREE
    return READY_THREE


class _Incomplete:
    """An object that satisfies only part of the interface."""

    def layout_note(self) -> str | None:
        return None


def test_a_pure_python_fake_satisfies_the_interface() -> None:
    assert isinstance(FakeActuator(), Actuator)
    assert not isinstance(_Incomplete(), Actuator)
    assert not isinstance(object(), Actuator)


def test_the_fake_drives_a_point_cycle_through_the_tables() -> None:
    actuator = FakeActuator()
    path = actuator.record_and_store("sw100-k1-161738", 4.0, Path("capture"))
    assert actuator.presses == [(1, StripControl.RECORD), (0, StripControl.STOP)]
    assert actuator.commits == 1
    assert path.name == "sw100-k1-161738.BDD"


def test_a_store_view_is_dismissed_before_the_next_point() -> None:
    actuator = FakeActuator()
    actuator.state = STORE_FOUR
    actuator.record_and_store("sw100-k2-161738", 4.0, Path("capture"))
    assert actuator.presses[0] == (0, StripControl.NEW_ACQUISITION)
    assert actuator.presses[1] == (1, StripControl.RECORD)


def test_the_fake_refuses_to_start_from_a_recording() -> None:
    """Only start from a verified ready state (docs/16 §15b)."""
    actuator = FakeActuator()
    actuator.state = RECORDING_ONE
    with pytest.raises(RuntimeError, match="recording"):
        actuator.record_and_store("sw100-k1-161738", 4.0, Path("capture"))
    assert actuator.presses == []


def test_a_write_is_readable_through_the_interface() -> None:
    actuator = FakeActuator()
    for role, value in ordered_writes(
        ParameterSet(
            sound_speed_ms=1460.0,
            first_gate_mm=2.0,
            resolution_mm=0.121667,
            gates=805,
        )
    ):
        actuator.write_parameter(role, value)
    assert actuator.read_parameter(ParamRole.RESOLUTION) == "0.122"
    assert actuator.read_parameter(ParamRole.GATES) == "805"
    assert actuator.read_parameter(ParamRole.PRF) == ""


def test_the_fake_answers_overlays_and_reports_what_they_were() -> None:
    actuator = FakeActuator()
    assert actuator.answer_overlay() is None
    actuator.overlays.append(OverlayKind.WARNING)
    assert actuator.answer_overlay() is OverlayKind.WARNING
    assert actuator.answer_overlay() is None
