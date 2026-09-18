"""What is on the screen, before what is on it is resolved — B06 and B08.

Two live-discovered facts about **surface classification**, and both of them are ordering claims:

- **B06** — an overlay such as the ``Define TGC`` panel can be picked as the strip candidate, so
  the run refuses for the *wrong reason* (an unknown/0-button strip row) instead of naming the
  active non-measurement surface. Worse, the panel's own buttons classify as a ``ready`` row, so
  the gate can accept it: the classifier calls every 3–4 button no-slider row ``READY`` and
  ``STRIP_BUTTON_ORDER[(READY, 3)]`` then names those positions ``Pause / Record / Clear and
  restart``. Classification must come before strip/column resolution, and any non-measurement
  surface must return a surface-state refusal first.
- **B08** — ``Compare profiles`` and ``Measure US field`` are whole-screen **replacement**
  surfaces, not overlays, and neither is a measurement screen. They must not be classified as
  one, and a channel mode must never be read out of their missing parameter column.

The third case is the same finding one surface further in, and it is the one this file's own
`Operating parameters` fixture supplies: the panel measured on the instrument 2026-09-18
(``tests/data/udop-parameters-dialog-tree.json``) is a dialog **structurally** — a 627x384
``TSp_Panel`` of the window with 21 direct children and fifteen ``TSp_Value_Button`` fields of its
own — while the resolver's own dialog rule asked for a direct edit *and* a ``TSp_Browse``, which
this panel carries neither of. It therefore took part in the strip vote, its five bottom buttons
outvoted the recording strip's three, and the panel that is a dialog was bound as the strip.

The fixtures are the measured manual screen (``test_acquire_layout_gate.manual_screen``) plus one
panel each, taken from the committed crops: ``UI-OVERLAY-01..04``
(``docs/dop3000/ui-crops/overlay-define-tgc-uniform.png`` and its ``-auto`` / ``-slope`` /
``-custom`` siblings, 453x123, caption-less, movable — the overlay B06 was found with) and
``UI-OVERLAY-19`` / ``UI-OVERLAY-21`` / ``UI-OVERLAY-22``
(``overlay-measure-us-field-blocking.png``, ``overlay-compare-profiles-new-comparison.png``,
``overlay-full-screen-compare-profiles-add-second-curve.png`` — the replacement surfaces, with
``UI-OVERLAY-22`` the frame in which the column, the menu band, the strip and the status bar are
all gone). Nothing here is a live read: the panels are placed where the crops put them and the
*resolution* the trees carry is the one the driver's own rules produce for them, which is stated
at each fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

from test_acquire_layout_gate import (
    ORIGIN,
    _button,
    _panel,
    _widget,
    manual_screen,
)

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import ChannelMode, classify_strip_view
from udv_echo_process.acquire.ui.layout import classify_surface
from udv_echo_process.acquire.ui.model import SurfaceKind

#: The overlay panel's handle, above the measured screen's own (1–5) so nothing collides.
OVERLAY_HWND = 77
#: Where the crop sits in the client: the plot band of the measured screen is the client's
#: y 84–1025, and 0.30–0.70 of it is where the strip votes from, so the overlay is placed inside.
OVERLAY_TOP = ORIGIN[1] + 330


def define_tgc_overlay(top: int = OVERLAY_TOP) -> tuple[dict, list[dict]]:
    """The ``Define TGC`` panel and its buttons, at the size ``UI-OVERLAY-01`` measures.

    453x123 and caption-less, with its own mode combo, value boxes and buttons — none of which
    this case needs: what matters is that it is a ``TSp_Panel`` of the window, inside the plot
    band, hosting ``TSp_Button`` children and no slider.
    """
    panel = _panel(OVERLAY_HWND, top, left=600, w=453, h=123)
    kids = [_button(OVERLAY_HWND + 1 + index, 620 + 90 * index, top + 15) for index in range(3)]
    return panel, kids


def screen_with_overlay(*, bound_row: bool = True) -> dict:
    """The measured manual screen with the overlay open over it, resolved as the driver resolves it.

    The resolution is not invented: :meth:`Win32Actuator._resolve` scores a panel for the strip by
    the position of its buttons inside the plot (the 0.30–0.70 band) and takes the one **hosting
    the most of them**, so a button panel sitting in the band's middle wins the vote — which is
    exactly the live incident, where the resolver bound the overlay and the run then diagnosed
    its (empty) button row. ``bound_row=False`` is the same tree as the live run saw it: the
    overlay bound, and no buttons read in its row.
    """
    roles = manual_screen()
    overlay, kids = define_tgc_overlay()
    roles["panels"] = sorted([*roles["panels"], overlay], key=lambda panel: panel["top"])
    roles["raw"] = [*roles["raw"], overlay, *kids]
    roles["parent_of"] = {
        **roles["parent_of"],
        overlay["hwnd"]: 0,
        **{kid["hwnd"]: overlay["hwnd"] for kid in kids},
    }
    roles["strip_panel"] = overlay
    roles["strip_row"] = kids if bound_row else []
    roles["state"] = classify_strip_view(len(roles["strip_row"]), False).value
    return roles


# B06: UI-OVERLAY-01..04 (ui-crops/overlay-define-tgc-uniform.png) as the candidate.
def test_an_overlay_in_the_plot_band_is_never_accepted_as_the_strip() -> None:
    """B06, the dangerous half: an overlay's buttons can be read as the strip's own row.

    With the ``Define TGC`` panel up, the resolver's own vote hands the overlay over as
    ``strip_panel``; its three painted buttons then classify as ``StripView.READY``, which
    ``STRIP_BUTTON_ORDER`` documents as ``Pause / Record / Clear and restart``. Nothing in the
    gate notices, so a run could bind a press to a control of a TGC panel. A non-measurement
    surface has to be a clause of its own — and the first one, before any strip-row or column
    diagnosis, because the row it would diagnose is a symptom of the surface being wrong.
    """
    roles = screen_with_overlay()

    reasons = driver.layout_shape_reasons(roles)

    assert reasons, "the gate accepted a screen whose strip resolved to an active overlay panel"
    assert "STRIP_BUTTON_ORDER" not in reasons[0], reasons[0]
    assert any("surface" in clause or "overlay" in clause for clause in reasons), reasons


# B06: the live symptom — a 0-button strip diagnosis where an overlay is the finding.
def test_the_active_surface_is_named_before_the_strip_row_is_diagnosed() -> None:
    """B06, the live symptom: a refusal that is right for the wrong reason.

    The run did refuse — so a test that only asked "did it stop?" would pass — but the operator
    was told the strip's row holds 0 buttons, when the finding is a ``Define TGC`` overlay on the
    screen and no strip resolution at all. A wrong diagnosis costs a live slot: it sends the
    operator to look for a strip they will not find.
    """
    roles = screen_with_overlay(bound_row=False)

    reasons = driver.layout_shape_reasons(roles)

    assert reasons, "a screen with an overlay up and no strip row was accepted"
    assert any("surface" in clause or "overlay" in clause for clause in reasons), reasons
    assert "STRIP_BUTTON_ORDER" not in reasons[0], reasons[0]
    assert driver.layout_refusal(roles) is not None


# B06 (guard): the measured manual screen with no overlay on it.
def test_the_same_screen_without_the_overlay_is_still_accepted() -> None:
    """The guard on both cases above: the fix must not refuse every screen."""
    assert driver.layout_refusal(manual_screen()) is None
    assert driver.screen_mode(manual_screen()) is ChannelMode.MANUAL


# ------------------------------------------------------ B08: the replacement surfaces


def replacement_surface() -> dict:
    """``Compare profiles`` / ``Measure US field`` as a resolved tree — content replaced.

    ``UI-OVERLAY-22`` is the frame that shows it: the parameter column, the menu band, the strip
    and the status bar are gone and the title bar alone survives, so what is left of the window
    is the surface's own widget band — ``UI-OVERLAY-22``'s band reads ``Get a comparison``,
    ``Save this comparison``, ``New comparison``, ``New IQ comparison``, ``Add Curve``,
    ``Exit``. The six buttons are modelled, because that band is what the resolver will bind: with
    no ``TDop_Plot`` on the screen ``_resolve``'s band rule has no band to score and the panel
    hosting the most buttons becomes the strip candidate, and with no column anywhere
    :func:`driver.screen_mode` reads the absence as an assisted channel.
    """
    band = _panel(90, ORIGIN[1], w=1000, h=60)
    buttons = [_button(91 + index, 10 + 140 * index, ORIGIN[1] + 10) for index in range(6)]
    raw = [band, *buttons]
    return {
        "window": 0,
        "class_name": driver.MAIN_CLASS,
        "client": (1920, 1027),
        "origin": ORIGIN,
        "raw": raw,
        "panels": [band],
        "parent_of": {widget["hwnd"]: 0 for widget in raw},
        "menu": {},
        "menu_band": None,
        "plot": None,
        "open_popup": False,
        "value_dialogs": set(),
        "browse_dialogs": set(),
        "strip_panel": band,
        "strip_row": buttons,
        "state": classify_strip_view(len(buttons), False).value,
        "left_panel": None,
        "param_rows": [],
        "params": {},
    }


# B08: UI-OVERLAY-19 / UI-OVERLAY-21 / UI-OVERLAY-22 (the replacement surfaces).
def test_a_replacement_surface_is_not_classified_as_a_measurement_screen() -> None:
    """B08: a replaced screen is a *surface*, and never a channel mode.

    Two wrong answers are available today and both are asserted here. ``screen_mode`` answers
    ``ASSISTED`` — from the missing column alone, which the same frame shows is a property of the
    surface rather than of the channel; and the shape check refuses for the wrong reasons (no
    menubar band, no plot band, no status band), none of which says *this is not the measurement
    screen*. A run that took the first for a mode would go looking for an assisted channel; one
    that only read the second would look for a layout drift.
    """
    roles = replacement_surface()

    assert driver.screen_mode(roles) is not ChannelMode.ASSISTED
    assert driver.screen_mode(roles) is None
    reasons = driver.layout_shape_reasons(roles)
    assert reasons, "a replacement surface was accepted as a measurement screen"
    assert any("surface" in clause or "measurement screen" in clause for clause in reasons), reasons


# ------------------------------------ the measured dialog, classified before any strip binding
#
# The fixture is the measured ``Operating parameters`` panel (2026-09-18) over the measured manual
# screen, and the resolution is the driver's **own**: ``Win32Actuator._resolve`` is run for real, on
# a ``win32gui`` stand-in built from those rows, so the vote the run would take is the vote taken
# here. What the panel's shape says is that it is a dialog — 627 px wide, 21 direct children,
# fifteen ``TSp_Value_Button`` fields of its own, its five bottom buttons in the plot's scored
# 0.30-0.70 band — and it carries **neither** a direct ``TEdit``/``TSp_Edit`` **nor** a
# ``TSp_Browse``, which is exactly the pair the resolver's private dialog rule asked for.

#: The fixture's own dialog handle, and the handles this case gives the screen it sits on. The
#: fixture carries no handle on purpose (handles are volatile — control ids change on every
#: launch), so the dialog keeps its own; the manual screen keeps ``manual_screen``'s 1–5 for its
#: panels, and the window itself is 700 so that no panel handle is the window's.
DIALOG_HWND = 8585312
STRIP_HWND = 3
WINDOW_HWND = 700
FIXTURE = Path(__file__).parent / "data" / "udop-parameters-dialog-tree.json"


def _row(
    hwnd: int, cls: str, parent: int, rect: tuple[int, int, int, int], text: str = ""
) -> dict:
    """One control of the stand-in's tree, in the shape ``_visible_children`` produces."""
    left, top, right, bottom = rect
    return {
        "hwnd": hwnd,
        "cls": cls,
        "parent": parent,
        "text": text,
        "visible": True,
        "rect": (left, top, right, bottom),
        "left": left,
        "top": top,
        "w": right - left,
        "h": bottom - top,
    }


