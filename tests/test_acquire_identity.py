"""One identity per panel, decided once — the classifier, its order, and the resolver that reads it.

``docs/dop3000/identity-classification-plan.md`` §2.1 is the specification this file pins, item by
item, on **synthesised shapes**: the measured rects below are quoted from the 2026-09-19 kept reads
(``docs/dop3000/device-verification.md``, *the four-button strip, block-held* and *the removal
guard*) because they are the shapes the rules were written against — and a shape, never a handle, is
what a case here binds to.

Three things are asserted together, and each of them is a claim the plan makes:

- **the order, and the admitting clause of §2.2** — the 453/502/551 px strip panels own exactly one
  ``TComboBox`` and ``ui.dialog._is_dialog_panel`` accepts that for any panel wider than 400 px; the
  392x132 guard is admitted by no dialog predicate at all; the 149x59 cursor info box is smaller
  than the width guard. So a strip panel is the strip **while the dialog predicate says it is a
  dialog** (that the two disagree is the point), the guard is a warning, and the box is neither;
- **identity is not a binding** — the measured 453x40 four-button, no-slider row is the strip and
  stays :attr:`…actuator.StripView.AMBIGUOUS`, which ``ui/strip.py`` refuses by name (ledger B10);
- **the resolver reads it** — ``roles["identities"]``, ``roles["blocking_surface"]``, the strip
  panel, ``value_dialogs``/``browse_dialogs``, ``open_popup`` and the surface kind, on a tree
  resolved through ``Win32Actuator._resolve`` for real (the ``win32gui`` stand-in is
  ``test_acquire_surface_classification``'s, imported rather than copied, so this file cannot invent
  a window the resolver does not read).

Nothing here presses anything or enumerates a live window, and no case can: the stand-in answers a
flat table of rows, and the cases that ask a surface question call a pure function.
"""

from __future__ import annotations

import pytest
from test_acquire_surface_classification import ORIGIN, WINDOW_HWND, _MeasuredGui, _row

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import StripView, classify_strip_view
from udv_echo_process.acquire.ui.dialog import _is_dialog_panel
from udv_echo_process.acquire.ui.identity import (
    PanelIdentity,
    ScreenContext,
    blocking_surface,
    panel_identity,
)
from udv_echo_process.acquire.ui.layout import classify_surface
from udv_echo_process.acquire.ui.model import Rect, SurfaceKind
from udv_echo_process.acquire.ui.strip import press_refusal, strip_state_of

# ------------------------------------------------------------------ the measured shapes, as fixtures
#
# Every rect below is a *read*, quoted where it is named, and none of them is an identity: they are
# the shapes the classifier's warrants were written against, handed to it as a tree.

MENUBAR_PANEL = (0, 23, 1920, 55)
COLUMN_PANEL = (0, 55, 190, 1016)
PLOT = (200, 65, 1910, 1006)
STATUS_PANEL = (0, 1016, 1920, 1050)

#: The recording strip's own panel, in the three grown states and the paused one: 453x40
#: (intermediate, four buttons, no visible slider), 502x123 (after a removal), 551x123 (block held)
#: and 370x123 (`Pause` / `Record` / `Clear and restart` plus the slider) — all at the same top-left
#: corner, sized by the state (device-verification.md, *the strip's state tree*).
STRIP_PANEL_453 = (343, 414, 796, 454)
STRIP_PANEL_502 = (343, 414, 845, 537)
STRIP_PANEL_551 = (343, 414, 894, 537)
STRIP_PANEL_370 = (343, 414, 713, 537)

#: The row's buttons, left to right, at the rects the reads carry (the grown rows are wider than the
#: intermediate one, which is the state's own difference and not a binding).
ROW_453 = ((353, 424, 432, 444), (442, 424, 527, 444), (537, 423, 628, 443), (638, 423, 776, 443))
ROW_370 = ((353, 424, 444, 444), (454, 423, 545, 443), (555, 423, 693, 443))
ROW_502 = ((353, 424, 444, 444), (454, 423, 545, 443), (555, 423, 644, 443), (654, 423, 825, 443))
ROW_551 = ((353, 424, 444, 444), (454, 423, 545, 443), (555, 423, 693, 443), (703, 423, 874, 443))

#: The two caption-less toggles the grown panel owns **below its own rect** (measured
#: ``[350,467,401,482]`` and ``[409,467,453,482]``, the `Profiles history in` selector): in-panel in
#: the 123 px states, outside the 40 px one, and never part of the strip's row.
TOGGLES = ((350, 467, 401, 482), (409, 467, 453, 482))

#: The `Show block` combo — the child whose class makes ``_is_dialog_panel`` admit a strip panel.
COMBO = (429, 506, 474, 527)
SLIDER = (465, 449, 848, 499)

