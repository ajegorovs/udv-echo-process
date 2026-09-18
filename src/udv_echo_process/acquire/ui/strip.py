"""The recording strip's pure interpreter: its row, its state, and the row that binds nothing.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), moved out of
:mod:`udv_echo_process.acquire.driver` by Patch 2's widget slice. Nothing here enumerates a window
or sends a message: every function answers from an already-resolved panel, its children and the
reading the resolver took.

**What this module is the authority for**

- the strip's **row geometry** (:func:`strip_row`, which is ``driver._strip_row`` moved verbatim)
  and the **slider mark** that decides the view (:func:`has_slider`) — the panel is draggable and
  morphs (``98x40`` → ``352x40`` → ``413x123``), so its buttons are identified by their order in
  the current row, never by a width (134 vs 138 px is too close) and never by a caption;
- the **state** one resolved strip is in (:func:`strip_state_of`);
- the shape gate's strip clauses (:func:`strip_clauses`), so the gate asks this module what the row
  is instead of reading a row itself.

**What belongs elsewhere**

- the vocabulary and the tables — ``STRIP_BUTTON_ORDER``, ``StripView``, ``StripControl``,
  ``StripState``, ``STARTABLE_VIEWS`` and :func:`classify_strip_view` are
  :mod:`udv_echo_process.acquire.actuator`'s, and are re-exported here so the strip interpreter is
  one import;
- the gesture: a strip press is ``Win32Actuator.press`` and the held ``WM_LBUTTONDOWN`` is
  ``Win32Actuator._click_hold`` — the gesture the live sessions proved, which moves verbatim;
- the *dialog's* bottom button band (``ui.dialog.bottom_row``), which is a dialog binding and not
  a strip one.

**The four-button, no-slider row (ledger B10 — critical, and *device-pending*).**

Two descriptions of that state disagree about *which button is which*, and this module does not
reconcile them: the committed crop ``UI-STRIP-01`` (``ui-crops/run-controls.png``) paints
``Pause`` / ``Record`` / ``Clear and restart`` for the three-button row, while ``UI-STRIP-02``
(``ui-crops/overlay-record-extra-block.png``, the grown state with a block held) paints
``New acquisition`` / ``Do store`` / ``Clear and restart`` / ``Remove current block`` for the
four-button row. No live tree of the grown state exists in the repository, so the row is read
through :data:`…actuator.STRIP_BUTTON_ORDER` like every other row — the *reading* is unchanged —
and the disagreement itself is pinned in ``tests/test_acquire_strip_ambiguity.py``, which is where
the role map goes the day ``docs/dop3000/device-verification.md`` V4 settles it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from udv_echo_process.acquire.actuator import (
    STARTABLE_VIEWS,
    STRIP_BUTTON_ORDER,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    press_index,
    strip_controls,
)
from udv_echo_process.acquire.ui.model import ScreenObservation

__all__ = [
    "STARTABLE_VIEWS",
    "STRIP_BUTTON_ORDER",
    "StripControl",
    "StripState",
    "StripView",
    "classify_strip_view",
    "has_slider",
    "press_index",
    "strip_clauses",
    "strip_controls",
    "strip_row",
    "strip_state_of",
]


def strip_row(panel: dict, kids: Sequence[dict]) -> list[dict]:
    """The strip's top-row buttons, left -> right.

    Two buttons the panel never paints sit *below* the panel's own rect; requiring a
    button's centre to lie inside the panel excludes them. Width is never an identity —
    134 vs 138 px is too close — so the row is sorted by ``left`` and addressed by index
    (:func:`…actuator.press_index`) (docs/16 §7, §10).
    """
    panel_bottom, band = panel["top"] + panel["h"], panel["top"] + 30
    return sorted(
        (
            k
            for k in kids
            if k["cls"] == "TSp_Button"
            and k["top"] < band
            and (k["top"] + k["h"] // 2) < panel_bottom
        ),
        key=lambda k: k["left"],
    )


def has_slider(kids: Sequence[Mapping]) -> bool:
    """True when the panel owns a ``TSp_Sliding_Bar`` child — the store view's own mark.

    The slider is decisive rather than one signal among several: it exists only in the store
    view (``actuator.STRIP_BUTTON_ORDER``), so its presence names the view whatever the row's
    length is.
    """
    return any(k["cls"] == "TSp_Sliding_Bar" for k in kids)


def strip_state_of(
    button_count: int, has_slider: bool, slider_max: int | None = None
) -> StripState:
    """The strip state implied by a structure just resolved — the reading, not a choice.

    ``slider_max`` (the selected block's profile count) is deliberately defaulted to ``None``:
    the reference never read the slider's range, and guessing is worse than saying nothing.
    """
    return StripState(button_count=button_count, has_slider=has_slider, slider_max=slider_max)


def strip_clauses(observation: ScreenObservation) -> tuple[str, ...]:
    """The strip's clauses of the shape gate: what this row is, or why it is not a shape.

    Returned rather than appended so the gate keeps its own order (the surface clauses come first,
    because the row a wrong-surface screen would diagnose is a *symptom* of the surface being
    wrong — ledger B06).
    """
    strip = observation.strip.panel
    row = list(observation.strip.row)
    view: StripView | None = None
    if observation.strip.state_reading is not None:
        try:
            view = StripView(observation.strip.state_reading)
        except ValueError:
            view = None
    if strip is None:
        return (
            (
                "no recording strip panel resolved: no short button-hosting panel sits in the "
                "plot's 0.30-0.70 band, so which buttons mean pause, record and stop is unstated"
            ),
        )
    if observation.plot is None:
        return (
            (
                "the plot band did not resolve, so the strip's own rule (the button panel in the "
                "middle of the plot) could not be applied to the panel that was found"
            ),
        )
    if view is None or (view, len(row)) not in STRIP_BUTTON_ORDER:
        return (
            (
                f"the strip's row holds {len(row)} button(s) in view "
                f"{observation.strip.state_reading!r}, which is no row in STRIP_BUTTON_ORDER: a "
                "different button panel sits in the plot's middle band, and a press would be "
                "bound to the wrong position"
            ),
        )
    return ()
