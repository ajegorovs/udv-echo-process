"""One guarded press on the ``Channels`` popup's **Enable multiplexer** toggle.

The popup is the operator's: this command never opens, closes or moves it. It binds exactly one
instrument window, reads the full 8-band settings surface, and needs a **fresh capture taken in
this same invocation** whose two frames agree and whose capture-time digests were re-derived from
the decoded pixels. That capture must prove the conjunction a mode entry needs — the entry line
painted ``Enable multiplexer`` (``VISUAL_DISABLED``) and the rollover row painting the green check
(``ON_PROVEN``) — and it must be ``live-bracketed`` / ``capture-digest-verified``. A retained
``mpx-mode-read`` directory, a bare ``enable_precondition`` boolean, or a visual attribution on its
own is never a licence to press.

Two captures, in this order, and they are distinct facts
-------------------------------------------------------
1. the **decision** capture, taken before anything is written: its job is to establish that this
   invocation may take on the obligation at all;
2. the **final licensing** capture, taken at the narrow action boundary — *after* the obligation
   has been written durably and immediately before the press — never recycled from (1).

Recycling (1) would mean the press rested on pixels read before the record existed, and a window
that changed while the record was being written would be pressed anyway. The record carries both
pairs in separate fields (``old_*`` for the decision, ``final_*`` for the licence), and when the
final capture refuses, the record is still rewritten with what that capture found — its run
directory, its digests and its attribution.

Ordering, and what it does not buy
----------------------------------
The claim is a durable write (``O_EXCL`` + ``fsync``) *before* the boundary runs; the boundary then
re-asks the window set, the stopped recording row, the binding and the popup's role, takes the new
capture, and only then posts. This command **claims no atomicity**: another process, the operator or
the application itself can move, repaint, close or consume that control between the last read and
the posted message, and no wait, lock or timeout can close that gap. What it does instead is state
the requirement on the operator and measure the interval:

* the operator must keep hands off — no clicks, keys, popup moves or channel changes — for the
  whole command, and the record and the result both say so;
* ``boundary_seconds`` is a **monotonic diagnostic** of how long the licensing capture and its
  checks took, not a security timeout. No cap is invented: only a caller that passes
  ``max_boundary_seconds`` gets an enforced limit, and then it refuses with zero presses.

``posted`` stays ``"unknown"`` after a press: attempted is not delivered. The post state is read
and, **only when that read resolves the clipped one-entry popup**, one fresh post-press capture
pair is taken and held to the entry contract: ``VISUAL_ENABLED`` is reported only when that pair
is ``ok``, its frames agree, its digests re-derive, its guards bind the original window and popup,
and both frames paint ``Desable multiplexer`` at the measured 158x43 entry shape. When no entry is
visible the mode stays ``UNKNOWN`` explicitly — it is never inferred from the press, from a
``ready`` strip, or from a different surface — and no retry, ``Record`` or ``Disable`` follows.
The operator still owns the enabled interval; ``Disable multiplexer`` remains their gesture.

Rolling is a separate fact and it is load-bearing. With ``Roll over the channels`` **off** a mode
entry auto-arms and records (``docs/dop3000/udop-automation.md`` §12.13), which this command must
never trigger: ``OFF_PROVEN``, ``UNKNOWN`` and ``ABSENT`` all refuse with **zero presses** and no
record. Only ``ON_PROVEN`` proceeds — and even then enabling starts relay cycling, so the operator
must be present.

The target is resolved by the reader's **role and provenance** *and* by measured row geometry:
:func:`…ui.channels.bind_enable_toggle` requires exactly one toggle that both carries the measured
``Enable multiplexer`` attribution and owns the measured Enable label band with its popup-relative
rect, and whose rect never reaches the rollover mark band. A caption sequence is not an identity on
its own: a permuted tree would otherwise hand this command the wrong control. The action boundary
re-runs that rule live, requires the same handle **and the same rect**, and then posts one held
press on that toggle's handle. There is no generic ``press(handle)`` entry point.

Nothing else is pressed: no ``Record``, no ``Disable``, no ``Stop``, no ``Clear``, no retry, no
hover, no click elsewhere. A raised press leaves ``posted`` ``"unknown"``: attempted is not
delivered.

Live status: the press recipe is the existing held ``WM_LBUTTONDOWN`` / ``WM_LBUTTONUP`` one, but
**this command's press has not been exercised on the instrument**. The enabled interval that follows
it is likewise unverified and needs a bounded operator trial.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from udv_echo_process.acquire import mode_marks
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.binding import resolve_bound_target
from udv_echo_process.acquire.channels_capture import CAPTURE_ENTRY_NO_NUMERIC
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.channels_repeat import (
    _strip_not_recording,
    claim_trial_record,
    trial_record_file,
    update_trial_record,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.store_completed import screen_clauses
from udv_echo_process.acquire.ui.channels import (
    CAPTION_SOURCE,
    ENABLE_CAPTION,
    TOGGLE_CAPTIONS,
    ChannelsRead,
    ChannelsSurface,
    ModeToggle,
    bind_enable_toggle,
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ENABLE_CAPTION",
    "MEASURED_TOGGLES",
    "TRIAL_FILE_NAME",
    "EnableMultiplexedResult",
    "EnableStage",
    "acquire_enable_multiplexed",
    "enable_toggle",
]

#: ``ENABLE_CAPTION`` is imported from ``ui.channels`` — one owner of the role's caption.

#: The measured toggle captions, in the reader's screen order (owned by ``ui.channels``).
MEASURED_TOGGLES = TOGGLE_CAPTIONS

TRIAL_FILE_NAME = "enable-multiplexed-trial.json"

PRESS_EVIDENCE = (
    "one press attempt with the strip's posted held-press recipe (WM_LBUTTONDOWN, hold, "
    "WM_LBUTTONUP) on the Enable toggle's own handle, re-resolved — handle, caption and "
    "popup-relative rect — immediately before the press; never BM_CLICK and never a screen "
    "coordinate. Whether the message was delivered is unknown, so no field here claims a post"
)

HANDS_OFF = (
    "the operator must keep hands off the keyboard, mouse and instrument for the whole command: "
    "the popup must not move or be clicked, and no channel may change between the licensing "
    "capture and the posted press. The command states this requirement; it cannot enforce it"
)

OS_RACE = (
    "an operating-system race remains between the last read and the posted message: the "
    "application can move, repaint, disable or close that control in between, so the capture "
    "states the moment before the press and never a lock, and the post state stays unknown"
)

RELAY_WARNING = (
    "enabling starts the relay: with the multiplexer on the instrument cycles the configured "
    "channels even though Roll over the channels was ON, so a record relay may begin without the "
    "Record control being pressed — be present, and stop it from the UI if it is not wanted"
)

_FRESH_CONTEXT = "live-bracketed"
_FRESH_INTEGRITY = "capture-digest-verified"

BOUNDARY_DIAGNOSTIC = (
    "boundary_seconds is a monotonic measurement of the licensing capture and its checks taken "
    "immediately before the press: a diagnostic, not a security timeout and not an atomicity "
    "claim. No cap applies unless the caller passed max_boundary_seconds"
)


def _now_stamp() -> str:
    return datetime.now(tz=UTC).astimezone().isoformat()


def _reason(exc: BaseException) -> str:
    """A never-empty reason for a caught failure."""
    text = str(exc).strip()
    return text or type(exc).__name__


class EnableStage(str, Enum):
    """How far one invocation got — each member says what is established, not what was tried."""

    PRESSED = "pressed"
    PRESS_RAISED = "press_raised"


class EnableMultiplexedResult(ValueModel):
    """What the one guarded mode press established, and everything it could not."""

    stage: EnableStage
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    target_hwnd: int | None = None
    #: The popup-relative rectangle the press was licensed against, re-checked at the press.
    target_rect: tuple[int, int, int, int] | None = None
    target_attribution: str = ENABLE_CAPTION
    target_provenance: str = CAPTION_SOURCE
    signature: tuple[str, ...] = ()
    capture_dir: str = ""
    #: The **decision** evidence: what licensed taking on the obligation, before anything was
    #: written. Distinct from the final pair below and never reused for the press.
    old_label: str = ""
    old_mode: str = ""
    old_rolling: str = ""
    old_context: str = ""
    old_integrity: str = ""
    old_frame_digests: tuple[str, str] | None = None
    #: The **final licensing** evidence: the capture taken after the durable claim, at the narrow
    #: boundary, immediately before the press.
    final_label: str = ""
    final_mode: str = ""
    final_rolling: str = ""
    final_context: str = ""
    final_integrity: str = ""
    final_frame_digests: tuple[str, str] | None = None
    final_capture_dir: str = ""
    #: Monotonic measurement of the boundary, and its terms: diagnostic only.
    boundary_seconds: float | None = None
    boundary_evidence: str = BOUNDARY_DIAGNOSTIC
    #: The post-press read: the surface it found, and the mode — stated only from a fresh entry
    #: pair taken when that read resolves the clipped one-entry popup.
    post_surface: str = "UNKNOWN"
    post_mode: Literal["VISUAL_ENABLED", "UNKNOWN"] = "UNKNOWN"
    post_rolling: str = "UNKNOWN"
    post_capture_dir: str = ""
    post_capture_kind: str = ""
    post_frame_digests: tuple[str, str] | None = None
    post_error: str = ""
    presses: int = 0
    press: Literal["not_attempted", "attempted"] = "not_attempted"
    posted: Literal["not_attempted", "unknown"] = "not_attempted"
    press_error: str = ""
    press_evidence: str = PRESS_EVIDENCE
    restoration_owed: tuple[str, ...] = ()
    trial_record: Path | None = None
    trial_record_phase: Literal["", "obligation", "preflight_refused", "after"] = ""
    trial_record_error: str = ""
    observed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        return (
            f"enable multiplexed (stage {self.stage.value}, presses {self.presses}, "
            f"posted {self.posted}, post mode {self.post_mode}); "
            + "; ".join(self.restoration_owed)
        )


# ---------------------------------------------------------------------------------------------
# target resolution: role, provenance and measured row geometry — never an index
# ---------------------------------------------------------------------------------------------


def enable_toggle(report: ChannelsRead) -> ModeToggle:
    """The one toggle the reader binds to ``Enable multiplexer``, or a refusal.

    The rule is owned by :func:`…ui.channels.bind_enable_toggle` — the measured 8-band signature,
    the measured caption sequence, the caption's provenance and the measured Enable row band, with
    the rollover mark band excluded — so this command and the action boundary cannot disagree
    about what the target is.
    """
    return bind_enable_toggle(report)


# ---------------------------------------------------------------------------------------------
# capture contract
# ---------------------------------------------------------------------------------------------


def _verified_capture(
    report: ChannelsRead, *, what: str
) -> mode_marks.ModeMarkAttribution:
    """The fresh capture's mode evidence, or a refusal naming the clause that failed."""
    capture = report.capture
    if capture is None:
        raise AcquisitionError(
            f"no capture was taken {what}: a mode press needs a fresh same-invocation capture, "
            "never a retained directory and never an attribution alone — nothing was pressed"
        )
    if capture.status != "ok":
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok"
        raise AcquisitionError(
            f"the capture {what} is not ok ({reasons}): nothing was pressed"
        )
    mark = capture.visual_mode_mark
    if mark is None:
        raise AcquisitionError(
            f"the capture {what} carries no mode attribution for the measured settings shape: "
            "nothing was pressed"
        )
    if (
        mark.surface != mode_marks.SETTINGS_FULL
        or mark.label != "ENABLE_MULTIPLEXER"
        or mark.mode != "VISUAL_DISABLED"
    ):
        raise AcquisitionError(
            f"the capture {what} reads surface={mark.surface!r} label={mark.label!r} "
            f"mode={mark.mode!r} where the disabled settings surface is required: nothing was "
            "pressed"
        )
    if mark.rolling == "OFF_PROVEN":
        raise AcquisitionError(
            "HAZARD: the popup's rollover mark proves Roll over the channels OFF, and a mode "
            "entry with rolling off auto-arms and records on enable (§12.13). This command "
            "refuses with zero presses and performs no cleanup — set rolling ON as a separate "
            "operator gesture first"
        )
    if mark.rolling != "ON_PROVEN":
        raise AcquisitionError(
            f"the capture {what} proves no rolling state ({mark.rolling!r}): rolling OFF "
            "auto-arms on enable, so the conjunction is required and nothing was pressed"
        )
    if (
        mark.acquisition_context != _FRESH_CONTEXT
        or mark.freshness != "live_bracketed"
        or mark.integrity != _FRESH_INTEGRITY
        or mark.frames_agreed is not True
        or mark.recognition != "EXACT_TEMPLATE_MATCH"
    ):
        raise AcquisitionError(
            f"the capture {what} is not a fresh live-bracketed digest-verified pair "
            f"(context={mark.acquisition_context!r}, freshness={mark.freshness!r}, "
            f"integrity={mark.integrity!r}, agreed={mark.frames_agreed!r}, "
            f"recognition={mark.recognition!r}): a retained or unverified reading is not a "
            "precondition — nothing was pressed"
        )
    digests = mark.frame_digests
    if (
        digests is None
        or len(digests) != 2
        or any(len(digest) != 64 for digest in digests)
    ):
        raise AcquisitionError(
            f"the capture {what} carries no two genuine frame digests: nothing was pressed"
        )
    # The derived boolean is accepted only after the conjunction above has been established.
    if mark.enable_precondition is not True:
        raise AcquisitionError(
            f"the capture {what} does not state the enable precondition after its own "
            "conjunction check: nothing was pressed"
        )
    return mark


