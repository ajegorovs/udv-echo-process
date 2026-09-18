"""The layout gate and the stated process mode — plan §24, its §24.6 table.

What this module pins, and why it exists at all: ``layout_note`` used to be ``None`` only when the
visible-control count was exactly ``EXPECTED_CONTROL_COUNT`` (43) and the panel count 4, so the
**instrument** — whose clean screen reads 44 in 4, because its parameter column paints one more
row — was refused for looking *more* like the instrument than the simulator does.

§24 splits the one gate into the three jobs it was doing: a **structural** shape check that is
mode-independent (:func:`driver.layout_shape_reasons`), a **stated** process mode read from the
caption and compared with a declaration the caller makes (``process_mode`` / ``process_mode_clause``
/ ``campaign.refuse_process_mode``), and the total count, which stops being a gate in either mode and
becomes **evidence** (§24.5 D4) carried by :func:`driver.layout_evidence` into the reading, the note
and the run's record.

Everything here is headless and instrument-free: the screens are *resolved role maps* synthesised
in the shape ``Win32Actuator._resolve`` returns, so the shape check — which is pure over that map —
is exercised on trees rather than on a window. The single case that must go through a driver uses a
:class:`StubScreen`, whose window layer is faked and whose **input primitives are overridden**, so
this file can never press anything even if the gate it is testing regresses.

The identity rows of §24.6 (the mode moving ``identity_digest``, the count no longer moving it, and a
W4-shaped identity refusing on a resume) are pinned next to the models they are about:
``tests/test_acquire_snapshot.py`` and ``tests/test_acquire_campaign.py``.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from test_acquire_runner import FakeActuator, point_for

from udv_echo_process.acquire import campaign, driver, live, runner
from udv_echo_process.acquire.actuator import (
    PROCESS_MODE_PREFIXES,
    ChannelMode,
    OverlayKind,
    ProcessMode,
    ScreenFingerprint,
    StripState,
    StripView,
    classify_strip_view,
    process_mode,
)
from udv_echo_process.acquire.config import RecordSettings

#: The client and its screen-space origin, as §21/§22 measured them: panel rects arrive in screen
#: coordinates (``_visible_children`` reads ``GetWindowRect``), so a synthesised tree carries an
#: origin like the driver's own.
CLIENT = (1920, 1027)
ORIGIN = (0, 23)

#: The instrument's caption and the simulator's — the two strings the vocabulary is prefix-matched
#: against, one of them carrying a version (§22.1).
INSTRUMENT_CAPTION = "UDOP DOP3010.43"
SIMULATION_CAPTION = "UDOP Simul"

_CLASS = driver.MAIN_CLASS


def _widget(hwnd: int, cls: str, left: int, top: int, w: int, h: int) -> dict:
    """One control in the shape ``_visible_children`` produces."""
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
    }


def _panel(hwnd: int, top: int, *, left: int = 0, w: int = 1920, h: int = 25) -> dict:
    return _widget(hwnd, "TSp_Panel", left, top, w, h)


def _button(hwnd: int, left: int, top: int) -> dict:
    return _widget(hwnd, "TSp_Button", left, top, 80, 20)


def _value_row(hwnd: int, top: int) -> list[dict]:
    """One parameter-column row: the value button and the edit inside it."""
    button = _widget(hwnd, "TSp_Value_Button", 10, top, 130, 24)
    edit = _widget(hwnd, "TSp_Edit", 14, top + 4, 40, 16)
    return [button, edit]


def manual_screen(
    *,
    controls: int = 43,
    column_roles: int = len(driver.PARAM_COLUMN_ORDER),
    strip_row: int = 3,
    plot: bool = True,
    dialog: bool = False,
    popup: bool = False,
) -> dict:
    """A measured **manual** screen as a resolved role map: 4 panels, a column, a strip, a status bar.

    ``controls`` is the visible-control **total**, and it is a knob on purpose: the reference
    install's clean manual screen is 43 and the instrument's is 44, and both are this tree — the
    count is what D4 takes out of the gate, so a test has to be able to move it alone. The extra
    controls are painted as spare parameter-column rows, which is what the instrument's own ``Tgc
    [dB]`` row is.

    ``column_roles`` below seven, ``plot=False``, ``dialog=True`` and ``popup=True`` are the four
    ways §24.3 refuses a screen that looked like this one.
    """
    oy = ORIGIN[1]
    menu_band = _panel(1, oy, h=25)
    column = _panel(2, oy + 60, w=190, h=945)
    strip = _panel(3, oy + 454, left=448, w=352, h=40)
    status = _panel(4, oy + 1003, h=24)
    panels = [menu_band, column, strip, status]
    plot_control = _widget(5, "TDop_Plot", 200, oy + 42, 1710, 941) if plot else None
    row = [_button(60 + i, 455 + 90 * i, oy + 465) for i in range(strip_row)]
    rows: list[dict] = []
    for index in range(column_roles):
        rows += _value_row(100 + 2 * index, oy + 100 + 25 * index)
    value_dialogs: set[int] = set()
    if dialog:
        # The `Operating parameters` dialog: a panel of its own, wide and full of controls —
        # which is what `_is_dialog_panel`/`_resolve` recognise it by, never by its position.
        dialog_panel = _panel(9, oy + 200, left=400, w=627, h=384)
        panels.append(dialog_panel)
        value_dialogs.add(9)
    raw = [*panels, *(row or []), *rows]
    if plot_control is not None:
        raw.append(plot_control)
    # Pad to the requested total with the controls the instrument paints and the simulator does
    # not — its parameter column's extra `Tgc [dB]` row, here a bare label because a *total* is all
    # this needs to move. The padding is never truncated away, so every tree below keeps the four
    # bands, the row and the plot that its shape is judged by.
    while len(raw) < max(controls, 1):
        raw.append(_widget(700 + len(raw), "TSp_Label", 10, oy + 400, 120, 18))
    roles: dict = {
        "window": 0,
        "class_name": _CLASS,
        "client": CLIENT,
        "origin": ORIGIN,
        "raw": raw,
        "panels": sorted(panels, key=lambda p: p["top"]),
        "parent_of": {w["hwnd"]: 0 for w in raw},
        "menu": {"Parameters": _button(200, 0, oy)},
        "menu_band": menu_band,
        "plot": plot_control,
        "open_popup": popup,
        "value_dialogs": value_dialogs,
        "browse_dialogs": set(),
        "strip_panel": strip,
        "strip_row": row,
        "state": classify_strip_view(
            len(row), any(w["cls"] == "TSp_Sliding_Bar" for w in row)
        ).value,
        "left_panel": column,
        "param_rows": [
            {"button": rows[i], "edit": rows[i + 1]} for i in range(0, len(rows), 2)
        ],
        "params": {
            role: {"button": rows[2 * i], "edit": rows[2 * i + 1]}
            for i, role in enumerate(driver.PARAM_COLUMN_ORDER)
            if 2 * i + 1 < len(rows)
        },
    }
    for widget in raw:
        roles["parent_of"][widget["hwnd"]] = (
            widget["hwnd"] if widget["cls"] == "TSp_Panel" else 0
        )
    return roles


def assisted_screen(*, controls: int = 21) -> dict:
    """The **assisted** shape: the same bands, and **no parameter column anywhere** on the screen.

    Three panels — the menubar band, the strip and the status bar — because the application removes
    the sidebar column for an assisted channel (measured: 21 visible controls in 3 panels). That
    absence is exactly what :func:`driver.screen_mode` reads as :attr:`ChannelMode.ASSISTED`, which
    is why the two shapes have to be *alternatives*: a predicate that demanded a column would refuse
    this screen before the classification could ever run.
    """
    oy = ORIGIN[1]
    menu_band = _panel(1, oy, h=25)
    strip = _panel(3, oy + 454, left=448, w=352, h=40)
    status = _panel(4, oy + 1003, h=24)
    row = [_button(60 + i, 455 + 90 * i, oy + 465) for i in range(3)]
    plot_control = _widget(5, "TDop_Plot", 200, oy + 42, 1710, 941)
    raw = [menu_band, strip, status, plot_control, *row]
    while len(raw) < controls:
        raw.append(_widget(700 + len(raw), "TSp_Label", 10, oy + 300, 120, 18))
    roles: dict = {
        "window": 0,
        "class_name": _CLASS,
        "client": CLIENT,
        "origin": ORIGIN,
        "raw": raw,
        "panels": [menu_band, strip, status],
        "parent_of": {w["hwnd"]: 0 for w in raw},
        "menu": {"Parameters": _button(200, 0, oy)},
        "menu_band": menu_band,
        "plot": plot_control,
        "open_popup": False,
        "value_dialogs": set(),
        "browse_dialogs": set(),
        "strip_panel": strip,
        "strip_row": row,
        "state": classify_strip_view(len(row), False).value,
        "left_panel": None,
        "param_rows": [],
        "params": {},
    }
    return roles


# ------------------------------------------------------------------ 24.6, rows 1 and 2
# The count is evidence and the two shapes are alternatives.


def test_a_manual_screen_passes_at_43_controls_and_at_44() -> None:
    """D4: the instrument is no longer refused for being the instrument.

    43 (the reference install's clean manual screen) and 44 (the instrument's own, whose parameter
    column paints one more row) are the *same tree* with one control more, and both are accepted.
    """
    for controls in (43, 44):
        roles = manual_screen(controls=controls)
        assert driver.layout_shape_reasons(roles) == (), controls
        assert driver.layout_refusal(roles) is None, controls
        assert len(roles["raw"]) == controls


def test_each_count_appears_in_the_evidence_line() -> None:
    """The count stays a *reading*: 43 and 44 are both visible to whoever reads a report (D4)."""
    for controls in (43, 44):
        roles = manual_screen(controls=controls)
        evidence = driver.layout_evidence(roles)
        assert f"{controls} visible controls" in evidence, evidence
        # ...and the reference install's own reading is named beside it, so the drift is readable
        # rather than merely present.
        assert str(driver.EXPECTED_CONTROL_COUNT) in evidence
        assert str(driver.EXPECTED_PANEL_COUNT) in evidence


def test_no_count_is_a_gate_at_any_value() -> None:
    """The shape decides, and it is indifferent to the total — even to a wildly different one."""
    for controls in (22, 42, 43, 44, 45, 99):
        roles = manual_screen(controls=controls)
        assert driver.layout_refusal(roles) is None, controls
        assert len(roles["raw"]) == controls, controls


def test_the_assisted_shape_passes_the_common_core_and_is_refused_by_its_absent_column() -> None:
    """Row 2, and round 2's P1 — **corrected by ledger B01**.

    The test this replaces asserted that the assisted shape passes the gate *and* that
    :func:`driver.screen_mode` reads the missing column as ``ASSISTED``. The live incident B01
    (``UI-OVERLAY-06``, the ``Preferences`` dialog) disproved the second half: the option *Show
    fast access parameters panel (not available in assisted mode)* takes the column away while
    the channel stays manual, so the absent column cannot be read as a mode, and a manual
    acquisition requires the panel **present and complete**.

    What survives is the shape half, asserted here so the refusal cannot be satisfied by refusing
    the shape: the assisted tree is refused by *nothing structural* — no clause about the window
    class, the menubar band, the strip, the status band or the plot — and the clause that does
    refuse it is the parameter panel's own, naming the ``Preferences`` option and the assisted
    possibility without claiming either. The manual screen is unaffected.
    """
    roles = assisted_screen()
    assert len(roles["panels"]) == 3

    # ...the common core passes untouched: the refusal is about the panel, not the shape.
    structural = [
        clause
        for clause in driver.layout_shape_reasons(roles)
        if "parameter panel" not in clause
    ]
    assert structural == [], structural

    # ...and the panel is what refuses it, by name, with both readings of its absence.
    refusal = driver.layout_refusal(roles)
    assert refusal is not None
    assert "fast-access parameter panel is absent" in refusal, refusal
    assert "Preferences" in refusal and "assisted" in refusal, refusal
    assert "missing field" not in refusal  # a refusal about the screen, not a broken binding

    # No mode is read out of the absence — the reading ledger B01 forbids.
    assert driver.screen_mode(roles) is None
    # The manual shape is the manual screen's, and each is still told apart by its column.
    assert driver.screen_mode(manual_screen()) is ChannelMode.MANUAL
    assert driver.layout_refusal(manual_screen()) is None


# ------------------------------------------------------------------ 24.6, row 3
# The guard this slice must not weaken: nothing may be over the screen.


def test_a_dialog_panel_fails_and_the_clause_names_it() -> None:
    """A dialog's widgets are not the layout's, so a press would land on the wrong control."""
    roles = manual_screen(dialog=True)
    reasons = driver.layout_shape_reasons(roles)
    assert reasons, "a dialog panel over the measurement screen was accepted"
    clause = next(text for text in reasons if "dialog" in text)
    # ...naming the dialog panel itself, read off the tree rather than described.
    dialog_panel = next(p for p in roles["panels"] if p["hwnd"] == 9)
    assert str(dialog_panel["rect"]) in clause, clause
    assert driver.layout_refusal(roles) is not None


def test_an_open_popup_fails() -> None:
    """A menu popup is a button panel like any other, and the strip resolver's decoy (§21.3)."""
    roles = manual_screen(popup=True)
    reasons = driver.layout_shape_reasons(roles)
    assert any("popup" in text for text in reasons), reasons


