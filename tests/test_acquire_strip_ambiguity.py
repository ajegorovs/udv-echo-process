"""B10 — the four-button, no-slider strip row is not a row this driver may press.

The critical, device-pending blind spot. Two descriptions of the same state disagree, and they
disagree about *which button is which*:

- the code's ``STRIP_BUTTON_ORDER[(StripView.READY, 4)]`` reads
  ``Pause / Record / Do store / Clear and restart``, and ``classify_strip_view`` calls **every**
  3–4 button no-slider row ``READY``, so a four-button row is startable and its positions are
  bound as those four roles;
- the committed crop ``overlay-record-extra-block.png`` — indexed as ``UI-STRIP-02`` in
  ``docs/dop3000/ui-element-index.md``, and the operator's own reading of it — paints
  ``New acquisition / Do store / Clear and restart / Remove current block``.

The third slot is demonstrably the same button in both cropped states (the same circular-arrow
glyph), while the first two captions are not (``UI-STRIP-01``'s frame paints ``Pause`` beside a
black two-bar glyph and ``Record`` beside a red disc; ``UI-STRIP-02``'s paints ``New
acquisition`` beside the same two-bar glyph and ``Do store`` beside a floppy disc). Pixel
evidence and tree state may not even be the same instant, so the disagreement is **not**
reconciled by inference here: until a live tree capture settles it, a four-button no-slider row
is ambiguous, it exposes no executable button binding, and no press may come out of it. The
store view's own four-entry row — the one the crop's captions do match — is untouched, and that
is asserted too, so a fix cannot simply refuse the whole strip.

Provenance: ``UI-STRIP-01``/``UI-STRIP-02`` in ``docs/dop3000/ui-element-index.md`` (finding 20),
``docs/dop3000/ui-crops/run-controls.png`` and ``overlay-record-extra-block.png``. No live tree
of the grown state exists in the repository, which is why the state is pinned as *ambiguous*
rather than as a role map: the day a capture lands, this module is where the answer goes.
"""

from __future__ import annotations

import pytest
from test_acquire_layout_gate import manual_screen

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import (
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    press_index,
    strip_controls,
)


# B10: UI-STRIP-01 (ui-crops/run-controls.png) and the store row's own four.
def test_the_three_button_row_and_the_store_row_keep_their_documented_bindings() -> None:
    """The rows the crops agree about, so the pin above cannot be satisfied by refusing the strip.

    ``UI-STRIP-01`` is the three-button row (``Pause`` / ``Record`` / ``Clear and restart``, no
    slider, nothing highlighted) and ``STRIP_BUTTON_ORDER`` documents it; the four-entry *store*
    row is the one ``UI-STRIP-02``'s captions match.
    """
    assert classify_strip_view(3, has_slider=False) is StripView.READY
    assert [control.value for control in strip_controls(StripView.READY, 3)] == [
        "pause",
        "record",
        "clear_and_restart",
    ]
    assert press_index(StripView.READY, StripControl.RECORD, 3) == 1

    assert classify_strip_view(3, has_slider=True) is StripView.STORE
    assert [control.value for control in strip_controls(StripView.STORE, 4)] == [
        "new_acquisition",
        "do_store",
        "clear_and_restart",
        "remove_current_block",
    ]


# B10: UI-STRIP-02 (ui-crops/overlay-record-extra-block.png), index finding 20.
def test_the_four_captions_the_grown_crop_paints_are_the_store_rows_four() -> None:
    """The crop's row is the store view's, which is what makes the no-slider four ambiguous.

    ``UI-STRIP-02``'s panel is grown and a block is held (its own combo reads ``Show block`` =
    ``2``), and the four captions it paints are exactly ``STRIP_BUTTON_ORDER[(STORE, 4)]``. The
    row the *code* binds a four-button no-slider strip to is a different one — the same count,
    different roles — and nothing in the repository says which of the two a no-slider four
    resolves to on the device. So the pin is the disagreement itself: whatever the ambiguous row
    ends up bound to (or not bound to at all), it is never this crop's row.
    """
    crop = [control.value for control in strip_controls(StripView.STORE, 4)]
    assert crop == [
        "new_acquisition",
        "do_store",
        "clear_and_restart",
        "remove_current_block",
    ]

    try:
        bound = [control.value for control in strip_controls(StripView.READY, 4)]
    except ValueError:
        # The fix's own shape: the ambiguous row has no binding at all to disagree with.
        bound = []
    assert bound != crop