def _post_entry_evidence(
    report: ChannelsRead,
    *,
    target: WindowTarget,
    popup_hwnd: int,
    directory: Path,
) -> tuple[Literal["VISUAL_ENABLED", "UNKNOWN"], str, tuple[str, str] | None, str]:
    """The post-press mode from one fresh entry pair, or ``UNKNOWN`` and why.

    This is the only place the enabled post state is stated, and it states it from pixels and
    identity facts, never from the fact that this command pressed:

    * the pair must be a fresh ``entry_no_numeric`` capture whose ``status`` is ``ok`` and whose
      two frames agreed, so a torn or repainting popup states nothing;
    * the mode attribution must be the exact ``MULTIPLEXER_ON_ENTRY`` template match painting
      ``Desable multiplexer`` — an absent, altered, translated or unrecognised line is not
      enabled;
    * both guards must name the **original** bound window and the **original** popup panel, so a
      different panel's entry line is never read as this popup's;
    * the run directory must be the one this invocation claimed under its own capture root, and
      the digests must be two re-derived 64-character pair digests.

    The clipped entry popup structurally has no rollover row, so ``post_rolling`` stays unknown;
    a ``ready`` strip is not consulted and implies no mode.
    """

    def unknown(reason: str, claim: str = "") -> tuple:
        return ("UNKNOWN", claim, None, reason)

    capture = report.capture
    if capture is None:
        return unknown(
            "the clipped entry was reported but this invocation holds no fresh capture for it: "
            "a retained pair is history, so the mode after the press is unknown and nothing is "
            "retried"
        )
    claim = capture.directory or ""
    if capture.capture_kind != CAPTURE_ENTRY_NO_NUMERIC:
        return unknown(
            f"the post-press capture is {capture.capture_kind!r} where the clipped entry's "
            "contract is required: the settings and entry contracts are never interchanged",
            claim,
        )
    if capture.status != "ok":
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok"
        return unknown(
            f"the post-press entry capture is not ok ({reasons}): the enabled mode is not "
            "claimed and nothing is retried",
            claim,
        )
    guards = capture.guards
    if not guards.consistent or guards.after is None:
        return unknown(
            "the post-press entry pair's window guards do not agree across the capture: "
            + ("; ".join(guards.failures) or "no closing guard"),
            claim,
        )
    for guard in (guards.before, guards.after):
        if guard.hwnd != target.hwnd:
            return unknown(
                f"the post-press capture's {guard.label} guard resolved hwnd {guard.hwnd} "
                f"where the original binding is {target.hwnd}: identity drift, so no mode is "
                "claimed",
                claim,
            )
        if guard.popup_hwnd != popup_hwnd:
            return unknown(
                f"the post-press capture's {guard.label} guard resolved popup hwnd "
                f"{guard.popup_hwnd} where the licensed popup is {popup_hwnd}: a different "
                "panel's entry line states nothing about this popup",
                claim,
            )
    if claim and Path(claim).parent.resolve() != directory.resolve():
        return unknown(
            f"the post-press pair was claimed at {claim!r}, outside this invocation's capture "
            f"root {str(directory)!r}: a pair from elsewhere is not this press's evidence",
            claim,
        )
    mark = capture.visual_mode_mark
    if mark is None:
        return unknown(
            "the post-press entry capture carries no mode attribution for the measured clipped "
            "shape, so the enabled mode is unknown",
            claim,
        )
    if (
        mark.surface != mode_marks.MULTIPLEXER_ON_ENTRY
        or mark.label != "DESABLE_MULTIPLEXER"
        or mark.mode != "VISUAL_ENABLED"
    ):
        return unknown(
            f"the post-press pair reads surface={mark.surface!r} label={mark.label!r} "
            f"mode={mark.mode!r} where the measured ``Desable multiplexer`` entry is required: "
            "an absent, altered, wrong-sized or otherwise unattributed entry states no enabled "
            "mode",
            claim,
        )
    if (
        mark.recognition != "EXACT_TEMPLATE_MATCH"
        or mark.frames_agreed is not True
        or mark.acquisition_context != _FRESH_CONTEXT
        or mark.freshness != "live_bracketed"
        or mark.integrity != _FRESH_INTEGRITY
    ):
        return unknown(
            "the post-press entry pair is not a fresh live-bracketed digest-verified agreement "
            f"(recognition={mark.recognition!r}, agreed={mark.frames_agreed!r}, "
            f"context={mark.acquisition_context!r}, freshness={mark.freshness!r}, "
            f"integrity={mark.integrity!r})",
            claim,
        )
    digests = mark.frame_digests
    if digests is None or len(digests) != 2 or any(len(item) != 64 for item in digests):
        return unknown(
            "the post-press entry pair carries no two genuine frame digests, so the enabled "
            "mode is not claimed",
            claim,
        )
    return "VISUAL_ENABLED", claim, (digests[0], digests[1]), ""