#: The cursor info box: measured ``TSp_Panel [908,466,1057,525]`` = 149x59 with one caption-less
#: child panel ``[916,475,1045,514]``, and owning ``TSp_Button [917,578,997,598]`` — a button whose
#: centre lies **outside** the box.
INFO_BOX = (908, 466, 1057, 525)
INFO_BOX_CHILD = (916, 475, 1045, 514)
INFO_BOX_BUTTON = (917, 578, 997, 598)

#: The reused destructive guard: measured ``TSp_Panel 4393476 [772,490,1164,622]`` = 392x132 with
#: exactly two buttons — ``[1000,587,1069,612]`` (left/safe) and ``[1079,587,1154,612]``.
WARNING_PANEL = (772, 490, 1164, 622)
WARNING_BUTTONS = ((1000, 587, 1069, 612), (1079, 587, 1154, 612))

#: The measured ``Define TGC`` overlay: ``TSp_Panel [400,168,850,288]`` = 450x120, six children, its
#: four buttons' tops 46-89 px below its own top — the clause that keeps it out of the strip's row.
TGC_PANEL = (400, 168, 850, 288)
TGC_BUTTONS = (
    (406, 214, 521, 234),
    (408, 238, 516, 263),
    (710, 257, 770, 277),
    (778, 256, 838, 276),
)
TGC_VALUE_BUTTONS = ((429, 177, 544, 209), (558, 177, 653, 205))

#: The measured ``Parameters`` popup panel (``(169, 55, 401, 250)``, 195 px tall) and its entries.
POPUP_PANEL = (169, 55, 401, 250)
POPUP_ENTRIES = ((173, 61, 240, 80), (173, 95, 240, 114), (173, 130, 240, 149))

#: The measured ``Operating parameters`` dialog: 627x384 with 21 direct children and fifteen
#: ``TSp_Value_Button`` fields of its own (``tests/data/udop-parameters-dialog-tree.json``).
DIALOG_PANEL = (655, 364, 1282, 748)

#: The screen context the measured reads carry: the monitor's rect and the menubar band's handle.
MONITOR = ScreenContext(plot=Rect.from_control(_row(WINDOW_HWND + 1, "TDop_Plot", 0, PLOT)), menubar=1)


def _row_of(hwnd: int, cls: str, rect: tuple[int, int, int, int], text: str = "") -> dict:
    """One control as the resolver's own row shape (``_visible_children``'s keys)."""
    left, top, right, bottom = rect
    return {
        "hwnd": hwnd,
        "cls": cls,
        "text": text,
        "left": left,
        "top": top,
        "w": right - left,
        "h": bottom - top,
        "rect": (left, top, right, bottom),
        "visible": True,
    }


def _shape(rects: tuple[tuple[int, int, int, int], ...], first: int) -> list[dict]:
    """``TSp_Button`` rows for a run of rects, in the order given."""
    return [_row_of(first + index, "TSp_Button", rect) for index, rect in enumerate(rects)]


def _tgc_kids(first: int = 100) -> list[dict]:
    """The ``Define TGC`` panel's own six children: four buttons and two value buttons."""
    return [
        *_shape(TGC_BUTTONS, first),
        *[
            _row_of(first + 10 + index, "TSp_Value_Button", rect)
            for index, rect in enumerate(TGC_VALUE_BUTTONS)
        ],
    ]


# ------------------------------------------------------------------------- the per-panel pass
# The classifier's own entry point, asked of rows in the resolver's own shape and — through
# ``ui.identity``'s own reconciliation — of the normalized projection the pure rules hold.


def test_a_strip_panel_that_owns_a_combo_and_is_wider_than_400_is_a_strip_not_a_dialog() -> None:
    """§2.2's admitting clause: the strip is the strip *while the dialog predicate says it is one*.

    The 453x40 intermediate panel directly owns exactly one ``TComboBox`` — the ``Show block`` combo
    — and ``_DIALOG_INPUT_CLASSES`` accepts that for any panel wider than 400 px, which is how the
    strip's own panel entered ``value_dialogs`` and, from there, left the strip vote while the screen
    reported no popup and its surface ``dialog``. The two verdicts are asserted side by side on
    purpose: the classifier's answer is not "the predicate is wrong", it is that the panel's own
    shape — a top row inside its own top 30 px, in the plot's middle band — is asked **first**.
    """
    panel = _row_of(3, "TSp_Panel", STRIP_PANEL_453)
    kids = [
        *_shape(ROW_453, 100),
        *_shape(TOGGLES, 200),
        _row_of(300, "TComboBox", COMBO, text="2"),
    ]

    assert _is_dialog_panel(panel, kids), (
        "the measured counterexample no longer holds: this panel is not in the dialog union the "
        "plan's §2.2 measures, so this case is not about the clause it was written for"
    )
    assert panel_identity(panel, kids, context=MONITOR) is PanelIdentity.MEASUREMENT_STRIP