def test_an_overlay_found_by_the_driver_is_a_clause_of_its_own() -> None:
    """``_find_overlay``'s own answer joins the refusal — it cannot be part of a pure shape check."""
    roles = manual_screen()
    assert driver.layout_refusal(roles) is None
    assert driver.layout_refusal(roles, overlay=OverlayKind.WARNING) is not None
    assert "warning" in str(driver.layout_refusal(roles, overlay=OverlayKind.WARNING))


# ------------------------------------------------------------------ 24.6, rows 4 and 5
# The common core is asserted, not assumed.


def test_a_tree_with_neither_shape_fails_and_the_clause_says_which() -> None:
    """No column **and** no resolvable strip: neither accepted shape, and the strip is named."""
    roles = manual_screen()
    roles["strip_panel"] = None
    roles["strip_row"] = []
    roles["state"] = StripState(button_count=0).view.value
    roles["params"] = {}
    roles["param_rows"] = []
    roles["left_panel"] = None
    reasons = driver.layout_shape_reasons(roles)
    assert reasons, "a screen with no strip and no column was accepted"
    assert any("strip" in text for text in reasons), reasons
    assert driver.layout_refusal(roles) is not None


def test_a_tree_with_no_status_band_fails_and_the_clause_names_it() -> None:
    """The other half of the common core: a band at the client's bottom, found by shape.

    The sidebar column alone does not answer it — it starts above the strip, and the band being
    asked for is the one under everything — so removing the status bar is a real refusal.
    """
    roles = manual_screen()
    roles["panels"] = [p for p in roles["panels"] if p["h"] != 24]
    reasons = driver.layout_shape_reasons(roles)
    assert any("status band" in text for text in reasons), reasons