# ---------------------------------------------------------------------------------------------
# the narrow action boundary
# ---------------------------------------------------------------------------------------------


@dataclass
class _Boundary:
    """What the boundary immediately before the press found — clauses, or a licence.

    A refusal still carries whatever the final capture produced (its run directory, its digests
    and its attribution), because that pair must be retained even when it licenses no press.
    """

    clauses: tuple[str, ...] = ()
    capture_dir: str = ""
    mark: mode_marks.ModeMarkAttribution | None = None
    rect: tuple[int, int, int, int] | None = None
    seconds: float | None = None


def _final_boundary(
    live,
    target: WindowTarget,
    *,
    capture_fn: Callable[..., ChannelsRead],
    directory: Path,
    enumerate_fn: Callable[[], Sequence[int]],
    class_name: str,
    windows: Sequence[int],
    toggle_hwnd: int,
    popup_hwnd: int,
    clock: Callable[[], float],
    max_seconds: float | None,
) -> _Boundary:
    """Ready, no overlay, one live binding, and a **new** capture — immediately before the press.

    Every check here runs *after* the durable claim, so a refusal leaves a record that says what
    was refused and owes no restoration. Nothing is posted on any path.
    """
    out = _Boundary()
    started = clock()
    try:
        fresh_windows = tuple(enumerate_fn())
    except Exception as exc:  # noqa: BLE001 - an unreadable window set is a refusal
        out.clauses = (f"the window set could not be enumerated: {_reason(exc)}",)
        out.seconds = clock() - started
        return out
    if fresh_windows != tuple(windows):
        changed = f"{list(windows)} -> {list(fresh_windows)}"
        out.clauses = (
            f"the window set changed between the decision and the press ({changed})",
        )
        out.seconds = clock() - started
        return out
    clauses, _state = screen_clauses(
        live, target, fresh_windows, class_name=class_name, strip=_strip_not_recording
    )
    if clauses:
        out.clauses = clauses
        out.seconds = clock() - started
        return out
    live.verify_bound_target(target)
    try:
        report = capture_fn(live, target=target, capture_dir=directory)
    except Exception as exc:  # noqa: BLE001 - a failed final capture refuses, it never retries
        out.clauses = (f"the final capture could not be taken: {_reason(exc)}",)
        out.seconds = clock() - started
        return out
    capture = report.capture
    if capture is not None:
        out.capture_dir = capture.directory or str(directory)
        out.mark = capture.visual_mode_mark
    try:
        target_toggle = bind_enable_toggle(report)
        if target_toggle.hwnd is None or int(target_toggle.hwnd) != int(toggle_hwnd):
            raise AcquisitionError(
                f"the Enable toggle or its popup changed under the read "
                f"({toggle_hwnd}/{popup_hwnd} -> {target_toggle.hwnd}/"
                f"{None if report.popup is None else report.popup.hwnd}): nothing was pressed"
            )
        out.rect = target_toggle.rect
        out.mark = _verified_capture(report, what="at the action boundary")
    except AcquisitionError as exc:
        out.clauses = (str(exc),)
        out.seconds = clock() - started
        return out
    out.seconds = clock() - started
    if max_seconds is not None and out.seconds > max_seconds:
        took = f"{out.seconds:.3f}"
        allowed = f"{max_seconds:.3f}"
        clause = (
            f"the boundary took {took} s where the caller allowed {allowed} s between the "
            + "licensing capture and the press"
        )
        out.clauses = (clause,)
    return out