def test_the_measured_strip_shapes_are_strips_and_the_370_one_too() -> None:
    """All four measured strip shapes are the strip: 453, 502, 551 and the 370 px paused one.

    The 370 px panel is the shape the *old* predicate let through for the wrong reason (``w > 400``
    stopped 30 px short of it) and the one whose screen reported an open menu; the 453/502/551
    shapes are the ones it admitted. The law is the same for all four — the panel's own top row
    inside its own top 30 px, with that row's centre in the plot's 0.30-0.70 band — and the slider is
    not required: the 453 row has none and is the strip.
    """
    for rect, row, has_slider in (
        (STRIP_PANEL_453, ROW_453, False),
        (STRIP_PANEL_502, ROW_502, True),
        (STRIP_PANEL_551, ROW_551, True),
        (STRIP_PANEL_370, ROW_370, True),
    ):
        kids = [*_shape(row, 100), *_shape(TOGGLES, 200)]
        if has_slider:
            kids.append(_row_of(300, "TSp_Sliding_Bar", SLIDER))
        assert (
            panel_identity(_row_of(3, "TSp_Panel", rect), kids, context=MONITOR)
            is PanelIdentity.MEASUREMENT_STRIP
        ), rect


def test_the_measured_four_button_row_is_the_strip_and_still_binds_nothing() -> None:
    """Identity is not a binding (ledger B10): the row is the strip, and ``ui/strip.py`` refuses it.

    The strip is identified and its state read off that same row — four buttons, no slider — and the
    state remains :attr:`…StripView.AMBIGUOUS`, whose binding refuses by name. A classification that
    made the row pressable would be the ledger B10 defect again, one layer up.
    """
    panel = _row_of(3, "TSp_Panel", STRIP_PANEL_453)
    kids = [*_shape(ROW_453, 100), *_shape(TOGGLES, 200)]

    assert panel_identity(panel, kids, context=MONITOR) is PanelIdentity.MEASUREMENT_STRIP

    state = strip_state_of(button_count=len(ROW_453), has_slider=False, slider_max=None)
    assert state.view is StripView.AMBIGUOUS
    assert classify_strip_view(len(ROW_453), False) is StripView.AMBIGUOUS
    assert state.is_startable is False
    assert press_refusal(state) is not None


def test_a_compact_two_button_panel_with_no_store_dialog_is_a_warning() -> None:
    """The measured warning family — 392x132, and the two other measured members of the family.

    The family rule is the discriminator rather than one rect: compact (wider than 250 px, taller
    than 90 px) with a **two-button** bottom band. The store overwrite warning's geometry is not
    measured, and 397x135 / 353x155 are, so a rule written around 392x132 alone would miss it.
    """
    kids = _shape(WARNING_BUTTONS, 100)
    assert (
        panel_identity(_row_of(3, "TSp_Panel", WARNING_PANEL), kids, context=MONITOR)
        is PanelIdentity.WARNING
    )
    for rect in ((300, 300, 697, 435), (300, 300, 653, 455)):
        assert (
            panel_identity(_row_of(3, "TSp_Panel", rect), kids, context=MONITOR)
            is PanelIdentity.WARNING
        ), rect


def test_a_strip_panel_is_never_a_warning_and_a_warning_is_never_a_strip() -> None:
    """The two families cannot wear each other's shape, in either direction.

    The warning is asked on the strip's own panel shape and the strip on the warning's: the
    warning's pair sits in its **bottom band** (``ui.dialog.bottom_row``'s own last 70 px, and
    exactly two of them), while the strip's row sits in its top 30 px — so the two rules cannot meet
    on one panel. The same clause is what keeps the family rule off ``Define TGC``, whose own bottom
    band resolves three buttons.
    """
    strip_kids = [
        *_shape(ROW_551, 100),
        *_shape(TOGGLES, 200),
        _row_of(300, "TSp_Sliding_Bar", SLIDER),
    ]
    assert (
        panel_identity(_row_of(3, "TSp_Panel", WARNING_PANEL), strip_kids, context=MONITOR)
        is not PanelIdentity.WARNING
    )
    assert (
        panel_identity(
            _row_of(3, "TSp_Panel", STRIP_PANEL_551), _shape(WARNING_BUTTONS, 100), context=MONITOR
        )
        is not PanelIdentity.MEASUREMENT_STRIP
    )
    assert (
        panel_identity(_row_of(3, "TSp_Panel", TGC_PANEL), _tgc_kids(), context=MONITOR)
        is PanelIdentity.OVERLAY
    )


