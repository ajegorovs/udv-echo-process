"""The recording strip's lifecycle: record, hold, stop, reset, and the cycle that stores a point.

Split out of the flat :mod:`udv_echo_process.acquire.driver` by Patch 4 — **verbatim**. This
surface holds the strip's own state read, the held press, the guarded view waits, the overlay
answering that keeps a modal warning from wedging the application, the recovery that leaves the
instrument safe after a failure, and :meth:`RecordingSurface.record_and_store`, the one whole
cycle. No decision, message, order, timeout, hold or refusal changed: this is a move, not a
rewrite.

**Nothing here is proven on an instrument.** Every gesture in this module is *device-pending*
(``docs/dop3000/device-verification.md``, V2/V4/V5/V6): a moved workflow is not a verified one,
and the cloud-only validation contract (``docs/dop3000/acquisition-architecture.md`` §8) forbids
claiming that it is.

**It is a mixin.** The bodies are the ones ``Win32Actuator`` had, they reach their collaborators
through ``self`` (a press re-resolves the strip panel through the facade, a store cycle is the
Store surface's, an overlay press is the Parameters surface's), and ``acquire/driver.py`` composes
this piece into the one live class (``udop/session.py`` is that facade's compatibility name).
``self._resolve``, ``self._click_hold`` and
``self.ensure_channel`` therefore resolve on the composed instance exactly as they resolved on
the flat class — which is what keeps every subclass that overrides a private
(``tests/test_acquire_driver.py``'s ``FakeDriver``) overriding the same method.

``_OVERLAY_SETTLE_S`` and ``_POLL_S`` live here, with the loops that read them: this is the
surface that answers overlays. The two other surfaces that poll at the same cadence import them
from here rather than holding a second copy of the number — so the value a test patches is **this
module's**, and ``_OVERLAY_SETTLE_S``'s one other reader, the facade's ``preflight``, holds the
copy it imported (named in ``docs/dop3000/acquisition-architecture.md`` §5).
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    STARTABLE_VIEWS,
    STORE_TIMEOUT_S,
    VIEW_TIMEOUT_S,
    DialogControl,
    OverlayKind,
    ProcessMode,
    StripControl,
    StripState,
    StripView,
    overlay_answer,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.ui.dialog import bottom_row as _bottom_row
from udv_echo_process.acquire.ui.identity import PanelIdentity
from udv_echo_process.acquire.ui.strip import (
    press_refusal as strip_press_refusal,
)
from udv_echo_process.acquire.ui.strip import (
    strip_state_of,
)

# ------------------------------------------------------------------------ the strip's cadence

#: The settle after an accepted overlay answer, and the cadence the polling loops below
#: run at. The held press's own settle travels with the gesture, in ``win32/messages.py``.
_OVERLAY_SETTLE_S, _POLL_S = 0.8, 0.4


def dialog_up_clause(roles: Mapping) -> str | None:
    """Why no press and no menubar gesture may be taken while a blocking surface is up.

    The resolver decides what every panel **is** — once, from the panel's own shape
    (:mod:`udv_echo_process.acquire.ui.identity`) — and publishes the classified inventory plus
    the surface that blocks an action (``roles["blocking_surface"]``: ``WARNING``, ``OVERLAY``,
    ``APPLICATION_DIALOG`` or ``MENU_POPUP``). This clause reads both statements, so a step that
    would act behind *any* of them refuses before it acts: a dialog is a modal this application's
    own posted clicks ignore (docs/16 §8), a warning guard is the reused destructive panel, a
    ``Define TGC`` overlay is an operator's surface the driver must not act under, and an open
    menu is the strip resolver's decoy. Nothing here presses anything, and nothing here dismisses
    anything: the operator clears the surface from the UI.

    **The name is kept** for the callers and tests written against it (``press``,
    ``_settle_press``, ``_open_parameters_dialog``), and the *wording* keeps the dialog case's
    exact sentence, because that failure has been read by operators: ``None`` means nothing is
    blocking, never "nothing was checked".

    A map that states the *dialog union* and no ``blocking_surface`` — every fixture and fake
    written before the classification landed — is answered by the union alone, so those callers
    keep refusing exactly what they refused.
    """
    up = set(roles.get("value_dialogs") or ()) | set(roles.get("browse_dialogs") or ())
    if up:
        panel = next((p for p in roles.get("panels") or () if p["hwnd"] in up), None)
        if panel is None:
            return None
        rect = tuple(panel["rect"])
        return (
            f"an application dialog is up at {rect[:2]} (rect {rect}): this step would act behind a "
            "modal in an application whose posted clicks ignore modality (docs/16 §8) — clear the "
            "dialog from the UI first, this driver never WM_CLOSEs a dialog and never presses into one"
        )
    surface = roles.get("blocking_surface")
    if surface is None:
        return None
    try:
        kind = PanelIdentity(str(getattr(surface, "value", surface)))
    except ValueError:  # a name this vocabulary does not carry: refuse, by that name
        kind = PanelIdentity.OTHER
    named = {
        PanelIdentity.WARNING: (
            "a warning guard",
            (
                "the application reuses one panel family for its destructive guards and the tree "
                "does not state which warning is painted, so this driver answers none of them here"
            ),
        ),
        PanelIdentity.OVERLAY: (
            "a non-measurement overlay",
            (
                "it is not the measurement layout, and nothing under it resolves to the widgets "
                "these roles were bound to"
            ),
        ),
        PanelIdentity.MENU_POPUP: (
            "a menu popup",
            (
                "the parameter roles below it would bind to the popup's own controls, and this "
                "driver never WM_CLOSEs a popup"
            ),
        ),
    }.get(kind)
    if named is None:
        return None
    what, why = named
    panel = next(
        (
            p
            for p in roles.get("panels") or ()
            if roles.get("identities", {}).get(p["hwnd"]) is kind
        ),
        None,
    )
    at = f" at {tuple(panel['rect'])}" if panel is not None else ""
    return (
        f"{what} is up{at}: {why} — this step would act behind it, so nothing is pressed and "
        "nothing is dismissed here; clear it from the UI (Cancel/its own safe end) first"
    )


class RecordingSurface:
    """The strip lifecycle of :class:`~udv_echo_process.acquire.udop.session.Win32Actuator`.

    The recording surface of the live actuator: the strip's state, the held press every button
    of the row is taken with, the view waits that watch the overlays while they poll, and the
    cycle that records, holds, stops and stores one point. Moved out of the flat actuator
    verbatim by Patch 4; see this module's docstring for what is and is not claimed.
    """

    def _state_of(self, roles: dict) -> StripState:
        """The strip state implied by an already-resolved role map.

        Both facts come off the map itself, and that is the point: the row's length, and the
        slider's presence — which is what :meth:`_resolve` read off the strip panel's own live
        children (``ui/strip.py``'s :func:`…ui.strip.has_slider`) and carried here as
        ``roles["strip_slider"]``. A map that states neither is read from the *view* it classified,
        and ``STORE`` **is** the slider's view (:func:`…actuator.classify_strip_view`), so a state
        can be read from a captured or synthesised tree with no window behind it at all — which is
        what makes this read testable off the instrument.

        The state itself is built by ``ui/strip.py`` (:func:`…ui.strip.strip_state_of`), including
        ``slider_max``, which is deliberately left unset: the reference never read the slider's
        range, and guessing is worse than ``None``.
        """
        if "strip_slider" in roles:
            slider = bool(roles["strip_slider"])
        else:
            slider = roles.get("state") == StripView.STORE.value
        return strip_state_of(
            button_count=len(roles["strip_row"]),
            has_slider=slider,
            slider_max=None,
        )

    def _find_overlay(self, roles: dict | None = None):
        """Find an overlay panel: not a known layout panel, owning its own dialog row.

        Returns ``(kind, panel, kids)`` or ``None``. A warning is a panel with a bottom
        button pair; the Store dialog is the panel owning a ``TSp_Browse`` and edits but
        none of the values dialog's ``TSp_Value_Button`` children. The app reuses one
        geometry for all its warnings, so structure is the only discriminator
        (docs/16 §8, §12b).

        **Both halves are read off the classification now** (``roles["identities"]``): only a panel
        the classifier called :attr:`…identity.PanelIdentity.WARNING` is a warning here, and only an
        :attr:`…identity.PanelIdentity.APPLICATION_DIALOG` panel that also carries the browse
        discriminator is a store dialog. That is what keeps this surface's *answer* — a press of the
        warning's safe end — off every other panel that merely looked like a warning: measured
        2026-09-19, the ``Define TGC`` overlay (450x120, six children, three buttons in its own
        bottom band) satisfied the old family rule, and the strip's own panel satisfied it in the
        intermediate state. A map that states **no** identities — a fixture or a fake written
        before the classification — is read by the structural rules below, so those callers keep
        exactly the behaviour they had.
        """
        roles = roles if roles is not None else self._resolve()
        identities: Mapping = roles.get("identities") or {}
        known: set[int] = set()
        for key in ("menu", "combos"):
            known.update(k["hwnd"] for k in (roles.get(key) or {}).values())
        known.update(
            row["edit"]["hwnd"]
            for row in (roles.get("param_rows") or [])
            if row.get("edit")
        )
        known.update(roles["value_dialogs"])
        if roles.get("left_panel") is not None:
            known.add(roles["left_panel"]["hwnd"])
        if roles.get("strip_panel") is not None:
            known.add(roles["strip_panel"]["hwnd"])
        if roles.get("panels"):
            known.add(roles["panels"][0]["hwnd"])  # the menu bar's own panel
            known.add(roles["panels"][-1]["hwnd"])  # the status bar's
        for panel in roles["panels"]:
            if panel["hwnd"] in known:
                continue
            identity = identities.get(panel["hwnd"])
            if identity is not None and identity not in (
                PanelIdentity.WARNING,
                PanelIdentity.APPLICATION_DIALOG,
            ):
                # Classified, and not one of the two surfaces this method owns an answer for:
                # an overlay, the cursor info box, a strip panel or an unknown panel is never
                # answered — and never pressed — from here.
                continue
            kids = self._children_of(panel["hwnd"], roles)
            if any(k["cls"] == "TSp_Browse" for k in kids) and any(
                k["cls"] in ("TEdit", "TSp_Edit") for k in kids
            ):
                return (OverlayKind.STORE_DIALOG, panel, kids)
            if _bottom_row(panel, kids) and panel["w"] > 250 and panel["h"] > 90:
                return (OverlayKind.WARNING, panel, kids)
        return None

    def _peek_overlay(self) -> OverlayKind | None:
        """Which overlay is up, without answering it."""
        found = self._find_overlay()
        return None if found is None else found[0]

    def strip_state(self) -> StripState:
        """The strip's current structure, freshly resolved."""
        return self._state_of(self._resolve())

    def wait_for_view(
        self, views: Iterable[StripView | str], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        """Poll until the strip reaches one of ``views``; return the last state seen.

        Overlays are *not* answered here — this is the protocol's read-only wait, and the
        caller decides whether a wedged view is a failure. The cycle uses the
        overlay-watching variant (:meth:`_wait_for_view_guarded`).
        """
        wanted = {v if isinstance(v, StripView) else StripView(v) for v in views}
        deadline = time.monotonic() + max(0.0, timeout_s)
        state = self.strip_state()
        while state.view not in wanted and time.monotonic() < deadline:
            time.sleep(_POLL_S - 0.05)
            state = self.strip_state()
        return state

    def press(self, control: StripControl) -> None:
        """Press one strip button of the *current* view, **held**, by position.

        A posted held press is exactly what this strip answers — measured live 2026-09-17 by
        A/B on the same button: the held posted press started the recording and the Stop press
        reached the store view, while a *real* click (``SetCursorPos`` + ``mouse_event`` down/up,
        the recipe `recon/19_store_cycle_real.py` uses) changed **nothing** on any of the three
        buttons of the row. `docs/16 §1` already had the sharper statement of the rule — an
        *instant* down/up in the same millisecond is ignored — which is what `recon/19` meant by
        "the strip ignores posted messages". So the hold is the whole gesture, and no cursor is
        taken here: the menubar hover stays the only real-input step.

        The overlay guard runs **first** (posted clicks ignore modality, docs/16 §8), then the
        strip is re-resolved — its rect and its children change with the view — and the index
        comes from :func:`…actuator.press_index`, never from a width.

        The row is checked for a **binding** before the index is asked for: the ambiguous
        four-button row with no slider has none, and it refuses by name rather than pressing
        something the crops disagree about (:func:`…ui.strip.press_refusal`, ledger B10). Nothing
        is posted and nothing is recorded on that path.
        """
        self._settle_press()
        roles = self._resolve()
        if roles["open_popup"]:
            raise AcquisitionError(
                "a menu popup is open; the strip binding would be unreliable — close it from "
                "the UI, this driver never WM_CLOSEs a popup"
            )
        # An application **dialog** is a guard of its own, and not the same check: ``open_popup``
        # excludes dialogs (the measured ``Operating parameters`` panel must not be read as an
        # open menu), so without this clause a leftover dialog would leave ``press`` free to post
        # a held press behind a modal (docs/16 §8 — this application's posted clicks ignore
        # modality). ``_settle_press`` reads the same clause; this one is the press path's own.
        clause = dialog_up_clause(roles)
        if clause is not None:
            raise AcquisitionError(clause)
        if roles["strip_panel"] is None:
            raise AcquisitionError("no recording strip panel found")
        state = self._state_of(roles)
        # The ambiguous row is refused by name **before** the press, not by a missing index: it
        # holds four buttons and no slider, the repository's own crops disagree about which of
        # them is which, and a press here would post a real held message on the operator's
        # instrument under a role nobody has verified (ledger B10). Nothing is posted and
        # nothing is recorded; the clause is ``ui/strip.py``'s own wording.
        refusal = strip_press_refusal(state)
        if refusal is not None:
            raise AcquisitionError(refusal)
        index = state.index_of(
            control
        )  # raises with the known row when the press is impossible
        self._click_hold(roles["strip_row"][index]["hwnd"])
        self.last_roles = self._resolve()  # the panel morphed: never reuse the old row

    def answer_overlay(self) -> OverlayKind | None:
        """Answer an overlay if one is up, and say what it was.

        Warnings are answered with the LEFT button (:func:`…actuator.overlay_answer`), so an
        existing file is never silently replaced. The Store dialog is returned **untouched**
        — it is not an overlay to dismiss, it is where the name is set. Nothing is ever
        ``WM_CLOSE``\\ d: an unanswered overlay traps the operator's cursor in the app, and
        a closed one can lose the step the caller is mid-way through.
        """
        answered: OverlayKind | None = None
        for _ in range(4):
            found = self._find_overlay()
            if found is None:
                return answered
            kind, panel, kids = found
            answer = overlay_answer(kind)
            if answer is None:
                return kind  # the Store dialog: the caller owns its fields and commit
            self._dialog_button(panel, kids, answer)
            answered = kind
            time.sleep(_OVERLAY_SETTLE_S)
        return answered

    def hold_recording(self, duration_s: float) -> None:
        """Wait out a point's duration, watching the view and the overlays.

        The public name for what the cycle itself uses, because a caller that drives the strip
        by hand — a preflight, a probe — needs the *same* hold and not a ``time.sleep``: a
        monotonic deadline measured from the **confirmed** recording view, a warning answered
        instead of slept through (a modal stalls the application's own timers), and a recording
        that stopped by itself raised rather than ignored.
        """
        self._hold_recording(duration_s)

    def wait_for_view_guarded(
        self, want: Iterable[StripView], timeout_s: float
    ) -> StripState:
        """Poll for a view while answering the overlays that would otherwise wedge the app."""
        return self._wait_for_view_guarded(want, timeout_s)

    def peek_overlay(self) -> OverlayKind | None:
        """Which overlay is up, if any — read-only, and it presses nothing."""
        return self._peek_overlay()

    def _settle_press(self) -> None:
        """Answer every overlay before a press; refuse if one needs the caller.

        And refuse when an application **dialog** is up: it is not an overlay ``_find_overlay``
        answers (the values dialog is in its ``known`` set), and a press behind a modal is exactly
        what this guard exists to stop (docs/16 §8). The clause reads the resolver's own union,
        because that is the only statement of "a dialog is up" on the map (:func:`dialog_up_clause`).
        """
        for _ in range(4):
            roles = self._resolve()
            found = self._find_overlay(roles)
            if found is None:
                clause = dialog_up_clause(roles)
                if clause is not None:
                    raise AcquisitionError(clause)
                return
            kind, panel, kids = found
            if kind is OverlayKind.STORE_DIALOG:
                raise AcquisitionError(
                    "the Store dialog is up; no press is safe until it is handled"
                )
            self._dialog_button(panel, kids, overlay_answer(kind) or DialogControl.SAFE)
            self._note(f"answered a {kind.value} before pressing")
            time.sleep(_OVERLAY_SETTLE_S)

    def _wait_for_view_guarded(
        self, want: Iterable[StripView], timeout_s: float
    ) -> StripState:
        """Poll for ``want`` while watching for overlays.

        A warning raised mid-step is answered with its safe button and recorded; the poll
        keeps running, so a modal warning can never turn the wait into a hang.
        """
        wanted = set(want)
        deadline = time.monotonic() + max(0.0, timeout_s)
        state = self.strip_state()
        while state.view not in wanted and time.monotonic() < deadline:
            kind = self._peek_overlay()
            if kind is OverlayKind.WARNING:
                self._note("answered a warning while waiting for a view change")
                self.answer_overlay()
            elif kind is OverlayKind.STORE_DIALOG:
                return state  # reported, not waited through
            time.sleep(_POLL_S - 0.05)
            state = self.strip_state()
        return state

    def _hold_recording(self, duration_s: float) -> None:
        """Wait out the point's duration, watching the view and the overlays."""
        deadline = time.monotonic() + max(0.0, duration_s)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.5, remaining))
            if self._peek_overlay() is OverlayKind.WARNING:
                # Seen, not slept through: a modal warning stalls the app's own timers.
                self._note("answered a warning raised during recording")
                self.answer_overlay()
            state = self.strip_state()
            if state.view is not StripView.RECORDING:
                raise AcquisitionError(
                    f"the recording stopped on its own (view {state.view.value!r}) after "
                    f"{duration_s - max(0.0, deadline - time.monotonic()):.1f} s"
                )

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: ProcessMode,
        timeout_s: float = STORE_TIMEOUT_S,
        verify_channel: bool = True,
    ) -> Path:
        """Record ``duration_s``, stop, store as ``name``; return the stored path.

        Never a blind sleep: the recording view is polled and overlays are watched for
        throughout, because a modal warning raised mid-recording wedges the app and must be
        seen. Any failure dismisses overlays, leaves the application not recording, and
        raises :class:`AcquisitionError` — a point that failed is never returned as if it
        had been stored.

        ``expected_mode`` is the process this run was measured against, and it is **required and
        keyword-only** so no cycle can leave the expectation implied (plan §24.4). The screen's
        caption is checked against it — and the layout's shape, which is mode-independent —
        before anything is pressed: a run measured in simulation refuses to record against the
        instrument, and vice versa, naming the caption it saw rather than calling the screen
        unclean.
        """
        # DEVIATION: §24.4 names this method `record(*, expected_mode)`; the port's name is
        # `record_and_store` and is kept, because the runner, the live verbs and every fake call it
        # by that name and this slice changes no caller's vocabulary for a rename's sake.
        try:
            note = self.layout_note(expected_mode=expected_mode)
            if note is not None:
                raise AcquisitionError(f"refusing to start: {note}")
            state = self.strip_state()
            if state.view is StripView.STORE:
                self.press(
                    StripControl.NEW_ACQUISITION
                )  # dismiss the leftover block view
                self._note("cleared the leftover block view")
                state = self.wait_for_view((StripView.READY,), timeout_s=VIEW_TIMEOUT_S)
            if state.view not in STARTABLE_VIEWS or state.view is not StripView.READY:
                raise AcquisitionError(
                    f"the cycle must start from the ready view, not {state.view.value!r}"
                )
            # The channel is a precondition of the point, verified from the dialog
            # before a recording is spent: another channel's block decodes as a valid
            # point that is not this point (docs/16 §12).
            if verify_channel:
                self._note("verifying the channel from the parameters dialog")
                self.ensure_channel()
                self._note("the channel is verified; pressing Record")
            else:
                self._note("the channel was verified once for this run; pressing Record")
            self.press(StripControl.RECORD)
            state = self._wait_for_view_guarded((StripView.RECORDING,), VIEW_TIMEOUT_S)
            if state.view is not StripView.RECORDING:
                raise AcquisitionError(
                    f"the Record press did not start a recording (view {state.view.value!r})"
                )
            self._note(f"recording confirmed; holding {duration_s:.1f} s")
            self._hold_recording(duration_s)
            self._note(f"the {duration_s:.1f} s hold is over; pressing Stop")
            self.press(StripControl.STOP)
            state = self._wait_for_view_guarded((StripView.STORE,), VIEW_TIMEOUT_S)
            if state.view is not StripView.STORE:
                raise AcquisitionError(
                    f"Stop did not reach the store view ({state.view.value!r})"
                )
            self.press(StripControl.DO_STORE)
            self._await_store_dialog(VIEW_TIMEOUT_S)
            # Where the store will land is asserted before anything is named or
            # committed: the caller watches this directory, not the one the dialog
            # happened to remember (docs/16 §12b).
            self.assert_working_directory(directory)
            known = self._names_in(directory)
            self._note(f"the Store dialog is up; naming the file {name!r}")
            self.set_store_name(name)
            self.commit_store()
            stored = self._store_until_file(name, directory, known, timeout_s)
            # The size is the runner's to log (`file_size_bytes`); a note must not touch the
            # filesystem, because a sweep may be faked against an actuator with no disk behind
            # it and a note that raises would turn a stored point into a failed one.
            self._note(f"stored {stored.name}")
            return stored
        except AcquisitionError as exc:
            self._recover()
            raise AcquisitionError(f"{name}: {exc}") from exc
        except Exception as exc:
            self._recover()
            raise AcquisitionError(f"{name}: unexpected failure: {exc!r}") from exc

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: ProcessMode,
        timeout_s: float = STORE_TIMEOUT_S,
        verify_channel: bool = True,
    ) -> tuple[bool, Path | str]:
        """``record_and_store`` with the failure in the return value instead of a raise.

        ``(True, path)`` or ``(False, reason)`` — the shape a sweep loop logs per point. The
        expectation is required here too, and passed straight through: the per-point gate a
        runner's loop reaches is this one, and a default would put the expectation back where
        §24.4 refuses to have it.
        """
        try:
            return True, self.record_and_store(
                name,
                duration_s,
                directory,
                expected_mode=expected_mode,
                timeout_s=timeout_s,
                verify_channel=verify_channel,
            )
        except AcquisitionError as exc:
            return False, str(exc)

    def _recover(self) -> None:
        """Leave the application safe after a failure, then let the caller report it.

        Overlays are answered (never closed), and a recording left running is stopped: a
        leftover recording would otherwise be stored under the next point's name.
        """
        try:
            for _ in range(4):
                kind = self._peek_overlay()
                if kind is None or kind is OverlayKind.STORE_DIALOG:
                    break
                self.answer_overlay()
            if self.strip_state().view is StripView.RECORDING:
                self._note("a recording was left running; pressing Stop")
                self.press(StripControl.STOP)
        except Exception as exc:  # noqa: BLE001 - recovery must never mask the failure
            self._note(f"recovery was incomplete: {exc!r}")
