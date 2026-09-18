"""The UI counterexamples the live sessions found, pinned at **today's** entry points.

Every case here is a live-discovered fact that today's code gets wrong or could get wrong, and
each one is written as the behaviour contract rather than as a test of the code that currently
produces it: the entry points are the names the refactor keeps re-exporting
(``driver.screen_mode``, ``driver.layout_shape_reasons``, ``driver.layout_refusal``,
``Win32Actuator.read_parameter`` / ``read_dialog_parameters`` / ``instrument_snapshot``,
``driver.dialog_value_fields``), so a module moving underneath them does not move them.

Where today's behaviour is already the safe one the test is a plain passing test, and it is the
pin the refactor must not break while it moves code. Where today's behaviour is the unsafe
reading — inventing a channel mode from absence, binding a menubar by index — the test carries
``xfail(strict=True)`` with the blind-spot id in its reason, so landing the fix turns it into an
XPASS and the suite goes red until the marker is removed *with* the fix. Never a silent skip.

The blind-spot ids are the committed ledger's (``docs/dop3000/acquisition-ui-model.md`` §6,
B01…B20) and the verification items that settle them are ``docs/dop3000/device-verification.md``
(V1 for B01, V4 for B10 — both device-pending, which is why the fix they wait for is a refusal
rather than a role map). Every case below names the committed evidence it rests on, one line:

- **B01** — the sidebar can be hidden by the application's own ``Preferences`` option
  *Show fast access parameters panel (not available in assisted mode)*, live-measured
  2026-09-17/18 (``docs/dop3000/ui-crops/menu-preferences-assisted-off.png`` /
  ``menu-preferences-assisted-on.png``, UI-OVERLAY-06), so the absent parameter column is **not**
  evidence of an assisted channel. The two shapes below are the same tree, panel for panel.
- **B02** — TGC ``Uniform``/``Auto`` adds and removes the ``Tgc [dB]`` parameter-column row
  (``UI-WINDOW-01``, ``app-whole.png``, paints it), moving the visible-control total 44 → 42 in
  **one** mode: a count is a reading, never a layout identity.
- **B03** — the menubar's painted buttons differ between app variants and carry no tree text
  (``UI-WINDOW-01`` and ``menu-bar-no-udv.png``): ``Parameters`` happens to sit at index 2 in the
  measured variants, which is accidental safety, not a binding rule.
- **B09** — the committed ``Operating parameters`` dialog of 2026-09-18
  (``tests/data/udop-parameters-dialog-tree.json``, read by ``tools/live/probes/w1_fixed_facts.py``):
  five unpainted ``TSp_Edit`` children state ``89`` beside combos whose painted values are
  ``4`` / ``Medium`` / ``medium``.
- **B17** — the dialog states the channel its parameters belong to (``docs/16`` §12): the
  dialog-only facts may only be attached once that channel equals the one the run routed.
"""

from __future__ import annotations

import pytest
from test_acquire_dialog import FakeDialogDriver, measured_controls, read_text_for
from test_acquire_layout_gate import (
    ORIGIN,
    StubScreen,
    _widget,
    assisted_screen,
    manual_screen,
)

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import ChannelMode, ParamRole

# ---------------------------------------------------------------- B01: the hidden sidebar


def hidden_sidebar_screen() -> dict:
    """The measured **manual** screen with its fast-access column hidden by ``Preferences``.

    B01's mechanism: the option *Show fast access parameters panel* takes the sidebar away while
    the channel stays manual, so this tree and
    :func:`test_acquire_layout_gate.assisted_screen` are the **same shape** — which is exactly
    why the absence of the column cannot decide the mode. Built from the measured manual screen
    by hiding the column panel and its seven rows (never by inventing a screen), so the tree
    keeps the measured menubar band, strip, plot and status bar at their measured places.
    """
    roles = manual_screen()
    hidden = {roles["left_panel"]["hwnd"]}
    for row in roles["param_rows"]:
        hidden |= {row["button"]["hwnd"], row["edit"]["hwnd"]}
    roles["panels"] = [panel for panel in roles["panels"] if panel["hwnd"] not in hidden]
    roles["raw"] = [widget for widget in roles["raw"] if widget["hwnd"] not in hidden]
    roles["parent_of"] = {
        hwnd: parent for hwnd, parent in roles["parent_of"].items() if hwnd not in hidden
    }
    roles["left_panel"] = None
    roles["param_rows"] = []
    roles["params"] = {}
    return roles