def test_a_browse_store_dialog_is_never_a_warning() -> None:
    """The store discriminator is asked before the warning family (plan §2.1 item 2).

    A store dialog is a panel owning an edit **and** a ``TSp_Browse`` — and it may well be compact
    with a two-button band, which is the warning's own shape. Reading it as a warning would send the
    point down the warning answer path and lose its commit path, so the discriminator runs first.
    """
    panel = _row_of(3, "TSp_Panel", WARNING_PANEL)
    kids = [
        *_shape(WARNING_BUTTONS, 100),
        _row_of(200, "TEdit", (820, 500, 1000, 520)),
        _row_of(201, "TSp_Browse", (1010, 500, 1090, 520)),
    ]

    assert panel_identity(panel, kids, context=MONITOR) is PanelIdentity.APPLICATION_DIALOG


def test_a_panel_owning_a_button_outside_its_own_rect_is_neither_a_strip_nor_a_popup() -> None:
    """The cursor info box: small, caption-less, a caption-less child panel, no in-panel row.

    Measured ``TSp_Panel [908,466,1057,525]`` = 149x59 with the child panel ``[916,475,1045,514]``
    and the owned button ``[917,578,997,598]`` — whose centre lies *outside* the box. Counting an
    owned button as an in-panel row is what made the strip vote pick the box in the block-held and
    intermediate reads (``strip.panel_id`` was the box, view ``unknown``, 0 buttons), and treating
    that button as "a panel that hosts a button" is what made a paused screen report an open menu.
    Neither reading survives: the box is ``CURSOR_INFO``, and an owned button outside the panel
    confers nothing.
    """
    panel = _row_of(3, "TSp_Panel", INFO_BOX)
    kids = [
        _row_of(100, "TSp_Panel", INFO_BOX_CHILD),
        _row_of(101, "TSp_Button", INFO_BOX_BUTTON),
    ]

    identity = panel_identity(panel, kids, context=MONITOR)
    assert identity is PanelIdentity.CURSOR_INFO
    assert identity is not PanelIdentity.MEASUREMENT_STRIP
    assert identity is not PanelIdentity.MENU_POPUP
    # The box is not a blocking surface either: a screen with one cursor up is a measurement screen,
    # and the box is an incidental painted surface (plan §2.1 item 5).
    assert blocking_surface({3: identity}) is None
    # ...and the same question asked of a panel that is *only* a button outside its own rect.
    bare = _row_of(4, "TSp_Panel", INFO_BOX)
    outside = [_row_of(101, "TSp_Button", INFO_BOX_BUTTON)]
    assert panel_identity(bare, outside, context=MONITOR) not in (
        PanelIdentity.MEASUREMENT_STRIP,
        PanelIdentity.MENU_POPUP,
    )


def test_the_measured_tgc_overlay_is_an_overlay() -> None:
    """``Define TGC``: over the monitor, its own button row 46-89 px below its own top.

    Measured ``TSp_Panel [400,168,850,288]`` = 450x120, six children, two of them
    ``TSp_Value_Button`` — so the canonical dialog predicate accepts it (``> 400 px`` and an input
    child), which is V3's measured failure: the run reported "a dialog is up" for the overlay and
    then blamed the strip. Its buttons' tops are what keep it out of the strip's warrant, and the
    absence of the real strip panel from that read's visible set is why the overlay has to be found
    on its own evidence rather than beside a resolved strip.
    """
    panel = _row_of(3, "TSp_Panel", TGC_PANEL)
    kids = _tgc_kids()

    assert _is_dialog_panel(panel, kids)  # the predicate it is claimed before, not by
    assert panel_identity(panel, kids, context=MONITOR) is PanelIdentity.OVERLAY
    # **Where the order shows itself.** With a menubar band but no monitor resolved, the overlay's
    # own clause cannot be asked (it is "over the monitor") and the shape falls to the dialog
    # fallback — the measured pre-fix reading, which is why that fallback is last. With neither a
    # band nor a monitor there is no measurement screen at all: the panel is a *replacement*
    # surface's widget band, which is what ``Compare profiles`` / ``Measure US field`` leave behind.
    assert (
        panel_identity(panel, kids, context=ScreenContext(menubar=1))
        is PanelIdentity.APPLICATION_DIALOG
    )
    assert panel_identity(panel, kids, context=ScreenContext()) is PanelIdentity.REPLACEMENT