def test_a_strip_row_outside_the_known_rows_fails() -> None:
    """§21.3 item 3's silent case: *a different button panel in the plot's middle band*."""
    for length in (0, 2, 5, 9):
        roles = manual_screen(strip_row=length)
        reasons = driver.layout_shape_reasons(roles)
        assert any("STRIP_BUTTON_ORDER" in text for text in reasons), (length, reasons)
    # ...while the rows the application really builds are accepted, one button included: a
    # *documented* view is not a shape failure (the runner refuses a non-startable view itself).
    for length in (1, 3, 4):
        assert driver.layout_shape_reasons(manual_screen(strip_row=length)) == (), length


def test_a_column_that_resolves_without_its_roles_fails() -> None:
    """§24.3's own refusal case: the column resolved, and it is not the column these roles bind to."""
    roles = manual_screen(column_roles=3)
    reasons = driver.layout_shape_reasons(roles)
    assert any("roles" in text for text in reasons), reasons


def test_the_class_and_the_plot_band_are_checked_too() -> None:
    """An unknown window class, and a tree with no plot for the strip's own rule to sit in."""
    other_class = manual_screen()
    other_class["class_name"] = "TOther"
    assert any("class" in text for text in driver.layout_shape_reasons(other_class))

    no_plot = manual_screen(plot=False)
    assert any("plot" in text for text in driver.layout_shape_reasons(no_plot))


