"""The three-button store row a *repeated* multiplexed run ends in, and why it is not bound.

Projection of one live, read-only capture taken 2026-10-21 (``UDOP DOP3010.43``,
``outputs/live/top-level-windows-full-a.png`` plus the control tree of the same instant,
kept in ``.hermes/scratch/multiplexer-development/repeat2-completion-capture.log``):

- the strip panel is 477x123 and holds **three** visible top-row ``TSp_Button`` widgets
  (91, 138 and 198 px wide, left → right), the visible ``TSp_Sliding_Bar``, and the two
  ``TComboBox`` children (``Show block`` = 1, ``Show channel`` = 2);
- two further ``TSp_Button`` widgets are painted *behind* that row at the same height with
  ``visible: false`` — the unfiltered child set is five buttons wide;
- the captions read off the frame are ``Do store`` / ``Clear and restart`` /
  ``Remove current sequence``, and the status bar reads ``Profile 100``, ``CH2``, ``Block 1``;
- ``text_wm_gettext`` is empty for every button, so the tree carries **no caption**: the
  row's length, its slider and its geometry are all the vocabulary has.

That last point is the finding this module pins. ``STRIP_BUTTON_ORDER`` keys roles on
``(view, button_count)``, and the repository already binds ``(STORE, 3)`` as
``new_acquisition`` / ``do_store`` / ``clear_and_restart`` (crop-derived, the non-MPX
three-button store panel 413x123). The observed completion row is the *same* key —
``STORE`` with three visible buttons and a slider — but its captions put ``Do store``
first, where the existing row puts ``New acquisition``. So ``press(DO_STORE)`` from this
row would land on index 1, which the frame paints ``Clear and restart``: the operator's
unsaved block, discarded by a press meant to commit it.

Therefore the MPX completion path must keep refusing this row **as a bare count**. Widening it
to ``button_count == 3`` would be widening on a count that two different rows share, which is
the failure ``classify_strip_view``'s own docstring refuses to make. The row is instead named by
its **measured signature** (``StripRowVariant.REPEATED_MPX_COMPLETION``), selected only on an
exact match with the captured geometry — see ``tests/test_acquire_mpx_row_variant.py``.
Nothing here presses, stores, clears or discards anything: the assertions are the refusal and the
disagreement that causes it.
"""

from __future__ import annotations

import pytest

from udv_echo_process.acquire.actuator import (
    STRIP_BUTTON_ORDER,
    StripControl,
    StripRowSignature,
    StripRowVariant,
    StripState,
    StripView,
    classify_strip_view,
    press_index,
)
from udv_echo_process.acquire.store_completed import completed_row_clauses
from udv_echo_process.acquire.ui.strip import has_slider, strip_row

#: Read off the captured frame, left → right. Evidence, not a role map: the second and
#: third entries are what index 1 and index 2 *paint*, and no role in
#: :class:`StripControl` is claimed for the third.
FRAME_CAPTIONS = ("Do store", "Clear and restart", "Remove current sequence")


def _kid(
    hwnd: int,
    cls: str,
    left: int,
    top: int,
    w: int,
    h: int,
    *,
    text: str = "",
    visible: bool = True,
) -> dict:
    """One control in the shape ``_visible_children`` produces, panel-local."""
    return {
        "hwnd": hwnd,
        "cls": cls,
        "text": text,
        "left": left,
        "top": top,
        "w": w,
        "h": h,
        "rect": (left, top, left + w, top + h),
        "visible": visible,
    }


#: Panel-local geometry of the three visible buttons (91/138/198 px wide at ``top=9``).
_STORE3_BUTTONS: tuple[dict, ...] = (
    _kid(464008, "TSp_Button", 10, 9, 91, 20),
    _kid(267420, "TSp_Button", 111, 9, 138, 20),
    _kid(5444370, "TSp_Button", 259, 9, 198, 20),
)
#: The two buttons painted behind the row at the same height, ``visible: false``.
_STORE3_HIDDEN: tuple[dict, ...] = (
    _kid(660202, "TSp_Button", 10, 10, 79, 20, visible=False),
    _kid(659836, "TSp_Button", 99, 10, 85, 20, visible=False),
)
_STORE3_OTHER: tuple[dict, ...] = (
    _kid(659846, "TSp_Sliding_Bar", 122, 35, 358, 50),
    _kid(4722254, "TComboBox", 86, 92, 45, 21, text="1"),
    _kid(3148618, "TComboBox", 220, 92, 45, 21, text="2"),
)
STORE3_KIDS: tuple[dict, ...] = (*_STORE3_BUTTONS, *_STORE3_OTHER)
STORE3_KIDS_WITH_HIDDEN: tuple[dict, ...] = (
    *_STORE3_BUTTONS,
    *_STORE3_HIDDEN,
    *_STORE3_OTHER,
)
STORE3_PANEL = _kid(4329288, "TSp_Panel", 0, 0, 477, 123)