def test_the_measured_operating_dialog_is_a_dialog_and_not_an_overlay() -> None:
    """The value table's own shape is what the broad fallback is for (plan §2.1 item 8).

    627x384 with 21 direct children — "full of controls", the reference's own floor — so the overlay
    clause (which asks for *fewer* than that) does not swallow it, whatever button band it paints low
    in its own rect.
    """
    kids = [
        *[
            _row_of(100 + index, "TSp_Value_Button", (786, 420 + 20 * index, 926, 440 + 20 * index))
            for index in range(15)
        ],
        _row_of(200, "TComboBox", (1083, 373, 1150, 393), text="1"),
        *[
            _row_of(300 + index, "TSp_Button", (900 + 90 * index, 700, 990 + 90 * index, 725))
            for index in range(5)
        ],
    ]
    panel = _row_of(3, "TSp_Panel", DIALOG_PANEL)

    assert len(kids) == 21
    assert panel_identity(panel, kids, context=MONITOR) is PanelIdentity.APPLICATION_DIALOG


def test_the_parameters_popup_is_a_popup_and_an_unknown_button_panel_is_not() -> None:
    """Plan §2.1 item 1: the demonstrated popup predicate and its entries — and nothing generic.

    ``parameters_overlay``'s own two facts (the measured ``left`` and a height above the recorded
    one) plus ``entry_buttons``' containment; an unknown panel that merely hosts a button is not a
    popup, which is the reading that made the ``Define TGC`` overlay, every warning box and the
    cursor info box report an open menu.
    """
    popup = _row_of(3, "TSp_Panel", POPUP_PANEL)

    assert panel_identity(popup, _shape(POPUP_ENTRIES, 100), context=MONITOR) is (
        PanelIdentity.MENU_POPUP
    )
    # A panel of the same height that is not the measured popup's own geometry: not a popup.
    elsewhere = _row_of(4, "TSp_Panel", (300, 55, 532, 250))
    assert panel_identity(elsewhere, _shape(POPUP_ENTRIES, 200), context=MONITOR) is not (
        PanelIdentity.MENU_POPUP
    )
    # ...and the measured geometry with nothing inside it is not a popup either.
    assert panel_identity(popup, [_row_of(100, "TSp_Button", (900, 900, 950, 920))]) is not (
        PanelIdentity.MENU_POPUP
    )


def test_a_replacement_screen_is_a_replacement() -> None:
    """Plan §2.1 item 6: no menubar band and no plot, while the client area hosts a widget band.

    ``Compare profiles`` / ``Measure US field`` replace the client area (UI-OVERLAY-19/21/22), so the
    surface's own widget band is all that is left — and it is what the resolver used to bind as the
    strip. The identity is the band's and the surface kind is the replacement's; neither is an
    overlay, and neither claims a channel mode (ledger B08).
    """
    context = ScreenContext(plot=None, menubar=None)
    band = _row_of(3, "TSp_Panel", (0, 23, 1000, 83))
    kids = _shape(tuple((10 + 140 * index, 33, 90 + 140 * index, 53) for index in range(6)), 100)

    assert panel_identity(band, kids, context=context) is PanelIdentity.REPLACEMENT

    roles = {
        "window": 0,
        "class_name": driver.MAIN_CLASS,
        "client": (1920, 1027),
        "origin": ORIGIN,
        "raw": [band, *kids],
        "panels": [band],
        "menu": {},
        "menu_band": None,
        "plot": None,
        "open_popup": False,
        "value_dialogs": set(),
        "browse_dialogs": set(),
        "strip_panel": band,
        "strip_row": kids,
        "state": classify_strip_view(len(kids), False).value,
        "left_panel": None,
        "param_rows": [],
        "params": {},
    }
    assert classify_surface(roles) is SurfaceKind.REPLACEMENT


# ------------------------------------------------------------------- the blocking-surface result


def _blocked(panel: dict, kids: list[dict]) -> PanelIdentity | None:
    """The blocking surface of a one-panel screen, classified — what the cases below read."""
    return blocking_surface({panel["hwnd"]: panel_identity(panel, kids, context=MONITOR)})


def test_the_blocking_surface_names_warning_overlay_and_popup() -> None:
    """``blocking_surface`` answers with the surface to clear, not with "a button panel is up"."""
    warning = _row_of(3, "TSp_Panel", WARNING_PANEL)
    tgc = _row_of(4, "TSp_Panel", TGC_PANEL)
    popup = _row_of(5, "TSp_Panel", POPUP_PANEL)

    assert _blocked(warning, _shape(WARNING_BUTTONS, 100)) is PanelIdentity.WARNING
    assert _blocked(tgc, _tgc_kids()) is PanelIdentity.OVERLAY
    assert _blocked(popup, _shape(POPUP_ENTRIES, 100)) is PanelIdentity.MENU_POPUP