# ------------------------------------------------------------------ 24.6, rows 6 and 7
# The mode rung: the one thing that cannot be checked structurally.


def test_the_caption_states_the_mode_and_is_prefix_matched() -> None:
    """The vocabulary is two prefixes, and the instrument's caption carries a version (§22.1)."""
    assert [prefix for _mode, prefix in PROCESS_MODE_PREFIXES] == ["UDOP Simul", "UDOP DOP3010"]
    assert process_mode(INSTRUMENT_CAPTION) is ProcessMode.INSTRUMENT
    assert process_mode(SIMULATION_CAPTION) is ProcessMode.SIMULATION
    # The *version* moves and the name does not: that is why the match is a prefix.
    assert process_mode("UDOP DOP3010.44") is ProcessMode.INSTRUMENT
    assert process_mode("udop dop3010.44") is ProcessMode.INSTRUMENT  # case is not the statement
    assert process_mode("UDOP Simul 607_4") is ProcessMode.SIMULATION
    # A name outside the vocabulary is a refusal, not a default: this driver was not measured
    # against it (``routed_channel``'s argument, §12.1).
    assert process_mode("UDOP DOP3011.1") is None
    assert process_mode("") is None
    assert process_mode("Some other application") is None


def test_a_declared_mode_that_differs_from_the_caption_refuses_and_names_it() -> None:
    """Row 6: the acceptance path's refusal, naming the caption it read (D5)."""
    clause = driver.process_mode_clause(INSTRUMENT_CAPTION, ProcessMode.SIMULATION)
    assert clause is not None
    assert INSTRUMENT_CAPTION in clause, clause
    assert "'instrument'" in clause and "'simulation'" in clause, clause
    # The agreeing direction states nothing.
    assert driver.process_mode_clause(INSTRUMENT_CAPTION, ProcessMode.INSTRUMENT) is None
    assert driver.process_mode_clause(SIMULATION_CAPTION, ProcessMode.SIMULATION) is None
    assert driver.process_mode_clause(SIMULATION_CAPTION, ProcessMode.INSTRUMENT) is not None


