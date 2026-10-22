"""One guarded press on the ``Channels`` popup's **Roll over the channels** toggle.

This is the setter for the rolling fact, and it is deliberately *not* the mode-entry command:
``Enable multiplexer`` is a different row and a different control, and
:meth:`…udop.recording.RecordingSurface.press_rollover_toggle` refuses any handle the rollover
row's measured band does not own. Nothing here presses ``Enable``, ``Record``, ``Disable``,
``Stop`` or ``Clear``.

Set once, from a closed screen
-----------------------------
The popup is **this command's** to open: it starts with a read that must resolve ``ABSENT``, opens
with the one measured ``Channels`` hover, presses at most one toggle, and closes the popup it
opened in a ``finally``. An already-open popup is refused by default (``adopt_open=False``), the
same policy as ``channels-inspect``, so the command never takes over the operator's popup; a
caller that passes ``adopt_open=True`` keeps the library's rule that an adopted popup is left open
unless ``close_adopted=True`` is also passed.

The literal vocabulary
----------------------
``--requested`` is the state to establish, ``--expect`` the state the fresh decision capture must
prove first, and ``--baseline`` the trial's declared original state. All three are literal
``on``/``off`` values, validated before any gesture, and none is inferred from a capture: the
baseline the record carries is the caller's string, never the state the popup happened to show.
``requested == expect`` is a **NOOP**: zero presses, no obligation and no trial record, but the
command still closes the popup it opened. ``requested != baseline`` states the restoration the
operator still owes **whether or not anything was pressed** — a no-op that leaves the declared
baseline unreached owes exactly the same restoration, it just does not write it down. A restore
invocation (``--requested off --baseline off``) keeps that original baseline as its own
declaration and writes no automatic second press.

Who closes what
---------------
The close is a contract, not a courtesy: a popup this command opened must be observed ``ABSENT``
before the invocation is settled, and so must an adopted popup the caller asked to close
(``close_adopted=True``). Only the library's own adopt rule exempts one — an adopted popup with
``close_adopted=False`` is left open **by policy** and says so. The verdict is typed
(:class:`PopupClosure`) and built from ``opened.adopted``/``opened.outcome``, never from "a handle
was returned", so a press that cannot prove its close is never reported as settled.

Ordering, and what it does not buy
----------------------------------
1. a **decision** capture — a fresh, live-bracketed, digest-verified full settings pair that proves
   ``VISUAL_DISABLED`` (the multiplexer is off) and the rollover mark reading ``--expect``;
2. the durable **pending** obligation (``O_EXCL`` + ``fsync``) — the claim, before the boundary;
3. a **fresh final licensing** capture at the narrow boundary, after that write and immediately
   before the press, re-resolving the same window set, the same popup, the same measured settings
   signature, the same toggle handle **and** the same popup-relative rect;
4. **one** held press, only when the requested state differs from the licensed one;
5. a fresh post capture while the full settings popup is still up;
6. the owned close, in a ``finally``; the record is rewritten after it.

``posted`` stays ``"unknown"`` after a press: attempted is not delivered, and a raised press is
reported as a raised press, never as "nothing happened". A boundary refusal happens *after* the
hover that opened the popup, so it reports zero **presses** while its ``hover_attempted`` says a
gesture was already made. If the durable rewrite after the press fails, the pending record stays
on disk with ``press: not_attempted`` **as of that write** and must not be read as "no action".

No cap is invented: only a caller that passes ``max_boundary_seconds`` gets an enforced elapsed
limit, and then a refusal with zero presses. A cap must be a finite, strictly positive number and
``settle_s`` a finite, non-negative one; both are validated **before** the first read, hover,
claim or press, because a bound that is ``NaN`` or negative either silently disables itself
(every comparison with ``NaN`` is false) or clamps to a delay the caller never asked for.

Live status: one supervised OFF→ON→OFF round trip on the measured build (each invocation one
press, three capture pairs, post state proven, popup closed ``ABSENT``), with every refusal,
adopt, NOOP, raised-press and failed-rewrite path established offline only. No unattended or
repeated cycling has been exercised, and no other build, layout or geometry is claimed. The
pixel rules re-use the committed rolling-ON/OFF fixtures and the measured row band.
"""

from __future__ import annotations

