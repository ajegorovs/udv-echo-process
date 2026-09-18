"""The ``Parameters`` popup and the ``Operating parameters`` dialog composition.

Split out of the flat :mod:`udv_echo_process.acquire.driver` by Patch 4 — **verbatim**. This
surface holds the menubar hover that opens the popup, the popup's entry (the topmost one, by
screen order, never a lower entry), the structural identification of the dialog an entry opened,
the dialog read that carries the sound speed, the first gate and the burst length, the channel
selection and its verification from the dialog that the application keeps, the wrong-dialog close
and the read-only dialog table. No decision, message, order, timeout, hold or refusal changed:
this is a move, not a rewrite.

**Nothing here is proven on an instrument.** The menubar hover, the popup's entries, the dialog
and the channel read-back are *device-pending* (``docs/dop3000/device-verification.md``,
V2/V3/V4), and the cloud-only validation contract
(``docs/dop3000/acquisition-architecture.md`` §8) forbids claiming otherwise.

**It is a mixin**: the bodies are the ones ``Win32Actuator`` had, they reach their collaborators
through ``self`` (the cursor, the transport, the surface resolution and the overlay detection are
the facade's or the recording surface's), and ``acquire/driver.py`` composes this piece into the
one live class (``udop/session.py`` is that facade's compatibility name).

The timing knobs this surface's loops read — how long the dialog is given to fill, how long one
popup entry's press is given to produce a dialog, how long the application is given to replace
the dialog after a channel write, and the popup's own wait and poll cadence — moved here with
the loops: a constant lives with the code that reads it, which is the rule Patch 3 followed when
it left them in the flat module (its loops were there then). ``_POLL_S``, the package's poll
cadence, is the recording surface's and is imported from it. A test that shortens one of these
waits patches **this module** — the module that runs the loop and reads its own binding, never
the facade's re-exported copy of the value.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from udv_echo_process.acquire.actuator import (
    DIALOG_FIELD_ORDER,
    PRESS_HOLD_MS,
    DialogControl,
    ParamRole,
)
from udv_echo_process.acquire.config import (
    MAX_CHANNEL,
    MIN_CHANNEL,
)
from udv_echo_process.acquire.snapshot import (
    DialogParameters,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import _POLL_S
from udv_echo_process.acquire.ui.dialog import (
    _is_dialog_panel,
    dialog_channel_text,
    dialog_refusal,
    dialog_value_fields,
    text_at,
)
from udv_echo_process.acquire.ui.dialog import bottom_row as _bottom_row
from udv_echo_process.acquire.ui.layout import (
    observation_of,
    panel_mode,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_ENTRY,
    PARAMETERS_MENU,
    anchor_clause,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_LEFT as _OVERLAY_LEFT,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_MIN_H as _OVERLAY_MIN_H,
)
from udv_echo_process.acquire.ui.menu import entry_buttons as _entry_buttons
from udv_echo_process.acquire.ui.menu import observation_text as _observation_text

# --------------------------------------------------------------- the dialog's own timings


#: How long the dialog is given to state its values before the read gives up on it. Measured:
#: an application that has just started builds the table **empty** the first time it is opened
#: and states it on the next open, so a read that took the first empty answer as the answer would
#: record three unreadable facts on an instrument that states them perfectly well; a read that
#: waited forever would hang a live run on a dialog that is never going to fill. Two seconds is
#: several times the measured fill (the second open states everything immediately).
DIALOG_FILL_TIMEOUT_S = 2.0


#: How many popup entries are tried, and how long one entry's press is given to produce a
#: dialog before the next entry. Both are bounded: a misidentified overlay must never turn
#: the entry loop into a walk across the menubar. The measured overlay holds five entries
#: (screen tops 61, 95, 130, 165, 205) and the first is ``Operating parameters``, so the
#: bound costs nothing in practice — it exists so that a wrong overlay cannot be walked
#: through entry by entry. The dialog window is the reference's own
#: (``while time.time() - t0 < 8: time.sleep(0.5)`` — it polls at :data:`_MENU_POLL_S`), so
#: a slow dialog is never mistaken for no dialog.
_ENTRY_DIALOG_TIMEOUT_S = 8.0
#: How long to let the application replace its parameters dialog after a channel write
#: before reading the channel back from the one that is still up. The reference re-resolved
#: the dialog at the same point (`recon/41`); measured live 2026-09-17 the replacement is
#: already there when the write's own settle (``_COMBO_SETTLE_S``) is over, so this is a
#: ceiling, not a wait.
_DIALOG_REPLACE_S = 2.0

#: How long the popup, the dialog and a selection read-back are given, and the cadence
#: they are polled at — the reference recipe's own numbers (``while time.time() - t0 < 8:
#: time.sleep(0.5)``, ``recon/41_burst_sampling_volume.py``), not a longer window.
_MENU_TIMEOUT_S, _MENU_POLL_S = 8.0, 0.5

#: The gesture a popup entry is taken with, named in the diagnostics the caller reports:
#: the **posted held press** on the entry's own handle — the reference's own gesture
#: (``click_hold(entry_hwnd)``, ``recon/41_burst_sampling_volume.py``), which opened
#: ``Operating parameters``, read its fields, changed a combo and accepted, repeatedly.
#: It is not a cursor move and not a click, and there is no second gesture: a re-derived
#: alternative is what three fix cycles went into.
GESTURE_POSTED_PRESS = "posted held press"

# ------------------------------------------------------------------------ the dialog's helpers


def channel_items() -> tuple[str, ...]:
    """The channel combo's items, as the application shows them: ``'1'``..``'10'``.

    Derived from the one range (:data:`…config.MIN_CHANNEL`/:data:`…config.MAX_CHANNEL`),
    never listed again: a second copy of the channel list is exactly the parallel
    constant this module must not have.
    """
    return tuple(str(n) for n in range(MIN_CHANNEL, MAX_CHANNEL + 1))


def _descendants(roles: Mapping, root: int) -> list[dict]:
    """Every already-resolved control inside ``root``, breadth first.

    The tree comes from the resolution's own parent map, so this walks the *same*
    snapshot the roles were resolved from instead of re-enumerating the window.
    """
    by_parent: dict[int, list[dict]] = {}
    for node in roles["raw"]:
        by_parent.setdefault(roles["parent_of"].get(node["hwnd"], 0), []).append(node)
    out: list[dict] = []
    queue = list(by_parent.get(root, []))
    while queue:
        node = queue.pop(0)
        out.append(node)
        queue.extend(by_parent.get(node["hwnd"], []))
    return out


class ParametersSurface:
    """The ``Parameters`` interaction of :class:`~udv_echo_process.acquire.udop.session.Win32Actuator`.

    The Parameters surface of the live actuator: the menubar anchor's real-cursor hover, the
    popup and its entries, the dialog an entry opened, the table the dialog states, and the
    measurement channel's selection and read-back. Moved out of the flat actuator verbatim by
    Patch 4; see this module's docstring for what is and is not claimed.
    """

    def _open_parameters_dialog(self) -> dict:
        """Open ``Parameters → Operating parameters`` and return the dialog's panel.

        The dialog is a modal overlay reached through the menubar — not a sidebar
        control, and not a top-level window (``EnumWindows`` finds nothing: the app's
        dialogs are child panels, docs/16 §6).

        Nothing on this path matches a control by its caption, and nothing can: this
        application's widgets are caption-less (``GetWindowText`` is empty for all of them
        — the live read of the open popup showed the overlay panel and its five entries
        with empty captions), which is why a title lookup found no entry at all. What
        identifies each thing instead:

        1. the **overlay** is the panel that became *visible* on the hover
           (:meth:`_poll_parameters_overlay`, with the reference's ``left == 169 and
           h > 120`` rect as the fallback when the appearance diff is ambiguous). The panel
           this application pre-creates and hides is not an overlay: presence is not
           visibility, and a popup whose panel reports ``IsWindowVisible == False`` is
           refused by name rather than pressed into (:meth:`_require_visible_popup`);
        2. the **entries** are the ``TSp_Button`` widgets lying inside that overlay,
           ordered by screen ``top`` — the first is ``Operating parameters``
           (:func:`_entry_buttons`; enumeration order is not screen order) — and an entry
           is taken with the **posted held press on its own handle** (:meth:`_press_entry`,
           the reference's own gesture). Every attempt records what the application did
           (whether the overlay was visible, whether the popup closed, any panel that
           appeared, its rect and its top-level child classes —
           :attr:`last_entry_attempt`) and the failure below reports that record;
        3. the **dialog** is found **structurally** (:meth:`_dialog_panels`: a panel
           wider than :data:`_DIALOG_MIN_W` that is not the parameter column and is full
           of controls — the reference's own ``find_dialog`` predicate), and among dialogs
           the operating one is the one holding the **channel combo**
           (:meth:`_channel_combo` — a ``TComboBox`` listing ``'1'``..``'10'``, wherever
           the dialog nests it). An entry whose dialog does not hold it is tried past:
           that dialog is closed with its **left** button
           (:meth:`_close_wrong_dialog`, never its Accept, which on a parameters dialog is
           what would commit whatever it holds), and the next entry by screen order is
           pressed. A bounded number of entries is tried; when none yields the operating
           dialog the failure is raised by name.

        The menu is opened by **hovering the menubar button with the operator's real
        cursor** (:meth:`_hover_centre`): this application's menubar ignores posted
        messages — a posted ``WM_MOUSEMOVE`` opened nothing and so did a posted press
        held for :data:`…actuator.PRESS_HOLD_MS` (two live runs, both aborting safely) —
        while the same button opened its menu under a real cursor in
        ``recon/41_burst_sampling_volume.py``. Nothing posts a message to the menubar any
        more. The cursor stays on the button through the poll for the popup — a
        hover-opened popup can be dismissed by moving the cursor off the menubar — and is
        put back once the entry has been taken, or the attempt has failed
        (:meth:`_restore_cursor`). Both moves go through :meth:`_move_real_cursor`, which
        clears the clip this application sets on an open popup: a clipped restore is what
        put a live run's cursor in the menu's bottom-left corner, and a clipped hover is
        what made the button unreachable at ``(204, 40)``.
        ``allow_real_input=False`` refuses this step by name instead — never falling
        back to the posted press, which is known not to open this menu.
        """
        if not self._allow_real_input:
            raise AcquisitionError(
                f"the {PARAMETERS_MENU!r} menu cannot be opened without real input: this "
                "application's menubar ignores posted messages, so its button is hovered "
                "with the operator's real cursor (SetCursorPos + mouse_event) and there "
                "is deliberately no posted fallback — allow_real_input=False, so nothing "
                "was moved on this unattended or locked desktop"
            )
        roles = self._resolve()
        if roles["open_popup"]:
            raise AcquisitionError(
                "a menu popup is already open; the entry press would be unreliable — "
                "close it from the UI, this driver never WM_CLOSEs a popup"
            )
        menu = (roles.get("menu") or {}).get(PARAMETERS_MENU)
        if menu is None:
            # The anchor is proven where it is *resolved* and nowhere else: ``_resolve`` publishes
            # no binding for a bar the signature cannot show, so this method has nothing to hover
            # (ledger B03, and the anchor rule itself is ``ui/menu.py``'s
            # :func:`…ui.menu.anchor_clause`). Naming the pure clause here is not a second rule —
            # it is the diagnosis, and it is produced *before* the cursor is read, moved and
            # parked on a menubar button.
            clause = anchor_clause(observation_of(roles))
            raise AcquisitionError(
                f"no {PARAMETERS_MENU!r} button in the menubar"
                + (f": {clause}" if clause else "")
            )
        # The hover's precondition, asserted before the cursor is moved: this application
        # ignores a hover while it is inactive, so a window in front turns the one gesture
        # that opens this menu into a no-op that reads like a broken gesture (measured
        # live 2026-09-17: a console window in front, no popup, nothing pressed).
        self._require_foreground(roles["window"])
        saved = self._cursor_position()
        sidebar_before = bool(roles.get("params"))
        try:
            # The snapshot is taken *before* this hover, so "visible after, not before" is
            # a statement about *this* attempt: a popup panel a previous attempt left
            # hidden is not in the set, and one the app reuses without hiding it falls back
            # to the recorded rect below.
            before = self._panel_map()
            self._hover_centre(menu["hwnd"])  # the popup opens on this real hover
            overlay = self._poll_parameters_overlay(before)
            entries = _entry_buttons(overlay, self._resolve()["raw"])
            if not entries:
                raise AcquisitionError(
                    f"the {PARAMETERS_MENU!r} popup holds no entries to press; the entry is "
                    "the ``TSp_Button`` inside the overlay, ordered by screen top — "
                    f"{_observation_text(self.last_entry_attempt)}"
                )
            # **The topmost entry, and no other.** It is ``Operating parameters``; the ones
            # below it are ``Default parameters``, ``Save parameters``, ``Recall
            # parameters`` and the trigger parameters — and pressing *Default parameters*
            # **selects the assisted mode** (manual doc 04: "the default parameters select
            # the assisted mode"), which this application switches on silently while the
            # popup is up. A retry that walks down the popup therefore changes the
            # instrument's state in order to recover from a transient failure: the stored
            # `assisted Mode` word read 0 in every file up to 19:01 and 1 by 21:26, in a
            # window whose only presses were this driver's. The reference never pressed
            # more than the entry it meant (`recon/41_burst_sampling_volume.py`).
            entry = entries[0]
            panel = self._press_entry(entry, overlay)
            if panel is None:
                raise AcquisitionError(
                    f"the topmost {PARAMETERS_MENU!r} popup entry at {entry['rect'][:2]} "
                    "opened no dialog, and no lower entry is pressed on purpose: the second "
                    "one is 'Default parameters', which selects the assisted mode — "
                    f"{_observation_text(self.last_entry_attempt)}"
                )
            try:
                self._channel_combo(panel)
            except AcquisitionError as exc:
                self._close_wrong_dialog(panel)
                raise AcquisitionError(
                    f"the topmost {PARAMETERS_MENU!r} popup entry at {entry['rect'][:2]} "
                    f"did not open the {PARAMETERS_ENTRY!r} dialog (the one holding the "
                    f"channel combo): {exc} — "
                    f"{_observation_text(self.last_entry_attempt)}"
                ) from exc
            self._assert_assisted_unchanged(sidebar_before)
            return panel
        finally:
            # The menu has been used (or the attempt is over, hover or press): the
            # operator's cursor goes back, so no path leaves it parked on the menubar.
            self._restore_cursor(saved)

    def _assert_assisted_unchanged(self, sidebar_before: bool) -> None:
        """Refuse when this interaction switched the assisted mode **on** by itself.

        The mode is the application's own state and this driver never sets it — but a press
        one entry low in the ``Parameters`` popup does: the second entry is ``Default
        parameters`` and the default parameters select the assisted mode. The visible
        consequence is that the sidebar parameter column goes away (43 visible controls in 4
        panels become 21 in 3) and every parameter write loses its target, so the point is
        already lost: this raises *now*, naming the cause, instead of a sweep failing later
        with a message about a missing field.

        A mode that was already on when the interaction started is not this driver's doing
        and is not raised here — :meth:`ensure_channel` records which mode the channel's
        panel came up in, and a point on an assisted channel is refused by the parameter
        write itself, with the mode named.
        """
        if not sidebar_before:
            return
        if self._resolve().get("params"):
            return
        raise AcquisitionError(
            "the assisted mode was switched ON during this menu interaction: the sidebar "
            "parameter column is gone, which is what this application does when the assisted "
            "mode is on (43 visible controls in 4 panels -> 21 in 3). The second entry of the "
            f"{PARAMETERS_MENU!r} popup is 'Default parameters', and the manual's rule is "
            "'the default parameters select the assisted mode' — while the application "
            "highlights that very entry by itself, so any press one entry low turns the mode "
            "on silently. Nothing has been written to the instrument by this driver, which "
            "does not leave the assisted mode either: its own toggle is the application's "
            "Preference menu, so an operator has to clear it before the point can be made"
        )

    def _close_parameters_dialog(self, panel: dict) -> None:
        """Close the dialog with its LEFT button (``Cancel``), never a window close.

        The app confines the cursor to its dialogs, so an open one traps the operator
        (docs/16 §6); a panel whose bottom row cannot be resolved is noted instead of
        raising, so a failed point is never masked by a failed cleanup.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
        except AcquisitionError as exc:
            self._note(f"the {PARAMETERS_ENTRY!r} dialog could not be closed: {exc}")

    def ensure_channel(self) -> int:
        """Make the application measure on the configured channel, and prove it took.

        Called before **every** point, because the channel is what decides which
        channel's block the stored file carries — and a point recorded on the wrong
        channel decodes as a perfectly valid point that is not the point (docs/16 §12,
        the channel trap). The order is the load-bearing part:

        1. open ``Parameters → Operating parameters`` — the menubar button is
           **hovered with the operator's real cursor** (:meth:`_hover_centre`: this
           application's menubar answers nothing posted), the popup is identified as the
           panel that became **visible** on that hover, its caption-less entries are taken
           in **screen order** (the first is ``Operating parameters``) with a **posted held
           press on the entry's own handle** — the reference's own gesture
           (``recon/41_burst_sampling_volume.py``), and the one step in this cycle that
           needs no cursor at all — and the cursor is put back once an entry has been
           taken, clearing the clip the open popup sets first so the restore is not
           clamped into it. The dialog an entry opened is identified **structurally**, not
           by a caption and not by the channel combo: a dialog that does not hold the
           channel combo is closed with its LEFT button and the next entry in screen order
           is tried;
        2. find the channel combo *structurally* (see :meth:`_channel_combo`);
        3. read the channel back from the dialog; if it is not the configured one,
           write the selection (``CB_SETCURSEL`` + ``CBN_SELCHANGE``, no Enter) and
           read it back **again** — a combo write can silently not apply (docs/16 §2);
        4. accept the dialog, then re-open it and read the selection again: only the
           re-opened dialog shows what the *application* kept, not what the control
           believes;
        5. close it with the left button.

        Returns the verified channel. Any step that cannot be verified raises
        :class:`AcquisitionError` naming what was asked for and what the dialog showed,
        which fails the point — recording on an unverified channel is the worst outcome
        this driver can produce.
        """
        wanted = self._channel_setting
        panel = self._open_parameters_dialog()
        try:
            combo, parent = self._channel_combo(panel)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                self._note(
                    f"the {PARAMETERS_ENTRY!r} dialog reads channel index {index} "
                    f"({text!r}), not channel {wanted.channel} (combo index "
                    f"{wanted.combo_index}): writing the selection"
                )
                self._combo_select(combo["hwnd"], wanted.combo_index, parent)
                # **Re-resolve the dialog here.** Measured live 2026-09-17: changing the
                # channel makes this application *replace* its parameters dialog — channel 2
                # is in assisted mode, so the write closed `Operating parameters`
                # (627x384, 21 children) and opened `Assisted mode parameters for channel 2`
                # (511x384, 14 children, a block slider) — and every handle taken before the
                # write is then dead. The reference re-resolved at exactly this point
                # (`find_dialog(resolve()) or dlg`, `recon/41_burst_sampling_volume.py`); the
                # port kept the old panel and pressed a window that no longer existed, which
                # left the new dialog on the operator's screen with nothing able to close it.
                replaced = self._poll_dialog(_DIALOG_REPLACE_S)
                if replaced is not None:
                    if replaced["hwnd"] != panel["hwnd"]:
                        self._note(
                            "the application replaced its parameters dialog after the "
                            f"write: {panel['rect'][:2]} -> {replaced['rect'][:2]} — every "
                            "handle taken before the write is dead, so the read-back and the "
                            "accept use the re-resolved panel"
                        )
                    panel = replaced
                mode = panel_mode(
                    panel, self._children_of(panel["hwnd"], self._resolve())
                )
                self._note(
                    f"channel {wanted.channel}'s parameters panel is the {mode!r} one "
                    f"(application's own statement, read from the panel it built)"
                )
                combo, _parent = self._channel_combo(panel)
                index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the measurement channel was not selected: channel {wanted.channel} "
                    f"(combo index {wanted.combo_index}) was requested in the "
                    f"{PARAMETERS_ENTRY!r} dialog, but the dialog reads back index {index} "
                    f"({text!r}) — recording here would store another channel's block"
                )
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.CONFIRM)  # accept the dialog
        except BaseException:
            # Re-resolved, not the handle held: the application may have replaced the dialog
            # under us (it does on a channel write), and a close on a dead handle presses
            # nothing and leaves the dialog on the operator's screen.
            self._close_any_dialog()
            raise
        confirmed = self._open_parameters_dialog()
        try:
            combo, _parent = self._channel_combo(confirmed)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the application did not keep the measurement channel: channel "
                    f"{wanted.channel} (combo index {wanted.combo_index}) was selected and "
                    f"accepted, but a re-opened {PARAMETERS_ENTRY!r} dialog reads back index "
                    f"{index} ({text!r})"
                )
        finally:
            self._close_any_dialog()
        return wanted.channel

    def read_dialog_parameters(self) -> DialogParameters:
        """Read the sound speed, the first gate and the burst length off the ``Parameters`` dialog.

        **Which surface.** These three facts are the ones no measurement-screen surface states:
        they are not parameter-column roles (the column is the surface a *point* writes, and a
        point never writes them), they live in the ``Operating parameters`` dialog only, and they
        are stated **for the channel that dialog is showing**. So the read has to open the dialog
        and has to say whose parameters it described — both of which are carried in the reading
        (:class:`~udv_echo_process.acquire.snapshot.DialogParameters`).

        **How.** The routing step's own gesture: hover the menubar button with the operator's real
        cursor and press the topmost entry (:meth:`_open_parameters_dialog`), read the table, and
        close the dialog with its own left button in a ``finally`` — re-resolved, because the panel
        this read opened can be gone by the time the read ends (:meth:`_close_any_dialog`), and
        reported rather than assumed if it cannot be taken down. The close is not housekeeping:
        an open dialog confines the cursor to itself and traps the operator, and **Escape closes
        nothing in this application** (reported 2026-09-18, and noted before).

        **What is checked before any value is believed.** A field's identity here is a *position*
        (:data:`DIALOG_FIELD_ORDER`), so a dialog that is not the table those bindings were
        measured against would hand the compile a plausible wrong fact — the one failure a
        pre-run check must not have. Three checks stand between the two:

        * the table **filled**: an application that has just started builds this table *empty* the
          first time the dialog is opened and states it on the next open (measured 2026-09-18 —
          the first-open table read 2 stating controls where the second read 22), so the read polls
          rather than recording an empty dialog as a filled one;
        * the table's **shape** is the measured one (:data:`DIALOG_COLUMN_ROWS`), and it states
          the channel it is showing in its header combo;
        * every **anchor** (:data:`DIALOG_ANCHORS`) reads the same text the measurement screen
          reads, which is what makes the positions evidence rather than habit.

        **What it does when it refuses.** It returns an unreadable reading whose reason names what
        happened — a dialog that never filled, a shape that is not this table, an anchor that
        disagrees with the screen, a header that does not resolve, a gesture that failed (noted in
        the run log as well). It never raises for those, and it never invents a value: the facts
        stay ``unreadable`` in the snapshot, and the compile refuses on them.
        """
        try:
            panel = self._open_parameters_dialog()
        except AcquisitionError as exc:
            self._note(f"the {PARAMETERS_ENTRY!r} dialog could not be opened for a read: {exc}")
            return DialogParameters(
                reason=f"the {PARAMETERS_ENTRY!r} dialog could not be opened: {exc}"
            )
        try:
            fields = self._poll_dialog_fields(panel)
            channel = self._dialog_channel_text(self._descendants_of(panel["hwnd"]), fields)
            refusal = self._dialog_refusal(fields, channel)
            if refusal:
                return DialogParameters(channel=channel, reason=refusal)
            return DialogParameters(
                channel=channel,
                fields=tuple(
                    (field.value, self._text_at(fields, column, row))
                    for field, column, row in DIALOG_FIELD_ORDER
                ),
            )
        finally:
            # **Re-resolved, not the handle this read opened.** The application can take that panel
            # away while the table is being read — it replaces its parameters dialog outright when
            # a mode changes (measured live 2026-09-17, and again on a channel write) — and every
            # handle taken before the replacement is dead: a close aimed at it presses nothing and
            # leaves the **fresh** modal on the operator's screen, where Escape closes nothing and
            # the cursor is confined to the dialog's own rectangle. The close is not housekeeping
            # (an open dialog traps the operator), so it goes through the path that closes whatever
            # is *up* — re-resolved — and that reports a dialog it could not take down instead of
            # returning as if the screen were clear.
            self._close_any_dialog()

    def _poll_dialog_fields(self, panel: dict) -> list[dict[str, object]]:
        """The dialog's value table, re-read until it states something or the wait runs out.

        The application fills this table a moment after the dialog appears — and *not at all* the
        first time it is opened on a freshly started application (measured). Reading it once, the
        moment it appears, is therefore the difference between three read facts and three facts
        recorded as unreadable on an instrument that states them perfectly well.
        """
        deadline = time.monotonic() + DIALOG_FILL_TIMEOUT_S
        while True:
            fields = dialog_value_fields(self._descendants_of(panel["hwnd"]), self._get_text)
            if any(row["value"] for row in fields) or time.monotonic() >= deadline:
                return fields
            time.sleep(_POLL_S)

    def _text_at(self, fields: Sequence[Mapping], column: int, row: int) -> str:
        """The text stated at ``(column, row)`` of the dialog's table, or ``\"\"``.

        The lookup itself is ``ui/dialog.py``'s (:func:`…ui.dialog.text_at`); the read is this
        method's, because it is the one that needs a window.
        """
        return text_at(fields, column, row, self._get_text)

    def _dialog_channel_text(self, kids: Sequence[Mapping], fields: Sequence[Mapping]) -> str:
        """The channel the dialog is showing, read from its header combo.

        The header is the combo that is **not** a table row (measured: it sits at the dialog's top,
        ``top`` 373 against the table's 443). It is read because the dialog — not the caller — is
        the surface that decides whose parameters are shown: a reading that did not carry it would
        let a compile compare one channel's sound speed against another channel's run, which is the
        channel trap this driver already refuses to make when it stores a block (docs/16 §12).

        Which combo that is, is ``ui/dialog.py``'s rule (:func:`…ui.dialog.dialog_channel_text`);
        the read itself is this method's.
        """
        return dialog_channel_text(kids, fields, self._get_text)

    def _dialog_refusal(self, fields: Sequence[Mapping], channel: str) -> str:
        """Why no dialog-only fact may be believed, or ``\"\"`` when the reading may be trusted.

        Every refusal is written out in full rather than summarised: the reason lands in a run
        record read by someone with no instrument in front of them, and "the dialog did not read"
        would leave them unable to tell a stale binding from an application that was busy.

        The three checks themselves — the table filled, the table's shape, and every anchor reading
        the same text the screen reads — are ``ui/dialog.py``'s
        (:func:`…ui.dialog.dialog_refusal`); what stays here is the two reads that need a window:
        the dialog's own text (``self._get_text``) and the measurement screen's
        (:meth:`_screen_anchor_text`). ``DIALOG_FILL_TIMEOUT_S`` is read here, at call time, so the
        reason a reading gives always names the wait this run actually performed.
        """
        return dialog_refusal(
            fields,
            channel,
            read_text=self._get_text,
            screen_text=self._screen_anchor_text,
            timeout_s=DIALOG_FILL_TIMEOUT_S,
        )

    def _screen_anchor_text(self, role: ParamRole) -> str:
        """The measurement screen's own text for an anchor role, or ``\"\"`` when it states none.

        The other half of an anchor check: the dialog's value at the same ``(column, row)`` has to
        be the text the parameter column itself reads for that role, which is what makes a
        positional binding evidence rather than habit (``ui/dialog.py``'s
        :func:`…ui.dialog.dialog_refusal`, :data:`…actuator.DIALOG_ANCHORS`).
        """
        screen = (self._resolve().get("params") or {}).get(role)
        return "" if screen is None else self._get_text(screen["edit"]["hwnd"])

    def _close_any_dialog(self) -> None:
        """Close whatever dialog is up, re-resolving it first — never a stale handle.

        Written because a live failure *left the dialog on the operator's screen* (measured
        2026-09-17, twice): the application had replaced the dialog on a channel write, the
        driver's panel handle was dead, and its close attempt therefore pressed nothing and
        raised "0 buttons in its bottom band". A close path that can itself fail on a stale
        handle is not a close path, so this resolves the panel afresh, presses the safe end,
        and reports — rather than raising — when even that cannot be done.

        And it **ends by asking the screen whether the dialog is gone**, because the close it
        calls never raises: a caller that took the attempt for the outcome would report a clean
        finish with a modal still up. A dialog that survives every attempt is named by its own
        rect, together with the remedy — nothing else on it is pressed and ``WM_CLOSE`` is never
        sent, this driver having no surface it is entitled to guess at.
        """
        for _attempt in range(2):
            found = self._dialog_panels()
            if not found:
                return
            self._close_parameters_dialog(found[0])
        # **Whether the dialog is gone is asked of the screen, never assumed from the presses.**
        # ``_close_parameters_dialog`` notes a band it cannot resolve instead of raising (a failed
        # cleanup must never mask the failure it is cleaning up after), so two attempts that both
        # pressed a dead handle — the panel the application replaced, or a band that no longer
        # holds the pair — end here with the modal still up. A dialog left open confines the
        # cursor to its own rectangle and traps the operator (docs/16 §6), and **Escape closes
        # nothing in this application**, so the state is not one a later step can recover from:
        # it is reported by its own rect, with nothing else pressed on it — this driver never
        # guesses a surface — and with the remedy named.
        remaining = self._dialog_panels()
        if not remaining:
            return
        rect = tuple(remaining[0]["rect"])
        self._note(
            f"the {PARAMETERS_ENTRY!r} dialog is still open at {rect[:2]} (rect {rect}) after "
            "both close attempts: its left (Cancel) button was pressed and the dialog did not go "
            "away, and nothing else on it is pressed — this driver never guesses a surface. An "
            "open dialog confines the cursor to its own rectangle and blocks the application, so "
            "an operator has to close it from the UI, or the application has to be restarted, "
            "before this point is retried"
        )

    def _panel_map(self, roles: Mapping | None = None) -> dict[int, dict]:
        """Every visible ``TSp_Panel`` right now, by handle.

        The panels are re-read, never remembered: the popup is a panel the application
        shows and hides, so the snapshot taken before the hover is only worth anything
        compared with a *fresh* one. Nothing here is keyed on a caption — these widgets
        have none (see the module docstring).
        """
        roles = self._resolve() if roles is None else roles
        return {k["hwnd"]: k for k in roles["raw"] if k["cls"] == "TSp_Panel"}

    def _poll_parameters_overlay(self, before: Mapping[int, dict]) -> dict:
        """The ``Parameters`` popup overlay: the panel that appeared on the hover.

        Identified by **appearance**, because a caption can never identify it: every
        caption-less ``TSp_*`` widget in this application answers ``GetWindowText`` with
        the empty string, so the overlay is the ``TSp_Panel`` that is visible now and was
        **not** in the ``before`` snapshot taken just before the menubar was hovered.

        When the diff is ambiguous — more than one new panel, or none yet — the reference
        recipe's own predicate decides (``recon/41_burst_sampling_volume.py``:
        ``left == 169 and h > 120``, the panel it read live at ``(169, 55, 401, 250)``;
        the popup is reused or re-shown by some menus, and then it was visible before the
        second hover and the diff alone would find nothing). Polled, never assumed: the
        recipe waited the same way and the popup takes a moment to paint. A popup that
        has shown neither within :data:`_MENU_TIMEOUT_S` is reported by name — and a panel
        that is in the tree but **hidden** is named in that failure too, because the
        overlay this application pre-creates is exactly that (:func:`_is_visible`): an
        accepted-but-hidden panel is a menu that is not on screen.
        """
        deadline = time.monotonic() + _MENU_TIMEOUT_S
        while True:
            panels = self._panel_map()
            # The reference's own predicate first (`recon/41`, verbatim): the panel the
            # application painted for this menu is the visible one at `left == 169` whose
            # height exceeds 120 (live: `(169, 55, 401, 250)`). Heeding it first is what the
            # handoff asks for — the appearance diff below is this driver's addition, and an
            # addition should never outrank the proven rule.
            recorded = sorted(
                (
                    p
                    for p in panels.values()
                    if p["left"] == _OVERLAY_LEFT
                    and p["h"] > _OVERLAY_MIN_H
                    and self._is_visible(p["hwnd"])
                ),
                key=lambda p: p["top"],
            )
            if recorded:
                return recorded[0]
            # Fallback for an overlay this application paints somewhere else (a different
            # theme or scale): the panel that appeared on the hover, when exactly one did.
            fresh = [
                p
                for hwnd, p in panels.items()
                if hwnd not in before and self._is_visible(p["hwnd"])
            ]
            if len(fresh) == 1:
                return fresh[0]
            if time.monotonic() >= deadline:
                break
            time.sleep(_MENU_POLL_S)
        hidden = self._hidden_panels()
        named = (
            "; the panels present in the tree with IsWindowVisible == False are "
            + ", ".join(f"{p['rect']}" for p in hidden[:4])
            + " — a pre-created, unpainted overlay is not an open menu, so nothing is "
            "pressed into it"
            if hidden
            else ""
        )
        raise AcquisitionError(
            f"the {PARAMETERS_MENU!r} popup did not appear within {_MENU_TIMEOUT_S:.0f} s "
            f"of its hover, so no {PARAMETERS_ENTRY!r} entry could be pressed: no *visible* "
            "panel appeared that was not visible before the hover, and none is a visible "
            f"panel matching the overlay the live application paints{named}"
        )

    def _dialog_panels(self, roles: Mapping | None = None) -> list[dict]:
        """The panels that are modal dialogs, fullest first — the reference's rule.

        A dialog is identified **structurally** (:func:`_is_dialog_panel`): a panel that
        is not the sidebar parameter column — that exclusion is by identity, the resolved
        ``left_panel``, never by position, because the column owns ``TSp_Value_Button``
        fields of its own — wider than :data:`_DIALOG_MIN_W`, and holding input controls
        of its own or at least :data:`_DIALOG_MIN_CHILDREN` direct children or a
        ``TSp_Browse``. This is what ``recon/41_burst_sampling_volume.py`` polled for, and
        it deliberately does **not** require the channel combo: which dialog *this* is, is
        the caller's question, and a dialog whose combo cannot be found must not be
        reported as "no dialog opened".

        Fullest first, the way the reference chose when several matched
        (``len(kids) > len(children(best, roles))``), then widest, so a warning strip
        cannot win over a real dialog.
        """
        roles = self._resolve() if roles is None else roles
        left = roles.get("left_panel")
        out: list[dict] = []
        for panel in roles.get("panels") or []:
            if left is not None and panel["hwnd"] == left["hwnd"]:
                continue
            kids = self._children_of(panel["hwnd"], roles)
            if _is_dialog_panel(panel, kids):
                out.append(panel)
        return sorted(
            out,
            key=lambda p: (
                -len(self._children_of(p["hwnd"], roles)),
                -p["w"],
                p["top"],
            ),
        )

    def _poll_dialog(self, timeout_s: float) -> dict | None:
        """The dialog panel that is up, or ``None`` when none appeared in ``timeout_s``.

        Found by structure (:meth:`_dialog_panels`), never by a caption and never by the
        channel combo — the live dialog's channel combo sits in its header, and a rule
        that demanded the combo inside a value field rejected a correctly opened dialog.
        ``None`` is a fact to report, not to paper over: the caller names it and tries the
        next entry by screen order.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            panels = self._dialog_panels()
            if panels:
                return panels[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(_MENU_POLL_S)

    def _panel_observation(self, panel: dict, roles: dict) -> dict:
        """One panel as the entry diagnostics report it: handle, rect, child classes.

        Classes only, never a caption: this application's widgets carry none (see the
        module docstring), so the classes of the panel's *direct* children are the
        structural fingerprint a live run can be read back against.
        """
        return {
            "hwnd": panel["hwnd"],
            "rect": tuple(panel["rect"]),
            "classes": tuple(
                sorted({k["cls"] for k in self._children_of(panel["hwnd"], roles)})
            ),
        }

    def _pressed_state(self, entry: dict, overlay: dict) -> dict:
        """What the overlay offered **at the moment of the press** — never read after it.

        A press closes the popup, so its entries are gone from the visible tree by the time
        the outcome is observed: a record that read them afterwards said "the overlay was
        NOT visible and held 0 entries" on a press that had in fact opened the operating
        dialog (measured live 2026-09-17). These four facts therefore come from *before* the
        gesture; the after-state is :attr:`…last_entry_attempt`'s ``overlay_closed`` and
        ``overlay_visible_after``.
        """
        roles = self._resolve()
        entries = _entry_buttons(overlay, roles["raw"])
        return {
            "overlay_visible": self._is_visible(overlay["hwnd"]),
            "overlay_items": len(entries),
            "entry_tops": [e["rect"][1] for e in entries],
            "entry_caption": self._get_text(entry["hwnd"]),
        }

    def _observe_entry_attempt(
        self,
        entry: dict,
        overlay: dict,
        before: set[int],
        gesture: str,
        panel: dict | None,
        *,
        gesture_failed: bool = False,
        pressed: Mapping | None = None,
    ) -> dict:
        """Record what the application actually did on one popup-entry press.

        Mechanical on purpose — was the overlay *visible*, did the popup close, did a panel
        appear that was not up before the press, and what does it hold — because the live
        run's failure was *not* that the driver pressed the wrong thing: it was that the
        press did nothing at all and the run could not say what the application did
        instead. The record is kept on :attr:`last_entry_attempt` whether the press worked
        or not, and it is what the caller puts in its failure message.

        ``pressed`` is the state captured **before** the gesture
        (:meth:`_pressed_state`): a press closes the popup, so the overlay's visibility and
        its entries can only be read truthfully beforehand.
        """
        roles = self._resolve()
        panels = self._panel_map(roles)
        state = dict(pressed or {})
        state.setdefault("overlay_visible", self._is_visible(overlay["hwnd"]))
        state.setdefault("overlay_items", 0)
        state.setdefault("entry_tops", [])
        state.setdefault("entry_caption", self._get_text(entry["hwnd"]))
        observation = {
            "gesture": gesture,
            "gesture_failed": bool(gesture_failed),
            "overlay_visible": state["overlay_visible"],
            "overlay_visible_after": self._is_visible(overlay["hwnd"]),
            "overlay_hwnd": overlay["hwnd"],
            "overlay_rect": tuple(overlay["rect"]),
            "overlay_items": state["overlay_items"],
            "entry_hwnd": entry["hwnd"],
            "entry_rect": tuple(entry["rect"]),
            "entry_caption": state["entry_caption"],
            "entry_tops": state["entry_tops"],
            "overlay_closed": overlay["hwnd"] not in panels,
            "new_panels": [
                self._panel_observation(p, roles)
                for hwnd, p in panels.items()
                if hwnd not in before
            ],
            "dialog": None if panel is None else self._panel_observation(panel, roles),
        }
        self.last_entry_attempt = observation
        return observation

    def _require_visible_popup(self, entry: dict, overlay: dict) -> None:
        """Refuse to press an entry of a popup that is not **visible**.

        The handoff's hardest-won rule: this application pre-creates the ``Parameters``
        overlay in its control tree with ``IsWindowVisible == False`` and shows it on the
        hover, so a panel that is *present* is not a menu that is *open*. A press accepted
        on presence puts real or posted coordinates into empty screen — which is what a
        live run did — so the overlay and the entry are both required to report visible,
        and the panels that are in the tree but hidden are named in the refusal.
        """
        hidden = []
        if not self._is_visible(overlay["hwnd"]):
            hidden.append(overlay)
        if not self._is_visible(entry["hwnd"]):
            hidden.append(entry)
        if not hidden:
            return
        named = ", ".join(
            f"{k['cls']} at {k['rect'][:2]} (rect {k['rect']})" for k in hidden
        )
        others = [p for p in self._hidden_panels() if p["hwnd"] != overlay["hwnd"]]
        if others:
            named += (
                "; other panels present in the tree with IsWindowVisible == False: "
                + ", ".join(f"{p['rect']}" for p in others[:4])
            )
        raise AcquisitionError(
            f"refusing to press the popup entry: {named} reports IsWindowVisible == False, "
            "so the overlay in the control tree is not a menu that is on screen — this "
            "application pre-creates that panel and shows it on the hover, and a press on "
            "a panel that is only *present* lands on whatever is painted there"
        )

    def _press_entry(self, entry: dict, overlay: dict) -> dict | None:
        """Take one popup entry; return the dialog it opened, or ``None``.

        The **posted held press** on the entry's own handle is the gesture
        (:meth:`_click_hold`): the reference's own ``click_hold(entry_hwnd)``, which opened
        ``Operating parameters``, read the dialog, changed a combo and accepted, repeatedly
        (``recon/41_burst_sampling_volume.py``). It is neither a cursor move nor a click,
        and there is deliberately no second gesture and no ``allow_real_input`` gate here:
        the entry needs no cursor, and a re-derived alternative gesture is what three fix
        cycles went into.

        The press is **refused** unless the overlay and the entry both report visible
        (:meth:`_require_visible_popup`) — the live failure was a press aimed at a
        pre-created panel that was not on screen.

        Whatever happens, the attempt is **observed**
        (:meth:`_observe_entry_attempt`): the popup's visibility, its state, any panel that
        appeared, and that panel's rect and top-level child classes go on
        :attr:`last_entry_attempt` — on success and on failure alike, and also when the
        gesture itself raised — because the next live run must be told what the
        application did, not merely that the step failed.

        Nothing here presses anything *inside* a dialog: which dialog opened is the
        caller's question, and it answers it structurally and by content.
        """
        before = set(self._panel_map())
        gesture = GESTURE_POSTED_PRESS
        # Read what the overlay offers *now*: the press closes it, and the entries are gone
        # from the visible tree by the time the outcome is recorded.
        pressed = self._pressed_state(entry, overlay)
        try:
            self._require_visible_popup(entry, overlay)
            self._click_hold(entry["hwnd"])
        except AcquisitionError:
            self._observe_entry_attempt(
                entry, overlay, before, gesture, None, gesture_failed=True, pressed=pressed
            )
            raise
        panel = self._poll_dialog(_ENTRY_DIALOG_TIMEOUT_S)
        self._observe_entry_attempt(
            entry, overlay, before, gesture, panel, pressed=pressed
        )
        return panel

    def _close_wrong_dialog(self, panel: dict) -> None:
        """Close a dialog that is not the operating one with its **LEFT** button.

        Never its right-hand/default button: on a parameters dialog that button *accepts*
        the dialog's values, and this is precisely the dialog whose identity is not yet
        established — a default parameters dialog's Accept is a change nobody asked for.
        The leftmost button of the bottom row is ``Cancel`` on every dialog this
        application paints (:func:`_bottom_row`, :data:`…actuator.DialogControl.SAFE`).
        A close that does not resolve is noted, never raised through: the caller still has
        entries to try, and the bounded loop is what keeps that safe.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
            self._note(
                f"a dialog without the channel combo was up at {panel['rect'][:2]}; closed "
                "it with its left button — never its default button"
            )
        except AcquisitionError as exc:
            self._note(f"a dialog without the channel combo could not be closed: {exc}")

    def _dialog_button(
        self,
        panel: dict,
        kids: Sequence[dict],
        which: DialogControl,
        hold_ms: int = PRESS_HOLD_MS,
    ) -> dict:
        """Press one end of a dialog's bottom pair (never by title, never by rect).

        The pair is taken **from the right**, which is the reference's own rule
        (``recon/41_burst_sampling_volume.py``, ``bottom[-1] if accept else bottom[-2]``):
        Accept is the rightmost button of the band and Cancel is the one immediately left
        of it. Never the leftmost of the band — the live operating dialog's band also
        holds the two indicator buttons "No emission on Probe In/Out" and "Use US coupling
        parameters" to the left of the pair, so pressing "the leftmost button of the
        bottom row" pressed an indicator and left the dialog open, which is what a live
        read-only run did (measured 2026-09-17).
        """
        row = _bottom_row(panel, kids)
        if len(row) < 2:
            raise AcquisitionError(
                f"the dialog at {panel['rect'][:2]} has {len(row)} button(s) in its "
                f"bottom band ({[b['rect'] for b in row]}): Cancel and Accept are the "
                "last two by position, so neither can be identified and nothing is pressed"
            )
        target = row[-2] if which is DialogControl.SAFE else row[-1]
        self._click_hold(target["hwnd"], hold_ms)
        return target

    def _channel_combo(self, panel: dict, roles: Mapping | None = None) -> tuple[dict, int]:
        """The channel combo inside ``panel``: ``(combo, its parent's hwnd)``.

        Identity is the **item list**: a ``TComboBox`` inside this dialog whose items are
        the application's channels, ``'1'``..``'10'`` (:func:`channel_items`). Never an id
        (ids change on every launch), never a screen coordinate stated in logic, never
        "the first combo" — the operating dialog holds several combos (burst, sampling
        volume, sensitivity) and they are told apart by what they list.

        The nesting through a ``TSp_Value_Button`` that an earlier revision demanded is
        **dropped**: the live read of the operating dialog shows its channel combo as the
        dialog's own header field — ``TComboBox`` at ``(1083, 373)`` directly under the
        627x384 panel, i.e. ``Operating parameters for channel [n ▼]`` — not inside a value
        field, so the nesting was an assumption that could reject a correctly opened
        dialog. Two matches are an ambiguity, not a choice to make; none is a failure that
        names every combo the dialog holds and what it lists, which is the diagnosis a
        live run needs.
        """
        roles = self._resolve() if roles is None else roles
        wanted = channel_items()
        matches: list[tuple[dict, int]] = []
        found: list[str] = []
        for node in _descendants(roles, panel["hwnd"]):
            if node["cls"] != "TComboBox":
                continue
            items = self._combo_items(node["hwnd"])
            found.append(f"TComboBox at {node['rect'][:2]} listing {list(items)}")
            if items == wanted:
                parent = roles["parent_of"].get(node["hwnd"])
                matches.append((node, 0 if parent is None else parent))
        if not matches:
            raise AcquisitionError(
                f"no channel combo in the dialog at {panel['rect'][:2]}: the measurement "
                f"channel lives in a TComboBox listing {list(wanted)}, and the "
                f"{len(found)} combo(s) this dialog holds list "
                f"{'; '.join(found) or 'nothing at all'}"
            )
        if len(matches) > 1:
            raise AcquisitionError(
                f"{len(matches)} combos in the dialog at {panel['rect'][:2]} list "
                f"{list(wanted)}; the channel combo is ambiguous, so nothing is selected"
            )
        return matches[0]

    def _channel_readback(self, combo: dict) -> tuple[int, str]:
        """The dialog's own statement of the channel: the combo's index **and** text.

        Both, because either alone lies: ``CB_GETCURSEL`` reports only what the control
        believes, and a combo's painted text has been seen to keep showing the previous
        entry after a write (docs/16 §2). A read-back that does not name the configured
        channel is a selection that did not take.
        """
        return self._combo_index(combo["hwnd"]), self._get_text(combo["hwnd"])

    def _channel_matches(self, index: int, text: str) -> bool:
        """True when a dialog read-back names the configured channel exactly."""
        wanted = self._channel_setting
        return index == wanted.combo_index and text.strip() == str(wanted.channel)