def test_an_empty_caption_refuses_with_nothing_stated_the_mode() -> None:
    """Row 7: the ``None`` case, by the ``routed_channel`` precedent — a refusal, not a default."""
    for caption in ("", "   "):
        clause = driver.process_mode_clause(caption, ProcessMode.SIMULATION)
        assert clause is not None
        assert "nothing stated the mode" in clause, clause
    unknown = driver.process_mode_clause("UDOP DOP29xx", ProcessMode.SIMULATION)
    assert unknown is not None and "states no process mode" in unknown, unknown


def test_the_shape_and_the_mode_are_separate_clauses_in_one_refusal() -> None:
    """D5: one clause per reason, each naming what was read — never one "unclean layout" sentence."""
    roles = manual_screen(dialog=True, popup=True)
    refusal = driver.layout_refusal(
        roles, caption=SIMULATION_CAPTION, expected_mode=ProcessMode.INSTRUMENT
    )
    assert refusal is not None
    # Three independent reasons, each present in its own words...
    assert "dialog" in refusal
    assert "popup" in refusal
    assert SIMULATION_CAPTION in refusal and "the process mode is 'simulation'" in refusal
    # ...plus the evidence line the counts live in.
    assert driver.layout_evidence(roles) in refusal
    # A screen that fails *only* the mode names the mode and says nothing about the layout: this is
    # the sentence that used to send an operator looking for a layout drift (24.2).
    mode_only = driver.layout_refusal(
        manual_screen(), caption=INSTRUMENT_CAPTION, expected_mode=ProcessMode.SIMULATION
    )
    assert mode_only is not None
    assert "the process mode is 'instrument'" in mode_only
    assert "layout" not in mode_only


# ------------------------------------------------------- rows 6/7 through a driver, not a clause


