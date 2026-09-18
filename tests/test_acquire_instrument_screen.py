"""The production-shaped tree: the instrument's own measured screen, resolved for real.

Every §24 case in this repository synthesises the tree it asserts against
(``test_acquire_layout_gate.manual_screen``) or states an already-resolved role map, so the
numbers the gate is pinned to are those fixtures' own invention — the clean screen is 43
*by construction*. What no test did is what the refactor has to survive: the tree the instrument
really painted, read by the driver's own resolver.

``tests/data/udop-measurement-screen-tree-instrument.json`` is that tree — the sanitised
real-experiment-mode read of 2026-09-18 (probe ``tools/live/probes/main_geometry.py``: 44 visible
controls in 4 panels, strip view ``ready``, caption ``UDOP DOP3010.43``) with the handles, the
cursor and the control tree itself dropped. This module gives the tree back: it projects the
fixture's flat control list onto the *same* fake ``win32gui`` surface
``test_acquire_surface_classification.py`` reads its measured dialog through (``_MeasuredGui``
and ``_row``, imported rather than copied), runs ``Win32Actuator._resolve`` on it for real, and
holds the production screen's own facts against **the fixture's own statements** — the row texts,
the strip's view, the visible-control total — so the reading and the read are checked against
each other rather than against a number written here.

**The parent map, and why it has to be inferred.** The fixture states no tree (handles are
volatile and the tree is the driver's own business), so the projection carries a parent for every
control and says how it got it: the four bands and the monitor hang off the window; a button
belongs to the panel whose rect holds its centre; a value field belongs to the
``TSp_Value_Button`` that wraps it, and the native ``Edit`` inside a ``TComboBox`` to that combo
(a Windows combo owns its edit), while a ``TSp_Edit`` is always its row's own child and never the
combo's — the stale-cell shape ledger B09 measured beside a painted combo. The two
``TSp_Button`` rows that sit *below* the strip panel's own rect are that panel's children:
``ui.strip.strip_row``'s own docstring states the pair ("Two buttons the panel never paints sit
below the panel's own rect") and the resolver's row filter is written to exclude them by centre.
Every one of those readings is guarded by a test that asserts the shape it rests on, and the one
relationship the fixture cannot state is driven *both* ways round in
:func:`test_the_two_buttons_below_the_strip_rect_are_one_reading_of_the_tree_not_a_verdict`.

**What this file is not.** It is not a device claim — nothing here is live-verified, and
``docs/dop3000/device-verification.md`` stays *device-pending*. It presses nothing:
``test_resolving_the_production_tree_reaches_no_user32_and_presses_nothing`` booby-traps the
transport and proves a resolve of this tree stays a read, so the file is safe to run on a machine
with the application in front of it. Every entry point is a name the refactor keeps re-exporting
(``driver.Win32Actuator._resolve``, ``driver.layout_shape_reasons``, ``driver.layout_refusal``,
``driver.layout_evidence``, ``driver.screen_mode``, ``driver.anchor_button``,
``driver.read_parameter``), so a module moving underneath them does not move this file.
"""

from __future__ import annotations

import ctypes
import json
import typing
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from test_acquire_layout_gate import CLIENT, ORIGIN
from test_acquire_surface_classification import WINDOW_HWND, _MeasuredGui, _row
from test_acquire_ui_counterexamples import INSTRUMENT_BAR

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import (
    PARAM_COLUMN_ORDER,
    ChannelMode,
    ParamRole,
    ProcessMode,
    StripView,
    process_mode,
)
from udv_echo_process.acquire.ui.layout import classify_surface
from udv_echo_process.acquire.ui.menu import (
    MEASURED_BAR,
    PARAMETERS_MENU,
    PARAMETERS_POPUP_LEFT,
)
from udv_echo_process.acquire.ui.model import ParameterPanelState, SurfaceKind

FIXTURE = (
    Path(__file__).parent / "data" / "udop-measurement-screen-tree-instrument.json"
)

#: The handle the projection gives the fixture's first control. The fixture carries no handle at
#: all (control ids change on every launch), so the projection states one per control, in the
#: fixture's own order — and the window keeps ``test_acquire_surface_classification.WINDOW_HWND``
#: (700), which is above every control, so no control handle is ever the window's.
HANDLE_BASE = 1000