# B01: the measured manual screen (test_acquire_layout_gate.manual_screen) against the assisted shape.
def test_the_hidden_sidebar_screen_is_the_assisted_shape_panel_for_panel() -> None:
    """A guard on the fixture: the two readings differ in nothing a tree can see.

    If this ever stops holding the two cases below stop meaning what they say, so the guard is
    asserted rather than assumed.
    """
    hidden = hidden_sidebar_screen()
    assisted = assisted_screen()
    assert [panel["hwnd"] for panel in hidden["panels"]] == [
        panel["hwnd"] for panel in assisted["panels"]
    ]
    assert len(hidden["panels"]) == 3
    assert hidden["params"] == {} and hidden["left_panel"] is None
    assert hidden["plot"] is not None and hidden["strip_panel"] is not None


# B01: UI-OVERLAY-06, ui-crops/menu-preferences-assisted-on.png (the option that hides the panel).
def test_a_manual_screen_whose_sidebar_is_hidden_is_never_read_as_assisted() -> None:
    """B01: *no sidebar* means *no sidebar*, never *assisted channel*.

    The sidebar may be hidden by a ``Preferences`` option with the channel manual, so a run that
    promoted the absence to an observed assisted state would refuse a channel it can perfectly
    well sweep — and would say so with a diagnosis pointing at the channel's mode rather than at
    the screen's configuration. The absence is a state this reading cannot resolve: ``None`` is
    the signature's refusal (the same value it answers for a dialog or an unrecognised layout),
    and the run's own precondition check is where the missing panel becomes a named refusal.
    """
    roles = hidden_sidebar_screen()

    assert driver.screen_mode(roles) is not ChannelMode.ASSISTED
    assert driver.screen_mode(roles) is None


# B01: the recommendation names the Preferences option (UI-OVERLAY-06), not the mode.
def test_the_missing_panel_refusal_does_not_assert_assisted_mode_as_a_fact() -> None:
    """B01: the diagnosis an operator reads must carry **both** readings of the absent panel.

    A manual sweep needs the fast-access panel, so asking for a parameter on a screen without it
    is a refusal — that part is right today and is asserted first. What is not right is the
    explanation: it states the assisted panel as *what the application does for this channel*,
    when the same screen is what a manual channel with the panel switched off in ``Preferences``
    paints. The operator is sent to the channel's mode instead of to the option that hides it.
    """
    screen = StubScreen(hidden_sidebar_screen())

    with pytest.raises(driver.AcquisitionError) as excinfo:
        screen.read_parameter(ParamRole.PRF)

    message = str(excinfo.value)
    assert ParamRole.PRF.value in message
    assert "Preferences" in message, message
    assert screen.presses == [], "a read must not press anything"


# B01 (positive half): the measured manual screen, sidebar present.
def test_the_manual_screen_with_its_sidebar_is_still_manual() -> None:
    """The positive half of B01: with the column resolved the classification still stands."""
    assert driver.screen_mode(manual_screen()) is ChannelMode.MANUAL


# --------------------------------------------- B02: the TGC row is a count, not an identity


# B02: the `Tgc [dB]` row (UI-WINDOW-01, app-whole.png) — 44 vs 42, one mode.
def test_the_tgc_rows_presence_moves_the_count_and_nothing_a_run_is_gated_on() -> None:
    """B02: the same real-process mode reads 44 with the ``Tgc [dB]`` row and 42 without it.

    The totals are evidence a reader compares across sessions — so both must be *visible* — and
    neither is a cleanliness or compatibility fact: a gate keyed on the count would refuse a
    screen for carrying a row the operator's own TGC mode put there.
    """
    with_row = manual_screen(controls=44)
    without_row = manual_screen(controls=42)

    for roles in (with_row, without_row):
        assert driver.layout_refusal(roles) is None, roles["raw"]
    # The counts are what differ, and each one is readable in the evidence line.
    assert "44 visible controls" in driver.layout_evidence(with_row)
    assert "42 visible controls" in driver.layout_evidence(without_row)
    # ...while the identity a resume compares does not carry the count at all (D6), which is
    # asserted at the model in tests/test_acquire_snapshot.py: here it is the tree half — the
    # shape a run is gated on is identical for the two readings.
    assert driver.layout_shape_reasons(with_row) == driver.layout_shape_reasons(without_row) == ()


