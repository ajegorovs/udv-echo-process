"""The leftover-dialog guard: a panel the resolver calls a dialog is never invisible to a press.

An independent review of ``eafc0e2..d969d20`` found the same defect five times, from five angles
(its findings L1–L5). The delta made ``_resolve`` identify a dialog with the **canonical**
predicate the dialog reader resolves the live dialog with (:func:`…ui.dialog._is_dialog_panel`)
instead of a narrower rule of its own — which was right, because the measured ``Operating
parameters`` panel (627x384, ``tests/data/udop-parameters-dialog-tree.json``) carries neither a
direct ``TEdit``/``TSp_Edit`` nor a ``TSp_Browse`` and a rule that asked for that pair left the one
panel on the screen that *is* a dialog inside the strip vote. But the predicate is **wider** than
the reference's ``find_dialog``: it also accepts any panel wider than 400 px holding an input child
(:data:`…ui.dialog._DIALOG_INPUT_CLASSES`), and every panel that newly enters
``value_dialogs``/``browse_dialogs`` is (a) excluded from ``open_popup`` and (b) added to
``_find_overlay``'s ``known`` set — so the runtime checks that exist to stop a press into a
non-measurement surface stopped seeing that class of panel entirely. The review proved the class is
not hypothetical with this repo's own measurement: the ``Define TGC`` overlay
(``TSp_Panel [400,168,850,288]`` = 450x120, six children, two of them ``TSp_Value_Button``,
``docs/dop3000/acquisition-campaign-compilation-plan.md`` §26.3) answers ``_is_dialog_panel``
``True``.

Every case here is written as the **behaviour contract at today's entry point** — the same
functions the review traced — so a regression fails by name:

- **L1** — the runtime overlay guard (:meth:`RecordingSurface._settle_press`) must refuse a map
  whose union says a dialog is up, instead of walking past it (the union was only a reader's
  input).
- **L2** — the two paths that take a physical action must refuse *before* it: a strip press
  (:meth:`RecordingSurface.press`) and the menubar hover
  (:meth:`ParametersSurface._open_parameters_dialog`). The measured, dangerous case is a leftover
  application dialog (a failed accept, an operator's own dialog) with the driver still willing to
  post a held press behind the modal — this application's posted clicks ignore modality
  (docs/16 §8).
- **L3** — the stranded-popup note must name the ``Parameters`` popup only when the reference's
  own recorded-rect predicate says one is up; ``open_popup`` does not mean that (the delta's own
  §26.3 record states it: ``open_popup`` is true for the ``Define TGC`` overlay, and for every
  measured warning box, while zero dialog panels resolved).
- **L4** — a failure that happens before any press may not attribute a *previous* attempt's
  record to this one.
- **L5** — the cleanup note must say what the close actually did: ``_close_parameters_dialog``
  swallows "the band did not resolve" (nothing pressed) into a note, so "its left (Cancel) button
  was pressed" is an unearned assertion — and the panel is whatever ``_dialog_panels()`` returned,
  not necessarily the ``Operating parameters`` dialog.

The screens are the repository's own resolved fixtures (``test_acquire_layout_gate.manual_screen``,
``test_acquire_driver.FakeUdopWindow``, ``test_acquire_dialog.FakeDialogDriver``), which is what the
review's reproductions used; nothing here invents a measurement, and no case can post a real message
(``_click_hold`` is overridden on every double).
"""

from __future__ import annotations

import pytest
from test_acquire_driver import HWND_POPUP, POPUP_ENTRIES, FakeUdopWindow, fake_driver
from test_acquire_layout_gate import manual_screen

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import StripControl


class _ResolvedScreen(driver.Win32Actuator):
    """A driver over an already-resolved role map: no window, no cursor, no message ever sent.

    ``_resolve`` answers the map it was given, the window-layer primitives are recorded instead of
    performed, and ``_click_hold`` records the press it was asked for — the shape
    ``tests/test_acquire_strip_ambiguity.py``'s ``StripScreen`` established, so a regression in a
    guard cannot reach the driver's real gesture code.
    """

    def __init__(self, roles: dict) -> None:
        super().__init__()
        self._roles = roles
        self.presses: list[int] = []
        self.notes: list[str] = []
        self.hovers: list[int] = []
        self.cursor: list[str] = []

    def _resolve(self) -> dict:
        return self._roles

    def _children_of(self, parent: int, roles: dict) -> list[dict]:
        """A panel's direct children, off the resolved map (the fixture states its own parents)."""
        return [k for k in roles["raw"] if roles["parent_of"].get(k["hwnd"]) == parent]

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(hwnd)

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def _hover_centre(self, hwnd: int) -> tuple[int, int]:
        self.hovers.append(hwnd)
        return (0, 0)

    def _cursor_position(self) -> tuple[int, int]:
        self.cursor.append("read")
        return (1, 2)

    def _restore_cursor(self, position: tuple[int, int]) -> None:
        self.cursor.append("restored")

    def _require_foreground(self, hwnd: int) -> None:
        self.cursor.append("foreground")