def _visible(children: tuple[dict, ...]) -> tuple[dict, ...]:
    return tuple(k for k in children if k.get("visible", True))


def test_the_captured_row_reads_as_a_store_row_of_three_buttons() -> None:
    """The slider, not the count, classifies the view — and the hidden pair is not counted."""
    visible = _visible(STORE3_KIDS_WITH_HIDDEN)
    assert len(strip_row(STORE3_PANEL, visible)) == 3
    assert len(strip_row(STORE3_PANEL, STORE3_KIDS_WITH_HIDDEN)) == 5
    assert has_slider(visible) is True
    assert classify_strip_view(3, has_slider=True) is StripView.STORE


def test_the_key_this_row_shares_with_the_other_three_button_store_row() -> None:
    """``(STORE, 3)`` is one key for two rows: length and slider cannot tell them apart.

    The non-MPX three-button store panel (413x123) is bound in the same table entry as this
    477x123 completion row, and ``StripState`` carries no caption, width or panel-size field
    with which to separate them. That is why a count is not a discriminator here.
    """
    assert (StripView.STORE, 3) in STRIP_BUTTON_ORDER
    assert (
        StripState(button_count=3, has_slider=True).controls
        == STRIP_BUTTON_ORDER[(StripView.STORE, 3)]
    )


def test_the_binding_would_press_a_different_caption_than_the_frame_paints() -> None:
    """``DO_STORE`` resolves to index 1 while the frame paints ``Do store`` at index 0.

    This is the measured disagreement that keeps the MPX completion path closed to this row:
    the press that would commit the block lands on ``Clear and restart``.
    """
    assert FRAME_CAPTIONS[0] == "Do store"
    assert STRIP_BUTTON_ORDER[(StripView.STORE, 3)][0] is StripControl.NEW_ACQUISITION
    assert press_index(StripView.STORE, StripControl.DO_STORE, 3) == 1
    assert (
        FRAME_CAPTIONS[press_index(StripView.STORE, StripControl.DO_STORE, 3)]
        == "Clear and restart"
    )


@pytest.mark.parametrize(
    "state",
    [
        StripState(button_count=3, has_slider=True, slider_max=100),
        StripState(button_count=4, has_slider=True, slider_max=100),
        StripState(button_count=3, has_slider=False),
    ],
    ids=["store-3", "store-4", "three-without-a-slider"],
)
def test_the_store_only_path_refuses_these_rows_by_name(state: StripState) -> None:
    """Fail-closed: the refusal names the row and nothing is pressed from it."""
    clauses = completed_row_clauses(state)
    assert clauses, state
    assert "slider" in clauses[0] or "binds" in clauses[0]


def test_the_two_button_completion_row_is_still_a_completion_row() -> None:
    """The measured 2026-10-20 row keeps its acceptance, by count and by role."""
    accepted = StripState(button_count=2, has_slider=True, slider_max=100)
    assert completed_row_clauses(accepted) == ()
    assert press_index(StripView.STORE, StripControl.DO_STORE, 2) == 0


def test_this_row_is_accepted_only_once_its_own_geometry_names_it() -> None:
    """The escape from the refusal is the measured variant, not a widened count.

    ``StripState(row_signature=…)`` carrying the captured 477x123 / 91-138-198 reading makes
    ``Do store`` index 0 of a **named** row; the same three buttons with no measurement (or any
    other geometry) stay on the legacy row and stay refused. See
    ``tests/test_acquire_mpx_row_variant.py`` for the discriminator's own boundary.
    """
    measured = StripState(
        button_count=3,
        has_slider=True,
        slider_max=100,
        row_signature=StripRowSignature(
            panel_width=477, panel_height=123, visible_widths=(91, 138, 198)
        ),
    )
    assert measured.row_variant is StripRowVariant.REPEATED_MPX_COMPLETION
    assert completed_row_clauses(measured) == ()
    assert measured.index_of(StripControl.DO_STORE) == 0
    assert measured.index_of(StripControl.CLEAR_AND_RESTART) == 1
    # The frame's captions and the measured row agree position by position.
    assert [
        FRAME_CAPTIONS[measured.index_of(control)] for control in measured.controls
    ] == list(FRAME_CAPTIONS)
    # Without that measurement the count alone is still refused.
    assert completed_row_clauses(StripState(button_count=3, has_slider=True))