# --------------------------------------------- B03: the menubar is an index, not an identity


def menubar_of(count: int) -> dict[str, dict]:
    """The menubar map the resolver would hand over for a variant painting ``count`` buttons.

    ``_resolve`` binds the apparent menubar buttons to the names in :data:`driver.MENU_ORDER`
    **by position**, so this is that map for a variant whose bar is not the measured one — the
    case B03 names: an index is not a semantic identity, and the name it produces may belong to
    another control.
    """
    buttons = [
        _widget(200 + index, "TSp_Button", 60 + 140 * index, ORIGIN[1] + 2, 120, 20)
        for index in range(count)
    ]
    return dict(zip(driver.MENU_ORDER, buttons, strict=False))


# B03: UI-WINDOW-01 / menu-bar-no-udv.png — the variants' menubars differ.
@pytest.mark.xfail(
    strict=True,
    reason="B03: a variant's menubar is still bound to MENU_ORDER by index, so a bar that is "
    "not the measured one is accepted as proof of the Parameters anchor — PATCH-2 resolves a "
    "verified anchor and refuses an unprovable one",
)
def test_a_menubar_that_is_not_the_measured_one_does_not_prove_the_parameters_anchor() -> None:
    """B03: the anchor has to be *verified*, and a painted-set difference is what breaks it.

    The variants this application ships do not paint the same menubar (``UI-WINDOW-01`` shows
    ten entries and ``menu-bar-no-udv.png`` a different bar again), and the entries carry no tree
    text, so a generic ``MENU_ORDER[i]`` silently renames every later role when a button is
    absent. The screen whose menubar is not the measured one therefore cannot state that the
    third button is ``Parameters`` — and a run that hovers it moves the operator's real cursor
    onto whatever control is there. It must be a clause of the shape check, before any hover.
    """
    roles = manual_screen()
    roles["menu"] = menubar_of(6)  # a variant: six entries where the measured bar has eleven

    reasons = driver.layout_shape_reasons(roles)

    assert reasons, "a menubar that is not the measured one was accepted as proof of the anchor"
    assert any("menubar" in clause for clause in reasons), reasons


# B03: the anchor check on the gesture's own path (driver.PARAMETERS_MENU).
def test_an_anchor_that_did_not_resolve_refuses_before_the_menubar_is_hovered() -> None:
    """B03: the gesture is reached *through* the anchor, and never by trying it.

    The hover is a real-cursor gesture on the operator's desktop, so an anchor that cannot be
    resolved must refuse before it happens. ``read_dialog_parameters`` is the run's own path
    there, and its ``_hover_centre`` fails this test if it is ever reached.
    """

    class NoHoverScreen(StubScreen):
        """A driver whose menubar hover is a test failure — the ordering half of the contract."""

        def _hover_centre(self, hwnd: int) -> tuple[int, int]:
            raise AssertionError(
                "the menubar was hovered, so the anchor refusal did not come first"
            )

    roles = manual_screen()
    roles["menu"] = {}
    screen = NoHoverScreen(roles)

    # The pure gate names it too, so the refusal is diagnosable from the tree alone...
    assert any("menubar" in clause for clause in driver.layout_shape_reasons(roles))
    # ...and the gesture ends before the cursor moves.
    reading = screen.read_dialog_parameters()

    assert not reading.readable()
    assert "no 'Parameters' button in the menubar" in reading.reason
    assert screen.warnings and "could not be opened" in screen.warnings[0], screen.warnings


# --------------------------------------------- B09: the combo states the value, the edit does not