class StubScreen(driver.Win32Actuator):
    """A ``Win32Actuator`` whose window layer is a synthesised tree and a fixed caption.

    **Every input primitive is overridden.** `_click_hold` records the press it was asked for and
    raises instead of performing it, and `_send` refuses outright, so a regression in the gate
    under test cannot reach the driver's real gesture code — this file has to be safe to run on a
    machine with a live application in front of it.
    """

    def __init__(self, roles: dict, *, caption: str = INSTRUMENT_CAPTION) -> None:
        super().__init__()
        self._roles = roles
        self._caption = caption
        self.presses: list[tuple] = []

    def _resolve(self) -> dict:
        return self._roles

    def window_caption(self) -> str:
        return self._caption

    def _find_overlay(self, roles: dict | None = None):
        return None

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(("click", hwnd))
        raise AssertionError("the gate let a press through: no test double may press anything")

    def _send(self, *args: object, **kwargs: object) -> int:
        raise AssertionError("the gate let a message through")

    def _restore_cursor(self, position: tuple[int, int]) -> None:  # pragma: no cover - no cursor
        raise AssertionError("the gate moved the cursor")


def test_recording_refuses_the_other_process_and_names_the_caption() -> None:
    """Row 6 end to end: ``record_and_store`` on a screen captioned ``UDOP DOP3010.43``."""
    screen = StubScreen(manual_screen(), caption=INSTRUMENT_CAPTION)

    ok, reason = screen.try_record_and_store(
        "sw100-k1-161738", 1.0, Path("capture"),
        expected_mode=ProcessMode.SIMULATION,
    )

    assert ok is False
    assert INSTRUMENT_CAPTION in str(reason), reason
    assert "simulation" in str(reason) and "instrument" in str(reason), reason
    assert screen.presses == [], "nothing may be pressed when the mode is not the declared one"


def test_recording_refuses_an_empty_caption() -> None:
    """Row 7 end to end: a window that states nothing cannot prove the declaration."""
    screen = StubScreen(manual_screen(), caption="")

    ok, reason = screen.try_record_and_store(
        "sw100-k1-161738", 1.0, Path("capture"),
        expected_mode=ProcessMode.SIMULATION,
    )

    assert ok is False
    assert "nothing stated the mode" in str(reason), reason
    assert screen.presses == []


def test_a_screen_with_a_dialog_up_refuses_before_the_recording() -> None:
    """The shape half, through the same driver: the refusal comes before any press."""
    screen = StubScreen(manual_screen(dialog=True))

    ok, reason = screen.try_record_and_store(
        "sw100-k1-161738", 1.0, Path("capture"),
        expected_mode=ProcessMode.INSTRUMENT,
    )

    assert ok is False
    assert "dialog" in str(reason), reason
    assert screen.presses == []


def test_the_layout_note_is_a_diagnostic_that_does_not_refuse_on_the_mode() -> None:
    """24.4's "diagnostics do not refuse": ``layout_note()`` with no expectation reports the shape.

    ``acquire status`` calls it that way, and the mode is *reported* (the fingerprint's own
    ``process_mode``) rather than refused — a diagnostic that refused would be useless.
    """
    assert StubScreen(manual_screen()).layout_note() is None
    failed = StubScreen(manual_screen(dialog=True)).layout_note()
    assert failed is not None and "dialog" in failed


def test_the_runner_gate_refuses_the_other_process_before_it_writes_anything() -> None:
    """The runner's per-point gate (24.4), on its own fake: refused with nothing applied."""
    fake = FakeActuator(Path("capture"))
    fake.process_mode_note_value = (
        "the process mode is 'instrument' where this run was measured against 'simulation' "
        "(the caption read 'UDOP DOP3010.43')"
    )
    engine = runner.SweepRunner(
        fake,
        RecordSettings(name_prefix="sw100"),
        Path("capture"),
        expected_mode=ProcessMode.SIMULATION,
    )

    outcome = engine.run_point(point_for(1), 1.0)

    assert outcome.ok is False
    assert outcome.aborted is True
    assert "not the process mode this run was measured against" in str(outcome.reason)
    assert fake.applied is None, "the point wrote a parameter before the mode was checked"
    assert fake.expected_modes, "the expectation did not reach the gate"
    assert all(mode is ProcessMode.SIMULATION for mode in fake.expected_modes)


# ----------------------------------------------------------- D3/24.4, structurally: required