def test_a_clean_measurement_screen_has_no_blocking_surface() -> None:
    """The guard on all of it: a strip, its bands and a cursor info box block nothing.

    The states the instrument paints most of the time are exactly this inventory, and a
    ``blocking_surface`` here would refuse a screen the operator is measuring on.
    """
    identities = {
        1: panel_identity(_row_of(1, "TSp_Panel", MENUBAR_PANEL), [], context=MONITOR),
        2: panel_identity(_row_of(2, "TSp_Panel", COLUMN_PANEL), [], context=MONITOR),
        3: panel_identity(
            _row_of(3, "TSp_Panel", STRIP_PANEL_370),
            [
                *_shape(ROW_370, 100),
                *_shape(TOGGLES, 200),
                _row_of(300, "TSp_Sliding_Bar", SLIDER),
            ],
            context=MONITOR,
        ),
        4: panel_identity(
            _row_of(4, "TSp_Panel", INFO_BOX),
            [
                _row_of(100, "TSp_Panel", INFO_BOX_CHILD),
                _row_of(101, "TSp_Button", INFO_BOX_BUTTON),
            ],
            context=MONITOR,
        ),
        5: panel_identity(_row_of(5, "TSp_Panel", STATUS_PANEL), [], context=MONITOR),
    }

    assert identities[1] is PanelIdentity.OTHER
    assert identities[3] is PanelIdentity.MEASUREMENT_STRIP
    assert identities[4] is PanelIdentity.CURSOR_INFO
    assert blocking_surface(identities) is None


# ------------------------------------------------------- the resolver, reading the classification


def screen_rows(
    strip: tuple[int, int, int, int] | None,
    row: tuple[tuple[int, int, int, int], ...] = (),
    *,
    slider: bool = False,
    box: bool = False,
    warning: bool = False,
    popup: bool = False,
    overlay: bool = False,
    second_strip: tuple[int, int, int, int] | None = None,
) -> list[dict]:
    """A whole measurement screen, as ``win32gui`` rows, with measured rects only.

    The menubar band with the measured bar's lefts, the parameter column with its seven value rows,
    the monitor, the status band — and then any of the states this file is about: one strip panel
    with its own row (plus the two caption-less toggles, the slider and the ``Show block`` combo the
    grown reads carry), the cursor info box, the 392x132 guard, the measured ``Parameters`` popup
    and the measured ``Define TGC`` panel. Every rect is a read's own; nothing here is invented, and
    no handle is an identity.
    """
    hwnd = 1000
    rows: list[dict] = []

    def add(cls: str, rect: tuple[int, int, int, int], parent: int, text: str = "") -> dict:
        nonlocal hwnd
        hwnd += 1
        row_of = _row_of(hwnd, cls, rect, text)
        row_of["parent"] = parent
        rows.append(row_of)
        return row_of

    menubar = add("TSp_Panel", MENUBAR_PANEL, WINDOW_HWND)
    for left in (8, 63, 169, 258, 334, 406, 466, 526, 606, 1850):
        add("TSp_Button", (left, 28, left + 50, 53), menubar["hwnd"])
    column = add("TSp_Panel", COLUMN_PANEL, WINDOW_HWND)
    for index in range(len(driver.PARAM_COLUMN_ORDER)):
        top = 150 + 25 * index
        button = add("TSp_Value_Button", (10, top, 150, top + 23), column["hwnd"])
        add("TSp_Edit", (14, top + 4, 54, top + 20), button["hwnd"], text=str(index))
    add("TDop_Plot", PLOT, WINDOW_HWND)
    if strip is not None:
        panel = add("TSp_Panel", strip, WINDOW_HWND)
        for rect in row:
            add("TSp_Button", rect, panel["hwnd"])
        for rect in TOGGLES:
            add("TSp_Button", rect, panel["hwnd"])
        if slider:
            add("TSp_Sliding_Bar", SLIDER, panel["hwnd"])
        # The ``Show block`` combo, owned directly by the panel in every measured strip state —
        # inside the 123 px rects, outside the 40 px one — and the child whose class is what
        # ``_is_dialog_panel`` accepts for a panel wider than 400 px (§2.2).
        add("TComboBox", COMBO, panel["hwnd"], text="2")
    if second_strip is not None:
        # A *second* panel with the strip's own shape: the crop-derived ``Define TGC`` fixture's
        # geometry (453x123, its three buttons in its own top 15 px), which is indistinguishably
        # strip-shaped — the case a measurement screen never paints.
        panel = add("TSp_Panel", second_strip, WINDOW_HWND)
        for index in range(3):
            add(
                "TSp_Button",
                (second_strip[0] + 20 + 90 * index, second_strip[1] + 15,
                 second_strip[0] + 100 + 90 * index, second_strip[1] + 35),
                panel["hwnd"],
            )
    if box:
        panel = add("TSp_Panel", INFO_BOX, WINDOW_HWND)
        add("TSp_Panel", INFO_BOX_CHILD, panel["hwnd"])
        add("TSp_Button", INFO_BOX_BUTTON, panel["hwnd"])
    if warning:
        panel = add("TSp_Panel", WARNING_PANEL, WINDOW_HWND)
        for rect in WARNING_BUTTONS:
            add("TSp_Button", rect, panel["hwnd"])
    if popup:
        panel = add("TSp_Panel", POPUP_PANEL, WINDOW_HWND)
        for rect in POPUP_ENTRIES:
            add("TSp_Button", rect, panel["hwnd"])
    if overlay:
        panel = add("TSp_Panel", TGC_PANEL, WINDOW_HWND)
        for index, rect in enumerate(TGC_BUTTONS):
            add("TSp_Button", rect, panel["hwnd"])
        for index, rect in enumerate(TGC_VALUE_BUTTONS):
            add("TSp_Value_Button", rect, panel["hwnd"])
    status = add("TSp_Panel", STATUS_PANEL, WINDOW_HWND)
    add("TSp_Button", (1840, 1025, 1900, 1045), status["hwnd"])
    return rows