# B09: tests/data/udop-parameters-dialog-tree.json (the 2026-09-18 dialog read).
def test_a_row_that_offers_a_choice_is_read_from_the_choice_and_never_from_the_edit() -> None:
    """B09: the measured dialog's stale child edits are evidence, never a fallback value.

    The fixture is the dialog as it stood on the running application: five ``TSp_Edit`` children
    state ``89`` (the sampling volume at 1460 m/s) while the combos of the same rows state the
    real parameters — burst ``4``, sensitivity ``Medium``/``medium``. A reader that fell back to
    the inner edit would hand a pre-run check a *different physical quantity* under the
    parameter's name, and nothing in the reading would say so. So: every row that offers a choice
    is read from the choice, the painted case is the value (never normalised here), and no field
    of this dialog is sourced from the stale buffer.
    """
    rows = measured_controls()
    stale = [row for row in rows if row["cls"] == "TSp_Edit" and row["text"] == "89"]
    assert stale, "the measured dialog no longer carries the stale child edits this case rests on"

    fields = driver.dialog_value_fields(rows, read_text_for(rows))
    buttons = [row for row in rows if row["cls"] == "TSp_Value_Button"]
    by_hwnd = {row["hwnd"]: row for row in rows}
    for field in fields:
        control = by_hwnd[field["hwnd"]]
        host = [button for button in buttons if driver._contains(button, control)]
        assert host, f"the field {field['cls']} at ({field['column']}, {field['row']}) has no row"
        offered = [
            row
            for row in rows
            if row["cls"] in ("TSp_Edit", "TComboBox") and driver._contains(host[0], row)
        ]
        if any(row["cls"] == "TComboBox" for row in offered):
            assert field["cls"] == "TComboBox", (
                field,
                "a row that offers a choice was read from the edit beside it",
            )
        assert field["value"] != "89", (field, "a field took the stale child edit's value")

    # The two rows the measurement names, checked by position and by the case they paint.
    by_position = {(field["column"], field["row"]): field for field in fields}
    burst, sensitivity = by_position[(0, 1)], by_position[(0, 2)]
    assert (burst["cls"], burst["value"]) == ("TComboBox", "4")
    assert (sensitivity["cls"], sensitivity["value"]) == ("TComboBox", "Medium")
    assert any(field["value"] == "medium" for field in fields)


# --------------------------------------------- B17: the dialog's channel, against the routed one


# B17: docs/16 §12 — the dialog's channel against the channel the run routed.
def test_a_dialog_for_another_channel_refuses_before_any_fact_is_attached() -> None:
    """B17: the dialog's channels must meet the run's before any dialog fact is believed.

    Today's behaviour is already the safe one — this is the pin the refactor keeps. The
    ``Operating parameters`` dialog states whose parameters it shows, and the recording lands on
    the channel the run routed, so a channel-2 burst, sound speed and first gate attached to a
    channel-1 reading is invisible downstream: every value is a plausible number. The refusal
    happens in ``instrument_snapshot`` before the screen is read at all (``screen_reads`` stays
    zero), and the channel comparison is on the text the dialog states rather than on a parse of
    it: whitespace is not another channel, and a different number is.
    """
    other = FakeDialogDriver(channel="2")
    reading = other.read_dialog_parameters()
    assert reading.channel == "2"

    with pytest.raises(driver.AcquisitionError) as excinfo:
        other.instrument_snapshot(routed_channel=1, dialog_parameters=reading)

    message = str(excinfo.value)
    assert "channel 2" in message and "channel 1" in message, message
    assert other.screen_reads == 0, "the screen was read before the channels were compared"
    assert other.closed == 1, "the dialog is closed behind the refused read"

    # The same reading on the channel it was routed to is never refused...
    padded = FakeDialogDriver(channel=" 2 ")
    agreed = padded.read_dialog_parameters()
    assert padded._require_same_channel(2, agreed) is None
    # ...and an unreadable reading keeps the reader's own reason instead of this one's.
    refused = FakeDialogDriver(open_raises="a menu popup is already open").read_dialog_parameters()
    assert FakeDialogDriver()._require_same_channel(1, refused) is None
    assert refused.reason