def test_every_record_path_requires_an_explicit_expectation() -> None:
    """The expectation is **required and keyword-only**, so no cycle can leave it implied.

    Asserted on the signatures rather than trusted: a default — of ``None`` or of a mode — is
    exactly the "inferred from what happens to be running" that §24.4 refuses.
    """
    paths = {
        "driver.Win32Actuator.record_and_store": driver.Win32Actuator.record_and_store,
        "driver.Win32Actuator.try_record_and_store": driver.Win32Actuator.try_record_and_store,
        "runner.SweepActuator.try_record_and_store": runner.SweepActuator.try_record_and_store,
        "runner.SweepRunner.__init__": runner.SweepRunner.__init__,
        "campaign.run_campaign": campaign.run_campaign,
        "live.point": live.point,
        "live.sweep": live.sweep,
    }
    for name, function in paths.items():
        parameter = inspect.signature(function).parameters["expected_mode"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert parameter.default is inspect.Parameter.empty, name


def test_the_diagnostics_did_not_gain_the_expectation() -> None:
    """A diagnostic that refused would be useless: ``status``, ``plan``, ``report``, ``decode``."""
    for function in (live.status, live.decode, campaign.compile_campaign):
        assert "expected_mode" not in inspect.signature(function).parameters, function.__name__


# ------------------------------------------------------------------ 24.6, row 11: the CLI


class _StatusSpy:
    """The live actuator the CLI's ``status`` reads: a fingerprint, and nothing else."""

    def __init__(self, mode: ProcessMode | None) -> None:
        self.mode = mode
        self.calls: list[tuple] = []

    def screen_fingerprint(self) -> ScreenFingerprint:
        self.calls.append(("screen_fingerprint",))
        return ScreenFingerprint(
            class_name=driver.MAIN_CLASS,
            hwnd=660124,
            rect=(-8, -8, 1928, 1058),
            maximized=True,
            screen=(1920, 1080),
            panels=4,
            visible_controls=44,
            strip=StripState(button_count=3),
            caption=INSTRUMENT_CAPTION if self.mode is ProcessMode.INSTRUMENT else SIMULATION_CAPTION,
            process_mode=self.mode,
            layout_shape_reasons=(),
            layout_evidence=driver.layout_evidence(manual_screen(controls=44)),
            cursor=(1268, 676),
            is_foreground=True,
        )


@pytest.mark.parametrize(
    ("label", "mode", "expected"),
    [
        ("the instrument", ProcessMode.INSTRUMENT, "instrument"),
        ("the simulator", ProcessMode.SIMULATION, "simulation"),
        ("a caption that states nothing", None, "None"),
    ],
)
def test_acquire_status_exits_zero_and_prints_the_mode_in_either_mode(
    label: str, mode: ProcessMode | None, expected: str, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """24.4's "diagnostics do not refuse": a mode is *reported*, whichever one is in front."""
    from udv_echo_process.cli import acquire_main

    spy = _StatusSpy(mode)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: spy)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["status"])

    assert exit_info.value.code == 0, label
    out = capsys.readouterr().out
    assert "process_mode" in out, out
    assert expected in out, out
    assert spy.calls == [("screen_fingerprint",)]


def test_acquire_status_also_prints_the_shape_verdict_and_the_counts(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The verdict the bring-up reads first, and the counts beside it as evidence (D4)."""
    from udv_echo_process.cli import acquire_main

    monkeypatch.setattr(
        live, "live_actuator", lambda *args, **kwargs: _StatusSpy(ProcessMode.INSTRUMENT)
    )

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["status", "--json"])

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["process_mode"] == "instrument"
    assert payload["visible_controls"] == 44
    assert payload["layout_shape_reasons"] == []
    assert "44 visible controls" in payload["layout_evidence"]


def test_the_displayed_views_are_the_known_ones() -> None:
    """A guard on the stubs above: they claim the tree the rows were written against."""
    roles = manual_screen()
    assert len(roles["panels"]) == 4
    assert roles["state"] == StripView.READY.value
    assert len(roles["params"]) == len(driver.PARAM_COLUMN_ORDER)
    assert len(assisted_screen()["panels"]) == 3
    assert assisted_screen()["params"] == {}
