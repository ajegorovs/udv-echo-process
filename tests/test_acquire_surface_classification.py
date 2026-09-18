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

from test_acquire_layout_gate import ORIGIN, _button, _panel, manual_screen

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import ChannelMode, classify_strip_view

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
