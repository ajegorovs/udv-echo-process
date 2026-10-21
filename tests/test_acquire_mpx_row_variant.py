"""The repeated-MPX completion row's **variant discriminator**, at the production boundary.

The 2026-10-21 capture (``.hermes/scratch/multiplexer-development/repeat2-completion-capture.log``
with ``outputs/live/top-level-windows-full-a.png``) shows a strip row that is *not* the row
``STRIP_BUTTON_ORDER[(STORE, 3)]`` binds:

- panel ``477x123``, one visible ``TSp_Sliding_Bar``, the two block/channel combos;
- three painted ``TSp_Button`` widgets 91, 138 and 198 px wide (left → right), plus two
  ``visible: false`` siblings (79 and 85 px) at the same height that are *not* part of the row;
- captions off the frame: ``Do store`` / ``Clear and restart`` / ``Remove current sequence``;
- every button's ``text_wm_gettext`` is empty, so the tree carries no caption at all.

So the roles are named by a **measured variant** (``StripRowVariant.REPEATED_MPX_COMPLETION``),
selected only when the resolved row's signature matches the captured one exactly, and the
count-keyed legacy entry is untouched. These tests pin, offline and with no GUI:

1. the projected capture resolves the variant, with ``Do store`` at index 0;
2. the legacy three-button row of the same key does not, and stays refused;
3. a near miss (one pixel, one button, a different panel) is **unknown**, never a match;
4. a store-only run on the discriminated row presses ``Do store`` and nothing else — zero
   ``Clear and restart``, ``Remove current sequence``, ``Record`` or ``New acquisition`` writes.

Nothing here claims the instrument answers the press: no window is read and no message posted.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from udv_echo_process.acquire.actuator import (
    MEASURED_ROW_VARIANTS,
    STRIP_BUTTON_ORDER,
    OverlayKind,
    StripControl,
    StripRowSignature,
    StripRowVariant,
    StripState,
    StripView,
    WindowTarget,
    measured_row_variant,
    press_index,
    strip_controls,
)
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    completed_row_clauses,
    is_completed_row,
    store_completed,
)
from udv_echo_process.acquire.udop.store import StoreDirectoryVerification
from udv_echo_process.acquire.ui.strip import (
    has_slider,
    strip_row,
    strip_row_signature,
    strip_state_of,
)

MAIN_CLASS = "TMain_Scr"

#: The captured signature: the **only** fact that names this row. Widths are what the panel
#: paints, not an identity — buttons are still pressed by position.
CAPTURED = StripRowSignature(
    panel_width=477, panel_height=123, visible_widths=(91, 138, 198)
)

#: The frame's captions, left → right. Evidence for the role map; never read by production.
FRAME_CAPTIONS = ("Do store", "Clear and restart", "Remove current sequence")


def _kid(
    hwnd: int,
    cls: str,
    left: int,
    top: int,
    w: int,
    h: int,
    *,
    visible: bool = True,
) -> dict:
    """One control in the shape the resolver's child enumeration produces."""
    return {
        "hwnd": hwnd,
        "cls": cls,
        "text": "",
        "left": left,
        "top": top,
        "w": w,
        "h": h,
        "rect": (left, top, left + w, top + h),
        "visible": visible,
    }


#: Panel-local geometry of the captured row: the strip panel is 477x123 and the three painted
#: buttons start at ``top=9``.
CAPTURE_PANEL = _kid(4329288, "TSp_Panel", 0, 0, 477, 123)
CAPTURE_PAINTED = (
    _kid(464008, "TSp_Button", 10, 9, 91, 20),
    _kid(267420, "TSp_Button", 111, 9, 138, 20),
    _kid(5444370, "TSp_Button", 259, 9, 198, 20),
)
#: The two buttons the capture probe reports behind the row with ``visible: false``. They are
#: **not** read by the live resolver (``_visible_children`` enumerates visible descendants), so
#: they must not change the signature — that is what this pair is here to check.
CAPTURE_HIDDEN = (
    _kid(660202, "TSp_Button", 10, 10, 79, 20, visible=False),
    _kid(659836, "TSp_Button", 99, 10, 85, 20, visible=False),
)
CAPTURE_OTHER = (
    _kid(659846, "TSp_Sliding_Bar", 122, 35, 358, 50),
    _kid(4722254, "TComboBox", 86, 92, 45, 21),
    _kid(3148618, "TComboBox", 220, 92, 45, 21),
)

#: What the live resolver hands in: visible children only.
LIVE_KIDS = (*CAPTURE_PAINTED, *CAPTURE_OTHER)
#: What a full control-tree probe carries: the same row plus its hidden siblings.
PROBED_KIDS = (*CAPTURE_PAINTED, *CAPTURE_HIDDEN, *CAPTURE_OTHER)


# --------------------------------------------------------------------------- the discriminator