#: The four bands' own rects, in the fixture's own coordinates — quoted here so a claim about one
#: of them reads as the panel it is (``main_geometry.py``'s 2026-09-18 read).
MENUBAR_BAND = (0, 23, 1920, 55)
COLUMN_PANEL = (0, 55, 190, 1016)
STRIP_PANEL = (343, 414, 695, 454)
STATUS_BAND = (0, 1016, 1920, 1050)
PLOT = (200, 65, 1910, 1006)

#: The `Tgc [dB]` row's two controls — the row §26.2 measured as present exactly when the TGC
#: mode is `Uniform`, and the whole of the instrument's 44 → 42 (its value button and its cell).
TGC_ROW = ((10, 325, 105, 349), (14, 329, 54, 345))

#: The instrument's own bar, left → right, as ``MEASURED_BAR`` says it is painted: ten entries
#: with ``Help`` alone at the band's right end (UI-WINDOW-01).
INSTRUMENT_BAR_LEFTS = (8, 63, 169, 258, 334, 406, 466, 526, 606, 1850)


# --------------------------------------------------------------------------- the fixture, as read


def instrument_tree() -> dict:
    """The committed fixture, read from disk — ``tests/data``' own JSON, never a copy of it."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rect(control: Mapping) -> tuple[int, int, int, int]:
    """One fixture control's rect, as the tuple the projection and the rules compare."""
    left, top, right, bottom = control["rect"]
    return (int(left), int(top), int(right), int(bottom))