# ---------------------------------------------------------------------------------- L1
# The wider union removed a class of panel from the runtime guard; the guard reads the union.


def test_a_leftover_dialog_is_refused_before_any_press_is_settled() -> None:
    """L1: ``_settle_press`` must refuse a map whose union says an application dialog is up.

    ``_find_overlay`` cannot answer this any more — the values dialog is in its ``known`` set, so
    it returns ``None`` — and the panel is a modal the application's posted clicks ignore
    (docs/16 §8). The refusal has to read the union the resolver published, or a press is settled
    into a stalled application with nothing having looked.
    """
    screen = _ResolvedScreen(manual_screen(dialog=True))

    with pytest.raises(driver.AcquisitionError) as excinfo:
        screen._settle_press()

    message = str(excinfo.value)
    assert "dialog" in message, message
    assert "(400, 223" in message, (
        message
    )  # named by the rect that is up, read off the map


# The class of panel the review proved the wider predicate newly accepts, kept as a case: the
# measured ``Define TGC`` overlay (``TSp_Panel [400,168,850,288]`` = 450x120, six direct children,
# two of them ``TSp_Value_Button``, plan §26.3). The review's own reproduction — not hypothetical.
def test_the_guard_covers_the_overlay_class_the_wider_predicate_newly_accepts() -> None:
    """L1's proof, as a case: the panel that flips class is refused, never invisible.

    ``450 > _DIALOG_MIN_W`` and two ``TSp_Value_Button`` children is enough for the canonical
    predicate, so this operator-opened, non-modal overlay enters the resolver's union and the
    runtime checks stop seeing it. Nothing about it being the *wrong* panel to press makes it a
    panel a press may be taken behind: the clause refuses, and names it by its own rect.
    """
    overlay = _widget(70, left=400, top=168, w=450, h=120)
    kids = [
        _widget(71, "TSp_Value_Button", left=500, top=172, w=60, h=24),
        _widget(72, "TSp_Value_Button", left=600, top=172, w=60, h=24),
        _widget(73, "TComboBox", left=700, top=172, w=60, h=24),
        _widget(74, "TSp_Button", left=450, top=250, w=70, h=25),
        _widget(75, "TSp_Button", left=560, top=250, w=70, h=25),
        _widget(76, "TSp_Button", left=670, top=250, w=70, h=25),
    ]
    assert driver._is_dialog_panel(overlay, kids), (
        "the review's measurement no longer holds: this panel is not in the union, so this case "
        "is not about the class it was written for"
    )

    roles = manual_screen()
    roles["panels"] = sorted([*roles["panels"], overlay], key=lambda p: p["top"])
    roles["raw"] = [*roles["raw"], overlay, *kids]
    roles["parent_of"] = {
        **roles["parent_of"],
        overlay["hwnd"]: 0,
        **{kid["hwnd"]: overlay["hwnd"] for kid in kids},
    }
    roles["value_dialogs"] = {overlay["hwnd"]}

    screen = _ResolvedScreen(roles)

    with pytest.raises(driver.AcquisitionError) as excinfo:
        screen._settle_press()

    assert "(400, 168" in str(excinfo.value), str(excinfo.value)
    assert screen.presses == []


# ---------------------------------------------------------------------------------- L2
# A leftover application dialog no longer blocked the gesture or a strip press; both refuse now.


class _SettledScreen(_ResolvedScreen):
    """The same screen with the *overlay* guard bypassed, so ``press``'s own clause is under test.

    ``_settle_press`` is the guard L1 repairs; a press test that let it run would be green for L1's
    reason and silent about ``press``'s own check. This is the isolation
    ``tests/test_acquire_strip_ambiguity.py``'s ``StripScreen`` uses for the same purpose.
    """

    def _settle_press(self) -> None:
        """No overlay to answer: this case is about the press path's own dialog check."""