def test_the_captured_row_is_the_variant_it_was_measured_to_be() -> None:
    """Panel size + painted widths name the row; the hidden siblings do not enter the key."""
    signature = strip_row_signature(CAPTURE_PANEL, LIVE_KIDS)
    assert signature == CAPTURED
    assert measured_row_variant(signature) is StripRowVariant.REPEATED_MPX_COMPLETION
    # A probe that still carries the hidden pair produces the **same** signature, because the
    # live boundary never returns them: the discriminator reads the same in both sources.
    assert strip_row_signature(CAPTURE_PANEL, PROBED_KIDS) == CAPTURED
    # The row itself is still three buttons and only the slider classifies the view.
    assert len(strip_row(CAPTURE_PANEL, LIVE_KIDS)) == 3
    assert has_slider(LIVE_KIDS) is True


def test_the_variant_puts_do_store_at_index_zero_of_the_same_key() -> None:
    """``(STORE, 3)`` keeps its legacy entry; the variant is a second, named row."""
    measured = strip_state_of(3, True, 100, row_signature=CAPTURED)
    assert measured.view is StripView.STORE
    assert measured.row_variant is StripRowVariant.REPEATED_MPX_COMPLETION
    assert measured.controls == (
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
        StripControl.REMOVE_CURRENT_SEQUENCE,
    )
    assert measured.index_of(StripControl.DO_STORE) == 0
    # The third caption is bound as its own role, and nothing in the driver presses it.
    assert measured.index_of(StripControl.REMOVE_CURRENT_SEQUENCE) == 2
    assert StripControl.REMOVE_CURRENT_SEQUENCE is not StripControl.REMOVE_CURRENT_BLOCK
    # The legacy reading of the same key is unchanged: this change widens no count.
    legacy = StripState(button_count=3, has_slider=True, slider_max=100)
    assert legacy.row_variant is None
    assert legacy.controls[0] is StripControl.NEW_ACQUISITION
    assert press_index(StripView.STORE, StripControl.DO_STORE, 3) == 1
    assert press_index(StripView.STORE, StripControl.CLEAR_AND_RESTART, 3) == 2


def test_the_captured_row_is_accepted_and_the_legacy_row_of_the_same_count_is_not() -> (
    None
):
    """Same key, same length, different roles: only the measured row passes the predicate."""
    measured = strip_state_of(3, True, 100, row_signature=CAPTURED)
    assert completed_row_clauses(measured) == ()
    assert is_completed_row(measured) is True
    assert completed_row_clauses(measured) == ()

    for unmeasured in (
        StripState(button_count=3, has_slider=True),
        # The non-MPX 413x123 row: never measured on this host, so it stays unknown.
        StripState(
            button_count=3,
            has_slider=True,
            row_signature=StripRowSignature(
                panel_width=413, panel_height=123, visible_widths=(134, 138, 141)
            ),
        ),
    ):
        clauses = completed_row_clauses(unmeasured)
        assert clauses, unmeasured
        assert "legacy three-button row" in clauses[0]
        assert (
            unmeasured.index_of(StripControl.DO_STORE) == 1
        )  # the index that is refused


@pytest.mark.parametrize(
    "signature",
    [
        # one pixel of panel width
        StripRowSignature(
            panel_width=476, panel_height=123, visible_widths=(91, 138, 198)
        ),
        # one pixel of button width
        StripRowSignature(
            panel_width=477, panel_height=123, visible_widths=(92, 138, 198)
        ),
        # one button more (a fourth painted control)
        StripRowSignature(
            panel_width=477, panel_height=123, visible_widths=(91, 138, 198, 60)
        ),
        # the right widths on another panel height
        StripRowSignature(
            panel_width=477, panel_height=124, visible_widths=(91, 138, 198)
        ),
    ],
    ids=["panel-width", "button-width", "extra-button", "panel-height"],
)
def test_a_near_miss_signature_is_unknown_and_stays_refused(
    signature: StripRowSignature,
) -> None:
    """Geometry is not a universal identity: an unmeasured shape is not the captured row."""
    assert measured_row_variant(signature) is None
    state = StripState(button_count=3, has_slider=True, row_signature=signature)
    assert state.row_variant is None
    assert state.controls[0] is StripControl.NEW_ACQUISITION
    assert completed_row_clauses(state)


def test_the_measured_table_holds_only_the_captured_signature() -> None:
    """One entry, exactly the numbers in the capture — not a family of shapes."""
    assert MEASURED_ROW_VARIANTS == {CAPTURED: StripRowVariant.REPEATED_MPX_COMPLETION}


