"""The two-button store row the multiplexed (MPX) acquisition leaves behind.

After a multiplexed recording is stopped, this application builds the store view with
**two** top-row buttons and the ``TSp_Sliding_Bar`` child, not the three or four the
existing table bound. ``classify_strip_view`` already answered that structure ``STORE``
(the slider is decisive), so the view was reachable while ``STRIP_BUTTON_ORDER`` carried
no row for it: ``press(DO_STORE)`` raised ``ValueError`` and a store could not be
committed from exactly the state the MPX runs end in.

The binding landed here is the agreed interface — ``(STORE, 2)`` is
``DO_STORE`` then ``CLEAR_AND_RESTART``, left to right.

**What the evidence is, and what it is not.**

- The *shape* below is a de-identified projection of one live, read-only control-tree
  capture taken 2026-10-20 (``UDOP DOP3010.43``, multiplexer sequence probe): a strip
  panel 269x123 holding two visible top-row ``TSp_Button`` widgets, a visible
  ``TSp_Sliding_Bar``, two visible ``TComboBox`` children (block and channel), and two
  further ``TSp_Button`` widgets painted *behind* the row at the same height with
  ``visible: false``. Handles, screen origin and the combos' values are not carried: the
  binding is positional, so the shape is what a regression needs.
- The two *captions* — left ``Do store``, right ``Clear and restart`` — come from a
  **manual inspection of the captured frame**, not from an automated press: no live
  click was posted to this row while landing this change, and nothing here claims the
  live adapter was exercised on the instrument.

So this module pins the production press boundary against the captured *structure* and
the captions as inspected; it does not assert that the instrument answers the press.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from udv_echo_process.acquire.actuator import (
    STRIP_BUTTON_ORDER,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    press_index,
    strip_controls,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import RecordingSurface
from udv_echo_process.acquire.ui.strip import has_slider, strip_row


def _widget(
    hwnd: int, cls: str, left: int, top: int, w: int, h: int, *, visible: bool = True
):
    """One control in the shape ``_visible_children`` produces, in panel-local geometry."""
    return {
        "hwnd": hwnd,
        "cls": cls,
        "text": "",
        "rect": (left, top, left + w, top + h),
        "left": left,
        "top": top,
        "w": w,
        "h": h,
        "id": 0,
        "visible": visible,
    }


# The MPX store panel, 2026-10-20 capture, translated to a local origin and renumbered.
# Top row (y = 9): one button 91 px wide, one 138 px wide — too close to tell apart by
# width, which is why the row is addressed by index. Slider below the row; the two
# combos are the block/channel pair and are not part of the row.
MPX_PANEL = _widget(1, "TSp_Panel", 0, 0, 269, 123)
MPX_DO_STORE = 2
MPX_CLEAR_AND_RESTART = 3
MPX_VISIBLE_KIDS: tuple[dict, ...] = (
    _widget(MPX_DO_STORE, "TSp_Button", 10, 9, 91, 20),
    _widget(MPX_CLEAR_AND_RESTART, "TSp_Button", 111, 9, 138, 20),
    _widget(4, "TSp_Sliding_Bar", 122, 35, 150, 50),
    _widget(5, "TComboBox", 86, 92, 45, 21),
    _widget(6, "TComboBox", 220, 92, 45, 21),
)
# Painted behind the row at the same height, not visible: the capture states them as
# such, and counting them would make the row four buttons wide.
MPX_HIDDEN_KIDS: tuple[dict, ...] = (
    _widget(7, "TSp_Button", 10, 10, 79, 20, visible=False),
    _widget(8, "TSp_Button", 99, 10, 85, 20, visible=False),
)


class CapturedStrip(RecordingSurface):
    """``RecordingSurface.press`` over an already-resolved strip, posting nothing.

    Only the three collaborators ``press`` reaches through ``self`` are replaced — the
    resolve, the overlay settle and the held press. Every rule under test (the binding
    lookup, the refusal of an unbound row, the index-to-handle step) is the production
    one.
    """

    def __init__(self, panel: dict, kids: Sequence[dict]) -> None:
        self.panel = panel
        self.kids = [k for k in kids if k.get("visible", True)]
        self.presses: list[int] = []

    def _resolve(self) -> dict:
        return {
            "strip_panel": self.panel,
            "strip_row": strip_row(self.panel, self.kids),
            "strip_slider": has_slider(self.kids),
            "open_popup": False,
            "panels": [self.panel],
        }

    def _settle_press(self) -> None:
        """No overlay in front of the strip in any of these states."""

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(hwnd)


def mpx_store_strip() -> CapturedStrip:
    """The captured MPX store panel: two buttons, a slider, two combos."""
    return CapturedStrip(MPX_PANEL, (*MPX_VISIBLE_KIDS, *MPX_HIDDEN_KIDS))


# ------------------------------------------------- the view and the row, by structure


def test_two_buttons_and_a_slider_are_the_store_view() -> None:
    """The slider already decided the view; the row is what was missing."""
    assert classify_strip_view(2, has_slider=True) is StripView.STORE
    assert StripState(button_count=2, has_slider=True).view is StripView.STORE


def test_the_two_button_store_row_is_do_store_then_clear_and_restart() -> None:
    """Left ``Do store``, right ``Clear and restart`` — the agreed interface."""
    assert strip_controls(StripView.STORE, 2) == (
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
    )
    assert STRIP_BUTTON_ORDER[(StripView.STORE, 2)] == (
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
    )
    assert press_index(StripView.STORE, StripControl.DO_STORE, 2) == 0
    assert press_index(StripView.STORE, StripControl.CLEAR_AND_RESTART, 2) == 1


def test_the_captured_row_is_two_buttons_and_the_hidden_pair_is_not_counted() -> None:
    """The visible filter is load-bearing: the unfiltered children are four buttons wide."""
    visible = [k for k in (*MPX_VISIBLE_KIDS, *MPX_HIDDEN_KIDS) if k["visible"]]
    assert len(strip_row(MPX_PANEL, visible)) == 2
    assert len(strip_row(MPX_PANEL, [*MPX_VISIBLE_KIDS, *MPX_HIDDEN_KIDS])) == 4
    assert has_slider(visible) is True


# ------------------------------------------------------- the production press boundary


def test_a_press_on_the_captured_store_row_lands_on_exactly_that_button() -> None:
    """``press(DO_STORE)`` posts to the left handle; ``CLEAR_AND_RESTART`` to the right."""
    strip = mpx_store_strip()
    assert strip.strip_state().button_count == 2
    assert strip.strip_state().view is StripView.STORE

    strip.press(StripControl.DO_STORE)
    assert strip.presses == [MPX_DO_STORE]

    other = mpx_store_strip()
    other.press(StripControl.CLEAR_AND_RESTART)
    assert other.presses == [MPX_CLEAR_AND_RESTART]
    assert strip.presses != other.presses


def test_the_two_button_store_row_binds_nothing_else() -> None:
    """No ``New acquisition`` and no ``Stop`` sits in this row: nothing is posted."""
    for control in (
        StripControl.NEW_ACQUISITION,
        StripControl.STOP,
        StripControl.RECORD,
    ):
        strip = mpx_store_strip()
        with pytest.raises((ValueError, AcquisitionError)):
            strip.press(control)
        assert strip.presses == [], control


def test_two_buttons_without_a_slider_stay_unknown() -> None:
    """The morph state between views: no view, no row, no press."""
    assert classify_strip_view(2, has_slider=False) is StripView.UNKNOWN
    strip = CapturedStrip(
        MPX_PANEL,
        tuple(k for k in MPX_VISIBLE_KIDS if k["cls"] != "TSp_Sliding_Bar"),
    )
    assert strip.strip_state().view is StripView.UNKNOWN
    for control in (StripControl.DO_STORE, StripControl.STOP):
        with pytest.raises((ValueError, AcquisitionError)):
            strip.press(control)
    assert strip.presses == []


def test_the_four_button_no_slider_row_is_still_unbound() -> None:
    """Ledger B10 is untouched: the ambiguous row gains no row and posts nothing."""
    assert classify_strip_view(4, has_slider=False) is StripView.AMBIGUOUS
    assert (StripView.AMBIGUOUS, 4) not in STRIP_BUTTON_ORDER
    assert (StripView.READY, 4) not in STRIP_BUTTON_ORDER
    with pytest.raises(ValueError):
        strip_controls(StripView.AMBIGUOUS, 4)

    row = [_widget(20 + i, "TSp_Button", 10 + 40 * i, 9, 36, 20) for i in range(4)]
    strip = CapturedStrip(MPX_PANEL, row)
    for control in (
        StripControl.RECORD,
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
    ):
        with pytest.raises((ValueError, AcquisitionError)):
            strip.press(control)
    assert strip.presses == []


@pytest.mark.parametrize(
    ("kids", "control", "expected_button"),
    [
        # one button: the recording view's own Stop
        ((_widget(30, "TSp_Button", 10, 9, 60, 20),), StripControl.STOP, 30),
        # three, no slider: the documented ready row, Record in the middle
        (
            tuple(
                _widget(40 + i, "TSp_Button", 10 + 90 * i, 9, 80, 20) for i in range(3)
            ),
            StripControl.RECORD,
            41,
        ),
        # two plus a slider: the captured MPX store row, Do store first
        (MPX_VISIBLE_KIDS, StripControl.DO_STORE, MPX_DO_STORE),
        (MPX_VISIBLE_KIDS, StripControl.CLEAR_AND_RESTART, MPX_CLEAR_AND_RESTART),
    ],
)
def test_a_press_always_lands_on_the_button_its_own_view_bound(
    kids: Sequence[dict], control: StripControl, expected_button: int
) -> None:
    """The binding is per view: the same role moves position as the row morphs.

    ``Do store`` is slot 0 in the captured two-button row and slot 1 in the documented
    three- and four-entry store rows, so a press that keyed on a fixed position — or on
    a width — would land on ``New acquisition`` or on a neighbour here. The handle
    posted is the one at ``press_index`` of the view the tree was just classified into.
    """
    strip = CapturedStrip(MPX_PANEL, kids)
    state = strip.strip_state()
    row = strip_row(strip.panel, strip.kids)
    bound = (state.view, state.button_count) in STRIP_BUTTON_ORDER

    if not bound:
        with pytest.raises((ValueError, AcquisitionError)):
            strip.press(control)
        assert strip.presses == []
        return

    strip.press(control)
    index = press_index(state.view, control, state.button_count)
    assert strip.presses == [row[index]["hwnd"]]
    assert strip.presses == [expected_button]