def measured_dialog_rows() -> list[dict]:
    """The measured dialog's panel and its 21 **direct** children, at the fixture's own rects.

    Only the rows the dialog owns are the fixture's: its rect, its class, and the rows the
    enumeration reported as its direct children (``depth == 0`` — fifteen value buttons, five
    bottom buttons and the header combo), with the text the one combo states. Nothing here is
    invented, because it is the shape that decides both questions at once: whether the panel is a
    dialog, and whether its button row falls in the band the strip vote scores in.
    """
    tree = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dialog = tree["dialog"]
    left, top, right, bottom = dialog["rect"]
    rows = [
        _row(dialog["hwnd"], dialog["cls"], WINDOW_HWND, (left, top, right, bottom))
    ]
    rows += [
        _row(
            900000 + index,
            control["cls"],
            dialog["hwnd"],
            tuple(control["rect"]),
            control["text"],
        )
        for index, control in enumerate(
            control for control in tree["controls"] if control["depth"] == 0
        )
    ]
    return rows


def measured_dialog_screen_rows() -> list[dict]:
    """That dialog over ``manual_screen``'s own measured panels, every row stating its parent.

    The screen around the dialog is the measured manual screen — the menubar band, the parameter
    column and its seven rows, the recording strip with its **three** buttons, the plot and the
    status bar, at the places ``manual_screen`` puts them — so the only thing this case adds is the
    dialog there. Parents matter here and ``manual_screen`` does not state them: ``_resolve`` reads
    a panel's **own** children, and a tree whose widgets all hang off the window would leave every
    panel looking empty.
    """
    oy = ORIGIN[1]
    menu_band = _panel(1, oy, h=25)
    column = _panel(2, oy + 60, left=0, w=190, h=945)
    strip = _panel(3, oy + 454, left=448, w=352, h=40)
    status = _panel(4, oy + 1003, h=24)
    plot = _widget(5, "TDop_Plot", 200, oy + 42, 1710, 941)
    rows: list[dict] = [
        {**panel, "parent": WINDOW_HWND}
        for panel in (menu_band, column, strip, status, plot)
    ]
    for index in range(len(driver.PARAM_COLUMN_ORDER)):
        top = oy + 100 + 25 * index
        button = _row(
            100 + 2 * index,
            "TSp_Value_Button",
            column["hwnd"],
            (10, top, 140, top + 24),
        )
        edit = _row(
            100 + 2 * index + 1, "TSp_Edit", button["hwnd"], (14, top + 4, 54, top + 20)
        )
        rows += [button, edit]  # the field's edit lives *inside* its value button
    rows += [
        {**_button(60 + index, 455 + 90 * index, oy + 465), "parent": strip["hwnd"]}
        for index in range(3)
    ]
    return rows + measured_dialog_rows()