# B10: critical and device-pending — no live tree of the grown state exists yet.
def test_a_four_button_row_without_a_slider_is_not_a_ready_strip() -> None:
    """B10: the state is AMBIGUOUS/unknown, so nothing in it may be addressed by position.

    ``Pause``, ``Record``, ``Do store`` and ``Clear and restart`` are consequential roles — a
    ``Record`` press starts a recording under the next point's name (docs/16 §15b) — and the
    committed crop says the first two positions of a grown no-slider row are *not* those two
    buttons. Both readings cannot be true, and the crop is not enough to choose: so the row is
    ambiguous, ``is_startable`` is false, and asking for a position in it is a refusal rather
    than an index a press can use.
    """
    assert classify_strip_view(4, has_slider=False) is not StripView.READY

    state = StripState(button_count=4, has_slider=False)
    assert state.is_startable is False
    # No executable button binding: not from the state, and not from the order map either.
    for control in (StripControl.RECORD, StripControl.PAUSE, StripControl.CLEAR_AND_RESTART):
        with pytest.raises(ValueError):
            state.index_of(control)
    with pytest.raises(ValueError):
        strip_controls(state.view, 4)


# B10: the driver's press path (Win32Actuator.press) over the ambiguous row.
def test_no_press_comes_out_of_a_four_button_row_without_a_slider() -> None:
    """B10's consequence, through the driver's own press path: nothing may be posted.

    The binding is resolved at press time from the row the driver has just read, so this is the
    one place the wrong row would become a real click on the operator's instrument. Whatever the
    fix's shape — a refusal from the classifier or from the press — what must hold is that no
    handle was pressed.
    """

    class StripScreen(driver.Win32Actuator):
        """A driver over an already-resolved tree, recording presses instead of posting them."""

        def __init__(self, roles: dict) -> None:
            super().__init__()
            self._roles = roles
            self.presses: list[int] = []

        def _resolve(self) -> dict:
            return self._roles

        def _settle_press(self) -> None:
            """No overlay to answer: the state under test is the one this file is about."""

        def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
            self.presses.append(hwnd)

    screen = StripScreen(manual_screen(strip_row=4))
    assert len(screen.strip_state().controls) == 4  # the row under test is the four-button one

    with pytest.raises((ValueError, driver.AcquisitionError)):
        screen.press(StripControl.RECORD)

    assert screen.presses == [], "a press was posted out of an ambiguous strip row"


# B10: the shape gate over manual_screen(strip_row=4) — the ambiguous row is not a shape.
def test_the_shape_gate_does_not_treat_a_four_button_no_slider_row_as_known() -> None:
    """B10 in the gate: an ambiguous row is not a shape a run may be gated on.

    `layout_shape_reasons` asks whether the row's length maps into ``STRIP_BUTTON_ORDER`` for the
    view the classifier returned, and the classifier answers ``AMBIGUOUS`` for a no-slider four —
    so the gate refuses the one row the repository's own evidence contradicts instead of gating a
    run on it. The assertion this one was written against,
    ``tests/test_acquire_layout_gate.py::test_a_strip_row_outside_the_known_rows_fails``, accepted
    the four-button row until B10 landed: it has been **corrected with this fix** (4 joined the
    lengths it refuses), so the two no longer stand against each other.
    """
    reasons = driver.layout_shape_reasons(manual_screen(strip_row=4))

    assert reasons, "the gate accepted the ambiguous four-button no-slider row as a known strip"
    assert any("strip" in clause.lower() for clause in reasons), reasons