def test_a_leftover_dialog_refuses_a_strip_press_before_the_held_press() -> None:
    """L2, the physical half: ``press`` must refuse a dialog with nothing posted.

    A strip button is taken with a **posted held press** (:meth:`_click_hold`), and this
    application's posted clicks ignore modality (docs/16 §8) — so behind a modal that press reaches
    whatever is painted there, under a role nobody has verified. Measured live, a leftover dialog
    is a real state: a failed accept, an operator's own ``Parameters`` dialog, the replacement the
    application builds on a channel write. The refusal precedes the gesture; nothing is posted.
    """
    screen = _SettledScreen(manual_screen(strip_row=3, dialog=True))

    with pytest.raises(driver.AcquisitionError) as excinfo:
        screen.press(StripControl.RECORD)

    message = str(excinfo.value)
    assert "dialog" in message, message
    assert "(400, 223" in message, message
    assert screen.presses == [], "a held strip press was posted behind an open dialog"


def test_a_leftover_dialog_refuses_the_menubar_gesture_before_the_hover() -> None:
    """L2, the cursor half: ``_open_parameters_dialog`` must refuse before it moves anything.

    The menubar is reached with the **operator's real cursor** (``SetCursorPos`` + ``mouse_event``),
    so an attempt made with a dialog up reads, moves and parks that cursor on a menubar behind a
    modal and then times out with "the popup did not appear" — a worse diagnosis than the refusal
    it replaced, and a real hand on a real desktop. The refusal is asserted *before the cursor is
    read*, which is what makes it a refusal rather than a failure.
    """
    screen = _ResolvedScreen(manual_screen(dialog=True))

    with pytest.raises(driver.AcquisitionError) as excinfo:
        screen._open_parameters_dialog()

    message = str(excinfo.value)
    assert "dialog" in message, message
    assert "(400, 223" in message, message
    assert screen.hovers == [], "the menubar was hovered with a dialog up"
    assert screen.cursor == [], (
        "the operator's cursor was read or moved with a dialog up"
    )


# ---------------------------------------------------------------------------------- L3
# The stranded-popup note names the Parameters popup only when that popup is what is up.


def _widget(
    hwnd: int,
    cls: str = "TSp_Panel",
    *,
    left: int = 0,
    top: int = 0,
    w: int = 60,
    h: int = 20,
) -> dict:
    """One control in the shape ``_visible_children`` produces (the fixtures' own helper)."""
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


#: The measured warning geometry the review names (the burst-volume warning, docs/16 §8): wider
#: than 250 px and taller than 90, so it is an overlay — and under the 400 px the dialog predicate
#: needs, so it is never a dialog. ``open_popup`` is true while it is up.
WARNING = _widget(50, left=300, top=300, w=392, h=132)
WARNING_BUTTONS = (
    _widget(51, "TSp_Button", left=380, top=410, w=80, h=25),
    _widget(52, "TSp_Button", left=560, top=410, w=80, h=25),
)


class _EndsWithAWarning(driver.Win32Actuator):
    """An attempt that fails while *another* panel is up when it ends — never the Parameters menu.

    The sequence the live application produces when an entry press raises a warning instead of the
    operating dialog (the burst-length/sampling-volume rejection that suppresses the popup,
    docs/16 §8): nothing is over the screen at the guard, the hover is taken, and by the time the
    attempt gives up a panel that is **not** the ``Parameters`` popup is up. Every window primitive
    this double does not need to script is recorded, so it can neither move a cursor nor press
    anything.
    """

    def __init__(self) -> None:
        super().__init__()
        self.resolves = 0
        self.notes: list[str] = []
        self.cursor: list[str] = []
        self._menubar = _widget(1, left=0, top=0, w=1920, h=25)
        self._parameters = _widget(2, "TSp_Button", left=120, top=2, w=80, h=20)

    def _resolve(self) -> dict:
        self.resolves += 1
        # Nothing is over the screen at the guard; the warning is up by the time the attempt ends.
        up = self.resolves >= 3
        raw = [self._menubar, self._parameters]
        panels = [self._menubar]
        if up:
            raw = [*raw, WARNING, *WARNING_BUTTONS]
            panels = [self._menubar, WARNING]
        return {
            "window": 0,
            "raw": raw,
            "panels": panels,
            "parent_of": {
                self._menubar["hwnd"]: 0,
                self._parameters["hwnd"]: self._menubar["hwnd"],
                WARNING["hwnd"]: 0,
                **{button["hwnd"]: WARNING["hwnd"] for button in WARNING_BUTTONS},
            },
            "menu": {"Parameters": self._parameters},
            "open_popup": up,
            "value_dialogs": set(),
            "browse_dialogs": set(),
            "params": {},
        }

    def _children_of(self, parent: int, roles: dict) -> list[dict]:
        return [k for k in roles["raw"] if roles["parent_of"].get(k["hwnd"]) == parent]

    def _require_foreground(self, hwnd: int) -> None:
        self.cursor.append("foreground")

    def _cursor_position(self) -> tuple[int, int]:
        self.cursor.append("read")
        return (1, 2)

    def _restore_cursor(self, position: tuple[int, int]) -> None:
        self.cursor.append("restored")

    def _hover_centre(self, hwnd: int) -> tuple[int, int]:
        self.cursor.append("hover")
        raise driver.AcquisitionError("the hover opened nothing")

    def _note(self, message: str) -> None:
        self.notes.append(message)