import math
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
from udv_echo_process.acquire.channels_capture import CaptureEvidence
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.channels_repeat import (
    _strip_not_recording,
    claim_trial_record,
    trial_record_file,
    update_trial_record,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.store_completed import screen_clauses
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import (
    READABLE_SURFACES,
    ChannelsRead,
    ChannelsSurface,
    bind_rollover_toggle,
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ROLLOVER_TRIAL_FILE_NAME",
    "PopupClosure",
    "Rolling",
    "SetRolloverResult",
    "SetRolloverStage",
    "acquire_set_rollover",
]

ROLLOVER_TRIAL_FILE_NAME = "set-rollover-trial.json"

_FRESH_CONTEXT = "live-bracketed"
_FRESH_INTEGRITY = "capture-digest-verified"

PRESS_EVIDENCE = (
    "one press attempt with the strip's posted held-press recipe (WM_LBUTTONDOWN, hold, "
    "WM_LBUTTONUP) on the Roll over the channels toggle's own handle, re-resolved — handle, "
    "caption, popup and popup-relative rect — immediately before the press; never BM_CLICK, "
    "never a screen coordinate and never the Enable toggle. Whether the message was delivered "
    "is unknown, so no field here claims a post"
)

HANDS_OFF = (
    "the operator must keep hands off the keyboard, mouse and instrument for the whole command: "
    "the popup must not move or be clicked, and no channel may change between the licensing "
    "capture and the posted press. The command states this requirement; it cannot enforce it"
)

OS_RACE = (
    "an operating-system race remains between the last read and the posted message: the "
    "application can move, repaint, disable or close that control in between, so the capture "
    "states the moment before the press and never a lock, and the post state stays a fresh read"
)

BOUNDARY_DIAGNOSTIC = (
    "boundary_seconds is a monotonic measurement of the licensing capture and its checks taken "
    "immediately before the press: a diagnostic, not a security timeout and not an atomicity "
    "claim. No cap applies unless the caller passed max_boundary_seconds"
)


class Rolling(str, Enum):
    """The rolling fact's two literal values — the command's whole vocabulary for it."""

    ON = "on"
    OFF = "off"


class SetRolloverStage(str, Enum):
    """How far one invocation got — each member says what is established, not what was tried."""

    NOOP = "noop"
    PRESSED = "pressed"
    PRESS_RAISED = "press_raised"


class PopupClosure(str, Enum):
    """What this invocation established about the popup it had to close — a typed verdict.

    ``owned`` comes from :attr:`…udop.parameters.ChannelsOpen.adopted` and ``outcome``, never from
    "a handle came back": a returned handle is a hover that was attempted, not a popup that exists
    or a close that landed. ``ADOPTED_LEFT_OPEN`` is the library's **policy** answer for a popup the
    caller adopted without asking to close it, and is the only non-closed member that settles.
    """

    OWNED_CLOSED = "owned_closed"
    OWNED_LEFT_OPEN = "owned_left_open"
    ADOPTED_CLOSED = "adopted_closed"
    ADOPTED_UNCLOSED = "adopted_unclosed"
    ADOPTED_LEFT_OPEN = "adopted_left_open"

    @property
    def settled(self) -> bool:
        """Whether the popup is provably gone, or left open by the library's own adopt policy."""
        return self in (
            PopupClosure.OWNED_CLOSED,
            PopupClosure.ADOPTED_CLOSED,
            PopupClosure.ADOPTED_LEFT_OPEN,
        )


class SetRolloverResult(ValueModel):
    """One setter invocation, with the capture evidence nested rather than copied per stage.

    ``decision`` is the capture that licensed taking the obligation, ``final`` the fresh pair
    taken at the boundary immediately before the press, and ``post`` the fresh pair read after it.
    Each is the reader's own :class:`CaptureEvidence`, so its mark, frames, guards and digests are
    one object and are never restated as parallel ``old_*``/``final_*`` fields.
    """

    stage: SetRolloverStage
    requested: Rolling
    expect: Rolling
    baseline: Rolling
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    target_hwnd: int | None = None
    #: The rects stay two separate facts: ``decision`` is the one the obligation was taken on,
    #: ``boundary`` the one re-resolved and licensed immediately before the press (and therefore
    #: the one the press used). Neither is written over the other.
    decision_rect: tuple[int, int, int, int] | None = None
    boundary_rect: tuple[int, int, int, int] | None = None
    decision: CaptureEvidence | None = None
    final: CaptureEvidence | None = None
    post: CaptureEvidence | None = None
    post_rolling: Literal["ON_PROVEN", "OFF_PROVEN", "UNKNOWN"] = "UNKNOWN"
    post_error: str = ""
    decision_capture_dir: str = ""
    final_capture_dir: str = ""
    post_capture_dir: str = ""
    boundary_seconds: float | None = None
    boundary_evidence: str = BOUNDARY_DIAGNOSTIC
    presses: int = 0
    press: Literal["not_attempted", "attempted"] = "not_attempted"
    posted: Literal["not_attempted", "unknown"] = "not_attempted"
    press_error: str = ""
    press_evidence: str = PRESS_EVIDENCE
    hover_attempted: bool = False
    opened: ChannelsOpen | None = None
    closed: ChannelsDismissal | None = None
    popup_left_open: bool | None = None
    popup_closure: PopupClosure | None = None
    restoration_owed: tuple[str, ...] = ()
    trial_record: Path | None = None
    trial_record_phase: Literal["", "pending", "refused", "after"] = ""
    trial_record_error: str = ""
    observed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        return (
            f"set rollover {self.requested.value} (stage {self.stage.value}, "
            f"expect {self.expect.value}, baseline {self.baseline.value}, presses "
            f"{self.presses}, posted {self.posted}, post rolling {self.post_rolling})"
        )


def _now_stamp() -> str:
    return datetime.now(tz=UTC).astimezone().isoformat()


def _reason(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__


def _rolling(value: str | Rolling) -> Rolling:
    """The literal ``on``/``off``, or a refusal — never a guess from a capture."""
    if isinstance(value, Rolling):
        return value
    try:
        return Rolling(str(value).strip().lower())
    except ValueError as exc:
        raise AcquisitionError(
            f"{value!r} is not a rolling state: only the literal 'on' or 'off' is accepted, and "
            "no value is inferred from the screen"
        ) from exc


def _timing(
    value: object, *, name: str, positive: bool, optional: bool = False
) -> float | None:
    """A caller's timing bound, or a refusal — **before** anything is read, hovered or pressed.

    ``NaN`` and ``inf`` are the reason this exists: ``elapsed > NaN`` and ``elapsed > inf`` are
    both false, so a non-finite cap silently licenses every elapsed boundary, and
    ``max(0.0, NaN)`` hands an unhovered wait to the open/close poll. ``bool`` is refused because
    it is an ``int`` in Python and ``True`` is not a duration.
    """
    if value is None:
        if optional:
            return None
        raise AcquisitionError(f"{name} is required and must be a finite number")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AcquisitionError(
            f"{name} is {value!r} ({type(value).__name__}), not a number: it must be a finite "
            f"{'positive' if positive else 'non-negative'} number of seconds, and nothing was "
            "read, hovered, claimed or pressed"
        )
    number = float(value)
    if not math.isfinite(number):
        raise AcquisitionError(
            f"{name} is {value!r}, which is not finite: a non-finite bound either disables "
            "itself (every comparison with NaN is false) or is meaningless, so nothing was "
            "read, hovered, claimed or pressed"
        )
    if positive and number <= 0:
        raise AcquisitionError(
            f"{name} is {number!r}, not a positive number of seconds: a cap of zero or less "
            "would refuse every boundary, so nothing was read, hovered, claimed or pressed"
        )
    if not positive and number < 0:
        raise AcquisitionError(
            f"{name} is {number!r}, not a non-negative number of seconds: nothing was read, "
            "hovered, claimed or pressed"
        )
    return number


def _mark(report: ChannelsRead) -> mode_marks.ModeMarkAttribution:
    capture = report.capture
    if capture is None:
        raise AcquisitionError(
            "no capture was taken: the rolling setter needs a fresh same-invocation full "
            "settings capture, never a retained directory and never an attribution alone"
        )
    mark = capture.visual_mode_mark
    if mark is None:
        raise AcquisitionError(
            "the capture carries no mode attribution for the measured settings shape"
        )
    return mark


def _verified(
    report: ChannelsRead, *, expected: Rolling, what: str
) -> tuple[CaptureEvidence, mode_marks.ModeMarkAttribution]:
    """The fresh capture's evidence, or a refusal naming the clause that failed."""
    capture = report.capture
    if capture is None:
        raise AcquisitionError(
            f"no capture was taken {what}: a rolling press needs a fresh same-invocation "
            "capture, never a retained directory and never an attribution alone"
        )
    if capture.status != "ok":
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok"
        raise AcquisitionError(f"the capture {what} is not ok ({reasons})")
    mark = capture.visual_mode_mark
    if mark is None:
        raise AcquisitionError(
            f"the capture {what} carries no mode attribution for the measured settings shape"
        )
    if mark.surface != mode_marks.SETTINGS_FULL or mark.mode != "VISUAL_DISABLED":
        raise AcquisitionError(
            f"the capture {what} reads surface={mark.surface!r} mode={mark.mode!r} where the "
            "full settings popup with the multiplexer visually disabled is required: a rolling "
            "write is only made on that surface"
        )
    if mark.rolling != ("ON_PROVEN" if expected is Rolling.ON else "OFF_PROVEN"):
        raise AcquisitionError(
            f"the capture {what} proves rolling {mark.rolling!r} where --expect states "
            f"{expected.value!r}: the expectation and the pixels disagree, so nothing is pressed"
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
            "precondition"
        )
    digests = mark.frame_digests
    if (
        digests is None
        or len(digests) != 2
        or any(len(digest) != 64 for digest in digests)
    ):
        raise AcquisitionError(
            f"the capture {what} carries no two genuine frame digests"
        )
    guards = capture.guards
    if not guards.consistent or guards.after is None:
        raise AcquisitionError(
            f"the capture {what} has window guards that do not agree across the pair: "
            + ("; ".join(guards.failures) or "no closing guard")
        )
    for guard in (guards.before, guards.after):
        if guard.foreground is not True:
            raise AcquisitionError(
                f"the capture {what} has a {guard.label} guard stating foreground="
                f"{guard.foreground!r}: the instrument must be the foreground window when the "
                "pixels are read"
            )
    return capture, mark


@dataclass
class _Boundary:
    """What the boundary immediately before the press found — clauses, or a licence."""

    clauses: tuple[str, ...] = ()
    capture: CaptureEvidence | None = None
    mark: mode_marks.ModeMarkAttribution | None = None
    rect: tuple[int, int, int, int] | None = None
    seconds: float | None = None


def _final_boundary(
    live,
    target: WindowTarget,
    *,
    expected: Rolling,
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
    """A **new** capture and binding, re-resolved after the claim and immediately before the press."""
    out = _Boundary()
    started = clock()
    try:
        fresh_windows = tuple(enumerate_fn())
    except Exception as exc:  # noqa: BLE001 - an unreadable window set is a refusal
        out.clauses = (f"the window set could not be enumerated: {_reason(exc)}",)
        out.seconds = clock() - started
        return out
    if fresh_windows != tuple(windows):
        out.clauses = (
            (
                f"the window set changed between the decision and the press "
                f"({list(windows)} -> {list(fresh_windows)})"
            ),
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
    try:
        live.verify_bound_target(target)
        report = capture_fn(live, target=target, capture_dir=directory)
        out.capture, out.mark = _verified(
            report, expected=expected, what="at the action boundary"
        )
        toggle = bind_rollover_toggle(report)
        if toggle.hwnd is None or int(toggle.hwnd) != int(toggle_hwnd):
            raise AcquisitionError(
                f"the Roll over the channels toggle or its popup changed under the read "
                f"({toggle_hwnd}/{popup_hwnd} -> {toggle.hwnd}/"
                f"{None if report.popup is None else report.popup.hwnd}): nothing was pressed"
            )
        if report.popup is None or report.popup.hwnd is None:
            raise AcquisitionError(
                "the settings popup resolved no handle at the action boundary: nothing was pressed"
            )
        if int(report.popup.hwnd) != int(popup_hwnd):
            raise AcquisitionError(
                f"the settings popup reads as {report.popup.hwnd} where {popup_hwnd} licensed "
                "the obligation: a different panel, so nothing was pressed"
            )
        out.rect = toggle.rect
    except AcquisitionError as exc:
        out.clauses = (str(exc),)
        out.seconds = clock() - started
        return out
    out.seconds = clock() - started
    if max_seconds is not None and out.seconds > max_seconds:
        out.clauses = (
            (
                f"the boundary took {out.seconds:.3f} s where the caller allowed "
                f"{max_seconds:.3f} s between the licensing capture and the press"
            ),
        )
    return out


def _post_evidence(
    report: ChannelsRead, *, target: WindowTarget, popup_hwnd: int, requested: Rolling
) -> tuple[Literal["ON_PROVEN", "OFF_PROVEN", "UNKNOWN"], CaptureEvidence | None, str]:
    """The post-press rolling state from one fresh settings pair, or UNKNOWN and why."""
    capture = report.capture
    if capture is None:
        return (
            "UNKNOWN",
            None,
            (
                "the full settings popup was re-read but this invocation holds no fresh "
                "capture: the post state is unknown and nothing is retried"
            ),
        )
    if capture.status != "ok":
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok"
        return "UNKNOWN", capture, f"the post-press capture is not ok ({reasons})"
    guards = capture.guards
    if not guards.consistent or guards.after is None:
        return (
            "UNKNOWN",
            capture,
            "the post-press pair's window guards do not agree across the capture: "
            + ("; ".join(guards.failures) or "no closing guard"),
        )
    for guard in (guards.before, guards.after):
        if guard.hwnd != target.hwnd:
            return (
                "UNKNOWN",
                capture,
                (
                    f"the post-press capture's {guard.label} guard resolved hwnd "
                    f"{guard.hwnd} where the original binding is {target.hwnd}: identity drift"
                ),
            )
        if guard.popup_hwnd != popup_hwnd:
            return (
                "UNKNOWN",
                capture,
                (
                    f"the post-press capture's {guard.label} guard resolved popup hwnd "
                    f"{guard.popup_hwnd} where the licensed popup is {popup_hwnd}: a "
                    "different panel states nothing about this popup"
                ),
            )
        if guard.foreground is not True:
            return (
                "UNKNOWN",
                capture,
                (
                    f"the post-press capture's {guard.label} guard states foreground="
                    f"{guard.foreground!r}: the pixels are not attributable to the instrument"
                ),
            )
    mark = capture.visual_mode_mark
    if (
        mark is None
        or mark.surface != mode_marks.SETTINGS_FULL
        or mark.mode != "VISUAL_DISABLED"
        or mark.acquisition_context != _FRESH_CONTEXT
        or mark.freshness != "live_bracketed"
        or mark.integrity != _FRESH_INTEGRITY
        or mark.frames_agreed is not True
        or mark.recognition != "EXACT_TEMPLATE_MATCH"
    ):
        return (
            "UNKNOWN",
            capture,
            (
                "the post-press pair does not prove a fresh live-bracketed digest-verified "
                "disabled settings surface with a recognised rollover mark"
            ),
        )
    digests = mark.frame_digests
    if digests is None or len(digests) != 2 or any(len(item) != 64 for item in digests):
        return (
            "UNKNOWN",
            capture,
            "the post-press pair carries no two genuine frame digests",
        )
    wanted = "ON_PROVEN" if requested is Rolling.ON else "OFF_PROVEN"
    if mark.rolling != wanted:
        return (
            "UNKNOWN",
            capture,
            (
                f"the post-press pair proves rolling {mark.rolling!r} where {wanted} was "
                "requested: the press is not reported as having taken effect"
            ),
        )
    return wanted, capture, ""  # type: ignore[return-value]


def acquire_set_rollover(
    *,
    requested: str | Rolling,
    expect: str | Rolling,
    baseline: str | Rolling,
    capture_dir: Path | str,
    trial_record: Path | str,
    bound_target: WindowTarget | None = None,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    adopt_open: bool = False,
    close_adopted: bool = False,
    settle_s: float = 3.0,
    stamp: Callable[[], str] = _now_stamp,
    clock: Callable[[], float] = time.monotonic,
    max_boundary_seconds: float | None = None,
    read_popup: Callable[..., ChannelsRead] | None = None,
    capture_popup: Callable[..., ChannelsRead] | None = None,
    open_popup: Callable[..., ChannelsOpen] | None = None,
    close_popup: Callable[..., ChannelsDismissal] | None = None,
    notes: list[str] | None = None,
) -> SetRolloverResult:
    """Open, set the rolling toggle at most once, read back and close — in that order."""
    settle = _timing(settle_s, name="settle_s", positive=False)
    cap = _timing(
        max_boundary_seconds, name="max_boundary_seconds", positive=True, optional=True
    )
    wanted = _rolling(requested)
    expected = _rolling(expect)
    original = _rolling(baseline)
    directory = Path(capture_dir)
    record_file = trial_record_file(trial_record, name=ROLLOVER_TRIAL_FILE_NAME)
    sink = notes if notes is not None else []
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(note_sink=sink.append, allow_real_input=True)
    )
    read_fn = read_popup if read_popup is not None else read_channels
    capture_fn = capture_popup if capture_popup is not None else read_channels
    open_fn = (
        open_popup
        if open_popup is not None
        else (lambda **kwargs: live.open_channels_popup(**kwargs))
    )
    close_fn = (
        close_popup
        if close_popup is not None
        else (lambda **kwargs: live.dismiss_channels_popup(**kwargs))
    )
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

    first = read_fn(live, target=target)
    opened: ChannelsOpen | None = None
    if first.surface in READABLE_SURFACES and first.readable:
        if not adopt_open:
            raise AcquisitionError(
                "a readable Channels popup is already open and adopt_open=False: this command "
                "starts closed and does not take over a popup it did not open"
            )
        # A typed adoption, not a bare flag: ``adopted``/``outcome`` are what the close contract
        # and the CLI read, and ``point`` stays None because no hover of ours opened this popup.
        opened = ChannelsOpen(
            outcome=PopupOutcome.OPEN,
            surface=first.surface.value,
            readable=True,
            adopted=True,
            point=None,
            reads=1,
        )
    elif first.surface is not ChannelsSurface.ABSENT:
        raise AcquisitionError(
            f"the pre-open reading is {first.surface.value!r}, neither 'absent' nor a readable "
            "Channels popup: nothing is hovered and nothing else is dismissed"
        )
    else:
        opened = open_fn(
            target=target,
            read=read_fn,
            timeout_s=settle,
            adopt_open=False,
        )
        if opened.outcome is not PopupOutcome.OPEN:
            raise AcquisitionError(
                "the measured Channels stepped entry produced no readable popup: "
                f"{opened.clause or opened.surface}"
            )

    adopted = opened is not None and opened.adopted
    hover_attempted = opened is not None and opened.point is not None
    owned = (
        opened is not None
        and opened.outcome is PopupOutcome.OPEN
        and not opened.adopted
    )
    closeable = owned or (adopted and close_adopted)

    decision: CaptureEvidence | None = None
    final: CaptureEvidence | None = None
    post: CaptureEvidence | None = None
    post_rolling: Literal["ON_PROVEN", "OFF_PROVEN", "UNKNOWN"] = "UNKNOWN"
    post_error = ""
    boundary: _Boundary | None = None
    popup_hwnd: int | None = None
    toggle_hwnd: int | None = None
    presses = 0
    press_error = ""
    press_state: Literal["not_attempted", "attempted"] = "not_attempted"
    stage: SetRolloverStage | None = None
    record_phase: Literal["", "pending", "refused", "after"] = ""
    record_error = ""
    restoration: tuple[str, ...] = ()
    pending = False
    closed: ChannelsDismissal | None = None
    decision_rect: tuple[int, int, int, int] | None = None
    boundary_rect: tuple[int, int, int, int] | None = None

    try:
        decision_report = capture_fn(live, target=target, capture_dir=directory)
        decision_capture, _decision_mark = _verified(
            decision_report, expected=expected, what="before the press"
        )
        decision = decision_capture
        toggle = bind_rollover_toggle(decision_report)
        if toggle.hwnd is None or decision_report.popup is None:
            raise AcquisitionError(
                "the popup or the Roll over the channels toggle resolved no handle: nothing "
                "was pressed"
            )
        popup_hwnd = int(decision_report.popup.hwnd)
        toggle_hwnd = int(toggle.hwnd)
        decision_rect = toggle.rect

        # The restoration is the *declaration*, not the press: a NOOP that leaves the trial's
        # baseline unreached owes exactly the same undo, so it is derived before the branch.
        restoration = (
            (
                (
                    f"the trial's declared baseline is rolling {original.value}: restoring it "
                    "is a separate invocation with --requested "
                    f"{original.value} --baseline {original.value}; this invocation never "
                    "restores automatically and never presses twice"
                ),
            )
            if wanted is not original
            else ()
        )

        if wanted is expected:
            stage = SetRolloverStage.NOOP
        else:
            obligation = {
                "phase": "pending",
                "command": "set-rollover",
                "written_at": stamp(),
                "requested": wanted.value,
                "expect": expected.value,
                "baseline": original.value,
                "bound_target": target.model_dump(),
                "capture_dir": str(directory),
                "popup_hwnd": popup_hwnd,
                "toggle_hwnd": toggle_hwnd,
                "decision_toggle_rect": list(decision_rect or ()),
                "boundary_toggle_rect": None,
                "decision_capture_dir": decision_capture.directory or "",
                "decision_frame_digests": list(
                    (decision_capture.visual_mode_mark.frame_digests or ())
                    if decision_capture.visual_mode_mark is not None
                    else ()
                ),
                "decision_rolling": (
                    None
                    if decision_capture.visual_mode_mark is None
                    else decision_capture.visual_mode_mark.rolling
                ),
                "operator_hands_off": HANDS_OFF,
                "os_race": OS_RACE,
                "scope": "one held press on the Roll over the channels toggle; nothing else",
                "presses": 0,
                "press": "not_attempted",
                "hover_attempted": hover_attempted,
                "press_state_as_of": (
                    "not_attempted as of that write; a press may follow and is not reflected here"
                ),
                "posted": "not_attempted",
                "obligation_open": True,
                "restoration_owed": list(restoration),
            }
            claim_trial_record(record_file, obligation)
            pending = True
            record_phase = "pending"

            boundary = _final_boundary(
                live,
                target,
                expected=expected,
                capture_fn=capture_fn,
                directory=directory,
                enumerate_fn=enumerate_fn,
                class_name=class_name,
                windows=windows,
                toggle_hwnd=toggle_hwnd,
                popup_hwnd=popup_hwnd,
                clock=clock,
                max_seconds=cap,
            )
            if boundary.capture is not None:
                final = boundary.capture
            if boundary.rect is not None:
                # The boundary's re-resolved rect is what the press is licensed with; the
                # decision's rect stays its own fact, so neither overwrites the other's
                # provenance.
                boundary_rect = boundary.rect
            if boundary.clauses:
                reason = "; ".join(boundary.clauses)
                refused = dict(obligation)
                refused.update(
                    {
                        "phase": "refused",
                        "completed_at": stamp(),
                        "stage": "refused",
                        "boundary_error": reason,
                        "boundary_seconds": boundary.seconds,
                        "decision_toggle_rect": list(decision_rect or ()),
                        "boundary_toggle_rect": (
                            None if boundary_rect is None else list(boundary_rect)
                        ),
                        "restoration_owed": [],
                        "obligation_open": False,
                    }
                )
                record_error = update_trial_record(record_file, refused)
                record_phase = "refused"
                pending = False
                raise AcquisitionError(
                    f"{reason} — zero presses were posted; the hover that opened the popup had "
                    "already happened, so this is not a claim that no gesture was made"
                    + (
                        f" (the refused record's rewrite failed: {record_error})"
                        if record_error
                        else f" (recorded at {record_file})"
                    )
                )

            try:
                live.press_rollover_toggle(
                    target=target,
                    popup_hwnd=popup_hwnd,
                    toggle_hwnd=toggle_hwnd,
                    toggle_rect=boundary_rect
                    if boundary_rect is not None
                    else decision_rect,
                )
            except Exception as exc:  # noqa: BLE001 - a raised press is a fact, not a retry
                press_error = (
                    f"the press raised {type(exc).__name__}: {_reason(exc)}; whether any message "
                    "reached the control is unknown — this is not a report that nothing was "
                    "pressed"
                )
            presses, press_state, stage = 1, "attempted", SetRolloverStage.PRESSED
            if press_error:
                stage = SetRolloverStage.PRESS_RAISED

            try:
                after = read_fn(live, target=target)
            except Exception as exc:  # noqa: BLE001 - an unreadable screen is a fact
                post_error = (
                    f"the screen could not be read after the press: {_reason(exc)}"
                )
            else:
                if after.surface is ChannelsSurface.SETTINGS_POPUP:
                    try:
                        captured = capture_fn(
                            live, target=target, capture_dir=directory
                        )
                    except Exception as exc:  # noqa: BLE001 - a failed capture is not a retry
                        post_error = (
                            "the full settings popup was visible after the press, but the fresh "
                            f"post-press capture could not be taken ({_reason(exc)}): the rolling "
                            "state after the press is unknown and nothing is retried"
                        )
                    else:
                        post_rolling, post, post_error = _post_evidence(
                            captured,
                            target=target,
                            popup_hwnd=popup_hwnd,
                            requested=wanted,
                        )
                else:
                    post_error = (
                        f"the post-press read resolved surface {after.surface.value!r}, not the "
                        "full settings popup: the rolling state after the press is UNKNOWN, and "
                        "nothing is retried or inferred from the press"
                    )
    finally:
        if closeable:
            try:
                closed = close_fn(target=target, read=read_fn, timeout_s=settle)
            except Exception as exc:  # noqa: BLE001 - a failed close is its own fact
                sink.append(
                    f"the owned close raised {type(exc).__name__}: {_reason(exc)}"
                )
        if pending:
            payload = {
                "phase": "after" if presses else "noop",
                "command": "set-rollover",
                "completed_at": stamp(),
                "requested": wanted.value,
                "expect": expected.value,
                "baseline": original.value,
                "stage": None if stage is None else stage.value,
                "presses": presses,
                "press": press_state,
                "hover_attempted": hover_attempted,
                "posted": "unknown" if presses else "not_attempted",
                "press_error": press_error,
                "post_rolling": post_rolling,
                "post_error": post_error,
                "boundary_seconds": None if boundary is None else boundary.seconds,
                "decision_toggle_rect": list(decision_rect or ()),
                "boundary_toggle_rect": (
                    None if boundary_rect is None else list(boundary_rect)
                ),
                "restoration_owed": list(restoration),
                "obligation_open": False,
            }
            record_error = update_trial_record(record_file, payload)
            record_phase = "after" if not record_error else "pending"

    closed_absent = closed is not None and closed.outcome is DismissalOutcome.ABSENT
    if closed is not None:
        popup_left_open = not closed_absent
    elif not closeable:
        popup_left_open = True if adopted else None
    else:
        popup_left_open = None
    if closeable:
        if closed_absent:
            popup_closure = (
                PopupClosure.ADOPTED_CLOSED if adopted else PopupClosure.OWNED_CLOSED
            )
        else:
            popup_closure = (
                PopupClosure.ADOPTED_UNCLOSED
                if adopted
                else PopupClosure.OWNED_LEFT_OPEN
            )
    elif adopted:
        popup_closure = PopupClosure.ADOPTED_LEFT_OPEN
    else:
        popup_closure = None
    if closeable and closed is None:
        sink.append("the owned close was not attempted (an error escaped the workflow)")
    if closeable and closed is not None and not closed_absent:
        sink.append(
            "the close was not observed ABSENT (outcome "
            f"{closed.outcome.value!r}, last surface {closed.surface_after!r}); no second path "
            "is walked"
        )

    observed = [
        f"read:popup={popup_hwnd}",
        f"read:rollover_toggle={toggle_hwnd}",
        f"decision:rect={decision_rect!r}",
        f"boundary:rect={boundary_rect!r}",
        f"popup:closure={None if popup_closure is None else popup_closure.value}",
        f"decision:rolling={_mark_rolling(decision)}",
        f"boundary:final={_mark_rolling(final)}",
        f"boundary:seconds={None if boundary is None else boundary.seconds!r}",
        f"post:rolling={post_rolling}",
    ]
    return SetRolloverResult(
        stage=stage if stage is not None else SetRolloverStage.NOOP,
        requested=wanted,
        expect=expected,
        baseline=original,
        bound_target=target,
        popup_hwnd=popup_hwnd,
        target_hwnd=toggle_hwnd,
        decision_rect=decision_rect,
        boundary_rect=boundary_rect,
        decision=decision,
        final=final,
        post=post,
        post_rolling=post_rolling,
        post_error=post_error,
        decision_capture_dir="" if decision is None else (decision.directory or ""),
        final_capture_dir="" if final is None else (final.directory or ""),
        post_capture_dir="" if post is None else (post.directory or ""),
        boundary_seconds=None if boundary is None else boundary.seconds,
        presses=presses,
        press=press_state,
        posted="unknown" if presses else "not_attempted",
        press_error=press_error,
        hover_attempted=hover_attempted,
        opened=opened,
        closed=closed,
        popup_left_open=popup_left_open,
        popup_closure=popup_closure,
        restoration_owed=restoration,
        trial_record=record_file if record_phase else None,
        trial_record_phase=record_phase,
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


def _mark_rolling(evidence: CaptureEvidence | None) -> str:
    if evidence is None or evidence.visual_mode_mark is None:
        return "UNKNOWN"
    return evidence.visual_mode_mark.rolling