def _centre(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """A rectangle's centre, as ``ui.menu._inside`` computes it (integer division)."""
    left, top, right, bottom = rect
    return ((left + right) // 2, (top + bottom) // 2)


def _holds_centre(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> bool:
    """True when ``inner``'s centre lies inside ``outer`` — the rule the strip vote and the
    parameter column's own resolution both use."""
    cx, cy = _centre(inner)
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _wraps(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    """True when ``inner``'s rect lies inside ``outer``'s — the nesting test a value field is
    found by (``ui.dialog._contains``)."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _area(rect: tuple[int, int, int, int]) -> int:
    """A rectangle's area, used to pick the innermost wrapping control."""
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def project_rows(tree: Mapping) -> list[dict]:
    """The fixture's flat control list as rows on the ``win32gui`` surface, tree inferred.

    The projection the module docstring describes, and nothing else: one row per fixture control,
    in the fixture's own order, each stating the rect, the class, the text the read recorded and a
    **handle** the fixture does not carry (``HANDLE_BASE`` + the control's index). The parent map
    is the inferred one, and :func:`test_the_flat_fixture_projects_onto_a_window_the_resolver_can_read`
    is the guard on its shape.
    """
    controls = list(tree["controls"])
    handle = {index: HANDLE_BASE + index for index in range(len(controls))}
    rect = {index: _rect(control) for index, control in enumerate(controls)}
    panels = [
        index for index, control in enumerate(controls) if control["cls"] == "TSp_Panel"
    ]
    fields = [
        index
        for index, control in enumerate(controls)
        if control["cls"] == "TSp_Value_Button"
    ]
    combos = [
        index for index, control in enumerate(controls) if control["cls"] == "TComboBox"
    ]

    def parent_of(index: int) -> int:
        """The inferred parent of one control — the module docstring's rules, in order."""
        cls = controls[index]["cls"]
        if cls in ("TSp_Panel", "TDop_Plot"):
            # The bands and the monitor are the window's own children: no band sits inside
            # another, and the monitor is not inside any of them.
            return WINDOW_HWND
        if cls == "TSp_Button":
            host = next(
                (p for p in panels if _holds_centre(rect[p], rect[index])), None
            )
            if host is not None:
                return handle[host]
            # A button no panel's rect holds: the strip panel's own two, below its rect. The
            # narrowest panel whose x-span carries it is that panel — the full-width bands carry
            # every x, so taking the innermost is what identifies it, and the guard below fails
            # if that is ever not a unique choice (the inference, not the fixture, would then
            # have decided the tree).
            spans = [
                p for p in panels if rect[p][0] <= _centre(rect[index])[0] <= rect[p][2]
            ]
            narrowest = min(spans, key=lambda p: _area(rect[p]))
            assert all(
                _area(rect[p]) > _area(rect[narrowest]) for p in spans if p != narrowest
            ), f"control {index} has no unique panel above it"
            return handle[narrowest]
        if cls == "Edit":
            # The native edit a combo owns, which is the Win32 structure of a combo box.
            host = next((c for c in combos if _wraps(rect[c], rect[index])), None)
            return handle[host] if host is not None else WINDOW_HWND
        # A `TSp_Edit` or a `TComboBox`: the *value button* that wraps it is its row container.
        # The innermost one wins; a `TSp_Edit` never nests inside a combo, which is the shape
        # ledger B09 measured (a stale cell beside the combo that paints the value).
        host = min(
            (f for f in fields if _wraps(rect[f], rect[index])),
            key=lambda f: _area(rect[f]),
            default=None,
        )
        return handle[host] if host is not None else WINDOW_HWND

    return [
        _row(
            handle[index],
            control["cls"],
            parent_of(index),
            rect[index],
            control["text"],
        )
        for index, control in enumerate(controls)
    ]


def surface(rows: Sequence[dict]) -> _MeasuredGui:
    """The rows on the fake ``win32gui`` surface one resolve reads them through."""
    return _MeasuredGui(list(rows))


def resolved_instrument(
    monkeypatch: pytest.MonkeyPatch, *, rows: Sequence[dict] | None = None
) -> dict:
    """``Win32Actuator._resolve``'s own answer for the fixture's tree, or for one variant of it."""
    gui = surface(project_rows(instrument_tree()) if rows is None else rows)
    monkeypatch.setattr(driver, "_gui", lambda: (gui, None))
    return driver.Win32Actuator(channel=1)._resolve()


def handle_of(rows: Sequence[dict], cls: str, rect: tuple[int, int, int, int]) -> int:
    """The handle the projection gave one fixture control — by class and rect, its only identity."""
    return next(
        row["hwnd"]
        for row in rows
        if row["cls"] == cls and tuple(row["rect"]) == tuple(rect)
    )


class _TextUser32:
    """``user32`` as far as a ``WM_GETTEXT`` read reaches it: the control's own tree text.

    A *resolve* needs no transport at all (and
    :func:`test_resolving_the_production_tree_reaches_no_user32_and_presses_nothing` asserts it);
    the one send a parameter read makes is ``WM_GETTEXT``, answered here from the same rows — so
    the value a role reads back is the text the tree states, which is what the live application
    answers. Nothing else is answered, because nothing else is asked.
    """

    def __init__(self, texts: Mapping[int, str]) -> None:
        self.texts = dict(texts)
        self.calls: list[tuple[int, int]] = []

    def SendMessageTimeoutW(self, hwnd, msg, wp, lp, flags, timeout_ms, result) -> int:
        """Answer ``WM_GETTEXT`` with the control's text, written into the caller's buffer."""
        key = int(getattr(hwnd, "value", hwnd))
        self.calls.append((key, msg))
        if msg != driver.WM_GETTEXT:
            return 0
        text = self.texts.get(key, "")
        ctypes.memmove(lp, (text + "\x00").encode("utf-16-le"), 2 * (len(text) + 1))
        return len(text)


# ----------------------------------------------------------------- the fixture, and its projection


def test_the_fixture_is_the_read_its_own_note_states() -> None:
    """The guard the rest of this file rests on: the committed read is the screen it claims.

    ``44 visible controls in 4 panels``, the strip panel §23.1 measured, the parameter column's
    ten values and the caption of the real-experiment mode — all of it the fixture's own
    statement, so a fixture that drifted fails *here* instead of silently re-baselining every
    assertion below it.
    """
    tree = instrument_tree()
    controls = list(tree["controls"])

    assert "2026-09-18" in tree["probe"]
    assert tree["caption"] == "UDOP DOP3010.43"
    assert tree["strip_view"] == StripView.READY.value
    assert len(controls) == 44
    assert (
        len([c for c in controls if c["cls"] == "TSp_Panel"])
        == driver.EXPECTED_PANEL_COUNT
    )
    assert len([c for c in controls if c["cls"] == "TDop_Plot"]) == 1
    # The column's own values, top → bottom, as the read recorded them: the seven roles' fields,
    # then the mode's own `Tgc [dB]` row and the two combo rows below it.
    assert [entry["text"] for entry in tree["param_column"]] == [
        "4000",
        "600",
        "50",
        "1.850",
        "1.00",
        "20",
        "0",
        "20",
        "89",
        "89",
    ]
    # The window's own geometry, as the rest of the suite measured it: the menubar band starts at
    # the client's top and the status band ends at its bottom, so the fixture is a 1920x1027
    # client at the origin the resolver reads.
    bands = [tuple(c["rect"]) for c in controls if c["cls"] == "TSp_Panel"]
    assert sorted(bands, key=lambda band: band[1]) == [
        MENUBAR_BAND,
        COLUMN_PANEL,
        STRIP_PANEL,
        STATUS_BAND,
    ]
    assert MENUBAR_BAND[1] == ORIGIN[1]
    assert STATUS_BAND[3] == ORIGIN[1] + CLIENT[1]
    assert STRIP_PANEL[2] - STRIP_PANEL[0] == 352  # §23.1's own 352 px strip panel
    # ...and the bar this file reads off the JSON is the bar `test_acquire_ui_counterexamples.py`
    # quoted from it by hand, offset for offset: the two readings of the one read agree.
    bar = sorted(
        (
            c["rect"]
            for c in controls
            if c["cls"] == "TSp_Button" and _holds_centre(MENUBAR_BAND, _rect(c))
        ),
        key=lambda rect: rect[0],
    )
    assert (
        tuple((rect[0] - bar[0][0], rect[2] - rect[0]) for rect in bar)
        == INSTRUMENT_BAR
    )


def test_the_flat_fixture_projects_onto_a_window_the_resolver_can_read() -> None:
    """The projection guard: every control has a parent, and the shape inferred is the driver's.

    The fixture states no tree, so the parents are the inferred ones (module docstring). What is
    asserted here is that the inference lands on *the* tree the driver's own rules were written
    for — the four bands and the monitor the window's children, each field inside its own value
    button (so ``_param_rows`` binds it), the combo's native edit inside the combo, and the strip
    panel hosting both its row and the two buttons below its rect that ``ui.strip.strip_row``
    excludes by centre. A projection that got any of that wrong would move the reading, not just
    the test.
    """
    tree = instrument_tree()
    rows = project_rows(tree)
    parents = {row["hwnd"]: row["parent"] for row in rows}
    by_hwnd = {row["hwnd"]: row for row in rows}

    assert len(rows) == len(tree["controls"]) == 44
    assert set(parents) == set(by_hwnd)
    assert set(parents.values()) <= {WINDOW_HWND} | set(parents)

    for row in rows:
        if row["cls"] in ("TSp_Panel", "TDop_Plot"):
            assert row["parent"] == WINDOW_HWND, row
        if row["cls"] in ("TSp_Edit", "TComboBox"):
            assert by_hwnd[row["parent"]]["cls"] == "TSp_Value_Button", row
        if row["cls"] == "Edit":
            assert by_hwnd[row["parent"]]["cls"] == "TComboBox", row

    # The strip panel's children: its three-button row *and* the pair below its own rect — the
    # pair the resolver's row filter is written to exclude, not the pair the fixture forgot.
    strip_hwnd = handle_of(rows, "TSp_Panel", STRIP_PANEL)
    kids = [row for row in rows if row["parent"] == strip_hwnd]
    assert [row["cls"] for row in kids] == ["TSp_Button"] * 5
    below = sorted(tuple(row["rect"]) for row in kids if row["top"] >= STRIP_PANEL[3])
    assert below == [(350, 467, 401, 482), (409, 467, 453, 482)]
    # ...and the whole tree is read off the fixture: every row's text is the fixture's own.
    assert [row["text"] for row in rows] == [c["text"] for c in tree["controls"]]


# ------------------------------------------------------------------- the production reading


def test_the_production_tree_resolves_to_the_tree_the_fixture_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reading: the instrument's measured tree, resolved by the driver's own resolver.

    Every assertion is a fact of the read the fixture recorded — the client and its origin, the
    four bands in order, the ten-entry bar with its anchor at the popup's own left, the strip's
    three-button ``ready`` row in the panel §23.1 measured, and the column's ten rows carrying the
    ten texts the read recorded — so the resolver is checked against the screen rather than
    against a synthesised tree that happens to look like it.
    """
    tree = instrument_tree()
    rows = project_rows(tree)
    roles = resolved_instrument(monkeypatch, rows=rows)

    assert roles["client"] == CLIENT
    assert roles["origin"] == ORIGIN
    assert roles["class_name"] == driver.MAIN_CLASS
    assert len(roles["raw"]) == 44
    assert [p["top"] for p in roles["panels"]] == [23, 55, 414, 1016]
    assert [tuple(p["rect"]) for p in roles["panels"]] == [
        MENUBAR_BAND,
        COLUMN_PANEL,
        STRIP_PANEL,
        STATUS_BAND,
    ]
    assert roles["menu_band"]["hwnd"] == handle_of(rows, "TSp_Panel", MENUBAR_BAND)
    assert roles["plot"]["hwnd"] == handle_of(rows, "TDop_Plot", PLOT)

    # The instrument's own bar, and the one binding it proves: the anchor, third by position, at
    # the popup's own measured left — the popup opens under *this* button (§26.1).
    assert [b["left"] for b in roles["menu_buttons"]] == list(INSTRUMENT_BAR_LEFTS)
    assert len(roles["menu_buttons"]) == len(MEASURED_BAR) == 10
    anchor = driver.anchor_button(driver.observation_of(roles))
    assert anchor is not None and anchor.rect is not None
    assert anchor.rect.left == PARAMETERS_POPUP_LEFT == 169
    assert roles["menu"] == {PARAMETERS_MENU: roles["menu_buttons"][2]}

    # The strip: the panel §23.1 measured, the row a press would be bound to (left → right), and
    # the view the fixture's own field states.
    assert roles["strip_panel"]["hwnd"] == handle_of(rows, "TSp_Panel", STRIP_PANEL)
    assert [b["left"] for b in roles["strip_row"]] == [353, 442, 537]
    assert roles["strip_slider"] is False
    assert roles["state"] == tree["strip_view"] == StripView.READY.value

    # The column: ten rows, and the seven roles bound top → bottom to the first seven of them,
    # each row reading the text the fixture recorded for it.
    assert roles["left_panel"]["hwnd"] == handle_of(rows, "TSp_Panel", COLUMN_PANEL)
    assert len(roles["param_rows"]) == len(tree["param_column"]) == 10
    assert [row["edit"]["text"] for row in roles["param_rows"]] == [
        entry["text"] for entry in tree["param_column"]
    ]
    assert list(roles["params"]) == list(PARAM_COLUMN_ORDER)
    assert [roles["params"][role]["button"]["hwnd"] for role in PARAM_COLUMN_ORDER] == [
        row["button"]["hwnd"] for row in roles["param_rows"][: len(PARAM_COLUMN_ORDER)]
    ]

    # Nothing is over the screen, and nothing on it is a dialog: the read is the measurement
    # screen and nothing else.
    assert roles["open_popup"] is False
    assert roles["value_dialogs"] == set()
    assert roles["browse_dialogs"] == set()


def test_the_production_tree_passes_the_gate_the_run_is_gated_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict: the instrument's own screen is accepted, and read as a manual channel.

    This is the §24 claim the fixture was delivered for, asserted on the tree it was measured
    from: no shape clause at all, the surface classified as the measurement screen, the column
    present and complete, and the counts — 44 in 4, one more control than the reference install's
    43 in 4 — carried as *evidence* in the sentence a report shows (D4), never as a gate.
    """
    roles = resolved_instrument(monkeypatch)

    assert driver.layout_shape_reasons(roles) == ()
    assert driver.layout_refusal(roles) is None
    assert classify_surface(roles) is SurfaceKind.MEASUREMENT
    assert driver.screen_mode(roles) is ChannelMode.MANUAL
    observation = driver.observation_of(roles)
    assert observation.parameter_panel is ParameterPanelState.PRESENT_COMPLETE
    assert observation.control_count == 44
    assert len(observation.panels) == driver.EXPECTED_PANEL_COUNT

    evidence = driver.layout_evidence(roles)
    assert "44 visible controls in 4 panels" in evidence
    # ...beside the reference install's own reading, so the drift between the two is readable.
    assert (
        f"the reference install's clean screen reads {driver.EXPECTED_CONTROL_COUNT} "
        f"in {driver.EXPECTED_PANEL_COUNT}"
    ) in evidence
    assert f"7 of {len(PARAM_COLUMN_ORDER)} role(s)" in evidence
    assert "no menu popup" in evidence and "0 dialog panel(s)" in evidence


def test_the_production_tree_reads_back_the_parameters_it_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read the runner takes, on the production tree: ``read_parameter`` for every role.

    The values are the fixture's own column, read through the driver's own path — the row's edit
    handle, ``WM_GETTEXT``, answered from the tree — so this is where the fixture's flat texts
    become the driver's reading: 4000 kHz, PRF 600, 50 gates, resolution 1.850 mm, velocity scale
    1.00, 20 emissions and a 0° angle, the numbers §23.1 recorded in real-experiment mode. A role
    bound to the wrong row reads a *plausible* wrong number, which is why the binding is asserted
    above and the values here.
    """
    rows = project_rows(instrument_tree())
    monkeypatch.setattr(driver, "_gui", lambda: (surface(rows), None))
    monkeypatch.setattr(
        driver, "_user32", lambda: _TextUser32({r["hwnd"]: r["text"] for r in rows})
    )
    screen = driver.Win32Actuator(channel=1)

    assert {role: screen.read_parameter(role) for role in PARAM_COLUMN_ORDER} == {
        ParamRole.US_FREQUENCY: "4000",
        ParamRole.PRF: "600",
        ParamRole.GATES: "50",
        ParamRole.RESOLUTION: "1.850",
        ParamRole.VELOCITY_SCALE_FACTOR: "1.00",
        ParamRole.EMISSIONS_PER_PROFILE: "20",
        ParamRole.DOPPLER_ANGLE: "0",
    }
    # ...and the channel the screen states is a statement of the fixture, not of a caption.
    assert screen.channel == 1


def test_the_caption_the_fixture_records_is_the_mode_the_run_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mode rung on the production read: the fixture's caption is the instrument's own.

    Nothing structural states which process is on the screen — the two clean layouts differ by the
    *mode's* own panel, not by a discriminator — so the caption is the evidence and the read
    carries the one it was taken under. The declaration the caption states passes; a run declared
    against the simulator is refused and the refusal names both the caption and the two modes.
    """
    caption = instrument_tree()["caption"]
    roles = resolved_instrument(monkeypatch)

    assert process_mode(caption) is ProcessMode.INSTRUMENT
    assert (
        driver.layout_refusal(
            roles, caption=caption, expected_mode=ProcessMode.INSTRUMENT
        )
        is None
    )

    mismatched = driver.layout_refusal(
        roles, caption=caption, expected_mode=ProcessMode.SIMULATION
    )
    assert mismatched is not None
    assert caption in mismatched
    assert "'instrument'" in mismatched and "'simulation'" in mismatched
    # The mode clause is the *only* reason: the layout itself passes, so an operator is not sent
    # looking for a layout drift that is not there (§24.5 D5).
    assert "layout" not in mismatched


def test_the_measured_tgc_row_is_a_count_and_never_a_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The instrument's own 44 → 42: the pair §26.2 measured, on the production tree itself.

    The ``Tgc [dB]`` row is on screen exactly when the TGC mode is ``Uniform``, and it costs two
    visible controls — its value button and its cell, the pair ``TGC_ROW`` names. The same channel
    therefore reads 44 in one setting and 42 in the other, and neither reading may be refused or
    gated on: a gate keyed on the total would refuse a screen for carrying a row the operator's own
    TGC setting put there (plan §24.5 D4). Both are visible in the evidence line a report shows.
    """
    tree = instrument_tree()
    rows = project_rows(tree)
    without = [row for row in rows if tuple(row["rect"]) not in TGC_ROW]

    assert [
        tuple(c["rect"]) for c in tree["controls"] if tuple(c["rect"]) in TGC_ROW
    ] == list(TGC_ROW)
    assert len(without) == 42

    for reading, controls, column_rows in ((rows, 44, 10), (without, 42, 9)):
        roles = resolved_instrument(monkeypatch, rows=reading)
        assert len(roles["raw"]) == controls
        assert len(roles["param_rows"]) == column_rows
        assert driver.layout_shape_reasons(roles) == (), controls
        assert driver.layout_refusal(roles) is None, controls
        assert driver.screen_mode(roles) is ChannelMode.MANUAL, controls
        assert f"{controls} visible controls in 4 panels" in driver.layout_evidence(
            roles
        )


def test_the_two_buttons_below_the_strip_rect_are_one_reading_of_the_tree_not_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one relationship the fixture cannot state, driven both ways round.

    ``ui.strip.strip_row``'s docstring says the strip panel "never paints" two buttons that sit
    below its own rect, so the projection reads them as that panel's children — the tree the
    resolver's own row filter was written against. The fixture cannot state it (it drops the tree),
    so the other reading is driven too: the same two rows hung off the window. What moves is the
    vote's own score, and it stays inside the plot's 0.30-0.70 band in both; what must *not* move
    is the binding (the panel, the row a press is bound to, the view), the gate's verdict, or the
    evidence line a reader compares across sessions.
    """
    rows = project_rows(instrument_tree())
    strip_hwnd = handle_of(rows, "TSp_Panel", STRIP_PANEL)
    below = {
        row["hwnd"] for row in rows if row["parent"] == strip_hwnd and row["top"] >= 454
    }
    assert len(below) == 2
    hung_off_the_window = [
        {**row, "parent": WINDOW_HWND} if row["hwnd"] in below else row for row in rows
    ]

    readings = (rows, hung_off_the_window)
    for reading in readings:
        roles = resolved_instrument(monkeypatch, rows=reading)
        assert roles["strip_panel"]["hwnd"] == strip_hwnd
        assert [b["left"] for b in roles["strip_row"]] == [353, 442, 537]
        assert roles["state"] == StripView.READY.value
        assert roles["strip_slider"] is False
        assert driver.layout_shape_reasons(roles) == ()

    # The vote itself, as arithmetic a reader can check: the centre of the panel's own button row
    # as a fraction of the plot's height, and the band the resolver scores it in.
    for reading in readings:
        centres = [
            row["top"] + row["h"] / 2
            for row in reading
            if row["cls"] == "TSp_Button" and row["parent"] == strip_hwnd
        ]
        fraction = (sum(centres) / len(centres) - PLOT[1]) / (PLOT[3] - PLOT[1])
        assert 0.30 <= fraction <= 0.70, (reading is rows, fraction)

    first, second = (
        resolved_instrument(monkeypatch, rows=reading) for reading in readings
    )
    assert driver.layout_evidence(first) == driver.layout_evidence(second)


def test_resolving_the_production_tree_reaches_no_user32_and_presses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolve of this tree is a **read**: no send, no post, no cursor, no press.

    The property that makes this file safe to run on a machine with the application in front of
    it — and the property ``acquire status`` depends on, since a diagnosis resolves the screen
    without touching it. ``user32`` and ``_post`` are booby-trapped, so reaching either is the
    failure whichever call it makes, and the driver's own diagnostics must still be empty.
    """

    class NoTransport:
        def __getattr__(self, name: str) -> typing.NoReturn:
            raise AssertionError(
                f"resolving the production tree reached user32.{name}: a resolve is a read"
            )

    rows = project_rows(instrument_tree())
    monkeypatch.setattr(driver, "_gui", lambda: (surface(rows), None))
    monkeypatch.setattr(driver, "_user32", lambda: NoTransport())

    def _no_post(*args: object, **kwargs: object) -> None:
        raise AssertionError("a resolve posted a message")

    monkeypatch.setattr(driver, "_post", _no_post)
    screen = driver.Win32Actuator(channel=1)

    roles = screen._resolve()

    assert driver.layout_refusal(roles) is None
    assert screen.last_press_screen is None, "a resolve pressed something"
    assert screen.last_hover_screen is None, "a resolve moved the cursor"


def test_the_same_projection_is_what_the_gate_reads_not_a_tree_that_accepts_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative controls: the acceptance above is a reading of this tree, not of any tree.

    An acceptance test is evidence only if the machinery it goes through can refuse. Three
    mutations of the production tree — the anchor's own button gone, the monitor gone, the
    column's value cells not on the screen — must each turn the *same* projection into the clause
    that names exactly what went missing, while the unmutated tree stays accepted.
    """
    rows = project_rows(instrument_tree())
    anchor = handle_of(rows, "TSp_Button", (169, 28, 239, 53))
    plot = handle_of(rows, "TDop_Plot", PLOT)
    cells = {row["hwnd"] for row in rows if row["cls"] == "TSp_Edit"}

    missing_anchor = [row for row in rows if row["hwnd"] != anchor]
    missing_plot = [row for row in rows if row["hwnd"] != plot]
    hidden_cells = [
        {**row, "visible": False} if row["hwnd"] in cells else row for row in rows
    ]

    for reading, clause in (
        (missing_anchor, "menubar"),
        (missing_plot, "plot"),
        (hidden_cells, "parameter column"),
    ):
        roles = resolved_instrument(monkeypatch, rows=reading)
        reasons = driver.layout_shape_reasons(roles)
        assert reasons, clause
        assert any(clause in reason for reason in reasons), (clause, reasons)
        assert driver.layout_refusal(roles) is not None