class _MeasuredGui:
    """``win32gui`` as one resolve asks it, over one flat table of the screen's controls."""

    def __init__(
        self, rows: list[dict], *, client: tuple[int, int] = (1920, 1027)
    ) -> None:
        self.client = client
        self.origin = ORIGIN
        self.rows = {row["hwnd"]: row for row in rows}

    def EnumWindows(self, callback, _lparam) -> int:
        callback(WINDOW_HWND, None)
        return 1

    def EnumChildWindows(self, _win: int, callback, _lparam) -> int:
        for hwnd in list(self.rows):
            callback(hwnd, None)
        return 1

    def IsWindowVisible(self, hwnd: int) -> bool:
        return hwnd == WINDOW_HWND or bool(self.rows[hwnd].get("visible", True))

    def GetWindowRect(self, hwnd: int) -> tuple[int, int, int, int]:
        if hwnd == WINDOW_HWND:
            return (
                self.origin[0],
                self.origin[1],
                self.origin[0] + self.client[0],
                self.origin[1] + self.client[1],
            )
        return self.rows[hwnd]["rect"]

    def GetClassName(self, hwnd: int) -> str:
        return driver.MAIN_CLASS if hwnd == WINDOW_HWND else str(self.rows[hwnd]["cls"])

    def GetWindowText(self, hwnd: int) -> str:
        return str(self.rows[hwnd]["text"])

    def GetDlgCtrlID(self, hwnd: int) -> int:
        return hwnd

    def GetParent(self, hwnd: int) -> int:
        return int(self.rows[hwnd]["parent"])

    def GetClientRect(self, _hwnd: int) -> tuple[int, int, int, int]:
        return (0, 0, self.client[0], self.client[1])

    def ClientToScreen(self, _hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
        return (self.origin[0] + point[0], self.origin[1] + point[1])


def resolved_dialog_screen(monkeypatch, rows: list[dict] | None = None) -> dict:
    """``Win32Actuator._resolve``'s own answer for the measured dialog on the manual screen."""
    gui = _MeasuredGui(measured_dialog_screen_rows() if rows is None else rows)
    monkeypatch.setattr(driver, "_gui", lambda: (gui, None))
    return driver.Win32Actuator(channel=1)._resolve()


# The measured shape: 15 TSp_Value_Button + 5 TSp_Button + 1 TComboBox directly under the panel.
def test_the_measured_parameters_dialog_enters_the_resolvers_dialog_union(
    monkeypatch,
) -> None:
    """The dialog union has to be the *structural* one — the predicate ``_dialog_panels`` uses.

    The measured panel is a dialog by the canonical rule and by no other evidence: wider than
    400 px, full of controls, and holding input widgets of its own. It carries no direct edit and
    no ``TSp_Browse``, so a second, narrower rule of the resolver's own leaves the panel outside
    ``value_dialogs``/``browse_dialogs`` — and everything downstream of that union (the dialog
    observation, the surface classification, the overlay check) then reads this screen as a screen
    with no dialog on it at all.
    """
    roles = resolved_dialog_screen(monkeypatch)

    union = set(roles["value_dialogs"]) | set(roles["browse_dialogs"])
    assert DIALOG_HWND in union, (
        "the measured Operating parameters panel is no dialog of this resolve: its 21 direct "
        "children carry no TEdit/TSp_Edit and no TSp_Browse, so the resolver's own rule excluded "
        "the one panel on this screen that is a dialog"
    )
    assert DIALOG_HWND in roles["value_dialogs"], (
        "a dialog that holds TSp_Value_Button fields of its own is the *values* dialog; only the "
        "browse/store class is browse_dialogs"
    )


# The consequence: the dialog's five buttons outvote the strip's three unless it is a dialog first.
def test_the_measured_parameters_dialog_is_never_the_strip_panel(monkeypatch) -> None:
    """The strip vote must not see a dialog: five dialog buttons beat the strip's three.

    The panel's bottom button row sits at 0.68 of the plot's height, inside the 0.30-0.70 band the
    vote scores in, so five buttons win it against the recording strip's three — the run then holds
    the dialog as ``strip_panel`` and the real strip is reported as an open menu popup instead. A
    dialog is decided **before** the vote, not by whether it wins it.
    """
    roles = resolved_dialog_screen(monkeypatch)

    assert roles["strip_panel"] is not None, (
        "the screen's own three-button strip did not resolve"
    )
    assert roles["strip_panel"]["hwnd"] == STRIP_HWND, (
        "the resolver bound the parameters dialog as the strip: its five bottom buttons outvote "
        "the recording strip's three, and a press would then come out of a dialog's button band"
    )
    assert roles["open_popup"] is False, (
        "with the dialog in the vote and excluded from `open_popup`, the screen's own strip was "
        "read as an open menu popup"
    )


# The surface the whole file is about: a dialog is a DIALOG, not an overlay and not a popup.
def test_the_measured_parameters_dialog_classifies_as_a_dialog_surface(
    monkeypatch,
) -> None:
    """``classify_surface`` answers ``DIALOG`` — the surface is decided before anything is pressed.

    The classifier's own order puts a resolved dialog panel first among the surfaces, so this one
    assertion covers the whole chain: the union, the observation built from it, and the verdict a
    diagnosis would start from. While the panel is no dialog, that verdict is *another* surface —
    a refusal that names an overlay or a popup on a screen whose only non-measurement surface is
    the ``Operating parameters`` dialog.
    """
    roles = resolved_dialog_screen(monkeypatch)

    assert classify_surface(roles) is SurfaceKind.DIALOG


# The guard: the browse/store class keeps landing in `browse_dialogs`, where it has always been.
def test_a_store_class_dialog_still_lands_in_browse_dialogs(monkeypatch) -> None:
    """The wider predicate must not move the browse/store dialog into the values half.

    ``_find_overlay`` and everything that answers a Store dialog read ``value_dialogs`` as "the
    values dialog is up, nothing to answer" and look for the store class by its own ``TSp_Browse``
    + edits: a store dialog filed as a values dialog would stop being found. The split is on the
    value buttons, which is what the panel's own children say it is.
    """
    rows = [
        row for row in measured_dialog_screen_rows() if row["parent"] != DIALOG_HWND
    ] + [
        _row(DIALOG_HWND + 1, "TEdit", DIALOG_HWND, (700, 400, 900, 420)),
        _row(DIALOG_HWND + 2, "TSp_Browse", DIALOG_HWND, (900, 400, 980, 420)),
    ]

    roles = resolved_dialog_screen(monkeypatch, rows)

    assert DIALOG_HWND in roles["browse_dialogs"]
    assert DIALOG_HWND not in roles["value_dialogs"]