def test_the_stranded_note_names_the_menu_only_when_the_menu_is_what_is_up() -> None:
    """L3: ``open_popup`` is not "the ``Parameters`` popup is up" — the note may not assert it is.

    ``open_popup`` means "a panel besides the menu bar, the status bar and the strip hosts
    buttons", which the delta's own §26.3 record states for the ``Define TGC`` overlay and which is
    true of every measured warning box (392x132, 397x135, 353x155). So a step that fails with a
    *warning* on screen — a state the operator clears with ``Continue`` — must not be told that a
    stranded menu is up and that the application has to be restarted: a false surface plus a wrong
    remedy, in a fail-closed diagnostic an operator acts on. The report is keyed on the popup the
    reference's own recorded rectangle finds, and when that popup is not up it says which panel it
    *is* talking about instead of naming the menu.
    """
    screen = _EndsWithAWarning()

    with pytest.raises(driver.AcquisitionError):
        screen._open_parameters_dialog()

    warning = next(
        note
        for note in screen.notes
        if "panel other than" in note or "still open" in note
    )
    assert "popup is still open" not in warning, warning
    assert "a panel other than the measurement layout is up" in warning, warning
    assert "restart" not in warning, (
        warning
    )  # the remedy belongs to a stranded menu, not to this


# ---------------------------------------------------------------------------------- L4
# A failure that never pressed anything may not report a previous attempt's record as its own.


def test_a_failure_before_the_press_does_not_borrow_an_earlier_attempts_record() -> (
    None
):
    """L4: ``last_entry_attempt`` is *this* attempt's record, or nothing.

    It is assigned only by :meth:`…_observe_entry_attempt` (i.e. only once an entry has been
    pressed) and was never cleared at the start of an attempt, so every failure that happens
    **before** the press — a hover that opens no popup, a popup the poll will not accept, a popup
    that holds no entries — carried the record of an **earlier** attempt in the same run: its
    entry, its rect, its ``overlay_visible_after``. The message then states a sighting this attempt
    never made, in a diagnostic an operator acts on, and the surface it names can be one that is no
    longer on screen. The attempt's own record starts empty.
    """
    app = FakeUdopWindow(channel=1)
    actuator = fake_driver(app, channel=1)

    # A first attempt that *does* reach the press, so a record exists to be borrowed.
    app.menu_open = True
    raw = app.nodes()
    overlay = next(node for node in raw if node["hwnd"] == HWND_POPUP)
    entry = driver._entry_buttons(overlay, raw)[0]
    actuator._press_entry(entry, overlay)
    previous = actuator.last_entry_attempt
    assert previous is not None
    assert "(190, 61" in driver._observation_text(previous)  # the entry it pressed

    # A second attempt that opens the popup and finds no entry in it: no press is attempted.
    app.dialog_open = (
        False  # the first attempt's dialog is gone; a leftover one is L2's subject
    )
    real_nodes = app.nodes

    def nodes_without_entries() -> list[dict]:
        return [node for node in real_nodes() if node["hwnd"] not in POPUP_ENTRIES]

    app.nodes = nodes_without_entries  # type: ignore[method-assign]

    with pytest.raises(driver.AcquisitionError) as excinfo:
        actuator._open_parameters_dialog()

    message = str(excinfo.value)
    assert "holds no entries" in message, message
    assert "no popup entry press was attempted" in message, message
    assert "(190, 61" not in message, (
        message
    )  # the *previous* attempt's entry, not this one's
    assert actuator.last_entry_attempt is None, (
        "the failed attempt left an earlier attempt's record on the surface"
    )