# ---------------------------------------------------------------------------------------------
# the workflow
# ---------------------------------------------------------------------------------------------


def acquire_enable_multiplexed(
    *,
    capture_dir: Path | str,
    trial_record: Path | str,
    bound_target: WindowTarget | None = None,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    stamp: Callable[[], str] = _now_stamp,
    clock: Callable[[], float] = time.monotonic,
    max_boundary_seconds: float | None = None,
    read_popup: Callable[..., ChannelsRead] | None = None,
    capture_popup: Callable[..., ChannelsRead] | None = None,
    notes: list[str] | None = None,
) -> EnableMultiplexedResult:
    """Press the Enable toggle once from a fresh verified capture, and say what stays unknown."""
    directory = Path(capture_dir)
    record_file = trial_record_file(trial_record, name=TRIAL_FILE_NAME)
    sink = notes if notes is not None else []
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(note_sink=sink.append, allow_real_input=False)
    )
    read_fn = read_popup if read_popup is not None else read_channels
    capture_fn = capture_popup if capture_popup is not None else read_channels
    enumerate_fn: Callable[[], Sequence[int]] = (
        enumerate_windows
        if enumerate_windows is not None
        else (lambda: tuple(visible_main_windows(class_name)))
    )

    windows = tuple(enumerate_fn())
    if len(windows) != 1:
        raise AcquisitionError(
            f"{len(windows)} visible {class_name} window(s) are up {list(windows)}: exactly one "
            "instrument must be running, and this command does not choose between copies"
        )
    target = resolve_bound_target(
        live, windows, bound_target=bound_target, class_name=class_name
    )
    clauses, _state = screen_clauses(
        live, target, windows, class_name=class_name, strip=_strip_not_recording
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))

    # (1) the decision capture: what licenses taking on the obligation at all.
    initial = capture_fn(live, target=target, capture_dir=directory)
    toggle = enable_toggle(initial)
    popup_hwnd = initial.popup.hwnd if initial.popup is not None else None
    if popup_hwnd is None or toggle.hwnd is None:
        raise AcquisitionError(
            "the popup or the Enable toggle resolved no handle: nothing was pressed"
        )
    old = _verified_capture(initial, what="before the press")
    toggle_hwnd = int(toggle.hwnd)
    popup_hwnd = int(popup_hwnd)

    restoration = (
        (
            "read the mode back from a freshly reopened Channels popup: this command cannot "
            "infer that the application is enabled, and the enabled interval is unverified"
        ),
        (
            "if the operator wants the old mode back, the Disable multiplexer entry is a "
            "separate operator gesture — this command never presses Disable, Record, Stop or "
            "Clear"
        ),
    )
    obligation = {
        "phase": "obligation",
        "command": "enable-multiplexed",
        "written_at": stamp(),
        "bound_target": target.model_dump(),
        "capture_dir": str(directory),
        "popup_hwnd": popup_hwnd,
        "toggle_hwnd": toggle_hwnd,
        "toggle_rect": list(toggle.rect or ()),
        "target_attribution": toggle.attribution.caption,
        "target_provenance": toggle.attribution.provenance,
        "signature": list(initial.signature),
        # The decision pair — evidence for taking the obligation, never the press's licence.
        "old_label": old.label,
        "old_mode": old.mode,
        "old_rolling": old.rolling,
        "old_mark": old.mark,
        "old_context": old.acquisition_context,
        "old_freshness": old.freshness,
        "old_integrity": old.integrity,
        "old_frame_digests": list(old.frame_digests or ()),
        "old_capture_dir": str(
            initial.capture.directory if initial.capture is not None else directory
        ),
        # The final licensing pair, written once the boundary has run — empty until then.
        "final_label": "",
        "final_mode": "",
        "final_rolling": "",
        "final_context": "",
        "final_integrity": "",
        "final_frame_digests": [],
        "final_capture_dir": "",
        "boundary_seconds": None,
        "boundary_error": "",
        "operator_hands_off": HANDS_OFF,
        "os_race": OS_RACE,
        "relay_warning": RELAY_WARNING,
        "scope": "one held press on the Enable toggle; nothing else",
        "presses": 0,
        "press": "not_attempted",
        "posted": "not_attempted",
        "obligation_open": False,
        "restoration_owed": list(restoration),
    }
    # (2) the durable claim, and only then the narrow action boundary.
    claim_trial_record(record_file, obligation)

    boundary = _final_boundary(
        live,
        target,
        capture_fn=capture_fn,
        directory=directory,
        enumerate_fn=enumerate_fn,
        class_name=class_name,
        windows=windows,
        toggle_hwnd=toggle_hwnd,
        popup_hwnd=popup_hwnd,
        clock=clock,
        max_seconds=max_boundary_seconds,
    )
    final = boundary.mark
    if boundary.clauses:
        reason = "; ".join(boundary.clauses)
        refused = dict(obligation)
        refused.update(
            {
                "phase": "preflight_refused",
                "completed_at": stamp(),
                "stage": "preflight_refused",
                "presses": 0,
                "press": "not_attempted",
                "posted": "not_attempted",
                "press_error": "",
                "boundary_error": reason,
                "boundary_seconds": boundary.seconds,
                "final_label": "" if final is None else final.label,
                "final_mode": "" if final is None else final.mode,
                "final_rolling": "" if final is None else final.rolling,
                "final_context": "" if final is None else final.acquisition_context,
                "final_integrity": "" if final is None else final.integrity,
                "final_frame_digests": list(
                    ()
                    if final is None or final.frame_digests is None
                    else final.frame_digests
                ),
                "final_capture_dir": boundary.capture_dir,
                "restoration_owed": [],
                "obligation_open": False,
            }
        )
        record_error = update_trial_record(record_file, refused)
        raise AcquisitionError(
            f"{reason} — nothing was pressed; the durable obligation at {record_file} records "
            "phase preflight_refused, press not_attempted and no restoration owed"
            + (f" (its final rewrite failed: {record_error})" if record_error else "")
        )

    press_error = ""
    try:
        live.press_mode_toggle(
            target=target,
            popup_hwnd=popup_hwnd,
            toggle_hwnd=toggle_hwnd,
            toggle_rect=boundary.rect,
        )
    except Exception as exc:  # noqa: BLE001 - a raised press is a fact, not a retry
        press_error = (
            f"the press raised {type(exc).__name__}: {_reason(exc)}; whether any message reached "
            "the control is unknown — this is not a report that nothing was pressed"
        )
    presses, press_state, posted = 1, "attempted", "unknown"
    stage = EnableStage.PRESS_RAISED if press_error else EnableStage.PRESSED

    # The post state is read, and one fresh pair is taken **only** when that read resolves the
    # clipped one-entry popup. An enabled mode is never inferred from the press, a ready strip or
    # any other surface, and nothing is retried when the entry is absent.
    post_error = ""
    post_surface = "UNKNOWN"
    post_mode: Literal["VISUAL_ENABLED", "UNKNOWN"] = "UNKNOWN"
    post_rolling = "UNKNOWN"
    post_capture_dir = ""
    post_capture_kind = ""
    post_frame_digests: tuple[str, str] | None = None
    try:
        post = read_fn(live, target=target)
    except Exception as exc:  # noqa: BLE001 - an unreadable screen is a fact
        post_error = f"the screen could not be read after the press: {_reason(exc)}"
    else:
        post_surface = post.surface.value
        if post.surface is ChannelsSurface.MULTIPLEXER_ON_ENTRY:
            try:
                captured = capture_fn(live, target=target, capture_dir=directory)
            except Exception as exc:  # noqa: BLE001 - a failed capture is not a retry
                post_error = (
                    "the clipped entry was visible after the press, but the fresh post-press "
                    f"capture could not be taken ({_reason(exc)}): the enabled mode is unknown "
                    "and nothing is retried"
                )
            else:
                (
                    post_mode,
                    post_capture_dir,
                    post_frame_digests,
                    post_error,
                ) = _post_entry_evidence(
                    captured,
                    target=target,
                    popup_hwnd=popup_hwnd,
                    directory=directory,
                )
                if captured.capture is not None:
                    post_capture_kind = captured.capture.capture_kind
        else:
            post_error = (
                f"the post-press read resolved surface {post_surface!r}, not the clipped "
                "one-entry popup: enabling is not inferred from the press, from a ready strip "
                "or from any other surface, so the mode after the press is UNKNOWN and nothing "
                "is retried; reopen Channels by hand to read it, or use Disable multiplexer "
                "when asked. " + RELAY_WARNING
            )

    payload = dict(obligation)
    payload.update(
        {
            "phase": "after",
            "completed_at": stamp(),
            "stage": stage.value,
            "presses": presses,
            "press": press_state,
            "posted": posted,
            "press_evidence": PRESS_EVIDENCE,
            "post_surface": post_surface,
            "post_mode": post_mode,
            "post_rolling": post_rolling,
            "post_capture_dir": post_capture_dir,
            "post_capture_kind": post_capture_kind,
            "post_frame_digests": list(post_frame_digests or ()),
            "press_error": press_error,
            "post_error": post_error,
            "final_label": final.label if final is not None else "",
            "final_mode": final.mode if final is not None else "",
            "final_rolling": final.rolling if final is not None else "",
            "final_context": final.acquisition_context if final is not None else "",
            "final_integrity": final.integrity if final is not None else "",
            "final_frame_digests": list(
                ()
                if final is None or final.frame_digests is None
                else final.frame_digests
            ),
            "final_capture_dir": boundary.capture_dir,
            "boundary_seconds": boundary.seconds,
            "restoration_owed": list(restoration),
            "obligation_open": True,
        }
    )
    record_error = update_trial_record(record_file, payload)
    observed = [
        f"read:popup={popup_hwnd}",
        f"read:enable_toggle={toggle_hwnd}",
        f"read:enable_rect={boundary.rect!r}",
        f"read:mode={old.mode}",
        f"read:rolling={old.rolling}",
        f"read:context={old.acquisition_context}/{old.integrity}",
        (
            f"boundary:final={None if final is None else final.mode}/"
            f"{None if final is None else final.rolling}"
        ),
        f"boundary:seconds={boundary.seconds!r}",
        f"post:surface={post_surface}",
        f"post:mode={post_mode}",
        f"post:capture={post_capture_dir or None}",
    ]
    return EnableMultiplexedResult(
        stage=stage,
        bound_target=target,
        popup_hwnd=popup_hwnd,
        target_hwnd=toggle_hwnd,
        target_rect=boundary.rect,
        target_attribution=toggle.attribution.caption,
        target_provenance=toggle.attribution.provenance,
        signature=tuple(initial.signature),
        capture_dir=str(directory),
        old_label=old.label,
        old_mode=old.mode,
        old_rolling=old.rolling,
        old_context=old.acquisition_context,
        old_integrity=old.integrity,
        old_frame_digests=old.frame_digests,
        final_label="" if final is None else final.label,
        final_mode="" if final is None else final.mode,
        final_rolling="" if final is None else final.rolling,
        final_context="" if final is None else final.acquisition_context,
        final_integrity="" if final is None else final.integrity,
        final_frame_digests=None if final is None else final.frame_digests,
        final_capture_dir=boundary.capture_dir,
        boundary_seconds=boundary.seconds,
        post_surface=post_surface,
        post_mode=post_mode,
        post_rolling=post_rolling,
        post_capture_dir=post_capture_dir,
        post_capture_kind=post_capture_kind,
        post_frame_digests=post_frame_digests,
        post_error=post_error,
        presses=presses,
        press=press_state,
        posted=posted,
        press_error=press_error,
        restoration_owed=restoration,
        trial_record=record_file,
        trial_record_phase="obligation" if record_error else "after",
        trial_record_error=record_error,
        observed=tuple(observed),
        notes=tuple(
            item
            for item in (
                *getattr(live, "warnings", ()),
                HANDS_OFF,
                press_error,
                post_error,
            )
            if item
        ),
    )