def resolved_screen(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> dict:
    """``Win32Actuator._resolve``'s own answer for one synthesised screen."""
    gui = _MeasuredGui(rows)
    monkeypatch.setattr(driver, "_gui", lambda: (gui, None))
    return driver.Win32Actuator(channel=1)._resolve()


def _panel_with(roles: dict, width: int, height: int | None = None) -> dict:
    """The resolved panel of a given size — the case's own shape, found in the resolver's panels."""
    return next(
        panel
        for panel in roles["panels"]
        if panel["w"] == width and (height is None or panel["h"] == height)
    )


def test_the_resolver_reads_the_classification_and_no_longer_votes_the_strip_out_of_dialogs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The intermediate state, resolved for real: strip, no dialog, no popup, nothing blocking.

    ``value_dialogs``/``browse_dialogs`` are the ``APPLICATION_DIALOG`` panels and nothing else, so
    the strip panel that owns the ``Show block`` combo is not in the union; ``strip_panel`` is the
    panel classified ``MEASUREMENT_STRIP``; ``open_popup`` is a real menu popup and nothing else; and
    the state's own four-button row stays ambiguous, which is the reading ledger B10 requires.
    """
    roles = resolved_screen(monkeypatch, screen_rows(STRIP_PANEL_453, ROW_453))
    strip = _panel_with(roles, 453)

    assert roles["identities"][strip["hwnd"]] is PanelIdentity.MEASUREMENT_STRIP
    assert roles["value_dialogs"] == set()
    assert roles["browse_dialogs"] == set()
    assert roles["strip_panel"]["hwnd"] == strip["hwnd"]
    assert roles["open_popup"] is False
    assert roles["blocking_surface"] is None
    assert roles["state"] == StripView.AMBIGUOUS.value
    assert len(roles["strip_row"]) == 4


def test_the_resolver_does_not_read_the_cursor_info_box_as_the_strip_or_as_a_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured decoy: the box is in the panel set, and neither the strip nor a menu popup.

    Two measured failures are asserted together, because they were the same panel: in the
    intermediate and block-held reads ``strip.panel_id`` was the info box (its own strip report read
    ``unknown`` / 0 buttons), and on the paused 370 px screen the box's caption-less button made
    ``open_popup`` true — a *paused* measurement screen reporting an open menu. With the box
    classified, the strip resolves to the strip and no menu is claimed.
    """
    roles = resolved_screen(
        monkeypatch, screen_rows(STRIP_PANEL_370, ROW_370, slider=True, box=True)
    )
    box = _panel_with(roles, 149)

    assert roles["identities"][box["hwnd"]] is PanelIdentity.CURSOR_INFO
    assert roles["strip_panel"]["w"] == 370
    assert roles["strip_panel"]["hwnd"] != box["hwnd"]
    assert roles["state"] == StripView.STORE.value
    assert roles["open_popup"] is False


def test_the_resolver_names_the_measured_guard_as_the_blocking_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 392x132 guard, resolved for real: ``WARNING``, and the surface reads ``overlay``.

    Measured, the guard is admitted by no dialog predicate at all (``392 <= 400``), so before the
    classification it was named nowhere while the strip behind it was reported as "a dialog is up".
    The screen's first refusal clause names the warning now, and the strip behind it is still the
    strip — the surface is diagnosed rather than the strip being blamed for it.
    """
    roles = resolved_screen(
        monkeypatch, screen_rows(STRIP_PANEL_502, ROW_502, slider=True, warning=True)
    )
    guard = _panel_with(roles, 392, 132)

    assert roles["identities"][guard["hwnd"]] is PanelIdentity.WARNING
    assert roles["blocking_surface"] is PanelIdentity.WARNING
    assert roles["strip_panel"]["w"] == 502
    assert classify_surface(roles) is SurfaceKind.OVERLAY
    reasons = driver.layout_shape_reasons(roles)
    assert reasons and "warning guard" in reasons[0], reasons


def test_only_a_real_menu_popup_sets_open_popup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The measured ``Parameters`` popup, and only it: the flag is the identity, not "some panel".

    ``open_popup`` used to be true for the ``Define TGC`` overlay, for every warning box and for the
    cursor info box (all of them host a button somewhere) and false for the real popup whenever the
    resolver had bound the popup's own panel as the strip. The pause-state screen above asserts the
    false half; this asserts the true half, with the popup's entries inside the measured panel.
    """
    roles = resolved_screen(
        monkeypatch, screen_rows(STRIP_PANEL_370, ROW_370, slider=True, popup=True)
    )
    assert roles["identities"][_panel_with(roles, 232, 195)["hwnd"]] is PanelIdentity.MENU_POPUP
    assert roles["open_popup"] is True
    assert roles["blocking_surface"] is PanelIdentity.MENU_POPUP

    # ...and a warning, an overlay or an info box does **not**, while still being a blocking
    # surface where it is one: narrowing this key must not have erased what a press must not
    # be posted behind.
    for kwargs, expected in (
        ({"warning": True}, PanelIdentity.WARNING),
        ({"overlay": True, "strip": None}, PanelIdentity.OVERLAY),
        ({"box": True}, None),
    ):
        options = {"strip": STRIP_PANEL_370, "row": ROW_370, "slider": True}
        options.update(kwargs)
        other = resolved_screen(monkeypatch, screen_rows(**options))  # type: ignore[arg-type]
        assert other["open_popup"] is False, kwargs
        assert other["blocking_surface"] is expected, kwargs


def test_a_second_panel_with_the_strips_own_shape_is_read_as_an_overlay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ledger B06, on the resolver: two strips' worth of shape where a measurement screen paints one.

    The crop-derived ``Define TGC`` fixture (``docs/dop3000/acquire/ui-crops/overlay-define-tgc-*.png``,
    453x123, caption-less, movable) is *indistinguishably* strip-shaped — its three buttons sit in its
    own top 15 px, inside the plot's middle band — so no per-panel warrant can tell it from the
    recording strip beside it, and the earlier reading is the one B06 records: the resolver bound the
    overlay as the strip and the run then diagnosed its button row. What the classification can say
    without consulting the binding is that the screen carries **two** panels satisfying the strip's
    warrant, which a measurement screen never does; the second is therefore a button panel over the
    monitor, the surface is an overlay, and nothing may be pressed out of a binding the screen cannot
    settle. The measured states each carry exactly one, so no real screen is affected.
    """
    roles = resolved_screen(
        monkeypatch,
        screen_rows(STRIP_PANEL_370, ROW_370, slider=True, second_strip=(600, 353, 1053, 476)),
    )
    second = _panel_with(roles, 453, 123)

    assert roles["identities"][second["hwnd"]] is PanelIdentity.MEASUREMENT_STRIP, (
        "the second panel's own shape is the strip's warrant, and the classification is per panel: "
        "it does not consult which of the two the resolver bound"
    )
    assert roles["blocking_surface"] is PanelIdentity.OVERLAY
    assert classify_surface(roles) is SurfaceKind.OVERLAY
    reasons = driver.layout_shape_reasons(roles)
    assert reasons and "overlay" in reasons[0].lower(), reasons
    assert "STRIP_BUTTON_ORDER" not in reasons[0], reasons


def test_the_resolver_reports_the_define_tgc_overlay_and_the_missing_strip_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V3's ordering, resolved for real: the overlay is the diagnosis and the strip its consequence.

    The measured read has the real strip panel **absent** from the visible panel set, so no strip
    resolves — and the surface must still be named first. That is the difference between this and
    the measured failure, which read "a dialog is up" for the overlay and then "no recording strip
    panel resolved": a refusal that is right, for the wrong reason.
    """
    roles = resolved_screen(monkeypatch, screen_rows(None, overlay=True))

    assert roles["identities"][_panel_with(roles, 450, 120)["hwnd"]] is PanelIdentity.OVERLAY
    assert roles["blocking_surface"] is PanelIdentity.OVERLAY
    assert roles["value_dialogs"] == set()
    assert roles["strip_panel"] is None
    assert roles["open_popup"] is False
    assert classify_surface(roles) is SurfaceKind.OVERLAY
    reasons = driver.layout_shape_reasons(roles)
    assert reasons and "overlay" in reasons[0], reasons
    assert "no recording strip panel resolved" in reasons[1], reasons