def test_a_named_variant_never_falls_back_to_the_legacy_row() -> None:
    """A variant is a measurement of one row; an unmeasured key is a refusal, not its count.

    ``None`` is the only value that means *nothing was measured*, and that path keeps answering
    the count-keyed legacy entry — which is what makes an unmeasured three-button store row the
    legacy ``New acquisition``-first row, unchanged. Naming a variant for a key that has no
    measured row must not quietly hand back those roles: ``Do store`` sits at index 0 in the
    repeated-MPX row and index 1 in the legacy row of the same length, so the fallback would
    press ``Clear and restart`` instead of committing, or the reverse.
    """
    with pytest.raises(ValueError) as raised:
        strip_controls(StripView.STORE, 4, StripRowVariant.REPEATED_MPX_COMPLETION)
    message = str(raised.value)
    assert "no measured button row" in message, message
    assert "repeated-mpx-completion" in message, message
    # A key with no legacy entry either refuses for the same reason, not with a KeyError.
    with pytest.raises(ValueError):
        strip_controls(StripView.READY, 3, StripRowVariant.REPEATED_MPX_COMPLETION)

    # The unmeasured path is untouched: ``None`` still answers the legacy entry, and the
    # measured path still answers the variant.
    assert strip_controls(StripView.STORE, 3) == STRIP_BUTTON_ORDER[(StripView.STORE, 3)]
    assert strip_controls(StripView.STORE, 3, None)[0] is StripControl.NEW_ACQUISITION
    assert strip_controls(
        StripView.STORE, 3, StripRowVariant.REPEATED_MPX_COMPLETION
    )[0] is StripControl.DO_STORE


def test_the_four_button_store_row_is_still_refused_whatever_its_roles() -> None:
    """The 4-button legacy row keeps its own entry and is never a completion row."""
    state = StripState(button_count=4, has_slider=True)
    assert state.row_variant is None
    assert completed_row_clauses(state)


# --------------------------------------------------------------------------- the one press


class RecordingStoreScreen:
    """A driver-shaped double that records every gesture the store-only path makes."""

    caption: ClassVar[str] = "UDOP DOP3010.43"

    def __init__(self, state: StripState) -> None:
        self.state = state
        self.presses: list[StripControl] = []
        self.names: list[str] = []
        self.commits = 0

    def bind_target(self, hwnd: int) -> WindowTarget:
        return WindowTarget(
            hwnd=hwnd, thread_id=11, process_id=22, class_name=MAIN_CLASS
        )

    def window_caption(self) -> str:
        return self.caption

    def peek_overlay(self) -> OverlayKind | None:
        return OverlayKind.STORE_DIALOG if self.presses else None

    def strip_state(self) -> StripState:
        return self.state

    def press(self, control: StripControl) -> None:
        self.presses.append(control)

    def set_store_name(self, name: str) -> None:
        self.names.append(name)

    def verify_working_directory(self, directory: Path) -> StoreDirectoryVerification:
        return StoreDirectoryVerification(
            before=str(directory), after=str(directory), changed=False
        )

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        path = Path(directory) / f"{self.names[-1]}.BDD"
        path.write_bytes(b"")
        return path


def _declaration() -> CompletedBlockDeclaration:
    return CompletedBlockDeclaration(
        channels=(1, 2), profiles_per_channel=100, stated_by="operator"
    )


def _run(tmp_path: Path, screen: RecordingStoreScreen):
    return store_completed(
        "repeat2-block",
        tmp_path,
        declaration=_declaration(),
        actuator=screen,
        enumerate_windows=lambda: (4711,),
    )


def test_a_store_only_run_on_the_measured_row_presses_do_store_and_nothing_else(
    tmp_path: Path,
) -> None:
    """One press, one commit: no Clear, no Remove, no Record, no New acquisition."""
    screen = RecordingStoreScreen(strip_state_of(3, True, 100, row_signature=CAPTURED))
    result = _run(tmp_path, screen)

    assert screen.presses == [StripControl.DO_STORE]
    assert screen.commits == 1
    assert screen.names == ["repeat2-block"]
    assert result.strip_state.row_variant is StripRowVariant.REPEATED_MPX_COMPLETION
    for refused in (
        StripControl.CLEAR_AND_RESTART,
        StripControl.REMOVE_CURRENT_SEQUENCE,
        StripControl.REMOVE_CURRENT_BLOCK,
        StripControl.RECORD,
        StripControl.NEW_ACQUISITION,
        StripControl.STOP,
        StripControl.PAUSE,
    ):
        assert refused not in screen.presses


def test_a_store_only_run_on_the_unmeasured_row_presses_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """The refusal lands before the gesture: zero presses, zero names, zero commits, no file."""
    screen = RecordingStoreScreen(StripState(button_count=3, has_slider=True))

    with pytest.raises(Exception) as raised:
        _run(tmp_path, screen)

    assert "legacy three-button row" in str(raised.value)
    assert screen.presses == []
    assert screen.names == []
    assert screen.commits == 0
    assert not any(tmp_path.glob("*"))
