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
    """Why no press and no menubar gesture may be taken while an application dialog is up.

    The resolver decides a dialog **structurally** and publishes the union on the map
    (``value_dialogs`` | ``browse_dialogs``). Every panel that union names is a modal the
    application's own posted clicks ignore (docs/16 §8), and the predicates the runtime checks used
    to see one with — ``_find_overlay``'s rows (the values dialog is in its ``known`` set) and
    ``open_popup`` (which excludes dialogs) — no longer answer for it. So this clause is read where
    an action would be taken, not only where a reading is interpreted: a panel the dialog reader
    would call a dialog must not be one the press path cannot see.

    ``None`` when the map states no dialog. The panel is named by its own rect, never by a caption:
    these widgets are caption-less and the identity of the panel ``_dialog_panels`` returns is the
    panel that happens to be up, not necessarily the ``Operating parameters`` one.
    """
    up = set(roles.get("value_dialogs") or ()) | set(roles.get("browse_dialogs") or ())
    if not up:
        return None
    panel = next((p for p in roles.get("panels") or () if p["hwnd"] in up), None)
    if panel is None:
        return None
    rect = tuple(panel["rect"])
    return (
        f"an application dialog is up at {rect[:2]} (rect {rect}): this step would act behind a "
        "modal in an application whose posted clicks ignore modality (docs/16 §8) — clear the "
        "dialog from the UI first, this driver never WM_CLOSEs a dialog and never presses into one"
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
        """
        roles = roles if roles is not None else self._resolve()
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
